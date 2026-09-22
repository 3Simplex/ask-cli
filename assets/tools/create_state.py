"""Dynamic state creation tool.

Allows the agent to define task-specific states at runtime with custom
context_providers, allowed_tools, system_prompt, and cognitive reasoning intent.
"""

from assets.core.registry import ask_tool

@ask_tool(
    name="create_state",
    description="Create a dynamic state at runtime with custom context, tools, and prompt. The state persists for the current session. Use this to create highly specialized modes of operation for specific tasks.",
    schema_properties={
        "name": {
            "type": "string",
            "description": "Name of the new state. A good name is concise and describes the state's specific purpose."
        },
        "allowed_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Must be a subset of your agent's total profile tools (not limited to tools currently active in this state). Include 'set_state' to allow transitions out of this state. Customize the toolset to the specific task."
        },
        "description": {
            "type": "string",
            "description": "A brief description of what this state is for, when and why to use it. This appears in your state directory and serves as the routing signal for state transitions."
        },
        "context_providers": {
            "type": "object",
            "description": "Variables injected into this state's system_prompt at runtime. Each provider can be:\n"
                        "- Shell command: {\"command\": \"shell cmd\", \"refresh\": \"always|<dynamic_state_name>\", \"cache_ttl\": <sec>}\n"
                        "- HTTP API: {\"type\": \"api\", \"url\": \"https://...\", \"method\": \"GET\", \"cache_ttl\": <sec>}\n"
                        "Note: Shell commands run in CWD. Fast-changing data should use 'always'; static references should use cache_ttl or state entry."
        },
        "reasoning": {
            "type": "string",
            "enum": ["none", "low", "medium", "high"],
            "description": "Cognitive reasoning effort needed for this state: 'none' for direct reflex or tool-running tasks, up to 'high' for complex analysis or planning. Model sampling parameters are configured automatically by the harness."
        },
        "system_prompt": {
            "type": "string",
            "description": "The exact operational instructions for this state. Every context_provider MUST be referenced using {variable_name} syntax. Providers supply the raw context; the prompt directs how to interpret it without duplicating effort."
        }
    }
)
async def create_state_handler(ctx, agent, args, internal_msgs=None):
    name = args.get("name", "")
    if not name:
        return "Error: No state name provided."

    # Validate: name must not conflict with a predefined (static) state.
    # Re-creating an existing DYNAMIC name is an in-place replace handled by the
    # single agent.dynamic_states[name] = state_config write below.
    static_states = set(agent.states.keys())
    if name in static_states:
        return f"Error: State '{name}' conflicts with a static state."

    # Validate against the agent's overall profile tools, NOT the current state's active tools
    agent_tools = set(agent.profile.get("tools", []))
    requested_tools = set(args.get("allowed_tools", []))
    if not requested_tools.issubset(agent_tools):
        missing = requested_tools - agent_tools
        return f"Error: Tools {missing} are not available to this agent's profile."

    # Build the state config without model-specific floats or token budgets
    state_config = {
        "allowed_tools": args.get("allowed_tools", []),
        "system_prompt": args.get("system_prompt", ""),
        "context_providers": args.get("context_providers", {}),
        "reasoning": args.get("reasoning", "none"),
        "description": args.get("description", ""),
    }

    # Store it in dynamic states
    agent.dynamic_states[name] = state_config

    return (
        f"SUCCESS: Created dynamic state '{name}'.\n"
        f"  Tools: {state_config['allowed_tools']}\n"
        f"  Reasoning: {state_config['reasoning']}\n"
        f"  Description: {state_config['description']}"
    )
