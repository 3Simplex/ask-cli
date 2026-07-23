#!/usr/bin/env python3

import os, sys, json, subprocess, requests, argparse, glob, time, re
import base64, mimetypes, uuid, asyncio
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

CONFIG_SOURCE_DIR = os.environ.get('ASK_CONFIG_DIR')
if CONFIG_SOURCE_DIR:
    config_path = os.path.join(CONFIG_SOURCE_DIR, 'config.json')
else:
    dir_name = os.path.dirname(__file__)
    if os.path.exists(os.path.join(dir_name, 'assets')):
        config_path = os.path.join(dir_name, 'assets', 'config', 'config.json')
    else:
        config_path = os.path.join(os.path.dirname(dir_name), 'assets', 'config', 'config.json')

with open(config_path, 'r') as f: _cfg = json.load(f)
API_BASE = _cfg['api_base']
API_URL = f'{API_BASE}/chat/completions'
API_MODELS_URL = f'{API_BASE}/models'
API_KEY = _cfg['api_key']
TIMEOUT = _cfg['timeout']
MAX_RESULT_CHARS = _cfg['max_result_chars']
AUTO_APPROVE = _cfg['auto_approve_default']
USE_SANDBOX = _cfg['use_sandbox_default']
SEARCH_TIMEOUT = _cfg.get('search_timeout', 30)

# --- Load State Profiles from states.json ---
STATES_SOURCE_DIR = os.environ.get('ASK_STATES_DIR')
if STATES_SOURCE_DIR:
    STATE_PROFILES_PATH = os.path.join(STATES_SOURCE_DIR, 'states.json')
else:
    dir_name = os.path.dirname(__file__)
    # 1. Try checking adjacent to the script
    if os.path.exists(os.path.join(dir_name, 'assets')):
        STATE_PROFILES_PATH = os.path.join(dir_name, 'assets', 'states', 'states.json')
    # 2. Try looking relative to the config dir (since we know config works!)
    elif CONFIG_SOURCE_DIR and os.path.exists(os.path.join(os.path.dirname(CONFIG_SOURCE_DIR), 'states', 'states.json')):
        STATE_PROFILES_PATH = os.path.join(os.path.dirname(CONFIG_SOURCE_DIR), 'states', 'states.json')
    # 3. Fallback to standard relative path
    else:
        STATE_PROFILES_PATH = os.path.join(os.path.dirname(dir_name), 'assets', 'states', 'states.json')

with open(STATE_PROFILES_PATH, 'r') as f:
    _state_data = json.load(f)

# Build STATE_PROFILES from the JSON
STATE_PROFILES = {}
for state_name, state_info in _state_data.items():
    STATE_PROFILES[state_name] = {
        "temperature": state_info.get("temperature", 0.1),
        "max_tokens": -1,
        "reasoning_budget": state_info.get("reasoning_budget", 0),
        "desc": state_info.get("description", state_name)
    }


# --- CONCURRENCY LOCKS ---
ui_lock = asyncio.Lock()

# --- SEARCH RATE LIMITER ---
class SearchRateLimiter:
    """Simple token-bucket rate limiter for search queries."""
    def __init__(self, max_per_minute: int, delay: float, max_concurrent: int):
        self.max_per_minute = max_per_minute
        self.delay = delay
        self.max_concurrent = max_concurrent
        self._timestamps: list[float] = []
        self._active = 0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self.max_per_minute:
                oldest = self._timestamps[0]
                wait = 60 - (now - oldest) + self.delay
                console.print(f"[dim]Waiting {wait:.1f}s for search rate limit...[/dim]")
            if self._timestamps:
                last = self._timestamps[-1]
                wait = self.delay - (now - last)
                if wait > 0:
                    console.print(f"[dim]Waiting {wait:.1f}s between searches...[/dim]")
            self._timestamps.append(time.time())
            self._active += 1
        # Sleep OUTSIDE the lock
        if len(self._timestamps) >= self.max_per_minute:
            oldest = self._timestamps[0]
            wait = 60 - (time.time() - oldest) + self.delay
            await asyncio.sleep(wait)
        if self._timestamps:
            last = self._timestamps[-1]
            wait = self.delay - (time.time() - last)
            if wait > 0:
                await asyncio.sleep(wait)
    async def release(self):
        async with self._lock:
            self._active -= 1
watcher_lock = asyncio.Lock()

search_rate_limiter = SearchRateLimiter(
    max_per_minute=_cfg.get('search_rate_limit', 5),
    delay=_cfg.get('search_rate_delay', 2.0),
    max_concurrent=_cfg.get('search_max_concurrent', 1),
)

WATCHER_LOG_DIR = os.path.join(DATA_DIR, "security_audit")
os.makedirs(WATCHER_LOG_DIR, exist_ok=True)
WATCHER_SYSTEM_PROMPT = """You are a high-security command auditor.
Evaluate the command based on:
1. Privilege escalation attempts.
2. Destructive filesystem operations.
3. Network exfiltration.
4. Obfuscated shell syntax.

Response Format:
- If safe: 'Reasoning:[Brief explanation] P'
- If unsafe: 'Reasoning: [Detailed reason] F'
"""

async def security_watcher(cmd):
    payload = {
        "messages":[
            {"role": "system", "content": WATCHER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this command: {cmd}"}
        ],
        "temperature": 0.1,  # 0.1 is slightly safer than 0.0 for some local models
        "max_tokens": 2048,
        "reasoning_budget": 2048 # Give it enough room to <think> before outputting P or F!
    }
    try:
        async with watcher_lock:
            r = await asyncio.to_thread(
                requests.post, API_URL,
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload, timeout=60
            )
            r.raise_for_status()

            msg = r.json()['choices'][0]['message']
            # Fallback chain: try content, then reasoning_content, then default to empty string
            response_text = msg.get('content') or msg.get('reasoning_content') or ""

            if not response_text.strip():
                response_text = "Reasoning: Local API returned an empty string. F"

        with open(os.path.join(WATCHER_LOG_DIR, "audit_log.jsonl"), "a") as f:
            f.write(json.dumps({"timestamp": datetime.now().isoformat(), "command": cmd, "decision": response_text}) + "\n")
        return response_text
    except Exception as e:
        return f"Reasoning: Watcher Error ({str(e)}) F"

console = Console()
os.makedirs(CONF_DIR, exist_ok=True)
os.makedirs(THREAD_DIR, exist_ok=True)
os.makedirs(ROUTINE_DIR, exist_ok=True)

def gen_id(prefix="msg"): return f"{prefix}_{uuid.uuid4().hex[:6]}"

def sync_thread_file(filepath, msgs):
    if not filepath: return
    try:
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w') as f: json.dump(msgs, f)
        os.replace(temp_file, filepath)
    except: pass

def get_identity_prompt(interactive_on, memory_active, is_multimodal):
    os_info = subprocess.getoutput("grep PRETTY_NAME /etc/os-release | cut -d'=' -f2 | tr -d '\"'")
    shell_info = os.environ.get("SHELL", "Unknown Shell")
    admin = "Administrator" if "wheel" in subprocess.getoutput("groups") else "Standard User"

    return f"""
### CORE IDENTITY ###
You are 'ask', an advanced, agentic Linux CLI assistant for {os_info}.
Current Shell: {shell_info}
Multi-modal: {"ENABLED" if is_multimodal else "DISABLED"}
User Status: {admin}

### CONTEXT LIMITS & MUTATIONS ###
You run locally. To remain fast, use targeted MUTATIONS. Instead of outputting large rewritten scripts, use your tools to apply small, targeted changes. Use the 'set_state' tool to switch to 'planning' if you need deep thought, and 'execution' when you are ready to act.
"""

def prompt_user(prompt_text):
    if not sys.stdin.isatty():
        with open('/dev/tty', 'r') as tty:
            console.print(prompt_text, end="")
            return tty.readline().strip()
    return input(prompt_text)

async def async_prompt_user(prompt_text):
    return await asyncio.to_thread(prompt_user, prompt_text)

async def run_cmd(cmd, silent=False):
    console.print(f"[dim italic]🛡  Security Watcher analyzing: {cmd[:30]}...[/dim italic]")

    watch_result = await security_watcher(cmd)

    # Bulletproof parsing: strip EVERYTHING except letters, then check the very last letter
    alpha_chars = re.sub(r'[^a-zA-Z]', '', watch_result.upper())
    watcher_passed = alpha_chars.endswith('P') if alpha_chars else False

    human_passed = False

    async with ui_lock:
        if not silent:
            if AUTO_APPROVE and watcher_passed:
                console.print(f"[bold green]⚡ Auto-approved:[/bold green] [cyan]{cmd}[/cyan]")
                human_passed = True
            else:
                console.print(Panel(f"[cyan]{cmd}[/cyan]", title="Permission Required"))
                if AUTO_APPROVE and not watcher_passed:
                    console.print(f"[bold red]Watcher flagged this command! Reasoning:[/bold red]\n[dim]{watch_result}[/dim]")
                ans = await async_prompt_user("Run this command? (y/n): ")
                human_passed = ans.lower() == 'y'
        else:
            human_passed = True

        if human_passed != watcher_passed:
            if await async_prompt_user("Security mismatch. Proceed anyway? (y/n): ") != 'y':
                return "User aborted due to security mismatch."

    if not human_passed: return "User denied execution."

    try:
        if USE_SANDBOX:
            cmd = f"bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /home --tmpfs /root --tmpfs /tmp --unshare-all --die-with-parent -- sh -c '{cmd.replace(''''''', ''''\\''''')}'"

        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await process.communicate()
        output = stdout.decode('utf-8', errors='replace')
        if len(output) > MAX_RESULT_CHARS:
            console.print(f"[bold yellow]⚠️  Warning: Output truncated at {MAX_RESULT_CHARS} chars.[/bold yellow]")
            if not sys.stdin.isatty():
                return output[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
            ans = await async_prompt_user("Continue with truncated output? (y/n): ")
            if ans.lower() != 'y':
                return output[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
            return output[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
        else:
            return output
    except Exception as e:
        return f"Command failed: {str(e)}"

# --- NATIVE TOOLS SCHEMA ---
NATIVE_TOOLS = [
    {"type": "function", "function": {"name": "run", "description": "Execute a Linux command.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "search", "description": "Search DuckDuckGo.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read", "description": "Read webpage text.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "gc", "description": "Garbage collect old messages by ID.", "parameters": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}}, "required": ["ids"]}}},
    {"type": "function", "function": {"name": "set_state", "description": "Change compute state. Available states: 'triage' (Fast response mode), 'planning' (Deep reasoning mode), 'execution' (Tool execution mode), 'learning' (Failure analysis mode)", "parameters": {"type": "object", "properties": {"state": {"type": "string", "enum": ["triage", "planning", "execution", "learning"]}}, "required": ["state"]}}}
]

async def execute_tool_call(tc, internal_msgs):
    global current_state
    name = tc['function']['name']
    try:
        args = json.loads(tc['function']['arguments'])
    except:
        args = {}

    res = ""
    try:
        if name == 'run':
            res = await run_cmd(args.get('command', ''))
        elif name == "search":
            query = args.get('query', '')
            console.print(f"[blue]🔍 Searching:[/blue] {query}")

            # Rate limiter + retry logic
            max_retries = _cfg.get('search_retry_count', 3)
            base_delay = _cfg.get('search_retry_base_delay', 1.0)
            timeout = _cfg.get('search_timeout', 30)

            for attempt in range(1, max_retries + 1):
                try:
                    await search_rate_limiter.acquire()
                    try:
                        raw = await asyncio.to_thread(
                            subprocess.check_output,
                            ["ddgr", "--json", "-n", "3", query],
                            stderr=subprocess.STDOUT,
                            timeout=timeout
                        )
                        if raw.strip():
                            res = str(json.loads(raw))
                        else:
                            res = "Error: Search returned no results."
                        break
                    except subprocess.TimeoutExpired:
                        console.print(f"[yellow]Search timed out (attempt {attempt}/{max_retries})[/yellow]")
                        continue
                    except Exception as e:
                        console.print(f"[yellow]Search error (attempt {attempt}/{max_retries}): {e}[/yellow]")
                        if attempt < max_retries:
                            wait = base_delay * (2 ** (attempt - 1))
                            console.print(f"[dim]Retrying in {wait:.1f}s...[/dim]")
                            await asyncio.sleep(wait)
                        else:
                            res = f"Error: Search failed after {max_retries} attempts: {e}"
                finally:
                    await search_rate_limiter.release()
            else:
                res = "Error: Search failed after maximum retries."
        elif name == 'read':
            console.print(f"[blue]📖 Reading:[/blue] {args.get('url')}")
            raw = await asyncio.to_thread(
                subprocess.check_output,
                ["lynx", "-dump", "-nolist", "-display_charset=utf-8", args.get('url')],
                stderr=subprocess.STDOUT
            )
            res = raw.decode('utf-8', errors='replace')
            if len(res) > MAX_RESULT_CHARS:
                console.print(f"[bold yellow]⚠️  Warning: Read output truncated at {MAX_RESULT_CHARS} chars.[/bold yellow]")
                if not sys.stdin.isatty():
                    res = res[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
                else:
                    ans = await async_prompt_user("Continue with truncated output? (y/n): ")
                    if ans.lower() != 'y':
                        res = res[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
                    else:
                        res = res[:MAX_RESULT_CHARS] + "\n[TRUNCATED]"
            else:
                res = res
        elif name == 'set_state':
            new_state = args.get('state')
            if new_state in STATE_PROFILES:
                current_state = new_state
                res = f"SUCCESS: Compute state changed to {current_state}. Reason budget updated. ({STATE_PROFILES[current_state]['desc']})"
                console.print(f"[dim purple]🧠 State Shift -> {current_state.upper()}[/dim purple]")
            else:
                res = f"Invalid state: {new_state}"
        elif name == 'gc':
            count = 0
            for m in internal_msgs:
                if m.get('id') in args.get('ids', []): m['gc'], count = True, count + 1
            res = f"Garbage collected {count} messages."
            console.print(f"[dim]🧹 GC applied to {count} blocks.[/dim]")
        else:
            res = f"Unknown tool {name}"

    except subprocess.CalledProcessError as e:
        # Feed CLI errors directly back to the AI
        res = f"Tool Execution Failed (exit code {e.returncode}): {e.output.decode('utf-8', errors='replace') if e.output else 'Unknown error'}"
    except json.JSONDecodeError:
        res = "Tool Execution Failed: Search returned invalid JSON data. You might be rate-limited by DuckDuckGo."
    except Exception as e:
        res = f"Tool Execution Error: {str(e)}"

    return {"role": "tool", "tool_call_id": tc['id'], "name": name, "content": res}

def build_api_payload(internal_msgs):
    api_msgs = []
    for m in internal_msgs:
        if m.get("gc", False): continue
        msg = {"role": m["role"], "content": m.get("content", "")}
        if "tool_calls" in m: msg["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            msg["tool_call_id"] = m["tool_call_id"]
            msg["name"] = m["name"]
        api_msgs.append(msg)
    return api_msgs

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="*", help="Your question")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("-a", "--auto", action="store_true")
    parser.add_argument("-s", "--sandbox", action="store_true")
    parser.add_argument("-c", "--continue-session", dest="continue_session", nargs="?", const="LAST")
    args = parser.parse_args()

    global AUTO_APPROVE, USE_SANDBOX, current_state
    AUTO_APPROVE = args.auto
    USE_SANDBOX = args.sandbox

    user_query = " ".join(args.query).strip()
    if not sys.stdin.isatty():
        user_query += f"\n\n[PIPED DATA]:\n{sys.stdin.read().strip()}"

    # --- RESTORED SESSION LOADING LOGIC ---
    latest_file = None
    files = glob.glob(os.path.join(THREAD_DIR, "*.json"))

    if args.continue_session and args.continue_session not in ["LAST", "LIST"]:
        # User specified a specific session name
        matched = glob.glob(os.path.join(THREAD_DIR, f"*{args.continue_session}*.json"))
        if matched:
            latest_file = max(matched, key=os.path.getmtime)
        else:
            # Use the EXACT name provided by the user (no aggressive underscore replacement)
            latest_file = os.path.join(THREAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.continue_session}.json")

    elif args.continue_session == "LAST" and files:
        latest_file = max(files, key=os.path.getmtime)

    # Fallback: Brand new session (generate name from query)
    if not latest_file:
        safe_q = "".join([c if c.isalnum() else "_" for c in (user_query[:30] if user_query else "session")])
        if not safe_q: safe_q = "session"
        latest_file = os.path.join(THREAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_q}.json")

    internal_msgs = []
    if os.path.exists(latest_file):
        try:
            with open(latest_file, 'r') as f: internal_msgs = json.load(f)
        except: pass

    sys_prompt = get_identity_prompt(args.interactive, len(internal_msgs)>0, False)
    if not internal_msgs:
        internal_msgs.append({"id": "sys", "role": "system", "content": sys_prompt, "gc": False})

    if user_query:
        # If the user asks a completely new question, default to planning if it's long, else triage
        current_state = "planning" if len(user_query) > 100 else "triage"
        internal_msgs.append({"id": gen_id("usr"), "role": "user", "content": user_query, "gc": False})

    sync_thread_file(latest_file, internal_msgs)

    turn_count = 0
    max_turns = _cfg.get("max_turns", 10)  # Prevent infinite agent loops

    while True:
        turn_count += 1
        if turn_count > max_turns:
            console.print(f"[bold yellow]⚠️  Warning: Maximum autonomous tool loops ({max_turns}) reached.[/bold yellow]")
            if not sys.stdin.isatty():
                internal_msgs.append({"id": gen_id("sys"), "role": "tool", "content": "System prevented further autonomous execution to avoid infinite loops.", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                break
            ans = await async_prompt_user("Continue anyway? (y/n): ")
            if ans.lower() != 'y':
                internal_msgs.append({"id": gen_id("sys"), "role": "tool", "content": "System prevented further autonomous execution to avoid infinite loops.", "gc": False})
                sync_thread_file(latest_file, internal_msgs)
                break

        api_messages = build_api_payload(internal_msgs)
        profile = STATE_PROFILES[current_state]

        payload = {
            "messages": api_messages,
            "temperature": profile["temperature"],
            "max_tokens": profile["max_tokens"],
            "reasoning_budget": profile["reasoning_budget"]
        }
        if args.interactive:
            payload["tools"] = NATIVE_TOOLS
            payload["tool_choice"] = "auto"

        with Live(Spinner("dots", text=f"Thinking [{current_state.upper()}]...", style="cyan"), transient=True):
            try:
                # Async API Call
                r = await asyncio.to_thread(
                    requests.post, API_URL,
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json=payload, timeout=TIMEOUT
                )
                r.raise_for_status()
                response_msg = r.json()['choices'][0]['message']
            except Exception as e:
                console.print(f"[red]API Error:[/red] {e}")
                break

        # Append Assistant response
        ast_msg = {"id": gen_id("ast"), "role": "assistant", "content": response_msg.get('content') or "", "gc": False}
        if "tool_calls" in response_msg:
            ast_msg["tool_calls"] = response_msg["tool_calls"]
            # After deciding on tools, switch state to execution for the next turn
            current_state = "execution"

        internal_msgs.append(ast_msg)
        sync_thread_file(latest_file, internal_msgs)

        # Print reasoning/text if present
        if ast_msg["content"]:
            from rich.markdown import Markdown
            console.print(Markdown(ast_msg["content"]))

        # --- CONCURRENT NATIVE TOOL EXECUTION ---
        if "tool_calls" in response_msg:
            tasks = [execute_tool_call(tc, internal_msgs) for tc in response_msg["tool_calls"]]
            results = await asyncio.gather(*tasks)

            for res_msg in results:
                res_msg["id"] = gen_id("res")
                res_msg["gc"] = False
                internal_msgs.append(res_msg)

            sync_thread_file(latest_file, internal_msgs)
            continue # Loop back to LLM to evaluate tool results

        break # No tools called, conversation turn is done

if __name__ == "__main__":
    try:
        from rich.console import Console # Just in case it's not globally available at this scope
        asyncio.run(main())
    except KeyboardInterrupt:
        Console().print("\n[bold red]🛑 Operation aborted by user.[/bold red]")
        sys.exit(0)
