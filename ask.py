#!/usr/bin/env python3
import os, sys, json, argparse, glob, asyncio, requests, subprocess, pkgutil, importlib, uuid
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.markdown import Markdown

# Initialize Architecture
from assets.context import AskContext
from assets.agent import Agent
from assets.core.registry import TOOL_REGISTRY, EVAL_REGISTRY, API_REGISTRY

def _load_api_modules():
    """Auto-discover and import all API provider drivers from assets/apis/"""
    if path := os.environ.get('ASK_ASSETS_DIR'):
        apis_dir = Path(path) / "apis"
    else:
        apis_dir = Path(__file__).parent / "assets" / "apis"
        if not apis_dir.is_dir():
            apis_dir = Path(__file__).parent.parent / "share" / "ask" / "assets" / "apis"

    if not apis_dir.is_dir():
        return

    for _, module_name, _ in pkgutil.walk_packages([str(apis_dir)], prefix="assets.apis."):
        try:
            importlib.import_module(module_name)
        except Exception:
            pass

def _load_tool_modules():
    """Auto-discover and import all tool modules from assets/tools/"""
    # 1. Respect the Nix wrapper's environment variable first
    if path := os.environ.get('ASK_ASSETS_DIR'):
        tools_dir = Path(path) / "tools"
    else:
        # 2. Local development fallback
        tools_dir = Path(__file__).parent / "assets" / "tools"
        if not tools_dir.is_dir():
            # 3. Standard Nix store fallback if env var is missing
            tools_dir = Path(__file__).parent.parent / "share" / "ask" / "assets" / "tools"

    if not tools_dir.is_dir():
        console = Console()
        console.print("[dim]⚠ Tools directory not found. Auto-discovery skipped.[/dim]")
        return

    for _, module_name, _ in pkgutil.iter_modules([str(tools_dir)]):
        module_full = f"assets.tools.{module_name}"
        try:
            importlib.import_module(module_full)
        except Exception as e:
            console = Console()
            console.print(f"[dim]⚠ Failed to load tool {module_name}: {e}[/dim]")

def _load_evaluator_modules():
    """Auto-discover and import all evaluator modules from assets/evaluators/"""
    if path := os.environ.get('ASK_ASSETS_DIR'):
        eval_dir = Path(path) / "evaluators"
    else:
        eval_dir = Path(__file__).parent / "assets" / "evaluators"
        if not eval_dir.is_dir():
            eval_dir = Path(__file__).parent.parent / "share" / "ask" / "assets" / "evaluators"

    if not eval_dir.is_dir():
        return

    for _, module_name, _ in pkgutil.iter_modules([str(eval_dir)]):
        module_full = f"assets.evaluators.{module_name}"
        try:
            importlib.import_module(module_full)
        except Exception as e:
            console = Console()
            console.print(f"[dim]⚠ Failed to load evaluator {module_name}: {e}[/dim]")

def _load_hook_modules():
    """Auto-discover and import all hook modules from assets/hooks/"""
    if path := os.environ.get('ASK_ASSETS_DIR'):
        hook_dir = Path(path) / "hooks"
    else:
        hook_dir = Path(__file__).parent / "assets" / "hooks"
        if not hook_dir.is_dir():
            hook_dir = Path(__file__).parent.parent / "share" / "ask" / "assets" / "hooks"

    if not hook_dir.is_dir():
        return

    for _, module_name, _ in pkgutil.iter_modules([str(hook_dir)]):
        module_full = f"assets.hooks.{module_name}"
        try:
            importlib.import_module(module_full)
        except Exception as e:
            console = Console()
            console.print(f"[dim]⚠ Failed to load hook {module_name}: {e}[/dim]")

# Initialize all plugins
_load_api_modules()
_load_tool_modules()
_load_evaluator_modules()
_load_hook_modules()

console = Console()

def _resolve_assets_dir():
    """Standardized path resolver matching _load_tool_modules() fallbacks."""
    if path := os.environ.get('ASK_ASSETS_DIR'):
        return Path(path)
    dev_path = Path(__file__).parent / "assets"
    nix_path = Path(__file__).parent.parent / "share" / "ask"
    return dev_path if dev_path.exists() else nix_path

def _load_raw_config():
    config_path = Path.home() / ".local" / "share" / "ask" / "config.json"
    if not config_path.exists():
        assets_dir = _resolve_assets_dir()
        config_path = assets_dir / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

async def _handle_provider_lazy_ops(argv):
    """Handles:
      ask -ap / ask --api-provider
      ask -ap -start / ask -ap -stop
      ask -ap <provider> -start / -stop / -load / -unload
    """
    cfg = _load_raw_config()
    providers = cfg.get("providers", {})
    active = cfg.get("active_provider", "")

    # Helper to instantiate driver for a provider dict
    def make_driver(pname):
        from assets.apis import get_api_driver
        pcfg = {**providers.get(pname, {}), "provider_name": pname}
        driver_type = pcfg.get("driver") or ("llama-cpp" if "llama" in pname or pcfg.get("type") == "router" else "openai-compatible")
        return get_api_driver(driver_type, pcfg)

    # 1. ask -ap / ask --api-provider (no specific provider argument given)
    ap_idx = -1
    for idx, a in enumerate(argv):
        if a in ("-ap", "--api-provider"):
            ap_idx = idx
            break

    if ap_idx == -1:
        return False

    next_arg = argv[ap_idx + 1] if ap_idx + 1 < len(argv) else None

    # Case A: `ask -ap` or `ask -ap -start` / `ask -ap -stop`
    if next_arg is None or next_arg.startswith("-"):
        sub_flag = next_arg

        if sub_flag in ("-start", "--start"):
            console.print("\n[bold cyan]⚡ Start a Provider Daemon:[/bold cyan]")
            stopped = []
            for p in providers:
                d = make_driver(p)
                if not await d.is_running():
                    stopped.append(p)
            if not stopped:
                console.print("  [dim]All configured provider daemons are running or static.[/dim]")
            else:
                for p in stopped:
                    console.print(f"  • {p} → [dim]Run:[/dim] ask -ap {p} -start")
            return True

        if sub_flag in ("-stop", "--stop"):
            console.print("\n[bold cyan]🛑 Stop a Provider Daemon:[/bold cyan]")
            running = []
            for p in providers:
                d = make_driver(p)
                if await d.is_running():
                    running.append(p)
            if not running:
                console.print("  [dim]No local router daemons currently running.[/dim]")
            else:
                for p in running:
                    console.print(f"  • {p} → [dim]Run:[/dim] ask -ap {p} -stop")
            return True

        # Plain `ask -ap` -> List all providers with status
        console.print("\n[bold cyan]📋 Configured API Providers & Routers:[/bold cyan]")
        if not providers:
            console.print("  (No providers configured. Run 'oobe' or edit ~/.local/share/ask/config.json)")
            return True

        for p_name, p_data in providers.items():
            driver_name = p_data.get("driver") or ("llama-cpp" if "llama" in p_name or p_data.get("type") == "router" else "openai-compatible")
            driver = make_driver(p_name)
            is_up = await driver.is_running()
            status_badge = "[bold green]ONLINE[/bold green]" if is_up else "[dim red]STOPPED[/dim red]"
            active_badge = " [bold cyan](ACTIVE)[/bold cyan]" if p_name == active else ""

            console.print(f"  • [bold]{p_name}[/bold] \\[{driver_name}\\] {status_badge}{active_badge}")
            console.print(f"    [dim]Endpoint:[/dim] {p_data.get('api_base', 'N/A')}")
            if is_up:
                loaded = await driver.list_loaded_models()
                if loaded:
                    console.print(f"    [dim]Loaded Models:[/dim] {', '.join(loaded)}")

        console.print("\n[dim]Provider Options:[/dim]")
        console.print("  ask -ap <provider> -start               Start router daemon")
        console.print("  ask -ap <provider> -stop                Stop router daemon")
        console.print("  ask -ap <provider> -load [model]        List or load available model")
        console.print("  ask -ap <provider> -unload [model]      List or unload running model")
        console.print("  ask -ap <provider> -info [model]        Inspect model configuration & context")
        console.print("  ask -ap <provider> -set <model> <k=v>   Set model preset & hot-reload in memory")
        console.print("  ask -ap <provider> -reload              Trigger hot-reload of presets")
        console.print("  ask -ap <provider> -presets             List saved preset templates")
        console.print("  ask -ap <provider> -save <name> <k=v>   Save reusable preset template")
        console.print("  ask -ap <provider> \"Your query\"         Run agent using provider")
        return True

    # Case B: A provider name was specified: `ask -ap <provider>`
    p_name = next_arg
    if p_name not in providers:
        console.print(f"[bold red]Provider '{p_name}' not found in configuration.[/bold red]")
        console.print(f"Available providers: {', '.join(providers.keys())}")
        return True

    sub_args = argv[ap_idx + 2:]
    driver = make_driver(p_name)

    # Check for subcommands
    if not sub_args:
        # Just `ask -ap <p_name>` without query or subcommands: show detail & options
        is_up = await driver.is_running()
        status_badge = "[bold green]ONLINE[/bold green]" if is_up else "[dim red]STOPPED[/dim red]"
        console.print(f"\n[bold cyan]Provider:[/bold cyan] {p_name} ({status_badge})")
        console.print(f"[dim]Driver:[/dim] {providers[p_name].get('driver')}")
        console.print(f"[dim]Endpoint:[/dim] {providers[p_name].get('api_base')}")

        avail = await driver.list_available_models()
        if avail:
            console.print(f"[dim]Available Models:[/dim] {', '.join(avail)}")
        loaded = await driver.list_loaded_models()
        if loaded:
            console.print(f"[dim]Loaded Models:[/dim] {', '.join(loaded)}")
        return True

    cmd = sub_args[0]
    if cmd in ("-start", "--start"):
        console.print(f"[cyan]Starting daemon for '{p_name}'...[/cyan]")
        ok, msg = await driver.start_daemon()
        console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
        return True

    elif cmd in ("-stop", "--stop"):
        console.print(f"[cyan]Stopping daemon for '{p_name}'...[/cyan]")
        ok, msg = await driver.stop_daemon()
        console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
        return True

    elif cmd in ("-load", "--load"):
        target_model = sub_args[1] if len(sub_args) > 1 and not sub_args[1].startswith("-") else None
        if not await driver.is_running():
            console.print(f"[bold yellow]Provider '{p_name}' is currently STOPPED.[/bold yellow]")
            console.print(f"Start it with: ask -ap {p_name} -start")
            return True

        avail = await driver.list_available_models()
        if not target_model:
            console.print(f"\n[bold cyan]Available live models on '{p_name}':[/bold cyan]")
            if avail:
                for idx, m in enumerate(avail):
                    console.print(f"  [{idx + 1}] {m}")
                console.print(f"\n[dim]Load by number or name:[/dim] ask -ap {p_name} -load <# or name>")
            else:
                console.print("  (No models currently reported by the live router)")
            return True
        else:
            # Resolve numeric selection
            if target_model.isdigit() and avail:
                idx = int(target_model) - 1
                if 0 <= idx < len(avail):
                    target_model = avail[idx]

            console.print(f"[cyan]Loading '{target_model}' on '{p_name}'...[/cyan]")
            ok, msg = await driver.load_model(target_model)
            console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
            return True

    elif cmd in ("-unload", "--unload"):
        target_model = sub_args[1] if len(sub_args) > 1 and not sub_args[1].startswith("-") else None
        if not await driver.is_running():
            console.print(f"[bold yellow]Provider '{p_name}' is currently STOPPED.[/bold yellow]")
            return True

        loaded = await driver.list_loaded_models()
        if not target_model:
            console.print(f"\n[bold cyan]Loaded running models on '{p_name}':[/bold cyan]")
            if loaded:
                for idx, m in enumerate(loaded):
                    console.print(f"  [{idx + 1}] {m}")
                console.print(f"\n[dim]Unload by number or name:[/dim] ask -ap {p_name} -unload <# or name>")
            else:
                console.print("  (No models currently loaded in memory)")
            return True
        else:
            # Resolve numeric selection
            if target_model.isdigit() and loaded:
                idx = int(target_model) - 1
                if 0 <= idx < len(loaded):
                    target_model = loaded[idx]

            console.print(f"[cyan]Unloading '{target_model}' from '{p_name}'...[/cyan]")
            ok, msg = await driver.unload_model(target_model)
            console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
            return True

    elif cmd in ("-info", "--info"):
        target_model = sub_args[1] if len(sub_args) > 1 and not sub_args[1].startswith("-") else ""
        avail = await driver.list_available_models()
        if target_model.isdigit() and avail:
            idx = int(target_model) - 1
            if 0 <= idx < len(avail):
                target_model = avail[idx]

        info = await driver.get_model_info(target_model)
        console.print(f"\n[bold cyan]📊 Provider / Model Info: {p_name}[/bold cyan]")
        if "global_preset" in info and info["global_preset"]:
            console.print(f"[dim]Global Defaults [*]:[/dim] {info['global_preset']}")

        models_info = info.get("models", {})
        if not models_info:
            console.print(f"  [dim]No live model telemetry available. (Daemon: {'ONLINE' if info.get('is_running') else 'STOPPED'})[/dim]")
        for m, mdata in models_info.items():
            status_str = "[bold green]🟢 LOADED[/bold green]" if mdata.get("loaded") else "[dim]⏸ UNLOADED[/dim]"
            console.print(f"\n• [bold]{m}[/bold] ({status_str})")
            if "n_ctx" in mdata:
                console.print(f"  - Allocated Context: [bold cyan]{mdata['n_ctx']:,}[/bold cyan] tokens (n_ctx)")
            if "n_ctx_train" in mdata:
                console.print(f"  - Native Max Context: [dim]{mdata['n_ctx_train']:,}[/dim] tokens (n_ctx_train)")
            if "params" in mdata and mdata["params"]:
                p_items = [f"{k}={v}" for k, v in list(mdata["params"].items())[:6]]
                console.print(f"  - Parameters: [dim]{', '.join(p_items)}[/dim]")
            if "preset" in mdata and mdata["preset"]:
                console.print(f"  - Saved Preset: [yellow]{mdata['preset']}[/yellow]")
        return True

    elif cmd in ("-reload", "--reload"):
        console.print(f"[cyan]Reloading router presets for '{p_name}'...[/cyan]")
        ok, msg = await driver.reload_router()
        console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
        return True

    elif cmd in ("-presets", "--presets"):
        presets = await driver.list_presets()
        console.print(f"\n[bold cyan]📋 Reusable Presets for '{p_name}':[/bold cyan]")
        if not presets:
            console.print("  (No templates saved. Save one with: ask -ap <p> -save <name> <k=v ...>)")
        for name, p_data in presets.items():
            console.print(f"  • [bold]@{name}[/bold] → [dim]{p_data}[/dim]")
        return True

    elif cmd in ("-save", "--save"):
        if len(sub_args) < 3:
            console.print("[bold red]Usage:[/bold red] ask -ap <provider> -save <template_name> <key=value ...>")
            return True
        tpl_name = sub_args[1].removeprefix("@")
        pairs = {p.split("=")[0]: p.split("=")[1] for p in sub_args[2:] if "=" in p}
        ok, msg = await driver.save_preset(tpl_name, pairs)
        console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
        return True

    elif cmd in ("-set", "--set"):
        if len(sub_args) < 2:
            console.print("[bold red]Usage:[/bold red] ask -ap <provider> -set [model] <key=value ... or @template>")
            return True

        first_arg = sub_args[1]
        avail = await driver.list_available_models()

        if "=" in first_arg or first_arg.startswith("@"):
            target_model = "*"
            raw_pairs = sub_args[1:]
        else:
            target_model = first_arg
            if target_model.isdigit() and avail:
                idx = int(target_model) - 1
                if 0 <= idx < len(avail):
                    target_model = avail[idx]
            raw_pairs = sub_args[2:]

        settings = {}
        for p in raw_pairs:
            if "=" in p:
                k, v = p.split("=", 1)
                settings[k] = v
            elif p.startswith("@"):
                settings["@"] = p.removeprefix("@")

        if not settings:
            console.print("[bold red]Error: No key=value settings or @template provided.[/bold red]")
            return True

        console.print(f"[cyan]Applying preset for '{target_model}' on '{p_name}'...[/cyan]")
        ok, msg = await driver.set_model_config(target_model, settings)
        console.print(f"[{'bold green' if ok else 'bold red'}]{msg}[/]")
        return True

    return False

def _lazy_arg_check(argv):
    """Intercept flags missing their values to restore old "lazy arg" behavior."""
    assets_dir = _resolve_assets_dir()

    def show_evals():
        console.print("\n[bold cyan]📋 Available Evaluators:[/bold cyan]")
        if EVAL_REGISTRY:
            for name in sorted(EVAL_REGISTRY.keys()): console.print(f"  • {name}")
        else: console.print("  (No evaluators registered)")

    def show_routines():
        console.print("\n[bold cyan]📋 Available Routines:[/bold cyan]")
        routines_dir = Path.home() / ".local" / "share" / "ask" / "routines"
        if routines_dir.exists():
            for f in sorted(routines_dir.glob("*.md")): console.print(f"  • {f.stem}")
        else: console.print("  (Directory not found or no routines yet)")

    def show_agents():
        console.print("\n[bold cyan]📋 Available Agents:[/bold cyan]")
        agents_path = assets_dir / "agents"
        if agents_path.exists():
            for f in sorted(agents_path.glob("*.json")): console.print(f"  • {f.stem}")
        else: console.print("  (Directory not found)")

    def print_eval_help(name):
        if name not in EVAL_REGISTRY:
            console.print(f"[bold red]Evaluator '{name}' not found.[/bold red]")
            return
        info = EVAL_REGISTRY[name]
        console.print(f"\n[bold cyan]Evaluator: {name}[/bold cyan]")
        console.print(f"[dim]Description:[/dim] {info.get('description', 'No description')}")
        if info.get("help_text"):
            console.print(f"[dim]Help:[/dim] {info['help_text']}")
        if info.get("usage"):
            console.print(f"[dim]Usage:[/dim] {info['usage'].rstrip()}")
        else:
            console.print(f"[dim]Usage:[/dim] ask -e {name} <input_data>")

    for i, arg in enumerate(argv):
        if arg in ("-e", "--evaluator"):
            if i + 1 < len(argv) and not argv[i+1].startswith("-"):
                val = argv[i+1]
                # Catch: ask -e <eval_name> --help
                if i + 2 < len(argv) and argv[i+2] == "--help":
                    print_eval_help(val)
                    return True
                # Valid value provided, let argparse handle it
                continue
            else:
                # Missing value: ask -e --help  OR  ask -e
                show_evals()
                return True
        elif arg in ("-r", "--routine"):
            if i + 1 < len(argv) and not argv[i+1].startswith("-"):
                continue
            else:
                show_routines()
                return True
        elif arg in ("-a", "--agent"):
            if i + 1 < len(argv) and not argv[i+1].startswith("-"):
                continue
            else:
                show_agents()
                return True

    return False

def gen_id(prefix="msg"): return f"{prefix}_{uuid.uuid4().hex[:6]}"

def sync_thread_file(filepath, msgs):
    if not filepath: return
    try:
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w') as f: json.dump(msgs, f)
        os.replace(temp_file, filepath)
    except: pass

async def main():
    # Handle provider lazy ops (-ap, -start, -stop, -load, -unload)
    if await _handle_provider_lazy_ops(sys.argv[1:]):
        sys.exit(0)

    if _lazy_arg_check(sys.argv[1:]):
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Agent State Kit CLI")
    parser.add_argument("query", nargs="*", help="Your question or evaluator input")
    parser.add_argument("-i", "--interactive", action="store_true", help="Enable tools")
    parser.add_argument("--auto", action="store_true", help="Auto-approve evaluated commands")
    parser.add_argument("-c", "--continue-session", nargs="?", const="LAST", help="Continue session")
    parser.add_argument("-a", "--agent", type=str, default="ask", help="Agent to call")
    parser.add_argument("-ap", "--api-provider", type=str, help="API / Router provider to use")
    parser.add_argument("-e", "--evaluator", type=str, help="Evaluator to run")
    parser.add_argument("-r", "--routine", type=str, help="Routine to load")
    parser.add_argument("-s", "--sandbox", action="store_true", help="Run in bwrap sandbox")
    parser.add_argument("--oobe", action="store_true", help="Run first-run setup wizard")
    args = parser.parse_args()

    # ── Explicit or first-run OOBE execution ──
    config_path = Path.home() / ".local" / "share" / "ask" / "config.json"

    if args.oobe or not config_path.exists():
        if not config_path.exists():
            console.print("[bold yellow]No configuration found. Starting first-run setup...[/bold yellow]")

        oobe_bin = Path(__file__).parent / "oobe"
        if oobe_bin.exists():
            subprocess.run([str(oobe_bin)])
        else:
            subprocess.run([sys.executable, str(Path(__file__).parent / "oobe.py")])
        sys.exit(0)

    # --- Guard: no query + piped input → show help and exit ---
    if not args.query and sys.stdin.isatty():
        parser.print_help()
        sys.exit(0)

    # --- RESTORE PIPED STDIN ---
    user_query = " ".join(args.query).strip()
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()
        if piped_data:
            user_query += f"\n\n[PIPED DATA]:\n{piped_data}"

    ctx = AskContext(args)
    agent = Agent(ctx, agent_name=args.agent)

    # --- Session Loading ---
    latest_file = None
    if args.continue_session:
        files = glob.glob(str(ctx.threads_dir / "*.json"))
        if args.continue_session != "LAST":
            # Strict match to prevent grabbing other sessions with overlapping names
            matched = [f for f in files if f.endswith(f"_{args.continue_session}.json")]
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
                        # Restore dynamic states from session
                        if "dynamic_states" in loaded:
                            agent.dynamic_states = loaded["dynamic_states"]
                        # Prevent agents from inheriting invalid states from cross-loaded sessions
                        if loaded["state"] in agent.states or loaded["state"] in agent.dynamic_states or loaded["state"] == "none":
                            agent.state_name = loaded["state"]
                        else:
                            console.print(f"[bold yellow]Warning: State '{loaded['state']}' is invalid for agent '{agent.name}'. Resetting state.[/bold yellow]")
                            agent.state_name = "none"
                    # Load the saved model for this session
                    if "model" in loaded:
                        ctx.config["model"] = loaded["model"]
                    if "tokens" in loaded:
                        ctx.current_tokens = loaded["tokens"]
                    internal_msgs = loaded.get("messages", [])
        except: pass

    if not internal_msgs:
        identity = f"Agent Name: {agent.name}\nAgent Purpose: {agent.profile.get('description', '')}"
        internal_msgs.append({"id": "sys", "role": "system", "content": identity.replace("  ", " ").strip(), "gc": False})

    if user_query:
        # NOTE: Removed automatic state setting! Let the AI manage it.
        internal_msgs.append({"id": gen_id("usr"), "role": "user", "content": user_query, "gc": False})

    # Resolve provider and model (detects hot loaded models or guides selection)
    await ctx.resolve_provider_and_model(has_explicit_provider=bool(args.api_provider))

    # Now that we have a guaranteed model, fetch its true context size
    await ctx.init_context_limit()

    # Direct Evaluator Invocation
    if args.evaluator:
        from assets.core.eval_runner import dispatch_evaluator
        console.print(f"\n[bold cyan]⚡ Running Evaluator:[/bold cyan] {args.evaluator}")

        # Resolve the evaluator's expected argument schema
        ev_config = EVAL_REGISTRY[args.evaluator]
        expected_args = ev_config.get("expected_args", {})

        # NOTE: Evaluators MUST declare expected_args in their decorator.
        # Single-arg: all CLI tokens join as that arg.
        # Multi-arg: one token per arg, left-to-right.
        # Map args.query to expected_args keys in order.
        query_parts = args.query
        input_data = {}

        arg_keys = list(expected_args.keys())
        if len(arg_keys) == 1:
            input_data[arg_keys[0]] = " ".join(query_parts)
        else:
            for i, key in enumerate(arg_keys):
                input_data[key] = query_parts[i] if i < len(query_parts) else ""

        with Live(Spinner("dots", text=f"Evaluating...", style="cyan"), transient=True):
            result = await dispatch_evaluator(ctx, args.evaluator, input_data, agent, internal_msgs)

        color = "green" if result.passed else "red"
        console.print(f"[bold {color}]Status:[/bold {color}] {result.status}")
        if result.value is not None:
            console.print(f"[{color}]Value:[/{color}] {result.value}")
        console.print(f"[{color}]Reasoning:[/{color}] {result.reasoning}")
        sys.exit(0 if result.passed else 1)

    with open(latest_file, 'w') as f:
        # Save the model to the thread state
        json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "tokens": ctx.current_tokens, "messages": internal_msgs, "dynamic_states": agent.dynamic_states}, f)

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

        # Proactively measure tokens before building the system prompt
        if ctx.config.get("model"):
            await ctx.measure_tokens(internal_msgs)

        fresh_ctx = await agent._resolve_context()

        # Pass internal_msgs directly — agent handles ID injection inline
        payload = await agent.get_api_payload(internal_msgs, fresh_ctx, interactive=args.interactive)

        # Inject the active session model into the payload
        if ctx.config.get("model"):
            payload["model"] = ctx.config["model"]

        with Live(Spinner("dots", text=f"Thinking [{agent.state_name.upper()}]...", style="cyan"), transient=True) as live:
            # --- API EXECUTION WITH RETRY ON WARMUP ---
            max_retries = 30
            retry_count = 0
            response_msg = None

            while retry_count < max_retries:
                try:
                    r = await asyncio.to_thread(
                        requests.post, f"{ctx.config['api_base']}/chat/completions",
                        headers={"Authorization": f"Bearer {ctx.config['api_key']}"},
                        json=payload, timeout=ctx.config['timeout']
                    )

                    # If model is still loading weights into VRAM, wait and retry
                    if r.status_code == 503 and "still loading" in r.text.lower():
                        retry_count += 1
                        live.update(Spinner("dots", text=f"Model is loading weights into GPU ({retry_count * 2}s)...", style="yellow"))
                        await asyncio.sleep(2)
                        continue

                    # If model failed or requires restart, don't loop endlessly
                    if r.status_code == 503 and "maintenance failed" in r.text.lower():
                        console.print(f"\n[bold red]API Error:[/bold red] Engine failed to start ({r.text.strip()}).")
                        break

                    r.raise_for_status()
                    response_data = r.json()
                    response_msg = response_data['choices'][0]['message']

                    if "usage" in response_data:
                        ctx.current_tokens = response_data["usage"].get("total_tokens", ctx.current_tokens)
                    break

                except requests.exceptions.RequestException as e:
                    if getattr(e, 'response', None) is not None and e.response.status_code == 503 and "still loading" in e.response.text.lower():
                        retry_count += 1
                        live.update(Spinner("dots", text=f"Model is loading weights into GPU ({retry_count * 2}s)...", style="yellow"))
                        await asyncio.sleep(2)
                        continue

                    err_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        try: err_msg += f"\nDetails: {e.response.json()}"
                        except: err_msg += f"\nDetails: {e.response.text}"
                    console.print(f"\n[bold red]API Error:[/bold red] {err_msg}")
                    break

            if not response_msg:
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
                json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "tokens": ctx.current_tokens, "messages": internal_msgs, "dynamic_states": agent.dynamic_states}, f)

            console.print("[bold green]✅ Tools completed.[/bold green]\n")
            continue

        # 4. IF NO TOOLS, SAVE FINAL STATE AND BREAK
        with open(latest_file, 'w') as f:
            json.dump({"state": agent.state_name, "model": ctx.config.get("model"), "tokens": ctx.current_tokens, "messages": internal_msgs, "dynamic_states": agent.dynamic_states}, f)
        break

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold red]Operation aborted by user.[/bold red]")
        import os
        os._exit(0) # Forces immediate termination of hanging background threads
