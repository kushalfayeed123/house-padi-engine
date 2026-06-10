import json
import logging
from typing import Dict, Any, Optional, cast
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
def schedule_tour(
    property_id: str, 
    visitor_name: str, 
    visitor_contact: str, 
    tour_date: str
) -> str:
    """Schedules a new property tour. tour_date format: YYYY-MM-DDTHH:MM:SSZ"""
    client = _get_client()
    try:
        response = client.table("tours").insert({
            "property_id": property_id,
            "visitor_name": visitor_name,
            "visitor_contact": visitor_contact,
            "tour_date": tour_date,
            "status": "pending"
        }).execute()
        return json.dumps({"status": "SUCCESS", "data": response.data[0]})
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})

@tool
def get_tour_details(tour_id: str) -> str:
    """Fetches details of a specific tour by ID."""
    try:
        client = _get_client()
        response = client.table("tours").select("*, properties(address)").eq("id", tour_id).maybe_single().execute()
        
        if response is None:
            return "error: Internal Database Error"
        if response.data is None:
            return "error: Tour not found"
        return json.dumps({"status": "SUCCESS", "data": response.data})
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})

@tool
def update_tour(tour_id: str, status: str) -> str:
    """Updates the status of a tour (e.g., 'confirmed', 'cancelled')."""
    client = _get_client()
    response = client.table("tours").update({"status": status}).eq("id", tour_id).execute()
    if not response.data:
        return json.dumps({"status": "ERROR", "message": "Update failed"})
    return json.dumps({"status": "SUCCESS"})