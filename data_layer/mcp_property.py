import json
import logging
from typing import Dict, Any, List, Optional, cast
import uuid
from langchain_core.tools import tool
from supabase import Client
from data_layer.schemas.add_property_input import AddPropertyInput
from data_layer.vector_service import vectorize_property_data

# Global state initialized safely
_supabase_client: Optional[Client] = None
logger = logging.getLogger(__name__)


def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client


def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized. Call set_client() before using tools.")
    return _supabase_client


def format_tool_output(data: Any) -> str:
    """Ensures tool output is a JSON string, handling potential errors."""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        return str(data)

# --- Core Tools ---


@tool(args_schema=AddPropertyInput)
def add_new_property_record(address: str,
    location: str,
    base_price: float,
    owner_id: str,
    specs: Dict[str, Any]) -> str:
    """Creates a new property record and returns the new property ID."""
    client = _get_client()
    
    # 1. CHECK FOR EXISTING (Defensive)
    try:
        existing = client.table("properties").select("id").eq("address", address).execute()
        # Verify if data exists BEFORE accessing index 0
        raw_data = existing.data
        if isinstance(raw_data, list) and len(raw_data) > 0:
            item = cast(Dict[str, Any], raw_data[0])
            
            return json.dumps({"status": "ALREADY_EXISTS", "id": item['id']})
    except Exception as e:
        logger.error(f"Error checking for existing property: {e}")
        # Proceed to creation or return error; usually safer to let it try to create if check fails
    
    # 2. CREATE
    
    safe_specs = specs or {}
        
    try:
        response = client.table("properties").insert({
            "address": address,
            "base_price": base_price,
            "location": location,  # New field
            "specs": safe_specs,
            "owner_id": owner_id
        }).execute()
        
        if not response.data:
            return json.dumps({"status": "ERROR", "message": "Failed to insert property"})
            
        item = cast(Dict[str, Any], response.data[0])
        property_id = item['id']
        
        # 3. VECTORIZE
        try:
            embedding = vectorize_property_data(address, owner_id, location, specs)
            client.table("properties").update({
                "vector_embedding": embedding
            }).eq("id", property_id).execute()
        except Exception as e:
            logger.error(f"Vectorization failed for {property_id}: {e}")
            # We continue because the property is already created
        
        return json.dumps({"status": "SUCCESS", "id": property_id})
        
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


@tool
def fetch_property_by_uuid(property_id: str) -> Dict[str, Any]:
    """
   REQUIRED: Provide a specific property_id (UUID).
    DO NOT use this tool to add, create, or register new properties.
    If you have creation data (address, price, features), you must use 'add_new_property_record'.
    """
    client = _get_client()
    response = client.table("properties").select("*").eq("id", property_id).maybe_single().execute()
    if response is None:
        return {"error": "Internal Database Error"}
        
    # 2. Handle missing data (maybe_single returns None for data if not found)
    if response.data is None:
        return {"error": "Property not found"}
        
    # 3. Explicitly cast the dynamic 'data' to the expected Dict[str, Any]
    # This silences the type checker and confirms you are handling the dynamic return
    return cast(Dict[str, Any], response.data)


@tool
def update_property(property_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates property fields."""
    if not is_valid_uuid(property_id):
        raise ValueError(f"Invalid UUID: {property_id}")
        
    client = _get_client()
    response = client.table("properties").update(update_data).eq("id", property_id).execute()
    
    # Defensive list access
    if response.data and len(response.data) > 0:
        return cast(Dict[str, Any], response.data[0])
    
    return {"status": "ERROR", "message": "Property not found or update failed"}


@tool
def delete_property(property_id: str) -> Dict[str, Any]:
    """Soft deletes a property record."""
    if not is_valid_uuid(property_id):
        raise ValueError(f"Agent attempted to use an invalid property ID: {property_id}. "
                         "This is likely a hallucinated placeholder.")
    client = _get_client()
    client.table("properties").update({"deleted_at": "now()"}).eq("id", property_id).execute()
    return {"status": "SUCCESS"}


