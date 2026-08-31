from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any

class BaseApiDriver(ABC):
    """Abstract base class for all API backends and router daemons."""

    def __init__(self, name: str, config: Dict[str, Any], ctx=None):
        self.name = name
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def is_running(self) -> bool:
        """Check if the backend daemon/endpoint is running and reachable."""
        pass

    async def start_daemon(self) -> Tuple[bool, str]:
        """Start the background daemon process if applicable."""
        return False, f"Starting a daemon is not supported by driver '{self.name}'."

    async def stop_daemon(self) -> Tuple[bool, str]:
        """Stop the background daemon process if applicable."""
        return False, f"Stopping a daemon is not supported by driver '{self.name}'."

    async def list_available_models(self) -> List[str]:
        """List all models available on disk or exposed by the service."""
        return []

    async def list_loaded_models(self) -> List[str]:
        """List models currently loaded in memory/router."""
        return []

    async def load_model(self, model_name: str) -> Tuple[bool, str]:
        """Load a specific model into memory/router."""
        return False, f"Dynamic model loading is not supported by driver '{self.name}'."

    async def unload_model(self, model_name: str) -> Tuple[bool, str]:
        """Unload a specific model from memory/router."""
        return False, f"Dynamic model unloading is not supported by driver '{self.name}'."

    async def get_context_limit(self, model_name: str) -> int:
        """Return the context limit (max tokens) for a given model."""
        return self.config.get("max_tokens", 8192)

    async def measure_tokens(self, model_name: str, messages: list) -> int:
        """Proactively count tokens for a list of messages."""
        return 0

    async def get_model_info(self, model_name: str = "") -> Dict[str, Any]:
        """Inspect runtime model parameters, context limits, and preset configurations."""
        return {}

    async def set_model_config(self, model_name: str, settings: Dict[str, str]) -> Tuple[bool, str]:
        """Persist settings to the preset store and hot-reload running model instance."""
        return False, f"Configuring presets is not supported by driver '{self.name}'."

    async def reload_router(self) -> Tuple[bool, str]:
        """Trigger a live reload of model configurations and presets."""
        return False, f"Reloading is not supported by driver '{self.name}'."

    async def list_presets(self) -> Dict[str, Dict[str, str]]:
        """List reusable preset templates."""
        return {}

    async def save_preset(self, name: str, settings: Dict[str, str]) -> Tuple[bool, str]:
        """Save a reusable preset template."""
        return False, f"Saving templates is not supported by driver '{self.name}'."
