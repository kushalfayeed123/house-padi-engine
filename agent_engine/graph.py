# app/agent_engine/graph.py
import logging
from typing import Annotated, TypedDict, List, Dict, Any, cast
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage # 1. Import AIMessage
from langgraph.prebuilt import ToolNode
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: str
    transaction_context: Dict[str, Any]


class PadiGraphOrchestrator:

    def __init__(self, registry: HousePadiAgentRegistry, llm_client: Any, oracle: OracleMCPServer, db_url: str):
        self.registry = registry
        self.llm = llm_client
        self.oracle = oracle
        self.db_url = db_url
        self.graph = self._build_workflow_graph()

    def _router_decision_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Routes the workflow by returning a dictionary that the graph uses 
        to update the AgentState['current_agent'].
        """
        # Ensure we safely access message content
        messages = state.get("messages", [])
        if not messages:
            return {"current_agent": "discovery"}

        # Extract content safely for Pylance/Type Checker
        content = getattr(messages[-1], "content", "")
        last_msg_lower = str(content).lower()
        
        # Deterministic routing logic
        if any(k in last_msg_lower for k in ["create", "add", "onboard"]):
            return {"current_agent": "broker"}
        
        if any(k in last_msg_lower for k in ["repair", "fix", "inspect", "ledger"]):
            return {"current_agent": "manager"}
            
        return {"current_agent": "discovery"}

    def _execute_agent_node(self, agent_name: str):

        def node(state: AgentState) -> Dict[str, Any]:
            manifest = self.registry.resolve_agent(agent_name)
            
            # PRODUCTION FIX: Bind ALL tools available in the Oracle.
            # This prevents 400 Bad Request errors by giving the LLM full access.
            all_tools = self.oracle.get_all_tools()
            llm_with_tools = self.llm.bind_tools(all_tools)
            
            # Context fetch
            context = self.oracle.execute_tool("context_fetcher", {"property_id": state.get("transaction_context", {}).get("property_id")})
            
            system_msg = SystemMessage(
                content=f"{manifest.system_instructions}\n\nSYSTEM CONTEXT: {context}"
            )
            
            response = llm_with_tools.invoke([system_msg] + state["messages"])
            return {"messages": [response], "current_agent": agent_name}

        return node

    def _should_continue(self, state: AgentState):
        """Routing logic to decide between running tools or finishing."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # If the LLM made a tool call, route to 'tools'
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        
        # Otherwise, stop
        return END

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        
        # 1. Define nodes
        workflow.add_node("router", self._router_decision_node)
        workflow.add_node("tools", ToolNode(self.oracle.get_all_tools()))
        
        # 2. Build agent nodes
        for manifest in self.registry.get_all_manifests():
            workflow.add_node(f"execute_{manifest.name}", self._execute_agent_node(manifest.name))
        
        # 3. Define edges
        workflow.add_edge(START, "router")
        
        # Route to the specific agent selected by the router
        workflow.add_conditional_edges("router", lambda s: f"execute_{s['current_agent']}")
        
        # 4. Agent-Tool Loop
        for manifest in self.registry.get_all_manifests():
            # After agent runs, check if it wants to use a tool
            workflow.add_conditional_edges(
                f"execute_{manifest.name}",
                self._should_continue
            )
            
        # DYNAMIC RETURN: After tools finish, always return to the active agent
        # This replaces the loop you previously had.
        workflow.add_conditional_edges(
            "tools",
            lambda s: f"execute_{s['current_agent']}"
        )
            
        return workflow.compile()
