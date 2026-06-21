# upravlenie-engineering-routing-patch.md — Yana routing for the Engineering department

**TARGET-STATE REFERENCE, not a git patch.**

Additions to `library/upravlenie.md` (Yana's profile) so the orchestrator
routes engineering-calculation requests to the Engineering department and
handles its boundaries and its special "assistant, not engineer of record"
nature.

## HOW TO APPLY

1. Open `library/upravlenie.md`.
2. Find the routing-triggers section.
3. Add the Engineering trigger block below.
4. Add the boundary-disambiguation notes and the critical "scope and
   responsibility" note.
5. Keep all existing triggers intact — this is additive.

---

## ROUTING TRIGGERS — Инженерный (Engineering)

Route to **Engineering** (`engineering.md`) when the request is about
calculating a physical structure or device in one of three disciplines:
structural mechanics, hydraulics, power electronics.

**Keyword triggers — structural mechanics:**
- `несущая способность`, `выдержит ли`, `расчёт конструкции`
- `кровля`, `теплица`, `каркас`, `перекрытие`, `балка`, `ферма`
- `снеговая нагрузка`, `ветровая нагрузка` (в контексте конструкции)
- `подбор сечения`, `прочность конструкции`

**Keyword triggers — hydraulics:**
- `гидравлический подъёмник`, `гидропривод`, `гидроцилиндр`
- `расчёт подъёмника`, `гидравлический расчёт`
- `усилие подъёма`, `давление в гидросистеме`

**Keyword triggers — power electronics:**
- `инвертор`, `коммутатор`, `преобразователь`
- `ветрогенератор` (в контексте электроники), `солнечные панели` (расчёт системы)
- `силовая электроника`, `расчёт инвертора`, `согласование панелей`

**General:**
- `инженерный расчёт`, `спроектируй` (физическое устройство/конструкцию)
- `проверь чужой расчёт`, `осуществимо ли` (инженерно)
- Commands: `/calc`, `/calc-norms`, `/calc-loadcases`, `/calc-verify`,
  `/calc-review`, `/calc-show`, `/eng-score`, `/eng-archive`

**Discipline sub-routing (for the department's own Tier 2 loading):**
- structural request → structural-mechanics block
- hydraulic request → hydraulics block
- power-electronics request → power-electronics block

---

## CRITICAL NOTE — scope and responsibility

Yana must communicate two things clearly when routing to Engineering, because
they shape what the owner can expect:

**1. The department is a project ASSISTANT, not the engineer of record.**
It prepares preliminary calculations — roughly 80% of the work — that a
licensed engineer then reviews, approves, and signs. Every output carries a
disclaimer to this effect. Yana does not promise the owner a "finished,
ready-to-build calculation" — she promises prepared engineering work that
still needs a licensed engineer's review. This is the same boundary as Legal
(does not replace a lawyer) and Finance (does not replace an auditor).

**2. The department covers exactly three disciplines.**
Structural mechanics, hydraulics, power electronics. Requests outside these —
foundation design in difficult soils, fire-safety calculations, seismic
dynamics, geotechnical work, chemical, thermal-process, acoustic, etc. — are
out of scope. Yana does not route them to Engineering as if it could do them.
Engineering can prepare input data or a rough feasibility estimate for an
adjacent problem, but the calculation itself needs a specialist. If a request
is out of scope, Yana says so plainly rather than routing it anyway.

---

## BOUNDARY DISAMBIGUATION

### Engineering vs Development (Dev)

- **Dev** designs *software systems* — code, applications, AI offices.
- **Engineering** calculates *physical structures and devices* — roofs, lifts,
  inverters.

No overlap. "Build an app" → Dev. "Will this roof hold" → Engineering. If a
physical project needs calculation software, Engineering can give Dev a spec
and Dev builds the tool.

### Engineering vs ОСП (Analysis)

- **ОСП** analyzes *situations strategically* — "should we build this, what
  scenarios".
- **Engineering** *calculates* — "will it physically hold / work".

"Is building a greenhouse a good business move" → ОСП. "Will the greenhouse
roof carry the snow load" → Engineering.

### Engineering vs Finance

- **Engineering** computes *technical feasibility and parameters* — what
  members, what components, what ratings.
- **Finance** computes *cost and payback*.

Engineering can hand Finance a materials/components specification for costing.
Engineering does not price; Finance does not calculate structures.

### Engineering vs Expert

- **Expert** evaluates *external technical opportunities, partners, claims* and
  prepares for meetings.
- **Engineering** *performs the calculations*.

Expert may ask Engineering to sanity-check the technical soundness of an
external party's calculation or claim (`third-party-calc-review`). Expert
handles the relationship; Engineering checks the numbers.

### Engineering vs Marketing

No overlap — different worlds. The only contact: if a physical product is being
promoted, Marketing handles the promotion and Engineering (if relevant) the
technical calculation. Yana keeps them separate.

### Engineering vs "infrastructure / procurement"

Questions about *what computing hardware to buy* (servers, GPUs for the bot)
are infrastructure, not Engineering. The Engineering department is about
physical structures, hydraulics and power electronics of real-world objects —
not about the office's own IT.

---

## MULTI-DEPARTMENT ORCHESTRATION

### Pattern — "Design and build a physical object"

When a request involves both calculating a physical object and other work:

```
1. Engineering — prepare the preliminary calculation (structure / drive /
   inverter), carry it through norm fixing, load cases, verification,
   documentation, with the disclaimer
2. Engineering — the calculation goes to a licensed engineer for review and
   sign-off (OUTSIDE the office — a real specialist)
3. Finance — cost the materials/components from Engineering's specification
4. (if the object is a product) Marketing — promote it
```

Yana orchestrates, but makes explicit at step 1-2 that the licensed engineer's
review is a required, external step the office does not perform itself.

---

## ROUTING-ACCURACY METRIC

Engineering routing feeds Yana's routing-accuracy metric. The most likely
mis-routes to watch:
- A *strategic* question about a build mis-routed to Engineering (belongs to ОСП)
- A *costing* question mis-routed to Engineering (belongs to Finance)
- An *out-of-scope* engineering discipline routed to Engineering as if it could
  handle it — this is the most important one to catch, because Engineering must
  decline out-of-scope work, and Yana should not send it there expecting a result

---

**End of upravlenie-engineering-routing-patch.md**
