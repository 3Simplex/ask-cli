"""Model metadata resolution via declarative profiles and file inspection."""

import os
import re
import json
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GenerationSpec:
    """Driver-agnostic description of a single completion request."""
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 1024
    thinking_enabled: bool = False
    supports_thinking: bool = False
    reasoning_effort: str = "none"
    template_kwargs: Dict[str, Any] = field(default_factory=dict)
    presence_penalty: Optional[float] = None


class ModelResolver:
    """Loads declarative model profiles from assets/models/ and resolves generation specs."""

    @staticmethod
    def _get_profiles_dir() -> Path:
        if path := os.environ.get("ASK_ASSETS_DIR"):
            return Path(path) / "models"
        return Path(__file__).parent.parent / "models"

    @classmethod
    def load_profiles(cls) -> List[Dict[str, Any]]:
        """Load all declarative profiles from assets/models/."""
        profiles = []
        p_dir = cls._get_profiles_dir()
        if p_dir.exists():
            for f in sorted(p_dir.glob("*.json")):
                try:
                    profiles.append(json.loads(f.read_text()))
                except Exception:
                    pass
        return profiles

    @classmethod
    def get_profile(cls, model_name: str) -> Dict[str, Any]:
        """Match a model name against profile patterns, falling back to default.json."""
        profiles = cls.load_profiles()
        model_clean = (model_name or "").lower()

        # 1. Match specific profiles first
        for prof in profiles:
            if prof.get("name") == "default":
                continue
            for pattern in prof.get("match", []):
                if fnmatch.fnmatch(model_clean, pattern.lower()):
                    return prof

        # 2. Fallback to default profile
        for prof in profiles:
            if prof.get("name") == "default":
                return prof

        # 3. Hardcoded fallback if no profiles exist
        return {
            "name": "fallback",
            "supports_thinking": False,
            "options": {"reasoning": ["none"]},
            "sampling": {"default": {"temperature": 0.2, "top_p": 0.9}}
        }

    @staticmethod
    def default_metadata() -> Dict[str, Any]:
        """Baseline metadata used when a model dir / server reports nothing."""
        return {
            "context_length": 8192,
            "supports_thinking": False,
            "thinking_kwargs": [],
            "reasoning_effort_levels": [],
        }

    @staticmethod
    def merge_server_metadata(base_meta: Dict[str, Any], props: Optional[Dict[str, Any]] = None,
                              n_ctx: Optional[int] = None, n_ctx_train: Optional[int] = None
                              ) -> Dict[str, Any]:
        """Fold server-reported context info into metadata (PURE, no I/O)."""
        merged = dict(base_meta)
        merged.setdefault("thinking_kwargs", [])
        merged.setdefault("reasoning_effort_levels", [])
        if props:
            gen = props.get("default_generation_settings", props)
            if isinstance(gen, dict):
                n_ctx = n_ctx or gen.get("n_ctx")
        for candidate in (n_ctx, n_ctx_train):
            try:
                if candidate and int(candidate) > 0:
                    merged["context_length"] = int(candidate)
                    break
            except (TypeError, ValueError):
                continue
        return merged

    @staticmethod
    def inspect(model_dir: Path) -> Dict[str, Any]:
        """Extract parameters from on-disk model files if present."""
        model_dir = Path(model_dir)
        result = {
            "context_length": 8192,
            "supports_thinking": False,
            "thinking_kwargs": [],
            "reasoning_effort_levels": []
        }

        cfg_path = model_dir / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                result["context_length"] = cfg.get("max_position_embeddings") or cfg.get("context_length", 8192)
            except Exception:
                pass

        tmpl = ""
        tok_path = model_dir / "tokenizer_config.json"
        if tok_path.exists():
            try:
                tok = json.loads(tok_path.read_text())
                tmpl = tok.get("chat_template", "")
            except Exception:
                pass
        jinja_path = model_dir / "chat_template.jinja"
        if jinja_path.exists():
            try:
                tmpl = jinja_path.read_text()
            except Exception:
                pass

        if tmpl:
            if "<think>" in tmpl or "enable_thinking" in tmpl or "reasoning_effort" in tmpl:
                result["supports_thinking"] = True
            if "enable_thinking" in tmpl:
                result["thinking_kwargs"].append("enable_thinking")
            if "preserve_thinking" in tmpl:
                result["thinking_kwargs"].append("preserve_thinking")

            efforts = set(re.findall(r'''reasoning_effort\s*==\s*['"]([^'"]+)['"]''', tmpl))
            result["reasoning_effort_levels"] = sorted(list(efforts))

        return result

    @classmethod
    def resolve(
        cls,
        model_target: Any,
        reasoning_intent: Optional[str] = None,
        remaining_tokens: int = 2048,
        safety_buffer: int = 1000,
        model_meta: Optional[Dict[str, Any]] = None,
    ) -> GenerationSpec:
        """Resolve a model profile and cognitive intent into a GenerationSpec."""
        if isinstance(model_target, dict):
            meta = model_target
            model_name = str(meta.get("model", "") or "")
        else:
            model_name = str(model_target or "")
            meta = model_meta or {}

        profile = cls.get_profile(model_name)
        intent = reasoning_intent or "none"
        max_tokens = max(256, int(remaining_tokens) - int(safety_buffer))

        supports_thinking = bool(profile.get("supports_thinking", False) or meta.get("supports_thinking", False))
        thinking_enabled = supports_thinking and (intent != "none")

        sampling = profile.get("sampling", {})
        template_kwargs = {}
        reasoning_effort = "none"
        presence_penalty = None

        levels = meta.get("reasoning_effort_levels") or profile.get("options", {}).get("reasoning", [])
        supported_kwargs = meta.get("thinking_kwargs") or list(profile.get("thinking_kwargs", {}).get("enable", {}).keys())

        if thinking_enabled:
            s_cfg = sampling.get("thinking", {"temperature": 1.0, "top_p": 0.95})
            if profile.get("thinking_kwargs", {}).get("enable"):
                template_kwargs = dict(profile["thinking_kwargs"]["enable"])
            else:
                template_kwargs = {}
                if "enable_thinking" in supported_kwargs:
                    template_kwargs["enable_thinking"] = True
                if "preserve_thinking" in supported_kwargs:
                    template_kwargs["preserve_thinking"] = True

            if profile.get("effort_map") and intent in profile["effort_map"]:
                reasoning_effort = profile["effort_map"][intent]
            elif intent == "high" and "xhigh" in levels:
                reasoning_effort = "xhigh"
            elif intent in levels:
                reasoning_effort = intent
            elif "medium" in levels:
                reasoning_effort = "medium"
            else:
                reasoning_effort = "low"
        else:
            s_cfg = sampling.get("none", sampling.get("default", {"temperature": 0.7, "top_p": 0.8}))
            if supports_thinking:
                if profile.get("thinking_kwargs", {}).get("disable"):
                    template_kwargs = dict(profile["thinking_kwargs"]["disable"])
                elif "enable_thinking" in supported_kwargs or supports_thinking:
                    template_kwargs = {"enable_thinking": False}
            presence_penalty = s_cfg.get("presence_penalty")

        return GenerationSpec(
            temperature=s_cfg.get("temperature", 0.7),
            top_p=s_cfg.get("top_p", 0.95),
            max_tokens=max_tokens,
            thinking_enabled=thinking_enabled,
            supports_thinking=supports_thinking,
            reasoning_effort=reasoning_effort,
            template_kwargs=template_kwargs,
            presence_penalty=presence_penalty,
        )
