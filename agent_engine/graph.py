# app/agent_engine/graph.py
import logging
from typing import Annotated, TypedDict, List, Dict, Any, cast
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage  # 1. Import AIMessage
from langgraph.prebuilt import ToolNode
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from langgraph.checkpoint.memory import MemorySaver

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
        builder = self._build_workflow_graph()
        
        memory = MemorySaver()
        self.graph = builder.compile(checkpointer=memory)
        
    def _validate_tool_calls(self, state: AgentState) -> Dict[str, Any]:
        """
        Enhanced Validation Gatekeeper: Blocks tool execution if 
        data is missing, looks like a placeholder, or is inferred.
        """
        
        logger.info("DEBUG [Graph]: Entering _validate_tool_calls node")
        
        messages = state.get("messages", [])
        if not messages:
            return {}
        
        last_msg = messages[-1]
        
        logger.info(f"DEBUG [Graph]: Inspecting last message: {last_msg.type}")
        allowed_keys = {"address", "location", "base_price", "specs", "internal_code"}
        # 1. Check if the message contains tool calls
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            logger.info(f"DEBUG [Graph]: Tool calls detected: {last_msg.tool_calls}")
            for tool_call in last_msg.tool_calls:
                if tool_call["name"] == "add_new_property_record":
                    args = tool_call.get("args", {})
                    
                    # A. Check for Missing Fields
                    required = ["address", "location", "base_price"]
                    missing = [f for f in required if not args.get(f)]
                    if missing:
                        friendly_error = f"I'm sorry, I couldn't save that yet. I still need: {', '.join(missing)}. Please ask the user for these details in a friendly way."
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content=friendly_error
                        )]}
                    
                    # B. Check for Placeholder/Hallucination Patterns
                    # Detects generic strings (e.g., 'test', 'unknown', 'fake')
                    placeholder_patterns = ["test", "fake", "unknown", "placeholder", "tbd", "n/a"]
                    address = str(args.get("address", "")).lower()
                    
                    if any(p in address for p in placeholder_patterns) or len(address) < 5:
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content="ERROR: The provided address appears to be a placeholder or invalid. Please provide a real, specific address."
                        )]}

                    # C. Check for invalid Price
                    if float(args.get("base_price", 0)) <= 0:
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content="ERROR: The base_price must be a valid, positive number. Please ask the user for the actual price."
                        )]}
                    specs = args.get("specs", {})
                    if not specs or len(specs) < 2:
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content="ERROR: Missing detailed property specifications. Please ask the user for bedroom count, bathroom count, or key amenities before proceeding."
                        )]}
                    extra_keys = set(args.keys()) - allowed_keys
                    if extra_keys:
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content=f"ERROR: Invalid arguments provided: {extra_keys}. Do not invent property fields."
                        )]}
                        
        return {}
    
    def _router_decision_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Sticky Router:
        1. If we have an existing 'current_agent' in the state, STICK to it.
        2. Only if state is empty/None, perform intent classification.
        """
        # If the state has an agent, keep it!
        active_agent = state.get("current_agent")
        
        # Check if the active_agent exists and is valid
        if active_agent and active_agent in [m.name for m in self.registry.get_all_manifests()]:
            logger.info(f"Sticky Route: Maintaining active agent: {active_agent}")
            return {"current_agent": active_agent}

        # Otherwise, classify from scratch
        messages = state.get("messages", [])
        content = str(getattr(messages[-1], "content", "")).lower()
        
        if any(k in content for k in ["create", "add", "onboard"]):
            return {"current_agent": "broker"}
        if any(k in content for k in ["repair", "fix", "inspect", "ledger"]):
            return {"current_agent": "manager"}
            
        return {"current_agent": "discovery"}

    def _should_continue(self, state: AgentState):
        """Routing logic to decide between running tools or finishing."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # If the LLM made a tool call, route to 'tools'
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        
        if isinstance(last_message, ToolMessage):
            if "ERROR" in last_message.content or "ALREADY_EXISTS" in last_message.content:
                return END
        
        if state.get("search_performed"):
            return "finish"
        
        # Otherwise, stop
        return END

    # Refined Helper for Routing
    def _route_after_validation(self, state: AgentState) -> str:
        """
        Handles logic after tool validation. 
        Explicitly checks for failures to loop back to the agent.
        """
        last_msg = state["messages"][-1]
        
        if isinstance(last_msg, ToolMessage):
            # Catch both hard errors AND business logic failures (like duplicates)
            if any(keyword in last_msg.content for keyword in ["ERROR", "ALREADY_EXISTS"]):
                return f"execute_{state['current_agent']}"
                
        # Default: Proceed to execution
        return "tools"


    def _execute_agent_node(self, agent_name: str):
        def node(state: AgentState) -> Dict[str, Any]:
            manifest = self.registry.resolve_agent(agent_name)
            all_tools = self.oracle.get_all_tools()
            
            # 1. REMOVED: The logic that strips tools based on text keywords.
            # Now, we simply authorize all tools defined in the agent's manifest.
            allowed_tools = [t for t in all_tools if t.name in manifest.authorized_mcp_tools]
            
            # 2. Bind all tools. The LLM will decide whether to call them.
            llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice="auto")
            
            system_msg = SystemMessage(content=f"{manifest.system_instructions}")            
            # Invoke LLM
            response = llm_with_tools.invoke([system_msg] + state["messages"])
            return {"messages": [response], "current_agent": agent_name}
        return node

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("router", self._router_decision_node)
        workflow.add_node("validate_tools", self._validate_tool_calls)
        workflow.add_node("tools", ToolNode(self.oracle.get_all_tools()))
        
        for manifest in self.registry.get_all_manifests():
            workflow.add_node(f"execute_{manifest.name}", self._execute_agent_node(manifest.name))
        
        workflow.add_edge(START, "router")
        workflow.add_conditional_edges("router", lambda s: f"execute_{s['current_agent']}")
        
        # Validation Loop
        for manifest in self.registry.get_all_manifests():
            workflow.add_conditional_edges(
                f"execute_{manifest.name}",
                lambda s: "validate_tools" if (
                    hasattr(s["messages"][-1], "tool_calls") and s["messages"][-1].tool_calls
                ) else END
            )
                    
        # FIX: Use the explicit routing function instead of a lambda
        workflow.add_conditional_edges("validate_tools", self._route_after_validation)
        
        # After tools finish, return to agent
        workflow.add_conditional_edges("tools", lambda s: f"execute_{s['current_agent']}")
        return workflow
