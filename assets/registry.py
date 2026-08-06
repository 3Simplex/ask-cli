# tools/registry.py (placed in assets/ for easier import/pathing)
TOOL_REGISTRY = {}

def ask_tool(name: str, description:str, schema_properties: dict):
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
