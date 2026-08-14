from assets.core.registry import ask_tool

@ask_tool(
    name="gc",
    description="Internal context management: Remove messages by ID to free up your LLM context window. Do NOT use this for Linux system garbage collection.",
    schema_properties={"ids": {"type": "array", "items": {"type": "string"}}}
)
async def gc_handler(ctx, agent, args, internal_msgs=None):
    ids_to_gc = args.get("ids", [])
    count = 0

    if internal_msgs is not None:
        for m in internal_msgs:
            if m.get("id") in ids_to_gc and not m.get("gc"):
                m["gc"] = True  # Flag it so ask.py removes it
                count += 1

    return f"Garbage collected {count} messages from your internal context window."
