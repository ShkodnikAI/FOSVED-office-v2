---
Task ID: 1
Agent: main
Task: Fix Yana — remove format_instruction, miniapp, add delegation/calendar/voice

Work Log:
- Found ROOT CAUSE: BuildContext() in dept/context.mlog appended FORMAT_INSTRUCTION to ALL departments including Yana (the _NO_FORMAT_DEPTS exclusion in llm_proxy.py was bypassed because Metalogos adds instruction BEFORE request reaches Python)
- Fixed context.mlog: BuildContext now checks `if dept != "yana" and dept != "admin"` before appending FORMAT_INSTRUCTION
- Rewrote dept/yana.mlog: custom HandleYana with YanaCalendar(), YanaNowInfo(), YanaCheckDelegate() — no longer calls BuildContext
- Updated library/yana.md: added dept routing table (12 departments), explicit ЗАПРЕЩЕНО style rules (no layers, badges, verdict), /calendar and /remember commands
- Added yana_events table to InitDB in app.mlog
- Added /calendar command in app.mlog
- Added delegation handler in app.mlog: if HandleYana returns dept name, auto-routes to target department handler
- Increased TTS timeout from 60s to 120s in llm_proxy.py
- Added SendReport guard for Yana in dept/miniapp.mlog
- Previous commit: safe auto_enricher import (try/except wrapper)

Stage Summary:
- Commits: 42ce486 (safe import), 3e5f2b8 (Yana v3)
- 5 files changed: app.mlog, context.mlog, yana.mlog, library/yana.md, llm_proxy.py, miniapp.mlog
- Yana should now: respond conversationally (no layers/badges), delegate to departments, know calendar/time, have voice with 120s timeout
