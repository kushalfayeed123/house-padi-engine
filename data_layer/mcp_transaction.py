import json
from typing import Dict, Any, List, Optional, cast
import uuid
from langchain_core.tools import tool
from supabase import Client

# Global state initialized safely
_supabase_client: Optional[Client] = None


def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client


def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized. Call set_client() before using tools.")
    return _supabase_client

# --- Core Tools ---


@tool
def create_property(address: str, base_price: float, internal_code: Optional[str], specs: Dict[str, Any]) -> str:
    """Creates a new property record and returns the new property ID."""
    client = _get_client()
    
    # Auto-generate code if missing for better UX
    if not internal_code:
        internal_code = f"PROP-{uuid.uuid4().hex[:6].upper()}"
        
    response = client.table("properties").insert({
        "address": address,
        "base_price": base_price,
        "internal_code": internal_code,
        "specs": specs or {}
    }).execute()
    raw_item = response.data[0]
    
    item = cast(Dict[str, Any], raw_item)
    
    return json.dumps({"status": "SUCCESS", "id": item['id']})


@tool
def get_property_details(property_id: str) -> Dict[str, Any]:
    """Fetches full metadata and current status for a specific property."""
    client = _get_client()
    response = client.table("properties").select("*").eq("id", property_id).single().execute()
    return cast(Dict[str, Any], response.data) if response.data else {}


@tool
def update_property(property_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates property fields (e.g., status, price, owner)."""
    client = _get_client()
    response = client.table("properties").update(update_data).eq("id", property_id).execute()
    data = cast(List[Any], response.data)
    return cast(Dict[str, Any], data[0]) if data else {"status": "SUCCESS"}


@tool
def delete_property(property_id: str) -> Dict[str, Any]:
    """Soft deletes a property record."""
    client = _get_client()
    client.table("properties").update({"deleted_at": "now()"}).eq("id", property_id).execute()
    return {"status": "SUCCESS"}


@tool
def log_property_history(property_id: str, event_type: str, payload: Dict[str, Any]) -> str:
    """Logs an event (e.g., 'creation', 'inspection') to the property history."""
    client = _get_client()
    client.table("property_history").insert({
        "property_id": property_id,
        "event_type": event_type,
        "payload": payload
    }).execute()
    return json.dumps({"status": "LOGGED"})


@tool
def create_inspection(property_id: str, inspector_name: str, date: str) -> Dict[str, Any]:
    """Schedules a new property inspection."""
    client = _get_client()
    response = client.table("inspections").insert({
        "property_id": property_id, "inspector": inspector_name, "scheduled_date": date
    }).execute()
    data = cast(List[Any], response.data)
    return cast(Dict[str, Any], data[0]) if data else {"status": "SUCCESS"}


@tool
def get_property_ledger(property_id: str) -> List[Dict[str, Any]]:
    """Retrieves all financial and maintenance records for a property."""
    client = _get_client()
    response = client.table("ledger").select("*").eq("property_id", property_id).execute()
    return cast(List[Dict[str, Any]], response.data) if response.data else []
