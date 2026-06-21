// ============================================================================
// army-engineering-patch.js — additions to army.js for the Engineering dept
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// Apply manually — don't blind-copy. army.js already has OSP, ЛЗ, Expert,
// Visual, Yana, the DDQ departments and Marketing.
//
// HOW TO APPLY:
// 1. Open army.js
// 2. Add the engineering aliases to SPECIALISTS
// 3. Add the 12 skill entries to SKILLS_MAP
// 4. Verify: grep -c "fosved/engineering" army.js  → expect 12
// ============================================================================

// ─── Additions to SPECIALISTS map ────────────────────────────────────────────

const SPECIALISTS_ENGINEERING_ADDITIONS = {
  'инженер':              'engineering.md',
  'инженерный':           'engineering.md',
  'инженерный отдел':     'engineering.md',
  'инженерия':            'engineering.md',
  'engineering':          'engineering.md',
  'расчёт':               'engineering.md',
  'расчет':               'engineering.md',
  'конструктор':          'engineering.md',
  'несущая способность':  'engineering.md',
  'гидравлика':           'engineering.md',
  'инвертор':             'engineering.md',
  'силовая электроника':  'engineering.md'
};

// ─── Additions to SKILLS_MAP ─────────────────────────────────────────────────

const SKILLS_MAP_ENGINEERING_ADDITIONS = {
  // Tier 1 — methodological core (always loaded with the department)
  'engineering-disclaimer-discipline': 'skills/fosved/engineering/engineering-disclaimer-discipline/SKILL.md', // T1
  'norm-base-fixation':                'skills/fosved/engineering/norm-base-fixation/SKILL.md',                // T1
  'load-case-enumeration':             'skills/fosved/engineering/load-case-enumeration/SKILL.md',             // T1
  'independent-verification':          'skills/fosved/engineering/independent-verification/SKILL.md',          // T1
  'calculation-documentation':         'skills/fosved/engineering/calculation-documentation/SKILL.md',         // T1

  // Tier 2 — domain depth (loaded by discipline block)
  // — structural mechanics —
  'structural-load-bearing':           'skills/fosved/engineering/structural-load-bearing/SKILL.md',           // T2
  'structural-elements-sizing':        'skills/fosved/engineering/structural-elements-sizing/SKILL.md',        // T2
  // — hydraulics —
  'hydraulic-drive-design':            'skills/fosved/engineering/hydraulic-drive-design/SKILL.md',            // T2
  // — power electronics —
  'power-electronics-inverter':        'skills/fosved/engineering/power-electronics-inverter/SKILL.md',        // T2
  'renewable-system-matching':         'skills/fosved/engineering/renewable-system-matching/SKILL.md',         // T2

  // Tier 3 — special techniques (loaded on explicit request)
  'feasibility-estimation':            'skills/fosved/engineering/feasibility-estimation/SKILL.md',            // T3
  'third-party-calc-review':           'skills/fosved/engineering/third-party-calc-review/SKILL.md'            // T3
};

// ─── Tier loading logic ──────────────────────────────────────────────────────
//
// When the Engineering department is invoked, always load its 5 Tier 1 skills.
// Load the Tier 2 block by discipline; Tier 3 only on explicit request.
//
//   always (T1): engineering-disclaimer-discipline, norm-base-fixation,
//                load-case-enumeration, independent-verification,
//                calculation-documentation
//
//   structural task (roof, greenhouse, frame, load-bearing)
//        → +structural-load-bearing +structural-elements-sizing
//   hydraulic task (lift, drive, actuator)
//        → +hydraulic-drive-design
//   power-electronics task (inverter, switching, wind/solar)
//        → +power-electronics-inverter +renewable-system-matching
//
//   T3 (explicit only):
//     early "is this possible" screening → feasibility-estimation
//     reviewing someone else's calculation → third-party-calc-review
//
// IMPORTANT: the Tier 1 disclaimer skill is non-optional and governs every
// output. The department is a project ASSISTANT — every result is preliminary
// and requires a licensed engineer's review and signature.
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  SPECIALISTS_ENGINEERING_ADDITIONS,
  SKILLS_MAP_ENGINEERING_ADDITIONS
};
