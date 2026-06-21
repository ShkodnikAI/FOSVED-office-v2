// PATCH for army.js — Department and skill registration for Fosved Office v4
// Updates SPECIALISTS aliases and SKILLS_MAP with all new ОСП v2 + ЛЗ skills
// Apply by replacing existing SPECIALISTS and SKILLS_MAP constants

// =============================================================================
// SPECIALISTS — department aliases
// =============================================================================

export const SPECIALISTS = {
  // Strategic intelligence (ОСП v2)
  osp: {
    aliases: ['осп', 'spd', 'стратегия', 'аналитика', 'аналитик', 'анализ', 'штаб', 'разведка'],
    profile: 'library/osp.md',
    skillsDir: 'skills/fosved/spd/',
    archiveModel: 'Analysis',
    primaryMetric: 'brier_score',
    psychotype: { primary: 'Параноик', secondary: 'Педант' },
    version: '3.0'
  },

  // Technological intelligence (Лаборатория знаний)
  lz: {
    aliases: ['лз', 'лаборатория', 'лаборатория знаний', 'kl', 'knowledge lab', 'технологии',
              'исследователь', 'сканер', 'tech-intel'],
    profile: 'library/lz.md',
    skillsDir: 'skills/fosved/lz/',
    archiveModel: 'KnowledgeArtifact',
    primaryMetric: 'disruption_accuracy',
    psychotype: { primary: 'Экспериментатор', secondary: 'Параноик' },
    version: '1.0'
  },

  // Routing coordinator (Yana)
  upravlenie: {
    aliases: ['управление', 'яна', 'диспетчер', 'координатор', 'менеджер',
              'project-manager', 'pm', 'router'],
    profile: 'library/upravlenie.md',
    skillsDir: 'skills/fosved/upravlenie/',
    archiveModel: 'RoutingDecision',
    primaryMetric: 'routing_accuracy',
    psychotype: { primary: 'Медиатор', secondary: 'Эмпат', tertiary: 'Параноик' },
    version: '2.0'
  },

  // Methodology forge (Veteran)
  kk: {
    aliases: ['кк', 'кузница', 'кузница кадров', 'fpd', 'ветеран', 'обучение',
              'инструктор', 'методология', 'forge'],
    profile: 'library/kk.md',
    skillsDir: 'skills/fosved/kk/',
    archiveModel: 'TrainingSession',
    primaryMetric: 'pass_rate',
    psychotype: { primary: 'Методист', secondary: 'Параноик' },
    version: '2.0'
  },

  // Other departments (existing from v3 — placeholders, kept for completeness)
  finance: {
    aliases: ['финансы', 'учёт', 'налоги', 'бухгалтерия', 'cashflow'],
    profile: 'library/finance.md',
    skillsDir: 'skills/fosved/finance/',
    archiveModel: 'FinancialForecast',
    primaryMetric: 'mape',
    psychotype: { primary: 'Педант', secondary: 'Методист' }
  },

  legal: {
    aliases: ['юрист', 'юридический', 'контракты', 'правовой', 'legal'],
    profile: 'library/legal.md',
    skillsDir: 'skills/fosved/legal/',
    archiveModel: 'LegalAssessment',
    primaryMetric: 'rewrite_rate',
    psychotype: { primary: 'Параноик', secondary: 'Педант' }
  },

  dev: {
    aliases: ['разработка', 'код', 'программирование', 'инженер', 'developer'],
    profile: 'library/dev.md',
    skillsDir: 'skills/fosved/dev/',
    archiveModel: 'DevTask',
    primaryMetric: 'estimate_accuracy',
    psychotype: { primary: 'Прагматик', secondary: 'Методист' }
  },

  ops: {
    aliases: ['операции', 'процессы', 'operations', 'sla'],
    profile: 'library/ops.md',
    skillsDir: 'skills/fosved/ops/',
    archiveModel: 'OperationalEvent',
    primaryMetric: 'sla_compliance',
    psychotype: { primary: 'Методист', secondary: 'Педант' }
  },

  studio: {
    aliases: ['студия', 'ai-studio', 'creative', 'артефакты'],
    profile: 'library/studio.md',
    skillsDir: 'skills/fosved/studio/',
    archiveModel: 'AIArtifact',
    primaryMetric: 'satisfaction_rating',
    psychotype: { primary: 'Экспериментатор', secondary: 'Прагматик' }
  },

  product: {
    aliases: ['продукт', 'маркетинг', 'product', 'marketing', 'конверсия'],
    profile: 'library/product.md',
    skillsDir: 'skills/fosved/product/',
    archiveModel: 'MarketingForecast',
    primaryMetric: 'conversion_accuracy',
    psychotype: { primary: 'Эмпат', secondary: 'Экспериментатор' }
  }
};

// =============================================================================
// SKILLS_MAP — full inventory of all skills with tier classification
// =============================================================================

export const SKILLS_MAP = {
  // ============================================================================
  // ОСП (SPD) — Strategic intelligence v2
  // ============================================================================
  osp: {
    // Tier 1 — Methodological core (always loaded)
    tier1: [
      'awareness-frame',           // Phase 1 reconnaissance with environment
      'root-cause-mapping',        // 5-level topology with fruits/seeds/diseases
      'forces-and-potentials',     // P = A × R × S × L × E
      'strategic-maneuvers',       // 6 Sun Tzu maneuvers
      'two-paths-synthesis',       // Formal + game-theoretic paths
      'decision-tree-forecast',    // Fruit projection
      'deconstruct',               // Master orchestration skill
      'reflexive-impact',          // Soros reflexivity check
      'calibration',               // Brier + 6 error categories
      'system-health-diagnostics'  // Tier 1.5 — auto-triggered
    ],

    // Tier 2 — Domain depth (loaded by task type)
    tier2: [
      'iw-watchlist',              // Pentagon early warning system
      'macro-regime-id',           // 4 quadrants + cycle phases
      'cross-asset-divergence',    // Daily mispricing detector
      'asymmetric-bet-structure',  // Taleb framework for asymmetric payoffs
      'antifragility-design',      // Portfolio that benefits from volatility
      'deep-profiling',            // HUMINT-style decision-maker profiling
      'cycle-position',            // Kondratieff/Juglar/Kitchin/debt cycles
      'narrative-vs-flows',        // Alpha layer with cross-country macro
      'cantillon',                 // Monetary emission with cross-border Cantillon
      'source-triangulation'       // Verification discipline
    ],

    // Tier 3 — Special techniques (rare, high-stakes use)
    tier3: [
      'order-of-battle',           // Pentagon-style physical inventory
      'phase-transition-detection', // 5 signatures of approaching transition
      'schelling-points',          // Coordination without communication
      'red-team'                   // Adversarial reconstruction
    ]
  },

  // ============================================================================
  // Лаборатория знаний (LZ) — Technology intelligence v1
  // ============================================================================
  lz: {
    // Tier 1 — Methodological core
    tier1: [
      'hype-cycle-mapping',        // Gartner-style stage classification
      'disruption-scoring',        // 5-component probability scoring
      'inflection-detection',      // 5-signal lab→commercial detector
      'technology-OOB',            // Pentagon-style capability comparison
      'cross-domain-transfer'      // Capabilities crossing domains
    ],

    // Tier 2 — Domain depth
    tier2: [
      'patent-prosecution-analysis', // Patents reveal real R&D direction
      'talent-flow-tracking',        // Researcher migrations as leading indicator
      'vc-tracking',                 // Capital concentration patterns
      'competing-alternatives'       // Alternatives to dominant approaches
    ],

    // Tier 3 — Special techniques
    tier3: [
      'leaked-roadmap-analysis',    // Authenticated leak intelligence
      'dark-web-tech-research',     // Research outside mainstream channels
      'deep-researcher-profiling'   // OSINT profiling of key technical talent
    ]
  },

  // ============================================================================
  // Кузница (KK) — Methodology forge v2
  // ============================================================================
  kk: {
    // Tier 1
    tier1: [
      'methodology-application',
      'specialist-creation',
      'psychotype-assessment',
      'skill-quality-review',
      'debrief-protocol'
    ],

    // Tier 2 (with new arsenal/paradigm management)
    tier2: [
      'training-program-design',
      'polygon-test-design',
      'arsenal-review',            // NEW: skill inventory and deprecation
      'paradigm-review'            // NEW: principles and architecture review
    ],

    // Tier 3
    tier3: [
      'recalibration-orchestration',
      'methodology-evolution'      // NEW: managing methodology versioning
    ]
  },

  // ============================================================================
  // Управление (Yana) — Routing coordinator v2
  // ============================================================================
  upravlenie: {
    tier1: [
      'routing-discipline',
      'context-preservation',
      'depth-determination',       // NEW: adaptive depth triggering
      'escalation-protocol'        // NEW: when to escalate to Forge
    ],
    tier2: [
      'orchestration-multi-dept',  // NEW: cross-departmental coordination
      'cross-departmental-reporting' // NEW: morning/weekly/monthly reports
    ]
    // No Tier 3 for Yana — operational not analytical
  }

  // Other departments' skills inventoried separately (not changed in v4)
};

// =============================================================================
// SKILL_LOADING_RULES — when each tier loads
// =============================================================================

export const SKILL_LOADING_RULES = {
  osp: {
    tier1: { trigger: 'always' },
    tier2: {
      trigger: 'depth_or_topic',
      conditions: {
        'iw-watchlist': { depth: '>=3', topics: ['monitoring', 'scenarios'] },
        'macro-regime-id': { depth: '>=2', topics: ['financial', 'macro'] },
        'cross-asset-divergence': { depth: '>=2', topics: ['markets'] },
        'asymmetric-bet-structure': { depth: '>=2', topics: ['investment'] },
        'antifragility-design': { depth: '>=3', topics: ['portfolio'] },
        'deep-profiling': { depth: '>=3', topics: ['leadership', 'decision-makers'] },
        'cycle-position': { depth: '>=2', topics: ['macro', 'investment'] },
        'narrative-vs-flows': { depth: '>=1', topics: ['financial', 'political'] },
        'cantillon': { depth: '>=2', topics: ['monetary', 'financial'] },
        'source-triangulation': { depth: '>=1', topics: 'all' }
      }
    },
    tier3: {
      trigger: 'depth_4_or_explicit',
      conditions: {
        'order-of-battle': { depth: '>=3', topics: ['military', 'industrial'] },
        'phase-transition-detection': { depth: '>=3', topics: ['regime', 'market'] },
        'schelling-points': { depth: '>=3', topics: ['coordination', 'conflict'] },
        'red-team': { depth: '>=3', explicit_only: true }
      }
    }
  },

  lz: {
    tier1: { trigger: 'always_for_tracked_tech' },
    tier2: {
      trigger: 'analysis_depth',
      conditions: {
        'patent-prosecution-analysis': { trigger: 'company_analysis_depth_2plus' },
        'talent-flow-tracking': { trigger: 'continuous_for_active_domains' },
        'vc-tracking': { trigger: 'continuous_for_active_subfields' },
        'competing-alternatives': { trigger: 'major_tech_decision' }
      }
    },
    tier3: {
      trigger: 'owner_authorization_required',
      conditions: {
        'leaked-roadmap-analysis': { mode: 'escalated' },
        'dark-web-tech-research': { mode: 'full', owner_approval: true },
        'deep-researcher-profiling': { mode: 'escalated' }
      }
    }
  }
};

// =============================================================================
// DEPARTMENT_INTERACTIONS — how departments cooperate
// =============================================================================

export const DEPARTMENT_INTERACTIONS = {
  osp_lz: {
    description: 'Strategic intelligence + Technology intelligence partnership',
    flows: [
      'lz_disruption_alert → osp_strategic_analysis',
      'osp_topic → lz_tech_context_provided',
      'lz_inflection → osp_asymmetric_bet_analysis'
    ]
  },
  yana_kk: {
    description: 'Operational routing + Methodology forge',
    flows: [
      'yana_routing_pattern_failures → kk_debrief_recommendation',
      'kk_methodology_update → yana_routing_rules_update',
      'kk_skill_deprecation → yana_aware_of_deprecated_capabilities'
    ]
  },
  yana_all: {
    description: 'Yana coordinates all departments',
    flows: [
      'owner_request → yana_route → department',
      'department_status → yana_aggregate → owner',
      'department_alert → yana_escalate → owner_or_kk'
    ]
  }
};

console.log('[army] Fosved Office v4 specialists and skills registered');
