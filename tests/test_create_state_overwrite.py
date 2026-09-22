"""create_state must replace an existing dynamic state in place, never refuse,
and must never grow the tool contract."""
import asyncio, unittest
from assets.core.registry import TOOL_REGISTRY
from assets.tools.create_state import create_state_handler

class _FakeAgent:
    def __init__(self):
        self.states = {"dev": {"allowed_tools": ["set_state", "delete_state"]}}
        self.dynamic_states = {}
        self.profile = {"tools": ["run", "read", "set_state", "delete_state", "create_state"]}

def _args(name, **over):
    a = {"name": name, "allowed_tools": ["run", "set_state", "delete_state"],
         "description": "first", "context_providers": {},
         "reasoning": "none", "system_prompt": "PROMPT-V1"}
    a.update(over); return a

class CreateStateOverwrite(unittest.TestCase):
    def test_same_name_twice_replaces_in_place_without_schema_change(self):
        agent = _FakeAgent()
        props_before = sorted(TOOL_REGISTRY["create_state"]["schema"]["function"]["parameters"]["properties"])
        required_before = list(TOOL_REGISTRY["create_state"]["schema"]["function"]["parameters"]["required"])
        first = asyncio.run(create_state_handler(None, agent, _args("worker")))
        self.assertIn("SUCCESS", first)
        v1 = dict(agent.dynamic_states["worker"])
        second = asyncio.run(create_state_handler(None, agent, _args("worker", description="second", system_prompt="PROMPT-V2")))
        self.assertIn("SUCCESS", second)
        self.assertNotIn("already exists", second)
        self.assertEqual(list(agent.dynamic_states), ["worker"])
        self.assertEqual(agent.dynamic_states["worker"]["system_prompt"], "PROMPT-V2")
        self.assertEqual(agent.dynamic_states["worker"]["description"], "second")
        self.assertEqual(v1["system_prompt"], "PROMPT-V1")
        static = asyncio.run(create_state_handler(None, agent, _args("dev")))
        self.assertIn("conflicts with a static state", static)
        self.assertEqual(agent.states["dev"], {"allowed_tools": ["set_state", "delete_state"]})
        props_after = sorted(TOOL_REGISTRY["create_state"]["schema"]["function"]["parameters"]["properties"])
        required_after = list(TOOL_REGISTRY["create_state"]["schema"]["function"]["parameters"]["required"])
        self.assertEqual(props_before, props_after)
        self.assertEqual(required_before, required_after)
        self.assertNotIn("overwrite", [p.lower() for p in props_after])

if __name__ == "__main__":
    unittest.main(verbosity=2)
