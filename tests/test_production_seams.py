"""
PRODUCTION SEAM VALIDATION GATE (tests/test_production_seams.py)
================================================================
End-to-end offline integration gates for the core agent harness seams:
  1. The Agent Turn-Loop Seam: Verifies that agent._resolve_context() and
     agent.get_api_payload() execute cleanly across state transitions,
     including dynamic states created with malformed/empty provider arguments.
  2. The Wire Dialect Seam: Verifies that GenerationSpec serializes through
     actual driver instances (OpenAI strict vs Router dialects) without
     AttributeErrors or contract leaks.
  3. The Declarative Profile Seam: Verifies capability resolution against
     real profile files in assets/models/.

Fast and completely OFFLINE (no live servers or network calls).
"""

import asyncio
import os
import unittest
from pathlib import Path

from assets.agent import Agent
from assets.core.models import ModelResolver
from assets.tools.create_state import create_state_handler
from assets.apis.openai_compatible import OpenAiCompatibleDriver
from assets.apis.routers.freetoken import FreeTokenDriver
from assets.apis.routers.llama_cpp import LlamaCppDriver


class _FakeCtx:
    """Minimal runtime harness context providing real asset resolution."""
    def __init__(self, model="oakmindai_Qwen3.8-Flash-Next"):
        self.base_dir = Path(__file__).resolve().parent.parent / "assets"
        self.config = {
            "model": model,
            "api_base": "http://localhost:8000/v1",
            "api_key": "",
            "timeout": 120000,
        }
        self.active_routine = None
        self.current_tokens = 500
        self.max_tokens = 81920
        self.driver = None

    def get_token_budget(self, max_tokens=None):
        return 40000


class ProductionSeamGates(unittest.TestCase):

    def setUp(self):
        # Force working-tree profile directory so checkout tests are immune to store shadowing
        self._orig_assets_dir = os.environ.get("ASK_ASSETS_DIR")
        os.environ["ASK_ASSETS_DIR"] = str(Path(__file__).resolve().parent.parent / "assets")

    def tearDown(self):
        if self._orig_assets_dir is not None:
            os.environ["ASK_ASSETS_DIR"] = self._orig_assets_dir
        else:
            os.environ.pop("ASK_ASSETS_DIR", None)

    # =========================================================================
    # SEAM 1: Turn-Loop & Dynamic Context Seam
    # =========================================================================
    def test_dynamic_state_with_string_context_providers_does_not_crash(self):
        """Regression Gate: Models often emit 'context_providers': '' when told

        a state has no providers. Verifies this edge case does not crash
        _resolve_context() with TypeError: 'str' object is not a mapping.
        """
        ctx = _FakeCtx()
        agent = Agent(ctx, "dev")

        # Simulate the exact LLM argument payload that bricked the session
        args = {
            "name": "scrub_seam_test",
            "allowed_tools": ["set_state", "gc"],
            "description": "context cleanup replacement",
            "context_providers": "",  # String instead of dict
            "reasoning": "high",
            "system_prompt": "Clean stale context."
        }

        # 1. State creation
        create_res = asyncio.run(create_state_handler(ctx, agent, args))
        self.assertIn("SUCCESS", create_res)

        # 2. State transition
        ok, msg = asyncio.run(agent.transition_to("scrub_seam_test"))
        self.assertTrue(ok, f"Transition failed: {msg}")

        # 3. Context resolution (CRITICAL SEAM: must not raise TypeError)
        try:
            fresh_ctx = asyncio.run(agent._resolve_context())
        except TypeError as exc:
            self.fail(f"Production turn-loop broke: agent._resolve_context() crashed on malformed providers: {exc}")

        self.assertIsInstance(fresh_ctx, dict)
        self.assertIn("current_tokens", fresh_ctx)

        # 4. API Payload assembly
        payload = asyncio.run(agent.get_api_payload(
            messages=[
                {"id": "sys", "role": "system", "content": "You are dev."},
                {"id": "usr_1", "role": "user", "content": "Run scrub."}
            ],
            fresh_ctx=fresh_ctx,
            interactive=True
        ))
        self.assertIn("messages", payload)
        self.assertIn("tools", payload)
        self.assertEqual(payload["model"], ctx.config["model"])

    # =========================================================================
    # SEAM 2: Wire Dialect & Driver Serialization Seam
    # =========================================================================
    def test_wire_payload_serialization_strict_vs_routers(self):
        """Verifies driver.format_completion_payload() end-to-end.

        Strict OpenAI drivers MUST NOT leak router-specific keys.
        Router drivers MUST forward thinking kwargs and reasoning efforts.
        """
        ctx = _FakeCtx("oakmindai_Qwen3.8-Flash-Next")
        agent = Agent(ctx, "ask")
        fresh_ctx = asyncio.run(agent._resolve_context())

        # Test A: Router Driver (FreeToken)
        ctx.driver = FreeTokenDriver("freetoken", ctx.config, ctx=ctx)
        payload_ft = asyncio.run(agent.get_api_payload(
            messages=[{"id": "usr_1", "role": "user", "content": "hello"}],
            fresh_ctx=fresh_ctx,
            interactive=False
        ))
        self.assertIn("messages", payload_ft)
        self.assertIn("temperature", payload_ft)
        self.assertIn("max_tokens", payload_ft)

        # Test B: Strict OpenAI-Compatible Driver
        ctx.driver = OpenAiCompatibleDriver("openai-compatible", ctx.config, ctx=ctx)
        payload_strict = asyncio.run(agent.get_api_payload(
            messages=[{"id": "usr_1", "role": "user", "content": "hello"}],
            fresh_ctx=fresh_ctx,
            interactive=False
        ))
        self.assertNotIn("chat_template_kwargs", payload_strict)
        self.assertNotIn("reasoning_effort", payload_strict)
        self.assertNotIn("reasoning_budget", payload_strict)
        self.assertNotIn("presence_penalty", payload_strict)

        # Test C: Llama.cpp Router Driver
        ctx.driver = LlamaCppDriver("llama-cpp", ctx.config, ctx=ctx)
        payload_llama = asyncio.run(agent.get_api_payload(
            messages=[{"id": "usr_1", "role": "user", "content": "hello"}],
            fresh_ctx=fresh_ctx,
            interactive=False
        ))
        self.assertIn("messages", payload_llama)

    # =========================================================================
    # SEAM 3: Declarative Model Profile Resolution Seam
    # =========================================================================
    def test_declarative_profiles_end_to_end(self):
        """Ensures ModelResolver resolves specs from declarative profiles

        without hardcoded sniffers or crashing on unprofiled models.
        """
        # 1. Qwen thinking intent -> high effort
        spec_qwen = ModelResolver.resolve("oakmindai_Qwen3.8-Flash-Next", reasoning_intent="high")
        self.assertTrue(spec_qwen.supports_thinking)
        self.assertTrue(spec_qwen.thinking_enabled)
        self.assertEqual(spec_qwen.reasoning_effort, "xhigh")
        self.assertTrue(spec_qwen.template_kwargs.get("enable_thinking"))

        # 2. Qwen reflex intent -> presence penalty, thinking disabled
        spec_reflex = ModelResolver.resolve("oakmindai_Qwen3.8-Flash-Next", reasoning_intent="none")
        self.assertFalse(spec_reflex.thinking_enabled)
        self.assertEqual(spec_reflex.presence_penalty, 1.5)
        self.assertFalse(spec_reflex.template_kwargs.get("enable_thinking"))

        # 3. DeepSeek-R1 profile -> correctly loaded and mapped
        spec_ds = ModelResolver.resolve("deepseek-r1-70b", reasoning_intent="high")
        self.assertTrue(spec_ds.supports_thinking)
        self.assertTrue(spec_ds.thinking_enabled)
        self.assertEqual(spec_ds.reasoning_effort, "xhigh")

        # 4. Unknown model fallback -> default.json, thinking disabled
        spec_unknown = ModelResolver.resolve("unknown-custom-model", reasoning_intent="high")
        self.assertFalse(spec_unknown.supports_thinking)
        self.assertFalse(spec_unknown.thinking_enabled)
        self.assertEqual(spec_unknown.reasoning_effort, "none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
