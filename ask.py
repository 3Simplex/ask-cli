#!/usr/bin/env python3

import os, sys, json, subprocess, requests, argparse, glob, time
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
API_URL, API_KEY = "http://localhost:8080/v1/chat/completions", "KEY"
TIMEOUT, MAX_RESULT_CHARS = 120, 16768
console = Console()

os.makedirs(CONF_DIR, exist_ok=True)
os.makedirs(THREAD_DIR, exist_ok=True)
os.makedirs(ROUTINE_DIR, exist_ok=True)

def get_identity_prompt(interactive_on, memory_active):
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
    
    return f"""
### CORE IDENTITY ###
You are 'ask', a professional Linux CLI assistant for {os_info}.
Current Shell: {shell_info}
Current Operational State: {mode_label} | {mem_label}
User Status: {admin}

### NIXOS CONSTRAINTS (MANDATORY) ###
1. Software is managed declaratively via `/etc/nixos/configuration.nix` or flakes.
2. For temporarily executing tools without installing them, ALWAYS suggest `nix-shell -p <pkg>` or `nix run nixpkgs#<pkg>`.
3. Preferences: {prefs.get('system_preference', 'None')}
4. Tool Usage: {"ENABLED. Use TOOL: {{'name': '...', ...}} blocks." if interactive_on else "DISABLED. Do NOT use tools. Guide the user manually."}

### TOOL DEFINITIONS (Interactive Mode Only) ###
- TOOL: {{"name": "run", "command": "..."}} -> Execute and SEE output. Use for "what is the status" or small system checks where you need to ingest the data.
- TOOL: {{"name": "display", "command": "..."}} -> Run and show to USER ONLY via pager. You do NOT see the data. Use for "show the status" or large lists.
- TOOL: {{"name": "search", "query": "..."}} -> Search DuckDuckGo.
- TOOL: {{"name": "read", "url": "..."}} -> Read webpage content.

### GROUNDING RULES ###
- If memory is INACTIVE, act as if this is the first time meeting the user.
- If memory is ACTIVE, continue the previous context naturally.
"""

def prompt_user(prompt_text):
    if not sys.stdin.isatty():
        with open('/dev/tty', 'r') as tty:
            console.print(prompt_text, end="")
            return tty.readline().strip()
    return input(prompt_text)

def run_cmd(cmd, silent=False):
    if not silent:
        console.print(Panel(f"[bold yellow]Action Proposed:[/bold yellow]\n[cyan]{cmd}[/cyan]", title="Permission Required"))
        if prompt_user("Run this command? (y/n): ").lower() != 'y': return "User denied execution."
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8')
        return output[:MAX_RESULT_CHARS] + ("\n[TRUNCATED]" if len(output) > MAX_RESULT_CHARS else "")
    except subprocess.CalledProcessError as e:
        return f"Command failed with output: {e.output.decode('utf-8')}"

def display_cmd(cmd):
    console.print(Panel(f"[bold green]Displaying to User:[/bold green]\n[cyan]{cmd}[/cyan]", title="User Pager View"))
    if prompt_user("View this output? (y/n): ").lower() == 'y':
        try:
            subprocess.run(f"{cmd} | less", shell=True)
            return "SUCCESS: Output displayed to user. (Note: You, the AI, have not seen this data)."
        except Exception as e: return f"Display failed: {e}"
    return "User denied display."

def main():
    parser = argparse.ArgumentParser(description="Agentic NixOS Assistant")
    parser.add_argument("query", nargs="*", help="Your question")
    parser.add_argument("-i", "--interactive", action="store_true", help="Enable tool usage")
    parser.add_argument("-c", "--continue-last", action="store_true", help="Resume last session")
    parser.add_argument("-r", "--routine", help="Load a routine playbook")
    args = parser.parse_args()

    latest_file = None
    files = glob.glob(os.path.join(THREAD_DIR, "*.json"))
    if files:
        latest_file = max(files, key=os.path.getmtime)
        if not args.continue_last and not args.routine and (time.time() - os.path.getmtime(latest_file)) < 600:
            console.print("[dim italic]💡 Hint: Use '-c' to continue your recent conversation.[/dim italic]")

    messages =[]
    memory_active = False
    if args.continue_last and latest_file:
        try:
            with open(latest_file, 'r') as f: 
                messages = json.load(f)
                memory_active = True
        except: console.print("[red]Failed to load thread.[/red]")

    if not messages:
        messages.append({"role": "system", "content": get_identity_prompt(args.interactive, memory_active)})
    else:
        messages[0]["content"] = get_identity_prompt(args.interactive, memory_active)

    if args.routine:
        tpath = os.path.join(ROUTINE_DIR, f"{args.routine}.md")
        if os.path.exists(tpath):
            with open(tpath, 'r') as f:
                messages.append({"role": "user", "content": f"START ROUTINE PLAYBOOK:\n{f.read()}"})

    user_query = " ".join(args.query).strip()
    piped_data = ""
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()

    if piped_data:
        if user_query:
            user_query = f"{user_query}\n\n[PIPED DATA]:\n{piped_data}"
        else:
            user_query = piped_data

    if not user_query and not args.routine and not args.continue_last:
        console.print(Panel("[bold cyan]Ask CLI[/bold cyan]\n'ask -r tutorial' to begin.", expand=False))
        return

    if user_query: 
        tool_status = "ENABLED (You MUST use TOOL blocks to execute commands)" if args.interactive else "DISABLED (Do NOT use tools)"
        enhanced_query = f"[SYSTEM NOTE: Interactive tools are currently {tool_status}]\n\n{user_query}"
        messages.append({"role": "user", "content": enhanced_query})

    while True:
        with Live(Spinner("dots", text="Thinking...", style="cyan"), transient=True):
            try:
                r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={"messages": messages}, timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
                content = data['choices'][0]['message'].get('content') or data['choices'][0]['message'].get('reasoning_content', "")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}"); break

        if "TOOL:" in content:
            if not args.interactive:
                messages.extend([{"role": "assistant", "content": content}, 
                                 {"role": "user", "content": "Error: Tools are DISABLED. Answer manually or ask user to use -i."}])
                continue
            
            try:
                line =[l for l in content.split('\n') if "TOOL:" in l][0]
                tool = json.loads(line.split("TOOL:")[1].strip())
                res = ""
                
                if tool['name'] == 'run':
                    res = run_cmd(tool['command'])
                elif tool['name'] == 'display':
                    res = display_cmd(tool['command'])
                elif tool['name'] == 'search':
                    console.print(f"[blue]🔍 Searching:[/blue] {tool['query']}")
                    res_raw = subprocess.check_output(["ddgr", "--json", "-n", "3", tool['query']], stderr=subprocess.DEVNULL)
                    res = str(json.loads(res_raw))
                elif tool['name'] == 'read':
                    console.print(f"[blue]📖 Reading:[/blue] {tool['url']}")
                    res = subprocess.check_output(["lynx", "-dump", "-nolist", tool['url']], timeout=10).decode('utf-8')[:MAX_RESULT_CHARS]
                
                messages.extend([{"role": "assistant", "content": content}, {"role": "user", "content": f"TOOL RESULT:\n{res}"}])
                continue
            except Exception as e:
                messages.append({"role": "user", "content": f"Tool Error: {e}"}); continue

        subprocess.run(['glow'], input=content.encode())
        messages.append({"role": "assistant", "content": content})
        
        safe_q = "".join([c if c.isalnum() else "_" for c in (user_query[:30] if user_query else "session")])
        fname = os.path.join(THREAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_q}.json")
        with open(fname, 'w') as f: json.dump(messages, f)
        break

if __name__ == "__main__": main()
