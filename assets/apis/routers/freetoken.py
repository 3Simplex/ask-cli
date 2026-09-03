import os
import signal
import asyncio
import requests
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Tuple
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

    def _get_presets_path(self) -> Path:
        presets_dir = Path.home() / ".local" / "share" / "ask" / "presets"
        presets_dir.mkdir(parents=True, exist_ok=True)
        return presets_dir / "freetoken.json"

    def _normalize_ft_key(self, k: str) -> str:
        k = k.lower().replace("_", "-").lstrip("-")
        mapping = {
            "c": "num-tokens",
            "ctx": "num-tokens",
            "tokens": "num-tokens",
            "num-tokens": "num-tokens",
            "max-tokens": "max-seq-len-override",
            "max-seq-len": "max-seq-len-override",
            "max-seq-len-override": "max-seq-len-override",
            "requests": "max-running-requests",
            "max-requests": "max-running-requests",
            "max-running-requests": "max-running-requests",
            "prefill": "max-prefill-length",
            "max-prefill": "max-prefill-length",
            "gpu": "gpu",
            "gpu-util": "gpu-memory-utilization",
            "gpu-memory-utilization": "gpu-memory-utilization",
            "tp": "tensor-parallel-size"
        }
        return mapping.get(k, k)

    def _sync_active_port(self, port: Any):
        if not port:
            return
        port_str = str(port)
        new_api_base = f"http://localhost:{port_str}/v1"
        self.config["api_base"] = new_api_base
        if self.ctx and hasattr(self.ctx, "config"):
            self.ctx.config["api_base"] = new_api_base

    async def is_running(self) -> bool:
        # Check control plane health first
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/health", timeout=2)
            if r.status_code in (200, 401, 403):
                return True
        except Exception:
            pass

        # Fallback check inference endpoint
        api_base = self.config.get("api_base", "http://localhost:8000/v1")
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
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
        models_dir = os.path.expanduser(self.config.get("models_dir", "~/models"))
        p = Path(models_dir)
        if p.exists():
            for item in p.iterdir():
                if not item.name.startswith("."):
                    models.add(item.name)

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
                if status.get("running") and status.get("model") and status.get("lastExitCode") in (None, 0):
                    port = status.get("port") or self._serve_port()
                    self._sync_active_port(port)

                    # Verify that ft serve is actually responsive before declaring it loaded
                    serve_healthy = False
                    try:
                        hr = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/health", timeout=1)
                        serve_healthy = (hr.status_code == 200)
                    except Exception:
                        pass

                    if not serve_healthy:
                        try:
                            pr = await asyncio.to_thread(requests.get, f"http://localhost:{port}/v1/models", timeout=1)
                            serve_healthy = (pr.status_code == 200)
                        except Exception:
                            pass

                    if serve_healthy:
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

        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(available):
                target = available[idx]
            else:
                return False, f"Invalid model index {model_name}. Available range: 1-{len(available)}."

        models_dir = os.path.expanduser(self.config.get("models_dir", "~/models"))
        candidate = Path(models_dir) / target
        target_path = str(candidate) if candidate.exists() else target
        port = int(self._serve_port())

        # Build ft serve flags from presets
        preset_file = self._get_presets_path()
        saved_presets = json.loads(preset_file.read_text()) if preset_file.exists() else {}
        merged_preset = {**saved_presets.get("*", {}), **saved_presets.get(target, {})}

        # Default to 1 slot to maximize KV cache allocation
        if "max-running-requests" not in merged_preset:
            merged_preset["max-running-requests"] = "1"

        ft_args = []
        for k, v in merged_preset.items():
            flag = f"--{k}" if not k.startswith("-") else k
            if v and str(v).lower() not in ("true", "on"):
                ft_args.extend([flag, str(v)])
            elif str(v).lower() in ("true", "on"):
                ft_args.append(flag)

        # Check if daemon already has an engine running
        is_already_running = False
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
            if r.status_code == 200:
                is_already_running = r.json().get("running", False)
        except Exception:
            pass

        endpoint = "/engine/switch" if is_already_running else "/engine/start"
        payload = {"model": target_path, "port": port, "args": ft_args, "force": True}

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

        api_base = f"http://localhost:{port}/v1"
        self._sync_active_port(port)
        from rich.console import Console
        console = Console()
        start_time = asyncio.get_event_loop().time()
        with console.status(f"[cyan]Loading '{model_name}' (args: {' '.join(ft_args)})...[/cyan]"):
            await asyncio.sleep(2)
            while asyncio.get_event_loop().time() - start_time < 120:
                try:
                    r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data and any(m.get("id") for m in data):
                            self._sync_active_port(port)
                            return True, f"FreeToken model '{model_name}' is ready on port {port}."
                except Exception:
                    pass

                try:
                    r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
                    if r.status_code == 200:
                        status = r.json()
                        if not status.get("running") and status.get("lastExitCode") not in (None, 0):
                            return False, f"FreeToken engine exited with code {status.get('lastExitCode')}. Check logs."
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
        # 1. Check preset override (max-seq-len-override)
        preset_file = self._get_presets_path()
        saved_presets = json.loads(preset_file.read_text()) if preset_file.exists() else {}
        preset = {**saved_presets.get("*", {}), **saved_presets.get(model_name, {})}
        if "max-seq-len-override" in preset:
            try:
                return int(preset["max-seq-len-override"])
            except ValueError:
                pass

        if not await self.is_running():
            return self.config.get("max_tokens", 8192)

        api_base = self.config.get("api_base", "http://localhost:8000/v1")

        # 2. Query /v1/models for model metadata (n_ctx_train)
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
            if r.status_code == 200:
                data = r.json().get("data", [])
                for entry in data:
                    if entry.get("id") == model_name:
                        meta = entry.get("meta", {})
                        # n_ctx_train is the native context length
                        if meta.get("n_ctx_train") and int(meta["n_ctx_train"]) > 0:
                            return int(meta["n_ctx_train"])
                        # Also check top-level fields
                        for key in ["max_context_length", "context_length"]:
                            if entry.get(key) and int(entry[key]) > 0:
                                return int(entry[key])
        except Exception:
            pass

        # 3. Query /engine/status to get the loaded model's max_seq_len_override
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
            if r.status_code == 200:
                status = r.json()
                # Some versions expose max_seq_len_override in status
                if status.get("max_seq_len_override") and int(status["max_seq_len_override"]) > 0:
                    return int(status["max_seq_len_override"])
        except Exception:
            pass

        # 4. Fallback to config default
        return self.config.get("max_tokens", 8192)

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
        if "*" in saved_presets:
            info["global_preset"] = saved_presets["*"]

        if not await self.is_running():
            return info

        engine_status = {}
        try:
            r = await asyncio.to_thread(requests.get, f"{self._control_url()}/engine/status", timeout=2)
            if r.status_code == 200:
                engine_status = r.json()
        except Exception:
            pass

        available = await self.list_available_models()
        loaded = await self.list_loaded_models()

        target_models = [model_name] if model_name and model_name in available else (
            available if not model_name else [model_name]
        )

        for m in target_models:
            is_loaded = m in loaded
            preset = saved_presets.get(m, {})
            m_info = {
                "loaded": is_loaded,
                "preset": preset
            }

            if is_loaded:
                m_info["n_ctx"] = await self.get_context_limit(m)
                params = {}
                if engine_status.get("port"):
                    params["port"] = engine_status.get("port")
                if engine_status.get("args"):
                    params["args"] = " ".join(engine_status.get("args")) if isinstance(engine_status.get("args"), list) else str(engine_status.get("args"))

                for k, v in preset.items():
                    if k not in params:
                        params[k] = v

                if params:
                    m_info["params"] = params

            info["models"][m] = m_info

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

        # Hot-reload if model is currently loaded
        loaded = await self.list_loaded_models()
        if target in loaded or (target == "*" and loaded):
            reload_target = loaded[0] if target == "*" else target
            await self.load_model(reload_target)
            return True, f"Updated FreeToken preset for '{target}' and hot-reloaded model in memory."

        return True, f"Saved FreeToken preset for '{target}'."

    async def list_presets(self) -> Dict[str, Dict[str, str]]:
        preset_file = self._get_presets_path()
        try:
            return json.loads(preset_file.read_text())
        except Exception:
            return {}

    async def save_preset(self, name: str, settings: Dict[str, str]) -> Tuple[bool, str]:
        preset_file = self._get_presets_path()
        presets = await self.list_presets()
        presets[name] = {self._normalize_ft_key(k): str(v) for k, v in settings.items()}
        preset_file.write_text(json.dumps(presets, indent=2))
        return True, f"Saved FreeToken preset template '@{name}'."

    async def reload_router(self) -> Tuple[bool, str]:
        loaded = await self.list_loaded_models()
        if loaded:
            return await self.load_model(loaded[0])
        return True, "FreeToken configuration refreshed."

    async def measure_tokens(self, model_name: str, messages: list) -> int:
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
