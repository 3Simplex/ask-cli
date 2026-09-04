---
when_to_read: "Adding or modifying a tool and its schema."
related: ["context-providers.md", "evaluators.md"]
---
# Tools

Tools are Python files in `assets/tools/`, registered via the `@ask_tool`
decorator.

```python
from assets.core.registry import ask_tool

@ask_tool(
    name="your-tool",
    description="What this tool does.",
    schema_properties={"param": {"type": "string"}}
)
async def your_tool_handler(ctx, agent, args, internal_msgs=None):
    param = args.get("param", "")
    return f"Result: {param}"
```

## Auto-Discovery

**No manual registration step is required.** `ask.py` auto-discovers every
module under `assets/tools/` via `pkgutil.iter_modules` at startup, which fires
the `@ask_tool` decorator. To add a tool, simply drop the file in
`assets/tools/` — do **not** add an import line anywhere.

> Note: the import path is `assets.core.registry` (the registry lives at
> `assets/core/registry.py`).

<!-- BEGIN GENERATED: tools — do not edit, produced by generate_docs.py -->

| Tool | Purpose | Args |
| --- | --- | --- |
| create_state | Create a dynamic state at runtime with custom context, tools, and prompt. The state persists for the current session. Use this to create highly specialized modes of operation for specific tasks. | name, allowed_tools, description, context_providers, reasoning_budget, temperature, system_prompt |
| delete_state | Delete a dynamic state created at runtime. | name |
| gc | Internal context management: Remove messages by ID to free up your LLM context window. Do NOT use this for Linux system garbage collection. | ids |
| read | Read the content of a local file or a web page. | target |
| run | Execute a Linux command. | command |
| search | Search DuckDuckGo. | query |
| set_state | Change your compute state to access different tools or operational modes. Available states include both predefined and dynamically created states. | state |
<!-- END GENERATED -->
