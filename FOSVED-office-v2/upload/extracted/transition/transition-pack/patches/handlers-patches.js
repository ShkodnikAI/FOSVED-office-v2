// PATCH for handlers/index.js — Self-improvement loop implementations
// All handlers used by scheduler.js for periodic reviews
// Apply by adding these functions to existing handlers/index.js

import { prisma } from '../lib/prisma.js';
import { sendTelegramMessage } from '../lib/telegram.js';

const OWNER_CHAT_ID = process.env.OWNER_CHAT_ID;

// =============================================================================
// HORIZON 2 — Monthly performance review
// =============================================================================

export async function runMonthlyDepartmentReview(department) {
  const period = formatPeriod(new Date(), 'YYYY-MM-prev');
  const periodStart = startOfMonth(subtractMonths(new Date(), 1));
  const periodEnd = endOfMonth(periodStart);

  console.log(`[review] Running monthly review for ${department} period ${period}`);

  // Aggregate metrics based on department type
  let metrics = {};

  if (department === 'osp') {
    metrics = await aggregateOSPMetrics(periodStart, periodEnd);
  } else if (department === 'lz') {
    metrics = await aggregateLabMetrics(periodStart, periodEnd);
  } else if (department === 'upravlenie') {
    metrics = await aggregateYanaMetrics(periodStart, periodEnd);
  } else {
    metrics = await aggregateGenericMetrics(department, periodStart, periodEnd);
  }

  // Determine trend vs prior month
  const priorReview = await prisma.monthlyReview.findFirst({
    where: { department, period: formatPeriod(periodStart, 'YYYY-MM-prev') },
    orderBy: { createdAt: 'desc' }
  });

  let trend = 'stable';
  if (priorReview && priorReview.primaryMetric !== null && metrics.primaryMetric !== null) {
    if (metrics.metricDirection === 'higher_is_better') {
      trend = metrics.primaryMetric > priorReview.primaryMetric ? 'improving'
            : metrics.primaryMetric < priorReview.primaryMetric ? 'deteriorating' : 'stable';
    } else {
      // For Brier scores, lower is better
      trend = metrics.primaryMetric < priorReview.primaryMetric ? 'improving'
            : metrics.primaryMetric > priorReview.primaryMetric ? 'deteriorating' : 'stable';
    }
  }

  // Identify improvements based on patterns
  const improvements = await identifyMonthlyImprovements(department, metrics);

  // Save review
  const review = await prisma.monthlyReview.create({
    data: {
      department,
      period,
      primaryMetric: metrics.primaryMetric,
      primaryMetricName: metrics.primaryMetricName,
      metricTrend: trend,
      depthLevelMetrics: JSON.stringify(metrics.depthLevelBreakdown || {}),
      topicClassMetrics: JSON.stringify(metrics.topicClassBreakdown || {}),
      fruitTypeMetrics: JSON.stringify(metrics.fruitTypeBreakdown || {}),
      errorCategoryBreakdown: JSON.stringify(metrics.errorCategoryBreakdown || {}),
      improvements: JSON.stringify(improvements),
      status: 'finalized'
    }
  });

  // Send summary to Yana for cross-departmental aggregation
  await notifyYanaOfReview(department, review);

  return review;
}

async function aggregateOSPMetrics(start, end) {
  // Get all verified analyses in period
  const verifiedAnalyses = await prisma.analysis.findMany({
    where: {
      verifiedAt: { gte: start, lte: end }
    }
  });

  if (verifiedAnalyses.length === 0) {
    return {
      primaryMetric: null,
      primaryMetricName: 'brier_score',
      metricDirection: 'lower_is_better',
      noData: true
    };
  }

  // Compute average Brier score
  const brierScores = verifiedAnalyses
    .filter(a => a.brierScore !== null)
    .map(a => a.brierScore);
  const avgBrier = brierScores.length > 0
    ? brierScores.reduce((a, b) => a + b, 0) / brierScores.length
    : null;

  // Breakdown by depth level
  const depthLevelBreakdown = {};
  for (let level = 0; level <= 4; level++) {
    const levelAnalyses = verifiedAnalyses.filter(a => a.depthLevel === level);
    const levelScores = levelAnalyses.map(a => a.brierScore).filter(s => s !== null);
    depthLevelBreakdown[`level_${level}`] = {
      count: levelAnalyses.length,
      avg_brier: levelScores.length > 0 ? levelScores.reduce((a, b) => a + b, 0) / levelScores.length : null
    };
  }

  // Error category breakdown
  const errorCategoryBreakdown = {
    tail: 0,
    miscalibrated: 0,
    analysis_error: 0,
    unfalsifiable: 0,
    methodology_gap: 0,
    environmental_misjudgment: 0
  };
  verifiedAnalyses.forEach(a => {
    if (a.errorCategory && errorCategoryBreakdown[a.errorCategory] !== undefined) {
      errorCategoryBreakdown[a.errorCategory]++;
    }
  });

  return {
    primaryMetric: avgBrier,
    primaryMetricName: 'brier_score',
    metricDirection: 'lower_is_better',
    totalAnalyses: verifiedAnalyses.length,
    depthLevelBreakdown,
    errorCategoryBreakdown
  };
}

async function aggregateLabMetrics(start, end) {
  const artifacts = await prisma.knowledgeArtifact.findMany({
    where: {
      lastReviewed: { gte: start, lte: end }
    }
  });

  // Disruption accuracy: predicted disruption vs actual outcome status
  const tracked = artifacts.length;
  const confirmedDisruptions = artifacts.filter(a => a.status === 'confirmed_disruption').length;
  const failed = artifacts.filter(a => a.status === 'failed').length;

  const accuracy = tracked > 0 ? (confirmedDisruptions / (confirmedDisruptions + failed)) || 0 : null;

  return {
    primaryMetric: accuracy,
    primaryMetricName: 'disruption_accuracy',
    metricDirection: 'higher_is_better',
    totalTracked: tracked,
    confirmedDisruptions,
    failed
  };
}

async function aggregateYanaMetrics(start, end) {
  const decisions = await prisma.routingDecision.findMany({
    where: { resolvedAt: { gte: start, lte: end } }
  });

  const correct = decisions.filter(d => d.wasCorrect === true).length;
  const accuracy = decisions.length > 0 ? correct / decisions.length : null;

  return {
    primaryMetric: accuracy,
    primaryMetricName: 'routing_accuracy',
    metricDirection: 'higher_is_better',
    totalDecisions: decisions.length,
    correct
  };
}

async function aggregateGenericMetrics(department, start, end) {
  // For other departments, defer to their specific archive models
  // This is placeholder; actual implementations vary per department
  return {
    primaryMetric: null,
    primaryMetricName: 'department_specific',
    metricDirection: 'higher_is_better'
  };
}

async function identifyMonthlyImprovements(department, metrics) {
  const improvements = [];

  // ОСП-specific patterns
  if (department === 'osp' && metrics.errorCategoryBreakdown) {
    const ec = metrics.errorCategoryBreakdown;
    const total = Object.values(ec).reduce((a, b) => a + b, 0);

    if (ec.methodology_gap / total > 0.2) {
      improvements.push({
        priority: 'high',
        action: 'Review methodology for systematic gaps',
        rationale: `${Math.round(ec.methodology_gap / total * 100)}% of errors are methodology gaps`
      });
    }

    if (ec.environmental_misjudgment / total > 0.15) {
      improvements.push({
        priority: 'high',
        action: 'Tighten environmental assessment in awareness frame',
        rationale: 'Pattern of missing substrate/disease/parasite signals'
      });
    }

    if (ec.miscalibrated / total > 0.3) {
      improvements.push({
        priority: 'medium',
        action: 'Run calibration discipline workshop; review probability discipline',
        rationale: 'High proportion of miscalibrated probabilities'
      });
    }
  }

  return improvements;
}

// =============================================================================
// HORIZON 3 — Quarterly methodology review
// =============================================================================

export async function runQuarterlyMethodologyReview(department) {
  const period = formatQuarter(new Date());

  // Get last 3 monthly reviews
  const recentReviews = await prisma.monthlyReview.findMany({
    where: { department },
    orderBy: { createdAt: 'desc' },
    take: 3
  });

  // Compute quarterly aggregate
  const validMetrics = recentReviews.filter(r => r.primaryMetric !== null);
  const quarterlyMetric = validMetrics.length > 0
    ? validMetrics.reduce((sum, r) => sum + r.primaryMetric, 0) / validMetrics.length
    : null;

  // Pattern analysis
  const patterns = analyzeQuarterlyPatterns(recentReviews);

  // Generate skill update recommendations
  const skillUpdates = generateSkillUpdates(department, patterns);

  const review = await prisma.quarterlyReview.create({
    data: {
      department,
      period,
      quarterlyMetric,
      trendVsPriorQuarters: JSON.stringify(patterns.trends),
      errorPatterns: JSON.stringify(patterns.errorPatterns),
      systematicWeaknesses: JSON.stringify(patterns.systematicWeaknesses),
      skillUpdates: JSON.stringify(skillUpdates)
    }
  });

  return review;
}

function analyzeQuarterlyPatterns(reviews) {
  const errorCategoryFrequency = {};
  const trendPattern = reviews.map(r => r.metricTrend);

  reviews.forEach(r => {
    if (r.errorCategoryBreakdown) {
      const breakdown = JSON.parse(r.errorCategoryBreakdown);
      Object.entries(breakdown).forEach(([category, count]) => {
        errorCategoryFrequency[category] = (errorCategoryFrequency[category] || 0) + count;
      });
    }
  });

  const systematicWeaknesses = [];
  if (errorCategoryFrequency.methodology_gap > 5) {
    systematicWeaknesses.push('persistent_methodology_gaps');
  }
  if (errorCategoryFrequency.environmental_misjudgment > 3) {
    systematicWeaknesses.push('environmental_assessment_weak');
  }
  if (trendPattern.filter(t => t === 'deteriorating').length >= 2) {
    systematicWeaknesses.push('deteriorating_trend_persistent');
  }

  return {
    trends: trendPattern,
    errorPatterns: errorCategoryFrequency,
    systematicWeaknesses
  };
}

function generateSkillUpdates(department, patterns) {
  const updates = [];

  if (patterns.systematicWeaknesses.includes('persistent_methodology_gaps')) {
    updates.push({
      action: 'review_skills',
      target_skills: department === 'osp'
        ? ['narrative-vs-flows', 'cantillon', 'forces-and-potentials']
        : [],
      rationale: 'Persistent methodology gaps indicate skill-level issues'
    });
  }

  if (patterns.systematicWeaknesses.includes('environmental_assessment_weak')) {
    updates.push({
      action: 'review_skills',
      target_skills: ['awareness-frame', 'system-health-diagnostics'],
      rationale: 'Environmental misjudgments suggest awareness frame insufficient'
    });
  }

  return updates;
}

// =============================================================================
// HORIZON 4 — Semi-annual arsenal review
// =============================================================================

export async function runArsenalReview(period) {
  console.log(`[arsenal] Starting arsenal review for ${period}`);

  // Get all skills from all departments
  const skillsAtStart = await loadAllSkillsInventory();

  // Compute utilization stats per skill
  const utilizationStats = await computeSkillUtilization();

  // Identify stale skills (not used 4+ quarters)
  const staleSkills = utilizationStats.filter(s => s.quartersWithoutUse >= 4);

  // Identify failing skills (fail rate > 30% across uses)
  const failingSkills = utilizationStats.filter(s => s.failRate > 0.3);

  // Industry survey: identify new techniques worth incorporating
  const newTechniques = await surveyIndustryTechniques();

  // Generate report
  const ownerReport = generateArsenalReport({
    skillsAtStart,
    utilizationStats,
    staleSkills,
    failingSkills,
    newTechniques
  });

  // Save review
  const review = await prisma.arsenalReview.create({
    data: {
      period,
      skillsAtStart: JSON.stringify(skillsAtStart),
      utilizationStats: JSON.stringify(utilizationStats),
      staleSkills: JSON.stringify(staleSkills),
      failingSkills: JSON.stringify(failingSkills),
      newTechniques: JSON.stringify(newTechniques),
      ownerReport,
      status: 'awaiting_owner_decisions'
    }
  });

  // Send to owner
  await sendArsenalReportToOwner(review);

  return review;
}

async function loadAllSkillsInventory() {
  const fs = await import('fs/promises');
  const path = await import('path');

  const skillsDir = path.join(process.cwd(), 'skills', 'fosved');
  const departments = await fs.readdir(skillsDir);

  const inventory = {};

  for (const dept of departments) {
    const deptPath = path.join(skillsDir, dept);
    const stats = await fs.stat(deptPath);
    if (!stats.isDirectory()) continue;

    const skills = await fs.readdir(deptPath);
    inventory[dept] = [];

    for (const skill of skills) {
      const skillPath = path.join(deptPath, skill, 'SKILL.md');
      try {
        const content = await fs.readFile(skillPath, 'utf-8');
        const match = content.match(/^---\n([\s\S]*?)\n---/);
        if (match) {
          inventory[dept].push({
            name: skill,
            metadata: match[1]
          });
        }
      } catch (e) {
        // Skip if SKILL.md doesn't exist
      }
    }
  }

  return inventory;
}

async function computeSkillUtilization() {
  // Loads skill usage from analyses, knowledge artifacts, and other archives
  // Returns: [{skill_name, dept, use_count_last_year, fail_rate, avg_score, last_used}]

  const stats = [];

  // ОСП skill usage (from analyses)
  const oneYearAgo = new Date();
  oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);

  const recentAnalyses = await prisma.analysis.findMany({
    where: { createdAt: { gte: oneYearAgo } },
    select: { triggeredSkills: true, brierScore: true, errorCategory: true }
  });

  const skillCounts = {};

  recentAnalyses.forEach(a => {
    if (a.triggeredSkills) {
      try {
        const triggered = JSON.parse(a.triggeredSkills);
        triggered.forEach(skill => {
          if (!skillCounts[skill]) {
            skillCounts[skill] = { uses: 0, fails: 0, scoresSum: 0, scoresCount: 0 };
          }
          skillCounts[skill].uses++;
          if (a.errorCategory && a.errorCategory !== 'tail') {
            skillCounts[skill].fails++;
          }
          if (a.brierScore !== null) {
            skillCounts[skill].scoresSum += a.brierScore;
            skillCounts[skill].scoresCount++;
          }
        });
      } catch (e) {}
    }
  });

  Object.entries(skillCounts).forEach(([skill, data]) => {
    stats.push({
      name: skill,
      dept: skill.split('/')[0] || 'unknown',
      use_count_last_year: data.uses,
      fail_rate: data.uses > 0 ? data.fails / data.uses : 0,
      avg_score: data.scoresCount > 0 ? data.scoresSum / data.scoresCount : null,
      quartersWithoutUse: data.uses === 0 ? 4 : 0  // simplified
    });
  });

  return stats;
}

async function surveyIndustryTechniques() {
  // Placeholder — in real implementation, this would survey:
  // - Recent strategic intelligence literature
  // - New methodology publications
  // - Cross-validation against current methods
  // For now returns empty; populated by manual curation in Forge
  return [];
}

function generateArsenalReport(data) {
  return `# Arsenal Review Report — ${new Date().toISOString().slice(0, 7)}

## Inventory Summary
- Total skills: ${Object.values(data.skillsAtStart).flat().length}
- Departments covered: ${Object.keys(data.skillsAtStart).length}

## Utilization Findings
- Stale skills (4+ quarters unused): ${data.staleSkills.length}
- Failing skills (>30% fail rate): ${data.failingSkills.length}

## Recommendations
${data.staleSkills.length > 0 ? `### Deprecate:
${data.staleSkills.map(s => `- ${s.name}`).join('\n')}` : ''}

${data.failingSkills.length > 0 ? `### Rewrite:
${data.failingSkills.map(s => `- ${s.name} (fail rate: ${Math.round(s.fail_rate * 100)}%)`).join('\n')}` : ''}

${data.newTechniques.length > 0 ? `### Consider adding:
${data.newTechniques.map(t => `- ${t.name}: ${t.rationale}`).join('\n')}` : ''}

## Methodology size constraint
New skill additions require corresponding deprecations to maintain fixed methodology size.

## Owner approval required for
- Skill deprecations
- Skill rewrites
- New skill additions
`;
}

async function sendArsenalReportToOwner(review) {
  await sendTelegramMessage(OWNER_CHAT_ID,
    `📊 Arsenal Review Ready\n\n` +
    `Period: ${review.period}\n` +
    `Status: ${review.status}\n\n` +
    `${review.ownerReport.substring(0, 3000)}\n\n` +
    `Use /arsenal-review-status ${review.id} for full report.\n` +
    `Use /skill-deprecate, /skill-evolve commands to act on findings.`
  );
}

// =============================================================================
// HORIZON 5 — Annual paradigm review
// =============================================================================

export async function runParadigmReview(year) {
  console.log(`[paradigm] Starting annual paradigm review for ${year}`);

  // This is initiated by the system but completed with owner participation
  // Initial draft prepared automatically; owner discussion required for finalization

  const yearStart = new Date(`${year}-01-01`);
  const yearEnd = new Date(`${year}-12-31`);

  // Year debrief data
  const allAnalyses = await prisma.analysis.findMany({
    where: { createdAt: { gte: yearStart, lte: yearEnd } }
  });

  const verifiedAnalyses = allAnalyses.filter(a => a.verifiedAt !== null);

  // Categorize: hits / misses / surprises
  const hits = verifiedAnalyses.filter(a =>
    a.brierScore !== null && a.brierScore < 0.15
  );

  const misses = verifiedAnalyses.filter(a =>
    a.brierScore !== null && a.brierScore > 0.40
  );

  const surprises = verifiedAnalyses.filter(a =>
    a.errorCategory === 'methodology_gap' || a.errorCategory === 'environmental_misjudgment'
  );

  // Initial draft of review
  const reviewDraft = {
    year,
    principlesReview: 'PENDING_OWNER_DISCUSSION',
    currentDepartments: await listCurrentDepartments(),
    proposedAdditions: 'PENDING_OWNER_DISCUSSION',
    proposedRetirements: 'PENDING_OWNER_DISCUSSION',
    hits: JSON.stringify(hits.map(a => ({ id: a.id, topic: a.topic, brier: a.brierScore }))),
    misses: JSON.stringify(misses.map(a => ({
      id: a.id, topic: a.topic, brier: a.brierScore, error_category: a.errorCategory
    }))),
    surprises: JSON.stringify(surprises.map(a => ({
      id: a.id, topic: a.topic, error_category: a.errorCategory
    }))),
    ownerDiscussion: 'PENDING'
  };

  const review = await prisma.paradigmReview.create({
    data: {
      ...reviewDraft,
      status: 'awaiting_owner_session'
    }
  });

  // Notify owner
  await sendTelegramMessage(OWNER_CHAT_ID,
    `📋 Annual Paradigm Review Ready (${year})\n\n` +
    `Total analyses: ${allAnalyses.length}\n` +
    `Verified: ${verifiedAnalyses.length}\n` +
    `Hits (Brier < 0.15): ${hits.length}\n` +
    `Misses (Brier > 0.40): ${misses.length}\n` +
    `Surprises (methodology gaps): ${surprises.length}\n\n` +
    `Annual paradigm review requires your participation.\n` +
    `Use /paradigm-review ${review.id} to start owner session.`
  );

  return review;
}

async function listCurrentDepartments() {
  // Returns list of current departments + their roles
  return JSON.stringify([
    { name: 'osp', role: 'strategic intelligence and analysis', psychotype: 'paranoid+pedantic' },
    { name: 'lz', role: 'technological intelligence', psychotype: 'experimentor+paranoid' },
    { name: 'finance', role: 'financial accounting and forecasting', psychotype: 'pedantic+methodist' },
    { name: 'legal', role: 'risk analysis and legal review', psychotype: 'paranoid+pedantic' },
    { name: 'dev', role: 'software development', psychotype: 'pragmatic+methodist' },
    { name: 'ops', role: 'operational processes', psychotype: 'methodist+pedantic' },
    { name: 'studio', role: 'AI artifact creation', psychotype: 'experimentor+pragmatic' },
    { name: 'product', role: 'marketing and product analytics', psychotype: 'empath+experimentor' },
    { name: 'upravlenie', role: 'routing coordination', psychotype: 'mediator+empath+paranoid' },
    { name: 'kk', role: 'methodology and personnel forge', psychotype: 'methodist+paranoid' }
  ]);
}

// =============================================================================
// Helper functions
// =============================================================================

function formatPeriod(date, format) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  if (format === 'YYYY-MM') return `${year}-${month}`;
  if (format === 'YYYY-MM-prev') {
    const prev = subtractMonths(date, 1);
    return `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`;
  }
  return `${year}-${month}`;
}

function formatQuarter(date) {
  const year = date.getFullYear();
  const quarter = Math.floor(date.getMonth() / 3) + 1;
  return `${year}-Q${quarter}`;
}

function subtractMonths(date, n) {
  const d = new Date(date);
  d.setMonth(d.getMonth() - n);
  return d;
}

function startOfMonth(date) {
  const d = new Date(date);
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  return d;
}

function endOfMonth(date) {
  const d = new Date(date);
  d.setMonth(d.getMonth() + 1);
  d.setDate(0);
  d.setHours(23, 59, 59, 999);
  return d;
}

async function notifyYanaOfReview(department, review) {
  // Yana aggregates monthly reviews into cross-departmental reports
  // Implementation depends on existing Yana notification system
  console.log(`[notify] Yana notified of ${department} monthly review (period: ${review.period})`);
}

// =============================================================================
// Other handlers referenced in scheduler (stubs — actual implementations elsewhere)
// =============================================================================

export async function triggerAnalysisVerification(verificationId) {
  // Triggers /verify on analysis with this verification ID
  console.log(`[verify] Triggered for verification ${verificationId}`);
}

export async function runLaboratoryScan({ scope }) {
  console.log(`[lab] Running ${scope} scan`);
  // Implementation: scan arxiv/biorxiv/medrxiv/patents/news for tech signals
}

export async function generateLabDigest({ period }) {
  console.log(`[lab] Generating ${period} digest`);
  // Implementation: top events from KnowledgeArtifacts updated in period
}

export async function reviewInflectionCandidates() {
  console.log('[lab] Reviewing inflection candidates');
}

export async function rescoreDisruptionCandidates() {
  console.log('[lab] Re-scoring disruption candidates');
}

export async function generateDailyMorningBriefing() {
  console.log('[yana] Generating morning briefing');
}

export async function generateWeeklyCrossReport() {
  console.log('[yana] Generating weekly cross report');
}

export async function generateMonthlyCrossReport() {
  console.log('[yana] Generating monthly cross report');
}

export async function updateMacroRegime() {
  console.log('[regime] Updating macro regime snapshot');
}

export async function scanCrossAssetDivergences() {
  console.log('[divergence] Scanning cross-asset divergences');
}

export async function reviewWatchlistIndicators({ horizons, alertLevels }) {
  console.log(`[watchlist] Reviewing indicators horizons=${horizons} alertLevels=${alertLevels}`);
}
