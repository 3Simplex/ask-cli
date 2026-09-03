---
when_to_read: "Configuring an API backend, using -ap subcommands, presets, or understanding the FreeToken two-plane model."
related: ["config.md", "tools.md"]
---
# API Providers & Routers

Providers live under the `providers` key of `~/.local/share/ask/config.json`
with an `active_provider` selector. Each provider names a `driver`
(`llama-cpp`, `freetoken-router`, or `openai-compatible`).

## The `-ap` Surface

```
ask -ap                          # list all providers with status
ask -ap -start / -stop           # which daemons could start / are running
ask -ap <provider>               # provider detail (endpoint, models)
ask -ap <provider> "query"       # run the agent using that provider
```

Per-provider subcommands:

| Subcommand | Effect |
| --- | --- |
| `-start` / `-stop` | Start / stop the provider's daemon |
| `-load [model]` | List loadable models, or load one (number or name) |
| `-unload [model]` | List loaded models, or unload one |
| `-info [model]` | Model telemetry: allocated context, params, saved preset |
| `-set [model] <k=v ...>` | Set preset values (or `@template`) and hot-reload in memory |
| `-save <name> <k=v ...>` | Save a reusable preset template `@name` |
| `-presets` | List saved preset templates |
| `-reload` | Hot-reload presets for the loaded model |

## Per-Backend Config Keys

| Key | Used by | Notes |
| --- | --- | --- |
| `api_base` | all | Inference endpoint, e.g. `http://localhost:8000/v1` |
| `api_key` | all | Encrypted at rest (Fernet, machine-derived key) |
| `driver` | all | `llama-cpp` / `freetoken-router` / `openai-compatible` |
| `server_path` | llama-cpp | `llama-server` binary |
| `port` | llama-cpp | Default `9931` |
| `models_dir` | llama-cpp, freetoken | Default `~/models` |
| `control_base` | freetoken | Daemon control plane, default `http://localhost:1900` |
| `command` | freetoken | Daemon start command, default `ft daemon` |
| `stop_command` | freetoken | Default `pkill -f 'ft daemon'` |

## OOBE Auto-Detect Probes

`oobe` probes three backends on first run:

| Backend | Probe endpoint |
| --- | --- |
| Llama.cpp | `http://localhost:9931/v1` |
| FreeToken | `http://localhost:8000/v1` |
| Ollama | `http://localhost:11434/v1` |

## FreeToken: The Two-Plane Model

FreeToken runs **two HTTP planes on two ports**. This is the single most
confusing thing about the integration:

```
ask ──lifecycle──▶ control plane :1900  (ft daemon: torch-free, supervises engine)
ask ──chat──────▶ inference  :8000/v1  (ft serve: the model itself, DIRECTLY)
```

- **Control plane (`:1900`, `control_base`)** owns engine lifecycle:
  `/engine/start`, `/engine/stop`, `/engine/switch`, `/engine/status`,
  `/engine/health`. Chat traffic NEVER flows through it.
- **Inference plane (`:8000`, `api_base`)** is the `ft serve` child. Chat
  completions go to it directly; the daemon is not in the request path.
- The harness syncs `api_base` to the serve's actual port reported by
  `/engine/status`, so `-load` on a non-default port keeps working.
- Presets (`~/.local/share/ask/presets/freetoken.json`) are translated into
  `ft serve` flags (`-set`/`-save`/`-presets`), with a `*` global section merged
  under per-model sections; `-set` hot-reloads a loaded model in memory.

> Not yet implemented (do not rely on it): daemon token auth
> (`X-FT-Token` / `$FREETOKEN_DAEMON_TOKEN`) is not sent by the harness.
