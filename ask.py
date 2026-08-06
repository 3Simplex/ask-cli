#!/usr/bin/env python3
import os, sys, json, argparse, glob, asyncio, requests, subprocess
from pathlib import Path
from datetime import datetime
import uuid

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.markdown import Markdown

# Initialize Architecture
from assets.context import AskContext
from assets.agent import Agent
from assets.registry import TOOL_REGISTRY

# Import tools to trigger their @ask_tool decorators
import assets.tools.gc
import assets.tools.search
import assets.tools.run
import assets.tools.read
import assets.tools.set_state

console = Console()

def gen_id(prefix="msg"): return f"{prefix}_{uuid.uuid4().hex[:6]}"

def sync_thread_file(filepath, msgs):
    if not filepath: return
    try:
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w') as f: json.dump(msgs, f)
        os.replace(temp_file, filepath)
    except: pass

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="*", help="Your question")
    parser.add_argument("-i", "--interactive", action="store_true", help="Enable tools")
    parser.add_argument("-c", "--continue-session", nargs="?", const="LAST", help="Continue session")
    parser.add_argument("-a", "--agent", type=str, default="ask", help="The agent profile to use (e.g., ask, linux, dev)")
    parser.add_argument("--auto", action="store_true", help="Auto-approve safe commands")
    parser.add_argument("-s", "--sandbox", action="store_true", help="Run in bwrap sandbox")
    parser.add_argument("-r", "--routine", type=str, help="Load a specific routine")
    parser.add_argument("--oobe", action="store_true", help="Run first-run setup wizard (even if config exists)")
    args = parser.parse_args()

    # ── Auto-run OOBE on first launch (BEFORE any context creation) ──
    # Change config_path to point to the user's writable home directory
    config_path = Path.home() / ".local" / "share" / "ask" / "config.json"

    if not config_path.exists():
        console.print("[bold yellow]No configuration found. Starting first-run setup...[/bold yellow]")

        oobe_bin = Path(__file__).parent / "oobe"
        if oobe_bin.exists():
            # Running in Nix: execute the bash wrapper directly
            subprocess.run([str(oobe_bin)], check=True)
        else:
            # Running locally: execute via Python
            subprocess.run([sys.executable, str(Path(__file__).parent / "oobe.py")], check=True)

    # --- RESTORE PIPED STDIN ---
    user_query = " ".join(args.query).strip()
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()
        if piped_data:
            user_query += f"\n\n[PIPED DATA]:\n{piped_data}"

    ctx = AskContext(args)

    # Check if we need to cold start a local server
    await ctx.ensure_server_running()

    agent = Agent(ctx, agent_name=args.agent)

    # --- Session Loading ---
    latest_file = None
    if args.continue_session:
        files = glob.glob(str(ctx.threads_dir / "*.json"))
        if args.continue_session != "LAST":
            matched = [f for f in files if args.continue_session in f]
            latest_file = max(matched, key=os.path.getmtime) if matched else str(ctx.threads_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.continue_session}.json")
        elif files:
            latest_file = max(files, key=os.path.getmtime)

    if not latest_file:
        safe_q = "".join([c if c.isalnum() else "_" for c in (user_query[:30] if user_query else "session")]) or "session"
        latest_file = str(ctx.threads_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_q}.json")

    internal_msgs = []
    if os.path.exists(latest_file):
        try:
            with open(latest_file, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    if "state" in loaded:
                        agent.state_name = loaded["state"]
                    # Load the saved model for this session
                    if "model" in loaded:
                        ctx.config["model"] = loaded["model"]
                    internal_msgs = loaded.get("messages", [])
        except: pass

    if not internal_msgs:
        identity = f"You are {agent.name}. {agent.profile.get('description', '')}"
        internal_msgs.append({"id": "sys", "role": "system", "content": identity.replace("  ", " ").strip(), "gc": False})

    if user_query:
        # NOTE: Removed automatic state setting! Let the AI manage it.
        internal_msgs.append({"id": gen_id("usr"), "role": "user", "content": user_query, "gc": False})

    # Trigger model selection if one isn't set yet
    await ctx.select_model_if_needed()

    with open(latest_file, 'w') as f:
        # Save the model to the thread state
        json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "messages": internal_msgs}, f)

    turn_count = 0

    while True:
        turn_count += 1

        # --- RESTORE MAX TURNS PROMPT ---
        if turn_count > ctx.config.get("max_turns", 10):
            console.print("[bold yellow]Warning: Maximum autonomous loops reached.[/bold yellow]")
            ans = await ctx.async_prompt_user("Continue anyway? (y/n): ")
            if ans.lower() == 'y':
                turn_count = 0  # Reset counter
            else:
                break

        fresh_ctx = await agent._resolve_context()

        # Pass internal_msgs directly — agent handles ID injection inline
        payload = await agent.get_api_payload(internal_msgs, fresh_ctx, interactive=args.interactive)

        # Inject the active session model into the payload
        if ctx.config.get("model"):
            payload["model"] = ctx.config["model"]

        with Live(Spinner("dots", text=f"Thinking [{agent.state_name.upper()}]...", style="cyan"), transient=True):
            # --- RESTORE API ERROR HANDLING ---
            try:
                r = await asyncio.to_thread(
                    requests.post, f"{ctx.config['api_base']}/chat/completions",
                    headers={"Authorization": f"Bearer {ctx.config['api_key']}"},
                    json=payload, timeout=ctx.config['timeout']
                )
                r.raise_for_status()
                response_msg = r.json()['choices'][0]['message']
            except requests.exceptions.RequestException as e:
                err_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try: err_msg += f"\nDetails: {e.response.json()}"
                    except: err_msg += f"\nDetails: {e.response.text}"
                console.print(f"\n[bold red]API Error:[/bold red] {err_msg}")
                break

        ast_msg = {"id": gen_id("ast"), "role": "assistant", "content": response_msg.get('content') or "", "gc": False}
        if "tool_calls" in response_msg:
            ast_msg["tool_calls"] = response_msg["tool_calls"]

        # 1. APPEND THE MESSAGE TO THE THREAD
        internal_msgs.append(ast_msg)

        # 2. PRINT TEXT TO CONSOLE
        if ast_msg["content"]:
            console.print(Markdown(ast_msg["content"]))

        # 3. HANDLE TOOLS
        if "tool_calls" in response_msg:
            console.print(f"\n[bold cyan]🔧 Executing {len(response_msg['tool_calls'])} tool(s)...[/bold cyan]")

            async def run_tool(tc):
                name = tc['function']['name']
                console.print(f"[dim]  → Running: {name}...[/dim]")
                try:
                    tc_args = json.loads(tc['function']['arguments'])
                except:
                    tc_args = {}
                try:
                    if name in TOOL_REGISTRY:
                        res = await TOOL_REGISTRY[name]["handler"](ctx, agent, tc_args, internal_msgs)
                    else:
                        res = f"Unknown tool {name}"
                except Exception as e:
                    res = f"Tool Execution Error: {str(e)}"
                return {"role": "tool", "tool_call_id": tc['id'], "name": name, "content": str(res)}

            tasks = [run_tool(tc) for tc in response_msg["tool_calls"]]
            results = await asyncio.gather(*tasks)
            internal_msgs.extend(results)

            # Filter out gc'd messages so they never appear again
            internal_msgs[:] = [m for m in internal_msgs if not m.get("gc")]

            # Persist state alongside messages
            with open(latest_file, 'w') as f:
                json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "messages": internal_msgs}, f)

            console.print("[bold green]✅ Tools completed.[/bold green]\n")
            continue

        # 4. IF NO TOOLS, SAVE FINAL STATE AND BREAK
        with open(latest_file, 'w') as f:
            json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "messages": internal_msgs}, f)
        break

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold red]Operation aborted by user.[/bold red]")
        sys.exit(0)
