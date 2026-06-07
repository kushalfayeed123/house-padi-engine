import logging
from typing import Dict, List, Any, cast
import openai
from pydantic import BaseModel, Field
from supabase import Client

logger = logging.getLogger(__name__)


class SemanticSearchSchema(BaseModel):
    query: str = Field(..., description="The semantic descriptor (e.g., 'abundant natural lighting').")
    max_budget: float = Field(default=float('inf'), description="Maximum currency cap value.")


class DiscoveryMCPServer:

    def __init__(self, supabase_client: Client):
        # We inject the client here, established in main.py/container
        self.client = supabase_client
        self.openai_client = openai.OpenAI()  # Uses OPENAI_API_KEY from env

    def get_tool_signature(self) -> Dict[str, Any]:
        return {
            "name": "search_semantic_listings",
            "description": "Scans real estate catalogs using natural text descriptions via pgvector.",
            "parameters": SemanticSearchSchema.model_json_schema()
        }

    def execute_tool(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            validated_args = SemanticSearchSchema(**arguments)
            
            # 1. Generate embedding for the user's natural language query
            embedding_response = self.openai_client.embeddings.create(
                input=validated_args.query,
                model="text-embedding-3-small"
            )
            query_embedding = embedding_response.data[0].embedding
            
            # 2. Call the Supabase RPC
            response = self.client.rpc(
                "match_properties",
                {
                    "query_embedding": query_embedding,
                    "budget_limit": validated_args.max_budget,
                    "match_threshold": 0.5
                }
            ).execute()
            
            return cast(List[Dict[str, Any]], response.data or [])
            
        except Exception as e:
            logger.error(f"Vector search failed: {str(e)}")
            return []
