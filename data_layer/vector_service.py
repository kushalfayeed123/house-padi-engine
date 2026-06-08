# app/services/vector_service.py
from sentence_transformers import SentenceTransformer
from typing import Dict, Any

# Load globally or in a factory to avoid reloading
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


def vectorize_property_data(address: str, location: str, specs: Dict[str, Any]) -> list[float]:
    """
    Creates a semantic string from property data and returns the embedding.
    """
    # Create a dense text representation of the property for better search results
    context_string = f"Address: {address}. Location: {location}. Features: {str(specs)}"    
    embedding = get_model().encode(context_string)
    return embedding.tolist()