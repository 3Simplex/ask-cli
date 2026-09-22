"""
PRODUCTION VALIDATION GATE  (tests/test_regressions.py)
======================================================
The gate the owner did NOT have — the reason the model-agnostic refactor
shipped with the security evaluator silently broken.

Unlike the concept prototype (test_model_harness.py, which only proves the
branch idea and is disposable), this is a REGRESSION gate: it drives the REAL
evaluator seam end-to-end so any future change that breaks it goes RED before
merge.

Deliberately OFFLINE and FAST:
  * the real ModelResolver.resolve() is executed (so a resolve() seam break is
    caught for real — this is exactly what A1 was),
  * ONLY the network edge (requests.post) is stubbed, with a canned response
    that flows through the real boolean/JSON parser, so we can assert a
    legitimate verdict actually lands as PASS — not merely that the call
    survived. The stub cannot mask A1, because A1 raises before requests.post
    is ever reached.

Run from the repo root with the build interpreter:
    PY=$(ls -d /nix/store/*-python3-3.13.12-env/bin/python3 | head -1)
    PYTHONPATH="$PWD" "$PY" -m unittest discover -s tests -p 'test_*.py'
"""
import asyncio
import importlib
import json
import pkgutil
import tempfile
import unittest
from pathlib import Path

import requests  # patched per-test; eval_runner looks up requests.post at call time

from assets.core.registry import EVAL_REGISTRY, EvalResult
from assets.core.eval_runner import dispatch_evaluator


def _load_evaluators():
    """Mirror ask.py's _load_evaluator_modules so @ask_evaluator decorators fire.
    assets/evaluators/__init__.py is empty — nothing registers without this."""
    eval_dir = Path(__file__).resolve().parent.parent / "assets" / "evaluators"
    for _, module_name, _ in pkgutil.iter_modules([str(eval_dir)]):
        importlib.import_module(f"assets.evaluators.{module_name}")


class _FakeResponse:
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): return None
    def json(self): return self._payload


class _FakeCtx:
    """Minimal stand-in for the harness ctx, enough for dispatch_evaluator +
    llm_eval_call. driver=None forces the else-branch payload path, which reads
    spec.* and therefore only runs if resolve() truly succeeded."""
    def __init__(self, model):
        self.config = {"model": model, "api_base": "http://localhost:1/v1", "api_key": ""}
        tmp = tempfile.mkdtemp()
        self.audit_dir = Path(tmp)
        self.data_dir = Path(tmp)
        self.driver = None


def _stub_llm(passed: bool):
    body = json.dumps({"passed": passed, "reasoning": "stubbed verdict"})
    def _post(url, **kwargs):
        return _FakeResponse({"choices": [{"message": {"content": body}}]})
    return _post


class EvaluatorSeamGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _load_evaluators()

    def setUp(self):
        self._orig_post = requests.post

    def tearDown(self):
        requests.post = self._orig_post

    def _run(self, evaluator, input_data, model="qwen3-test", passed=True):
        self.assertIn(evaluator, EVAL_REGISTRY,
                      f"{evaluator} evaluator failed to register")
        requests.post = _stub_llm(passed)
        ctx = _FakeCtx(model)
        return asyncio.run(dispatch_evaluator(ctx, evaluator, input_data))

    # ---- ASSERTION 1: the seam must not launder a crash into 'Evaluator error' ----
    def test_security_watcher_reaches_verdict_not_dispatch_crash(self):
        result = self._run("security_watcher", {"command": "ls -la /"})
        self.assertNotIn(
            "Evaluator error", result.reasoning,
            "security_watcher crashed inside dispatch_evaluator and was laundered "
            "into an 'Evaluator error'. The safety gate is effectively dead.")
        # requests.post is stubbed to PASS, so a healthy seam yields PASS:
        self.assertTrue(result.passed,
                        f"expected a real PASS verdict, got: {result.status} / {result.reasoning}")

    # ---- ASSERTION 2: a legitimate state transition must genuinely PASS ----
    def test_state_guard_legitimate_transition_passes(self):
        result = self._run("state_guard", {"state": "code_review"})
        self.assertNotIn(
            "Evaluator error", result.reasoning,
            "state_guard crashed inside dispatch_evaluator; every state transition "
            "would be hard-blocked with a laundered error.")
        self.assertTrue(result.passed,
                        f"legitimate transition must PASS, got: {result.status} / {result.reasoning}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
