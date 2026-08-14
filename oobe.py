#!/usr/bin/env python3
"""Minimal OOBE setup for ask-cli. Run once to configure LLM provider.

Dependencies: pip install cryptography
Usage: python oobe.py
"""

import os, json, sys
import requests
from pathlib import Path
from rich.console import Console

try:
    from cryptography.fernet import Fernet
except ImportError:
    print("[bold red]Error: cryptography package required.[/bold red]")
    print("Install: pip install cryptography")
    sys.exit(1)

import hashlib
import base64

console = Console()

# ── Encryption helpers ──────────────────────────────────────────────────
def _fernet_key():
    """Derive a Fernet key from hostname (stable per machine, no extra files)."""
    return base64.urlsafe_b64encode(
        hashlib.sha256(os.uname().nodename.encode()).digest()
    )

def encrypt(v: str) -> str:
    """Encrypt a value (e.g. API key) using Fernet."""
    return Fernet(_fernet_key()).encrypt(v.encode()).decode()


# ── Core logic ──────────────────────────────────────────────────────────

def try_router(host: str = "localhost", port: int = 9931) -> tuple[bool, dict | None]:
    """Probe for a running Llama.cpp router at the given host:port.

    Returns (found, models_data) where models_data is the parsed JSON
    if the endpoint responded with status 200.
    """
    try:
        r = requests.get(f"http://{host}:{port}/v1/models", timeout=2)
        if r.status_code == 200:
            return True, r.json()
    except Exception:
        pass
    return False, None


def setup() -> None:
    """Interactive first-run configuration wizard."""
    # Write to user directory to avoid Nix Store immutability conflicts
    config_path = Path.home() / ".local" / "share" / "ask" / "config.json"

    # Already configured?
    if config_path.exists():
        console.print("[dim]Config already exists at:[/dim]")
        console.print(f"[cyan]{config_path}[/cyan]")
        console.print("[dim]Run again to reconfigure (or delete the file).[/dim]")
        return

    console.print("\n[bold cyan]ask-cli first-run setup[/bold cyan]")

    # ── 1. Auto-detect running router ──────────────────────────────────
    console.print("\n[bold yellow]Checking for running Llama.cpp router...[/bold yellow]")
    ok, models = try_router()

    api_base = ""
    api_key = ""

    extra_provider_config = {}

    if ok:
        console.print(f"[bold green]✓ Found router at http://localhost:9931[/bold green]")

        model_list = models.get("data", [])
        console.print(f"[dim]Available models ({len(model_list)}):[/dim]")
        for m in model_list:
            status = "loaded"
            if "status" in m and isinstance(m["status"], dict):
                status = m["status"].get("value", "loaded")

            model_id = m.get("id", "unknown-model")
            icon = "✅" if status == "loaded" else "⏸"
            console.print(f"  {icon} {model_id} ({status})")

        api_base = "http://localhost:9931/v1"
        api_key = ""
    else:
        console.print("[bold yellow]⚠ No router found at http://localhost:9931[/bold yellow]")

        ans = input("Would you like to configure auto-start for a local llama-server? (y/n): ").strip().lower()
        if ans == 'y':
            server_path = input("[bold]Path to llama-server binary[/bold] (e.g. llama-server): ").strip() or "llama-server"
            models_dir = input("[bold]Path to models directory[/bold]: ").strip()

            api_base = "http://localhost:9931/v1"
            api_key = ""
            extra_provider_config = {
                "server_path": server_path,
                "models_dir": models_dir
            }
        else:
            console.print("Please provide your API connection details.\n")
            api_base = input("[bold]API Base[/bold] "
                             "(default http://localhost:9931/v1): ").strip()
            if not api_base:
                api_base = "http://localhost:9931/v1"

            api_key = input("[bold]API Key[/bold] "
                            "(press Enter if none): ").strip()

    # ── 2. Save config ────────────────────────────────────────────────
    config = {
        "providers": {
            "llama-cpp-router": {
                "type": "router",
                "api_base": api_base,
                "api_key": encrypt(api_key) if api_key else "",
                **extra_provider_config
            }
        },
        "active_provider": "llama-cpp-router",
        "timeout": 120000,
        "max_turns": 100,
        "max_result_chars": 10000,
        "auto_approve_default": False,
        "use_sandbox_default": False,
        "search_rate_limit": 5,
        "search_rate_delay": 5.0,
        "search_max_concurrent": 1,
        "search_retry_count": 3,
        "search_retry_base_delay": 10.0,
        "search_timeout": 30,
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))
    console.print(f"\n[bold green]✓ Saved to {config_path}[/bold green]")

    # ── 3. Verify connection ──────────────────────────────────────────
    if extra_provider_config:
        console.print("[dim]Skipping connection test (server will be started automatically by ask-cli).[/dim]")
    else:
        headers = {
            "Authorization": f"Bearer {api_key}"
        } if api_key else {}

        try:
            r = requests.get(f"{api_base}/models", headers=headers, timeout=3)
            r.raise_for_status()
            console.print(f"[bold green]✓ Connected ({len(r.json()['data'])} models)[/bold green]")
        except Exception as e:
            console.print(f"[bold red]✗ Verification failed: {e}[/bold red]")
            console.print("[dim]Edit config.json manually or re-run setup if needed.[/dim]")


if __name__ == "__main__":
    setup()
