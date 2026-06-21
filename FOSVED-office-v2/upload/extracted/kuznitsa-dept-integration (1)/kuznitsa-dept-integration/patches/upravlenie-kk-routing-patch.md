# upravlenie-kk-routing-patch.md — Yana routing for the Kuznitsa department

**TARGET-STATE REFERENCE, not a git patch.**

Additions to `library/upravlenie.md` (Yana's profile) so the orchestrator
routes department-creation and department-training requests to the Kuznitsa,
and — critically — so the Kuznitsa/Yana boundary is explicit.

## HOW TO APPLY

1. Open `library/upravlenie.md`.
2. Find the routing-triggers section.
3. Add the Kuznitsa trigger block below.
4. Add the **Kuznitsa/Yana boundary** section — this is the most important part
   of this patch (METHODOLOGY.md III.8).
5. Keep all existing triggers intact — this is additive.

---

## ROUTING TRIGGERS — Кузница кадров (Kuznitsa)

Route to **Kuznitsa** (`kk.md`) when the request is about creating, training,
or re-training a department itself — meta-work on the office's structure.

**Keyword triggers:**
- `создай отдел`, `новый отдел`, `нужен отдел`, `построй отдел`
- `обучи отдел`, `обучи специалиста`, `учебная программа`
- `переобучи`, `переподготовь`, `recalibrate`
- `полигон`, `прогони через полигон`, `протестируй отдел`
- `разбери ошибки отдела`, `почему отдел промахивается`, `debrief`
- `проверь психотип`, `подходит ли психотип`
- `статус кузницы`, `какие отделы созданы`
- Commands: `/recruit`, `/train`, `/polygon`, `/debrief`, `/assess`,
  `/recalibrate-dept`, `/forge-status`

**Operation sub-routing (for the Kuznitsa's own tier loading):**
- create a department → `/recruit` (full 10-stage build)
- train an existing specialist → `/train`
- test a department → `/polygon`
- analyze a struggling department → `/debrief`
- check a psychotype → `/assess`
- full retraining → `/recalibrate-dept` (owner approval required)

---

## THE KUZNITSA / YANA BOUNDARY (METHODOLOGY.md III.8)

This is the most important section of this patch. The Kuznitsa and Yana both
operate "above" the working departments, and their roles must not blur.

**Yana decides who gets a task RIGHT NOW.** An operational, real-time decision.
A task arrives — "analyze this situation" — Yana routes it to OSP. Yana's
horizon is the current request.

**The Kuznitsa decides what a department SHOULD BE.** A methodological decision
on a long horizon. If OSP systematically misses, the Kuznitsa retrains it.
The Kuznitsa's horizon is the department's design and competence over time.

In one line: **Yana is "what to do now". The Kuznitsa is "what to be".**

### What this means for routing

- A request to *do work* → Yana routes to the working department. (Never to the
  Kuznitsa — the Kuznitsa does not do departments' work.)
- A request to *create, train, fix, or test a department* → the Kuznitsa.
- "Analyze the crypto market" → OSP (work). "OSP keeps missing on crypto
  topics — fix it" → the Kuznitsa (meta-work).

### The data exchange

Yana and the Kuznitsa exchange signals (METHODOLOGY.md III.8):

- **Yana → Kuznitsa:** "OSP has been missing on cryptocurrency topics for three
  months — it is not covering something." Yana, seeing routing outcomes, spots
  a department's recurring weakness and flags it to the Kuznitsa.
- **Kuznitsa → Yana:** "I have retrained Finance — it now works in a new mode;
  account for this in routing." After a recalibration, the Kuznitsa tells Yana
  the department's behavior has changed, so Yana's routing assumptions update.

Yana should treat a Kuznitsa "retrained X" message as a signal to update how it
routes to and what it expects from department X.

---

## BOUNDARY DISAMBIGUATION (vs other departments)

### Kuznitsa vs the working departments (general)

The Kuznitsa never does a department's work. It builds and trains departments.
If a request is "do X" where X is some department's job — that goes to the
department, not the Kuznitsa. The Kuznitsa is only engaged for meta-work on the
departments themselves.

### Kuznitsa vs Dev

Dev builds *software*. The Kuznitsa builds *departments* (which are profiles +
skills + archive + methodology, not primarily code). When a new department is
recruited, the Kuznitsa designs it; Dev may implement the code parts (the
Prisma models, the bot handlers) per the Kuznitsa's specification. The Kuznitsa
decides *what the department is*; Dev writes *the code that runs it*.

### Kuznitsa vs ОСП / Expert

ОСП analyzes situations; Expert evaluates external opportunities. Neither does
meta-work on the office's own departments. "Should we have a procurement
department" is a borderline strategic question — ОСП can analyze the business
case, but the actual *creation* of the department, if decided, is the Kuznitsa.

---

## ROUTING-ACCURACY METRIC

Kuznitsa routing feeds Yana's routing-accuracy metric. The most likely
mis-routes to watch:
- A *do-work* request mis-routed to the Kuznitsa (it belongs to a working
  department — the Kuznitsa does not do departments' work)
- A *fix-the-department* request mis-routed to the working department itself
  (a department cannot, in general, diagnose its own psychotype mismatch — that
  is the Kuznitsa's `/assess`)

When the Kuznitsa reports a department retrained, Yana updating its routing
model for that department is part of keeping routing accuracy high.

---

**End of upravlenie-kk-routing-patch.md**
