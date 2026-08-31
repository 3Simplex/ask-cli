# Agent State Kit 🧰

A modular, agentic harness — designed as a **complete toolkit** for building and deploying purpose-built AI agents.

## Philosophy

The Agent State Kit is not an agent. It is a **framework** for building agents.

The three agents that ship with it — `ask`, `linux`, and `dev` — are **examples**, not the destination. They demonstrate the system's capabilities, but they are not the point. The point is the harness itself: a modular, composable system where you define your own agents, states, tools, and context_providers.

### Core Principles

1. **Modularity is the default.** Every component — agents, states, tools, context_providers — are independently definable and swappable.
2. **State machines drive execution.** Agents don't just "do things." They transition through states, each with different tool access, reasoning budgets, and system prompts.
3. **Context is dynamic.** context_providers are resolved at runtime, not baked in. They can be cached, refreshed, or triggered by state changes.
4. **The harness is the product.** The value is in the framework, not the pre-built agents. The examples are a starting point for inspiration.

## First-Run Setup (OOBE) 
                                                                                                                       
On first launch, the OOBE wizard auto-detects a running Llama.cpp router at `http://localhost:9931/v1`. If found, it configures the connection automatically. If not, it prompts you to:

1. Configure auto-start for a local llama-server (provides binary path and models directory), or
2. Provide your own API connection details

API keys are encrypted using Fernet with a machine-specific key derived from the hostname.

## Quick Start

# Agent State Kit, defaults to the "ask" demo agent.
ask "How do I use this?"

# Unlock tools with -i interactive mode, user-in-the-middle built into 'run' tool.
ask -i "Help me build a new agent"

# Assign an --agent {by-name}, or -a {name} for short.
ask -i --agent linux "Check my logs for errors."

# Switch API provider / router on the fly
ask -ap freetoken "Explain this repo"

# Inspect and manage API providers & routers
ask -ap                                # List all configured providers and statuses
ask -ap llama-cpp -start        # Start router daemon
ask -ap llama-cpp -load         # List available models to load
ask -ap llama-cpp -load qwen    # Load specific model into router
ask -ap freetoken -stop                # Stop running daemon

# Approve tools using --auto with security evaluator permission gate.
ask --auto -i -a dev -c repo-status-report "Show me the git status and report changes."

## Architecture

```
ask-cli/
├── ask.py                        # CLI entry point
├── oobe.py                       # First-run setup wizard (OOBE)
├── assets/
│   ├── agent.py                  # Core Agent class (state machine + context resolution)
│   ├── context.py                # Runtime context, security watcher, rate limiting
│   ├── registry.py               # Tool registration system (@ask_tool decorator)
│   ├── agents/                   # Agent profiles (JSON)
│   │   ├── ask.json              # Agent State Kit (demo agent) ← default
│   │   ├── linux.json            # Linux CLI assistant
│   │   └── dev.json              # Software development agent
│   ├── docs/                     # Documentation
│   │   └── developer-guide.md
│   ├── skills/                   # Skill expansion
│   │   └── nix-guide.md
│   ├── states/                   # State definitions per agent
│   │   ├── ask/
│   │   │   └── states.json
│   │   ├── linux/
│   │   │   └── states.json
│   │   └── dev/
│   │       └── states.json
│   └── tools/                    # Tool implementations
│       ├── run.py                # Shell command execution (with security watcher)
│       ├── read.py               # File/URL reading
│       ├── search.py             # DuckDuckGo search (rate-limited)
│       ├── gc.py                 # Context garbage collection
│       └── set_state.py          # State transitions
└── default.nix                   # Nix flake build
```

## See Also

- **Developer Guide** — Detailed for building custom agents, states, and tools etc...
