# app/data_layer/mcp_oracle.py
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from supabase import Client
from data_layer import mcp_transaction, mcp_discovery



class OracleMCPServer:
    def __init__(self, supabase_client: Client, embedding_model):
        self.client = supabase_client
        self.model = embedding_model
        mcp_transaction.set_client(supabase_client)
        
        # Complete inventory of all available tools
        self._tool_map = {
            "search_semantic_listings": mcp_discovery.create_search_tool(self.model, self.client),
            "add_new_property_record": mcp_transaction.add_new_property_record,
            "fetch_property_by_uuid": mcp_transaction.fetch_property_by_uuid,
            "update_property": mcp_transaction.update_property,
            "delete_property": mcp_transaction.delete_property,
            "log_property_history": mcp_transaction.log_property_history,
            "create_inspection": mcp_transaction.create_inspection,
            "get_property_ledger": mcp_transaction.get_ledger,
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