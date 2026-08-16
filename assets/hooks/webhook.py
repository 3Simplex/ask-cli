# assets/hooks/webhook.py
import asyncio
import requests
from datetime import datetime, timezone
from assets.core.registry import ask_hook
from rich.console import Console

console = Console()

@ask_hook(name="webhook_notify", description="Sends evaluator results to a Discord webhook as an embed.")
async def webhook_notify_handler(ctx, eval_name: str, input_data: dict, result):
    # --- NEW: Check evaluator-specific config first, fallback to global ---
    eval_config = ctx.config.get("evaluators", {}).get(eval_name, {})
    webhook_url = eval_config.get("webhook_url") or ctx.config.get("webhook_url")

    if not webhook_url:
        console.print(f"[dim yellow]⚠ Webhook not configured for '{eval_name}'. Skipping notification.[/dim yellow]")
        return

    status = result.status
    color = 0x2ecc71 if status == "PASS" else (0xe74c3c if status == "FAIL" else 0xf1c40f)
    title = "✅ Approved" if status == "PASS" else ("🚫 Blocked" if status == "FAIL" else "⚠️ Evaluated")

    # Safely truncate reasoning to prevent Discord API errors (max 1024 chars for embed field value)
    reasoning = str(result.reasoning)
    if len(reasoning) > 1000:
        reasoning = reasoning[:1000] + "..."

    # Safely get a string representation of the value
    val_str = str(result.value) if result.value is not None else "N/A"

    payload = {
        "content": f"🤖 **{eval_name}** evaluated: `{input_data.get('command', input_data.get('state', 'unknown'))}`",
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": [
                    {"name": "Status", "value": status, "inline": True},
                    {"name": "Value", "value": val_str, "inline": True},
                    {"name": "Reasoning", "value": f"```{reasoning}```", "inline": False}
                ],
                # Discord requires strict ISO 8601 format
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        ]
    }

    def _send():
        r = requests.post(webhook_url, json=payload, timeout=5)
        # If Discord rejects the payload, this throws an HTTPError
        r.raise_for_status()

    try:
        await asyncio.to_thread(_send)
    except Exception as e:
        # Instead of failing silently, let's warn the user in the CLI
        console.print(f"[dim yellow]⚠ Discord webhook failed: {e}[/dim yellow]")
