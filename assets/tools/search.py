import json
import subprocess
import asyncio
from assets.core.registry import ask_tool
from assets.core import defaults
from rich.console import Console

console = Console()

@ask_tool(
    name="search",
    description="Search DuckDuckGo.",
    schema_properties={"query": {"type": "string"}}
)
async def search_handler(ctx, agent, args, internal_msgs=None):
    query = args.get('query', '')
    console.print(f"[blue]Searching:[/blue] {query}")

    max_retries = defaults.get(ctx.config, "search_retry_count")
    base_delay = defaults.get(ctx.config, "search_retry_base_delay")
    timeout = defaults.get(ctx.config, "search_timeout")

    for attempt in range(1, max_retries + 1):
        try:
            # Use the rate limiter from context!
            await ctx.search_limiter.acquire()
            try:
                raw = await asyncio.to_thread(
                    subprocess.check_output,
                    ["ddgr", "--json", "-n", "3", query],
                    stderr=subprocess.STDOUT,
                    timeout=timeout
                )
                if raw.strip():
                    result_str = str(json.loads(raw))

                    # Prevent massive JSON from blowing the context
                    budget = ctx.get_token_budget()
                    max_chars = max(500, int(budget * 3.5))

                    if len(result_str) > max_chars:
                        console.print(f"[bold yellow]Warning: Search output truncated to fit context budget.[/bold yellow]")
                        return result_str[:max_chars] + "\n[TRUNCATED: LOW CONTEXT BUDGET]"

                    return result_str
                return "Error: Search returned no results."
            except subprocess.TimeoutExpired:
                console.print(f"[yellow]Search timed out (attempt {attempt}/{max_retries})[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Search error (attempt {attempt}/{max_retries}): {e}[/yellow]")
                if attempt < max_retries:
                    wait = base_delay * (2 ** (attempt - 1))
                    console.print(f"[dim]Retrying in {wait:.1f}s...[/dim]")
                    await asyncio.sleep(wait)
                else:
                    return f"Error: Search failed after {max_retries} attempts: {e}"
        finally:
            await ctx.search_limiter.release()

    return "Error: Search failed after maximum retries."
