# app/agent_engine/registry.py
import logging
from typing import Dict, List
from pydantic import BaseModel, Field, field_validator

from agent_engine.utils import load_agent_prompts

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AgentManifest(BaseModel):
    """
    Implements a strict contract defining the scope, behaviors,
    and tool allowances for any agent joining the House Padi ecosystem.
    """
    name: str = Field(
        ...,
        description="The unique alphanumeric identifier for the agent node (e.g., 'discovery')."
    )
    description: str = Field(
        ...,
        description="Natural language description outlining the exact scope of this agent. "
                    "Crucial for Padi's orchestrator routing determinations."
    )
    system_instructions: str = Field(
        ...,
        description="The absolute base behavior persona rules and prompt limits for this agent node."
    )
    authorized_mcp_tools: List[str] = Field(
        default_factory=list,
        description="Explicit string registry signatures of allowed Model Context Protocol tools."
    )

    @field_validator('name')
    @classmethod
    def validate_name_alphanumeric(cls, v: str) -> str:
        """Enforces alphanumeric naming standards to keep state graph endpoints clean."""
        if not v.isalnum():
            raise ValueError(f"Agent namespace identifier '{v}' must be strictly alphanumeric with zero punctuation.")
        return v.lower()


class HousePadiAgentRegistry:
    """
    An in-memory, thread-safe central data dictionary tracking all 
    active structural sub-agents available to Padi.
    """

    def __init__(self):
        self._registry: Dict[str, AgentManifest] = {}
        self.prompts = load_agent_prompts()

    def register_agent(self, manifest: AgentManifest) -> None:
        """Registers a verified agent configuration template into the active ecosystem runtime."""
        if manifest.name in self._registry:
            logger.warning(f"Duplicate warning: Overwriting active registry mapping for agent node: {manifest.name}")
        
        self._registry[manifest.name] = manifest
        logger.info(f"Successfully integrated agent manifest '{manifest.name}' into House Padi registry framework.")

    def resolve_agent(self, name: str) -> AgentManifest:
        """Locates an active agent manifest, dropping back to clear exception throws if invalid."""
        normalized_name = name.lower()
        if normalized_name not in self._registry:
            raise KeyError(f"Requested agent token '{name}' does not map to any active House Padi manifests.")
        return self._registry[normalized_name]

    def get_all_manifests(self) -> List[AgentManifest]:
        """Exposes every current structural manifest block for algorithmic router scanning."""
        return list(self._registry.values())
    
    def initialize_production_agents(self):
        """Pre-loads the ecosystem with core service agents."""
        ALLOWED_STATUSES = ["available", "rented", "maintenance", "pending", "archived"]
        
        manager_prompts = self.prompts.get("manager", {}).get("system_instructions", "").format(
        allowed_statuses=", ".join(ALLOWED_STATUSES)
        )
        discovery_prompts = self.prompts.get("discovery", {})
        broker_prompts = self.prompts.get("broker", {})
        identity_prompts = self.prompts.get("identity", {})
        
        # 1. Discovery
        self.register_agent(AgentManifest(
            name="discovery",
            description="Specializes in semantically searching for existing listings.",
            system_instructions=discovery_prompts.get("system_instructions", ""),
            authorized_mcp_tools=["search_semantic_listings"]
        ))

        # 2. Broker
        self.register_agent(AgentManifest(
            name="broker",
            description="Handles property onboarding only.",
            system_instructions=broker_prompts.get("system_instructions", ""),
            authorized_mcp_tools=["add_new_property_record"]
        ))

        # 3. Manager
        self.register_agent(AgentManifest(
            name="manager",
            description="Specializes in Property management tasks like updates, status changes, and maintenance scheduling.",
            system_instructions=manager_prompts,
            authorized_mcp_tools=["update_property", "fetch_property_by_uuid", "delete_property"]
        ))
        
        # 3. Identity Manager
        self.register_agent(AgentManifest(
            name="identity",
            description="Specializes in managing user profiles and settings.",
            system_instructions=identity_prompts.get("system_instructions", ""),
            authorized_mcp_tools=["get_user_profile", "update_user_profile", ]
        ))
        
        # 4. Tour Agent
        self.register_agent(AgentManifest(
            name="tour",
            description="Handles tour scheduling, updates, and confirmations.",
            system_instructions=self.prompts.get("tour", {}).get("system_instructions", ""),
            authorized_mcp_tools=["schedule_tour", "get_tour_details", "update_tour", "search_semantic_listings"]
        ))

        # 5. Renter Agent
        self.register_agent(AgentManifest(
            name="renter",
            description="Helps renters find properties, book tours, apply for leases, and manage lease agreements.",
            system_instructions=self.prompts.get("renter", {}).get("system_instructions", ""),
            authorized_mcp_tools=[
                "search_semantic_listings",
                "fetch_property_by_uuid",
                "schedule_tour",
                "get_renter_tour_requests",
                "apply_for_property",
                "get_renter_applications",
                "sign_lease",
                "get_lease_details",
                "get_active_leases",
                "get_user_profile",
                "update_user_profile"
            ]
        ))

        # 6. Landlord Agent
        self.register_agent(AgentManifest(
            name="landlord",
            description="Helps landlords manage properties, view tour requests, review applications, and manage leases.",
            system_instructions=self.prompts.get("landlord", {}).get("system_instructions", ""),
            authorized_mcp_tools=[
                "fetch_property_by_uuid",
                "view_tour_requests",
                "approve_tour_request",
                "deny_tour_request",
                "reschedule_tour",
                "view_applications",
                "view_application_details",
                "approve_application",
                "deny_application",
                "create_lease",
                "sign_lease",
                "get_lease_details",
                "get_active_leases",
                "terminate_lease",
                "get_user_profile",
                "update_user_profile"
            ]
        ))

    def is_valid_agent(self, name: str) -> bool:
        return name in self._registry
