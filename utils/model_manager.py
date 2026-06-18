import os
import logging
from sentence_transformers import SentenceTransformer
import threading

logger = logging.getLogger(__name__)


class ModelManager:
    _model = None
    _lock = threading.Lock()
    
    @classmethod
    @classmethod
    def get_model(cls):
        """Lazy loads the model only when requested."""
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    is_debug = os.getenv("DEBUG", "False").lower() == "true"
                    
                    if is_debug:
                        cache_path = os.path.abspath("./models_cache")
                        os.makedirs(cache_path, exist_ok=True)
                        logger.info(f"🐛 Debug mode ON: Enforcing strictly offline load from {cache_path}")
                        
                        # Fix: Pass cache_folder and local_files_only parameter inline 
                        cls._model = SentenceTransformer(
                            'all-MiniLM-L6-v2',
                            cache_folder=cache_path,
                            local_files_only=True
                        )
                    else:
                        logger.info("🚀 Production mode: Using default system cache.")
                        cls._model = SentenceTransformer('all-MiniLM-L6-v2')
                        
                    logger.info("✅ Model loaded.")
        return cls._model
