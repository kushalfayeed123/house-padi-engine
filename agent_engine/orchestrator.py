
import logging
from typing import Annotated, TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field, create_model
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from data_layer.tool_validators import TOOL_VALIDATORS
from data_layer.permissions import check_permission

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: Optional[str]
    transaction_context: Dict[str, Any]
    agent_plan: Optional[List[Dict[str, Any]]]
    search_performed: bool


class PlanStep(BaseModel):
    step_id: int = Field(..., description="The ordered step number.")
    description: str = Field(..., description="What this agent should do next.")
    tool_name: Optional[str] = Field(None, description="The tool to use for this step.")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool call.")


# ---------------------------------------------------------------------------
# Auto-injection map
# Defines which tools need which field silently injected from transaction_context.
# Format:  tool_name → { arg_name: context_key }
# ---------------------------------------------------------------------------

AUTO_INJECT: Dict[str, Dict[str, str]] = {
    # Property
    "add_new_property_record": {"owner_id": "current_user_id"},

    # Tour
    "schedule_tour":           {"renter_id": "current_user_id"},

    # Applications
    "apply_for_property":      {"renter_id": "current_user_id"},
    "get_renter_applications": {"renter_id": "current_user_id"},
    "approve_application":     {"landlord_id": "current_user_id"},
    "deny_application":        {"landlord_id": "current_user_id"},

    # Leases
    "sign_lease":              {"signer_id": "current_user_id"},
    "get_active_leases":       {"user_id": "current_user_id"},

    # User profile
    "get_user_profile":        {"user_id": "current_user_id"},
    "update_user_profile":     {"user_id": "current_user_id"},
}

# Fields the LLM should never be allowed to supply (always system-injected)
PROTECTED_ARGS: Dict[str, set] = {
    tool: set(mapping.keys()) for tool, mapping in AUTO_INJECT.items()
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class MultiAgentOrchestrator:

    def __init__(
        self,
        registry: HousePadiAgentRegistry,
        llm_client: Any,
        oracle: OracleMCPServer,
        db_url: str,
    ):
        self.registry = registry
        self.llm = llm_client
        self.oracle = oracle
        self.db_url = db_url

        builder = self._build_workflow_graph()
        memory = MemorySaver()
        self.graph = builder.compile(checkpointer=memory)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_router_schema(self, agent_names: List[str]):
        return create_model(
            "RouterDecision",
            next_agent=(str, Field(description="The agent best suited to handle the request.")),
        )

    def _render_agent_memory(self, state: AgentState) -> str:
        active_agent = state.get("current_agent")
        transaction_context = state.get("transaction_context", {})
        if not isinstance(transaction_context, dict):
            transaction_context = {}
        memory = transaction_context.get("agent_memory", {})
        if not active_agent or not memory.get(active_agent):
            return ""
        entries = memory.get(active_agent, [])[-5:]
        return "\n".join([f"MEMORY: {entry}" for entry in entries])

    def _merge_transaction_context(
        self,
        state: AgentState,
        incoming: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Fix 3 — Merges incoming context (from the HTTP request) with the
        context already persisted in the checkpoint so that user_id and
        user_role are never lost across graph turns.
        """
        existing = dict(state.get("transaction_context") or {})
        # Incoming values win for top-level identity keys so a fresh
        # request can always reassert who the caller is.
        for key in ("current_user_id", "user_role"):
            if incoming.get(key) is not None:
                existing[key] = incoming[key]
        # Merge any other keys the caller passed without wiping agent_memory
        for k, v in incoming.items():
            if k not in existing:
                existing[k] = v
        return existing

    def _update_agent_memory(
        self,
        state: AgentState,
        agent_name: str,
        message: BaseMessage,
    ) -> Dict[str, Any]:
        transaction_context = dict(state.get("transaction_context", {}))
        memory = dict(transaction_context.get("agent_memory", {}))
        entry = getattr(message, "content", None)
        if entry:
            agent_history = list(memory.get(agent_name, []))
            agent_history.append(entry)
            memory[agent_name] = agent_history[-20:]
            transaction_context["agent_memory"] = memory
        return transaction_context

    def _format_plan_instructions(self, plan: Optional[List[Dict[str, Any]]]) -> str:
        if not plan:
            return "The agent may proceed with a single-step response."
        lines = []
        for step in plan:
            lines.append(
                f"{step.get('step_id')}. {step.get('description')}"
                + (f" Use tool: {step.get('tool_name')}" if step.get("tool_name") else "")
            )
        return "PLANNED STEPS:\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def router_node(self, state: AgentState):
        manifests = self.registry.get_all_manifests()
        agent_names = [m.name for m in manifests]
        active_agent = state.get("current_agent")

        agent_descriptions = "\n".join([f"- '{m.name}': {m.description}" for m in manifests])
        memory_text = self._render_agent_memory(state)

        context_instruction = (
            f"\n\nCURRENT CONTEXT: The conversation is currently assigned to '{active_agent}'.\n"
            "Only stay on that agent unless the user explicitly changes the topic or asks for a different service."
        ) if active_agent else "\n\nNo agent is currently active."

        system_instructions = (
            "You are the House Padi Orchestrator. Decide which registered agent should handle the user's latest request.\n"
            f"Available agents:\n{agent_descriptions}\n"
            "- 'end': Use this if the user is done or the request has been fully satisfied."
            + context_instruction
        )

        if memory_text:
            system_instructions += "\n\n" + memory_text

        dynamic_schema = self._get_router_schema(agent_names + ["end"])
        messages = [SystemMessage(content=system_instructions)] + state["messages"]
        decision = self.llm.with_structured_output(dynamic_schema).invoke(messages)

        logger.info(f"Routing decision: {decision.next_agent}")
        return {"current_agent": decision.next_agent}

    def _plan_node(self, state: AgentState) -> Dict[str, Any]:
        agent_name = state.get("current_agent")
        if not agent_name:
            return {"agent_plan": []}

        manifest = self.registry.resolve_agent(agent_name)
        allowed_tools = ", ".join(manifest.authorized_mcp_tools) or "none"

        system_instructions = (
            f"You are the planning agent for '{agent_name}'.\n"
            f"Create an ordered execution plan for the user request using only the tools listed: {allowed_tools}.\n"
            "If no tool call is required, create a single descriptive step explaining the response.\n"
            "Output a JSON array of ordered steps with 'step_id', 'description', 'tool_name', and 'args'."
        )

        plan_schema = create_model(
            "AgentPlan",
            steps=(List[PlanStep], Field(description="A sequential execution plan for the chosen agent.")),
        )

        messages = [SystemMessage(content=system_instructions)] + state["messages"]
        decision = self.llm.with_structured_output(plan_schema).invoke(messages)
        return {"agent_plan": [step.model_dump() for step in decision.steps]}

    def _human_handoff_node(self, state: AgentState) -> dict:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I have reached a point where I need your guidance to proceed. "
                        "Could you please adjust your request, clarify the details, or provide additional context?"
                    )
                )
            ]
        }

    def _check_search_loop(self, state: AgentState) -> str:
        messages = state["messages"]
        if len(messages) < 2:
            return "continue"
        last_msg = messages[-1]
        second_last_msg = messages[-2]
        if isinstance(second_last_msg, ToolMessage) and "no_results" in second_last_msg.content:
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                return "stop_and_ask_user"
        return "continue"

    def _validate_tool_calls(self, state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        if not messages:
            return {}

        last_msg = messages[-1]
        if not (isinstance(last_msg, AIMessage) and last_msg.tool_calls):
            return {}

        if isinstance(last_msg, AIMessage) and isinstance(last_msg.content, str):
            if "function=" in last_msg.content:
                return {
                    "messages": [
                        SystemMessage(
                            content=(
                                "CRITICAL VIOLATION: You attempted to write a function call in plain text. "
                                "You must wait for the user to reply. DO NOT invent data and DO NOT search the web. "
                                "Just ask your question and stop generating text."
                            )
                        )
                    ]
                }

        ctx = state.get("transaction_context", {})

        for tool_call in last_msg.tool_calls:
            tool_name = tool_call["name"]
            args = tool_call.get("args", {})

            # --- schema validator (existing) ---
            validator = TOOL_VALIDATORS.get(tool_name)
            if validator:
                error_message = validator(args, messages)
                if error_message:
                    return {
                        "messages": [
                            ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=f"ERROR: {error_message}",
                            )
                        ]
                    }

            # --- RBAC check ---
            result = check_permission(tool_name, args, ctx)
            if not result.allowed:
                logger.warning(f"RBAC denied '{tool_name}' for role='{ctx.get('user_role')}': {result.reason}")
                return {
                    "messages": [
                        ToolMessage(
                            tool_call_id=tool_call["id"],
                            content=f"PERMISSION_DENIED: {result.reason}",
                        )
                    ]
                }

        return {}

    def _route_after_validation(self, state: AgentState) -> str:
        messages = state["messages"]
        last_msg = messages[-1]
        error_count = 0
        for msg in reversed(messages[-6:]):
            if isinstance(msg, ToolMessage) and (
                "ERROR:" in str(msg.content) or "PERMISSION_DENIED:" in str(msg.content)
            ):
                error_count += 1
            elif isinstance(msg, SystemMessage) and "CRITICAL" in str(msg.content):
                error_count += 1
        if error_count >= 2:
            logger.error("Circuit breaker triggered: Stopping infinite LLM loop.")
            return "human_handoff"

        if isinstance(last_msg, ToolMessage) and (
            "ERROR:" in last_msg.content or "PERMISSION_DENIED:" in last_msg.content
        ):
            return f"execute_{state['current_agent']}"

        if isinstance(last_msg, SystemMessage) and "CRITICAL" in str(last_msg.content):
            return f"execute_{state['current_agent']}"

        return "tools"

    def _supervisor_node(self, state: AgentState) -> Dict[str, Any]:
        return {}

    def _supervisor_route(self, state: AgentState) -> str:
        messages = state["messages"]
        if not messages:
            return END

        last_msg = messages[-1]
        if isinstance(last_msg, ToolMessage):
            if "ERROR:" in str(last_msg.content) or "PERMISSION_DENIED:" in str(last_msg.content):
                return "human_handoff"
            return "router"

        if isinstance(last_msg, SystemMessage) and "CRITICAL" in str(last_msg.content):
            return "human_handoff"

        return END

    def _execute_agent_node(self, agent_name: str):

        def node(state: AgentState) -> Dict[str, Any]:
            
            ctx = state.get("transaction_context", {})
            user_id = ctx.get("current_user_id")
            
            # If no user_id AND agent is not 'discovery', block immediately.
            if agent_name != "discovery" and not user_id:
                logger.warning(f"Unauthenticated access attempt blocked for agent: {agent_name}")
                return {
                    "messages": [
                        AIMessage(
                            content="Authentication required. Please log in to access this feature."
                        )
                    ]
                }
                
            manifest = self.registry.resolve_agent(agent_name)
            all_tools = self.oracle.get_all_tools()
            authorized_tool_names = manifest.authorized_mcp_tools
            ctx = state.get("transaction_context", {})
            system_msg = SystemMessage(
                content=(
                    f"{manifest.system_instructions}\n\n"
                    f"AVAILABLE TOOLS: {', '.join(authorized_tool_names)}.\n"
                    f"{self._format_plan_instructions(state.get('agent_plan'))}\n"
                    "STRICT RULE: Use only the tools listed above. Do not attempt any tool or API that is not explicitly authorized.\n"
                    "IDENTITY RULE: Never ask the user for their ID, role, or any system identifier. "
                    "These are injected automatically by the platform."
                )
            )

            allowed_tools = [t for t in all_tools if t.name in authorized_tool_names]
            llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice="auto")

            try:
                response = llm_with_tools.invoke([system_msg] + state["messages"])

                if response.tool_calls:
                    for tc in response.tool_calls:
                        tool_name = tc["name"]

                        # --- Fix 1, 2, 3: unified auto-injection via AUTO_INJECT map ---
                        injections = AUTO_INJECT.get(tool_name, {})
                        for arg_key, ctx_key in injections.items():
                            value = ctx.get(ctx_key)
                            if value is not None:
                                tc["args"][arg_key] = value

                        # Strip any protected arg the LLM hallucinated
                        protected = PROTECTED_ARGS.get(tool_name, set())
                        tc["args"] = {
                            k: v for k, v in tc["args"].items()
                            if v is not None and (k not in protected or k in injections)
                        }

                        if tool_name not in authorized_tool_names:
                            return {
                                "messages": [
                                    AIMessage(
                                        content=(
                                            f"ERROR: You are not authorized to use '{tool_name}'. "
                                            f"You may only use: {', '.join(authorized_tool_names)}."
                                        )
                                    )
                                ]
                            }

                new_context = self._update_agent_memory(state, agent_name, response)
                return {
                    "messages": [response],
                    "current_agent": agent_name,
                    "transaction_context": new_context,
                }

            except Exception as e:
                logger.error(f"Execution error in agent '{agent_name}': {e}")
                return {
                    "messages": [
                        AIMessage(
                            content=(
                                "SYSTEM ERROR: The previous attempt to use a tool failed because the output "
                                "was incorrectly formatted. You MUST use the provided tool-calling API. "
                                "Do not output plain text descriptions of the tool. Call the tool directly."
                            )
                        )
                    ]
                }

        return node

    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("router", self.router_node)
        workflow.add_node("planner", self._plan_node)
        workflow.add_node("validate_tools", self._validate_tool_calls)
        workflow.add_node("tools", ToolNode(self.oracle.get_all_tools()))
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("human_handoff", self._human_handoff_node)

        for manifest in self.registry.get_all_manifests():
            workflow.add_node(f"execute_{manifest.name}", self._execute_agent_node(manifest.name))

        workflow.add_edge(START, "router")

        def route_from_router(state: AgentState):
            agent = state.get("current_agent")
            return END if agent == "end" else "planner"

        workflow.add_conditional_edges("router", route_from_router)
        workflow.add_conditional_edges("planner", lambda state: f"execute_{state['current_agent']}")

        for manifest in self.registry.get_all_manifests():
            node_name = f"execute_{manifest.name}"

            def create_agent_router(agent_name):
                def route(state: AgentState):
                    if agent_name == "discovery" and self._check_search_loop(state) == "stop_and_ask_user":
                        return "human_handoff"

                    messages = state["messages"]
                    if messages:
                        last_msg = messages[-1]
                        if isinstance(last_msg, AIMessage) and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            return "validate_tools"
                        if isinstance(last_msg, AIMessage) and isinstance(last_msg.content, str):
                            if "function=" in last_msg.content or "tool_call" in last_msg.content:
                                return "validate_tools"
                    return "supervisor"

                return route

            workflow.add_conditional_edges(
                node_name,
                create_agent_router(manifest.name),
                {
                    "validate_tools": "validate_tools",
                    "human_handoff": "human_handoff",
                    "supervisor": "supervisor",
                    END: END,
                },
            )

        workflow.add_edge("tools", "supervisor")
        workflow.add_conditional_edges("validate_tools", self._route_after_validation)
        workflow.add_conditional_edges("supervisor", self._supervisor_route)

        return workflow
