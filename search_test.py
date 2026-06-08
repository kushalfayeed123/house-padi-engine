import os
from dotenv import load_dotenv
from supabase import create_client
from langchain_core.messages import HumanMessage
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from agent_engine.graph import PadiGraphOrchestrator
from langchain_groq import ChatGroq

# 0. Load setup
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL") or "", os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "")
registry = HousePadiAgentRegistry()
registry.initialize_production_agents()

# Assume your Orchestrator is configured correctly
orchestrator = PadiGraphOrchestrator(
    registry=registry,
    llm_client=ChatGroq(model="llama-3.1-8b-instant", temperature=0.0),
    oracle=OracleMCPServer(supabase_client=supabase),
    db_url=os.getenv("DATABASE_URL") or ""
)

# 1. Define the Search Request
# Change the content to match your real data
test_payload = {
    "messages": [HumanMessage(content="Find me properties located in Lagos with a budget below $600k per year")],
    "transaction_context": {"property_id": None}
}

config = {"configurable": {"thread_id": "test-search-session-001"}}

# 2. Execute
try:
    print("Invoking search graph...")
    result = orchestrator.graph.invoke(test_payload, config=config)
    
    # 3. Analyze output
    last_message = result["messages"][-1]
    
    print(f"\nFinal Agent Response: {last_message.content}")
    
    # Verify if it actually queried the DB
    tool_calls = [m for m in result["messages"] if hasattr(m, "tool_calls") and m.tool_calls]
    if tool_calls:
        print("\n--- Successful Tool Usage ---")
        for tc in tool_calls[-1].tool_calls:
            print(f"Tool used: {tc['name']}")
            print(f"Args used: {tc['args']}")
    else:
        print("\nWarning: No tool was called. The agent might have answered from memory.")

except Exception as e:
    print(f"Test Failed: {e}")