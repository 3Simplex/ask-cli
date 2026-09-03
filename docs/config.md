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

Every default below is defined once, in `assets/core/defaults.py`, and read
through its `get()` helper. Call sites must not hardcode their own fallback
literals for these keys.

| Option | Default | Description |
|--------|---------|-------------|
| `api_base` | `http://localhost:9931/v1` | LLM API base URL |
| `api_key` | `""` | Encrypted API key |
| `timeout` | `120000` | Request timeout (ms) |
| `max_turns` | `100` | Maximum autonomous tool loops |
| `max_result_chars` | `10000` | Max output characters before truncation |
| `auto_approve_default` | `false` | Auto-approve safe commands |
| `use_sandbox_default` | `false` | Run in bwrap sandbox |
| `search_rate_limit` | `5` | Max searches per minute |
| `search_rate_delay` | `5.0` | Delay between searches (s) |
| `search_max_concurrent` | `1` | Max concurrent searches |
| `search_retry_count` | `3` | Max search retries |
| `search_retry_base_delay` | `10.0` | Base delay for retries (s) |
| `search_timeout` | `30` | Search timeout (s) |
| `active_provider` | `""` | Default provider selection |
| `default_evaluator` | `security_watcher` | Evaluator gating `run` |
| `webhook_url` | `""` | Discord webhook URL for `webhook_notify` |
| `providers` | `{}` | Provider map (see `docs/providers.md`) |

### Per-evaluator overrides (`evaluators.<name>.*`)

These are read from an evaluator's own config dict, not the global config, so
they are intentionally NOT in `DEFAULTS`:

| Key | Default | Notes |
| --- | --- | --- |
| `model_override` | unset | Route this evaluator to a different model |
| `api_override` / `api_key_override` | unset | Route this evaluator to a different API |
| `timeout` | falls back to global `timeout` | Evaluator timeout (ms) |
| `max_tokens` | unset (a decorator may set its own) | Max response tokens |
| `post_hooks` | `[]` | Hook names to fire after this evaluator |

## Defaults: Single Source of Truth

Defaults previously drifted across `oobe.py`, `ask.py`, and `context.py` — most
notably `max_turns` (100 vs 10), `search_rate_delay` (5.0 vs 2.0),
`search_retry_base_delay` (10.0 vs 1.0), and a `timeout` read with no fallback
that raised `KeyError` when the key was absent.

All of that is resolved: `assets/core/defaults.py` now owns every global
default, and `oobe.py` stamps the same values from it, so a config created by
OOBE and a hand-written config missing a key now agree.

**Not governed by `DEFAULTS`** (deliberately): a provider's own `api_base`,
`api_key`, `models_dir`, `port`, `command`, and `control_base` — those carry
backend-specific defaults (e.g. FreeToken's `:8000`) that must not be collapsed
onto the global value.
