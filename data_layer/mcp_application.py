import json
import logging
from typing import Dict, Any, List, Optional, cast
import uuid
from langchain_core.tools import tool
from supabase import Client
from datetime import datetime

from data_layer.schemas.apply_for_property_input import ApplyForPropertyInput

_supabase_client: Optional[Client] = None
logger = logging.getLogger(__name__)


def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client


def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase_client


@tool(args_schema=ApplyForPropertyInput)
def apply_for_property(property_id: str,  application_data: Dict[str, Any], renter_id: Optional[str]=None) -> Dict[str, Any]:
    """Renter submits an application for a property."""
    client = _get_client()
    if not renter_id:
        return {"status": "ERROR", "message": "Authentication required."}
    try:
        response = client.table("applications").insert({
            "property_id": property_id,
            "renter_id": renter_id,
            "status": "pending",
            "metadata": application_data,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        if response.data:
            item = cast(Dict[str, Any], response.data[0])
            return {"status": "SUCCESS", "application_id": item.get("id"), "message": "Application submitted successfully."}
        return {"status": "ERROR", "message": "Failed to submit application."}
    except Exception as e:
        logger.error(f"Application submission error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def view_applications(property_id: str) -> Dict[str, Any]:
    """Landlord views all applications for a property."""
    client = _get_client()
    try:
        response = client.table("applications").select("*").eq("property_id", property_id).execute()
        if response.data:
            return {"status": "SUCCESS", "applications": response.data, "count": len(response.data)}
        return {"status": "SUCCESS", "applications": [], "count": 0, "message": "No applications yet."}
    except Exception as e:
        logger.error(f"View applications error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def view_application_details(application_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific application."""
    client = _get_client()
    
    # Debugging check: Is the client even initialized?
    if client is None:
        return {"status": "ERROR", "message": "Database client not initialized."}

    try:
        response = client.table("applications").select("*").eq("id", application_id).maybe_single().execute()
        
        # Defensive check: Ensure response is not None before accessing attributes
        if response is not None and hasattr(response, 'data') and response.data:
            return {"status": "SUCCESS", "application": response.data}
            
        return {"status": "ERROR", "message": "Application not found or response was empty."}
        
    except Exception as e:
        logger.error(f"View application details error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def approve_application(application_id: str, landlord_id: str) -> Dict[str, Any]:
    """Landlord approves a renter's application."""
    client = _get_client()
    try:
        response = client.table("applications").update({
            "status": "approved",
            "approved_by": landlord_id,
            "approved_at": datetime.utcnow().isoformat()
        }).eq("id", application_id).execute()

        if response.data:
            return {"status": "SUCCESS", "message": "Application approved. A lease will be prepared."}
        return {"status": "ERROR", "message": "Failed to approve application."}
    except Exception as e:
        logger.error(f"Approve application error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def deny_application(application_id: str, landlord_id: str, reason: str="") -> Dict[str, Any]:
    """Landlord denies a renter's application."""
    client = _get_client()
    try:
        response = client.table("applications").update({
            "status": "denied",
            "denied_by": landlord_id,
            "denial_reason": reason,
            "denied_at": datetime.utcnow().isoformat()
        }).eq("id", application_id).execute()

        if response.data:
            return {"status": "SUCCESS", "message": "Application denied."}
        return {"status": "ERROR", "message": "Failed to deny application."}
    except Exception as e:
        logger.error(f"Deny application error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def get_renter_applications(renter_id: str) -> Dict[str, Any]:
    """Renter views all their applications."""
    client = _get_client()
    try:
        response = client.table("applications").select("*").eq("renter_id", renter_id).execute()
        if response.data:
            return {"status": "SUCCESS", "applications": response.data, "count": len(response.data)}
        return {"status": "SUCCESS", "applications": [], "count": 0, "message": "You have no applications yet."}
    except Exception as e:
        logger.error(f"Get renter applications error: {e}")
        return {"status": "ERROR", "message": str(e)}
