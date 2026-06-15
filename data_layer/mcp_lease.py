import json
import logging
from typing import Dict, Any, Optional, cast
from langchain_core.tools import tool
from supabase import Client
from datetime import datetime

_supabase_client: Optional[Client] = None
logger = logging.getLogger(__name__)


def set_client(client: Client) -> None:
    global _supabase_client
    _supabase_client = client


def _get_client() -> Client:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase_client


@tool
def create_lease(property_id: str, renter_id: str, landlord_id: str, lease_terms: Dict[str, Any]) -> Dict[str, Any]:
    """Create a lease contract after application is approved."""
    client = _get_client()
    try:
        response = client.table("leases").insert({
            "property_id": property_id,
            "renter_id": renter_id,
            "landlord_id": landlord_id,
            "lease_terms": lease_terms,
            "status": "unsigned",
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        if response.data:
            item = cast(Dict[str, Any], response.data[0])
            return {"status": "SUCCESS", "lease_id": item.get("id"), "message": "Lease created and sent for signing."}
        return {"status": "ERROR", "message": "Failed to create lease."}
    except Exception as e:
        logger.error(f"Create lease error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def sign_lease(lease_id: str, signer_id: str) -> Dict[str, Any]:
    """Renter or landlord signs the lease contract."""
    client = _get_client()
    try:
        response = client.table("leases").select("*").eq("id", lease_id).maybe_single().execute()
        if not response.data:
            return {"status": "ERROR", "message": "Lease not found."}

        lease = cast(Dict[str, Any], response.data)
        signed_by = lease.get("signed_by", {})
        if not isinstance(signed_by, dict):
            signed_by = {}
        signed_by[signer_id] = datetime.utcnow().isoformat()

        # Check if both parties have signed
        is_fully_signed = len(signed_by) >= 2

        update_response = client.table("leases").update({
            "signed_by": signed_by,
            "status": "signed" if is_fully_signed else "partially_signed",
            "signed_at": datetime.utcnow().isoformat() if is_fully_signed else None
        }).eq("id", lease_id).execute()

        if update_response.data:
            message = "Lease fully signed and agreement is now active!" if is_fully_signed else "Lease signature recorded. Awaiting other party's signature."
            return {"status": "SUCCESS", "message": message}
        return {"status": "ERROR", "message": "Failed to sign lease."}
    except Exception as e:
        logger.error(f"Sign lease error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def get_lease_details(lease_id: str) -> Dict[str, Any]:
    """Get the details of a lease contract."""
    client = _get_client()
    try:
        response = client.table("leases").select("*").eq("id", lease_id).maybe_single().execute()
        if response.data:
            return {"status": "SUCCESS", "lease": response.data}
        return {"status": "ERROR", "message": "Lease not found."}
    except Exception as e:
        logger.error(f"Get lease details error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def get_active_leases(user_id: str) -> Dict[str, Any]:
    """Get all active leases for a user (as renter or landlord)."""
    client = _get_client()
    try:
        renter_leases = client.table("leases").select("*").eq("renter_id", user_id).eq("status", "signed").execute()
        landlord_leases = client.table("leases").select("*").eq("landlord_id", user_id).eq("status", "signed").execute()
        
        all_leases = (renter_leases.data or []) + (landlord_leases.data or [])
        return {"status": "SUCCESS", "leases": all_leases, "count": len(all_leases)}
    except Exception as e:
        logger.error(f"Get active leases error: {e}")
        return {"status": "ERROR", "message": str(e)}


@tool
def terminate_lease(lease_id: str, reason: str = "") -> Dict[str, Any]:
    """Terminate an active lease."""
    client = _get_client()
    try:
        response = client.table("leases").update({
            "status": "terminated",
            "termination_reason": reason,
            "terminated_at": datetime.utcnow().isoformat()
        }).eq("id", lease_id).execute()

        if response.data:
            return {"status": "SUCCESS", "message": "Lease terminated."}
        return {"status": "ERROR", "message": "Failed to terminate lease."}
    except Exception as e:
        logger.error(f"Terminate lease error: {e}")
        return {"status": "ERROR", "message": str(e)}
