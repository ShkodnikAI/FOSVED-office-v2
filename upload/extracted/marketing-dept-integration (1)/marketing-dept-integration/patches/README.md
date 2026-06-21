# Patches Directory — Marketing Integration

Files here are **target-state references**, not git patches. They show what
specific fosved-bot files should contain after each phase. NOT `git apply`-able.

## Process for each patch

1. Read the patch file fully.
2. Compare against the current file in fosved-bot.
3. Apply changes **manually**, preserving all existing content.
4. Verify with the check noted in the patch / integration plan.

Never blind-copy — fosved-bot already has OSP, ЛЗ, Expert, Visual, Yana and the
DDQ departments registered. Losing their entries breaks the bot.

## Files

| Patch | Phase | Purpose |
|-------|-------|---------|
| `army-marketing-patch.js` | M5 | `army.js` — SPECIALISTS aliases + 11 SKILLS_MAP entries with tier comments |
| `bot-marketing-handlers.js` | M6 | `bot.js` — 8 command handlers |
| `scheduler-marketing-patch.js` | M7 | `scheduler.js` — 3 scheduled tasks |
| `upravlenie-marketing-routing-patch.md` | M8 | `library/upravlenie.md` — Yana routing triggers + boundary disambiguation |

## Application order

Follow `MARKETING_INTEGRATION_PLAN.md` phases M1–M9. The patches map to phases
M5–M8 as in the table. Apply, test, commit, then next.

## Key caution

In `bot-marketing-handlers.js` — register `/campaign-forecast` and
`/campaign-verify` BEFORE `/campaign`, or use the `\b` anchored regexes
provided, so the shorter command doesn't capture the longer ones.

## No cross-department hooks in this block

Unlike DDQ, the Marketing block has no automatic cross-department hooks. Its
cross-department work (commissioning visuals from Visual, coordinating launches
with Dev/Design/QA, handing CAC to Finance) is orchestrated by Yana on demand,
described in `upravlenie-marketing-routing-patch.md`. Nothing fires
automatically — so there is no kill-switch to configure.
