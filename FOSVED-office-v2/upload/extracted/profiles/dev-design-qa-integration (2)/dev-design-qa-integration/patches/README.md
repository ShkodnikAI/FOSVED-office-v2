# Patches Directory — DDQ Integration

Files here are **target-state references**, not git patches. They show what
specific files in fosved-bot should contain after each phase. They are NOT
meant to be `git apply`-ed.

## Process for each patch

1. Read the patch file fully.
2. `diff` it conceptually against the current file in fosved-bot.
3. Apply changes **manually**, preserving all existing local content.
4. Verify with the check noted in the patch header.

Never blind-copy — fosved-bot already has OSP, ЛЗ, Expert, Yana and Visual
registered. Losing their entries would break the running bot.

## Files in this directory

| Patch | Phase | Purpose |
|-------|-------|---------|
| `army-ddq-patch.js` | Y5 | `army.js` — SPECIALISTS aliases + SKILLS_MAP entries for all 43 dev/design/qa skills with tier comments |
| `bot-ddq-handlers.js` | Y6 | `bot.js` — 31 command handlers (14 Dev + 8 Design + 9 QA) |
| `scheduler-ddq-patch.js` | Y7 | `scheduler.js` — 6 scheduled tasks (tech radar, estimate calibration, QA monitor, security scan, design audit, quarterly review) |
| `upravlenie-ddq-routing-patch.md` | Y8 | `library/upravlenie.md` — Yana routing triggers + multi-department orchestration + boundary disambiguation |
| `bot-cross-dept-hooks.js` | Y9 | `bot.js` — cross-department auto-hooks (Design→Dev, Dev→QA, QA defect→Dev hotfix). Best-effort, non-blocking, kill-switch `DDQ_AUTO_HOOKS=false` |

## Patches NOT in this directory (deferred / optional)

**Phase Y11 — miniapp screens (optional, can be deferred):**
The backend works fully without the miniapp. If/when miniapp screens are wanted,
they follow the patterns established in the prior Visual Department pack
(`miniapp-visuals-route.ts` / `miniapp-visuals-screen.tsx`). Three screens
would be added:
- `dev-screen.tsx` — Kanban of DevTasks, estimate-accuracy chart, tech radar
- `design-screen.tsx` — DesignArtifact gallery, design system viewer
- `qa-screen.tsx` — TestRun dashboard, defect trends, AI eval scores, security audits

Plus API routes: `/api/dev/*`, `/api/design/*`, `/api/qa/*`.

These can be written during Phase Y11 following the architecture in
`DDQ_INTEGRATION_PLAN.md`. They are not part of the v1.0 backend block.

## Application order

Follow `DDQ_INTEGRATION_PLAN.md` phases Y1–Y12 strictly. The patches map to
phases as in the table above. Apply, test, commit, then next.

**Highest-risk phase: Y6** (31 command handlers in bot.js). Integrate one
department at a time — Dev commands, test; Design commands, test; QA commands,
test. Do not add all 31 at once.

## Emergency disable

If cross-department hooks misbehave in production:

```
# In Render env vars:
DDQ_AUTO_HOOKS=false
```

All hooks in `bot-cross-dept-hooks.js` become no-ops immediately, without a
code change or redeploy of code (just an env-var change + restart).
