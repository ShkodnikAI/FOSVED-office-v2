// ============================================================================
// army-marketing-patch.js — additions to army.js for the Marketing department
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// Apply manually: add entries to existing army.js arrays/maps.
// Don't blind-copy — army.js already has OSP, ЛЗ, Expert, Visual, Yana, and
// the DDQ departments (dev/design/qa).
//
// HOW TO APPLY:
// 1. Open army.js
// 2. Add the marketing aliases to SPECIALISTS
// 3. Add the 11 skill entries to SKILLS_MAP
// 4. Verify: grep -c "fosved/marketing" army.js  → expect 11
// ============================================================================

// ─── Additions to SPECIALISTS map ────────────────────────────────────────────

const SPECIALISTS_MARKETING_ADDITIONS = {
  'маркетинг':           'marketing.md',
  'маркетолог':          'marketing.md',
  'продвижение':         'marketing.md',
  'отдел продвижения':   'marketing.md',
  'отдел маркетинга':    'marketing.md',
  'реклама':             'marketing.md',
  'marketing':           'marketing.md',
  'исследование рынка':  'marketing.md',
  'целевая аудитория':   'marketing.md',
  'кампания':            'marketing.md',
  'продвижение товаров': 'marketing.md'
};

// ─── Additions to SKILLS_MAP ─────────────────────────────────────────────────

const SKILLS_MAP_MARKETING_ADDITIONS = {
  // Tier 1 — methodological core (always loaded with the department)
  'audience-segmentation':    'skills/fosved/marketing/audience-segmentation/SKILL.md',     // T1
  'forecast-before-launch':   'skills/fosved/marketing/forecast-before-launch/SKILL.md',    // T1
  'campaign-verification':    'skills/fosved/marketing/campaign-verification/SKILL.md',     // T1
  'honest-claims-discipline': 'skills/fosved/marketing/honest-claims-discipline/SKILL.md',  // T1

  // Tier 2 — domain depth (loaded by task type)
  'market-research-methods':  'skills/fosved/marketing/market-research-methods/SKILL.md',   // T2
  'competitive-analysis':     'skills/fosved/marketing/competitive-analysis/SKILL.md',      // T2
  'unit-economics-and-cac':   'skills/fosved/marketing/unit-economics-and-cac/SKILL.md',    // T2
  'positioning-and-messaging':'skills/fosved/marketing/positioning-and-messaging/SKILL.md', // T2
  'channel-strategy':         'skills/fosved/marketing/channel-strategy/SKILL.md',          // T2

  // Tier 3 — special techniques (loaded on explicit request / major launches)
  'ab-testing-protocol':      'skills/fosved/marketing/ab-testing-protocol/SKILL.md',       // T3
  'launch-orchestration':     'skills/fosved/marketing/launch-orchestration/SKILL.md'       // T3
};

// ─── Tier loading logic ──────────────────────────────────────────────────────
//
// When the Marketing department is invoked, always load its 4 Tier 1 skills.
// Load Tier 2 by task type; Tier 3 only on explicit request / major launch.
//
//   always (T1): audience-segmentation, forecast-before-launch,
//                campaign-verification, honest-claims-discipline
//
//   research-mode task   → +market-research-methods +competitive-analysis
//   economics question   → +unit-economics-and-cac
//   campaign / creative  → +positioning-and-messaging +channel-strategy
//                          (+unit-economics-and-cac for the CAC go/no-go)
//
//   T3 (explicit only):
//     A/B testing a campaign     → ab-testing-protocol
//     full product launch        → launch-orchestration
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  SPECIALISTS_MARKETING_ADDITIONS,
  SKILLS_MAP_MARKETING_ADDITIONS
};
