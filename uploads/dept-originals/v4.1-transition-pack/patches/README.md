# Patches Directory

Files here are **target-state references** showing what specific files in fosved-bot should look like after each phase.

Per `CLAUDE_CODE_BRIEF.md`, patches are NOT git patches — they show the desired state. Process:
1. Read patch file
2. `diff` against current file in fosved-bot
3. Apply changes manually preserving local additions

## Files in this directory

| Patch | Used in Phase | Purpose |
|-------|---------------|---------|
| `army-patches.js` | Phase 2, 3, 4 | Updates to army.js — SPECIALISTS map and SKILLS_MAP for OSP V2, ЛЗ, Expert |
| `bot-commands-patches.js` | Phase 2, 3 | Bot command handlers for OSP V2 + ЛЗ |
| `expert-bot-commands.js` | Phase 4 | Bot command handlers for Expert department |
| `expert-army-patch.js` | Phase 4 | Expert-specific army.js entries |
| `handlers-patches.js` | Phase 2 | Updated OSP V2 command handlers (replaces V1) |
| `scheduler-patches.js` | Phase 2, 3, 5 | Updated scheduler.js with OSP V2 cycles + ЛЗ continuous monitoring |

## Patches NOT in this directory yet (Claude Code will create during phases)

These are noted for awareness — you may need to write them based on actual repository state:

- `bot_archive_hooks.js` (Phase 6) — auto-publish hooks in /analyze, /expert, /verify handlers
- `bot_lz_handlers.js` (Phase 3) — full ЛЗ handler implementation (some present in bot-commands-patches.js)
- `scheduler_lz.js` (Phase 3) — ЛЗ-specific scheduler tasks
- `bot_expert_handlers.js` (Phase 4) — full Expert handler implementation (see expert-bot-commands.js)
- `spd_research_integration.js` (Phase 4) — calls to lib/research.js inside spd.js
- `miniapp_chat_route.ts` (Phase 9) — /api/chat endpoint mirroring askAI()
- `miniapp_stt_route.ts` / `miniapp_tts_route.ts` (Phase 9) — voice endpoints
- `miniapp_chat_overlay.tsx` (Phase 9) — connect chat-overlay to /api/chat
- `miniapp_auth.ts` (Phase 9) — Telegram WebApp initData verification
- `lib_voice_providers.ts` (Phase 9) — shared voice pipeline for miniapp
- `miniapp_drive_screen.tsx` (Phase 8) — drive-screen redesign
- `miniapp_api_specs.md` (Phase 7) — specs for endpoints to implement

These can be written during their respective phases following the architecture established here.
