---
when_to_read: "Persisting or resuming a session, or using -c."
related: ["states.md", "config.md"]
---
# Sessions

Sessions are saved to `~/.local/share/ask/threads/*.json`:

```json
{
  "state": "current_state",
  "model": "selected_model_id",
  "messages": [...]
}
```

Resume a session with `ask -c LAST` or `ask -c <session_name>`.
