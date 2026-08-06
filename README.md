# Agent State Kit 🧰

A modular, agentic CLI harness built on Nix — designed as a **complete toolkit** for building and deploying purpose-built AI agents.

## Philosophy

The Agent State Kit is not an agent. It is a **framework** for building agents.

The three agents that ship with it — `ask`, `linux`, and `dev` — are **examples**, not the destination. They demonstrate the system's capabilities, but they are not the point. The point is the harness itself: a modular, composable system where you define your own agents, states, tools, and context commands.

### Core Principles

1. **Modularity is the default.** Every component — agents, states, tools, context commands — is independently definable and swappable.
2. **State machines drive execution.** Agents don't just "do things." They transition through states, each with different tool access, reasoning budgets, and system prompts.
3. **Context is dynamic.** Context commands are resolved at runtime, not baked in. They can be cached, refreshed, or triggered by state changes.
4. **The harness is the product.** The value is in the framework, not the pre-built agents. The examples are scaffolding to help you build your own.

## Quick Start

```bash
# Default: Agent State Kit (learn how the system works)
ask "What tools are available?"

# Linux assistant
ask --agent linux "What's my shell?"

# Development agent
ask --agent dev "Show me the git status"

# Interactive mode (unlocks tools)
ask -i "Help me build a new agent"

# Continue a session
ask -c LAST "What was I doing?"
```

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

- **Developer Guide** — Building custom agents, states, and tools
