# run.py
import re
import asyncio
import sys
from rich.panel import Panel
from rich.console import Console

from assets.registry import ask_tool

console = Console()

@ask_tool(
    name="run",
    description="Execute a Linux command.",
    schema_properties={"command": {"type": "string"}}
)
async def run_handler(ctx, agent, args, internal_msgs=None):
    cmd = args.get("command", "")
    if not cmd:
        return "Error: No command provided."

    # Use context instead of shared globals
    watch_result = await ctx.security_watcher(cmd)
    alpha_chars = re.sub(r'[^a-zA-Z]', '', watch_result.upper())
    watcher_passed = alpha_chars.endswith('P') if alpha_chars else False

    human_passed = False
    auto_approve = ctx.config.get('auto_approve_default', False)

    async with ctx.ui_lock:
        if auto_approve and watcher_passed:
            console.print(f"[bold green]Auto-approved: [cyan]{cmd}[/cyan]")
            human_passed = True
        else:
            console.print(Panel(f"[cyan]{cmd}[/cyan]", title="Permission Required"))
            if auto_approve and not watcher_passed:
                console.print(f"[bold red]Watcher flagged this command! Reasoning:[/bold red]\n[dim]{watch_result}[/dim]")

            # Safe async prompt
            ans = await ctx.async_prompt_user("Run this command? (y/n): ")
            human_passed = ans.lower() == 'y'

        if human_passed != watcher_passed:
            ans = await ctx.async_prompt_user("Security mismatch. Proceed anyway? (y/n): ")
            if ans.lower() != 'y':
                return "User aborted due to security mismatch."

    if not human_passed:
        return "User denied execution."

    try:
        if ctx.config.get('use_sandbox_default', False):
            cmd_escaped = cmd.replace("'", "'\\''")
            cmd = f"bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /home --tmpfs /root --tmpfs /tmp --unshare-all --die-with-parent -- sh -c '{cmd_escaped}'"

        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await process.communicate()
        output = stdout.decode('utf-8', errors='replace')

        # Dynamically calculate truncation based on remaining context
        budget = ctx.get_token_budget()
        max_chars = max(500, int(budget * 3.5))  # Min 500 chars, else heuristic

        if len(output) > max_chars:
            console.print(f"[bold yellow]Warning: Output truncated to {max_chars} chars to fit context budget.[/bold yellow]")
            ans = await ctx.async_prompt_user("Continue with truncated output? (y/n): ")
            if ans.lower() != 'y':
                return "User aborted due to truncation."
            return output[:max_chars] + "\n[TRUNCATED: LOW CONTEXT BUDGET]"
        return output
    except Exception as e:
        return f"Command failed: {str(e)}"
