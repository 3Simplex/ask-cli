---
when_to_read: "Wiring a context provider or using {template} substitution / refresh modes."
related: ["agents.md", "states.md"]
---
# Context Providers

Context providers are resolved at runtime and referenced in descriptions and
system prompts via `{name}` template syntax. They are declared in
`assets/agents/*.json` or per-state in `states.json`.

```json
{
  "context_providers": {
    "dir": {
      "command": "pwd",
      "refresh": "always"
    }
  }
}
```

## Refresh Modes

- `always`: run every turn
- `first_turn`: run only on the first turn
- `state_change`: run when the state changes
- `["state1", "state2"]`: run only in the listed states (best used in `agent.json`)
