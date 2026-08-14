# assets/core/registry.py
from dataclasses import dataclass, field
from typing import Any, Literal

# --- REGISTRIES ---
TOOL_REGISTRY = {}
EVAL_REGISTRY = {}
HOOK_REGISTRY = {}

# --- DATA MODELS ---
@dataclass
class EvalResult:
    status: Literal["PASS", "FAIL", "SCORED", "REPLY", "TRIGGER"]
    value: Any = None
    reasoning: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "SCORED")

# --- DECORATORS ---
def ask_tool(name: str, description: str, schema_properties: dict):
    """Decorator to register a tool."""
    def decorator(func):
        TOOL_REGISTRY[name] = {
            "handler": func,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": schema_properties,
                        "required": list(schema_properties.keys())
                    }
                }
            }
        }
        return func
    return decorator

def ask_evaluator(name: str, description: str, mode: str = "structured", stateful: bool = False, history_window: int = 10, **kwargs):
    """Decorator to register an evaluator."""
    def decorator(func):
        EVAL_REGISTRY[name] = {
            "handler": func,
            "mode": mode,
            "stateful": stateful,
            "history_window": history_window,
            "description": description,
            **kwargs  # Captures model_override, api_override, etc.
        }
        return func
    return decorator
