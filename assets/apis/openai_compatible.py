import asyncio
import requests
from assets.core.registry import ask_api
from assets.apis.base import BaseApiDriver

@ask_api(name="openai-compatible", description="Generic driver for OpenAI-compatible REST APIs")
class OpenAiCompatibleDriver(BaseApiDriver):

    async def is_running(self) -> bool:
        api_base = self.config.get("api_base", "")
        if not api_base:
            return False
        headers = {}
        if self.config.get("api_key"):
            headers["Authorization"] = f"Bearer {self.config['api_key']}"

        base = api_base.removesuffix("/v1")
        for path in ["/v1/models", "/models", "/health", "/"]:
            try:
                r = await asyncio.to_thread(requests.get, f"{base}{path}", headers=headers, timeout=2)
                if r.status_code in (200, 401, 403):
                    return True
            except Exception:
                pass
        return False

    async def list_available_models(self) -> list[str]:
        api_base = self.config.get("api_base", "")
        headers = {}
        if self.config.get("api_key"):
            headers["Authorization"] = f"Bearer {self.config['api_key']}"

        try:
            r = await asyncio.to_thread(requests.get, f"{api_base}/models", headers=headers, timeout=3)
            if r.status_code == 200:
                data = r.json().get("data", [])
                return [m.get("id") for m in data if m.get("id")]
        except Exception:
            pass

        # Fallback to configured default_model if set
        default_model = self.config.get("default_model")
        return [default_model] if default_model else []

    async def list_loaded_models(self) -> list[str]:
        # By default for static OpenAI endpoints, all listed models are considered available
        return await self.list_available_models()

    async def get_context_limit(self, model_name: str) -> int:
        return self.config.get("max_tokens", 8192)
