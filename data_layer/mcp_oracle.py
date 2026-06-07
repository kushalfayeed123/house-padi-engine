# app/data_layer/mcp_oracle.py
from data_layer.mcp_discovery import DiscoveryMCPServer
from data_layer.mcp_transaction import TransactionMCPServer
from supabase import Client, create_client


class OracleMCPServer:

    def __init__(self, supabase_client: Client):
        self.client = supabase_client        # Concrete implementation of orphan servers
        self.discovery = DiscoveryMCPServer(self.client)
        self.transactions = TransactionMCPServer()

    def execute_tool(self, tool_type: str, arguments: dict):
        """Dispatches work to specific MCP servers based on intent."""
        if tool_type == "discovery":
            return self.discovery.execute_tool(arguments)
        if tool_type == "transaction":
            return self.transactions.execute_tool(arguments)
        # Default fallback to Supabase-backed operational context
        return self._fetch_core_context(arguments)

    def _fetch_core_context(self, args: dict):
        # Implementation from your previous oracle code
        return self.client.table("properties").select("*").eq("id", args.get("property_id")).execute().data
