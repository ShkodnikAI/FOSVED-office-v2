# CONTEXT_HANDOFF.md — Concentrated Project Context

**Project:** Fosved Office (fosved-bot + fosved-miniapp)
**Owner:** @ShkodnikAI (Telegram ID 2044005421)
**Author:** Claude Opus (planning session)
**Version:** 1.0
**Date:** 2026-05-09
**Purpose:** Capture WHY decisions were made, so Claude Code (and future agents) work with full context, not just the WHAT from MIGRATION_PLAN.md

---

## WHO IS THE OWNER

A Russian-speaking individual building Fosved Office as a personal multi-departmental AI assistant for:
- Personal investment decisions (looking for asymmetric opportunities like Rheinmetall-before-Iran-war or Bitcoin-in-2010 type situations)
- Continuous learning about the world through structured analysis
- Business operations (project management, finance, contracts) at a small scale
- Technical due diligence on meetings in unfamiliar domains

**Key traits:**
- **Non-coder, technical-minded.** Understands architecture conceptually, cannot read code line-by-line.
- **Methodologically sharp.** Catches shallow analysis, demands rigor. Has caught Claude's misses in prior analyses (e.g., Russian fiscal cascade in BYN-USD analysis).
- **Time-constrained.** Develops in spare time. Sessions are focused but limited.
- **Long-term thinker.** Values systems that compound learning over years, not month-to-month wins.
- **High autonomy.** Says "Делай что считаешь нужным" / "Я тебе доверяю" — but expects you to use judgment about WHEN to ask, not skip safety checks.

**Communication style:**
- Russian by default. English for code, technical terms, log output.
- Direct. No fluff, no apology theater, no corporate hedging.
- Prefers prose over bullets for analysis. Bullets for plans/checklists/code.
- Skeptical of grandstanding — "looking smart" is not a goal.

**What he has explicitly told Claude in past sessions:**
- "Не нужно изучать заново, продолжи с места остановки" — efficient continuation > restating context
- "Я тебе доверяю, продолжай как считаешь нужным" — autonomy granted within sane bounds
- "Профессиональная этика, мы как патологоанатомы" — methodology is professional craft, not casual chat
- "Принимаю все твои рекомендации" — when convinced, decisive

**What he disliked in past sessions (don't repeat):**
- Long narratives about what you're going to do — just do it
- Asking for confirmation on settled matters
- "Let me clarify the question" preambles
- Suggesting features in the middle of execution
- Being verbose when concise would do

---

## EVOLUTION OF THE ARCHITECTURE

Understanding this evolution explains WHY each layer of v4.1 is what it is.

### v1 — Original concept (2025)

Single-file bot with hardcoded specialist prompts. No archive, no methodology, no skills system. Specialists were just "personality switches" through prompt prepending.

**Why insufficient:** no learning loop. No compounding intelligence. Each conversation isolated.

### v2 — Modular bot with database

Split into modules (database.js, finance.js, scheduler.js, etc.). Added Supabase Postgres. Specialists got dedicated profiles in `library/*.md`. Bot could remember conversations, tasks, projects.

**Limitations:** specialists were prompts in markdown, not bounded experts with skills and metrics. ОСП was just another specialist with bigger prompt.

### v3 — Strategic Planning Department V1 (May 2026)

Major addition: ОСП (Strategic Planning Department) as a fully methodologized specialist:
- 12-layer deconstruction protocol (source/content/timing/audience/silence/context/coordination/narrative/beneficiaries/analogies/ACH/forecast)
- Sherman Kent calibrated probabilities
- ACH (Heuer) for hypothesis testing
- Premortem at 3mo and 12mo
- Brier scoring on forecasts
- Watch list for active topics
- Monthly review + Quarterly methodology review
- 11 skills in three tiers

This was the breakthrough — first specialist with **real methodology, real archive, real learning loop**. Code in spd.js (550 lines) implements the business logic. 11 SKILL.md files in skills/fosved/spd/.

**Why this matters:** v3 proved the pattern works. The pattern: profile + tier-aware skills + Prisma archive + Brier-style metric + scheduler-driven self-review.

### v4 / v4.1 — Generalized to multiple departments (this migration)

Apply the v3 pattern to **other departments**:
- ОСП V2 — refined version of V1 (5-level topology of system maturity: leaves/branches/stem/roots/fruits, force differentials with formula P=A×R×S×L×E×E_modifier where E is environmental modifier)
- ЛЗ (Knowledge Lab) — continuous technology scanning, hype-cycle mapping, disruption probability
- Эксперт — technical due diligence preparation for specific meetings
- Кузница (Veteran) — methodology-of-methodology, planned but not implemented in v4.1
- AI Studio, Юрист, Финансы, Разработка, Продукт, Операции — currently shallow, get deepened in future

**Why v4.1 is "minor" version not v5.0:** the v3 pattern is preserved. Each new department uses same architecture. Not a revolution, an extension.

---

## KEY DESIGN DECISIONS — WITH RATIONALE

### Decision 1 — Why ОСП V2 replaces V1, not extends it

**Considered alternatives:**
- Keep V1 working, add V2 as parallel department "ОСП Strategic" — would have legacy and new in parallel
- Evolution path — V1 gradually upgraded to V2

**Decision:** drop V1, install V2 fresh.

**Why:**
- V1 archive in production is empty (placeholder data)
- V2 has different conceptual frame (5-level topology vs 12 layers)
- Parallel running causes confusion in routing and methodology drift
- Evolution path is slower than clean replacement when starting from empty

**What this means for Claude Code:** when applying Phase 2, fully replace V1. Don't preserve V1 logic "just in case". Backup files for emergency rollback only.

### Decision 2 — Why ЛЗ is separate from ОСП, not a sub-protocol

**Considered alternatives:**
- ЛЗ as a Tier 3 skill of ОСП ("technology scanning skill")
- ЛЗ as a workflow within ОСП's protocol

**Decision:** ЛЗ is a separate department.

**Why:**
- Different cadence: ОСП is event-driven (analyze when news happens), ЛЗ is continuous (scan watchlist daily)
- Different metric: ОСП measures Brier on forecasts, ЛЗ measures inflection-detection accuracy
- Different psychotype: ОСП is Paranoid+Pedant (challenging facts), ЛЗ is Pattern-Hunter+Curious (spotting emergence)
- Different output: ОСП produces Analysis (12-layer), ЛЗ produces KnowledgeArtifact (technology profile)

Sharing the architecture (profile + skills + archive + metric + reviews) but separating the function makes both stronger.

**What this means for Claude Code:** ЛЗ has its own routes, own commands, own scheduler tasks, own skill directory. Don't try to reuse ОСП code by genericizing — duplicate the pattern, specialize the substance.

### Decision 3 — Why Эксперт department exists at all

**Considered alternatives:**
- "Just use Grok with web search" — owner already has this
- Sub-protocol of ОСП — "ОСП for meeting prep"
- One-off skill rather than department

**Decision:** Эксперт is a separate department with full architecture.

**Why:**
- Different time horizon: ОСП is multi-month forecast, ЛЗ is multi-quarter trends, Эксперт is hours-to-days deadline
- Different output format: ОСП produces strategic analysis, Эксперт produces battle briefing with combat questions
- Different success criterion: ОСП validates by Brier on forecasts (months later), Эксперт validates by meeting performance (immediately)
- Use case is real and distinct: owner faces meetings (academy of sciences, investor pitches, contractor negotiations) where domain expertise gap creates information asymmetry. No other tool addresses this.

**What this means for Claude Code:** Эксперт is not "just another tool". Its discipline (combat questions with prepared response patterns, citation discipline, bullshit detection patterns) is what makes it useful. Don't simplify these — they're the value.

### Decision 4 — Why we use LDR ideas but not LDR itself

**Considered alternatives:**
- Deploy LDR as separate Render service, integrate via REST API
- Use LDR's Python library directly (would require Python service)
- Hybrid — deploy LDR for knowledge base only

**Decision:** take LDR's ideas (iterative research, source tier hierarchy, citation discipline, knowledge base building), implement in Node.js inside fosved-bot.

**Why:**
- LDR is a complete product, not a library — designed to be self-contained, not embedded
- Python+Docker+SQLCipher for an external service adds infrastructure overhead and ongoing cost ($25-50/month Render plans)
- Owner doesn't have constant deepexpert volume to amortize that cost yet
- Implementing the core pattern (3-iteration research loop with citations) in Node.js is achievable in lib/research.js — much smaller scope than running LDR
- Future: if usage justifies, can layer LDR-as-service later (decision deferred, not foreclosed)

**What this means for Claude Code:** lib/research.js implements iterative research pattern + knowledge base. Uses existing Grok web search + Claude API. No external service. Knowledge base is in same Supabase DB (ResearchSource model).

### Decision 5 — Why we don't use MTProto for Drive

**Considered alternatives:**
- Add `gramjs` or `telegram` npm package for MTProto
- Build separate Rust service like Telegram-Drive

**Decision:** stay with Bot API, accept 50MB file limit.

**Why:**
- Owner's actual Drive use is documents, contracts, reports — almost all under 50MB
- Bot API works today, MTProto requires user account credentials (api_id/api_hash) and session management
- MTProto adds significant complexity (auth flows, error handling, FLOOD_WAIT) for marginal benefit
- File limit is acceptable; if owner ever hits it for video/large files, revisit then

**What this means for Claude Code:** all file operations go through Bot API. `copyMessage`, `forwardMessage`, `sendDocument` to DRIVE_CHANNEL_ID. No MTProto, no gramjs. Drive UX in miniapp is improved (TG-Drive-style) but backend stays Bot API.

### Decision 6 — Why multi-user is "ready but not built"

**Considered alternatives:**
- Single-user forever (no multi-user planning)
- Multi-user fully built in v4.1
- Half-built (auth but no permission system)

**Decision:** add `userId` field everywhere with default OWNER_ID. No multi-user logic implemented.

**Why:**
- Owner expressed interest in eventual multi-user (team, then maybe SaaS) but not commitment
- Schema with `userId` is cheap now, retrofitting is expensive later
- Building full multi-user (auth flows, RBAC, UI for user management, data isolation) is months of work
- v4.1 is large enough already; multi-user would push it to v5.0

**What this means for Claude Code:** add `userId Int @default(2044005421)` to Conversation, Project, Task, Invoice, Document, Analysis, KnowledgeArtifact, ExpertBriefing, ResearchSource, etc. Don't add `where: { userId }` filters in queries (those would change semantics). Just have the field for future use.

### Decision 7 — Why Telegram Archive Channel is separate from Drive Channel

**Considered alternatives:**
- Use existing DRIVE_CHANNEL_ID for both files and summaries
- Multiple channels (one per department)

**Decision:** one new ARCHIVE_CHANNEL for summaries (different from DRIVE_CHANNEL_ID for files).

**Why:**
- Different content types: Drive has files (PDFs, docs), Archive has structured text summaries with hashtags
- Different reading experience: Drive is file explorer view, Archive is timeline of analyses
- Future shareability: Archive could be shared (read-only) with team/investors as a portfolio of analytical work; Drive contains private files
- Hashtags work better in dedicated channel without file noise

**What this means for Claude Code:** ARCHIVE_CHANNEL_ID is set in Render env in Phase 6. lib/archive-publisher.js posts to it. Don't conflate with DRIVE_CHANNEL_ID.

### Decision 8 — Why citation discipline is hard rule

**Considered alternatives:**
- Citations encouraged but not required
- Citations required only for Tier 2 skills (peer-review-simulation)
- Citations required everywhere

**Decision:** citations required for every numerical anchor and every Layer 2 (state-of-the-art) claim in Эксперт briefings AND in ОСП analyses Layer 2.

**Why:**
- Without citations, the briefing is "trust me bro" — not testable, not reusable
- Knowledge base only works if sources are tracked
- Combat questions are stronger with citations ("X claims Y, but according to Z report (link), the number is actually W")
- Brings academic rigor to commercial pitches

**What this means for Claude Code:** lib/research.js has `validateCitations(text)` function. ExpertBriefing creation must pass validation. If briefing has uncited numerical claims — flag, don't deliver.

### Decision 9 — Why Phase 9 (voice/chat in miniapp) was reordered after Phase 4

Owner explicitly requested this reordering for early UI feedback after the three new departments are functional.

**Why this matters methodologically:**
- Backend-first traditional approach means UI is delayed until almost all backend done
- Reordering means: as soon as the 3 departments work in bot, miniapp gets working chat to use them
- This gives owner real UX feedback at week 2, not week 4
- Risk: miniapp work happens before final coordination logic (Yana update in Phase 5) — but the chat just calls /api/chat which already routes through Yana, so the chat will improve as Phases 5-8 add features

### Decision 10 — Why we drop V1 placeholder data without ceremony

**Owner directly stated:** "Это все заглушки, можно удалять."

This applies to: analysis, analysis_indicators, analysis_verifications, monthly_reviews, quarterly_methodology_reviews, watch_topics, tasks, projects, invoices, documents, clients, client_timeline, entity_links, team_members, drive_files, search_logs, job_queue, project_messages, conversations.

NOT applies to: settings (STT/TTS keys preserved).

**What this means for Claude Code:** Phase 1 migration drops these tables and recreates them with v4.1 schema. No data preservation needed. Settings table preserved through migration.

---

## WORKED EXAMPLES — what good output looks like

### Example 1 — Belarus BYN-USD analysis (a past Claude miss)

In an earlier session, Claude analyzed Belarus's currency situation but **missed the cross-country macro spillover** — specifically, that Russian fiscal stress would propagate to Belarusian financial system through trade and currency arrangements. Owner caught this.

**Lesson:** ОСП V2 has explicit `narrative-vs-flows` skill with cross-country macro spillover instructions. When analyzing any country's economy, check connected economies (especially major trading partners and currency-linked).

This is why the methodology has detailed skills. Without `narrative-vs-flows` having explicit cross-country instructions, the same kind of miss happens.

### Example 2 — Hypothetical FusionCorp meeting (Эксперт worked example)

In a hypothetical scenario, owner is going to a meeting with a fusion energy startup ("FusionCorp") tomorrow about a potential investment. Эксперт produces:

**Phase 1 — Rapid Domain Immersion (4-layer):**
- Fundamentals: D-T fusion via magnetic confinement, requires temperatures >100M K, plasma stability the key challenge
- SOA: NIF achieved Q>1 in 2022 (laser fusion), tokamaks targeting Q=10 (ITER). Best Q from JET: ~0.67. Compact tokamaks (Commonwealth Fusion, Tokamak Energy) using HTS magnets aiming for Q=10 around 2026-2027
- Schools/debates: ITER mainstream vs compact private (CFS, FusionCorp, etc.) vs alternative-fuel (Helion D-He3)
- Numerical anchors: typical capex $5-7B/GW for FOAK fusion plant, tritium global supply ~30kg vs need 50-100 kg/year, plasma duration achieved continuously: <1 second

**Phase 2 — Project Deconstruction:**
- Central technical claim: compact tokamak with HTS magnets, Q=10 in 2027, commercial Q=30 by 2030
- Approach: copies CFS/Tokamak Energy pattern; not unique
- Demonstrated: small-scale magnet test, 30-second pulse at moderate temperature
- Claimed but not demonstrated: Q=10, $3B/GW capex, 2027 timeline
- Real shape: less-funded compact tokamak entrant in crowded space; aggressive timeline

**Phase 3 — Failure Modes (top 3):**
1. Tritium supply (catastrophic, certain) — global supply 30kg, needs 50-100kg/year, no plan
2. First wall materials under 14 MeV neutron flux (catastrophic, high prob) — no material yet
3. Capex realism (catastrophic for commercial, high prob) — $3B target vs $5-7B baseline

**Phase 4 — Combat Questions (top 5):**
1. (Type B numerical) "$3B/GW for FOAK or NOAK? what's the ratio?"
2. (Type A failure mode) "Tritium supply for 5 years — global ~30kg, you need 50-100kg/yr, plan?"
3. (Type A failure mode) "First wall materials under 14 MeV neutron, partner, timeline?"
4. (Type C competitive) "Helion targets D-He3, no tritium needed — your view on their probability?"
5. (Type F marker) "If you had to bet against your own approach, where?"

Each question has prepared good/uncertain/evasive response patterns documented.

**This is what an Эксперт briefing looks like done well.** Specific, citable, tactically usable.

### Example 3 — How OSP V2 differs from V1 in output

**V1 output (12 layers):** flat sequential layers, each ~paragraph. Heavy on deconstruction, lighter on synthesis.

**V2 output (5-level topology):**
- **Leaves** (visible events) — what happened, recent
- **Branches** (active processes) — ongoing dynamics
- **Stem** (institutional structure) — slow-moving systems
- **Roots** (underlying conditions) — economy, demography, geography
- **Fruits** (anticipated outcomes) — what this leads to

Plus **forces & potentials**: P = A × R × S × L × E (Active capacity × Resources × Situation favorability × Latent reserves × Environmental modifier). Quantified for each actor.

Plus **two-paths-synthesis**: explicit fork analysis for predicted bifurcation points.

Output is more spatially organized, more quantified, more action-oriented.

---

## WHAT HAS BEEN REJECTED (don't reopen)

To avoid repeating evaluations:

1. **Hetzner VPS / Fly.io / other deployment platforms** — Render is the chosen platform, settled.
2. **Supabase IPv4 paid add-on** — using transaction pooler (free), settled.
3. **SuperGemma 4 26B local LLM** — too heavy for this use case, settled (cloud LLMs only).
4. **Two separate repositories per specialist** — monorepo bot + monorepo miniapp.
5. **MTProto via gramjs for Drive** — Bot API only, accepted 50MB limit.
6. **Tauri/Rust desktop app** — web miniapp only.
7. **Python services for any feature** — all Node.js / TypeScript.
8. **External LDR service** — implement core in Node.js instead.
9. **Vector DB (pgvector) in v4.1** — deferred to v4.2.
10. **Multi-user fully built in v4.1** — only `userId` field readiness.
11. **Cookie-cutter specialist generation** — each department gets its psychotype and bespoke skills.
12. **One profile file with everything** — methodology lives in skills, profile is entry point.
13. **Single-cycle analysis** — multi-horizon self-improvement (daily/monthly/quarterly).
14. **Web-first as primary v4.1 goal** — Telegram-first remains, web is alternative interface.

---

## OPEN QUESTIONS / KNOWN GAPS

These are not blockers for v4.1 but worth tracking for future:

1. **Кузница (Veteran) implementation timing** — methodology of methodology. Currently planned but not in v4.1 scope. Trigger for activation: when 3+ departments have run for 3+ months and accumulated patterns.

2. **AI Studio specialist** — exists in UI concepts, no code. Activation depends on use case clarification.

3. **Юрист, Финансы, Разработка, Продукт, Операции deepening** — currently shallow profiles only. Each could become full v3-style specialist (profile + skills + archive). Sequence and timing TBD by owner priority.

4. **Cowork desktop mode** — owner mentioned interest in long-term. Tauri app sharing UI components with web miniapp. v5.0 or later.

5. **External integrations beyond Telegram** — Slack, Discord, email. No commitment.

6. **Real-time features** — WebSocket for miniapp live updates, push notifications. Phase 7 uses polling, real-time deferred.

7. **pgvector + embeddings** — semantic search across archive. v4.2 candidate.

8. **Multi-tenant SaaS** — selling Fosved Office to other companies. v5.0+.

These are mentioned because Claude Code may encounter hints of them in code/commits — they are not in scope for this migration.

---

## METHODOLOGICAL ANCHORS

When in doubt about HOW to do something — these methodological principles guide:

### Anchor 1 — Bounded specialists, not generic AI

Each specialist has a narrow scope, explicit psychotype, fixed skills set. They are not "generic AI assistant who can do X". They are bounded experts.

This is why each specialist has hard rules ("not ever does X even if asked"), specific psychotype (Paranoid + Pedant for OSP), and tier-aware skill loading.

When tempted to make specialists more flexible — resist. Bounded is the feature.

### Anchor 2 — Methodology compounds, conversations don't

A conversation is ephemeral. Methodology accumulates. Every Analysis, every Briefing, every Verification is **an asset that compounds**.

This is why everything is archived. Everything is verified. Everything has metrics. Everything feeds back into self-improvement reviews.

When tempted to skip archiving "for this one-off" — resist. The whole point is no one-offs.

### Anchor 3 — Forecasts must be falsifiable

Predictions without verification dates and binary indicators are noise. They cannot be scored, cannot be improved, cannot teach anything.

This is why Sherman Kent calibrated probabilities are mandatory. Why each forecast has watch indicators with windows. Why Brier scoring is automated.

When tempted to give "soft" predictions — resist. Either bet, or don't predict.

### Anchor 4 — Skills are not prompts

A skill is a methodology for a class of analysis, not a prompt template. It includes core principle, procedure, anti-patterns, output template, integration with parent.

Skills are dense by design — they encode professional practice. They look "long" because methodology has structure.

When tempted to simplify a skill — resist. The structure IS the value.

### Anchor 5 — Hard rules trump preferences

Each specialist has hard rules (never does X). These are non-negotiable, even if a request is reasonable in isolation.

This is what makes specialists trustworthy at scale. Without hard rules, behavior drifts under pressure.

When tempted to "just this once" violate a hard rule — resist. The point is they're hard.

---

## REFERENCE — full department list (current and target)

### Currently working (in production code):
- **Управление (Yana)** — coordinator, profile only, basic routing
- **Разработка** — profile only, basic chat
- **Юрист** — profile + document generation (NDA/MSA/SLA/TZ)
- **Финансы** — profile + invoice CRUD
- **Операции** — profile only
- **Продукт/Маркетинг** — profile only
- **AI Studio** — concept only, no code
- **ОСП V1** — full implementation (12-layer, replaced in Phase 2)

### Target after v4.1:
- **Управление (Yana)** — updated routing for 5 active departments + multi-dept orchestration
- **ОСП V2** — full v3-style implementation, replaces V1
- **ЛЗ Knowledge Lab** — full v3-style implementation, new
- **Эксперт** — full v3-style implementation, new
- **Кузница (Veteran)** — placeholder, profile only (activated future)
- **Other 6 specialists** — current state preserved (deepened in v4.2+)

---

## COMMUNICATION GLOSSARY (Russian terms used throughout)

For Claude Code working with Russian content:

- **ОСП** = Отдел Стратегического Планирования = Strategic Planning Department
- **СПД / SPD** = Strategic Planning Department (English alias for ОСП)
- **ЛЗ** = Лаборатория знаний = Knowledge Lab
- **Управление** = Management (the coordinator role, Yana)
- **Кузница** = Forge (the methodology evolution role, Veteran)
- **Эксперт** = Expert
- **Препарирование** = Deconstruction (OSP's analytical process)
- **Прогноз** = Forecast
- **Калибровка** = Calibration
- **Шкала Кента** = Sherman Kent scale
- **Боевые вопросы** = Combat questions (Эксперт's main output)
- **Брифинг** = Briefing
- **Архив** = Archive
- **Профиль** = Profile (specialist's library/*.md file)
- **Скилл** = Skill
- **Препарат** = Specimen / dissected analysis (OSP slang for an Analysis record)
- **Бенефициар** = Beneficiary

---

## FINAL NOTE

This document captures the WHY. The HOW is in MIGRATION_PLAN.md. The DISCIPLINE is in CLAUDE_CODE_BRIEF.md. The METHODOLOGY is in METHODOLOGY-v1.md and the skill files.

Together these four documents are sufficient for Claude Code to execute the migration without losing the meaning behind decisions.

If something seems unclear or contradictory — that's a signal something is wrong, not a license to invent. Ask the owner.

---

**End of CONTEXT_HANDOFF.md**
