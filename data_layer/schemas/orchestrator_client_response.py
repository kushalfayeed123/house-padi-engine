from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class OrchestratorClientResponse(BaseModel):
    success: bool = Field(
        ...,
        description="Indicates if the transaction execution block processed without unhandled framework crashes."
    )
    agent: str = Field(
        ...,
        description="The active or finalizing agent that processed this turn (e.g., 'broker', 'landlord', 'human_handoff')."
    )
    message: str = Field(
        ...,
        description="The clean, natural language text output prepared specifically for display to the end-user."
    )
    requires_action: bool = Field(
        False,
        description="Flags whether the system hit a checkpoint requiring user input, clarification, or interactive manual routing changes."
    )
    error: Optional[str] = Field(
        None,
        description="The operational system error message description if success is false, or null if the block runs clean."
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized state sync metadata passed back to help keep the client view state aligned with the backend."
    )
