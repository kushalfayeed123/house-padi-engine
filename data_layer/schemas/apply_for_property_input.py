from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class ApplyForPropertyInput(BaseModel):
    property_id: str = Field(description="The ID of the property being applied for")
    application_data: Dict[str, Any] = Field(
        description="Must contain 'employment_status' and 'income_range'"
    )
    renter_id: Optional[str] = Field(None, description="INTERNAL_ONLY_DO_NOT_USE")
  
    @field_validator("application_data")
    @classmethod
    def validate_application_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Enforce specific keys
        required_keys = {"employment_status", "income_range"}
        
        # Check if keys exist and have values
        missing = [key for key in required_keys if not v.get(key)]
        
        if missing:
            raise ValueError(
                f"Missing required application details: {', '.join(missing)}. "
                "You must ask the user for their employment status and income range before submitting."
            )
            
        return v
