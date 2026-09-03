#!/usr/bin/env python3
# oobe.py
import os, json, sys
import requests
from pathlib import Path
from rich.console import Console
from assets.core import defaults

try:
    from cryptography.fernet import Fernet
except ImportError:
    print("[bold red]Error: cryptography package required.[/bold red]")
    print("Install: pip install cryptography")
    sys.exit(1)

import hashlib
import base64

console = Console()

def _fernet_key():
    return base64.urlsafe_b64encode(
        hashlib.sha256(os.uname().nodename.encode()).digest()
    )

def encrypt(v: str) -> str:
    return Fernet(_fernet_key()).encrypt(v.encode()).decode()

def try_endpoint(url: str) -> tuple[bool, dict | None]:
    base = url.removesuffix("/v1")
    # Probe common health and model endpoints
    for path in ["/v1/models", "/models", "/health", "/"]:
        try:
            r = requests.get(f"{base}{path}", timeout=2)
            if r.status_code in (200, 401, 403):
                try:
                    return True, r.json()
                except Exception:
                    return True, {"status": "online"}
        except Exception:
            pass
    return False, None

def setup() -> None:
    config_path = Path.home() / ".local" / "share" / "ask" / "config.json"
    existing_config = {}
    if config_path.exists():
        try:
            existing_config = json.loads(config_path.read_text())
        except Exception:
            pass

    console.print("\n[bold cyan]ask-cli: Provider & Router Setup Wizard[/bold cyan]")

    providers = existing_config.get("providers", {})
    active_provider = defaults.get(existing_config, "active_provider")

    # Auto-migrate legacy provider structures
    for p_name, p_data in providers.items():
        if "driver" not in p_data:
            if "llama" in p_name or p_data.get("type") == "router":
                p_data["driver"] = "llama-cpp"
            else:
                p_data["driver"] = "openai-compatible"

    if providers:
        console.print("\n[dim]Existing configured providers:[/dim]")
        for p, d in providers.items():
            is_active = " [bold cyan](ACTIVE)[/bold cyan]" if p == active_provider else ""
            console.print(f"  • {p} [{d.get('driver')}] → {d.get('api_base')}{is_active}")

    console.print("\n[bold]Select setup action:[/bold]")
    console.print("  [1] Auto-detect running local routers (Llama.cpp on 9931, FreeToken on 1900, Ollama on 11434)")
    console.print("  [2] Configure / Update Llama.cpp Router (llama-server)")
    console.print("  [3] Configure / Update FreeToken Daemon")
    console.print("  [4] Add generic OpenAI-compatible API (OpenRouter, DeepSeek, vLLM, etc.)")
    if len(providers) > 1:
        console.print("  [5] Switch active default provider")

    choice = input(f"\nEnter choice (1-{5 if len(providers) > 1 else 4}, default 1): ").strip() or "1"

    if choice == "1":
        probes = [
            ("llama-cpp", "llama-cpp", "http://localhost:9931/v1"),
            ("freetoken", "freetoken-router", "http://localhost:8000/v1"),
            ("ollama-local", "openai-compatible", "http://localhost:11434/v1"),
        ]
        found = False
        for pname, driver, base in probes:
            ok, data = try_endpoint(base)
            if ok:
                found = True
                console.print(f"[bold green]✓ Found running {driver} at {base}[/bold green]")
                providers[pname] = {
                    "driver": driver,
                    "api_base": base,
                    "api_key": ""
                }
                if not active_provider:
                    active_provider = pname

        if not found:
            console.print("[bold yellow]⚠ No running routers detected. Creating default llama-cpp profile.[/bold yellow]")
            models_dir = input("Path to models directory (e.g. ~/models): ").strip() or "~/models"
            providers["llama-cpp"] = {
                "driver": "llama-cpp",
                "api_base": "http://localhost:9931/v1",
                "api_key": "",
                "server_path": "llama-server",
                "models_dir": models_dir,
                "port": 9931
            }
            active_provider = "llama-cpp"

    elif choice == "2":
        pname = input("Provider name (default 'llama-cpp'): ").strip() or "llama-cpp"
        api_base = input("API Base (default http://localhost:9931/v1): ").strip() or "http://localhost:9931/v1"
        models_dir = input("Path to models directory (e.g. ~/models): ").strip() or "~/models"
        server_path = input("Path to llama-server binary (default 'llama-server'): ").strip() or "llama-server"

        providers[pname] = {
            "driver": "llama-cpp",
            "api_base": api_base,
            "api_key": "",
            "server_path": server_path,
            "models_dir": models_dir,
            "port": 9931
        }
        active_provider = pname

    elif choice == "3":
        pname = input("Provider name (default 'freetoken'): ").strip() or "freetoken"
        api_base = input("Inference API Base (default http://localhost:8000/v1): ").strip() or "http://localhost:8000/v1"
        control_base = input("Daemon Control URL (default http://localhost:1900): ").strip() or "http://localhost:1900"
        models_dir = input("Path to models directory (e.g. ~/models): ").strip() or "~/models"
        cmd = input("Daemon start command (default 'ft daemon'): ").strip() or "ft daemon"

        providers[pname] = {
            "driver": "freetoken-router",
            "api_base": api_base,
            "control_base": control_base,
            "api_key": "",
            "models_dir": models_dir,
            "command": cmd
        }
        active_provider = pname

    elif choice == "4":
        pname = input("Provider name (e.g. 'openrouter'): ").strip()
        api_base = input("API Base URL (e.g. https://openrouter.ai/api/v1): ").strip()
        api_key = input("API Key (leave blank if none): ").strip()
        model = input("Default model name: ").strip()

        providers[pname] = {
            "driver": "openai-compatible",
            "api_base": api_base,
            "api_key": encrypt(api_key) if api_key else "",
            "default_model": model,
            "max_tokens": 32768
        }
        active_provider = pname

    elif choice == "5" and len(providers) > 1:
        console.print("\nSelect default active provider:")
        plist = list(providers.keys())
        for idx, p in enumerate(plist):
            console.print(f"  [{idx + 1}] {p}")
        sel = input(f"Choice (1-{len(plist)}): ").strip()
        try:
            active_provider = plist[int(sel) - 1]
        except Exception:
            pass

    config = {
        "providers": providers,
        "active_provider": active_provider or list(providers.keys())[0],
        "timeout": defaults.get(existing_config, "timeout"),
        "max_turns": defaults.get(existing_config, "max_turns"),
        "max_result_chars": defaults.DEFAULTS["max_result_chars"],
        "auto_approve_default": defaults.DEFAULTS["auto_approve_default"],
        "use_sandbox_default": defaults.DEFAULTS["use_sandbox_default"],
        "search_rate_limit": defaults.DEFAULTS["search_rate_limit"],
        "search_rate_delay": defaults.DEFAULTS["search_rate_delay"],
        "search_max_concurrent": defaults.DEFAULTS["search_max_concurrent"],
        "search_retry_count": defaults.DEFAULTS["search_retry_count"],
        "search_retry_base_delay": defaults.DEFAULTS["search_retry_base_delay"],
        "search_timeout": defaults.DEFAULTS["search_timeout"],
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))
    console.print(f"\n[bold green]✓ Configuration saved to {config_path}[/bold green]")
    console.print(f"[bold cyan]Active Provider: {config['active_provider']}[/bold cyan]")

if __name__ == "__main__":
    setup()
