import json
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool
from supabase import Client

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None

def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client

def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase_client



@tool
def get_user_profile(user_id: Optional[str] = None) -> str:
    """Retrieves current user profile. If user_id is None, returns error."""
    if not user_id:
        return json.dumps({"status": "no_session", "message": "No active user session detected."})
    
    try:
        response = _get_client().table("profiles").select("*").eq("id", user_id).single().execute()
        return json.dumps({"status": "success", "data": response.data})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def update_user_profile(updates: Dict[str, Any], user_id: Optional[str] = None) -> str:
    """Updates the profile for the current user_id."""
    if not user_id:
        return json.dumps({"status": "no_session", "message": "No active user session detected."})

    try:
        response = _get_client().table("profiles").update(updates).eq("id", user_id).execute()
        return json.dumps({"status": "success", "data": response.data})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})