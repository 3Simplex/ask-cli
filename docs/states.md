---
when_to_read: "Defining states, transitions, or gating a transition with an evaluator."
related: ["agents.md", "evaluators.md"]
---
# States

States live in `assets/states/<agent>/states.json` and drive execution: each state
controls the system prompt, available tools, and a **cognitive reasoning intent**
(`none` | `low` | `medium` | `high`). The intent is capability-independent: the matched
model profile under `assets/models/*.json` decides what it means on the wire, so one
state definition works across every backend.

```json
{
  "planning": {
    "description": "Use planning to accomplish goals.",
    "system_prompt": "Use deep reasoning to create or refine a step-by-step plan of actions.",
    "allowed_tools": ["read", "search", "set_state"],
    "reasoning": "high"
  },
  "action": {
    "description": "Use action to follow the plan.",
    "system_prompt": "Take steps to follow the plan, change to review after a step is complete.",
    "allowed_tools": ["run", "search", "read", "set_state"],
    "reasoning": "low"
  },
  "prune": {
    "description": "Use prune to prevent oom by cleaning the history.",
    "system_prompt": "Either use the 'gc' tool on stale messages or get out using 'set_state'.",
    "allowed_tools": ["gc", "set_state"],
    "reasoning": "none",
    "evaluators": ["state_guard"]
  }
}
```

## State Keys

- `system_prompt`: instructions while in this state (may include `{context}` refs)
- `description`: presented in the `set_state` tool list — explain purpose and transition requirements
- `allowed_tools`: which tools are available here
- `reasoning`: cognitive intent for the state — one of `none`, `low`, `medium`, `high`
  (default `none`). The model profile translates it: `supports_thinking` gates whether
  thinking turns on at all, `effort_map` picks the wire effort label, and `sampling.thinking`
  vs `sampling.none` supplies temperature/top_p/presence_penalty.
- `temperature`: accepted for backward shape-compatibility but **no longer governs the wire
  value**. Sampling is profile-owned (`assets/models/*.json`, resolved by
  `assets/core/models.py`); a per-state `temperature` is never passed to the resolver
  and should not be relied upon.
- `context_providers`: optional per-state context (see `docs/context-providers.md`)
- `evaluators`: optional list gating entry into this state (see `docs/evaluators.md`)
