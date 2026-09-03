---
when_to_read: "Looking up a config.json key or its default."
related: ["providers.md", "evaluators.md"]
---
# Configuration

## Location

- `~/.local/share/ask/config.json` (primary)
- Fallback: `assets/config/config.json` (dev environments)

## First-Run Setup (OOBE)

On first launch, `oobe` auto-detects running local routers (Llama.cpp on 9931,
FreeToken on 8000, Ollama on 11434). If none are found it prompts you to
configure a local llama-server or provide your own API details. API keys are
encrypted with Fernet using a machine-specific key derived from the hostname.
See `docs/providers.md` for the full probe/backend surface.

## Options

Two different "defaults" exist for most keys, so the table lists both:

- **OOBE** — the value `oobe.py` stamps into a fresh `config.json`.
- **Fallback** — the value used at runtime when the key is *absent* (e.g. a
  hand-written config). Where these disagree, see KNOWN DRIFT.

| Option | OOBE writes | Runtime fallback | Description |
|--------|-------------|------------------|-------------|
| `api_base` | per-provider | `""` | LLM API base URL |
| `api_key` | `""` | `""` | Encrypted API key |
| `timeout` | `120000` | **none — `KeyError`** | Request timeout (ms) |
| `max_turns` | `100` | `10` | Maximum autonomous tool loops |
| `max_result_chars` | `10000` | — | Max output characters before truncation |
| `auto_approve_default` | `false` | `false` | Auto-approve safe commands |
| `use_sandbox_default` | `false` | `false` | Run in bwrap sandbox |
| `search_rate_limit` | `5` | `5` | Max searches per minute |
| `search_rate_delay` | `5.0` | `2.0` | Delay between searches (s) |
| `search_max_concurrent` | `1` | `1` | Max concurrent searches |
| `search_retry_count` | `3` | `3` | Max search retries |
| `search_retry_base_delay` | `10.0` | `1.0` | Base delay for retries (s) |
| `search_timeout` | `30` | `30` | Search timeout (s) |
| `webhook_url` | — | unset | Discord webhook URL for `webhook_notify` |
| `providers` | detected | `{}` | Provider map (see `docs/providers.md`) |
| `active_provider` | first detected | `""` | Default provider selection |

### Per-evaluator overrides (`evaluators.<name>.*`)

| Key | Default | Notes |
| --- | --- | --- |
| `model_override` | unset | Route this evaluator to a different model |
| `api_override` / `api_key_override` | unset | Route this evaluator to a different API |
| `timeout` | falls back to global `timeout`, else `60000` | Evaluator timeout (ms) |
| `max_tokens` | unset (per-evaluator decorator may set its own) | Max response tokens |
| `post_hooks` | `[]` | Hook names to fire after this evaluator |

## KNOWN DRIFT (unfixed — do not "correct" without checking all sources)

These values are inconsistent across the codebase. They are recorded as drift,
NOT resolved, because no single source of truth exists yet.

- **`timeout`** — OOBE stamps `120000`, but the chat-completion call reads
  `ctx.config['timeout']` with **no fallback**, so a config missing the key
  raises `KeyError` mid-request. Evaluators fall back to `60000` instead.
- **`max_turns`** — OOBE writes `100`; the `ask.py` runtime fallback is `10`.
  A user who never ran OOBE silently gets **10** turns.
- **`search_rate_delay`** — OOBE writes `5.0`; runtime fallback is `2.0`.
- **`search_retry_base_delay`** — OOBE writes `10.0`; runtime fallback is `1.0`.

A planned `DEFAULTS` dict (single source of truth) is intended to eliminate this
class of drift; until then, treat this table as observed behavior and the
divergences as live bugs.
