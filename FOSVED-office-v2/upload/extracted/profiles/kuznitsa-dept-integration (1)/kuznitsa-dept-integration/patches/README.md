# Patches Directory — Kuznitsa Integration

Files here are **target-state references**, not git patches. They show what
fosved-bot files should contain after each phase. NOT `git apply`-able.

## Process for each patch

1. Read the patch file fully.
2. Compare against the current file in fosved-bot.
3. Apply changes **manually**, preserving all existing content.
4. Verify with the check noted in the patch / integration plan.

Never blind-copy — fosved-bot already has OSP, ЛЗ, Expert, Visual, Yana, the
DDQ departments, Marketing and Engineering registered. Losing their entries
breaks the bot.

## Files

| Patch | Phase | Purpose |
|-------|-------|---------|
| `army-kk-patch.js` | K5 | `army.js` — SPECIALISTS aliases + 8 SKILLS_MAP entries with tier comments |
| `bot-kk-handlers.js` | K6 | `bot.js` — 7 command handlers |
| `scheduler-kk-patch.js` | K7 | `scheduler.js` — 3 scheduled tasks |
| `upravlenie-kk-routing-patch.md` | K8 | `library/upravlenie.md` — Yana routing + the critical Kuznitsa/Yana boundary |

## Application order

Follow `KUZNITSA_INTEGRATION_PLAN.md` phases K1–K9. Patches map to phases
K5–K8. Apply, test, commit, then next.

## Key point — the Kuznitsa/Yana boundary

`upravlenie-kk-routing-patch.md` is not just routing triggers — its most
important content is the **Kuznitsa/Yana boundary** (METHODOLOGY.md III.8).
Yana is "what to do now"; the Kuznitsa is "what a department should be". Apply
that section carefully — if the boundary blurs, do-work requests get mis-routed
to the Kuznitsa and meta-work requests get mis-routed to working departments.

## No cross-department hooks in this block

The Kuznitsa has no automatic cross-department hooks. Its interaction with
other departments (designing them, debriefing them) and with Yana (the data
exchange) is described in `upravlenie-kk-routing-patch.md` and happens on
demand. Nothing fires automatically — no kill-switch to configure.

## Note — `/recalibrate-dept` is owner-gated

The `/recalibrate-dept` command initiates a heavy operation that, per Kuznitsa
hard rule 8, requires explicit owner approval before it proceeds. The handler
in `bot-kk-handlers.js` makes this explicit — the session opens in an
"awaiting owner approval" state. Do not remove that gate during integration.
