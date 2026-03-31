# The Tripartite Agent Protocol 🛡️

To ensure your agent actually uses the `aegis-memory` SDK effectively, you should include the following "Mandate" in its System Prompt. This ensures the agent checks historical precedents and system constraints before executing any task.

## The System Prompt Snippet (Paste this in)

```markdown
## MEMORY PROTOCOL: TRIPARTITE SITUATIONAL AWARENESS
Before executing any technical change or answering complex architectural questions, you MUST:
1. CALL `python bridge.py recall "<user_prompt>"` to retrieve historical context.
2. ANALYZE the returned `ContextPayload`:
   - Check `historical_precedents` for how this was done before.
   - Check `blast_radius` to see what other components might break.
   - Check `hard_constraints` for immutable system rules.
3. IF `confidence_score` is < 0.5, inform the user you have "Memory Gaps" and ask for clarification.
4. AFTER COMPLETING THE TASK, you MUST CALL `python bridge.py ingest "<summary_of_your_action>"` so future instances learn from this session.
```

## Implementation Example (Pseudo-code)

Regardless of which client or model you use, the loop should look like this:

```python
# 1. Boot up situational awareness
context = await memory.recall(user_input)

# 2. Feed that context into the LLM
response = await agent.ask(
    prompt=user_input,
    context=context.model_dump_json() # Inject the Tripartite Memory here!
)

# 3. Commit the new knowledge to the Ledger
await memory.ingest(content=response, actor="agent_name")
```
