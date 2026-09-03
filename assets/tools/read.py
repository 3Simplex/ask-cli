# read.py
import subprocess
import asyncio
from pathlib import Path
from rich.console import Console
from assets.core.registry import ask_tool

console = Console()

@ask_tool(
    name="read",
    description="Read the content of a local file or a web page.",
    schema_properties={"target": {"type": "string", "description": "A local file path or a URL (http:// or https://)."}}
)
async def read_handler(ctx, agent, args, internal_msgs=None):
    # Fallback to older arg formats if the AI hallucinates them
    target = args.get("target", args.get("path", args.get("url", "")))
    if not target:
        return "Error: No target provided."

    is_url = target.startswith("http://") or target.startswith("https://")

    try:
        if is_url:
            console.print(f"[blue]📖 Reading URL:[/blue] {target}")
            raw = await asyncio.to_thread(
                subprocess.check_output,
                ["lynx", "-dump", "-nolist", "-display_charset=utf-8", target],
                stderr=subprocess.STDOUT
            )
            content = raw.decode('utf-8', errors='replace')
        else:
            console.print(f"[blue]📖 Reading File:[/blue] {target}")
            path = Path(target).expanduser()
            if not path.exists():
                return f"Error: File {target} does not exist."
            with open(path, 'r') as f:
                content = f.read()
    except Exception as e:
        return f"Error reading target: {str(e)}"

    # Dynamically calculate truncation based on remaining context
    budget = ctx.get_token_budget()
    max_chars = max(500, int(budget * 3.5))

    if len(content) > max_chars:
        async with ctx.ui_lock:
            console.print(f"[bold yellow]Warning: Read output truncated to {max_chars} chars to fit context budget.[/bold yellow]")
            ans = await ctx.async_prompt_user("Continue with truncated output? (y/n): ")
            if ans.lower() != 'y':
                return "User aborted due to truncation."
            return content[:max_chars] + "\n[TRUNCATED: LOW CONTEXT BUDGET]"

    return content
