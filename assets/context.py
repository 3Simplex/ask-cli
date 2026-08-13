# context.py
import os
import json
import asyncio
import time
import requests
from datetime import datetime
from pathlib import Path
from rich.console import Console

console = Console()

class SearchRateLimiter:
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

class AskContext:
    def __init__(self, args=None):
        self.base_dir = self._resolve_assets_dir()
        self.data_dir = Path(os.path.expanduser("~/.local/share/ask"))

        # Load from the new user-local path
        config_path = self.data_dir / "config.json"

        # Fallback for dev environments where it's still in the source tree
        if not config_path.exists():
            config_path = self.base_dir / "config" / "config.json"

        with open(config_path) as f:
            self.config = json.load(f)

        # --- Resolve active provider settings & decrypt API key ---
        active = self.config.get("active_provider")
        if active and "providers" in self.config:
            provider = self.config["providers"].get(active, {})
            self.config["api_base"] = provider.get("api_base")
            self.config["server_path"] = provider.get("server_path")
            self.config["models_dir"] = provider.get("models_dir")

            enc_key = provider.get("api_key", "")
            if enc_key:
                import base64, hashlib
                from cryptography.fernet import Fernet

                # Reconstruct the machine-specific key
                fernet_key = base64.urlsafe_b64encode(
                    hashlib.sha256(os.uname().nodename.encode()).digest()
                )
                try:
                    self.config["api_key"] = Fernet(fernet_key).decrypt(enc_key.encode()).decode()
                except Exception:
                    self.config["api_key"] = ""
            else:
                self.config["api_key"] = ""
        # ---------------------------------------------------------

        self.active_routine = None

        # Override config with CLI flags if provided
        if args:
            if getattr(args, 'auto', False):
                self.config['auto_approve_default'] = True
            if getattr(args, 'sandbox', False):
                self.config['use_sandbox_default'] = True
            if getattr(args, 'routine', None):
                self.active_routine = args.routine

        self.data_dir = Path(os.path.expanduser("~/.local/share/ask"))
        self.threads_dir = self.data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir = self.data_dir / "security_audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        self.ui_lock = asyncio.Lock()
        self.watcher_lock = asyncio.Lock()

        self.search_limiter = SearchRateLimiter(
            max_per_minute=self.config.get('search_rate_limit', 5),
            delay=self.config.get('search_rate_delay', 2.0),
            max_concurrent=self.config.get('search_max_concurrent', 1),
        )

        self.current_tokens = 0
        self.max_tokens = 8192  # Default fallback

    def get_token_budget(self, max_tokens: int = None) -> int:
        """Calculate roughly how many tokens are remaining in the context window.
        Leaves a 1000 token buffer for system prompts and the model's reply."""
        # Use provided max_tokens or fall back to the native tracker
        mt = max_tokens if max_tokens else self.max_tokens
        buffer = 1000
        budget = mt - self.current_tokens - buffer
        return max(0, budget)

    async def init_context_limit(self):
        """Fetch the true context limit for the active session model."""
        model = self.config.get("model")
        if not model:
            return

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        import urllib.parse
        encoded_model = urllib.parse.quote(model)

        try:
            # Route exactly to the model we are about to use
            r = await asyncio.to_thread(requests.get, f"{api_base}/props?model={encoded_model}", timeout=2)
            if r.status_code == 200:
                data = r.json()
                n_ctx = data.get("default_generation_settings", {}).get("n_ctx", 0)
                if n_ctx > 0:
                    self.max_tokens = n_ctx
        except Exception:
            pass

    async def measure_tokens(self, messages: list) -> int:
        """Use the server's tokenizer to proactively count tokens in a message array."""
        if not self.config.get("api_base") or not self.config.get("model"):
            return self.current_tokens

        api_base = self.config["api_base"].removesuffix("/v1")
        payload = {
            "model": self.config["model"],
            "messages": messages
        }

        try:
            r = await asyncio.to_thread(
                requests.post,
                f"{api_base}/v1/chat/completions/input_tokens",
                headers={"Authorization": f"Bearer {self.config.get('api_key', '')}"},
                json=payload,
                timeout=5
            )
            if r.status_code == 200:
                self.current_tokens = r.json().get("input_tokens", self.current_tokens)
        except Exception:
            pass
        return self.current_tokens

    def _resolve_assets_dir(self) -> Path:
        if path := os.environ.get('ASK_ASSETS_DIR'):
            return Path(path)
        current_dir = Path(__file__).parent
        if current_dir.name == "assets":
            return current_dir
        dev_path = current_dir.parent / "assets"
        nix_path = current_dir.parent.parent / "share" / "ask" / "assets"
        return dev_path if dev_path.exists() else nix_path

    async def security_watcher(self, cmd: str) -> str:
        sys_prompt = "You are a high-security command auditor.\nEvaluate the command based on:\n1. Privilege escalation attempts.\n2. Destructive filesystem operations.\n3. Network exfiltration.\n4. Obfuscated shell syntax.\n\nResponse Format:\n- If safe: 'Reasoning:[Brief explanation] P'\n- If unsafe: 'Reasoning: [Detailed reason] F'"
        payload = {
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Analyze this command: {cmd}"}
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "reasoning_budget": 2048,
            "model": self.config.get("model")
        }
        try:
            async with self.watcher_lock:
                r = await asyncio.to_thread(
                    requests.post, f"{self.config['api_base']}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config['api_key']}"},
                    json=payload, timeout=60
                )
                r.raise_for_status()
                msg = r.json()['choices'][0]['message']
                response_text = msg.get('content') or msg.get('reasoning_content') or ""
                if not response_text.strip():
                    response_text = "Reasoning: Local API returned an empty string. F"

            with open(self.audit_dir / "audit_log.jsonl", "a") as f:
                f.write(json.dumps({"timestamp": datetime.now().isoformat(), "command": cmd, "decision": response_text}) + "\n")
            return response_text
        except Exception as e:
            return f"Reasoning: Watcher Error ({str(e)}) F"

    async def async_prompt_user(self, prompt_text: str) -> str:
        """Safely prompt the user, even if stdin is being piped."""
        import sys
        def _prompt():
            if not sys.stdin.isatty():
                try:
                    with open('/dev/tty', 'r') as tty:
                        console.print(prompt_text, end="")
                        return tty.readline().strip()
                except OSError:
                    return "n"  # Fallback if tty is entirely unavailable
            console.print(prompt_text, end="")
            return sys.stdin.readline().strip()

        return await asyncio.to_thread(_prompt)

    async def ensure_server_running(self):
        # Only run if cold-start parameters are provided
        if not self.config.get("server_path") or not self.config.get("models_dir"):
            return

        # Check if it's already running
        try:
            r = await asyncio.to_thread(requests.get, f"{self.config['api_base']}/models", timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass

        import urllib.parse
        import subprocess

        parsed = urllib.parse.urlparse(self.config["api_base"])
        port = str(parsed.port) if parsed.port else "9931"

        console.print(f"[bold yellow]Starting local llama-server in background on port {port}...[/bold yellow]")

        # Divert server output to a log file instead of polluting the terminal
        log_file = open(self.data_dir / "llama-server.log", "w")
        subprocess.Popen([
            self.config["server_path"],
            "--models-dir", self.config["models_dir"],
            "--port", port
        ], stdout=log_file, stderr=subprocess.STDOUT)

        start_time = time.time()
        with console.status("[cyan]Waiting for server to become ready...[/cyan]"):
            while time.time() - start_time < 30:
                try:
                    r = await asyncio.to_thread(requests.get, f"{self.config['api_base']}/models", timeout=1)
                    if r.status_code == 200:
                        console.print("[bold green]✓ llama-server ready[/bold green]")
                        return
                except Exception:
                    await asyncio.sleep(1)

        console.print("[bold red]✗ llama-server failed to start within 30 seconds. Check logs in ~/.local/share/ask/llama-server.log[/bold red]")

    async def select_model_if_needed(self):
        # If the model is already set (e.g. resumed from a saved thread), skip.
        if self.config.get("model"):
            return

        api_base = self.config.get('api_base', '')
        base_url = api_base.removesuffix("/v1")

        try:
            # Query the router for available models
            r = await asyncio.to_thread(requests.get, f"{base_url}/models", timeout=2)
            if r.status_code != 200:
                return

            models_data = r.json().get("data", [])
            if not models_data:
                return

            # If exactly one model is already loaded, seamlessly default to it
            loaded = [m["id"] for m in models_data if m.get("status", {}).get("value") == "loaded"]
            if len(loaded) == 1:
                self.config["model"] = loaded[0]
                return

            # Otherwise, prompt the user to select one for the session
            console.print("\n[bold cyan]Select a model to use for this session:[/bold cyan]")
            for i, m in enumerate(models_data):
                status = m.get("status", {}).get("value", "unknown")
                icon = "✅" if status == "loaded" else "⏸"
                console.print(f"  [{i+1}] {icon} {m.get('id', 'unknown')} ({status})")

            while True:
                ans = await self.async_prompt_user(f"\nEnter model number (1-{len(models_data)}): ")
                try:
                    idx = int(ans) - 1
                    if 0 <= idx < len(models_data):
                        self.config["model"] = models_data[idx]["id"]
                        console.print(f"[bold green]Selected: {self.config['model']}[/bold green]\n")
                        break
                    else:
                        console.print("[bold red]Invalid selection.[/bold red]")
                except ValueError:
                    console.print("[bold red]Please enter a valid number.[/bold red]")

        except Exception:
            # Silently fail if the endpoint isn't supported (e.g. OpenAI API)
            pass
