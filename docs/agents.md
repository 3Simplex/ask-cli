---
when_to_read: "Defining or editing an agent profile in assets/agents/*.json."
related: ["states.md", "context-providers.md", "tools.md"]
---
# Agent Profiles

An agent is defined by three components:

1. **Profile** (`assets/agents/<name>.json`) — name, description, context_providers, states, tools
2. **States** (`assets/states/<name>/states.json`) — see `docs/states.md`
3. **Tools** (`assets/tools/*.py`) — see `docs/tools.md`

## Create a Profile

Create `assets/agents/your-agent.json`:

```json
{
  "name": "my-agent",
  "description": "You are... {my_var}",
  "context_providers": {
    "my_var": {
      "command": "echo my_var is the output of this command.",
      "refresh": "always"
    }
  },
  "states": ["template_state", "planning", "action", "review"],
  "tools": ["your-tool", "run", "read", "search", "gc", "set_state"]
}
```

The `description` may reference context providers via `{name}` template syntax
(see `docs/context-providers.md`).

## Run It

```bash
ask --agent your-agent "hello"
```
