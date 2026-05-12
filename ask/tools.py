import json
import re
import subprocess
import sys
from rich.console import Console
from rich.panel import Panel
from .config import MAX_RESULT_CHARS
from .security import security_watcher
from . import config

console = Console()

def prompt_user(prompt_text: str) -> str:
    if not sys.stdin.isatty():
        with open('/dev/tty', 'r') as tty:
            console.print(prompt_text, end="")
            return tty.readline().strip()
    return input(prompt_text)

def run_cmd(cmd: str, silent: bool = False) -> str:
    console.print("[dim italic]🛡  Security Watcher is analyzing...[/dim italic]")
    watch_result = security_watcher(cmd)
    watcher_passed = watch_result.strip().endswith('P')

    human_passed = False
    if not silent:
        if config.AUTO_APPROVE and watcher_passed:
            console.print(f"[bold green]⚡ Auto-approved by Watcher:[/bold green] [cyan]{cmd}[/cyan]")
            human_passed = True
        else:
            console.print(Panel(f"[bold yellow]Action Proposed:[/bold yellow]\n[cyan]{cmd}[/cyan]", title="Permission Required"))
            if config.AUTO_APPROVE and not watcher_passed:
                console.print("[bold red]Watcher flagged this command! Manual override required.[/bold red]")
            human_passed = prompt_user("Run this command? (y/n): ").lower() == 'y'
    else:
        human_passed = True

    if human_passed != watcher_passed:
        console.print(Panel(f"[bold red]CONFLICT DETECTED![/bold red]\nHuman Approved: {human_passed}\nWatcher Approved: {watcher_passed}\n[bold]Watcher Reasoning:[/bold]\n{watch_result}", title="Security Mismatch"))
        if prompt_user("Are you absolutely sure you want to proceed with your choice? (y/n): ").lower() != 'y':
            return "User aborted due to security watcher mismatch."
        if not human_passed:
            return "User definitively denied execution."
    else:
        if not human_passed:
            return "User and Watcher agreed to deny execution."

    try:
        if config.USE_SANDBOX:
            safe_cmd = cmd.replace("'", "'\\''")
            cmd = f"bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /home --tmpfs /root --tmpfs /tmp --unshare-all --die-with-parent -- sh -c '{safe_cmd}'"
            console.print("[dim italic]📦 Executing inside Bubblewrap Sandbox...[/dim italic]")
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8', errors='replace')
        return output[:MAX_RESULT_CHARS] + ("\n[TRUNCATED]" if len(output) > MAX_RESULT_CHARS else "")
    except subprocess.CalledProcessError as e:
        return f"Command failed with output: {e.output.decode('utf-8')}"

def display_cmd(cmd: str) -> str:
    console.print(Panel(f"[bold green]Displaying to User:[/bold green]\n[cyan]{cmd}[/cyan]", title="User Pager View"))
    if prompt_user("View this output? (y/n): ").lower() == 'y':
        try:
            subprocess.run(f"{cmd} | less", shell=True)
            return "SUCCESS: Output displayed to user."
        except Exception as e:
            return f"Display failed: {e}"
    return "User denied display."

def parse_tool_call(content: str):
    # Try legacy TOOL: format
    if "TOOL:" in content:
        try:
            line = [line for line in content.split('\n') if "TOOL:" in line][0]
            return json.loads(line.split("TOOL:")[1].strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # Try native call: format
    match = re.search(r"call:([a-zA-Z0-9_]+)\{([^}]*)\}", content)
    if match:
        try:
            func_name = match.group(1)
            args_str = match.group(2).strip()
            # Basic attempt to fix unquoted keys
            args_str_fixed = re.sub(r'([a-zA-Z0-9_]+)\s*:', r'"\1":', args_str)
            tool_args = json.loads(f"{{{args_str_fixed}}}") if args_str_fixed else {}
            return {"name": func_name, **tool_args}
        except json.JSONDecodeError:
            pass

    return None
