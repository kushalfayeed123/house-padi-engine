import os
from sentence_transformers import SentenceTransformer
from supabase import Client, create_client
from langchain_groq import ChatGroq 
from data_layer.mcp_oracle import OracleMCPServer
from agent_engine.registry import HousePadiAgentRegistry
from agent_engine.graph import PadiGraphOrchestrator
from voice_engine.stream_handler import AudioStreamOrchestrator
import logging
logger = logging.getLogger(__name__)


class HousePadiSystem:

    def __init__(self):
        required_vars = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL"]
        if not all(os.getenv(v) for v in required_vars):
            raise ValueError(f"Missing one of required vars: {required_vars}")
        self.supabase = create_client(os.getenv("SUPABASE_URL") or "", os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "")      
        shared_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.oracle = OracleMCPServer(supabase_client=self.supabase, embedding_model=shared_model)
        
        self.registry = HousePadiAgentRegistry()
        self.registry.initialize_production_agents()
        llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.1, max_tokens=1024)
        
        # Inject the db_pool here
        self.orchestrator = PadiGraphOrchestrator(
            registry=self.registry,
            llm_client=llm,
            oracle=self.oracle,
            db_url=os.getenv("DATABASE_URL") or ""
        )
        
        # 5. Voice Layer
        self.voice_handler = AudioStreamOrchestrator(graph_orchestrator=self.orchestrator)
        
    def run_health_check(self):
        """Verifies external service connectivity before accepting traffic."""
        logger.info("Performing system health check...")
        
        # 1. Supabase Ping
        try:
            self.supabase.table("properties").select("id").limit(1).execute()
            logger.info("✅ Supabase connection verified.")
        except Exception as e:
            raise ConnectionError(f"Supabase unreachable: {e}")

        # 2. Key Presence Checks (Verify config exists)
        if not os.getenv("DEEPGRAM_API_KEY"):
            raise EnvironmentError("DEEPGRAM_API_KEY missing.")
        if not os.getenv("CARTESIA_API_KEY"):
            raise EnvironmentError("CARTESIA_API_KEY missing.")
            
        logger.info("✅ Voice Service Configs validated.")
