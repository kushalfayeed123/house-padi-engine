import os
from supabase import Client, create_client
from langchain_groq import ChatGroq 
from data_layer.mcp_oracle import OracleMCPServer
from agent_engine.registry import HousePadiAgentRegistry
from agent_engine.graph import PadiGraphOrchestrator
from voice_engine.stream_handler import AudioStreamOrchestrator


class HousePadiSystem:

    def __init__(self):
        # 1. Centralized Database Initialization
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url:
            raise ValueError("Environment variable 'SUPABASE_URL' is not set.")
        if not key:
            raise ValueError("Environment variable 'SUPABASE_SERVICE_ROLE_KEY' is not set.")
        
        self.supabase: Client = create_client(url, key)
        
        # 2. Data Layer Injection
        self.oracle = OracleMCPServer(supabase_client=self.supabase)
        
        # 3. Registry & Reasoning Layer
        self.registry = HousePadiAgentRegistry()
        llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0)
        self.orchestrator = PadiGraphOrchestrator(
            registry=self.registry,
            llm_client=llm,
            oracle=self.oracle
        )
        
        # 4. Voice Layer
        self.voice_handler = AudioStreamOrchestrator(graph_orchestrator=self.orchestrator)
