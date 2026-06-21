// patches/army-finance-patch.js
// Finance — patch for army.js
//
// INSTRUCTIONS:
// 1. Open main army.js
// 2. Locate the SPECIALISTS object — add the entries from SPECIALISTS_ADDITIONS below
// 3. Locate the SKILLS_MAP object — add the entries from SKILLS_MAP_ADDITIONS below
//
// After Sweep 0 (which introduces lib/departments-registry.js), SPECIALISTS will
// be auto-generated from the registry. Until then — manual addition here.

// ═══════════════════════════════════════════════════════════════════════
// 1. ADD TO SPECIALISTS
// ═══════════════════════════════════════════════════════════════════════

const SPECIALISTS_ADDITIONS = {
  // Russian aliases
  'финансы':    'finance.md',
  'финанс':     'finance.md',
  'фин':        'finance.md',
  'бухгалтерия': 'finance.md',
  // English aliases
  'finance':    'finance.md',
  'fin':        'finance.md',
};

// ═══════════════════════════════════════════════════════════════════════
// 2. ADD TO SKILLS_MAP
// ═══════════════════════════════════════════════════════════════════════

const SKILLS_MAP_ADDITIONS = {
  // Tier 1 — methodological core (5 skills)
  'cashflow-forecasting':              'fosved/finance/cashflow-forecasting/SKILL.md',
  'invoice-lifecycle-management':      'fosved/finance/invoice-lifecycle-management/SKILL.md',
  'unit-economics-calculation':        'fosved/finance/unit-economics-calculation/SKILL.md',
  'revenue-recognition-discipline':    'fosved/finance/revenue-recognition-discipline/SKILL.md',
  'forecast-verification-protocol':    'fosved/finance/forecast-verification-protocol/SKILL.md',

  // Tier 2 — domain depth (3 skills)
  'tax-compliance-multi-jurisdiction': 'fosved/finance/tax-compliance-multi-jurisdiction/SKILL.md',
  'multi-currency-handling':           'fosved/finance/multi-currency-handling/SKILL.md',
  'mrr-arr-reporting':                 'fosved/finance/mrr-arr-reporting/SKILL.md',

  // Tier 3 — special techniques (1 skill)
  'runway-and-burn-analysis':          'fosved/finance/runway-and-burn-analysis/SKILL.md',
};

// ═══════════════════════════════════════════════════════════════════════
// 3. VERIFICATION BEFORE MERGING
// ═══════════════════════════════════════════════════════════════════════
// Run before merging into army.js:
//
//   node -e "
//   const army = require('./army.js');
//   const patches = require('./patches/army-finance-patch.js');
//   for (const k of Object.keys(patches.SPECIALISTS_ADDITIONS)) {
//     if (army.SPECIALISTS[k]) console.log('COLLISION SPECIALIST:', k);
//   }
//   for (const k of Object.keys(patches.SKILLS_MAP_ADDITIONS)) {
//     if (army.SKILLS_MAP[k]) console.log('COLLISION SKILL:', k);
//   }
//   "
// Should print nothing if no collisions.

module.exports = {
  SPECIALISTS_ADDITIONS,
  SKILLS_MAP_ADDITIONS,
};
