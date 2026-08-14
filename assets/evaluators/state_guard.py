from assets.core.registry import ask_evaluator
from assets.core.eval_runner import llm_eval_call

@ask_evaluator(
    name="state_guard",
    description="Determines if the agent is allowed to enter a specific state.",
    mode="boolean",
    stateful=True,
    history_window=5,
    max_tokens=1024,
    reasoning_budget=1024
)
async def state_guard_handler(ctx, agent, input_data, eval_msgs, config):
    target_state = input_data.get("state", "unknown")

    # We are stateful, so we have access to eval_msgs!
    history_text = "No history."
    if eval_msgs:
        history_text = "\n".join([f"{m.get('role')}: {m.get('content')}" for m in eval_msgs if m.get('content')])

    sys_prompt = f"""You are a state transition guardian.
The agent is attempting to transition to the state: '{target_state}'.
Review the recent conversation history to determine if this transition makes logical sense.
If it is a completely unprompted or nonsensical transition, fail it.

Respond STRICTLY in JSON format:
{{"passed": true, "reasoning": "Brief explanation"}}"""

    user_prompt = f"Recent History:\n{history_text}\n\nApprove transition to {target_state}?"

    return await llm_eval_call(ctx, sys_prompt, user_prompt, config)
