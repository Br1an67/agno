# 04_tools

Examples for callable tool factories, tool choice, and tool call limits.

## Files
- `01_callable_tools.py` - Vary the toolset per user role using callable factories.
- `02_session_state_tools.py` - Use session_state directly as a parameter with caching disabled.
- `03_team_callable_members.py` - Assemble team members dynamically.
- `04_tools_with_literal_type_param.py` - Use typing.Literal for tool parameters with predefined values.
- `05_same_run_tool_loading.py` - Load a tool during execution and use it on the next model iteration without another user message.
- `tool_call_limit.py` - Limit the number of tool calls per run.
- `tool_choice.py` - Control which tool the agent selects.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Same-run registration

Calling `agent.add_tool()` from a tool makes the new tool available to that execution on its
next model request. The tool is also retained in the agent's configuration for later runs,
including continuation after confirmation. Registries of other already-running executions
are not changed. Calling `add_tool()` outside a tool call updates configuration only.

New tools use normal preparation for schemas, runtime context, media, async toolkit selection,
hooks, and confirmation. Existing names keep the first registered callable. This example uses
an already usable callable; adding a tool does not connect a new MCP server automatically.
Tool instructions appended during registration do not rebuild the existing system prompt.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/04_tools/<file>.py`
