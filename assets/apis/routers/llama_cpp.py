import os
import signal
import asyncio
import requests
import subprocess
import urllib.parse
import configparser
import json
from pathlib import Path
from typing import Dict, Any, Tuple
from assets.core.registry import ask_api
from assets.apis.base import BaseApiDriver

@ask_api(name="llama-cpp", description="Driver for Llama.cpp multi-model router daemon and llama-server")
class LlamaCppDriver(BaseApiDriver):

    def _get_pid_file(self) -> Path:
        pid_dir = Path.home() / ".local" / "share" / "ask" / "pids"
        pid_dir.mkdir(parents=True, exist_ok=True)
        provider_name = self.config.get("provider_name", "llama-cpp")
        return pid_dir / f"{provider_name}.pid"

    def _get_presets_path(self) -> Path:
        presets_dir = Path.home() / ".local" / "share" / "ask" / "presets"
        presets_dir.mkdir(parents=True, exist_ok=True)
        preset_file = presets_dir / "llama-cpp.ini"
        if not preset_file.exists():
            preset_file.write_text("version = 1\n\n[*]\n")
        return preset_file

    def _read_preset_ini(self, preset_file: Path) -> configparser.ConfigParser:
        """Parse INI file while safely skipping top-level llama-server metadata like 'version = 1'."""
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        if preset_file.exists():
            text = preset_file.read_text()
            lines = text.splitlines()
            body_lines = []
            first_section_found = False
            for line in lines:
                if line.strip().startswith("["):
                    first_section_found = True
                if first_section_found:
                    body_lines.append(line)
            if body_lines:
                parser.read_string("\n".join(body_lines))
        return parser

    def _write_preset_ini(self, preset_file: Path, parser: configparser.ConfigParser):
        """Write INI ensuring 'version = 1' stays at the top for llama-server."""
        with open(preset_file, "w") as f:
            f.write("version = 1\n\n")
            parser.write(f)

    def _get_templates_path(self) -> Path:
        presets_dir = Path.home() / ".local" / "share" / "ask" / "presets"
        presets_dir.mkdir(parents=True, exist_ok=True)
        templates_file = presets_dir / "templates.json"
        if not templates_file.exists():
            templates_file.write_text(json.dumps({
                "deep-context": {"c": "32768", "flash-attn": "on"},
                "max-context": {"c": "65536", "flash-attn": "on"},
                "coding-strict": {"c": "16384", "temp": "0.2", "top_p": "0.9"}
            }, indent=2))
        return templates_file

    def _normalize_key(self, k: str) -> str:
        k = k.lower().replace("_", "-")
        mapping = {
            "ctx": "c", "ctx-size": "c", "context": "c", "max-tokens": "c",
            "fa": "flash-attn", "flash-attention": "flash-attn",
            "ngl": "n-gpu-layers", "gpu": "n-gpu-layers", "gpu-layers": "n-gpu-layers",
            "temp": "temp", "temperature": "temp",
            "top-p": "top-p", "min-p": "min-p", "top-k": "top-k",
            "tb": "reasoning-budget", "reasoning-budget": "reasoning-budget", "think-budget": "reasoning-budget",
            "cram": "cache-ram", "cache-ram": "cache-ram"
        }
        return mapping.get(k, k)

    async def is_running(self) -> bool:
        api_base = self.config.get("api_base", "http://localhost:9931/v1")
        base_url = api_base.removesuffix("/v1")
        try:
            r = await asyncio.to_thread(requests.get, f"{base_url}/models", timeout=1)
            return r.status_code == 200
        except Exception:
            return False

    async def start_daemon(self) -> tuple[bool, str]:
        if await self.is_running():
            return True, "Daemon is already running."

        # Add os.path.expanduser here:
        server_path = os.path.expanduser(self.config.get("server_path", "llama-server"))
        models_dir = os.path.expanduser(self.config.get("models_dir", ""))
        api_base = self.config.get("api_base", "http://localhost:9931/v1")
        parsed = urllib.parse.urlparse(api_base)
        port = str(parsed.port) if parsed.port else "9931"

        if not models_dir or not Path(models_dir).exists():
            return False, f"Models directory '{models_dir}' does not exist."

        log_dir = Path.home() / ".local" / "share" / "ask" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / f"llama-server-{port}.log", "w")

        preset_file = str(self._get_presets_path())
        cmd = [server_path, "--models-dir", models_dir, "--models-preset", preset_file, "--port", port]
        try:
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
            self._get_pid_file().write_text(str(proc.pid))
            return True, f"Started llama-server on port {port} (PID: {proc.pid})."
        except Exception as e:
            return False, f"Failed to start llama-server: {e}"

    async def stop_daemon(self) -> tuple[bool, str]:
        pid_file = self._get_pid_file()
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                pid_file.unlink(missing_ok=True)
                return True, f"Stopped llama-server process (PID {pid})."
            except Exception as e:
                pid_file.unlink(missing_ok=True)
                return False, f"Error stopping process: {e}"
        return False, "No PID file found. Process may need to be stopped manually."

    async def list_available_models(self) -> list[str]:
        # Rely exclusively on live router models endpoint
        if not await self.is_running():
            return []

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
            if r.status_code == 200:
                data = r.json().get("data", [])
                # Extract clean aliases reported by llama-server (excluding mmproj if any)
                return sorted([m.get("id") for m in data if m.get("id") and not m.get("id", "").startswith("mmproj-")])
        except Exception:
            pass
        return []

    async def list_loaded_models(self) -> list[str]:
        if not await self.is_running():
            return []

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        loaded = set()

        # 1. Query slots (active running models in llama-server memory)
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/slots", timeout=2)
            if r.status_code == 200:
                slots = r.json()
                if isinstance(slots, list):
                    for slot in slots:
                        model_id = slot.get("model") or slot.get("model_alias")
                        if model_id and not model_id.startswith("mmproj-"):
                            loaded.add(model_id)
        except Exception:
            pass

        # 2. Check /models endpoint status fields
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models", timeout=2)
            if r.status_code == 200:
                data = r.json().get("data", [])
                for m in data:
                    mid = m.get("id", "")
                    if mid.startswith("mmproj-"):
                        continue
                    status = m.get("status")
                    if isinstance(status, dict) and status.get("value") == "loaded":
                        loaded.add(mid)
                    elif status == "loaded" or m.get("loaded") is True:
                        loaded.add(mid)
        except Exception:
            pass

        return sorted(list(loaded))

    async def load_model(self, model_name: str) -> tuple[bool, str]:
        if not await self.is_running():
            return False, "llama-server is offline. Start it first with 'ask -ap llama-cpp -start'."

        available = await self.list_available_models()
        target = model_name

        # Support selection by index number
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(available):
                target = available[idx]
            else:
                return False, f"Invalid model index {model_name}. Available range: 1-{len(available)}."

        if target not in available:
            return False, f"Model '{target}' not found in available models on llama-server."

        # Check if already loaded in memory
        loaded = await self.list_loaded_models()
        if target in loaded:
            return True, f"Model '{target}' is already loaded in memory."

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        try:
            r = await asyncio.to_thread(requests.post, f"{api_base}/models/load", json={"model": target}, timeout=10)
            if r.status_code in (200, 201):
                return True, f"Model '{target}' loaded successfully."
            return False, f"Server returned status {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Failed to load model: {e}"

    async def unload_model(self, model_name: str) -> tuple[bool, str]:
        if not await self.is_running():
            return False, "llama-server is offline."

        loaded = await self.list_loaded_models()
        target = model_name

        # Support selection by index number from loaded models
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(loaded):
                target = loaded[idx]

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        try:
            r = await asyncio.to_thread(requests.post, f"{api_base}/models/unload", json={"model": target}, timeout=10)
            if r.status_code in (200, 201):
                return True, f"Model '{target}' unloaded successfully."
            return False, f"Server returned status {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Failed to unload model: {e}"

    async def get_context_limit(self, model_name: str) -> int:
        api_base = self.config.get("api_base", "").removesuffix("/v1")
        encoded_model = urllib.parse.quote(model_name) if model_name else ""

        # Tier 1: Query live /props?model={model}
        if encoded_model:
            try:
                r = await asyncio.to_thread(requests.get, f"{api_base}/props?model={encoded_model}", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    gen = data.get("default_generation_settings", {})
                    n_ctx = gen.get("n_ctx", 0) or data.get("n_ctx", 0)
                    if n_ctx and int(n_ctx) > 0:
                        return int(n_ctx)
            except Exception:
                pass

        # Tier 2: Query active slots (live VRAM per-slot limit)
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/slots", timeout=5)
            if r.status_code == 200:
                slots = r.json()
                if isinstance(slots, list) and slots:
                    slot_ctx = slots[0].get("n_ctx", 0)
                    if slot_ctx and int(slot_ctx) > 0:
                        return int(slot_ctx)
        except Exception:
            pass

        # Tier 3: Query root /props
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/props", timeout=5)
            if r.status_code == 200:
                data = r.json()
                gen = data.get("default_generation_settings", {})
                n_ctx = gen.get("n_ctx", 0) or data.get("n_ctx", 0)
                if n_ctx and int(n_ctx) > 0:
                    return int(n_ctx)
        except Exception:
            pass

        # Tier 4: Check configured preset INI file
        try:
            preset_file = self._get_presets_path()
            parser = self._read_preset_ini(preset_file)
            if model_name and parser.has_section(model_name) and parser.has_option(model_name, "c"):
                return int(parser.get(model_name, "c"))
            if parser.has_section("*") and parser.has_option("*", "c"):
                return int(parser.get("*", "c"))
        except Exception:
            pass

        # Tier 5: Query /v1/models metadata (trained max context)
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/v1/models", timeout=5)
            if r.status_code == 200:
                for entry in r.json().get("data", []):
                    if entry.get("id") == model_name and "meta" in entry and entry["meta"]:
                        train_ctx = entry["meta"].get("n_ctx_train", 0)
                        if train_ctx and int(train_ctx) > 0:
                            return int(train_ctx)
        except Exception:
            pass

        return self.config.get("max_tokens", 8192)

    async def measure_tokens(self, model_name: str, messages: list) -> int:
        api_base = self.config.get("api_base", "").removesuffix("/v1")
        payload = {"model": model_name, "messages": messages}
        try:
            r = await asyncio.to_thread(
                requests.post,
                f"{api_base}/v1/chat/completions/input_tokens",
                headers={"Authorization": f"Bearer {self.config.get('api_key', '')}"},
                json=payload,
                timeout=5
            )
            if r.status_code == 200:
                return r.json().get("input_tokens", 0)
        except Exception:
            pass
        return 0

    async def reload_router(self) -> Tuple[bool, str]:
        if not await self.is_running():
            return False, "llama-server is offline."
        api_base = self.config.get("api_base", "").removesuffix("/v1")
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models?reload=1", timeout=5)
            if r.status_code == 200:
                return True, "Reloaded models and presets in llama-server."
            return False, f"Server returned status {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Failed to reload presets: {e}"

    async def list_presets(self) -> Dict[str, Dict[str, str]]:
        templates_path = self._get_templates_path()
        try:
            return json.loads(templates_path.read_text())
        except Exception:
            return {}

    async def save_preset(self, name: str, settings: Dict[str, str]) -> Tuple[bool, str]:
        templates_path = self._get_templates_path()
        try:
            data = json.loads(templates_path.read_text()) if templates_path.exists() else {}
        except Exception:
            data = {}
        normalized = {self._normalize_key(k): str(v) for k, v in settings.items()}
        data[name] = normalized
        templates_path.write_text(json.dumps(data, indent=2))
        return True, f"Saved preset template '@{name}' with settings: {normalized}"

    async def get_model_info(self, model_name: str = "") -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "provider": self.name,
            "is_running": await self.is_running(),
            "endpoint": self.config.get("api_base", ""),
            "presets_path": str(self._get_presets_path()),
            "models": {}
        }

        # Read preset INI
        preset_file = self._get_presets_path()
        parser = self._read_preset_ini(preset_file)

        global_preset = dict(parser.items("*")) if parser.has_section("*") else {}
        info["global_preset"] = global_preset

        if not await self.is_running():
            return info

        api_base = self.config.get("api_base", "").removesuffix("/v1")
        available = await self.list_available_models()
        loaded = await self.list_loaded_models()

        target_models = [model_name] if model_name and model_name in available else (
            available if not model_name else [model_name]
        )

        # Query static metadata for all models once without triggering VRAM loads
        v1_meta = {}
        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/v1/models", timeout=3)
            if r.status_code == 200:
                for entry in r.json().get("data", []):
                    mid = entry.get("id")
                    if mid and "meta" in entry and entry["meta"]:
                        v1_meta[mid] = entry["meta"]
        except Exception:
            pass

        for m in target_models:
            is_loaded = m in loaded
            m_info: Dict[str, Any] = {
                "loaded": is_loaded,
                "preset": dict(parser.items(m)) if parser.has_section(m) else {}
            }

            # CRITICAL: ONLY query /props if model is already loaded in memory
            # Querying /props on an unloaded model forces llama-server to load it!
            if is_loaded:
                try:
                    encoded = urllib.parse.quote(m)
                    r = await asyncio.to_thread(requests.get, f"{api_base}/props?model={encoded}", timeout=2)
                    if r.status_code == 200:
                        data = r.json()
                        gen = data.get("default_generation_settings", {})
                        m_info["n_ctx"] = gen.get("n_ctx")
                        m_info["params"] = gen.get("params", {})
                        m_info["modalities"] = data.get("modalities", {})
                except Exception:
                    pass

            # Safe static metadata from /v1/models
            if m in v1_meta:
                meta = v1_meta[m]
                if meta.get("n_ctx_train"):
                    m_info["n_ctx_train"] = meta.get("n_ctx_train")
                if meta.get("n_params"):
                    m_info["n_params"] = meta.get("n_params")
                if meta.get("size"):
                    m_info["size_bytes"] = meta.get("size")

            info["models"][m] = m_info

        return info

    async def set_model_config(self, model_name: str, settings: Dict[str, str]) -> Tuple[bool, str]:
        preset_file = self._get_presets_path()
        parser = self._read_preset_ini(preset_file)

        # Expand template if requested
        expanded_settings = {}
        templates = await self.list_presets()
        for k, v in settings.items():
            if str(v).startswith("@") or k.startswith("@"):
                tpl_name = str(v).removeprefix("@") if str(v).startswith("@") else k.removeprefix("@")
                if tpl_name in templates:
                    expanded_settings.update(templates[tpl_name])
                else:
                    return False, f"Template '@{tpl_name}' not found. Check available with 'ask -ap {self.name} -presets'."
            else:
                expanded_settings[self._normalize_key(k)] = str(v)

        target_section = "*" if not model_name or model_name == "*" else model_name
        if not parser.has_section(target_section):
            parser.add_section(target_section)

        for k, v in expanded_settings.items():
            parser.set(target_section, k, str(v))

        self._write_preset_ini(preset_file, parser)

        reload_msg = ""
        if await self.is_running():
            await self.reload_router()
            loaded = await self.list_loaded_models()
            if target_section in loaded:
                await self.load_model(target_section)
                reload_msg = f" (live hot-reloaded '{target_section}' in memory)"

        return True, f"Saved preset for [{target_section}]: {expanded_settings}{reload_msg}"
