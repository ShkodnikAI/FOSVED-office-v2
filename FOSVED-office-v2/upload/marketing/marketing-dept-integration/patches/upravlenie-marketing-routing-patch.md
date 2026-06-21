# upravlenie-marketing-routing-patch.md — Yana routing for the Marketing department

**TARGET-STATE REFERENCE, not a git patch.**

Additions to `library/upravlenie.md` (Yana's profile) so the orchestrator
routes market-research and promotion requests to the Marketing department and
handles its boundaries with the existing departments.

## HOW TO APPLY

1. Open `library/upravlenie.md`.
2. Find the routing-triggers section.
3. Add the Marketing trigger block below.
4. Add the boundary-disambiguation notes — these prevent collisions with OSP,
   ЛЗ, Design, Visual, Expert and Finance.
5. Keep all existing triggers intact — this is additive.

---

## ROUTING TRIGGERS — Продвижение (Marketing)

Route to **Marketing** (`marketing.md`) when the request is about
understanding a market/audience or promoting a product or service.

**Keyword triggers — research mode:**
- `исследуй рынок`, `исследование рынка`, `анализ рынка`
- `целевая аудитория`, `кто наш клиент`, `сегмент`, `сегментация`
- `конкуренты`, `анализ конкурентов`, `competitive`
- `сколько стоит привлечь клиента`, `CAC`, `unit-экономика` (маркетинговая часть)
- `какие каналы`, `где продвигать`, `где наша аудитория`

**Keyword triggers — campaign / creative mode:**
- `продвинь`, `продвижение`, `реклама`, `рекламная кампания`
- `кампания`, `запусти кампанию`
- `позиционирование`, `рекламный текст`, `рекламное сообщение`, `слоган`
- `как продать`, `как привлечь клиентов`, `привлечение`
- `A/B тест` (рекламных сообщений), `запуск продукта` (маркетинговая часть)
- Commands: `/market-research`, `/segment`, `/competitors`, `/campaign`,
  `/campaign-forecast`, `/campaign-verify`, `/marketing-score`,
  `/marketing-archive`

**Task-type sub-routing (for the department's own tier loading):**
- research request → loads `market-research-methods`, `competitive-analysis`
- campaign request → loads `positioning-and-messaging`, `channel-strategy`
- economics question → loads `unit-economics-and-cac`
- A/B test / product launch → loads the Tier 3 skills

---

## BOUNDARY DISAMBIGUATION

These notes keep Marketing from mis-routing against existing departments.

### Marketing vs ОСП (Analysis)

- **ОСП** analyzes *strategic situations* — "what is happening, what scenarios
  are possible". Probabilistic, broad.
- **Marketing** analyzes *markets and audiences* — "who is the buyer, how do we
  reach them". Concrete, conversion-focused.

Disambiguators:
- "проанализируй ситуацию на рынке X стратегически" → **ОСП**
- "кто наша аудитория на рынке X и как до неё дотянуться" → **Marketing**
- "какие сценарии развития рынка" → **ОСП**
- "какой сегмент покупателей выбрать" → **Marketing**

### Marketing vs ЛЗ (Knowledge Lab)

- **ЛЗ** tracks *technologies*.
- **Marketing** tracks *promotion channels and advertising trends*.

"насколько зрелая технология X" → **ЛЗ**. "какие каналы продвижения сейчас
работают" → **Marketing**. No real overlap.

### Marketing vs Design (DDQ)

- **Design** makes the *product interface* — how the product looks and works.
- **Marketing** makes the *advertising creative* — how the product is promoted.

A landing page is the boundary case: structure, layout and UX → **Design**;
the advertising copy, positioning and headline → **Marketing**. They collaborate
on landing pages, with Yana coordinating the handoff.

### Marketing vs Visual

- **Visual** renders infographics and visual artifacts.
- **Marketing** decides the campaign message and may *commission* a visual
  (banner, card) from the Visual department.

"визуализируй данные исследования" → Marketing produces the research, then
requests the visual from **Visual**. Marketing does not render visuals itself.

### Marketing vs Expert

- **Expert** prepares for meetings and evaluates external opportunities and
  partnerships.
- **Marketing** attracts an audience and promotes products.

"подготовь к встрече с инвестором" → **Expert** (Marketing may supply market
understanding as input). "продвинь продукт среди клиентов" → **Marketing**.

### Marketing vs Finance

- **Marketing** forecasts CAC and customer-acquisition payback for campaigns.
- **Finance** runs the overall cashflow model.

Marketing hands its CAC and payback-period forecast to **Finance**, which
integrates it into the broader financial picture. Unit-economics is a shared
boundary: Marketing owns the acquisition-cost side, Finance owns the
whole-business cash position.

---

## MULTI-DEPARTMENT ORCHESTRATION

### Pattern — "Promote a new product"

When the request is to promote something newly built, the pipeline crosses
departments:

```
1. Marketing — research the audience, segment, position, plan channels,
   FORECAST the campaign (forecast-before-launch)
2. Marketing — request campaign visuals from Visual
3. (for a major release) Marketing coordinates a launch with Dev/Design/QA
   via launch-orchestration — product readiness confirmed before any
   public date
4. Marketing — launch, gather actuals
5. Marketing — verify (campaign-verification); hand CAC/payback to Finance
```

Yana orchestrates; Marketing owns the promotion, but depends on Visual (creative
assets), Dev/Design/QA (product readiness for launches) and Finance (cash-flow
integration of CAC).

### Conflict note

Marketing's psychotype is Эмпат + Экспериментатор — it generates many creative
variants and is willing to let most underperform to find a hit. This can clash
with departments that want certainty before acting (QA's Параноик, Finance's
Педант). Yana mediates: Marketing's experiment-and-iterate approach is correct
*for marketing*, but a campaign's forecast and CAC still pass Finance's
cash-flow reality check before a large budget is committed.

---

## ROUTING-ACCURACY METRIC

Marketing routing feeds Yana's standard routing-accuracy metric. A request that
had to be re-routed (e.g. sent to ОСП but belonged to Marketing, or vice versa)
counts as a miss. Recurring Marketing mis-routes signal that a trigger or a
boundary note above needs sharpening — especially the ОСП boundary, which is
the most likely confusion.

---

**End of upravlenie-marketing-routing-patch.md**
