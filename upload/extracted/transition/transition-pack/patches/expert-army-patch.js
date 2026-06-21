// PATCH for army.js — Expert department v4.1 registration
// Adds Expert to SPECIALISTS and SKILLS_MAP
// Apply by adding these entries to existing army.js v4 SPECIALISTS and SKILLS_MAP

// =============================================================================
// SPECIALISTS — add Expert entry
// =============================================================================

export const SPECIALISTS_EXPERT_ENTRY = {
  expert: {
    aliases: [
      'эксперт', 'expert', 'препаратор', 'due-diligence', 'dd',
      'экспертиза', 'техэксперт', 'attache', 'техатташе'
    ],
    profile: 'library/expert.md',
    skillsDir: 'skills/fosved/expert/',
    archiveModel: 'ExpertBriefing',
    primaryMetric: 'meeting_understanding_score',
    psychotype: {
      primary: 'Скептик-эрудит',
      secondary: 'Параноик',
      tertiary: 'Педант'
    },
    version: '1.0',
    description: 'Technical due diligence preparation for live meetings — generates battle briefings to bring owner from "knows nothing about domain" to "asks meeting-winning questions"'
  }
};

// =============================================================================
// SKILLS_MAP — add Expert skills inventory
// =============================================================================

export const SKILLS_MAP_EXPERT_ENTRY = {
  expert: {
    // Tier 1 — Methodological core (always loaded for any briefing)
    tier1: [
      'rapid-domain-immersion',     // 4-layer scaffold for fast deep-dive
      'project-deconstruction',      // Real shape vs pitch
      'failure-modes-mapping',       // 7-category systematic risk identification
      'combat-questions-design',     // Main output skill
      'bullshit-detection'           // 12 manipulation patterns catalog
    ],

    // Tier 2 — Domain depth (loaded by meeting type)
    tier2: [
      'technical-economics-validation', // BOM/capex/opex testing
      'peer-review-simulation',          // Academic-grade scrutiny
      'adjacent-field-cross-check',      // Multi-field perspective
      'competing-claims-comparison'      // Real competitive landscape
    ],

    // Tier 3 — Special techniques (deep mode only)
    tier3: [
      'pre-meeting-intel',           // OSINT on attendees
      'tactical-meeting-protocol'    // In-meeting performance
    ]
  }
};

// =============================================================================
// SKILL_LOADING_RULES — Expert-specific rules
// =============================================================================

export const SKILL_LOADING_RULES_EXPERT_ENTRY = {
  expert: {
    tier1: {
      trigger: 'always_for_any_briefing'
      // All Tier 1 loads for every Expert briefing regardless of depth
    },
    tier2: {
      trigger: 'depth_or_topic',
      conditions: {
        'technical-economics-validation': {
          trigger: 'investment_or_economic_topic'
          // Loads when meeting involves economic/investment decisions
        },
        'peer-review-simulation': {
          trigger: 'empirical_claims_present'
          // Loads when project makes empirical/scientific claims
        },
        'adjacent-field-cross-check': {
          trigger: 'multidisciplinary_project',
          // Loads when project crosses multiple fields (most serious tech does)
          loadByDefault: true  // default for depth >= 2
        },
        'competing-claims-comparison': {
          trigger: 'competitive_landscape_relevant'
          // Loads when project is in competitive space (almost always)
        }
      }
    },
    tier3: {
      trigger: 'depth_3_only',
      conditions: {
        'pre-meeting-intel': {
          trigger: 'attendees_known_and_significant',
          owner_authorization: 'implicit_via_deepexpert_command'
        },
        'tactical-meeting-protocol': {
          trigger: 'high_stakes_meeting',
          owner_authorization: 'implicit_via_deepexpert_command'
        }
      }
    }
  }
};

// =============================================================================
// Routing triggers for Yana — phrases that route to Expert
// =============================================================================

export const EXPERT_ROUTING_TRIGGERS = [
  // Direct triggers
  'встреча с',
  'meeting with',
  'презентация',
  'pitch',
  'due diligence',
  'разобраться в',
  'подготовь к встрече',
  'мне нужно понять',
  'академия наук',
  'investor meeting',
  'инвестор',
  'investor pitch',
  'fundraising meeting',
  'технический разбор',

  // Expert specific keywords
  'эксперт',
  'препарируй',
  'разбор технологии',
  'разобрать проект',
  'техническая экспертиза',
  'техэкспертиза',

  // Time-bounded triggers (specific feature of Expert)
  'через * часов',
  'через * дней',
  'завтра встреча',
  'через неделю презентация',

  // Context-bounded triggers
  'мне будут показывать',
  'мне предлагают',
  'хотят чтобы я',
  'втюхать',
  'подсунуть',

  // Domain-agnostic technical evaluation
  'разобраться как профессионал',
  'выглядеть подготовленным',
  'не знаю в этой теме',
  'в этой области не разбираюсь'
];

// =============================================================================
// Inter-department interactions — Expert with others
// =============================================================================

export const EXPERT_INTERACTIONS = {
  expert_osp: {
    description: 'Expert + Strategic Intelligence',
    flows: [
      'expert_briefing_strategic_context → osp_provides_macro_context',
      'osp_strategic_topic → expert_briefing_for_specific_meeting',
      'expert_post_briefing_findings → osp_updates_relevant_analyses'
    ],
    example: 'Investment in fusion startup: ОСП analyzes fusion industry trajectory; Expert prepares for specific meeting with FusionCorp leadership'
  },

  expert_lz: {
    description: 'Expert + Technology Intelligence',
    flows: [
      'lz_tracked_technology → expert_briefing_inherits_context',
      'expert_briefing_specific_project → lz_updates_competitive_landscape',
      'lz_inflection_alert → expert_proactive_briefing_prep'
    ],
    example: 'mRNA cancer therapy: ЛЗ tracks mRNA platform technology class; Expert prepares for specific meeting with cancer therapy startup using mRNA'
  },

  expert_legal: {
    description: 'Expert + Legal',
    flows: [
      'major_due_diligence → parallel_expert_and_legal_dd',
      'expert_technical_findings → legal_contract_implications'
    ],
    example: 'Major investment: Legal handles legal DD; Expert handles technical/economic DD; outputs combined for investment decision'
  },

  yana_expert: {
    description: 'Yana routes to Expert by triggers',
    flows: [
      'owner_query_with_meeting_context → yana_routes_to_expert',
      'expert_status_updates → yana_aggregates_for_owner',
      'multi_dept_complex → yana_orchestrates_expert_with_others'
    ]
  }
};

// =============================================================================
// Application instructions
// =============================================================================

/*
To apply this patch:

1. Open existing army.js (v4)

2. Find SPECIALISTS object, add entry:
   ...existing entries...
   ...spread SPECIALISTS_EXPERT_ENTRY...

3. Find SKILLS_MAP object, add entry:
   ...existing entries...
   ...spread SKILLS_MAP_EXPERT_ENTRY...

4. Find SKILL_LOADING_RULES object, add entry:
   ...existing entries...
   ...spread SKILL_LOADING_RULES_EXPERT_ENTRY...

5. Update Yana's routing triggers (in upravlenie.md profile)
   Add EXPERT_ROUTING_TRIGGERS to her routing rules

6. Update DEPARTMENT_INTERACTIONS to include EXPERT_INTERACTIONS

After application:
- node sync-skills.js --inventory should show 47 total skills (24 OSP + 12 LZ + 11 Expert)
- node sync-skills.js --dept expert should load all 5 Tier 1 + 4 Tier 2 + skip Tier 3 (depth default 2)
- /expert <topic> command should route correctly through Yana
*/
