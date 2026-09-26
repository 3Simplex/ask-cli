"""Invocation-time whitelist gate.

Contract: a tool call whose name is not in the ACTIVE STATE's effective
whitelist must not reach its handler, regardless of what the model knows
or emits. This is a cheap deterministic gate at the dispatch funnel -- it
is deliberately NOT an evaluator (live evaluators cost API calls; a future
LLM tool guard may sit behind this gate, never replace it).

OFFLINE. The dispatch funnel is exercised directly via ask._run_tool with
a sentinel handler installed into the real TOOL_REGISTRY and torn down.
"""
import asyncio
import json
import unittest

import ask
from assets.agent import Agent
from assets.core.registry import TOOL_REGISTRY

GATE_PROBE = "_gate_probe"
FIRED_TOKEN = "TOOL_FIRED"
DEV_TOOLS = ["run", "read", "set_state", "search", "create_state", "delete_state", "gc"]

FIRED = False


async def _probe_handler(ctx, agent, args, internal_msgs=None):
    global FIRED
    FIRED = True
    return FIRED_TOKEN


def _install(name):
    TOOL_REGISTRY[name] = {
        "handler": _probe_handler,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": "gate sentinel",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    }


def _stub_agent(states, dynamic, state_name, profile_tools=None):
    a = Agent.__new__(Agent)
    a.states = states
    a.dynamic_states = dynamic
    a.state_name = state_name
    a.profile = {"tools": DEV_TOOLS if profile_tools is None else list(profile_tools)}
    return a


def _tc(name):
    return {"id": "call_gate_1", "function": {"name": name, "arguments": json.dumps({"probe": 1})}}


def _dispatch(agent, name):
    return asyncio.run(ask._run_tool(_tc(name), None, agent, []))


class T1IsToolAllowedContract(unittest.TestCase):
    """The Agent-side single source of truth for the effective whitelist."""

    def test_uninitialized_allows_only_set_state(self):
        a = _stub_agent({}, {}, "none")
        self.assertTrue(a.is_tool_allowed("set_state"))
        for name in DEV_TOOLS:
            if name == "set_state":
                continue
            self.assertFalse(a.is_tool_allowed(name), f"{name} must be denied while uninitialized")
        self.assertFalse(a.is_tool_allowed("run"))

    def test_declared_and_profiled_is_allowed(self):
        a = _stub_agent({"gate_static": {"allowed_tools": ["run"]}}, {}, "gate_static")
        self.assertTrue(a.is_tool_allowed("run"))

    def test_declared_but_not_profiled_is_denied(self):
        a = _stub_agent({"gate_static": {"allowed_tools": [GATE_PROBE]}}, {}, "gate_static")
        self.assertFalse(a.is_tool_allowed(GATE_PROBE))

    def test_profiled_but_not_declared_is_denied(self):
        a = _stub_agent({"gate_static": {"allowed_tools": ["set_state"]}}, {}, "gate_static")
        self.assertFalse(a.is_tool_allowed("run"))

    def test_dynamic_state_shadows_static(self):
        a = _stub_agent(
            {"gate_dup": {"allowed_tools": ["run"]}},
            {"gate_dup": {"allowed_tools": ["read"]}},
            "gate_dup",
        )
        self.assertTrue(a.is_tool_allowed("read"))
        self.assertFalse(a.is_tool_allowed("run"))

    def test_unknown_state_denies_all_but_set_state_escape(self):
        # A bogus state name is the recovery posture get_api_payload already
        # implements (tools_whitelist = ["set_state"]): every real tool is
        # denied, but the one transition tool stays available so a session whose
        # persisted state no longer exists can climb out instead of bricking.
        a = _stub_agent({"gate_static": {"allowed_tools": ["run"]}}, {}, "nowhere")
        self.assertFalse(a.is_tool_allowed("run"))
        self.assertFalse(a.is_tool_allowed("read"))
        self.assertFalse(a.is_tool_allowed(GATE_PROBE))
        self.assertTrue(a.is_tool_allowed("set_state"))

    def test_empty_allowed_tools_denies_all(self):
        a = _stub_agent({"gate_static": {"allowed_tools": []}}, {}, "gate_static")
        self.assertFalse(a.is_tool_allowed("run"))
        self.assertFalse(a.is_tool_allowed("set_state"))


class T2DispatchGate(unittest.TestCase):
    """The funnel itself: non-whitelisted must never reach the handler."""

    def setUp(self):
        global FIRED
        FIRED = False
        self._saved = {}

    def tearDown(self):
        for name, entry in self._saved.items():
            if entry is None:
                TOOL_REGISTRY.pop(name, None)
            else:
                TOOL_REGISTRY[name] = entry
        self._saved = {}
        FIRED = False

    def _save(self, name):
        self._saved.setdefault(name, TOOL_REGISTRY.get(name))

    def test_denied_registered_tool_does_not_fire(self):
        self._save(GATE_PROBE)
        _install(GATE_PROBE)
        agent = _stub_agent({"gate_static": {"allowed_tools": ["set_state"]}}, {}, "gate_static")

        env = _dispatch(agent, GATE_PROBE)

        self.assertEqual(env["role"], "tool")
        self.assertEqual(env["tool_call_id"], "call_gate_1")
        self.assertFalse(FIRED, "sentinel handler ran: whitelist was not enforced at dispatch")
        content = env["content"]
        self.assertFalse(content.startswith("Unknown tool"),
                         "deny must not be laundered into the registry-membership branch")
        self.assertFalse(content.startswith("Tool Execution Error"),
                         "deny must not be laundered into the try/except branch")
        self.assertIn("not permitted", content)
        self.assertIn("gate_static", content)

    def test_whitelisted_tool_fires(self):
        self._save(GATE_PROBE)
        _install(GATE_PROBE)
        agent = _stub_agent(
            {"gate_allow": {"allowed_tools": [GATE_PROBE]}}, {}, "gate_allow",
            profile_tools=DEV_TOOLS + [GATE_PROBE],
        )

        env = _dispatch(agent, GATE_PROBE)

        self.assertTrue(FIRED, "whitelisted sentinel must reach its handler")
        self.assertIn(FIRED_TOKEN, env["content"])

    def test_unknown_tool_still_reports_unknown(self):
        env = _dispatch(_stub_agent({"gate_static": {"allowed_tools": []}}, {}, "gate_static"),
                        "no_such_tool_xyz")
        self.assertFalse(FIRED)
        self.assertTrue(env["content"].startswith("Unknown tool"),
                        "registry-membership precedence must be retained")

    def test_profile_tool_outside_state_whitelist_does_not_fire(self):
        self._save("read")
        _install("read")
        agent = _stub_agent({"gate_edit": {"allowed_tools": ["set_state"]}}, {}, "gate_edit")

        env = _dispatch(agent, "read")

        self.assertFalse(FIRED, "profile membership must not override the state whitelist")
        self.assertIn("not permitted", env["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
