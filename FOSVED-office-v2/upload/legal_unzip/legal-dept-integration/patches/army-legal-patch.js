// patches/army-legal-patch.js
// Legal — patch for army.js

const SPECIALISTS_ADDITIONS = {
  'юрист':         'legal.md',
  'юр':            'legal.md',
  'юриспруденция': 'legal.md',
  'право':         'legal.md',
  'legal':         'legal.md',
  'lawyer':        'legal.md',
};

const SKILLS_MAP_ADDITIONS = {
  // Tier 1
  'risk-mapping-protocol':         'fosved/legal/risk-mapping-protocol/SKILL.md',
  'contract-drafting-discipline':  'fosved/legal/contract-drafting-discipline/SKILL.md',
  'red-flag-detection':            'fosved/legal/red-flag-detection/SKILL.md',
  'cross-jurisdiction-comparison': 'fosved/legal/cross-jurisdiction-comparison/SKILL.md',
  'precedent-search-application':  'fosved/legal/precedent-search-application/SKILL.md',
  // Tier 2
  'nda-msa-sla-templates':         'fosved/legal/nda-msa-sla-templates/SKILL.md',
  'gdpr-compliance-check':         'fosved/legal/gdpr-compliance-check/SKILL.md',
  'ip-clause-discipline':          'fosved/legal/ip-clause-discipline/SKILL.md',
  'consumer-protection-check':     'fosved/legal/consumer-protection-check/SKILL.md',
  // Tier 3
  'dispute-resolution-strategy':   'fosved/legal/dispute-resolution-strategy/SKILL.md',
};

// COLLISION CHECK before applying:
//   node -e "
//   const army = require('./army.js');
//   const p = require('./patches/army-legal-patch.js');
//   for (const k of Object.keys(p.SPECIALISTS_ADDITIONS)) {
//     if (army.SPECIALISTS[k]) console.log('COLLISION:', k);
//   }
//   for (const k of Object.keys(p.SKILLS_MAP_ADDITIONS)) {
//     if (army.SKILLS_MAP[k]) console.log('COLLISION:', k);
//   }
//   "

module.exports = { SPECIALISTS_ADDITIONS, SKILLS_MAP_ADDITIONS };
