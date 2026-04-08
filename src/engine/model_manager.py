from src.engine.inference_engine import InferenceEngine

from src.core.utils import load_settings
from src.core.logger import logging
from src.core.exception import CustomException

_engine_instance = None
_engine_config = None

def get_engine():
    global _engine_instance, _engine_config
    settings = load_settings()
    current_config = settings

    if _engine_instance is None or _engine_config != current_config:
        logging.info(f"Initializing new InferenceEngine: {current_config}")
        try:
            _engine_instance = InferenceEngine(
                provider=current_config.get("provider"),
                model_name=current_config.get("model")
            )

            _engine_config = current_config
        
        except Exception as e:
            logging.error(f"Error initializing InferenceEngine: {str(e)}")
            raise CustomException(f"Failed to initialize InferenceEngine: {str(e)}")
    
    return _engine_instance

def reset_engine():
    global _engine_instance, _engine_config
    logging.info("Resetting InferenceEngine instance")
    _engine_instance = None
    _engine_config = None