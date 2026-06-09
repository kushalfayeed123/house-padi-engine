# app/data_layer/mcp_discovery.py
from langchain_core.tools import tool
import json

# Remove the global _model and _client variables entirely

def create_search_tool(model, client):
    """
    Factory function to create a tool instance with pre-injected dependencies.
    """
    @tool
    def search_semantic_listings(query: str, max_budget: float = 999999999999.0) -> str:
        """Scans real estate catalogs using natural text descriptions via vector similarity."""
        
        # Generate embedding using the injected model
        embedding = model.encode(query).tolist()
        
        # Call the Supabase RPC
        response = client.rpc("match_properties", {
            "query_embedding": embedding,
            "budget_limit": max_budget,
            "match_threshold": 0.5
        }).execute()
        
        return json.dumps({"status": "success", "matches": response.data})
    
    return search_semantic_listings