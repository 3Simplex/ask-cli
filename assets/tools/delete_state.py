"""
Dynamic state deletion tool.

Allows the agent to clean up dynamic states it created at runtime.
"""
from assets.core.registry import ask_tool

@ask_tool(
    name="delete_state",
    description="Delete a dynamic state created at runtime.",
    schema_properties={
        "name": {"type": "string", "description": "Name of the dynamic state to delete"}
    }
)
async def delete_state_handler(ctx, agent, args, internal_msgs=None):
    name = args.get("name", "")
    if not name:
        return "Error: No state name provided."

    if name in agent.states:
        return f"Error: State '{name}' is a static state. Cannot delete."

    if name in agent.dynamic_states:
        del agent.dynamic_states[name]
        return f"SUCCESS: Deleted dynamic state '{name}'."

    return f"Error: Dynamic state '{name}' not found."
