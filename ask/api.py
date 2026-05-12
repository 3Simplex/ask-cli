import base64
import json
import os
import subprocess
from typing import Any, Dict, List, Tuple

import requests

from .config import API_KEY, API_MODELS_URL, PREF_FILE


def detect_server_capabilities() -> Tuple[bool, str]:
    try:
        r = requests.get(API_MODELS_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=3)
        if r.status_code == 200:
            models = r.json().get("data", [])
            for m in models:
                name = m.get("id", "").lower()
                if any(kw in name for kw in ["vision", "vl", "llava", "gemma-4", "gemma4", "pixtral"]):
                    return True, m.get("id")
            if models:
                return False, models[0].get("id")
    except Exception:
        pass
    return False, "unknown"


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def get_identity_prompt(interactive_on: bool, memory_active: bool, is_multimodal: bool) -> str:
    os_info = subprocess.getoutput("grep PRETTY_NAME /etc/os-release | cut -d'=' -f2 | tr -d '\"'")
    shell_info = os.environ.get("SHELL", "Unknown Shell")
    admin = "Administrator (sudo via wheel)" if "wheel" in subprocess.getoutput("groups") else "Standard User"

    prefs = {}
    if PREF_FILE.exists():
        try:
            with open(PREF_FILE, 'r') as f:
                prefs = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    mode_label = "[MODE: INTERACTIVE]" if interactive_on else "[MODE: READ-ONLY / ADVISORY]"
    mem_label = "[MEMORY LINK: ACTIVE]" if memory_active else "[MEMORY LINK: INACTIVE / FRESH SESSION]"
    mm_label = "ENABLED" if is_multimodal else "DISABLED"

    # Example usage of prefs (even if it doesn't change behavior now, it preserves the data structure for future use/consistency)
    _ = prefs.get("example_pref", None)

    tools_disabled = "Tools are DISABLED in this session."
    tools_enabled = """
- TOOL: {"name": "run", "command": "..."} -> Execute and SEE output.
- TOOL: {"name": "display", "command": "..."} -> Run and show to USER ONLY via pager. You do NOT see the data.
- TOOL: {"name": "search", "query": "..."} -> Search DuckDuckGo.
- TOOL: {"name": "read", "url": "..."} -> Read webpage content.
- TOOL: {"name": "gc", "ids":["msg_123", "msg_456"]} -> Mark message for garbage collector.
"""

    return f"""
### CORE IDENTITY ###
You are 'ask', an advanced, agentic Linux CLI assistant for {os_info}.
Current Shell: {shell_info}
Current Operational State: {mode_label} | {mem_label}
Multi-modal Capabilities: {mm_label}
User Status: {admin}

### NIXOS CONSTRAINTS (MANDATORY) ###
1. Software is managed declaratively via `/etc/nixos/configuration.nix` or flakes.
2. For temporarily executing tools, ALWAYS suggest `nix-shell -p <pkg>` or `nix run nixpkgs#<pkg>`.

### CONTEXT GARBAGE COLLECTION ###
You run on a large context model. To prevent context poisoning, you are equipped with a Garbage Collector.
Each message/tool block in your history is prepended with a metadata ID by the backend before you recieve it. If a conversational tangent is finished, or a large tool output is no longer needed, immediately use the `gc` tool to mark those messages for removal by the garbage collector. You should not write the metadata into a message yourself even if it looks like you should otherwise.

### TOOL DEFINITIONS ###
{tools_enabled if interactive_on else tools_disabled}

### GROUNDING RULES ###
- If memory is INACTIVE, act as if this is the first time meeting the user.
- If memory is ACTIVE, continue naturally.
- You are an AI assistant that can call external tools.
- To call a tool, you MUST wrap the call between the special tokens:


TOOL: {{"name": "", "command": ""}}\n

"""


def build_api_payload(internal_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    api_msgs = []
    for m in internal_msgs:
        if m.get("gc", False):
            continue

        role = m["role"]
        msg_id = m.get("id", "sys")
        raw_content = m["content"]

        prefix = f"[ID: {msg_id}]\n" if msg_id != "sys" and role != "system" else ""

        if isinstance(raw_content, str):
            content = prefix + raw_content
        elif isinstance(raw_content, list):
            content = []
            for idx, block in enumerate(raw_content):
                if block["type"] == "text" and idx == 0:
                    content.append({"type": "text", "text": prefix + block["text"]})
                else:
                    content.append(block)

        api_msgs.append({"role": role, "content": content})
    return api_msgs
