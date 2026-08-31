"""
Dynamic state creation tool.

Allows the agent to define task-specific states at runtime with custom
context_providers, allowed_tools, system_prompt, and reasoning_budget.

Example:
  create_state {
    "name": "git-review",
    "description": "Review git diffs with git help and status context.",
    "allowed_tools": ["run", "read", "set_state"],
    "system_prompt": "You are reviewing a git diff. Be thorough and critical.\n\n{git_help}\n{git_status}",
    "context_providers": {
      "git_help": {
        "command": "git merge --help",
        "refresh": "first_turn"
      },
      "git_status": {
        "command": "git status",
        "refresh": "always"
      }
    },
    "evaluators": ["state_guard"]
  }
"""
import json
from assets.core.registry import ask_tool

@ask_tool(
    name="create_state",
    description="Create a dynamic state at runtime with custom context, tools, and prompt. The state persists for the current session. Use this to create highly specialized modes of operation for specific tasks.",
    schema_properties={
        "name": {
            "type": "string",
            "description": "Name of the new state, a good name must be concice and descriptive to the purpose of the state."
        },
        "allowed_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Must be a subset of your current tools, include set_state to allow state transitions. A well defined state should be customized to the intended use of the chosen tool for a specific task."
        },
        "description": {
            "type": "string",
            "description": "A brief description of what this state is for, when and why to use it, the intent & scope of the state are defined with this property which will be displayed to you in your state directory along with its name and tools. This is important for an agent while deciding which state to use."
        },
        "context_providers": {
            "type": "object",
            "description": "Variables injected into this states system_prompt at runtime. Each provider can be:\n"
                        "- Shell command:\n"
                        "  {\"command\": \"shell command\", \"refresh\": \"always|<dynamic_state_name>\", \"cache_ttl\": <seconds>}\n"
                        "- HTTP API:\n"
                        "  {\"type\": \"api\", \"url\": \"https://...\", \"method\": \"GET\", \"cache_ttl\": <seconds>}\n"
                        "Refresh policies: 'always' (every turn), '<dynamic_state_name>' (on entry of the state named), Choosing the correct refresh policy and optional ttl depends on the rate that the dynamic context becomes stale.\n"
                        "Note: All shell commands execute in the agent's current CWD. Use absolute paths or 'cd <dir> &&' for other locations as needed.\n"
                        "This feature is usefull to provide grounding context, such as --help for a particular command, or any relevant information required only while in this state, etc..."
        },
#        "evaluators": {
#            "type": "array",
#            "items": {"type": "string"},
#            "description": "(Optional) List of evaluators. Commented out untill evaluators are better suited for dynamic states."
#        },
        "reasoning_budget": {
            "type": "integer",
            "description": "Reasoning budget in tokens, should be determined based on complexity of the expected output of the state (e.g., 4096 or 8192)."
        },
        "temperature": {
            "type": "number",
            "description": "LLM Temperature for this state ranging from 0.1 for determinatively strict, up to 0.9 for unpredictably creative."
        },
        "system_prompt": {
            "type": "string",
            "description": "The exact system prompt for this state seasoned by each of its schema_properties. Each of the context_providers MUST be injected here using {variable_name} syntax. The purpose of a well made state is to provide perfect context with instruction to enable the llm with grounding for a task without. Avoid suggesting redundant effort which is given through any context_providers refferenced here."
        }
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
        #"evaluators": args.get("evaluators", []),
        "reasoning_budget": args.get("reasoning_budget", 4096),
        "temperature": args.get("temperature", 0.1),
        "description": args.get("description", ""),
    }

    # Store it
    agent.dynamic_states[name] = state_config

    return (
        f"SUCCESS: Created dynamic state '{name}'.\n"
        f"  Tools: {state_config['allowed_tools']}\n"
        #f"  Evaluators: {state_config['evaluators']}\n"
        f"  Description: {state_config['description']}"
    )
