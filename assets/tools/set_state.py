from assets.core.registry import ask_tool

@ask_tool(
    name="set_state",
    description="Change your compute state to access different tools or operational modes. Available states include both predefined and dynamically created states.",
    schema_properties={"state": {"type": "string", "description": "The exact name of the state to transition to."}}
)
async def set_state_handler(ctx, agent, args, internal_msgs=None):
    new_state = args.get('state')

    # Now we await the transition and unpack the success/msg tuple
    success, msg = await agent.transition_to(new_state, internal_msgs)

    if success:
        # Get the state config (from either static or dynamic)
        if new_state in agent.states:
            state_cfg = agent.states[new_state]
        else:
            state_cfg = agent.dynamic_states[new_state]
        unlocked_tools = state_cfg.get("allowed_tools", [])
        return f"SUCCESS: Compute state changed to {new_state}. You now have access to these tools: {unlocked_tools}"

    # Provide the block reason or fallback message
    valid_states = list(agent.states.keys()) + list(agent.dynamic_states.keys())
    return f"Failed to change state: {msg}\nValid states for your profile are: {', '.join(valid_states)}"
