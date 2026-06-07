from typing import Annotated, TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, SystemMessage
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer # Our new Oracle

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: str
    transaction_context: Dict[str, Any]

class PadiGraphOrchestrator:
    def __init__(self, registry: HousePadiAgentRegistry, llm_client: Any, oracle: OracleMCPServer):
        self.registry = registry
        self.llm = llm_client
        self.oracle = oracle
        self.graph = self._build_workflow_graph()

    def _router_decision_node(self, state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        if not messages: return {"current_agent": "discovery"}
        
        manifests = self.registry.get_all_manifests()
        agent_pool = "\n".join([f"- {m.name}: {m.description}" for m in manifests])
        
        prompt = f"Select the best agent from:\n{agent_pool}\nRespond with ONLY the lowercase name."
        response = self.llm.invoke([SystemMessage(content=prompt), messages[-1]])
        
        target = response.content.strip().lower()
        return {"current_agent": target if target in [m.name for m in manifests] else "discovery"}

    def _execute_agent_node(self, agent_name: str):
        def node(state: AgentState) -> Dict[str, Any]:
            # 1. Oracle Context Retrieval: Fetch operational state before LLM speaks
            # Note: In production, extract property_id from state['transaction_context']
            context = self.oracle.execute_tool({
                "thread_id": "live_voice_session", 
                "property_id": state.get("transaction_context", {}).get("property_id", "default_id"),
                "include_financials": True,
                "include_history": True
            })
            
            # 2. Inject Context & Manifest Instructions
            manifest = self.registry.resolve_agent(agent_name)
            system_prompt = SystemMessage(content=f"{manifest.system_instructions}\nOracle Context: {context}")
            
            response = self.llm.invoke([system_prompt] + state["messages"])
            return {"messages": [response], "current_agent": agent_name}
        return node

    def _build_workflow_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("orchestrator_router", self._router_decision_node)
        
        # Add Execution Nodes
        core_targets = ["discovery", "transaction", "legal"]
        for agent_id in core_targets:
            workflow.add_node(f"execute_{agent_id}", self._execute_agent_node(agent_id))
        
        workflow.add_edge(START, "orchestrator_router")
        
        # Dynamic Branching
        workflow.add_conditional_edges("orchestrator_router", lambda s: f"execute_{s['current_agent']}")
        
        # CYCLIC LOOP: Route back to router instead of END for persistent session
        for agent_id in core_targets:
            workflow.add_edge(f"execute_{agent_id}", "orchestrator_router")
            
        return workflow.compile(checkpointer=MemorySaver())