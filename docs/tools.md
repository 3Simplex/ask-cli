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
