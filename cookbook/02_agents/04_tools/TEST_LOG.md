# Test Log -- 04_tools

### 05_same_run_tool_loading.py

**Status:** NOT RUN against a provider
**Description:** Demonstrates loading a multiplication tool and calling it in the same run.
**Result:** Syntax and repository validation checked locally. Provider-free regression tests
exercise sync, async, streaming, dynamic schemas, context, hooks, and confirmation/continuation.
The live cookbook requires `OPENAI_API_KEY` and was not executed against a provider.

---

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### 01_callable_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 01 callable tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 17s.

---

### 02_session_state_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 02 session state tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 7s.

---

### 03_team_callable_members.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 03 team callable members. Ran successfully and produced expected output.
**Result:** Completed successfully in 87s.

---

### 04_tools_with_literal_type_param.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates using typing.Literal for tool parameters with predefined values. Tests both Toolkit methods and standalone functions with Literal type hints.
**Result:** JSON schema correctly generates enum constraints for Literal types.

---

### tool_call_limit.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates tool call limit. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### tool_choice.py

**Status:** TIMEOUT
**Tier:** untagged
**Description:** Demonstrates tool choice. Timed out after 120s - likely making many API calls or stuck.
**Result:** Timed out after 120s.

---
