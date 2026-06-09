# app/agent_engine/graph.py
import logging
from typing import Annotated, TypedDict, List, Dict, Any, cast
from typing_extensions import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage  # 1. Import AIMessage
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


class RouterDecision(BaseModel):
    next_agent: Literal["broker", "discovery", "end"] = Field(
        description="The agent best suited to handle the request."
    )


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
        
    def _human_handoff_node(self, state: AgentState) -> dict:
        """
        Final node: Stops the automated agent loop and presents a message to the user.
        """
        # Create a final message indicating the handoff
        return {
            "messages": [
                AIMessage(
                    content="I've reached a point where I need your guidance to proceed. "
                            "Could you please adjust your budget, location, or search criteria?"
                )
            ]
        }
        
    def router_node(self, state: AgentState):
        # 1. Define clear instructions for the router
        system_instructions = (
            "You are an expert intent classifier for a property management system. "
            "Analyze the user's latest message and assign it to the correct agent.\n"
            "- 'discovery': Use this for SEARCHING, FINDING, or LISTING properties. (e.g., 'find me a house', 'show me 2 bedroom apartments')\n"
            "- 'broker': Use this for CREATING, ADDING, UPDATING, or MANAGING property records. (e.g., 'create a new listing', 'add a property', 'update details')\n"
            "- 'end': Use this if the user is saying goodbye or asking to stop."
        )
        
        # 2. Combine instructions with the history
        messages = [SystemMessage(content=system_instructions)] + state["messages"]
        
        # 3. Force the LLM to choose with the definition in mind
        decision = self.llm.with_structured_output(RouterDecision).invoke(messages)
        
        logger.info(f"Dynamic Route: LLM selected '{decision.next_agent}' based on intent.")
        return {"current_agent": decision.next_agent}
        
    def _check_search_loop(self, state: AgentState) -> str:
        messages = state["messages"]
        
        # Look at the last two messages
        if len(messages) < 2:
            return "continue"
            
        last_msg = messages[-1]
        second_last_msg = messages[-2]
        
        # Check if the last tool call was a search that returned no results
        if (isinstance(second_last_msg, ToolMessage) and 
            "no_results" in second_last_msg.content):
            
            # If the model is trying to use a tool again...
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                # FORCE IT TO STOP
                return "stop_and_ask_user"
                
        return "continue"
        
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
                allowed_tools = ["search_semantic_listings", "fetch_property_by_uuid", "add_new_property_record", "update_property", "delete_property", "log_property_history", "create_inspection", "get_property_ledger"  ] 
                
                # 2. Check for Hallucination
                if tool_call["name"] not in allowed_tools:
                    return {"messages": [ToolMessage(
                        tool_call_id=tool_call["id"],
                        content=f"ERROR: Unauthorized tool usage. You attempted to use '{tool_call['name']}', but you are only permitted to use: {allowed_tools}. Please try again using only authorized tools."
                    )]}
                    
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
                        
                if tool_call["name"] == "search_semantic_listings":
                    args = tool_call.get("args", {})
                    
                    # Check if user actually mentioned money
                    user_text = str(messages[-2].content).lower()  # Get the last user message
                    price_keywords = ["naira", "million", "budget", "price", "cost", "afford"]
                    
                    # IF agent is trying to set a budget but the user never mentioned price
                    if "max_budget" in args and not any(k in user_text for k in price_keywords):
                        return {"messages": [ToolMessage(
                            tool_call_id=tool_call["id"],
                            content="STOP: Do not invent a budget. If the user has not specified a price range, please ask them for their budget first."
                        )]}
                        
        return {}
    
    def _router_decision_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Dynamic Router: Always classifies based on the latest intent.
        """
        messages = state.get("messages", [])
        if not messages:
            return {"current_agent": "discovery"}  # Default start

        # Use your LLM structured output to decide
        decision = self.llm.with_structured_output(RouterDecision).invoke(messages)
        
        logger.info(f"Dynamic Route: LLM decided to switch to {decision.next_agent}")
        return {"current_agent": decision.next_agent}

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
            if any(keyword in last_msg.content for keyword in ["ERROR", "ALREADY_EXISTS"]):
                return f"execute_{state['current_agent']}"
                
        return "tools"

    def _execute_agent_node(self, agent_name: str):

        def node(state: AgentState) -> Dict[str, Any]:
            manifest = self.registry.resolve_agent(agent_name)
            all_tools = self.oracle.get_all_tools()
            authorized_tool_names = manifest.authorized_mcp_tools
            tools_list_string = ", ".join(authorized_tool_names)
            formatted_instructions = manifest.system_instructions.replace("{TOOLS_LIST}", tools_list_string)

            # ADD THIS: Force the agent to handle missing info textually
            negative_constraint = (
                "\n\nCRITICAL: You only have access to these tools: {tools_list}. "
                "If you need information from the user (like budget, location, or specs) "
                "that you do not have, DO NOT try to call a tool to ask for it. "
                "Instead, simply respond to the user with a text message asking for that information."
            )

            system_msg = SystemMessage(content=formatted_instructions + negative_constraint.format(tools_list=", ".join(authorized_tool_names)))
            allowed_tools = [t for t in all_tools if t.name in authorized_tool_names]            
            llm_with_tools = self.llm.bind_tools(allowed_tools, tool_choice="auto")
            
            try: 
                response = llm_with_tools.invoke([system_msg] + state["messages"])
                if response.tool_calls:
                     for tc in response.tool_calls:
                         if tc["name"] not in authorized_tool_names:
                             return {"messages": [AIMessage(content="I attempted to use an unauthorized tool. I must only use my provided tools.")]}
                return {"messages": [response], "current_agent": agent_name}
            except Exception as e:
                logger.error(f"Execution error: {e}")
                return {"messages": [AIMessage(content="I apologize, I made a technical error. Let's restart our search.")]}

        return node
    
    def route_from_router(self, state: AgentState):
            agent = state.get("current_agent")
            
            # Handle the termination case
            if agent == "end":
                return END
            
            # Default to the specific agent node
            return f"execute_{agent}"

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        
        # 1. Point the node to the correct, improved router logic
        workflow.add_node("router", self.router_node) 
        workflow.add_node("validate_tools", self._validate_tool_calls)
        workflow.add_node("tools", ToolNode(self.oracle.get_all_tools()))
        workflow.add_node("human_handoff", self._human_handoff_node)
        
        for manifest in self.registry.get_all_manifests():
            node_name = f"execute_{manifest.name}"
            workflow.add_node(node_name, self._execute_agent_node(manifest.name))
        
        workflow.add_edge(START, "router")
        
        # 2. Dynamic Router Edge: This handles the transition automatically 
        # based on the 'current_agent' key set by router_node
        def route_from_router(state: AgentState):
            agent = state.get("current_agent")
            if agent == "end":
                return END
            # Automatically maps to the node name (e.g., execute_broker)
            return f"execute_{agent}"

        workflow.add_conditional_edges("router", route_from_router)
        
        # 3. Agent to Router Loop (using the same logic as before)
        for manifest in self.registry.get_all_manifests():
            agent_node_name = f"execute_{manifest.name}"
            
            # Helper to generate the routing function
            def create_agent_router(agent_name):

                def route(state: AgentState):
                    # Logic remains the same
                    if agent_name == "discovery" and self._check_search_loop(state) == "stop_and_ask_user":
                        return "human_handoff"
                    last_msg = state["messages"][-1]
                    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                        return "validate_tools"
                    return END

                return route

            workflow.add_conditional_edges(
                agent_node_name,
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
