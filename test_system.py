import os
from dotenv import load_dotenv
from supabase import create_client
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from agent_engine.registry import HousePadiAgentRegistry
from data_layer.mcp_oracle import OracleMCPServer
from agent_engine.graph import PadiGraphOrchestrator

# 0. Load environment variables
load_dotenv()

# 1. Setup Infrastructure
supabase = create_client(os.getenv("SUPABASE_URL") or "", os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "")

registry = HousePadiAgentRegistry()
registry.initialize_production_agents()

oracle = OracleMCPServer(supabase_client=supabase)
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0)

orchestrator = PadiGraphOrchestrator(
    registry=registry,
    llm_client=llm,
    oracle=oracle,
    db_url=os.getenv("DATABASE_URL") or ""
)

# 2. Simulate User Request (CORRECTED: Use HumanMessage object)
test_payload = {
    "messages": [HumanMessage(content="Create a new property for me at 123 Lagos St, $500k")],
    "transaction_context": {"property_id": None}
}

config = {"configurable": {"thread_id": "unique-user-session-123"}}

# 3. Execute Workflow
try:
    # 3. Execute Workflow
    print("Invoking graph...")
    result = orchestrator.graph.invoke(test_payload, config=config)

    last_message = result["messages"][-1]

    # Print the content if it exists
    if last_message.content:
        print("Content:", last_message.content)
    else:
        print("No textual content found.")

    # Inspect if there were any tool calls requested
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print("\n--- Tool Call Detected ---")
        for tool_call in last_message.tool_calls:
            print(f"Tool Name: {tool_call['name']}")
            print(f"Arguments: {tool_call['args']}")
    else:
        print("No tool calls detected in this response.")
except Exception as e:
    print(f"Execution Failed: {e}")
