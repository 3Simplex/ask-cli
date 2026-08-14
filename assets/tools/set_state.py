from assets.core.registry import ask_tool

@ask_tool(
    name="set_state",
    description="Change your compute state to access different tools or operational modes.",
    schema_properties={"state": {"type": "string", "description": "The exact name of the state to transition to."}}
)
async def set_state_handler(ctx, agent, args, internal_msgs=None):
    new_state = args.get('state')

    # Now we await the transition and unpack the success/msg tuple
    success, msg = await agent.transition_to(new_state, internal_msgs)

    if success:
        unlocked_tools = agent.states[new_state].get("allowed_tools", [])
        return f"SUCCESS: Compute state changed to {new_state}. You now have access to these tools: {unlocked_tools}"

    # Provide the block reason or fallback message
    valid_states = ', '.join(agent.states.keys())
    return f"Failed to change state: {msg}\nValid states for your profile are: {valid_states}"
