import argparse
import glob
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner

from . import config
from .api import (
    build_api_payload,
    detect_server_capabilities,
    encode_image,
    get_identity_prompt,
)
from .config import (
    API_URL,
    ROUTINE_DIR,
    THREAD_DIR,
    TIMEOUT,
    init_dirs,
)
from .session import gen_id, sync_thread_file
from .tools import display_cmd, parse_tool_call, run_cmd

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Agentic NixOS Assistant")
    parser.add_argument("query", nargs="*", help="Your question")
    parser.add_argument("-i", "--interactive", action="store_true", help="Enable tool usage")
    parser.add_argument("-a", "--auto", action="store_true", help="Auto-approve commands if Watcher passes")
    parser.add_argument("-s", "--sandbox", action="store_true", help="Wrap commands in a secure Bubblewrap sandbox")
    parser.add_argument("-c", "--continue-session", dest="continue_session", metavar="SESSION_NAME", nargs="?", const="LIST", default=None, help="List sessions (no args), resume a session by name, or create a new named session. Falls back to LAST session if no name matched and no distinct query given.")
    parser.add_argument("-r", "--routine", nargs="?", const="LIST", help="Load a routine playbook. Use without args to list.")
    parser.add_argument("-img", "--image", action="append", help="Path to image to include")
    args = parser.parse_args()

    config.AUTO_APPROVE = args.auto
    config.USE_SANDBOX = args.sandbox

    init_dirs()

    is_multimodal, model_name = detect_server_capabilities()

    user_query = " ".join(args.query).strip()
    piped_data = ""
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()

    if piped_data:
        user_query = f"{user_query}\n\n[PIPED DATA]:\n{piped_data}" if user_query else piped_data

    if args.routine == "LIST":
        routines = glob.glob(str(ROUTINE_DIR / "*.md"))
        if routines:
            console.print(Panel("\n".join([os.path.basename(r)[:-3] for r in routines]), title="Available Routines"))
        else:
            console.print("[red]No routines found.[/red]")
        return

    if args.continue_session == "LIST":
        sessions = glob.glob(str(THREAD_DIR / "*.json"))
        if sessions:
            sessions.sort(key=os.path.getmtime, reverse=True)
            lines = [os.path.basename(s)[:-5] for s in sessions[:20]]
            console.print(Panel("\n".join(lines), title="Recent Sessions (use: ask -c <name>)"))
        else:
            console.print("[red]No sessions found.[/red]")
        return

    latest_file = None
    files = glob.glob(str(THREAD_DIR / "*.json"))

    if args.continue_session and args.continue_session not in ["LAST", "LIST"]:
        matched = glob.glob(str(THREAD_DIR / f"*{args.continue_session}*.json"))
        if matched:
            latest_file = Path(max(matched, key=os.path.getmtime))
        else:
            if user_query:
                latest_file = THREAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.continue_session}.json"
            else:
                user_query = args.continue_session
                args.continue_session = "LAST"

    if args.continue_session == "LAST" and not latest_file and files:
        latest_file = Path(max(files, key=os.path.getmtime))

    if not args.continue_session and not args.routine and files:
        last_any = max(files, key=os.path.getmtime)
        if (time.time() - os.path.getmtime(last_any)) < 600:
            console.print("[dim italic]💡 Hint: Use '-c' to continue your recent conversation.[/dim italic]")

    internal_msgs = []
    memory_active = False

    if args.continue_session and latest_file:
        if latest_file.exists():
            try:
                with open(latest_file, 'r') as f:
                    internal_msgs = json.load(f)
                    memory_active = True
            except (json.JSONDecodeError, IOError):
                console.print(f"[red]Failed to load thread: {latest_file}[/red]")
    else:
        safe_q = "".join([c if c.isalnum() else "_" for c in (user_query[:30] if isinstance(user_query, str) and user_query else "session")])
        if not safe_q:
            safe_q = "session"
        latest_file = THREAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_q}.json"

    sys_prompt = get_identity_prompt(args.interactive, memory_active, is_multimodal)
    if not internal_msgs:
        internal_msgs.append({"id": "sys", "role": "system", "content": sys_prompt, "gc": False})
    else:
        internal_msgs[0]["content"] = sys_prompt

    if args.routine and args.routine != "LIST":
        tpath = ROUTINE_DIR / f"{args.routine}.md"
        if tpath.exists():
            with open(tpath, 'r') as f:
                internal_msgs.append({"id": gen_id("rtn"), "role": "user", "content": f"START ROUTINE PLAYBOOK:\n{f.read()}", "gc": False})
        else:
            console.print(f"[red]Routine '{args.routine}' not found.[/red]")
            return

    if not user_query and not args.routine and not args.continue_session:
        console.print(Panel("[bold cyan]Ask CLI[/bold cyan]\n'ask -r tutorial' to begin.", expand=False))
        return

    if user_query or args.image:
        tool_status = "ENABLED (Use TOOL blocks)" if args.interactive else "DISABLED"
        enhanced_query = f"[SYSTEM NOTE: Interactive tools are {tool_status}]\n\n{user_query}"

        final_content = enhanced_query
        if args.image:
            final_content = [{"type": "text", "text": enhanced_query}]
            for img_path in args.image:
                if os.path.exists(img_path):
                    mime_type, _ = mimetypes.guess_type(img_path)
                    final_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type or 'image/jpeg'};base64,{encode_image(img_path)}"}
                    })
                else:
                    console.print(f"[red]Image not found:[/red] {img_path}")

        internal_msgs.append({"id": gen_id("usr"), "role": "user", "content": final_content, "gc": False})

    sync_thread_file(latest_file, internal_msgs)

    while True:
        sync_thread_file(latest_file, internal_msgs)
        api_messages = build_api_payload(internal_msgs)

        with Live(Spinner("dots", text="Thinking...", style="cyan"), transient=True):
            try:
                r = requests.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {config.API_KEY}"},
                    json={"messages": api_messages},
                    timeout=TIMEOUT
                )
                r.raise_for_status()
                data = r.json()
                content = data['choices'][0]['message'].get('content') or data['choices'][0]['message'].get('reasoning_content', "")
            except Exception as e:
                console.print(f"[red]API Error:[/red] {e}")
                break

        content = re.sub(r"^\s*\[ID:[^\]]+\]\s*", "", content)
        ast_id = gen_id("ast")
        internal_msgs.append({"id": ast_id, "role": "assistant", "content": content, "gc": False})

        sync_thread_file(latest_file, internal_msgs)

        tool = parse_tool_call(content)
        if tool:
            if not args.interactive:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": "Error: Tools are DISABLED.", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

            try:
                res = ""
                if tool['name'] == 'gc':
                    ids_to_remove = tool.get('ids', [])
                    removed_count = 0
                    for m in internal_msgs:
                        if m.get('id') in ids_to_remove and m.get('id') != "sys":
                            m['gc'] = True
                            removed_count += 1
                    res = f"SUCCESS: Garbage collected {removed_count} messages."
                    console.print(f"[dim]🧹 Garbage Collected {removed_count} blocks.[/dim]")

                elif tool['name'] == 'run':
                    res = run_cmd(tool.get('command', ''))
                elif tool['name'] == 'display':
                    res = display_cmd(tool.get('command', ''))
                elif tool['name'] == 'search':
                    query = tool.get('query', '')
                    console.print(f"[blue]🔍 Searching:[/blue] {query}")
                    res_raw = subprocess.check_output(["ddgr", "--json", "-n", "3", query], stderr=subprocess.DEVNULL)
                    res = str(json.loads(res_raw))
                elif tool['name'] == 'read':
                    console.print(f"[blue]📖 Reading:[/blue] {tool['url']}")
                    res = subprocess.check_output(["lynx", "-dump", "-nolist", "-display_charset=utf-8", "-assume_charset=utf-8", tool['url']], timeout=180).decode('utf-8', errors='replace')[:config.MAX_RESULT_CHARS]
                else:
                    res = f"Error: Unknown tool '{tool['name']}'"

                internal_msgs.append({"id": gen_id("res"), "role": "user", "content": f"TOOL RESULT:\n{res}", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

            except Exception as e:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": f"Tool Error: {e}", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

        clean_content = "\n".join([line for line in content.split("\n") if "TOOL:" not in line and "<|tool_call>" not in line])

        try:
            subprocess.run(['glow'], input=clean_content.encode())
        except FileNotFoundError:
            from rich.markdown import Markdown
            console.print(Markdown(clean_content))

        break
