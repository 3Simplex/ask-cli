import os
import signal
import asyncio
import requests
import subprocess
from pathlib import Path
from assets.core.registry import ask_api
from assets.apis.base import BaseApiDriver

@ask_api(name="freetoken-router", description="Driver for FreeToken inference daemon")
class FreeTokenDriver(BaseApiDriver):

    def _control_url(self) -> str:
        return self.config.get("control_base", "http://localhost:1900")

    def _serve_port(self) -> str:
        api_base = self.config.get("api_base", "http://localhost:8000/v1")
        import urllib.parse
        parsed = urllib.parse.urlparse(api_base)
        return str(parsed.port) if parsed.port else "8000"

    async def is_running(self) -> bool:
        # Check either the control plane (port 1900) or the serve endpoint (port 8000)
        urls_to_test = [
            f"{self._control_url()}/health",
            f"{self.config.get('api_base', 'http://localhost:8000/v1')}/models"
        ]
        for url in urls_to_test:
            try:
                r = await asyncio.to_thread(requests.get, url, timeout=2)
                if r.status_code in (200, 401, 403):
                    return True
            except Exception:
                pass
        return False

    def _get_pid_file(self) -> Path:
        pid_dir = Path.home() / ".local" / "share" / "ask" / "pids"
        pid_dir.mkdir(parents=True, exist_ok=True)
        return pid_dir / "freetoken.pid"

    async def start_daemon(self) -> tuple[bool, str]:
        if await self.is_running():
            return True, "FreeToken daemon is already running."

        cmd_str = self.config.get("command", "ft daemon")
        log_dir = Path.home() / ".local" / "share" / "ask" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "freetoken-daemon.log", "a")

        try:
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            self._get_pid_file().write_text(str(proc.pid))
            return True, f"FreeToken daemon started (PID: {proc.pid}). Logs: ~/.local/share/ask/logs/freetoken-daemon.log"
        except Exception as e:
            return False, f"Failed to start FreeToken daemon: {e}"

    async def stop_daemon(self) -> tuple[bool, str]:
        pid_file = self._get_pid_file()
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                pid_file.unlink(missing_ok=True)
            except Exception:
                pid_file.unlink(missing_ok=True)

        cmd_str = self.config.get("stop_command", "pkill -f 'ft daemon'")
        try:
            subprocess.run(cmd_str, shell=True, stderr=subprocess.DEVNULL)
            return True, "FreeToken daemon stopped."
        except Exception as e:
            return False, f"Failed to stop FreeToken daemon: {e}"

    async def list_available_models(self) -> list[str]:
        if not await self.is_running():
            return []

        models = set()

        # 1. Scan configured models_dir for available model folders/checkpoints
        models_dir = os.path.expanduser(self.config.get("models_dir", "~/models"))
        p = Path(models_dir)
        if p.exists():
            for item in p.iterdir():
                if not item.name.startswith("."):
                    models.add(item.name)

        # 2. Include live running model if active
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=1)
            if r.status_code == 200:
                status = r.json()
                if status.get("model"):
                    raw = status["model"]
                    if raw.startswith(models_dir):
                        raw = str(Path(raw).relative_to(p))
                    models.add(raw)
        except Exception:
            pass

        return sorted(list(models))

    async def list_loaded_models(self) -> list[str]:
        if not await self.is_running():
            return []

        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=1)
            if r.status_code == 200:
                status = r.json()
                if status.get("running") and status.get("model"):
                    raw = status["model"]
                    models_dir = os.path.expanduser(self.config.get("models_dir", "~/models"))
                    if raw.startswith(models_dir):
                        raw = str(Path(raw).relative_to(Path(models_dir)))
                    return [raw]
        except Exception:
            pass
        return []

    async def load_model(self, model_name: str) -> tuple[bool, str]:
        if not await self.is_running():
            return False, "FreeToken daemon is offline. Start it first with 'ask -ap freetoken -start'."

        target = model_name
        available = await self.list_available_models()

        # Support selection by index number
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(available):
                target = available[idx]
            else:
                return False, f"Invalid model index {model_name}. Available range: 1-{len(available)}."

        # Resolve full path from models_dir if it exists
        models_dir = os.path.expanduser(self.config.get("models_dir", "~/models"))
        candidate = Path(models_dir) / target
        if candidate.exists():
            target_path = str(candidate)
        else:
            target_path = target

        port = int(self._serve_port())

        # Check current status
        is_already_running = False
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
            if r.status_code == 200:
                is_already_running = r.json().get("running", False)
        except Exception:
            pass

        # Force restart any stalled or maintenance-failed instance
        endpoint = "/engine/switch" if is_already_running else "/engine/start"
        payload = {"model": target_path, "port": port, "args": [], "force": True}

        try:
            r = await asyncio.to_thread(
                requests.post,
                f"{self._control_url()}{endpoint}",
                json=payload,
                timeout=10
            )
            if r.status_code not in (200, 201):
                return False, f"FreeToken daemon error ({r.status_code}): {r.text}"
        except Exception as e:
            return False, f"Failed to reach FreeToken daemon: {e}"

        # Wait until inference engine (port 8000) is 100% loaded and returning models
        api_base = self.config.get("api_base", f"http://localhost:{port}/v1")

        from rich.console import Console
        console = Console()
        start_time = asyncio.get_event_loop().time()
        with console.status(f"[cyan]Loading '{model_name}' into GPU (FreeToken)...[/cyan]"):
            await asyncio.sleep(2)
            while asyncio.get_event_loop().time() - start_time < 120:
                try:
                    r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
                    # When weights are ready, FreeToken returns 200 with data list
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data and any(m.get("id") for m in data):
                            return True, f"FreeToken model '{model_name}' is ready on port {port}."
                except Exception:
                    pass

                # Check if daemon reports a crash or exit
                try:
                    r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
                    if r.status_code == 200:
                        status = r.json()
                        if not status.get("running") and status.get("lastExitCode") not in (None, 0):
                            return False, f"FreeToken engine exited with code {status.get('lastExitCode')}. Check 'ft daemon logs' for details."
                except Exception:
                    pass

                # Check if serve port is reporting maintenance failure
                try:
                    r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
                    if r.status_code == 503 and "maintenance failed" in r.text.lower():
                        return False, "FreeToken serve failed during initialization (maintenance failed). Check 'ft daemon logs'."
                except Exception:
                    pass

                await asyncio.sleep(2)

        return False, f"Model load timed out after 120 seconds (port {port} not ready)."

    async def unload_model(self, model_name: str) -> tuple[bool, str]:
        try:
            r = await asyncio.to_thread(requests.post, f"{self._control_url()}/engine/stop", json={"force": False}, timeout=10)
            if r.status_code == 200:
                return True, "FreeToken serve stopped."
            return False, f"FreeToken returned status {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Failed to stop FreeToken serve: {e}"

    async def get_context_limit(self, model_name: str) -> int:
        # 1. Query live engine stats from FreeToken daemon control plane
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/stats", timeout=2)
            if r.status_code == 200:
                stats = r.json()
                # Extract true active KV cache token limit or max_seq_len
                limit = stats.get("max_seq_len") or stats.get("kv_cache_tokens") or stats.get("max_context_length")
                if limit and int(limit) > 0:
                    return int(limit)
        except Exception:
            pass

        # 2. Query direct serve stats
        try:
            api_base = self.config.get("api_base", "http://localhost:8000/v1").removesuffix("/v1")
            r = await asyncio.to_thread(requests.get, f"{api_base}/v1/stats", timeout=2)
            if r.status_code == 200:
                stats = r.json()
                limit = stats.get("max_seq_len") or stats.get("kv_cache_tokens")
                if limit and int(limit) > 0:
                    return int(limit)
        except Exception:
            pass

        def _get_presets_path(self) -> Path:
        presets_dir = Path.home() / ".local" / "share" / "ask" / "presets"
        presets_dir.mkdir(parents=True, exist_ok=True)
        return presets_dir / "freetoken.json"

    def _normalize_ft_key(self, k: str) -> str:
        k = k.lower().replace("_", "-")
        mapping = {
            "c": "max-model-len", "ctx": "max-model-len", "max-tokens": "max-model-len",
            "gpu": "gpu-memory-utilization", "gpu-util": "gpu-memory-utilization",
            "tp": "tensor-parallel-size"
        }
        return mapping.get(k, k)

    async def get_model_info(self, model_name: str = "") -> dict:
        info = {
            "provider": self.name,
            "is_running": await self.is_running(),
            "control_url": self._control_url(),
            "api_base": self.config.get("api_base"),
            "models": {}
        }
        preset_file = self._get_presets_path()
        saved_presets = json.loads(preset_file.read_text()) if preset_file.exists() else {}
        info["presets"] = saved_presets

        if await self.is_running():
            try:
                r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/stats", timeout=2)
                if r.status_code == 200:
                    info["engine_stats"] = r.json()
            except Exception:
                pass
        return info

    async def set_model_config(self, model_name: str, settings: dict) -> tuple[bool, str]:
        preset_file = self._get_presets_path()
        try:
            presets = json.loads(preset_file.read_text()) if preset_file.exists() else {}
        except Exception:
            presets = {}

        target = model_name or "*"
        presets.setdefault(target, {})
        for k, v in settings.items():
            presets[target][self._normalize_ft_key(k)] = str(v)

        preset_file.write_text(json.dumps(presets, indent=2))

        # If model is currently loaded, switch it
        loaded = await self.list_loaded_models()
        if target in loaded:
            await self.load_model(target)
            return True, f"Updated FreeToken preset for '{target}' and restarted engine."

        return True, f"Saved FreeToken preset for '{target}'."

    async def measure_tokens(self, model_name: str, messages: list) -> int:
        # Pre-check tokenization using FreeToken's native tokenize endpoint if available
        api_base = self.config.get("api_base", "http://localhost:8000/v1")
        payload = {"model": model_name, "messages": messages}
        for endpoint in [f"{api_base}/tokenize", f"{api_base}/chat/completions/input_tokens"]:
            try:
                r = await asyncio.to_thread(requests.post, endpoint, json=payload, timeout=2)
                if r.status_code == 200:
                    data = r.json()
                    tokens = data.get("input_tokens") or data.get("tokens") or (len(data.get("tokens", [])) if isinstance(data.get("tokens"), list) else 0)
                    if tokens:
                        return int(tokens)
            except Exception:
                pass
        return 0
