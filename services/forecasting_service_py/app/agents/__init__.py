"""LLM agent modules. Each agent is a thin function that builds a prompt
and calls `app.agents.llm.generate`. The wrapper handles provider selection,
caching via AgentRun, and token/latency logging."""
