from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class AddPropertyInput(BaseModel):
    address: str = Field(description="The full address of the property")
    location: str = Field(description="The city, state, or district")
    base_price: float = Field(description="The base price of the property")
    specs: Dict[str, Any] = Field(description="Property specifications (bedrooms, bathrooms, etc.)")
    owner_id: Optional[str] = Field(default=None, description="System will auto-inject this. Leave blank.")

    @field_validator("specs")
    @classmethod
    def validate_specs(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Ensure it's not empty
        if not v:
            raise ValueError("Specs cannot be empty. Must include 'bedrooms', 'bathrooms', etc.")
        
        # 2. Optional: Ensure at least one critical key exists (or leave logic to LLM)
        required_keys = {"bedrooms"}
        if not any(k in v.keys() for k in required_keys):
             # You can raise a ValueError here to force the agent to retry with better info
             pass 
        return v
