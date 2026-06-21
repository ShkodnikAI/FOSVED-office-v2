// ============================================================================
// army-kk-patch.js — additions to army.js for the Kuznitsa department
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// Apply manually — don't blind-copy. army.js already has OSP, ЛЗ, Expert,
// Visual, Yana, the DDQ departments, Marketing and Engineering.
//
// HOW TO APPLY:
// 1. Open army.js
// 2. Add the kk aliases to SPECIALISTS
// 3. Add the 8 skill entries to SKILLS_MAP
// 4. Verify: grep -c "fosved/kk" army.js  → expect 8
// ============================================================================

// ─── Additions to SPECIALISTS map ────────────────────────────────────────────

const SPECIALISTS_KK_ADDITIONS = {
  'кузница':            'kk.md',
  'кузница кадров':     'kk.md',
  'ветеран':            'kk.md',
  'kuznitsa':           'kk.md',
  'kk':                 'kk.md',
  'veteran':            'kk.md',
  'обучение отделов':   'kk.md',
  'создание отдела':    'kk.md',
  'переобучение':       'kk.md',
  'полигон':            'kk.md'
};

// ─── Additions to SKILLS_MAP ─────────────────────────────────────────────────

const SKILLS_MAP_KK_ADDITIONS = {
  // Tier 1 — methodological core (always loaded with the department)
  'methodology-application':    'skills/fosved/kk/methodology-application/SKILL.md',    // T1
  'specialist-creation':        'skills/fosved/kk/specialist-creation/SKILL.md',        // T1
  'psychotype-assessment':      'skills/fosved/kk/psychotype-assessment/SKILL.md',      // T1
  'skill-quality-review':       'skills/fosved/kk/skill-quality-review/SKILL.md',       // T1
  'debrief-protocol':           'skills/fosved/kk/debrief-protocol/SKILL.md',           // T1

  // Tier 2 — domain depth (loaded by operation type)
  'training-program-design':    'skills/fosved/kk/training-program-design/SKILL.md',    // T2
  'polygon-test-design':        'skills/fosved/kk/polygon-test-design/SKILL.md',        // T2

  // Tier 3 — special techniques (loaded on explicit request)
  'recalibration-orchestration':'skills/fosved/kk/recalibration-orchestration/SKILL.md' // T3
};

// ─── Tier loading logic ──────────────────────────────────────────────────────
//
// When the Kuznitsa is invoked, always load its 5 Tier 1 skills.
// Load Tier 2 by operation; Tier 3 only on explicit request.
//
//   always (T1): methodology-application, specialist-creation,
//                psychotype-assessment, skill-quality-review, debrief-protocol
//
//   /recruit  → +training-program-design +polygon-test-design (full build)
//   /train    → +training-program-design
//   /polygon  → +polygon-test-design
//   /debrief  → (Tier 1 covers it — psychotype-assessment + debrief-protocol)
//   /assess   → (Tier 1 — psychotype-assessment)
//
//   T3 (explicit only):
//     /recalibrate-dept → recalibration-orchestration
//
// NOTE: the Kuznitsa is the RECURSIVE department — it was itself built by the
// methodology in these skills. METHODOLOGY.md Part III is its specification.
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  SPECIALISTS_KK_ADDITIONS,
  SKILLS_MAP_KK_ADDITIONS
};
