# app/data_layer/mcp_oracle.py
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from supabase import Client
from data_layer import mcp_property, mcp_discovery, mcp_tour, mcp_user, mcp_application, mcp_lease


class OracleMCPServer:

    def __init__(self, supabase_client: Client, embedding_provider):
        self.client = supabase_client
        self.get_embedding_model = embedding_provider
        self.model = self.get_embedding_model() 
        mcp_property.set_client(supabase_client)
        mcp_user.set_client(supabase_client)
        mcp_tour.set_client(supabase_client)
        mcp_application.set_client(supabase_client)
        mcp_lease.set_client(supabase_client)
        
        # Complete inventory of all available tools
        self._tool_map = {
            "search_semantic_listings": mcp_discovery.create_search_tool(self.model, self.client),
            "add_new_property_record": mcp_property.add_new_property_record,
            "fetch_property_by_uuid": mcp_property.fetch_property_by_uuid,
            "update_property": mcp_property.update_property,
            "delete_property": mcp_property.delete_property,
            "fetch_properties_by_owner": mcp_property.fetch_properties_by_owner,
            "get_user_profile": mcp_user.get_user_profile,
            "update_user_profile": mcp_user.update_user_profile,
            "schedule_tour": mcp_tour.schedule_tour,
            "get_tour_details": mcp_tour.get_tour_details,
            "update_tour": mcp_tour.update_tour,
            "view_tour_requests": mcp_tour.view_tour_requests,
            "approve_tour_request": mcp_tour.approve_tour_request,
            "deny_tour_request": mcp_tour.deny_tour_request,
            "reschedule_tour": mcp_tour.reschedule_tour,
            "get_renter_tour_requests": mcp_tour.get_renter_tour_requests,
            "apply_for_property": mcp_application.apply_for_property,
            "view_applications": mcp_application.view_applications,
            "view_application_details": mcp_application.view_application_details,
            "approve_application": mcp_application.approve_application,
            "deny_application": mcp_application.deny_application,
            "get_renter_applications": mcp_application.get_renter_applications,
            "create_lease": mcp_lease.create_lease,
            "sign_lease": mcp_lease.sign_lease,
            "get_lease_details": mcp_lease.get_lease_details,
            "get_active_leases": mcp_lease.get_active_leases,
            "terminate_lease": mcp_lease.terminate_lease
        }

    def get_all_tools(self) -> List[Any]:
        """Expose all tools to the LLM to prevent 400 Bad Request/validation errors."""
        return list(self._tool_map.values())

    def get_tools_by_name(self, names: List[str]) -> List[Any]:
        return [self._tool_map[name] for name in names if name in self._tool_map]

    def execute_tool(self, tool_type: str, arguments: Dict[str, Any]) -> Any:
        """Internal dispatcher for system-level context fetching."""
        if tool_type == "context_fetcher":
            return {"status": "active_session"}
        return {"error": "Tool not found"}
