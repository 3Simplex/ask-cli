import asyncio
import re
import json
import requests
from rich.console import Console
from assets.core.registry import EVAL_REGISTRY, EvalResult
from datetime import datetime

console = Console()

async def dispatch_evaluator(ctx, evaluator_name: str, input_data: dict, agent=None, internal_msgs=None) -> EvalResult:
    """Finds the evaluator plugin, sets up its routing/history, and executes it."""
    if evaluator_name not in EVAL_REGISTRY:
        return EvalResult(status="FAIL", reasoning=f"Evaluator '{evaluator_name}' not registered.")

    # Create a shallow copy so we don't permanently mutate the registry
    config = EVAL_REGISTRY[evaluator_name].copy()

    # Overlay any user overrides from config.json
    user_overrides = ctx.config.get("evaluators", {}).get(evaluator_name, {})
    config.update(user_overrides)

    handler = config["handler"]
    stateful = config.get("stateful", False)
    history_window = config.get("history_window", 10)

    # 1. Dynamic Model & API Routing (Override context temporarily)
    orig_model = ctx.config.get("model")
    orig_api_base = ctx.config.get("api_base")
    orig_api_key = ctx.config.get("api_key")

    if config.get("model_override"):
        ctx.config["model"] = config["model_override"]
    if config.get("api_override"):
        ctx.config["api_base"] = config["api_override"]
    if config.get("api_key_override"):
        ctx.config["api_key"] = config["api_key_override"]

    try:
        # 2. History Injection (If Stateful)
        eval_msgs = None
        if stateful and internal_msgs:
            # Pass only the recent window to prevent context limits
            eval_msgs = internal_msgs[-history_window:]

        # 3. Execute the Evaluator Plugin Handler
        config["evaluator_name"] = evaluator_name
        result = await handler(ctx, agent, input_data, eval_msgs, config)

        # Enforce contract
        if not isinstance(result, EvalResult):
            return EvalResult(status="FAIL", reasoning="Plugin did not return an EvalResult.")

        # --- 3.5 Dispatch Post-Hooks ---
        post_hooks = config.get("post_hooks", [])
        if isinstance(post_hooks, list):
            from assets.core.registry import HOOK_REGISTRY
            for hook_name in post_hooks:
                if hook_name in HOOK_REGISTRY:
                    try:
                        # Fire the hook!
                        await HOOK_REGISTRY[hook_name]["handler"](ctx, evaluator_name, input_data, result)
                    except Exception as e:
                        console.print(f"[dim yellow]⚠ Hook '{hook_name}' failed: {e}[/dim yellow]")
                else:
                    console.print(f"[dim yellow]⚠ Warning: Hook '{hook_name}' not registered.[/dim yellow]")

        return result

    except Exception as e:
        return EvalResult(status="FAIL", reasoning=f"Evaluator error: {str(e)}")

    finally:
        # 4. Restore Context (Guaranteed rollback)
        if config.get("model_override"):
            ctx.config["model"] = orig_model
        if config.get("api_override"):
            ctx.config["api_base"] = orig_api_base
        if config.get("api_key_override"):
            ctx.config["api_key"] = orig_api_key

def safe_json_parse(response: str, ctx, evaluator_name: str = "") -> EvalResult:
    try:
        data = json.loads(response)
        return EvalResult(status="PASS", value=data.get("value"), reasoning=json.dumps(data, indent=2))
    except json.JSONDecodeError as e:
        debug_dir = ctx.data_dir / "eval_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / (f"{evaluator_name}_debug.json" if evaluator_name else "debug.json")
        debug_file.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "evaluator": evaluator_name,
            "raw_response": response,
            "parse_error": str(e)
        }, indent=2))
        return EvalResult(status="FAIL", reasoning=f"JSON parse error saved to {debug_file}")

async def llm_eval_call(ctx, system_prompt: str, user_prompt: str, config: dict) -> EvalResult:
    """Helper for plugins to standardly query the LLM and parse the mode."""
    mode = config.get("mode", "boolean")
    payload = {
        "model": ctx.config.get("model"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": config.get("temperature", 0.1)
    }

    # Dynamically inject tokens/budgets from the plugin config
    if "max_tokens" in config:
        payload["max_tokens"] = config["max_tokens"]
    if "reasoning_budget" in config:
        payload["reasoning_budget"] = config["reasoning_budget"]

    # Dynamic timeout (default to ctx timeout, fallback to 60s)
    timeout = config.get("timeout", ctx.config.get("timeout", 60000) / 1000.0)
    if timeout < 1: timeout = 60

    try:
        r = await asyncio.to_thread(
            requests.post,
            f"{ctx.config['api_base']}/chat/completions",
            headers={"Authorization": f"Bearer {ctx.config.get('api_key', '')}"},
            json=payload,
            timeout=timeout
        )
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]

        # Safely extract text whether it's in content or reasoning_content
        response = msg.get("content") or msg.get("reasoning_content") or ""

        if not response.strip():
            return EvalResult(status="FAIL", reasoning="LLM returned an empty response.")

        # Strip <think> tags and markdown wrappers so JSON parsing succeeds
        clean_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        clean_response = re.sub(r'^```json\s*', '', clean_response)
        clean_response = re.sub(r'^```\s*', '', clean_response)
        clean_response = re.sub(r'\s*```$', '', clean_response)
        clean_response = clean_response.strip()

        if mode == "boolean":
            try:
                parsed = json.loads(clean_response)
                status = "PASS" if parsed.get("passed", False) else "FAIL"
                return EvalResult(status=status, reasoning=parsed.get("reasoning", clean_response))
            except json.JSONDecodeError:
                return safe_json_parse(clean_response, ctx, config.get("evaluator_name", ""))

        elif mode == "structured":
            try:
                parsed = json.loads(clean_response)
                status = "SCORED" if parsed.get("passed", False) else "FAIL"
                return EvalResult(status=status, value=parsed.get("score"), reasoning=parsed.get("reasoning", ""), metadata=parsed)
            except json.JSONDecodeError:
                return safe_json_parse(clean_response, ctx, config.get("evaluator_name", ""))

        else: # unstructured
            return EvalResult(status="REPLY", value=response, reasoning=response)

    except Exception as e:
        return EvalResult(status="FAIL", reasoning=f"LLM Call failed: {str(e)}")
