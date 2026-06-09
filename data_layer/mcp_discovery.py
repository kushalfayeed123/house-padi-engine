import logging
from typing import Optional
from langchain_core.tools import tool
import json
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchInput(BaseModel):
    query: str = Field(..., description="The natural language query describing the property.")
    max_budget: Optional[float] = Field(None, description="The maximum budget. Do not invent one.")
    # Add filters to the schema so the LLM knows it can extract them
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Dynamic filters for specific attributes (e.g., {'bedrooms': 4, 'pool': true})."
    )


def create_search_tool(model, client):
    @tool(args_schema=SearchInput)
    def search_semantic_listings(
        query: str, 
        max_budget: Optional[float] = None, 
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Scans real estate catalogs using natural language and optional feature filters.
        Use this when a user describes a property (e.g., '3 bedroom house in Lekki') 
        or requests specific features.
        """
        try:
            logger.info(f"Searching: '{query}' | Budget: {max_budget} | Filters: {filters}")
            
            # 1. Generate embedding
            embedding = model.encode(query).tolist()
            
            # 2. Call Supabase RPC
            # Ensure filters is a dict; if None, default to an empty dict
            response = client.rpc("match_properties", {
                "query_embedding": embedding,
                "budget_limit": max_budget,
                "match_threshold": 0.4,
                "filters": filters or {} 
            }).execute()
            
            if not response.data:
                return json.dumps({
                    "status": "no_results",
                    "message": "No properties found matching these criteria."
                })
            
            return json.dumps({"status": "success", "matches": response.data})
            
        except Exception as e:
            logger.error(f"Search tool failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})
    
    return search_semantic_listings
