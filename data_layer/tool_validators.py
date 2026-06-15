from typing import Dict, Any, Optional
from dateutil import parser


def validate_add_property(args: Dict[str, Any], history: Any) -> Optional[str]:
    """
    Returns an error string if validation fails, otherwise returns None.
    """
    # 1. Check for Missing 
    if "user_id" in args and args.get("user_id") is not None:
        return "Internal Error: Agent attempted to handle restricted identifiers."
    required = ["address", "location", "base_price", "specs", "owner_id"]
    missing = [f for f in required if not args.get(f)]
    if missing:
        return f"I'm missing: {', '.join(missing)}. Please ask the user for these details."
    
    # 2. Check for Placeholder/Hallucination Patterns
    address = str(args.get("address", "")).lower()
    placeholder_patterns = ["test", "fake", "unknown", "placeholder", "tbd", "n/a"]
    if any(p in address for p in placeholder_patterns) or len(address) < 5:
        return "The address appears to be invalid or a placeholder. Please provide a real, specific address."

    # 3. Check for invalid Price
    try:
        if float(args.get("base_price", 0)) <= 0:
            return "The base_price must be a valid, positive number."
    except (ValueError, TypeError):
        return "The base_price must be a valid numeric value."

    # 4. Check for invalid Specs
    specs = args.get("specs", {})
    if not specs or len(specs) < 1:  # Adjust length based on your requirements
        return "Missing detailed property specifications. Please provide bedroom count, bathroom count, or key amenities."

    # 5. Check for extra/unexpected keys
    allowed_keys = {"address", "location", "base_price", "specs", "owner_id"}
    extra_keys = set(args.keys()) - allowed_keys
    if extra_keys:
        return f"Invalid arguments provided: {extra_keys}. Do not invent property fields."

    return None


def validate_search(args: Dict[str, Any], history: Any) -> Optional[str]:
    # Check context: Did user mention money?
    user_text = str(history[-2].content).lower() if len(history) > 1 else ""
    price_keywords = ["naira", "million", "budget", "price", "cost", "afford"]
    
    # Check if budget is in args AND has a real value
    has_budget = "max_budget" in args and args["max_budget"] is not None
    
    if has_budget and not any(k in user_text for k in price_keywords):
        return "Do not invent a budget. If the user has not specified a price range, please ask them for their budget first."
        
    return None


def validate_schedule_tour(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate tour scheduling."""
    if not args.get("property_id"):
        return "I need to know which property you want to tour."
    
    tour_date_raw = args.get("tour_date")
    if not tour_date_raw:
        return "Please specify the date and time for the tour (e.g., 'June 15 at 2:00 PM')."

    # Check that either renter_id is provided OR both visitor_name and visitor_contact are provided
    renter_id = args.get("renter_id")
    visitor_name = args.get("visitor_name")
    visitor_contact = args.get("visitor_contact")
    
    if not renter_id and (not visitor_name or not visitor_contact):
        return "I need either your renter ID or your name and contact information to schedule the tour."
    
    return None



    # The Registry
TOOL_VALIDATORS = {
    "add_new_property_record": validate_add_property,
    "search_semantic_listings": validate_search,
    "schedule_tour": validate_schedule_tour
}


def validate_apply_for_property(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate application submission."""
    if not args.get("property_id"):
        return "I need to know which property you're applying for."
    if not args.get("renter_id"):
        return "Your user ID is required. Please log in."
    if not args.get("application_data"):
        return "Please provide information about yourself (employment, references, etc.)."
    return None


def validate_view_applications(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate landlord viewing applications."""
    if not args.get("property_id"):
        return "I need to know which property's applications you want to view."
    return None


def validate_approve_application(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate application approval."""
    if not args.get("application_id"):
        return "I need the application ID to approve."
    if not args.get("landlord_id"):
        return "Your user ID is required to approve applications."
    return None


def validate_deny_application(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate application denial."""
    if not args.get("application_id"):
        return "I need the application ID to deny."
    if not args.get("landlord_id"):
        return "Your user ID is required to deny applications."
    return None


def validate_create_lease(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate lease creation."""
    if not args.get("property_id"):
        return "I need the property ID for the lease."
    if not args.get("renter_id"):
        return "I need the renter's user ID."
    if not args.get("landlord_id"):
        return "I need the landlord's user ID."
    if not args.get("lease_terms"):
        return "I need lease terms (duration, rent amount, move-in date, etc.)."
    return None


def validate_sign_lease(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate lease signing."""
    if not args.get("lease_id"):
        return "I need the lease ID to sign."
    if not args.get("signer_id"):
        return "Your user ID is required to sign the lease."
    return None


def validate_terminate_lease(args: Dict[str, Any], history: Any) -> Optional[str]:
    """Validate lease termination."""
    if not args.get("lease_id"):
        return "I need the lease ID to terminate."
    return None


# Update the registry with new validators
TOOL_VALIDATORS.update({
    "apply_for_property": validate_apply_for_property,
    "view_applications": validate_view_applications,
    "approve_application": validate_approve_application,
    "deny_application": validate_deny_application,
    "create_lease": validate_create_lease,
    "sign_lease": validate_sign_lease,
    "terminate_lease": validate_terminate_lease
})

