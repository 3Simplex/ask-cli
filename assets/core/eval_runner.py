import asyncio
import json
import requests
from rich.console import Console
from assets.core.registry import EVAL_REGISTRY, EvalResult

console = Console()

async def dispatch_evaluator(ctx, evaluator_name: str, input_data: dict, agent=None, internal_msgs=None) -> EvalResult:
    """Finds the evaluator plugin, sets up its routing/history, and executes it."""
    if evaluator_name not in EVAL_REGISTRY:
        return EvalResult(status="FAIL", reasoning=f"Evaluator '{evaluator_name}' not registered.")

    config = EVAL_REGISTRY[evaluator_name]
    handler = config["handler"]
    stateful = config.get("stateful", False)
    history_window = config.get("history_window", 10)

    # 1. Dynamic Model & API Routing (Override context temporarily)
    orig_model = ctx.config.get("model")
    orig_api_base = ctx.config.get("api_base")

    if config.get("model_override"):
        ctx.config["model"] = config["model_override"]
    if config.get("api_override"):
        ctx.config["api_base"] = config["api_override"]

    try:
        # 2. History Injection (If Stateful)
        eval_msgs = None
        if stateful and internal_msgs:
            # Pass only the recent window to prevent context limits
            eval_msgs = internal_msgs[-history_window:]

        # 3. Execute the Evaluator Plugin Handler
        result = await handler(ctx, agent, input_data, eval_msgs)

        # Enforce contract
        if not isinstance(result, EvalResult):
            return EvalResult(status="FAIL", reasoning="Plugin did not return an EvalResult.")

        return result

    except Exception as e:
        return EvalResult(status="FAIL", reasoning=f"Evaluator error: {str(e)}")

    finally:
        # 4. Restore Context (Guaranteed rollback)
        if config.get("model_override"):
            ctx.config["model"] = orig_model
        if config.get("api_override"):
            ctx.config["api_base"] = orig_api_base

async def llm_eval_call(ctx, system_prompt: str, user_prompt: str, mode: str = "boolean", temperature: float = 0.1) -> EvalResult:
    """Helper for plugins to standardly query the LLM and parse the mode."""
    payload = {
        "model": ctx.config.get("model"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": 512
    }

    try:
        r = await asyncio.to_thread(
            requests.post,
            f"{ctx.config['api_base']}/chat/completions",
            headers={"Authorization": f"Bearer {ctx.config.get('api_key', '')}"},
            json=payload,
            timeout=30
        )
        r.raise_for_status()
        response = r.json()["choices"][0]["message"].get("content", "")

        if mode == "boolean":
            try:
                parsed = json.loads(response)
                status = "PASS" if parsed.get("passed", False) else "FAIL"
                return EvalResult(status=status, reasoning=parsed.get("reasoning", response))
            except json.JSONDecodeError:
                # Fallback if the LLM didn't return strict JSON
                status = "PASS" if "PASS" in response.upper() else "FAIL"
                return EvalResult(status=status, reasoning=response)

        elif mode == "structured":
            try:
                parsed = json.loads(response)
                status = "SCORED" if parsed.get("passed", False) else "FAIL"
                return EvalResult(status=status, value=parsed.get("score"), reasoning=parsed.get("reasoning", ""), metadata=parsed)
            except json.JSONDecodeError:
                return EvalResult(status="FAIL", reasoning=f"Failed to parse structured JSON: {response}")

        else: # unstructured
            return EvalResult(status="REPLY", value=response, reasoning=response)

    except Exception as e:
        return EvalResult(status="FAIL", reasoning=f"LLM Call failed: {str(e)}")
