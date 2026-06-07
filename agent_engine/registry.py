# app/agent_engine/registry.py
import logging
from typing import Dict, List
from pydantic import BaseModel, Field, field_validator

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
    
    # Add this to your HousePadiAgentRegistry class
    def initialize_production_agents(self):
        """Pre-loads the ecosystem with core service agents."""
        
        # 1. Discovery Agent: Read-only search
        self.register_agent(AgentManifest(
            name="discovery",
            description="Specializes in semantic property search and market filtering.",
            system_instructions="You are the Discovery Expert. Use search_semantic_listings. DO NOT create properties.",
            authorized_mcp_tools=["search_semantic_listings"]
        ))

        # 2. Broker Agent: Handles property lifecycle creation
        self.register_agent(AgentManifest(
            name="broker",
            description="Handles property onboarding and initial auditing.",
            system_instructions=(
                "You are the Property Broker. "
                "CRITICAL RULE: If you do not have a specific internal code for a property, "
                "YOU MUST pass an empty string ('') for the 'internal_code' parameter. "
                "Do not pass null or leave the field empty."
                    ),
            authorized_mcp_tools=["create_property", "log_property_history"]
        ))
        
        # 3. Manager Agent: Operational maintenance
        self.register_agent(AgentManifest(
            name="manager",
            description="Specializes in maintenance, inspections, and lease management.",
            system_instructions="You are the Property Manager.",
            authorized_mcp_tools=["log_maintenance", "get_property_ledger", "create_inspection"]
        ))
