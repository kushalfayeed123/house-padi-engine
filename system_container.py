import os
from supabase import Client, create_client
from langchain_groq import ChatGroq 
from data_layer.mcp_oracle import OracleMCPServer
from agent_engine.registry import HousePadiAgentRegistry
from agent_engine.graph import PadiGraphOrchestrator
from voice_engine.stream_handler import AudioStreamOrchestrator


class HousePadiSystem:

    def __init__(self):
        url = os.getenv("SUPABASE_URL") or ""
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
        db_url = os.getenv("DATABASE_URL") or ""  # Required for the connection pool

        if not all([url, key, db_url]):
            raise ValueError("Required environment variables (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL) are not set.")
        
        self.supabase: Client = create_client(url, key)
      
        self.oracle = OracleMCPServer(supabase_client=self.supabase)
        
        self.registry = HousePadiAgentRegistry()
        llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0)
        
        # Inject the db_pool here
        self.orchestrator = PadiGraphOrchestrator(
            registry=self.registry,
            llm_client=llm,
            oracle=self.oracle,
            db_url=db_url
        )
        
        # 5. Voice Layer
        self.voice_handler = AudioStreamOrchestrator(graph_orchestrator=self.orchestrator)
