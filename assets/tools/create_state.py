"""
Dynamic state creation tool.

Allows the agent to define task-specific states at runtime with custom
context_providers, allowed_tools, system_prompt, and reasoning_budget.

Example:
  create_state {
    "name": "git-review",
    "allowed_tools": ["run", "read", "set_state"],
    "system_prompt": "You are reviewing a git diff. Be thorough and critical.",
    "context_providers": {
      "git_help": {
        "command": "git merge --help",
        "refresh": "first_turn"
      },
      "git_status": {
        "command": "git status",
        "refresh": "always"
      }
    }
  }
"""
import json
from assets.core.registry import ask_tool

@ask_tool(
    name="create_state",
    description="Create a dynamic state at runtime with custom context, tools, and prompt. The state persists for the current session.",
    schema_properties={
        "name": {"type": "string", "description": "Name of the new state"},
        "allowed_tools": {"type": "array", "items": {"type": "string"}, "description": "Tools available in this state"},
        "system_prompt": {"type": "string", "description": "System prompt for this state"},
        "context_providers": {"type": "object", "description": "Context providers (shell commands or API calls)"},
        "reasoning_budget": {"type": "integer", "description": "Reasoning budget in tokens"},
        "temperature": {"type": "number", "description": "Temperature for this state"},
        "description": {"type": "string", "description": "Description of what this state is for"}
    }
)
async def create_state_handler(ctx, agent, args, internal_msgs=None):
    name = args.get("name", "")
    if not name:
        return "Error: No state name provided."

    # Validate: name must not conflict with existing static states
    static_states = set(agent.states.keys())
    dynamic_states = set(agent.dynamic_states.keys())
    if name in static_states:
        return f"Error: State '{name}' conflicts with a static state."
    if name in dynamic_states:
        return f"Error: State '{name}' already exists (dynamic)."

    # Validate: allowed_tools must be subset of agent's tools
    agent_tools = set(agent.profile.get("tools", []))
    requested_tools = set(args.get("allowed_tools", []))
    if not requested_tools.issubset(agent_tools):
        missing = requested_tools - agent_tools
        return f"Error: Tools {missing} are not available to this agent."

    # Build the state config
    state_config = {
        "allowed_tools": args.get("allowed_tools", []),
        "system_prompt": args.get("system_prompt", ""),
        "context_providers": args.get("context_providers", {}),
        "reasoning_budget": args.get("reasoning_budget", 4096),
        "temperature": args.get("temperature", 0.1),
        "description": args.get("description", ""),
    }

    # Store it
    agent.dynamic_states[name] = state_config

    # Also add to the session persistence
    if internal_msgs:
        # We'll persist via the session file in ask.py
        pass

    return (
        f"SUCCESS: Created dynamic state '{name}'.\n"
        f"  Tools: {state_config['allowed_tools']}\n"
        f"  Description: {state_config['description']}"
    )
