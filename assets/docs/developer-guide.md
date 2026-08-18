# Developer Guide: Building Custom Agents

## Overview

The Agent State Kit is a framework for building custom AI agents. Each agent is defined by three components:

1. **Profile** (`agents/<name>.json`) — name, description, context_providers, states, tools
2. **States** (`states/<name>/states.json`) — state definitions with system prompts, description, allowed tools, temperature, reasoning budget, context_providers
3. **Tools** (`tools/*.py`) — tool implementations registered via the `@ask_tool` decorator

## Building a Custom Agent

### 1. Create an Agent Profile

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

### 2. Define States

Create `assets/states/your-agent/states.json`:

```json
{
  "template_state": {
    "description": "Explain when and why to use this state.",
    "system_prompt": "Your system prompt here, may include context_providers for {this_state}.",
  "context_providers": {
    "this_state": {
      "command": "echo when state specific information is required.",
      "refresh": "template_state"
    }
  },
    "allowed_tools": ["your-tool", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 0
  },
  "planning": {
    "description": "Use planning to acomplish goals.",
    "system_prompt": "Use deep reasoning to create or refine a step-by-step plan of actions.",
    "allowed_tools": ["read", "search", "set_state"],
    "temperature": 0.6,
    "reasoning_budget": 8192
  },
  "action": {
    "description": "Use action to follow the plan.",
    "system_prompt": "Take steps to follow the plan, change to review after a step is complete or if you have trouble.",
    "allowed_tools": ["run", "search", "read", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 4096
  },
  "review": {
    "description": "Use review after an action or planning.",
    "system_prompt": "Analyze the outcome. Decide what to do next.",
    "allowed_tools": ["read", "search", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 4096
  },
  "prune": {
    "description": "Use prune to prevent oom by cleaning the history.",
    "system_prompt": "Only use tools while in this state. Either use the 'gc' tool on stale and irrelevant messages or get out using 'set_state'.",
    "allowed_tools": ["gc", "set_state"],
    "temperature": 0.1,
    "reasoning_budget": 4096
  }
}
```

## Context Providers

Context providers are resolved at runtime and can be referenced in agent descriptions using `{name}` template syntax. For use with states.json and agent.json files.

```json
{
  "context_providers": {
      "dir": {            # name
      "command": "pwd",   # command or api
      "refresh": "always" # resolve
    }
  }
}
```

- `always`: Run every turn
- `first_turn`: Run only on the first turn
- `state_change`: Run when the state changes
- `["state1", "state2"]`: Run only in specific states (best used in the agent.json file)

### 3. Run It

```bash
ask --agent your-agent "hello"
```

## Adding Custom Tools

Create a tool file in `assets/tools/your-tool.py`:

```python
from assets.registry import ask_tool

@ask_tool(
    name="your-tool",
    description="What this tool does.",
    schema_properties={"param": {"type": "string"}}
)
async def your_tool_handler(ctx, agent, args, internal_msgs=None):
    param = args.get("param", "")
    # Do something
    return f"Result: {param}"
```

Import the tool in `ask.py` to trigger the decorator:

```python
import assets.tools.your-tool
```

## State Machine Design

States control what tools are available and how the agent behaves:

Each state has:
- `system_prompt`: Instructions for the agent while in this state
- `description`: A description presented in the set_state tool list (explain its purpose and transition requirements)
- `context_providers`: Optionally collect/provide special context while in this state
- `allowed_tools`: Which tools are available in this state
- `temperature`: LLM temperature (lower = more deterministic)
- `reasoning_budget`: Max tokens for reasoning

## Session Persistence

Sessions are saved to `~/.local/share/ask/threads/*.json`:

```json
{
  "state": "current_state",
  "model": "selected_model_id",
  "messages": [...]
}
```

Resume a session with `ask -c LAST` or `ask -c <session_name>`.

## Evaluator Framework

Evaluators are pluggable, AI-driven policy engines that assess data, commands, or state transitions before they execute. 

### 1. Creating an Evaluator
Create a Python file in `assets/evaluators/` using the `@ask_evaluator` decorator.

```python
from assets.core.registry import ask_evaluator, EvalResult
from assets.core.eval_runner import llm_eval_call

@ask_evaluator(
    name="my_custom_guard",
    description="Briefly explain what this checks.",
    mode="boolean",                         # "boolean", "structured", or "unstructured"
    stateful=True,                          # True = injects conversation history
    model_override="mini-model",            # Routes just this evaluator to a different model (optional)
    api_override="http://other-api/v1",     # Routes to a different API (optional)
    history_window=5,                       # Number of messages to inject if stateful
    max_tokens=1024,
    reasoning_budget=1024
)
async def my_guard_handler(ctx, agent, input_data, eval_msgs, config):
    # input_data is a dict containing what you are evaluating
    sys_prompt = "You are a judge. Output valid JSON: {\"passed\": true, \"reasoning\": \"...\"}"
    user_prompt = f"Evaluate: {input_data}"
    
    # Call the framework helper
    return await llm_eval_call(ctx, sys_prompt, user_prompt, config)
```

### 2. Using Evaluators
Evaluators can be triggered in three ways:

**Via CLI:**
Test an evaluator independently or run it against an existing session.
```bash
ask -e security_watcher "rm -rf /"
ask -e state_guard -c my_session "Evaluate transition to planning"
```

**Via Tools:**
Tools can invoke evaluators to gate their own execution.
```python
from assets.core.eval_runner import dispatch_evaluator

# Inside a tool handler
eval_result = await dispatch_evaluator(ctx, "security_watcher", {"command": cmd}, agent, internal_msgs)
if not eval_result.passed:
    return f"Blocked: {eval_result.reasoning}"
```

**Via State Transitions:**
Add the `evaluators` key to a state in `states.json` to prevent the agent from entering a state unless the evaluator approves.
```json
"prune": {
  "allowed_tools": ["gc", "set_state"],
  "evaluators": ["state_guard"]
}
```

## Post-Evaluation Hooks

Hooks are side-effect callbacks that fire **after** an evaluator completes. They are useful for logging, notifications, or audit trails.

### 1. Creating a Hook
Create a Python file in `assets/hooks/` using the `@ask_hook` decorator:

```python
from assets.core.registry import ask_hook

@ask_hook(name="my_hook", description="What this hook does.")
async def my_hook_handler(ctx, eval_name: str, input_data: dict, result):
    # result is an EvalResult from the evaluator
    # Do something with the result (log, notify, etc.)
    pass
```

### 2. Wiring Hooks to Evaluators
Add a `post_hooks` list to an evaluator's config (in `config.json` or via decorator kwargs):

```python
@ask_evaluator(
    name="my_guard",
    description="My guard",
    mode="boolean",
    post_hooks=["webhook_notify"]  # List of registered hook names
)
async def my_guard_handler(ctx, agent, input_data, eval_msgs, config):
    ...
```

Or via `config.json`:
```json
{
  "webhook_url": "https://discord.com/api/webhooks/url_fallback_applies_to_all_unconfigured_evaluators...",
  "evaluators": {
    "my_guard": {
      "post_hooks": ["webhook_notify"]
    }
  }
}
```

### 3. Built-in Hook: Discord Webhook
The `webhook_notify` hook sends evaluator results to a Discord webhook as an embed. Configure it in `config.json`:

```json
{
  "evaluators": {
    "security_watcher": {
      "webhook_url": "https://discord.com/api/webhooks/url_configured_for_this_evaluator_only...",
      "post_hooks": ["webhook_notify"]
    }
  }
}
```

## Pluggable Evaluator: Gold-Star Session Review

The `gold_star_eval` evaluator reviews an agent session log and scores it against a 5-criterion rubric:

1. **Task Completion** — Did the agent accomplish the goal?
2. **Efficiency & Tool Routing** — Were tools used wisely?
3. **Safety & Data Preservation** — Were sensitive data and system integrity respected?
4. **Communication & Clarity** — Was the agent's output clear and well-structured?
5. **Context & OS/Env Fit** — Did the agent adapt to the environment?

### Usage

```bash
# Evaluate a session by name
ask -e gold_star_eval "my_session_name"

# Evaluate with optional feedback
ask -e gold_star_eval "my_session_name" --feedback "The agent missed a step"
```

### Output

Returns a structured JSON with per-criterion scores (1-5), an overall star rating, and notes on what went well, what went wrong, and recommendations.

## Configuration

### First-Run Setup (OOBE)

On first launch, the OOBE wizard auto-detects a running Llama.cpp router at `http://localhost:9931/v1`. If found, it configures the connection automatically. If not, it prompts you to:

1. Configure auto-start for a local llama-server (provides binary path and models directory), or
2. Provide your own API connection details

API keys are encrypted using Fernet with a machine-specific key derived from the hostname.

### Config Location

- `~/.local/share/ask/config.json` (primary)
- Fallback: `assets/config/config.json` (dev environments)

### Config Options

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
| `webhook_url` | `""` | Discord webhook URL for `webhook_notify` hook |
| `evaluators.evaluator_name.model_override` | `"coder:7b"` | Model to override for an evaluator |
| `evaluators.evaluator_name.timeout` | `30000` | Timeout for an evaluator (ms) |
| `evaluators.evaluator_name.api_override` | `"https://api.openai.com/v1"` | API base URL to override for a specific evaluator |
| `evaluators.evaluator_name.api_key_override` | `"sk-your-key-here"` | API key to override for a specific evaluator |
| `evaluators.evaluator_name.max_tokens` | `4096` | Maximum number of tokens to generate for an evaluator response |
| `evaluators.evaluator_name.post_hooks` | `[]` | List of hook names to fire after this evaluator |


## Nix Installation

```nix
{ pkgs ? import <nixpkgs> {} }:

pkgs.stdenv.mkDerivation {
  name = "ask-cli-3.0";
  src = ./.;
  nativeBuildInputs = [ pkgs.makeWrapper ];
  buildInputs = [
    (pkgs.python3.withPackages (ps: with ps; [ requests rich ]))
  ];
  installPhase = ''
    mkdir -p $out/bin
    mkdir -p $out/share/ask
    cp ask.py $out/bin/ask
    cp -r assets $out/share/ask/
    chmod +x $out/bin/ask
    patchShebangs $out/bin/ask
    wrapProgram $out/bin/ask \
      --set ASK_ASSETS_DIR "$out/share/ask/assets" \
      --prefix PYTHONPATH : "$out/share/ask" \
      --prefix PATH : ${pkgs.lib.makeBinPath [
        pkgs.ddgr
        pkgs.lynx
        pkgs.bubblewrap
        pkgs.coreutils
        pkgs.gnupg
      ]}
  '';
}
```

## Dependencies

- Python 3 with `requests` and `rich`
- `ddgr` (DuckDuckGo search CLI)
- `lynx` (URL reading)
- `bwrap` (Bubblewrap sandbox, optional)
- `coreutils`, `gnupg` (system utilities)
- `cryptography` (for OOBE key encryption)
