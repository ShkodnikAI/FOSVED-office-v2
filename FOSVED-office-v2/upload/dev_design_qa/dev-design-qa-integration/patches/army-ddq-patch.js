// ============================================================================
// army-ddq-patch.js — additions to army.js for Dev + Design + QA departments
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// Apply manually: read this file, add entries to existing army.js arrays/maps.
// Don't blind-copy — army.js already has OSP, ЛЗ, Expert, Yana, Visual.
//
// HOW TO APPLY:
// 1. Open army.js
// 2. Locate SPECIALISTS object → add the dev/design/qa aliases below
// 3. Locate SKILLS_MAP object → add the 43 skill entries below
// 4. Save and verify:
//      grep -c "fosved/dev\|fosved/design\|fosved/qa" army.js   → expect 43
// ============================================================================

// ─── Additions to SPECIALISTS map ────────────────────────────────────────────

const SPECIALISTS_DDQ_ADDITIONS = {
  // — Разработка (Dev) —
  'разработка':        'dev.md',
  'разработчик':       'dev.md',
  'дев':               'dev.md',
  'отдел разработки':  'dev.md',
  'dev':               'dev.md',
  'development':       'dev.md',
  'код':               'dev.md',
  'кодинг':            'dev.md',

  // — Дизайн (Design) —
  'дизайн':            'design.md',
  'дизайнер':          'design.md',
  'отдел дизайна':     'design.md',
  'design':            'design.md',
  'ui':                'design.md',
  'ux':                'design.md',
  'интерфейс':         'design.md',

  // — Тестирование (QA) —
  'тестирование':      'qa.md',
  'тестировщик':       'qa.md',
  'отдел тестирования':'qa.md',
  'qa':                'qa.md',
  'тест':              'qa.md',
  'тесты':             'qa.md',
  'тестинг':           'qa.md'
};

// NOTE on collisions: the Visual department already claims 'design' as an alias
// in army-visual-patch.js. Resolve in favour of context — Yana routing
// (upravlenie-ddq-routing-patch.md) disambiguates "дизайн интерфейса" (Design
// dept) vs "инфографика/визуализация" (Visual dept). If army.js does direct
// alias lookup, keep 'design' → 'design.md' here and let Visual keep only
// 'визуал'/'инфографика'. Adjust the Visual patch's 'design' entry accordingly.

// ─── Additions to SKILLS_MAP ─────────────────────────────────────────────────

const SKILLS_MAP_DDQ_ADDITIONS = {
  // ===== Разработка (Dev) — 20 skills (5 T1 + 12 T2 + 3 T3) =====

  // Tier 1 — methodological core (always loaded with department)
  'architecture-decision-records': 'skills/fosved/dev/architecture-decision-records/SKILL.md', // T1
  'estimation-discipline':         'skills/fosved/dev/estimation-discipline/SKILL.md',          // T1
  'code-organization-standards':   'skills/fosved/dev/code-organization-standards/SKILL.md',    // T1
  'tech-radar-maintenance':        'skills/fosved/dev/tech-radar-maintenance/SKILL.md',         // T1
  'iterative-implementation':      'skills/fosved/dev/iterative-implementation/SKILL.md',       // T1

  // Tier 2 — domain depth (loaded by task type)
  'nextjs-architecture':           'skills/fosved/dev/nextjs-architecture/SKILL.md',            // T2
  'database-design':               'skills/fosved/dev/database-design/SKILL.md',                // T2
  'api-design':                    'skills/fosved/dev/api-design/SKILL.md',                     // T2
  'agent-architecture':            'skills/fosved/dev/agent-architecture/SKILL.md',             // T2
  'llm-integration':               'skills/fosved/dev/llm-integration/SKILL.md',                // T2
  'multi-agent-orchestration':     'skills/fosved/dev/multi-agent-orchestration/SKILL.md',      // T2
  'local-model-deployment':        'skills/fosved/dev/local-model-deployment/SKILL.md',         // T2
  'model-fine-tuning':             'skills/fosved/dev/model-fine-tuning/SKILL.md',              // T2
  'devops-deployment':             'skills/fosved/dev/devops-deployment/SKILL.md',              // T2
  'observability-setup':           'skills/fosved/dev/observability-setup/SKILL.md',            // T2
  'refactoring-discipline':        'skills/fosved/dev/refactoring-discipline/SKILL.md',         // T2
  'dependency-management':         'skills/fosved/dev/dependency-management/SKILL.md',          // T2

  // Tier 3 — special techniques (loaded on explicit request / major decisions)
  'performance-optimization':      'skills/fosved/dev/performance-optimization/SKILL.md',       // T3
  'security-hardening':            'skills/fosved/dev/security-hardening/SKILL.md',             // T3
  'legacy-system-modernization':   'skills/fosved/dev/legacy-system-modernization/SKILL.md',    // T3

  // ===== Дизайн (Design) — 12 skills (5 T1 + 5 T2 + 2 T3) =====

  // Tier 1 — methodological core
  'user-task-analysis':            'skills/fosved/design/user-task-analysis/SKILL.md',          // T1
  'design-system-thinking':        'skills/fosved/design/design-system-thinking/SKILL.md',      // T1
  'accessibility-first':           'skills/fosved/design/accessibility-first/SKILL.md',         // T1
  'design-tokens-discipline':      'skills/fosved/design/design-tokens-discipline/SKILL.md',    // T1
  'cognitive-laws-application':    'skills/fosved/design/cognitive-laws-application/SKILL.md',   // T1

  // Tier 2 — production techniques
  'wireframe-production':          'skills/fosved/design/wireframe-production/SKILL.md',         // T2
  'interaction-states':            'skills/fosved/design/interaction-states/SKILL.md',           // T2
  'responsive-design':             'skills/fosved/design/responsive-design/SKILL.md',            // T2
  'component-library-development': 'skills/fosved/design/component-library-development/SKILL.md',// T2
  'dev-handoff-specs':             'skills/fosved/design/dev-handoff-specs/SKILL.md',            // T2

  // Tier 3 — special techniques
  'user-research-methods':         'skills/fosved/design/user-research-methods/SKILL.md',        // T3
  'conversational-ui-design':      'skills/fosved/design/conversational-ui-design/SKILL.md',     // T3

  // ===== Тестирование (QA) — 11 skills (4 T1 + 5 T2 + 2 T3) =====

  // Tier 1 — methodological core
  'test-strategy-design':          'skills/fosved/qa/test-strategy-design/SKILL.md',             // T1
  'failure-modes-mapping':         'skills/fosved/qa/failure-modes-mapping/SKILL.md',            // T1
  'defect-discipline':             'skills/fosved/qa/defect-discipline/SKILL.md',                // T1
  'regression-test-discipline':    'skills/fosved/qa/regression-test-discipline/SKILL.md',       // T1

  // Tier 2 — production techniques
  'unit-testing-craft':            'skills/fosved/qa/unit-testing-craft/SKILL.md',               // T2
  'integration-testing-patterns':  'skills/fosved/qa/integration-testing-patterns/SKILL.md',     // T2
  'e2e-testing-with-playwright':   'skills/fosved/qa/e2e-testing-with-playwright/SKILL.md',      // T2
  'security-testing-protocol':     'skills/fosved/qa/security-testing-protocol/SKILL.md',        // T2
  'ai-evals-framework':            'skills/fosved/qa/ai-evals-framework/SKILL.md',               // T2

  // Tier 3 — special techniques
  'performance-testing':           'skills/fosved/qa/performance-testing/SKILL.md',              // T3
  'chaos-engineering':             'skills/fosved/qa/chaos-engineering/SKILL.md'                 // T3
};

// ─── Tier loading logic ──────────────────────────────────────────────────────
//
// When a DDQ department is invoked, always load its Tier 1 skills.
// Load Tier 2 based on task type; Tier 3 only on explicit request.
//
// DEV:
//   always (T1): the 5 core skills above
//   web_app / site task   → +nextjs-architecture +database-design +api-design
//   ai_office task        → +agent-architecture +llm-integration +multi-agent-orchestration
//   local_ai task         → +local-model-deployment +model-fine-tuning
//   any deploy            → +devops-deployment +observability-setup
//   refactor task         → +refactoring-discipline
//   dependency work       → +dependency-management
//   T3 (explicit only)    → performance-optimization | security-hardening | legacy-system-modernization
//
// DESIGN:
//   always (T1): the 5 core skills above
//   wireframing           → +wireframe-production +interaction-states
//   responsive work       → +responsive-design
//   component/system work → +component-library-development
//   handoff to Dev        → +dev-handoff-specs
//   T3 (explicit only)    → user-research-methods | conversational-ui-design
//
// QA:
//   always (T1): the 4 core skills above
//   unit testing          → +unit-testing-craft
//   integration testing   → +integration-testing-patterns
//   e2e testing           → +e2e-testing-with-playwright
//   security testing      → +security-testing-protocol
//   AI feature testing    → +ai-evals-framework
//   T3 (explicit only)    → performance-testing | chaos-engineering
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  SPECIALISTS_DDQ_ADDITIONS,
  SKILLS_MAP_DDQ_ADDITIONS
};
