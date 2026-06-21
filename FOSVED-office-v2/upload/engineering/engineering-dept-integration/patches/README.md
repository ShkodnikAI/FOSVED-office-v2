# Patches Directory — Engineering Integration

Files here are **target-state references**, not git patches. They show what
fosved-bot files should contain after each phase. NOT `git apply`-able.

## Process for each patch

1. Read the patch file fully.
2. Compare against the current file in fosved-bot.
3. Apply changes **manually**, preserving all existing content.
4. Verify with the check noted in the patch / integration plan.

Never blind-copy — fosved-bot already has OSP, ЛЗ, Expert, Visual, Yana, the
DDQ departments and Marketing registered. Losing their entries breaks the bot.

## Files

| Patch | Phase | Purpose |
|-------|-------|---------|
| `army-engineering-patch.js` | E5 | `army.js` — SPECIALISTS aliases + 12 SKILLS_MAP entries with tier comments |
| `bot-engineering-handlers.js` | E6 | `bot.js` — 8 command handlers |
| `scheduler-engineering-patch.js` | E7 | `scheduler.js` — 3 scheduled tasks |
| `upravlenie-engineering-routing-patch.md` | E8 | `library/upravlenie.md` — Yana routing + scope/responsibility note + boundary disambiguation |

## Application order

Follow `ENGINEERING_INTEGRATION_PLAN.md` phases E1–E9. Patches map to phases
E5–E8. Apply, test, commit, then next.

## Key cautions

**Command anchoring.** In `bot-engineering-handlers.js` — register
`/calc-norms`, `/calc-loadcases`, `/calc-verify`, `/calc-review`, `/calc-show`
BEFORE `/calc`, or use the `\b` anchored regexes provided, so the shorter
command does not capture the longer ones.

**The disclaimer is not optional.** Every engineering output the bot sends
carries the preliminary-work disclaimer (the department is a project assistant,
not the engineer of record). The handlers include it. Do not strip it during
integration — it is a hard rule and a safety device.

## No cross-department hooks in this block

Like the Marketing block, the Engineering block has no automatic
cross-department hooks. Its cross-department work (handing a materials
specification to Finance, sanity-checking a claim for Expert) is orchestrated
by Yana on demand, described in `upravlenie-engineering-routing-patch.md`.
Nothing fires automatically — no kill-switch to configure.
