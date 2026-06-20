import json
import logging
from typing import Annotated, Hashable, TypedDict, List, Dict, Any, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage, HumanMessage
from pydantic import BaseModel, Field, ValidationError, create_model
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from data_layer.schemas.orchestrator_client_response import OrchestratorClientResponse
from data_layer.tool_validators import TOOL_VALIDATORS
from data_layer.permissions import check_permission
from supabase import Client

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
# ---------------------------------------------------------------------------


AUTO_INJECT: Dict[str, Dict[str, str]] = {
    # Property
    "add_new_property_record": {"owner_id": "current_user_id"},

    # Tour
    "schedule_tour": {"renter_id": "current_user_id"},

    # Applications
    "apply_for_property": {"renter_id": "current_user_id"},
    "get_renter_applications": {"renter_id": "current_user_id"},
    "approve_application": {"landlord_id": "current_user_id"},
    "deny_application": {"landlord_id": "current_user_id"},

    # Leases
    "sign_lease": {"signer_id": "current_user_id"},
    "get_active_leases": {"user_id": "current_user_id"},

    # User profile
    "get_user_profile": {"user_id": "current_user_id"},
    "update_user_profile": {"user_id": "current_user_id"},
}

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
        supabase_client: Client
    ):
        self.registry = registry
        self.llm = llm_client
        self.oracle = oracle
        self.db_url = db_url
        self.supabase_client = supabase_client

        builder = self._build_workflow_graph()
        memory = MemorySaver()
        self.graph = builder.compile(checkpointer=memory)
        
    async def arun_turn(
        self,
        user_message: str,
        thread_id: str,
        user_id: Optional[str]=None,
        user_role: Optional[str]=None
    ) -> Dict[str, Any]:
        """
        Asynchronously executes a graph turn, handles state checkpoint merging, 
        and enforces the structural client response contract. Includes a defensive
        async throttle loop to prevent burst 429 rate limits against Groq.
        """
        import asyncio  # Ensure asyncio is available for throttling
        
        config = {"configurable": {"thread_id": thread_id}}
        
        # 1. Fetch existing checkpoint state asynchronously to merge historical context
        existing_state = await self.graph.aget_state(config)
        existing_ctx = {}
        if existing_state and existing_state.values:
            existing_ctx = existing_state.values.get("transaction_context", {}) or {}
            
        # 2. Merge incoming secure user parameters with historical runtime data
        merged_context = {
            **existing_ctx,
            "current_user_id": user_id,
            "user_role": user_role
        }

        initial_input = {
            "messages": [HumanMessage(content=user_message)],
            "transaction_context": merged_context
        }
        
        try:
            # INFRASTRUCTURE DEFENSE LAYER: Smooth out high-frequency parallel requests
            # Sleeping for 1 second gives Groq's rolling window time to clear previous token spikes.
            logger.info("Applying dynamic rate-limiting throttle (asyncio.sleep) to absorb burst traffic...")
            await asyncio.sleep(1.0)

            # 3. Await state-graph execution path
            final_state = await self.graph.ainvoke(initial_input, config=config)
            
            messages = final_state.get("messages", [])
            current_agent = final_state.get("current_agent", "unknown")
            tx_context = final_state.get("transaction_context", {}) or {}
            
            # 4. Extract natural language text payload intended for user
            final_text = ""
            is_handoff = (current_agent == "human_handoff")
            
            if messages:
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        # Ensure we extract clean display prose rather than fallback JSON configurations
                        if isinstance(msg.content, str) and not msg.content.strip().startswith("{"):
                            final_text = msg.content
                            break
                    elif isinstance(msg, SystemMessage) and "CRITICAL VIOLATION" in str(msg.content):
                        final_text = "I encountered an issue verifying your input format. Please try again."
                        break
            
            if not final_text:
                final_text = "Your request was processed successfully, but no text was generated."

            # Return uniform dictionary matching the client contract spec
            return {
                "success": True,
                "agent": current_agent,
                "message": final_text,
                "requires_action": is_handoff,
                "error": None,
                "context": {
                    "current_user_id": tx_context.get("current_user_id"),
                    "user_role": tx_context.get("user_role")
                }
            }

        except Exception as graph_fault:
            logger.error(f"Fatal operational crash inside orchestrator async run loop: {graph_fault}", exc_info=True)
            return {
                "success": False,
                "agent": "system_circuit_breaker",
                "message": "An unexpected system handling error occurred. Please try again shortly.",
                "requires_action": True,
                "error": str(graph_fault),
                "context": {"current_user_id": user_id, "user_role": user_role}
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trim_historical_context(self, messages: list, max_tokens_estimate: int=2000) -> list:
        """
        Calculates approximate token depth working backwards to safeguard
        against TPM/RPM limits on low-tier providers.
        """
        if not messages:
            return []
        trimmed = []
        token_counter = 0
        for msg in reversed(messages):
            msg_length = len(str(msg.content).split()) * 1.4
            if token_counter + msg_length > max_tokens_estimate:
                break
            trimmed.insert(0, msg)
            token_counter += msg_length
        return trimmed

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

    def _merge_transaction_context(self, state: AgentState, new_context: dict) -> dict:
        """
        Scans the latest messages array for successful tool outputs and automatically
        promotes returned entity identifiers to the global transaction state.
        """
        merged = dict(state.get("transaction_context", {}))
        merged.update(new_context)
        
        # Dynamically find the last message if it's a ToolMessage
        messages = state.get("messages", [])
        if messages and type(messages[-1]).__name__ == "ToolMessage":
            tool_msg: BaseMessage = messages[-1]
            try:
                import json
                content_str = tool_msg.content
                if isinstance(content_str, list):
                    # Fallback / extraction strategy if content is stored in a multi-part content block list
                    content_str = " ".join([item if isinstance(item, str) else json.dumps(item) for item in content_str])
            
                if isinstance(content_str, (str, bytes, bytearray)):
                    data = json.loads(content_str)
                    
                    # Generic loop: if the tool returned explicit context keys, promote them
                    if isinstance(data, dict):
                        # Check for standard identification key patterns across your platform
                        for key, val in data.items():
                            if key.endswith("_id") or key in ["id", "uuid", "reference"]:
                                # Standardize tracking format
                                context_key = f"current_{(tool_msg.name or '').split('_')[-1]}_id" if key == "id" else key
                                merged[context_key] = val
                                logger.info(f"💾 Dynamic context promotion: {context_key} -> {val}")
                else:
                    logger.warning(f"Skipping context harvest: tool_msg.content is an unsupported type: {type(content_str)}")
                    
            except Exception as e:
                logger.error(f"Failed generic tool context promotion: {e}")
                
        return merged

    def _update_agent_memory(self, state: AgentState, agent_name: str, message: BaseMessage) -> Dict[str, Any]:
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
                +(f" Use tool: {step.get('tool_name')}" if step.get("tool_name") else "")
            )
        return "PLANNED STEPS:\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def router_node(self, state: AgentState):
        manifests = self.registry.get_all_manifests()
        ctx = state.get("transaction_context", {}) or {}
        user_role = ctx.get("user_role", "discovery")

        # Define strict target routing maps bound directly to active roles
        role_routing_boundaries = {
            "renter": ["discovery", "renter"],
            "landlord": ["discovery", "landlord"],
            "broker": ["discovery", "renter", "landlord", "broker"]
        }
        allowed_destinations = role_routing_boundaries.get(user_role, ["discovery"])
        agent_names = [m.name for m in manifests if m.name in allowed_destinations]
        
        active_agent = state.get("current_agent")
        agent_descriptions = "\n".join([f"- '{m.name}': {m.description}" for m in manifests if m.name in allowed_destinations])
        memory_text = self._render_agent_memory(state)

        context_instruction = (
            f"\n\nCURRENT CONTEXT: The conversation is currently assigned to '{active_agent}'.\n"
            "Only stay on that agent unless the user explicitly changes the topic or asks for a different service."
        ) if active_agent and active_agent in allowed_destinations else "\n\nNo agent is currently active."

        system_instructions = (
            "You are the House Padi Orchestrator. Decide which registered agent should handle the user's latest request.\n"
            "CRITICAL: Your response must be a valid json object with exactly one key: 'next_agent'.\n"
            "Do not return any other keys like 'agent', 'status', 'applications', or 'request'. Use only the 'next_agent' key.\n"
            f"Available agents for this session:\n{agent_descriptions}\n"
            "CRITICAL RULE: If the user is providing personal details (income, employment) in response to a request "
            "from the current agent, you MUST route to the current agent.\n"
            "- 'end': Use this if the user is done or the request has been fully satisfied."
            +context_instruction
        )

        if memory_text:
            system_instructions += "\n\n" + memory_text

        # Slice trailing conversation turns to avoid context ballooning over low-TPM router limits
        safe_messages = self._trim_historical_context(state["messages"], max_tokens_estimate=1500)
        messages = [SystemMessage(content=system_instructions)] + safe_messages
        
        messages.append(
            SystemMessage(
                content=(
                    "### IMPORTANT ROUTER EXECUTION COMMAND ###\n"
                    "Ignore any data structures, success payloads, or application logs above. "
                    "Do not try to copy or summarize them. You must now act purely as the routing engine.\n"
                    "Output a valid json object containing exclusively the key 'next_agent' bound to one of the allowed strings.\n"
                    f"Allowed string values for 'next_agent': {agent_names + ['end']}\n"
                    "Target format example: {\"next_agent\": \"end\"}"
                )
            )
        )

        dynamic_schema = self._get_router_schema(agent_names + ["end"])
        decision = self.llm.with_structured_output(dynamic_schema, method="json_mode").invoke(messages)

        target_agent = decision.next_agent if decision.next_agent in (agent_names + ["end"]) else "discovery"
        logger.info(f"Routing decision (Role Context: {user_role}): {target_agent}")
        return {"current_agent": target_agent}
    
    def get_tool_definitions_prompt(self, authorized_tools: List[str]) -> str:
        if not authorized_tools:
            return "None. You cannot use any tools for this agent."
            
        tool_objects = self.oracle.get_tools_by_name(authorized_tools)
        prompt_lines = []
        for tool_obj in tool_objects:
            tool_name = getattr(tool_obj, "name", "unknown")
            args_schema = getattr(tool_obj, "args", "No arguments required.")
            description = getattr(tool_obj, "description", "No description provided.")
            
            prompt_lines.append(
                f"- Tool: '{tool_name}'\n"
                f"  Description: {description}\n"
                f"  Required Arguments Schema: {args_schema}"
            )
            
        return "\n".join(prompt_lines)

    def _plan_node(self, state: AgentState) -> Dict[str, Any]:

        agent_name = state.get("current_agent")
        if not agent_name or agent_name == "end":
            return {"agent_plan": []}

        messages = state.get("messages", [])
        updated_plan = state.get("agent_plan") or []        
        # --- STATE-MACHINE EXECUTED STEP PURGE ---
        # Look back to see if the user's message is a continuation of a parameter-gathering loop.
        if len(messages) >= 3 and messages[-1].type == "human" and updated_plan:
            current_planned_tool = updated_plan[0].get("tool_name")
            
            # Find the most recent AI generation and any matching tool executions before this human turn
            last_ai_msg = next((m for m in reversed(messages[:-1]) if m.type == "ai"), None)
            last_tool_msg = next((m for m in reversed(messages[:-1]) if m.type == "tool"), None)
            
            if last_ai_msg and last_tool_msg and last_tool_msg.name == current_planned_tool:
                metadata = getattr(last_ai_msg, "response_metadata", {})
                finish_reason = metadata.get("finish_reason") or metadata.get("kv", {}).get("finish_reason")
                
                # If the AI completed the summary response cleanly without asking parameter-gathering questions,
                # the step is complete and must be removed to avoid forcing tool re-execution on the next turn.
                if finish_reason == "stop":
                    logger.info(f"🧹 Planned step '{current_planned_tool}' was completely executed and conversationalized. Popping stack.")
                    updated_plan.pop(0)

        # --- CRITICAL DE-DUPLICATION CHECK ---
        # Look back at the conversation history. If a tool just finished executing,
        # we explicitly return an empty plan so the executor knows to write a natural
        # summary response for the user instead of calling the tool again.
        if messages:
            last_message = messages[-1]
            
            # Check standard LangGraph/LangChain ToolMessage layouts
            is_tool_msg = type(last_message).__name__ == "ToolMessage" or hasattr(last_message, "tool_call_id")
            
            if is_tool_msg:
                logger.info(
                    f"🎯 Found completed tool output at history tail. "
                    f"Clearing plan steps to let agent '{agent_name}' compile the final prose answer."
                )
                return {"agent_plan": []}
        # -------------------------------------

        manifest = self.registry.resolve_agent(agent_name)
        authorized_tools = manifest.authorized_mcp_tools
        detailed_tools_prompt = self.get_tool_definitions_prompt(authorized_tools)

        if authorized_tools:
            ToolNameLiteral = Literal[tuple(authorized_tools)]  # type: ignore
            tool_name_field = (Optional[ToolNameLiteral], Field(None, description="The authorized tool to use for this step."))
        else:
            tool_name_field = (Optional[Literal[""]], Field(None, description="No tools available for this agent. Keep null or empty."))

        DynamicPlanStep = create_model(
            "DynamicPlanStep",
            step_id=(int, Field(..., description="The ordered step number.")),
            description=(str, Field(..., description="What this agent should do next.")),
            tool_name=tool_name_field,
            args=(Dict[str, Any], Field(default_factory=dict, description="Arguments for the tool call."))
        )

        plan_schema = create_model(
            "AgentPlan",
            steps=(List[DynamicPlanStep], Field(description="A sequential execution plan for the chosen agent.")),
        )
        
        authorized_tools_list_str = ", ".join([f"'{t}'" for t in authorized_tools])
        schema_dict = plan_schema.model_json_schema()
        system_instructions = (
            f"You are the planning agent for '{agent_name}'.\n"
            "You must output valid JSON matching this schema:\n"
            f"{json.dumps(schema_dict, indent=2)}\n\n"
            "CRITICAL CONSTRAINTS:\n"
            f"1. You may ONLY use these exact tool names: {authorized_tools_list_str}.\n"
            "2. If a user asks for a feature, map their intent to the closest tool name above.\n"
            "3. DO NOT hallucinate tool names. If no tool matches, return an empty steps list.\n\n"
            f"AVAILABLE TOOLS:\n{detailed_tools_prompt}\n"
        )

        safe_messages = self._trim_historical_context(messages, max_tokens_estimate=1500)
        invocation_messages = [SystemMessage(content=system_instructions)] + safe_messages
        invocation_messages.append(
            SystemMessage(
                content=(
                    "### IMPORTANT PLANNER EXECUTION COMMAND ###\n"
                    "Output a valid json object with a single root key 'steps' containing your execution list.\n"
                    f"You may only choose from these specific tools: {authorized_tools or 'None'}.\n"
                    "Target format example: {\"steps\": []}"
                )
            )
        )

        decision = self.llm.with_structured_output(plan_schema, method="json_mode").invoke(invocation_messages)
        
        sanitized_steps = []
        for step in decision.steps:
            step_dict = step.model_dump()
            t_name = step_dict.get("tool_name")
            
            if t_name and t_name not in authorized_tools:
                logger.warning(f"Sanitizer caught unauthorized tool hallucination '{t_name}' for agent '{agent_name}'. Stripping assignment.")
                step_dict["tool_name"] = None
                step_dict["args"] = {}
                
            sanitized_steps.append(step_dict)

        # Merge our evaluated plan changes back into state output safely
        return {"agent_plan": updated_plan if updated_plan != list(state.get("agent_plan") or []) else sanitized_steps}

    def _human_handoff_node(self, state: AgentState) -> dict:
        return {
            "current_agent": "human_handoff"
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

                validator = TOOL_VALIDATORS.get(tool_name)
                if validator:
                    error_message = validator(args, messages)
                    if error_message:
                        logger.error(f"VALIDATION FAILED for tool '{tool_name}': {error_message} | Provided Args: {args}")
                        return {
                            "messages": [
                                ToolMessage(
                                    tool_call_id=tool_call["id"],
                                    content=f"ERROR: {error_message}",
                                )
                            ]
                        }

                result = check_permission(tool_name, args, ctx, supabase=self.supabase_client)
                if not result.allowed:
                    logger.error(f"RBAC DENIED '{tool_name}' for role='{ctx.get('user_role')}': {result.reason} | Args: {args}")
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
        
        # Circuit Breaker: Stop infinite error loops
        error_count = 0
        for msg in reversed(messages[-6:]):
            if isinstance(msg, ToolMessage) and ("ERROR:" in str(msg.content) or "PERMISSION_DENIED:" in str(msg.content)):
                error_count += 1
        if error_count >= 2:
            logger.error("Circuit breaker triggered: Routing to human handoff to stop loop.")
            return "human_handoff"

        # CRITICAL LOOP FIX: Check the last message in state
        last_msg = messages[-1]

        # 1. If the last message is a ToolMessage, a tool JUST finished running.
        # Instead of letting the graph loop forever, send the tool results back to the user!
        if isinstance(last_msg, ToolMessage):
            logger.info("Tool execution completed. Handing off back to the user.")
            return "human_handoff"

        # 2. If the last message is an AIMessage, check if the LLM wants to run a tool
        if isinstance(last_msg, AIMessage):
            if last_msg.tool_calls:
                logger.info(f"LLM requested {len(last_msg.tool_calls)} tool call(s). Routing to tools node.")
                return "tools"
            else:
                # The agent provided conversational prose or hit a dead end without tools
                logger.info("Agent provided direct text response. Routing to human handoff.")
                return "human_handoff"

        # Fallback default
        return "human_handoff"

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
            
            if agent_name != "discovery" and not user_id:
                logger.warning(f"Unauthenticated access attempt blocked for agent: {agent_name}")
                return {
                    "messages": [
                        AIMessage(content="Authentication required. Please log in to access this feature.")
                    ]
                }
                
            manifest = self.registry.resolve_agent(agent_name)
            all_tools = self.oracle.get_all_tools()
            authorized_tool_names = manifest.authorized_mcp_tools
            
            agent_plan = state.get("agent_plan", [])
            target_tool = None
            if agent_plan and isinstance(agent_plan, list):
                target_tool = agent_plan[0].get("tool_name")

            # Base system policy and routing definitions stay securely at the head
            system_msg = SystemMessage(
                content=(
                    "### CRITICAL IDENTITY POLICY ###\n"
                    "YOU MUST NEVER ASK THE USER FOR THEIR RENTER_ID, USER_ID, OR AUTHENTICATION DETAILS.\n"
                    "The system has automatic access to these identifiers via the secure transaction context.\n"
                    "If a tool requires an ID, call the tool directly. The platform will automatically inject the "
                    "required ID into the request. Do not prompt the user for data that the platform "
                    "already possesses.\n\n"
                    f"{manifest.system_instructions}\n"
                )
            )
            
            all_tool_names = [t.name for t in all_tools]
            for name in authorized_tool_names:
                if name not in all_tool_names:
                    logger.error(f"CONFIG ERROR: Agent '{agent_name}' is authorized to use '{name}', but this tool is not in the Oracle list.")

            allowed_tools = self.oracle.get_tools_by_name(manifest.authorized_mcp_tools)
            
            # Slice and trim state context backwards to fit under Groq 6,000 TPM limit limits
            trimmed_history = self._trim_historical_context(state["messages"], max_tokens_estimate=2200)

            # Build the base array execution container
            final_invocation_messages = [system_msg] + trimmed_history

            if target_tool and target_tool in authorized_tool_names:
                logger.info(f"Forcing strict execution of planned tool: '{target_tool}'")
                final_invocation_messages.append(
                    SystemMessage(
                        content=(
                            f"CRITICAL: You are forced to execute the tool '{target_tool}'. "
                            "Do NOT write any plain text sentences, conversational greetings, or descriptions alongside it. "
                            "Provide ONLY the tool function parameters. Do not speak to the user yet."
                        )
                    )
                )
                llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice=target_tool)
            else:
                logger.info("No explicit tool planned. Falling back to autonomous routing.")
                llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice="auto")
                
                # --- POSITION-BASED STRUCTURAL OVERRIDE ---
                # If agent_plan is empty, we check if it was explicitly emptied due to a tool running.
                if not agent_plan:
                    final_invocation_messages.append(
                        SystemMessage(
                            content=(
                                "### FINALIZING TOOL RESPONSE EXECUTIVE COMMAND ###\n"
                                "You have successfully gathered data from the tool execution history listed above. "
                                "Do NOT repeat or read out the default guidance or placeholder text instructions. "
                                "Analyze the raw JSON data results provided by the ToolMessage directly above, "
                                "and present a warm, helpful conversational summary listing the matching available options "
                                "directly to the renter."
                            )
                        )
                    )
                else:
                    # Fallback to normal conversational text routing
                    plan_instructions = self._format_plan_instructions(agent_plan)
                    final_invocation_messages.append(SystemMessage(content=plan_instructions))

            logger.info(f"Invoking LLM with structured message timeline payload: {final_invocation_messages}")

            try:
                response = llm_with_tools.invoke(final_invocation_messages)
                logger.info(f"LLM Tool Calls Found: {len(getattr(response, 'tool_calls', []))}")

                processed_messages = [response]
                
                if response.tool_calls:
                    new_tool_calls = []
                    for tc in response.tool_calls:
                        tool_name = tc["name"]
                        args_payload = dict(tc.get("args", {}))
                        
                        injections = AUTO_INJECT.get(tool_name, {})
                        for arg_key, ctx_key in injections.items():
                            value = ctx.get(ctx_key)
                            if value is not None:
                                args_payload[arg_key] = value
                        
                        protected = PROTECTED_ARGS.get(tool_name, set())
                        args_payload = {
                            k: v for k, v in args_payload.items()
                            if v is not None and (k not in protected or k in injections)
                        }

                        new_tc = {
                            "name": tool_name,
                            "args": args_payload,
                            "id": tc.get("id"),
                            "type": "tool_call"
                        }

                        if tool_name not in authorized_tool_names:
                            return {
                                "messages": [
                                    AIMessage(
                                        content=f"ERROR: You are not authorized to use '{tool_name}'."
                                    )
                                ]
                            }
                        new_tool_calls.append(new_tc)

                    sanitized_response = AIMessage(
                        content=response.content,
                        tool_calls=new_tool_calls,
                        id=response.id,
                        response_metadata=response.response_metadata
                    )
                    processed_messages = [sanitized_response]

                new_context = self._update_agent_memory(state, agent_name, response)
                merged_context = self._merge_transaction_context(state, new_context)
                raw_plan = state.get("agent_plan")
                updated_plan = list(raw_plan if raw_plan is not None else [])
                if updated_plan and response.tool_calls:
                    executed_tool_name = response.tool_calls[0]["name"]
                    planned_tool_name = updated_plan[0].get("tool_name")
                    
                    # Verify that the tool called aligns with what was expected
                    if executed_tool_name == planned_tool_name:
                        logger.info(f"🚀 Consumed planned tool step from stack: {executed_tool_name}")
                        updated_plan.pop(0)
                return {
                    "messages": processed_messages,
                    "agent_plan": updated_plan,
                    "current_agent": agent_name,
                    "transaction_context": merged_context,
                }

            except Exception as e:
                logger.error(f"Execution error in agent '{agent_name}': {e}")
                return {
                    "messages": [
                        AIMessage(
                            content="I encountered an issue building your search profile requirements. Let's adjust slightly—could you rephrase that request?"
                        )
                    ],
                    "agent_plan": []  
                }

        return node
    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("router", self.router_node)
        workflow.add_node("planner", self._plan_node)  # Formally wired below
        workflow.add_node("validate_tools", self._validate_tool_calls)
        workflow.add_node("human_handoff", self._human_handoff_node)

        manifests = self.registry.get_all_manifests()
        for manifest in manifests:
            node_name = f"execute_{manifest.name}"
            workflow.add_node(node_name, self._execute_agent_node(manifest.name))

        # 1. Start goes to Router to determine which agent owns the intent
        workflow.add_edge(START, "router")

        # 2. FIX: Router now routes directly to the PLANNER instead of bypassing it
        routing_map: Dict[Hashable, str] = {m.name: "planner" for m in manifests}
        routing_map["end"] = END
        workflow.add_conditional_edges("router", lambda state: state.get("current_agent", "end"), routing_map)

        # 3. FIX: Planner routes conditionally to the selected execution agent node
        def route_from_planner(state: AgentState) -> str:
            agent = state.get("current_agent", "end")
            return f"execute_{agent}" if agent != "end" else END

        planner_map: Dict[Hashable, str] = {f"execute_{m.name}": f"execute_{m.name}" for m in manifests}
        planner_map[END] = END
        
        workflow.add_conditional_edges("planner", route_from_planner, planner_map)

        # 4. Agent execution nodes point to validation layer
        for manifest in manifests:
            node_name = f"execute_{manifest.name}"
            workflow.add_edge(node_name, "validate_tools")

        # 5. Validation layer routes to tools or handoff
        workflow.add_conditional_edges(
            "validate_tools",
            self._route_after_validation,
            {
                "tools": "tools",
                "human_handoff": "human_handoff"
            }
        )

        # Dynamic tools node setup
        allowed_tools = self.oracle.get_all_tools()
        tools_node = ToolNode(allowed_tools)
        workflow.add_node("tools", tools_node)

        # After tools run, loop back to the planner/agent to process the tool outputs
        workflow.add_edge("tools", "planner")
        workflow.add_edge("human_handoff", END)

        return workflow
