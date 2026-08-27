# agent.py
import json
import time
import copy
import asyncio
import subprocess
from .core.registry import TOOL_REGISTRY

class Agent:
    async def _resolve_cmd(self, cmd: str) -> str:
        if not cmd: return ""
        try:
            result = await asyncio.to_thread(
                subprocess.check_output,
                cmd, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=10
            )
            return result.strip()
        except Exception as e:
            return f"[cmd_error] {e}"

    async def _resolve_api(self, cfg: dict) -> str:
        import requests
        url = cfg.get("url", cfg.get("endpoint", ""))
        if not url: return ""

        # If it's a relative path, assume it's for the local LLM server
        if url.startswith("/"):
            # Strip /v1 if present so we can hit root endpoints like /props
            base_url = self.ctx.config.get("api_base", "").removesuffix("/v1")
            url = base_url + url

        method = cfg.get("method", "GET").upper()
        headers = cfg.get("headers", {})
        payload = cfg.get("payload")
        extract = cfg.get("extract", "")

        try:
            r = await asyncio.to_thread(
                requests.request, method, url, headers=headers, json=payload, timeout=5
            )
            r.raise_for_status()
            data = r.json()

            # Simple JSON path extractor (e.g., "data[0].id" or "default_generation_settings.n_ctx")
            if extract:
                parts = extract.replace('[', '.').replace(']', '').split('.')
                for part in parts:
                    if not part: continue
                    if isinstance(data, dict):
                        data = data.get(part)
                    elif isinstance(data, list):
                        try: data = data[int(part)]
                        except (ValueError, IndexError): return ""
                    else:
                        return ""

            return str(data) if data is not None else ""
        except Exception as e:
            return f"[api_error] {e}"

    async def _resolve_context(self) -> dict:
        self._turn_count += 1
        now = time.time()
        resolved = {}

        # Merge both old 'context_commands' and new 'context_providers'
        all_providers = {**self._raw_commands, **self._state_commands.get(self.state_name, {})}

        async def resolve_one(key, cfg):
            # Default to 'shell' if not specified for backward compatibility
            ptype = cfg.get("type", "shell")
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
                if ptype == "shell":
                    val = await self._resolve_cmd(cfg.get("command", ""))
                elif ptype == "api":
                    val = await self._resolve_api(cfg)
                else:
                    val = f"[error] unknown provider type: {ptype}"

                self._context_cache[key] = {"result": val, "expires": now}
                return key, val
            return key, self._context_cache.get(key, {}).get("result", "")

        tasks = [resolve_one(k, v) for k, v in all_providers.items()]
        results = await asyncio.gather(*tasks)

        # Build the final dict and inject in-memory runtime variables
        final_context = {k: v for k, v in results}
        final_context["current_tokens"] = str(getattr(self.ctx, "current_tokens", 0))
        final_context["max_context"] = str(getattr(self.ctx, "max_tokens", 8192))
        final_context["current_model"] = str(self.ctx.config.get("model", "unknown"))

        return final_context

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

        self._raw_commands = self.profile.get("context_providers", self.profile.get("context_commands", {}))
        self._state_commands = {
            name: cfg.get("context_providers", cfg.get("context_commands", {}))
            for name, cfg in self.states.items()
        }

        # Dynamic states: created at runtime by the agent
        self.dynamic_states = {}

    async def get_api_payload(self, messages, fresh_ctx, interactive=False):
        # 1. Deepcopy so we don't pollute internal_msgs permanently
        messages = copy.deepcopy(messages)

        def _apply_templates(target, ctx_data):
            if isinstance(target, dict):
                return {k: (_apply_templates(v, ctx_data) if isinstance(v, (dict, list)) else
                           str(v).format_map(ctx_data) if isinstance(v, str) else v)
                        for k, v in target.items()}
            elif isinstance(target, list):
                return [_apply_templates(i, ctx_data) for i in target]
            return target

        # If uninitialized, strictly limit tools to 'set_state'
        if self.state_name not in self.states and self.state_name not in self.dynamic_states:
            tools_whitelist = ["set_state"]
            state_prompt = "You are currently uninitialized (state: 'none')."
            temperature = 0.1
            reasoning_budget = 0
        else:
            # Check dynamic states first
            if self.state_name in self.dynamic_states:
                templated_state = _apply_templates(self.dynamic_states[self.state_name], fresh_ctx)
                state_tools = templated_state.get("allowed_tools", [])
                agent_whitelist = self.profile.get("tools", [])
                # Intersect state tools and agent profile tools
                tools_whitelist = [t for t in state_tools if t in agent_whitelist]
                state_prompt = templated_state.get("system_prompt", "")
                temperature = templated_state.get("temperature", 0.1)
                reasoning_budget = templated_state.get("reasoning_budget", 0)
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
            # 2. Strip previous instructions BEFORE format_map to avoid KeyErrors from injected code/JSON
            raw_content = messages[system_msg_index]["content"]
            clean_base_raw = raw_content.split("### STATE ARCHITECTURE")[0].strip()

            # 3. Format map safely on the clean template
            class SafeDict(dict):
                def __missing__(self, key):
                    return '{' + key + '}'
            clean_base = clean_base_raw.format_map(SafeDict(fresh_ctx))

            # ONLY inject the tool glossary if interactive mode is ON
            if interactive:
                # 1. Build a dynamic map of all states (static + dynamic)
                state_directory = []
                for s_name, s_cfg in self.states.items():
                    s_tools = [t for t in s_cfg.get("allowed_tools", []) if t in self.profile.get("tools", [])]
                    s_desc = s_cfg.get("description", "No description provided.")
                    state_directory.append(f"  - {s_name.upper()}: {s_tools}\n    Purpose: {s_desc}")

                # Dynamic states
                for s_name, s_cfg in self.dynamic_states.items():
                    s_tools = [t for t in s_cfg.get("allowed_tools", []) if t in self.profile.get("tools", [])]
                    s_desc = s_cfg.get("description", "No description provided.")
                    state_directory.append(f"  - {s_name.upper()} (DYNAMIC): {s_tools}\n    Purpose: {s_desc}")

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
                        available_states = list(self.states.keys()) + list(self.dynamic_states.keys())
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

    async def transition_to(self, new_state: str, internal_msgs=None) -> tuple[bool, str]:
        # Check dynamic states first
        if new_state in self.dynamic_states:
            state_cfg = self.dynamic_states[new_state]
            # Check for evaluator guards in dynamic states
            evaluators = state_cfg.get("evaluators", [])

            if evaluators:
                from assets.core.eval_runner import dispatch_evaluator
                for eval_name in evaluators:
                    result = await dispatch_evaluator(self.ctx, eval_name, {"state": new_state}, self, internal_msgs)
                    if not result.passed:
                        return False, f"Blocked by {eval_name}: {result.reasoning}"

            self._last_state = self.state_name
            self.state_name = new_state
            return True, "OK"

        # Check static states
        if new_state in self.states:
            state_cfg = self.states[new_state]
            evaluators = state_cfg.get("evaluators", [])

            if evaluators:
                from assets.core.eval_runner import dispatch_evaluator
                for eval_name in evaluators:
                    result = await dispatch_evaluator(self.ctx, eval_name, {"state": new_state}, self, internal_msgs)
                    if not result.passed:
                        return False, f"Blocked by {eval_name}: {result.reasoning}"

            self._last_state = self.state_name
            self.state_name = new_state
            return True, "OK"

        return False, f"Invalid state '{new_state}'. Valid states: {', '.join(self.states.keys())} + dynamic states."

    def get_all_states(self) -> dict:
        """Return all states (static + dynamic) for serialization."""
        return {**self.states, **self.dynamic_states}
