"""API Provider and Router Driver Subsystem.

Auto-discovered by ask.py's _load_api_modules().
"""
from pathlib import Path
from assets.core.registry import API_REGISTRY

def get_api_driver(driver_name: str, config: dict, ctx=None):
    """Retrieve and instantiate an API driver by its registered name."""
    if driver_name not in API_REGISTRY:
        # Fallback to generic openai-compatible driver if not explicitly registered
        driver_name = "openai-compatible"

    driver_class = API_REGISTRY[driver_name]["driver_class"]
    return driver_class(driver_name, config, ctx)
