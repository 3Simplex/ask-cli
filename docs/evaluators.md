---
when_to_read: "Writing an evaluator, wiring a post-evaluation hook, or gating a state transition."
related: ["states.md", "tools.md", "config.md"]
---
# Evaluators & Hooks

Evaluators are pluggable, AI-driven policy engines that assess data, commands,
or state transitions before they execute. Hooks are side-effect callbacks that
fire **after** an evaluator completes (logging, notifications, audit trails).

## Creating an Evaluator

Create a Python file in `assets/evaluators/` using the `@ask_evaluator`
decorator (auto-discovered, like tools):

```python
from assets.core.registry import ask_evaluator, EvalResult
from assets.core.eval_runner import llm_eval_call

@ask_evaluator(
    name="my_custom_guard",
    description="Briefly explain what this checks.",
    mode="boolean",                         # "boolean", "structured", or "unstructured"
    stateful=True,                          # True = injects conversation history
    model_override="mini-model",            # Route just this evaluator to a different model (optional)
    api_override="http://other-api/v1",     # Route to a different API (optional)
    history_window=5,                       # Messages to inject if stateful
    max_tokens=1024,
    reasoning_budget=1024
)
async def my_guard_handler(ctx, agent, input_data, eval_msgs, config):
    sys_prompt = "You are a judge. Output valid JSON: {\"passed\": true, \"reasoning\": \"...\"}"
    user_prompt = f"Evaluate: {input_data}"
    return await llm_eval_call(ctx, sys_prompt, user_prompt, config)
```

## Using Evaluators

**Via CLI** — test standalone or against a session:
```bash
ask -e security_watcher "rm -rf /"
ask -e state_guard -c my_session "Evaluate transition to planning"
```

**Via Tools** — a tool can gate its own execution:
```python
from assets.core.eval_runner import dispatch_evaluator

eval_result = await dispatch_evaluator(ctx, "security_watcher", {"command": cmd}, agent, internal_msgs)
if not eval_result.passed:
    return f"Blocked: {eval_result.reasoning}"
```

**Via State Transitions** — add an `evaluators` key to a state in `states.json`
to block entry unless the evaluator approves:
```json
"prune": {
  "allowed_tools": ["gc", "set_state"],
  "evaluators": ["state_guard"]
}
```

## Creating a Hook

Create a Python file in `assets/hooks/` using the `@ask_hook` decorator
(auto-discovered):

```python
from assets.core.registry import ask_hook

@ask_hook(name="my_hook", description="What this hook does.")
async def my_hook_handler(ctx, eval_name: str, input_data: dict, result):
    # result is an EvalResult from the evaluator
    pass
```

## Wiring Hooks to Evaluators

Add a `post_hooks` list via decorator kwargs or `config.json`:

```json
{
  "webhook_url": "https://discord.com/api/webhooks/url_fallback_for_unconfigured_evaluators...",
  "evaluators": {
    "my_guard": {
      "post_hooks": ["webhook_notify"]
    }
  }
}
```

The built-in `webhook_notify` hook sends evaluator results to a Discord webhook
as an embed; a per-evaluator `webhook_url` overrides the global fallback.

## Built-in: Gold-Star Session Review

`gold_star_eval` reviews a session log against a 5-criterion rubric (task
completion, efficiency & tool routing, safety & data preservation, communication
& clarity, context & OS/env fit) and returns per-criterion scores (1-5), an
overall star rating, and notes.

```bash
ask -e gold_star_eval "my_session_name"
ask -e gold_star_eval "my_session_name" --feedback "The agent missed a step"
```
