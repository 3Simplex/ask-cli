---
when_to_read: "Defining states, transitions, or gating a transition with an evaluator."
related: ["agents.md", "evaluators.md"]
---
# States

States live in `assets/states/<agent>/states.json` and drive execution: each
state controls the system prompt, available tools, and generation parameters.

```json
{
  "planning": {
    "description": "Use planning to accomplish goals.",
    "system_prompt": "Use deep reasoning to create or refine a step-by-step plan of actions.",
    "allowed_tools": ["read", "search", "set_state"],
    "temperature": 0.6,
    "reasoning_budget": 8192
  },
  "action": {
    "description": "Use action to follow the plan.",
    "system_prompt": "Take steps to follow the plan, change to review after a step is complete.",
    "allowed_tools": ["run", "search", "read", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 4096
  },
  "prune": {
    "description": "Use prune to prevent oom by cleaning the history.",
    "system_prompt": "Either use the 'gc' tool on stale messages or get out using 'set_state'.",
    "allowed_tools": ["gc", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 4096,
    "evaluators": ["state_guard"]
  }
}
```

## State Keys

- `system_prompt`: instructions while in this state (may include `{context}` refs)
- `description`: presented in the `set_state` tool list — explain purpose and transition requirements
- `allowed_tools`: which tools are available here
- `temperature`: LLM temperature (lower = more deterministic)
- `reasoning_budget`: max tokens for reasoning
- `context_providers`: optional per-state context (see `docs/context-providers.md`)
- `evaluators`: optional list gating entry into this state (see `docs/evaluators.md`)
