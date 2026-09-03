# context.py
import os
import json
import asyncio
import time
import requests
from datetime import datetime
from assets.core import defaults
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
            # Wait if we've hit the concurrent limit
            while self._active >= self.max_concurrent:
                await asyncio.sleep(0.1)
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
        # Now release the lock before sleeping, so other tasks can queue
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

        # ── directories and locks ──
        self.threads_dir = self.data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir = self.data_dir / "security_audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        self.ui_lock = asyncio.Lock()
        self.watcher_lock = asyncio.Lock()

        self.search_limiter = SearchRateLimiter(
            max_per_minute=defaults.get(self.config, "search_rate_limit"),
            delay=defaults.get(self.config, "search_rate_delay"),
            max_concurrent=defaults.get(self.config, "search_max_concurrent"),
        )

        # These are set twice in the original—it's harmless, but keep one:
        self.current_tokens = 0
        self.max_tokens = 8192
        self.active_routine = None

        # Initialize active provider dynamically
        req_provider = getattr(args, 'api_provider', None) if args else None
        initial_provider = req_provider or defaults.get(self.config, "active_provider")
        self.switch_provider(initial_provider)

        # Override config with CLI flags if provided
        if args:
            if getattr(args, 'auto', False):
                self.config['auto_approve_default'] = True
            if getattr(args, 'sandbox', False):
                self.config['use_sandbox_default'] = True
            if getattr(args, 'routine', None):
                self.active_routine = args.routine

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
        if not model or not hasattr(self, 'driver'):
            return

        try:
            limit = await self.driver.get_context_limit(model)
            if limit > 0:
                self.max_tokens = limit
                console.print(f"[dim]⚡ Context window set to {self.max_tokens:,} tokens ({model})[/dim]")
        except Exception as e:
            console.print(f"[dim yellow]⚠ Could not detect context limit: {e}[/dim yellow]")

    async def measure_tokens(self, messages: list) -> int:
        """Proactively measure tokens using driver or fallback heuristic."""
        model = self.config.get("model", "")
        if hasattr(self, 'driver'):
            try:
                tokens = await self.driver.measure_tokens(model, messages)
                if tokens > 0:
                    self.current_tokens = tokens
                    return self.current_tokens
            except Exception:
                pass

        # Fallback character estimation if driver returns 0
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        self.current_tokens = int(total_chars / 3.5)
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

    def switch_provider(self, provider_name: str):
        """Configure runtime settings, decrypt API key, and instantiate driver for a provider."""
        providers = self.config.get("providers", {})
        if provider_name and provider_name in providers:
            self.active_provider_name = provider_name
            provider = providers[provider_name]
            self.config["api_base"] = provider.get("api_base")
            self.config["driver"] = provider.get("driver") or (
                "llama-cpp" if "llama" in provider_name or provider.get("type") == "router" else "openai-compatible"
            )
            if provider.get("default_model"):
                self.config.setdefault("model", provider.get("default_model"))
            if provider.get("max_tokens"):
                self.max_tokens = provider.get("max_tokens")

            enc_key = provider.get("api_key", "")
            if enc_key:
                import base64, hashlib
                from cryptography.fernet import Fernet

                fernet_key = base64.urlsafe_b64encode(
                    hashlib.sha256(os.uname().nodename.encode()).digest()
                )
                try:
                    self.config["api_key"] = Fernet(fernet_key).decrypt(enc_key.encode()).decode()
                except Exception:
                    self.config["api_key"] = ""
            else:
                self.config["api_key"] = ""
        else:
            self.active_provider_name = provider_name or ""
            self.config.setdefault("driver", "openai-compatible")

        from assets.apis import get_api_driver
        provider_cfg = providers.get(self.active_provider_name, {})
        provider_cfg = {
            **provider_cfg,
            "api_base": self.config.get("api_base"),
            "api_key": self.config.get("api_key"),
            "provider_name": self.active_provider_name
        }
        self.driver = get_api_driver(self.config.get("driver", "openai-compatible"), provider_cfg, ctx=self)

    def get_driver_for_provider(self, provider_name: str):
        """Instantiate a driver instance for any configured provider without modifying active context."""
        from assets.apis import get_api_driver
        providers = self.config.get("providers", {})
        pcfg = {**providers.get(provider_name, {}), "provider_name": provider_name}
        driver_type = pcfg.get("driver") or (
            "llama-cpp" if "llama" in provider_name or pcfg.get("type") == "router" else "openai-compatible"
        )
        return get_api_driver(driver_type, pcfg, ctx=self)

    async def ensure_current_server_running(self):
        """Start daemon for currently selected provider if not already running."""
        if not hasattr(self, 'driver'):
            return

        if await self.driver.is_running():
            return

        console.print(f"[bold yellow]Provider '{self.active_provider_name}' daemon is not running. Starting daemon...[/bold yellow]")
        success, msg = await self.driver.start_daemon()
        if success:
            console.print(f"[bold green]✓ {msg}[/bold green]")
            start_time = time.time()
            with console.status("[cyan]Waiting for daemon to respond...[/cyan]"):
                while time.time() - start_time < 15:
                    if await self.driver.is_running():
                        console.print("[bold green]✓ Provider ready[/bold green]")
                        return
                    await asyncio.sleep(1)
        else:
            console.print(f"[dim yellow]Notice: {msg}[/dim yellow]")

    async def resolve_provider_and_model(self, has_explicit_provider: bool = False):
        providers = self.config.get("providers", {})
        if not providers:
            return

        # 1. If model is already set (e.g. resumed thread session)
        if self.config.get("model"):
            model_target = self.config["model"]
            # Verify if active provider owns this model; if not, find the right provider
            curr_driver = getattr(self, 'driver', None)
            curr_avail = (await curr_driver.list_available_models()) if curr_driver and await curr_driver.is_running() else []

            if model_target not in curr_avail:
                for p_name in providers:
                    d = self.get_driver_for_provider(p_name)
                    if await d.is_running() and model_target in (await d.list_available_models()):
                        self.switch_provider(p_name)
                        break

            await self.ensure_current_server_running()
            if hasattr(self, 'driver') and await self.driver.is_running():
                loaded = await self.driver.list_loaded_models()
                if self.config["model"] not in loaded:
                    await self.driver.load_model(self.config["model"])
            return

        # 2. If user explicitly passed -ap <provider>
        if has_explicit_provider and self.active_provider_name:
            await self.ensure_current_server_running()
            await self._select_model_for_active_provider()
            return

        # 3. Check for hot/loaded models across all configured providers
        hot_models = []
        for p_name in providers:
            d = self.get_driver_for_provider(p_name)
            if await d.is_running():
                loaded = await d.list_loaded_models()
                for m in loaded:
                    hot_models.append((p_name, m))

        if hot_models:
            console.print("\n[bold cyan]🔥 Active loaded models found in memory:[/bold cyan]")
            for i, (p_name, m_name) in enumerate(hot_models):
                console.print(f"  [{i+1}] 🟢 [bold]{m_name}[/bold] [dim]({p_name})[/dim]")
            other_idx = len(hot_models) + 1
            console.print(f"  [{other_idx}] ➕ [dim]Choose a different provider / model[/dim]")

            ans = await self.async_prompt_user(f"\nEnter selection (1-{other_idx}, default 1): ")
            choice = 1
            if ans.strip():
                try:
                    choice = int(ans.strip())
                except ValueError:
                    choice = 1

            if 1 <= choice <= len(hot_models):
                chosen_p, chosen_m = hot_models[choice - 1]
                self.switch_provider(chosen_p)
                self.config["model"] = chosen_m
                console.print(f"[bold green]Using hot model: {chosen_m} ({chosen_p})[/bold green]\n")

                # Verify the engine is actively answering; start it if not ready
                if hasattr(self, 'driver') and await self.driver.is_running():
                    loaded = await self.driver.list_loaded_models()
                    if chosen_m not in loaded:
                        await self.driver.load_model(chosen_m)
                return

        # 4. No hot model chosen -> Provider Picker -> Model Picker
        console.print("\n[bold cyan]Select an API Provider / Router:[/bold cyan]")
        p_list = list(providers.keys())
        for i, p_name in enumerate(p_list):
            d = self.get_driver_for_provider(p_name)
            is_up = await d.is_running()
            status_str = "[bold green]ONLINE[/bold green]" if is_up else "[dim red]STOPPED[/dim red]"
            console.print(f"  [{i+1}] {p_name} ({status_str})")

        while True:
            ans = await self.async_prompt_user(f"\nEnter provider number (1-{len(p_list)}): ")
            try:
                idx = int(ans.strip()) - 1
                if 0 <= idx < len(p_list):
                    selected_p = p_list[idx]
                    self.switch_provider(selected_p)
                    break
            except ValueError:
                pass
            console.print("[bold red]Invalid selection.[/bold red]")

        await self.ensure_current_server_running()
        await self._select_model_for_active_provider()

    async def _select_model_for_active_provider(self):
        """Prompt and load model for current active provider."""
        if not hasattr(self, 'driver'):
            return

        loaded = await self.driver.list_loaded_models()
        available = await self.driver.list_available_models()

        if not available and not loaded:
            return

        if len(available) == 1:
            self.config["model"] = available[0]
            if self.config["model"] not in loaded:
                await self.driver.load_model(self.config["model"])
            return

        console.print(f"\n[bold cyan]Select a model for provider '{self.active_provider_name}':[/bold cyan]")
        for i, m in enumerate(available):
            icon = "🟢" if m in loaded else "⏸"
            status_text = " [bold green](LOADED)[/bold green]" if m in loaded else ""
            console.print(f"  [{i+1}] {icon} {m}{status_text}")

        while True:
            ans = await self.async_prompt_user(f"\nEnter model number (1-{len(available)}): ")
            try:
                idx = int(ans.strip()) - 1
                if 0 <= idx < len(available):
                    self.config["model"] = available[idx]
                    console.print(f"[bold green]Selected: {self.config['model']}[/bold green]\n")
                    break
            except ValueError:
                pass
            console.print("[bold red]Invalid selection.[/bold red]")

        if self.config.get("model") and self.config["model"] not in loaded:
            success, msg = await self.driver.load_model(self.config["model"])
            if not success:
                console.print(f"[bold red]Error loading model:[/bold red] {msg}")
