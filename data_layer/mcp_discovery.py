import json
from typing import List, Dict, Any, cast, Optional
from langchain_core.tools import tool
from sentence_transformers import SentenceTransformer
from supabase import Client

# Use Optional so the type checker understands it starts as None
_client: Optional[Client] = None
_model: Optional[SentenceTransformer] = None

def set_discovery_resources(client: Client) -> None:
    global _client, _model
    _client = client
    _model = SentenceTransformer('all-MiniLM-L6-v2')

def _get_resources() -> tuple[Client, SentenceTransformer]:
    """Helper to ensure resources are initialized before use."""
    if _client is None or _model is None:
        raise RuntimeError("Discovery MCP resources not initialized. Call set_discovery_resources() first.")
    return _client, _model

@tool
def search_semantic_listings(query: str, max_budget: float = 999999999999.0) -> str:
    """
    Scans real estate catalogs using natural text descriptions via vector similarity.
    """
    client, model = _get_resources()
    
    # Generate embedding
    embedding = model.encode(query).tolist()
    
    # Call the Supabase RPC
    response = client.rpc("match_properties", {
        "query_embedding": embedding,
        "budget_limit": max_budget,
        "match_threshold": 0.5
    }).execute()
    
    # Cast explicitly to avoid JSON structure warnings
    return json.dumps({"status": "success", "matches": response.data})