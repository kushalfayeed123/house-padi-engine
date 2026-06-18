# data_layer/permissions.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set
import logging

from supabase import Client

logger = logging.getLogger(__name__)


@dataclass
class PermissionResult:
    allowed: bool
    reason: str = ""

    @staticmethod
    def ok() -> "PermissionResult":
        return PermissionResult(allowed=True)

    @staticmethod
    def denied(reason: str) -> "PermissionResult":
        return PermissionResult(allowed=False, reason=reason)

# ---------------------------------------------------------------------------
# Ownership rules — unchanged, still code-side checks
# ---------------------------------------------------------------------------


OwnershipRule = Callable[[Dict[str, Any], Dict[str, Any]], bool]


def _owns_property(args, ctx):
    supabase = ctx.get("_supabase_client")
    if not supabase: return True
    try:
        resp = supabase.table("properties").select("owner_id").eq("id", args.get("property_id", "")).maybe_single().execute()
        if resp and resp.data:
            return resp.data.get("owner_id") == ctx.get("current_user_id")
    except Exception:
        pass
    return False


def _owns_tour(args, ctx):
    supabase = ctx.get("_supabase_client")
    if not supabase: return True
    try:
        resp = supabase.table("tours").select("properties(owner_id)").eq("id", args.get("tour_id", "")).maybe_single().execute()
        if resp and resp.data:
            return (resp.data.get("properties") or {}).get("owner_id") == ctx.get("current_user_id")
    except Exception:
        pass
    return False


def _owns_application(args, ctx):
    supabase = ctx.get("_supabase_client")
    if not supabase: return True
    try:
        resp = supabase.table("applications").select("properties(owner_id)").eq("id", args.get("application_id", "")).maybe_single().execute()
        if resp and resp.data:
            return (resp.data.get("properties") or {}).get("owner_id") == ctx.get("current_user_id")
    except Exception:
        pass
    return False


OWNERSHIP_RULES: Dict[str, OwnershipRule] = {
    "update_property": _owns_property,
    "delete_property": _owns_property,
    "view_tour_requests": _owns_tour,
    "approve_tour_request": _owns_tour,
    "deny_tour_request": _owns_tour,
    "reschedule_tour": _owns_tour,
    "approve_application": _owns_application,
    "deny_application": _owns_application,
}

# ---------------------------------------------------------------------------
# Permission check — now hits the materialized view
# ---------------------------------------------------------------------------

# Tools that are openly accessible without authentication
PUBLIC_TOOLS = {"search_semantic_listings"}


def check_permission(
    tool_name: str,
    args: Dict[str, Any],
    ctx: Dict[str, Any],
    supabase: Client
) -> PermissionResult:
    user_id = ctx.get("current_user_id")

    # Unauthenticated access — only public tools allowed
    if not user_id:
        if tool_name in PUBLIC_TOOLS:
            return PermissionResult.ok()
        return PermissionResult.denied(
            f"You must be logged in to use '{tool_name}'."
        )

    if not supabase:
        return PermissionResult.denied("No database client available for permission check.")

    # Authenticated — check materialized view
    try:
        resp = (
            supabase.table("user_permissions")
            .select("permission")
            .eq("user_id", user_id)
            .eq("permission", tool_name)
            .maybe_single()
            .execute()
        )
        has_permission = resp is not None and resp.data is not None
    except Exception as e:
        logger.error(f"Permission lookup failed for tool='{tool_name}' user='{user_id}': {e}")
        return PermissionResult.denied("Permission check failed. Please try again.")

    if not has_permission:
        return PermissionResult.denied(
            f"You do not have permission to perform '{tool_name}'. "
            "Contact support if you believe this is an error."
        )

    # Ownership check
    ownership_rule = OWNERSHIP_RULES.get(tool_name)
    if ownership_rule:
        try:
            if not ownership_rule(args, ctx):
                return PermissionResult.denied(
                    f"Access denied: you do not own the resource targeted by '{tool_name}'."
                )
        except Exception:
            return PermissionResult.denied(
                f"Could not verify ownership for '{tool_name}'. Access denied."
            )

    return PermissionResult.ok()
