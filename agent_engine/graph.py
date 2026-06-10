import logging
from typing import Annotated, TypedDict, List, Dict, Any, cast, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, create_model
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from langgraph.checkpoint.memory import MemorySaver

from data_layer.tool_validators import TOOL_VALIDATORS

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: str
    transaction_context: Dict[str, Any]
    search_performed: bool

class PadiGraphOrchestrator:

    def __init__(self, registry: HousePadiAgentRegistry, llm_client: Any, oracle: OracleMCPServer, db_url: str):
        self.registry = registry
        self.llm = llm_client
        self.oracle = oracle
        self.db_url = db_url
        
        # Build the graph dynamically
        builder = self._build_workflow_graph()
        memory = MemorySaver()
        self.graph = builder.compile(checkpointer=memory)

    def _get_router_schema(self, agent_names: List[str]):
        """Dynamically creates a Pydantic model based on available agents."""
        return create_model(
            "RouterDecision",
            next_agent=(Literal[tuple(agent_names)], Field(description="The agent best suited to handle the request.")),
        )

    def router_node(self, state: AgentState):
        """
        Dynamically routes requests by querying the Registry for available agents.
        """
        manifests = self.registry.get_all_manifests()
        agent_names = [m.name for m in manifests]
        
        # Build dynamic descriptions for the system prompt
        agent_descriptions = "\n".join([f"- '{m.name}': {m.description}" for m in manifests])
        
        system_instructions = (
            "You are an expert intent classifier. Analyze the user's latest message and assign it to the correct agent.\n"
            f"Available Agents:\n{agent_descriptions}\n"
            "- 'end': Use this if the user is saying goodbye or asking to stop."
        )
        
        # Build dynamic Pydantic schema
        dynamic_schema = self._get_router_schema(agent_names + ["end"])
        
        messages = [SystemMessage(content=system_instructions)] + state["messages"]
        decision = self.llm.with_structured_output(dynamic_schema).invoke(messages)
        
        logger.info(f"Dynamic Route: LLM selected '{decision.next_agent}'")
        return {"current_agent": decision.next_agent}

    def _human_handoff_node(self, state: AgentState) -> dict:
        return {
            "messages": [
                AIMessage(
                    content="I've reached a point where I need your guidance to proceed. "
                            "Could you please adjust your, location, or search criteria?"
                )
            ]
        }

    def _check_search_loop(self, state: AgentState) -> str:
        messages = state["messages"]
        if len(messages) < 2: return "continue"
        
        last_msg = messages[-1]
        second_last_msg = messages[-2]
        
        if (isinstance(second_last_msg, ToolMessage) and "no_results" in second_last_msg.content):
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                return "stop_and_ask_user"
        return "continue"

    def _validate_tool_calls(self, state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        if not messages: return {}
        
        last_msg = messages[-1]
        if not (isinstance(last_msg, AIMessage) and last_msg.tool_calls):
            return {}

        for tool_call in last_msg.tool_calls:
            tool_name = tool_call["name"]
            args = tool_call.get("args", {})
            
            # 1. Check if we have a registered validator for this tool
            validator = TOOL_VALIDATORS.get(tool_name)
            
            if validator:
                error_message = validator(args, messages)
                
                # 2. If validator returns a message, it failed validation
                if error_message:
                    return {"messages": [ToolMessage(
                        tool_call_id=tool_call["id"],
                        content=f"ERROR: {error_message}"
                    )]}
        
        return {}

    def _route_after_validation(self, state: AgentState) -> str:
        last_msg = state["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            if any(k in last_msg.content for k in ["ERROR", "ALREADY_EXISTS"]):
                return f"execute_{state['current_agent']}"
        return "tools"

    def _execute_agent_node(self, agent_name: str):
        def node(state: AgentState) -> Dict[str, Any]:
            manifest = self.registry.resolve_agent(agent_name)
            all_tools = self.oracle.get_all_tools()
            authorized_tool_names = manifest.authorized_mcp_tools
            
            # Prepare instructions
            system_msg = SystemMessage(content=manifest.system_instructions)
            allowed_tools = [t for t in all_tools if t.name in authorized_tool_names]
            llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice="auto")
            user_id = state["transaction_context"].get("current_user_id")
            
            try:
                response = llm_with_tools.invoke([system_msg] + state["messages"])
                
                # Pre-processing tool calls
                if response.tool_calls:
                    for tc in response.tool_calls:
                        if tc["name"] in ["get_user_profile", "update_user_profile", "add_new_property_record"]:
                             tc["args"]["user_id"] = user_id
                             tc["args"]["owner_id"] = user_id
                             
                        tc["args"] = {k: v for k, v in tc["args"].items() if v is not None}
                        
                        if tc["name"] not in authorized_tool_names:
                            return {"messages": [ToolMessage(
                                tool_call_id=tc["id"],
                                content=f"ERROR: Unauthorized tool usage. You attempted to use '{tc['name']}', but you are only permitted to use: {', '.join(authorized_tool_names)}. Please try again using only authorized tools."
                            )]}
                
                return {"messages": [response], "current_agent": agent_name}
            except Exception as e:
                logger.error(f"Execution error: {e}")
                return {"messages": [AIMessage(content="I made a technical error.")]}
        return node

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        
        # Standard Nodes
        workflow.add_node("router", self.router_node) 
        workflow.add_node("validate_tools", self._validate_tool_calls)
        workflow.add_node("tools", ToolNode(self.oracle.get_all_tools()))
        workflow.add_node("human_handoff", self._human_handoff_node)
        
        # Add dynamic agent nodes
        for manifest in self.registry.get_all_manifests():
            workflow.add_node(f"execute_{manifest.name}", self._execute_agent_node(manifest.name))
        
        workflow.add_edge(START, "router")
        
        # Dynamic Router Edge
        def route_from_router(state: AgentState):
            agent = state.get("current_agent")
            return END if agent == "end" else f"execute_{agent}"

        workflow.add_conditional_edges("router", route_from_router)
        
        # Dynamic Edges back to Router
        for manifest in self.registry.get_all_manifests():
            node_name = f"execute_{manifest.name}"
            
            def create_agent_router(agent_name):
                def route(state: AgentState):
                    # Specialized loop check for discovery
                    if agent_name == "discovery" and self._check_search_loop(state) == "stop_and_ask_user":
                        return "human_handoff"
                    
                    last_msg = state["messages"][-1]
                    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                        return "validate_tools"
                    return END
                return route

            workflow.add_conditional_edges(
                node_name,
                create_agent_router(manifest.name),
                {
                    "validate_tools": "validate_tools",
                    "human_handoff": "human_handoff",
                    "router": "router",
                    END: END
                }
            )

        workflow.add_edge("tools", "router")
        workflow.add_conditional_edges("validate_tools", self._route_after_validation)
        
        return workflow