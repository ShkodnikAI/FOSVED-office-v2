// ============================================================================
// army-visual-patch.js — additions to army.js for Visual Department
// ============================================================================
//
// This is a TARGET-STATE REFERENCE, not a git patch.
// Apply manually: read this file, add entries to existing army.js arrays/maps.
// Don't blind-copy — army.js has existing specialists, don't lose them.
//
// HOW TO APPLY:
// 1. Open army.js
// 2. Locate SPECIALISTS object
// 3. Add visual aliases entries (see below)
// 4. Locate SKILLS_MAP object
// 5. Add visual skills entries with proper tier comments (see below)
// 6. Save and verify: grep -c "visual" army.js (should be 12+)
// ============================================================================

// ─── Additions to SPECIALISTS map ────────────────────────────────────────────

const SPECIALISTS_VISUAL_ADDITIONS = {
  // Add these to existing SPECIALISTS object:

  'визуал':              'visual.md',
  'визуальный':          'visual.md',
  'визуальный отдел':    'visual.md',
  'инфографика':         'visual.md',
  'инфографики':         'visual.md',
  'visual':              'visual.md',
  'visualization':       'visual.md',
  'infographic':         'visual.md',
  'design':              'visual.md'
};

// ─── Additions to SKILLS_MAP ─────────────────────────────────────────────────

const SKILLS_MAP_VISUAL_ADDITIONS = {
  // Visual Department skills (11 total: 5 T1 + 5 T2 + 1 T3)
  // Tier 1 — methodological core (always loaded with department)
  'visual-grammar':             'skills/fosved/visual/visual-grammar/SKILL.md',           // T1
  'infographic-templates':      'skills/fosved/visual/infographic-templates/SKILL.md',    // T1
  'data-to-visual-mapping':     'skills/fosved/visual/data-to-visual-mapping/SKILL.md',   // T1
  'compression-principle':      'skills/fosved/visual/compression-principle/SKILL.md',    // T1
  'style-evolution-discipline': 'skills/fosved/visual/style-evolution-discipline/SKILL.md', // T1

  // Tier 2 — production techniques (loaded based on request type)
  'svg-generation':             'skills/fosved/visual/svg-generation/SKILL.md',           // T2
  'memorable-design-techniques':'skills/fosved/visual/memorable-design-techniques/SKILL.md', // T2
  'reference-sheet-composition':'skills/fosved/visual/reference-sheet-composition/SKILL.md', // T2
  'premium-spec-generation':    'skills/fosved/visual/premium-spec-generation/SKILL.md',  // T2
  'type-system-application':    'skills/fosved/visual/type-system-application/SKILL.md',  // T2

  // Tier 3 — special techniques (loaded for quarterly evolution work)
  'visual-pattern-discovery':   'skills/fosved/visual/visual-pattern-discovery/SKILL.md'  // T3
};

// ─── Tier loading logic ─────────────────────────────────────────────────────
//
// When visual department is invoked, always load Tier 1 skills.
// Load Tier 2 based on operation type:
//   - /visual card → +svg-generation, +type-system-application
//   - /visual memorable → +svg-generation, +memorable-design-techniques, +type-system-application
//   - /visual reference → +svg-generation, +reference-sheet-composition, +type-system-application
//   - /visual compression → +svg-generation, +type-system-application
//   - /visual-spec → +premium-spec-generation, +memorable-design-techniques
//
// Load Tier 3 only for:
//   - quarterlyStyleEvolution → +visual-pattern-discovery
//   - Owner explicit request → +visual-pattern-discovery
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  SPECIALISTS_VISUAL_ADDITIONS,
  SKILLS_MAP_VISUAL_ADDITIONS
};
