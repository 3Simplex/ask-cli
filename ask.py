#!/usr/bin/env python3

import os, sys, json, subprocess, requests, argparse, glob, time, re
import base64, mimetypes, uuid
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner

# --- Paths & Global Config ---
CONF_DIR = os.path.expanduser("~/.config/ask")
DATA_DIR = os.path.expanduser("~/.local/share/ask")
THREAD_DIR = os.path.join(DATA_DIR, "threads")
ROUTINE_DIR = os.path.join(DATA_DIR, "routines")
PREF_FILE = os.path.join(CONF_DIR, "preferences.json")

with open(os.path.join(os.path.dirname(__file__), 'assets', 'config', 'config.json'), 'r') as f: _cfg = json.load(f)
API_BASE = _cfg['api_base']
API_URL = f'{API_BASE}/chat/completions'
API_MODELS_URL = f'{API_BASE}/models'
API_KEY = _cfg['api_key']
TIMEOUT = _cfg['timeout']
MAX_RESULT_CHARS = _cfg['max_result_chars']
AUTO_APPROVE_DEFAULT = _cfg['auto_approve_default']
USE_SANDBOX_DEFAULT = _cfg['use_sandbox_default']
AUTO_APPROVE = AUTO_APPROVE_DEFAULT
USE_SANDBOX = USE_SANDBOX_DEFAULT

WATCHER_LOG_DIR = os.path.join(DATA_DIR, "security_audit")
os.makedirs(WATCHER_LOG_DIR, exist_ok=True)
WATCHER_SYSTEM_PROMPT = """You are a high-security command auditor.
Your sole purpose is to analyze proposed Linux commands for malicious intent,
unauthorized data exfiltration, or destructive actions.

Evaluate the command based on:
1. Privilege escalation attempts.
2. Destructive filesystem operations (e.g., rm -rf /).
3. Network exfiltration (e.g., curl, wget to unknown IPs).
4. Obfuscated shell syntax.

Response Format:
- If safe: 'Reasoning:[Brief explanation] P'
- If unsafe: 'Reasoning: [Detailed reason] F'
"""

def security_watcher(cmd):
    payload = {
        "messages":[
            {"role": "system", "content": WATCHER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this command: {cmd}"}
        ]
    }
    try:
        r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json=payload, timeout=180)
        r.raise_for_status()
        response_text = r.json()['choices'][0]['message'].get('content', "Reasoning: Error parsing response F")
        audit_entry = {
            "timestamp": datetime.now().isoformat(),
            "command": cmd,
            "decision": response_text
        }
        with open(os.path.join(WATCHER_LOG_DIR, "audit_log.jsonl"), "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        return response_text
    except Exception as e:
        return f"Reasoning: Watcher Error ({str(e)}) F"

console = Console()

os.makedirs(CONF_DIR, exist_ok=True)
os.makedirs(THREAD_DIR, exist_ok=True)
os.makedirs(ROUTINE_DIR, exist_ok=True)

def gen_id(prefix="msg"):
    return f"{prefix}_{uuid.uuid4().hex[:6]}"

def sync_thread_file(filepath, msgs):
    if not filepath: return
    try:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f: disk_msgs = json.load(f)
            except: disk_msgs =[]
            existing_ids = {m.get('id') for m in msgs if m.get('id')}
            for m in disk_msgs:
                if m.get('id') and m.get('id') not in existing_ids:
                    msgs.append(m)
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w') as f: json.dump(msgs, f)
        os.replace(temp_file, filepath)
    except Exception as e:
        pass

def detect_server_capabilities():
    try:
        r = requests.get(API_MODELS_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=3)
        if r.status_code == 200:
            models = r.json().get("data",[])
            for m in models:
                name = m.get("id", "").lower()
                if any(kw in name for kw in["vision", "vl", "llava", "gemma-4", "gemma4", "pixtral"]):
                    return True, m.get("id")
            if models: return False, models[0].get("id")
    except Exception:
        pass
    return False, "unknown"

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_identity_prompt(interactive_on, memory_active, is_multimodal):
    os_info = subprocess.getoutput("grep PRETTY_NAME /etc/os-release | cut -d'=' -f2 | tr -d '\"'")
    shell_info = os.environ.get("SHELL", "Unknown Shell")
    admin = "Administrator (sudo via wheel)" if "wheel" in subprocess.getoutput("groups") else "Standard User"

    prefs = {}
    if os.path.exists(PREF_FILE):
        try:
            with open(PREF_FILE, 'r') as f: prefs = json.load(f)
        except: pass

    mode_label = "[MODE: INTERACTIVE]" if interactive_on else "[MODE: READ-ONLY / ADVISORY]"
    mem_label = "[MEMORY LINK: ACTIVE]" if memory_active else "[MEMORY LINK: INACTIVE / FRESH SESSION]"
    mm_label = "ENABLED" if is_multimodal else "DISABLED"

    return f"""
### CORE IDENTITY ###
You are 'ask', an advanced, agentic Linux CLI assistant for {os_info}.
Current Shell: {shell_info}
Current Operational State: {mode_label} | {mem_label}
Multi-modal Capabilities: {mm_label}
User Status: {admin}

### NIXOS CONSTRAINTS (MANDATORY) ###
1. Software is managed declaratively via `/etc/nixos/configuration.nix` or flakes.
2. For temporarily executing tools, ALWAYS suggest `nix-shell -p <pkg>` or `nix run nixpkgs#<pkg>`.

### CONTEXT GARBAGE COLLECTION ###
You run on a large context model. To prevent context poisoning, you are equipped with a Garbage Collector.
Each message/tool block in your history is prepended with a metadata ID by the backend before you recieve it. If a conversational tangent is finished, or a large tool output is no longer needed, immediately use the `gc` tool to mark those messages for removal by the garbage collector. You should not write the metadata into a message yourself even if it looks like you should otherwise.

### TOOL DEFINITIONS ###
{ "Tools are DISABLED in this session." if not interactive_on else """
- TOOL: {"name": "run", "command": "..."} -> Execute and SEE output.
- TOOL: {"name": "display", "command": "..."} -> Run and show to USER ONLY via pager. You do NOT see the data.
- TOOL: {"name": "search", "query": "..."} -> Search DuckDuckGo.
- TOOL: {"name": "read", "url": "..."} -> Read webpage content.
- TOOL: {"name": "gc", "ids":["msg_123", "msg_456"]} -> Mark message for garbage collector.
"""}

### GROUNDING RULES ###
- If memory is INACTIVE, act as if this is the first time meeting the user.
- If memory is ACTIVE, continue naturally.
- You are an AI assistant that can call external tools.
- To call a tool, you MUST wrap the call between the special tokens:


TOOL: {{"name": "", "command": ""}}\n

"""

def prompt_user(prompt_text):
    if not sys.stdin.isatty():
        with open('/dev/tty', 'r') as tty:
            console.print(prompt_text, end="")
            return tty.readline().strip()
    return input(prompt_text)

def run_cmd(cmd, silent=False):
    global AUTO_APPROVE
    console.print("[dim italic]🛡  Security Watcher is analyzing...[/dim italic]")
    watch_result = security_watcher(cmd)
    watcher_passed = watch_result.strip().endswith('P')

    human_passed = False
    if not silent:
        if AUTO_APPROVE and watcher_passed:
            console.print(f"[bold green]⚡ Auto-approved by Watcher:[/bold green] [cyan]{cmd}[/cyan]")
            human_passed = True
        else:
            console.print(Panel(f"[bold yellow]Action Proposed:[/bold yellow]\n[cyan]{cmd}[/cyan]", title="Permission Required"))
            if AUTO_APPROVE and not watcher_passed:
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
        if USE_SANDBOX:
            safe_cmd = cmd.replace("'", "'\\''")
            cmd = f"bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /home --tmpfs /root --tmpfs /tmp --unshare-all --die-with-parent -- sh -c '{safe_cmd}'"
            console.print("[dim italic]📦 Executing inside Bubblewrap Sandbox...[/dim italic]")
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8', errors='replace')
        return output[:MAX_RESULT_CHARS] + ("\n[TRUNCATED]" if len(output) > MAX_RESULT_CHARS else "")
    except subprocess.CalledProcessError as e:
        return f"Command failed with output: {e.output.decode('utf-8')}"

def display_cmd(cmd):
    console.print(Panel(f"[bold green]Displaying to User:[/bold green]\n[cyan]{cmd}[/cyan]", title="User Pager View"))
    if prompt_user("View this output? (y/n): ").lower() == 'y':
        try:
            subprocess.run(f"{cmd} | less", shell=True)
            return "SUCCESS: Output displayed to user."
        except Exception as e: return f"Display failed: {e}"
    return "User denied display."

def build_api_payload(internal_msgs):
    api_msgs =[]
    for m in internal_msgs:
        if m.get("gc", False):
            continue

        role = m["role"]
        msg_id = m.get("id", "sys")
        raw_content = m["content"]

        prefix = f"[ID: {msg_id}]\n" if msg_id != "sys" and role != "system" else ""

        if isinstance(raw_content, str):
            content = prefix + raw_content
        elif isinstance(raw_content, list):
            content =[]
            for idx, block in enumerate(raw_content):
                if block["type"] == "text" and idx == 0:
                    content.append({"type": "text", "text": prefix + block["text"]})
                else:
                    content.append(block)

        api_msgs.append({"role": role, "content": content})
    return api_msgs

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
    global AUTO_APPROVE
    AUTO_APPROVE = args.auto
    global USE_SANDBOX
    USE_SANDBOX = args.sandbox

    is_multimodal, model_name = detect_server_capabilities()

    user_query = " ".join(args.query).strip()
    piped_data = ""
    if not sys.stdin.isatty(): piped_data = sys.stdin.read().strip()

    if piped_data:
        user_query = f"{user_query}\n\n[PIPED DATA]:\n{piped_data}" if user_query else piped_data

    if args.routine == "LIST":
        routines = glob.glob(os.path.join(ROUTINE_DIR, "*.md"))
        if routines:
            console.print(Panel("\n".join([os.path.basename(r)[:-3] for r in routines]), title="Available Routines"))
        else:
            console.print("[red]No routines found.[/red]")
        return

    if args.continue_session == "LIST":
        sessions = glob.glob(os.path.join(THREAD_DIR, "*.json"))
        if sessions:
            sessions.sort(key=os.path.getmtime, reverse=True)
            lines = [os.path.basename(s)[:-5] for s in sessions[:20]]
            console.print(Panel("\n".join(lines), title="Recent Sessions (use: ask -c <name>)"))
        else:
            console.print("[red]No sessions found.[/red]")
        return

    latest_file = None
    files = glob.glob(os.path.join(THREAD_DIR, "*.json"))
    
    if args.continue_session and args.continue_session not in["LAST", "LIST"]:
        matched = glob.glob(os.path.join(THREAD_DIR, f"*{args.continue_session}*.json"))
        if matched:
            latest_file = max(matched, key=os.path.getmtime)
        else:
            if user_query:
                # User provided a distinct name AND a query. Treat as a new named session.
                latest_file = os.path.join(THREAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.continue_session}.json")
            else:
                # User provided only one argument after -c, treat it as the query for the LAST session.
                user_query = args.continue_session
                args.continue_session = "LAST"

    if args.continue_session == "LAST" and not latest_file and files:
        latest_file = max(files, key=os.path.getmtime)

    if not args.continue_session and not args.routine and files:
        last_any = max(files, key=os.path.getmtime)
        if (time.time() - os.path.getmtime(last_any)) < 600:
            console.print("[dim italic]💡 Hint: Use '-c' to continue your recent conversation.[/dim italic]")

    internal_msgs =[]
    memory_active = False
    
    if args.continue_session and latest_file:
        if os.path.exists(latest_file):
            try:
                with open(latest_file, 'r') as f:
                    internal_msgs = json.load(f)
                    memory_active = True
            except: 
                console.print(f"[red]Failed to load thread: {latest_file}[/red]")
        # If it doesn't exist yet, memory_active remains False (correct for a new named session)
    else:
        safe_q = "".join([c if c.isalnum() else "_" for c in (user_query[:30] if isinstance(user_query, str) and user_query else "session")])
        if not safe_q: safe_q = "session"
        latest_file = os.path.join(THREAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_q}.json")

    sys_prompt = get_identity_prompt(args.interactive, memory_active, is_multimodal)
    if not internal_msgs:
        internal_msgs.append({"id": "sys", "role": "system", "content": sys_prompt, "gc": False})
    else:
        internal_msgs[0]["content"] = sys_prompt

    if args.routine and args.routine != "LIST":
        tpath = os.path.join(ROUTINE_DIR, f"{args.routine}.md")
        if os.path.exists(tpath):
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
            final_content =[{"type": "text", "text": enhanced_query}]
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

    # Save to disk immediately so other processes can see the user prompt
    sync_thread_file(latest_file, internal_msgs)

    while True:
        # Check disk for injected messages before talking to API
        sync_thread_file(latest_file, internal_msgs)
        api_messages = build_api_payload(internal_msgs)

        with Live(Spinner("dots", text="Thinking...", style="cyan"), transient=True):
            try:
                r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={"messages": api_messages}, timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
                content = data['choices'][0]['message'].get('content') or data['choices'][0]['message'].get('reasoning_content', "")
            except Exception as e:
                console.print(f"[red]API Error:[/red] {e}"); break

        content = re.sub(r"^\s*\[ID:[^\]]+\]\s*", "", content)
        ast_id = gen_id("ast")
        internal_msgs.append({"id": ast_id, "role": "assistant", "content": content, "gc": False})
        
        # Save assistant text immediately
        sync_thread_file(latest_file, internal_msgs)

        # --- ADVANCED TOOL PARSING (Bilingual) ---
        tool = None

        if "TOOL:" in content:
            if not args.interactive:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": "Error: Tools are DISABLED.", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue
            try:
                line =[l for l in content.split('\n') if "TOOL:" in l][0]
                tool = json.loads(line.split("TOOL:")[1].strip())
            except Exception as e:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": f"Tool Parse Error: {e}", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

        elif "<|tool_call>" in content or "call:" in content:
            if not args.interactive:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": "Error: Tools are DISABLED.", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue
            try:
                match = re.search(r"call:([a-zA-Z0-9_]+)\{([^}]*)\}", content)
                if match:
                    func_name = match.group(1)
                    args_str = match.group(2).strip()

                    args_str_fixed = re.sub(r'([a-zA-Z0-9_]+)\s*:', r'"\1":', args_str)

                    tool_args = json.loads(f"{{{args_str_fixed}}}") if args_str_fixed else {}
                    tool = {"name": func_name, **tool_args}
            except Exception as e:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": f"Native Tool Parse Error: {e}", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

        # --- TOOL EXECUTION ---
        if tool:
            try:
                res = ""
                if tool['name'] == 'gc':
                    ids_to_remove = tool.get('ids',[])
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
                    res = subprocess.check_output(["lynx", "-dump", "-nolist", "-display_charset=utf-8", "-assume_charset=utf-8", tool['url']], timeout=180).decode('utf-8', errors='replace')[:MAX_RESULT_CHARS]
                else:
                    res = f"Error: Unknown tool '{tool['name']}'"

                internal_msgs.append({"id": gen_id("res"), "role": "user", "content": f"TOOL RESULT:\n{res}", "gc": False})
                
                # Save tool result immediately
                sync_thread_file(latest_file, internal_msgs)
                continue

            except Exception as e:
                internal_msgs.append({"id": gen_id("err"), "role": "user", "content": f"Tool Error: {e}", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                continue

        # --- OUTPUT FORMATTING ---
        clean_content = "\n".join([line for line in content.split("\n") if "TOOL:" not in line and "<|tool_call>" not in line])

        try:
            subprocess.run(['glow'], input=clean_content.encode())
        except FileNotFoundError:
            from rich.markdown import Markdown
            console.print(Markdown(clean_content))

        break

if __name__ == "__main__": main()
