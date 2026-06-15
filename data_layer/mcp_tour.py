import json
import logging
from typing import Dict, Any, Optional, cast
from langchain_core.tools import tool
from pydantic import BaseModel
from supabase import Client
from datetime import datetime

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None

def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client

def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase_client


class GetTourDetailsSchema(BaseModel):
    tour_id: str

@tool
def schedule_tour(
    property_id: str, 
    tour_date: str,
    renter_id: Optional[str] = None,
    visitor_name: Optional[str] = None,
    visitor_contact: Optional[str] = None
) -> Dict[str, Any]:
    """Schedules a new property tour. tour_date format: YYYY-MM-DDTHH:MM:SS or natural language like '2026-06-15 at 2:00 PM'"""
    client = _get_client()
    try:
        # If renter_id is provided, fetch user details from profile
        if renter_id:
            user_response = client.table("profiles").select("*").eq("id", renter_id).maybe_single().execute()
            if user_response is not None and user_response.data:
                user_data = cast(Dict[str, Any], user_response.data)
                visitor_name = user_data.get("name", "Unknown Visitor")
                visitor_contact = user_data.get("email") or user_data.get("phone", "N/A")
            else:
                return {"status": "ERROR", "message": "Renter profile not found."}
        
        # Validate required fields
        if not visitor_name or not visitor_contact:
            return {"status": "ERROR", "message": "Visitor name and contact information are required."}
        
        response = client.table("tours").insert({
            "property_id": property_id,
            "visitor_id": renter_id,
            "visitor_name": visitor_name,
            "visitor_contact": visitor_contact,
            "tour_date": tour_date,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        if response.data:
            item = cast(Dict[str, Any], response.data[0])
            return {"status": "SUCCESS", "tour_id": item.get("id"), "message": "Tour scheduled successfully. The landlord will confirm shortly."}
        return {"status": "ERROR", "message": "Failed to schedule tour."}
    except Exception as e:
        logger.error(f"Schedule tour error: {e}")
        return {"status": "ERROR", "message": str(e)}

@tool(args_schema=GetTourDetailsSchema)
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


@tool
def view_tour_requests(property_id: str) -> Dict[str, Any]:
    """Landlord views all tour requests for a property."""
    client = _get_client()
    try:
        response = client.table("tours").select("*").eq("property_id", property_id).execute()
        if response.data:
            return {"status": "SUCCESS", "tour_requests": response.data, "count": len(response.data)}
        return {"status": "SUCCESS", "tour_requests": [], "count": 0, "message": "No tour requests yet."}
    except Exception as e:
        logger.error(f"View tour requests error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def approve_tour_request(tour_id: str) -> Dict[str, Any]:
    """Landlord approves a tour request."""
    client = _get_client()
    try:
        response = client.table("tours").update({"status": "approved"}).eq("id", tour_id).execute()
        if response.data:
            return {"status": "SUCCESS", "message": "Tour approved. Visitor will receive confirmation."}
        return {"status": "ERROR", "message": "Failed to approve tour."}
    except Exception as e:
        logger.error(f"Approve tour request error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def deny_tour_request(tour_id: str, reason: str = "") -> Dict[str, Any]:
    """Landlord denies a tour request."""
    client = _get_client()
    try:
        response = client.table("tours").update({
            "status": "denied",
            "denial_reason": reason
        }).eq("id", tour_id).execute()
        if response.data:
            return {"status": "SUCCESS", "message": "Tour request denied."}
        return {"status": "ERROR", "message": "Failed to deny tour request."}
    except Exception as e:
        logger.error(f"Deny tour request error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def reschedule_tour(tour_id: str, new_date: str) -> Dict[str, Any]:
    """Landlord reschedules a tour to a new date."""
    client = _get_client()
    try:
        response = client.table("tours").update({
            "tour_date": new_date,
            "status": "rescheduled"
        }).eq("id", tour_id).execute()
        if response.data:
            return {"status": "SUCCESS", "message": "Tour rescheduled successfully."}
        return {"status": "ERROR", "message": "Failed to reschedule tour."}
    except Exception as e:
        logger.error(f"Reschedule tour error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def get_renter_tour_requests(renter_id: str) -> Dict[str, Any]:
    """Renter views all their tour requests."""
    client = _get_client()
    try:
        response = client.table("tours").select("*").eq("visitor_id", renter_id).execute()
        if response.data:
            return {"status": "SUCCESS", "tours": response.data, "count": len(response.data)}
        return {"status": "SUCCESS", "tours": [], "count": 0, "message": "You have no tour requests yet."}
    except Exception as e:
        logger.error(f"Get renter tour requests error: {e}")
        return {"status": "ERROR", "message": str(e)}
