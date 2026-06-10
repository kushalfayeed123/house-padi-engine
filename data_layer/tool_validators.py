from typing import Dict, Any, Optional
from dateutil import parser


def validate_add_property(args: Dict[str, Any], history: Any) -> Optional[str]:
    """
    Returns an error string if validation fails, otherwise returns None.
    """
    # 1. Check for Missing Fields
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
    # 1. Check for basic presence
    # if not args.get("property_id"):
    #     return "I need to know which property you want to tour."
    
    tour_date_raw = args.get("tour_date")
    if not tour_date_raw:
        return "Please specify the date and time for the tour (e.g., '2026-06-15 at 2:00 PM')."

    # 2. Attempt to parse the date/time string
    try:
        # fuzzy=False ensures we don't accidentally parse junk
        dt = parser.parse(tour_date_raw, fuzzy=False)
        
        # 3. Validation Logic: Check if it's in the future
        # (Optional but highly recommended)
        from datetime import datetime
        if dt < datetime.now():
            return f"The date '{tour_date_raw}' is in the past. Please provide a future date."

        # 4. Check if Time was provided
        # By default, dateutil sets missing time to 00:00:00.
        # If the input doesn't explicitly look like it contains time info, prompt for it.
        # We check if the input string contains common time indicators.
        time_indicators = ["am", "pm", ":", "o'clock", "noon", "morning", "evening"]
        if not any(indicator in str(tour_date_raw).lower() for indicator in time_indicators):
            return "Please include the specific time of day for the tour (e.g., '10:00 AM')."

    except (ValueError, OverflowError, TypeError):
        return f"I couldn't understand the date '{tour_date_raw}'. Please use a format like 'YYYY-MM-DD HH:MM'."
        
    return None


    # The Registry
TOOL_VALIDATORS = {
    "add_new_property_record": validate_add_property,
    "search_semantic_listings": validate_search,
    "schedule_tour": validate_schedule_tour

}
