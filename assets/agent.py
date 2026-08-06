# agent.py
import json
import time
import copy
import asyncio
import subprocess
from .registry import TOOL_REGISTRY

class Agent:
    async def _resolve_cmd(self, cmd: str) -> str:
        try:
            result = subprocess.check_output(
                cmd, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=10
            )
            return result.strip()
        except Exception as e:
            return f"[cmd_error] {e}"

    async def _resolve_context(self) -> dict:
        self._turn_count += 1
        now = time.time()
        resolved = {}
        all_commands = {**self._raw_commands, **self._state_commands.get(self.state_name, {})}

        async def resolve_one(key, cfg):
            cmd = cfg.get("command", "")
            policy = cfg.get("refresh", "first_turn")
            ttl = cfg.get("cache_ttl", 0)

            # 1. Check cache
            if key in self._context_cache:
                cached = self._context_cache[key]
                if ttl == 0 or now - cached["expires"] < ttl:
                    return key, cached["result"]

            # 2. Check policy
            should_run = False
            if isinstance(policy, str):
                should_run = (policy == "always") or \
                            (policy == "first_turn" and self._turn_count == 1) or \
                            (policy == "state_change" and self._last_state != self.state_name)
            elif isinstance(policy, list):
                should_run = (self.state_name in policy)

            # 3. Execute & cache
            if should_run:
                val = await self._resolve_cmd(cmd)
                self._context_cache[key] = {"result": val, "expires": now}
                return key, val
            return key, self._context_cache.get(key, {}).get("result", "")

        tasks = [resolve_one(k, v) for k, v in all_commands.items()]
        results = await asyncio.gather(*tasks)
        return {k: v for k, v in results}

    def _inject_ids_inline(self, messages):
        """Prepend message IDs inline to each message's content when gc is available.
        This gives the agent direct, unambiguous references to messages by ID.
        """
        if self.state_name not in self.states:
            return messages
        state_cfg = self.states[self.state_name]
        if "gc" not in state_cfg.get("allowed_tools", []):
            return messages

        for m in messages:
             if m.get("gc"):
                 continue
             if m.get("id") and m.get("content"):
                 m["content"] = f"[{m['id']}] {m['content']}"
        return messages

    def __init__(self, ctx, agent_name="ask"):
        from rich.console import Console
        self.ctx = ctx

        agent_file = ctx.base_dir / "agents" / f"{agent_name}.json"
        if not agent_file.exists():
            Console().print(f"[bold yellow]Warning: Agent profile '{agent_name}' not found. Falling back to 'ask'.[/bold yellow]")
            agent_name = "ask"

        self.name = agent_name
        self.state_name = "none" # Default to 'none' for a fresh initialization
        self._last_state = None
        self._turn_count = 0
        self._context_cache = {}

        with open(ctx.base_dir / "agents" / f"{agent_name}.json") as f:
            self.profile = json.load(f)
        with open(ctx.base_dir / "states" / agent_name / "states.json") as f:
            self.states = json.load(f)

        self.context = {}
        if self.ctx.active_routine:
            self.context["active_routine"] = self.ctx.active_routine

        self._raw_commands = self.profile.get("context_commands", {})
        self._state_commands = {
            name: cfg.get("context_commands", {})
            for name, cfg in self.states.items()
        }

    async def get_api_payload(self, messages, fresh_ctx, interactive=False):
        def _apply_templates(target, ctx_data):
            if isinstance(target, dict):
                return {k: (_apply_templates(v, ctx_data) if isinstance(v, (dict, list)) else
                           str(v).format_map(ctx_data) if isinstance(v, str) else v)
                        for k, v in target.items()}
            elif isinstance(target, list):
                return [_apply_templates(i, ctx_data) for i in target]
            return target

        # If uninitialized, strictly limit tools to 'set_state'
        if self.state_name not in self.states:
            tools_whitelist = ["set_state"]
            state_prompt = "You are currently uninitialized (state: 'none')."
            temperature = 0.1
            reasoning_budget = 0
        else:
            templated_state = _apply_templates(self.states[self.state_name], fresh_ctx)
            state_tools = templated_state.get("allowed_tools", [])
            agent_whitelist = self.profile.get("tools", [])
            # Intersect state tools and agent profile tools
            tools_whitelist = [t for t in state_tools if t in agent_whitelist]
            state_prompt = templated_state.get("system_prompt", "")
            temperature = templated_state.get("temperature", 0.1)
            reasoning_budget = templated_state.get("reasoning_budget", 0)

        # Inject instructions into the system message dynamically
        system_msg_index = next((i for i, m in enumerate(messages) if m["role"] == "system"), None)
        if system_msg_index is not None:
            # Format map first for OS info
            base_content = messages[system_msg_index]["content"].format_map(fresh_ctx)
            clean_base = base_content.split("### STATE ARCHITECTURE")[0].strip()

            # ONLY inject the tool glossary if interactive mode is ON
            if interactive:
                # 1. Build a dynamic map of all states
                state_directory = []
                for s_name, s_cfg in self.states.items():
                    s_tools = [t for t in s_cfg.get("allowed_tools", []) if t in self.profile.get("tools", [])]
                    s_desc = s_cfg.get("description", "No description provided.")
                    state_directory.append(f"  - {s_name.upper()}: {s_tools}\n    Purpose: {s_desc}")
                state_directory_str = "\n".join(state_directory)

                # 2. Build a Tool Glossary so it knows what all tools do
                tool_glossary = []
                for t_name in self.profile.get("tools", []):
                    if t_name in TOOL_REGISTRY:
                        t_desc = TOOL_REGISTRY[t_name]["schema"]["function"]["description"]
                        tool_glossary.append(f"  - {t_name}: {t_desc}")
                tool_glossary_str = "\n".join(tool_glossary)

                instructions = (f"\n\n### STATE ARCHITECTURE & CAPABILITIES ###\n"
                                f"You operate using distinct compute states. You must use the 'set_state' tool to switch between them to access different tools.\n"
                                f"{state_directory_str}\n\n"
                                f"### TOOL GLOSSARY ###\n"
                                f"{tool_glossary_str}\n\n"
                                f"[CURRENT COMPUTE STATE: {self.state_name.upper()}]\n"
                                f"Tools currently available to you: {tools_whitelist}\n"
                                f"State Instructions: {state_prompt}")

                messages[system_msg_index]["content"] = clean_base + "\n" + instructions
            else:
                # If non-interactive, leave tools out of the prompt entirely
                messages[system_msg_index]["content"] = clean_base

        tools = []
        if interactive:
            for name, entry in TOOL_REGISTRY.items():
                if name in tools_whitelist:
                    # Deep copy the schema so we don't pollute the global registry
                    schema = copy.deepcopy(entry["schema"])

                    # DYNAMIC OVERRIDE: Inject this agent's specific states into the set_state tool
                    if name == "set_state":
                        available_states = list(self.states.keys())
                        schema["function"]["description"] = f"Change compute state. Available states: {', '.join(available_states)}"
                        schema["function"]["parameters"]["properties"]["state"]["enum"] = available_states

                    tools.append(schema)

        # Inject IDs inline into messages (for gc tool)
        messages = self._inject_ids_inline(messages)

        # Assemble the payload cleanly without injecting empty fields
        payload = {
            "messages": messages,
            "temperature": temperature,
            "reasoning_budget": reasoning_budget,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return payload

    def transition_to(self, new_state: str):
        if new_state in self.states:
            self._last_state = self.state_name
            self.state_name = new_state
            return True
        return False
