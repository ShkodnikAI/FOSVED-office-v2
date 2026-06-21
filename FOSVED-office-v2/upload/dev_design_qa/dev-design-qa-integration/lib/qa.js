// ============================================================================
// lib/qa.js — QA Department engine
// ============================================================================
//
// Core operations for the Testing (QA) department:
//   - Test strategy generation
//   - TestRun orchestration (unit, integration, e2e, security, perf, a11y, ai_eval)
//   - DefectRecord lifecycle (record, triage, link to hotfix, verify)
//   - AI evals (Promptfoo-style: groundedness, relevance, faithfulness,
//     prompt injection resistance, hallucination detection, cost tracking)
//   - SecurityAudit (dependency audit + OWASP checklist)
//   - Daily production monitoring
//   - Weekly security scan
//   - Quarterly methodology review
//
// Storage: TestRun / DefectRecord / SecurityAudit / AIEvalRun in DB.
//          Critical defects + high-severity security findings auto-published
//          to Telegram archive.
//
// Cross-department: a critical DefectRecord creates a Dev hotfix task
//   (handled in bot-cross-dept-hooks.js, this module exposes the helper).
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Constants ───────────────────────────────────────────────────────────────

const TEST_TYPES = [
  'unit', 'integration', 'e2e', 'security',
  'performance', 'accessibility', 'ai_eval', 'smoke', 'regression'
];

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3, trivial: 4 };

// Coverage targets by area (from qa/test-strategy-design skill)
const COVERAGE_TARGETS = {
  critical_path: 95,
  business_logic: 90,
  overall: 80
};

// AI eval metric thresholds (from qa/ai-evals-framework skill)
const AI_EVAL_THRESHOLDS = {
  groundedness: 0.85,
  relevance: 0.85,
  faithfulness: 0.90,
  coherence: 0.80,
  promptInjectionResistance: 0.95,
  overallPass: 0.90
};

// ─── Test strategy ───────────────────────────────────────────────────────────

/**
 * Generate a test strategy for a project. Returns a structured plan; does not
 * execute. The plan covers the test pyramid balance + perpendicular suites.
 */
export function generateTestStrategy({ projectName, projectType, hasAI = false, hasUserInput = false }) {
  const pyramid = {
    unit: { share: 0.70, focus: 'isolated logic, mocked dependencies, edge cases' },
    integration: { share: 0.20, focus: 'API contracts, DB integration, component boundaries' },
    e2e: { share: 0.10, focus: 'critical user journeys end-to-end' }
  };

  const perpendicular = [];
  // Security required when user input / auth / payment / personal data present
  if (hasUserInput || projectType === 'web_app' || projectType === 'ai_office') {
    perpendicular.push({
      type: 'security',
      cadence: 'every release + weekly scan',
      focus: 'OWASP Top 10, dependency audit, secrets scan'
    });
  }
  // Accessibility required for any UI release
  if (['web_app', 'site', 'ai_office'].includes(projectType)) {
    perpendicular.push({
      type: 'accessibility',
      cadence: 'every UI release',
      focus: 'WCAG AA: contrast, keyboard nav, screen reader, semantic HTML'
    });
  }
  // AI evals required when LLM features present
  if (hasAI) {
    perpendicular.push({
      type: 'ai_eval',
      cadence: 'every prompt change + weekly regression',
      focus: 'golden dataset 50+, groundedness/relevance/faithfulness, prompt injection, hallucination, cost'
    });
  }
  // Performance for projects with explicit perf requirements
  perpendicular.push({
    type: 'performance',
    cadence: 'before major release',
    focus: 'load/stress, Web Vitals (LCP/FID/CLS), p95/p99 latency'
  });

  return {
    projectName,
    projectType,
    pyramid,
    perpendicular,
    coverageTargets: COVERAGE_TARGETS,
    gateRule: 'No release with open critical defects. Coverage on critical paths >= 95%.',
    generatedAt: new Date().toISOString()
  };
}

// ─── TestRun orchestration ───────────────────────────────────────────────────

/**
 * Create a TestRun record (started state). Actual test execution is performed
 * by the project's own test tooling; this records the run + verdict.
 */
export async function createTestRun({
  target, testType, targetRepositoryId = null, targetTaskId = null,
  testFramework = null, scopeDescription = null,
  triggerType = 'manual', userId = OWNER_ID
}) {
  if (!TEST_TYPES.includes(testType)) {
    throw new Error(`Unknown testType "${testType}". Valid: ${TEST_TYPES.join(', ')}`);
  }
  return prisma.testRun.create({
    data: {
      userId, target, testType, targetRepositoryId, targetTaskId,
      testFramework, scopeDescription, triggerType,
      startedAt: new Date(), verdict: 'pending'
    }
  });
}

/**
 * Record the results of a completed TestRun and compute the verdict + gate
 * decision. Returns the updated run.
 */
export async function completeTestRun(testRunId, {
  totalTests = 0, passedTests = 0, failedTests = 0, skippedTests = 0,
  coverage = null, coverageDetails = null, output = null, rawResultsUrl = null
}) {
  const run = await prisma.testRun.findUnique({ where: { id: testRunId } });
  if (!run) throw new Error(`TestRun ${testRunId} not found`);

  const passRate = totalTests > 0 ? passedTests / totalTests : null;
  const durationSec = Math.round((Date.now() - new Date(run.startedAt).getTime()) / 1000);

  // Verdict: failed if any test failed; partial if skips present; passed otherwise
  let verdict = 'passed';
  if (failedTests > 0) verdict = 'failed';
  else if (skippedTests > 0 && passedTests > 0) verdict = 'partial';
  else if (totalTests === 0) verdict = 'error';

  // Gate decision: no_go if failures, conditional if coverage below target
  let gateDecision = 'go';
  if (verdict === 'failed') gateDecision = 'no_go';
  else if (coverage !== null && coverage < COVERAGE_TARGETS.overall) gateDecision = 'conditional';

  const updated = await prisma.testRun.update({
    where: { id: testRunId },
    data: {
      completedAt: new Date(), durationSec,
      totalTests, passedTests, failedTests, skippedTests, passRate,
      coverage, coverageDetails, output: output ? output.slice(0, 5000) : null,
      rawResultsUrl, verdict, gateDecision
    }
  });

  // Failed runs with the target being production-critical → archive alert
  if (verdict === 'failed') {
    await publishToArchive({
      text: `🔴 *Тесты провалены* — ${run.target}\n` +
            `Тип: ${run.testType} | ${failedTests}/${totalTests} failed\n` +
            `Gate: ${gateDecision}\n#qa #test_failed #${slug(run.target)}`
    }).catch(() => {});
  }

  return updated;
}

// ─── Defect lifecycle ────────────────────────────────────────────────────────

/**
 * Record a defect. Critical defects are flagged for hotfix creation
 * (the actual Dev task is created by the cross-department hook) and
 * published to the archive.
 */
export async function recordDefect({
  title, description, severity, category,
  stepsToReproduce, expectedBehavior, actualBehavior,
  environment = null, testRunId = null, userId = OWNER_ID
}) {
  if (!(severity in SEVERITY_ORDER)) {
    throw new Error(`Unknown severity "${severity}". Valid: ${Object.keys(SEVERITY_ORDER).join(', ')}`);
  }

  const defect = await prisma.defectRecord.create({
    data: {
      userId, title, description, severity, category,
      stepsToReproduce, expectedBehavior, actualBehavior,
      environment, testRunId, status: 'open'
    }
  });

  if (testRunId) {
    await prisma.testRun.update({
      where: { id: testRunId },
      data: { defectsCreated: { increment: 1 } }
    }).catch(() => {});
  }

  // Critical/high defects → archive alert
  if (severity === 'critical' || severity === 'high') {
    await publishToArchive({
      text: `${severity === 'critical' ? '🚨' : '⚠️'} *Дефект ${severity}* — ${title}\n` +
            `Категория: ${category}\n` +
            `${actualBehavior.slice(0, 200)}\n` +
            `#qa #defect #${severity}`
    }).catch(() => {});
  }

  return defect;
}

/**
 * Returns whether a defect should spawn a Dev hotfix task. Used by the
 * cross-department hook. Critical defects always; high defects reaching
 * production.
 */
export function defectNeedsHotfix(defect) {
  if (defect.severity === 'critical') return true;
  if (defect.severity === 'high' && defect.reachedProduction) return true;
  return false;
}

/**
 * Link a defect to the Dev hotfix task that will fix it.
 */
export async function assignDefectToTask(defectId, devTaskId) {
  return prisma.defectRecord.update({
    where: { id: defectId },
    data: { assignedToTaskId: devTaskId, status: 'in_progress' }
  });
}

/**
 * Close a defect after fix is verified. Requires that a regression test was
 * added — the defect-discipline skill mandates "bug found -> test added".
 */
export async function verifyDefectFix(defectId, { regressionTestRef, rootCause, rootCauseCategory }) {
  if (!regressionTestRef) {
    throw new Error('Cannot verify defect without a regression test (defect-discipline rule).');
  }
  return prisma.defectRecord.update({
    where: { id: defectId },
    data: {
      status: 'verified',
      verifiedAt: new Date(),
      fixedAt: new Date(),
      regressionTestAdded: true,
      regressionTestRef,
      rootCause: rootCause || undefined,
      rootCauseCategory: rootCauseCategory || undefined
    }
  });
}

// ─── AI evals ────────────────────────────────────────────────────────────────

/**
 * Run an AI eval. The caller supplies the measured metric scores (produced by
 * Promptfoo / a custom harness); this function records the AIEvalRun, computes
 * the overall verdict, detects regressions vs the previous run, and alerts on
 * poor scores.
 *
 * metricScores: { groundedness, relevance, faithfulness, coherence, ... } 0..1
 */
export async function recordAIEvalRun({
  aiSystem, systemDescription = null, llmProvider = null, llmModel = null,
  evalFramework = 'promptfoo', goldenDatasetSize, goldenDatasetVersion = null,
  metricScores = {}, promptInjectionResistanceScore = null,
  hallucinationDetected = 0, biasFlagsCount = 0,
  totalTokensUsed = null, estimatedCostUsd = null,
  userId = OWNER_ID
}) {
  const metricsEvaluated = Object.keys(metricScores);
  const scoreValues = Object.values(metricScores).filter(v => typeof v === 'number');
  const overallScore = scoreValues.length
    ? scoreValues.reduce((a, b) => a + b, 0) / scoreValues.length
    : null;

  // Compare against previous run for same system
  const previous = await prisma.aIEvalRun.findFirst({
    where: { userId, aiSystem },
    orderBy: { conductedAt: 'desc' }
  });

  let regressionDetected = false;
  let regressionDetails = null;
  if (previous && previous.overallScore != null && overallScore != null) {
    const drop = previous.overallScore - overallScore;
    if (drop > 0.05) {  // >5 percentage points drop = regression
      regressionDetected = true;
      regressionDetails =
        `Overall score dropped ${(drop * 100).toFixed(1)}pp ` +
        `(${(previous.overallScore * 100).toFixed(1)}% → ${(overallScore * 100).toFixed(1)}%) ` +
        `vs run #${previous.id}`;
    }
  }

  // Verdict
  let verdict = 'passed';
  const failures = [];
  for (const [metric, threshold] of Object.entries(AI_EVAL_THRESHOLDS)) {
    if (metric === 'overallPass') continue;
    if (metric in metricScores && metricScores[metric] < threshold) {
      failures.push(`${metric} ${(metricScores[metric] * 100).toFixed(0)}% < ${(threshold * 100).toFixed(0)}%`);
    }
  }
  if (promptInjectionResistanceScore != null &&
      promptInjectionResistanceScore < AI_EVAL_THRESHOLDS.promptInjectionResistance) {
    failures.push(`prompt injection resistance ${(promptInjectionResistanceScore * 100).toFixed(0)}%`);
  }
  if (hallucinationDetected > 0) failures.push(`${hallucinationDetected} hallucination(s)`);
  if (overallScore != null && overallScore < AI_EVAL_THRESHOLDS.overallPass) {
    failures.push(`overall ${(overallScore * 100).toFixed(0)}% < ${(AI_EVAL_THRESHOLDS.overallPass * 100).toFixed(0)}%`);
  }
  if (failures.length > 0) verdict = regressionDetected ? 'failed' : 'needs_review';

  const recommendations = failures.length
    ? `Review required: ${failures.join('; ')}.`
    : 'All metrics within thresholds.';

  const run = await prisma.aIEvalRun.create({
    data: {
      userId, aiSystem, systemDescription, llmProvider, llmModel,
      evalFramework, goldenDatasetSize, goldenDatasetVersion,
      metricsEvaluated: JSON.stringify(metricsEvaluated),
      metricScores: JSON.stringify(metricScores),
      overallScore,
      promptInjectionTested: promptInjectionResistanceScore != null,
      promptInjectionResistanceScore,
      hallucinationDetected, biasFlagsCount,
      totalTokensUsed, estimatedCostUsd,
      comparedToPreviousRunId: previous ? previous.id : null,
      regressionDetected, regressionDetails,
      verdict, recommendations,
      conductedAt: new Date()
    }
  });

  // Alert on failure or regression
  if (verdict === 'failed' || regressionDetected) {
    await publishToArchive({
      text: `🔴 *AI eval — ${verdict}* — ${aiSystem}\n` +
            (overallScore != null ? `Overall: ${(overallScore * 100).toFixed(1)}%\n` : '') +
            (regressionDetails ? `${regressionDetails}\n` : '') +
            `${recommendations}\n#qa #ai_eval #${slug(aiSystem)}`
    }).catch(() => {});
  }

  return run;
}

// ─── Security audit ──────────────────────────────────────────────────────────

/**
 * Record a security audit. findings: array of
 *   { id, severity, title, description, location, cve, recommendation, fixed }
 * Computes severity counts, pass/blockedRelease flags.
 */
export async function recordSecurityAudit({
  target, targetRepositoryId = null, auditType, scope,
  methodology = null, findings = [], userId = OWNER_ID
}) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const f of findings) {
    if (f.severity in counts) counts[f.severity]++;
  }
  const totalFindings = findings.length;
  // Pass if no critical/high unfixed findings
  const unfixedCriticalHigh = findings.filter(
    f => (f.severity === 'critical' || f.severity === 'high') && !f.fixed
  ).length;
  const passedAudit = unfixedCriticalHigh === 0;
  const blockedRelease = !passedAudit;

  const audit = await prisma.securityAudit.create({
    data: {
      userId, target, targetRepositoryId, auditType, scope, methodology,
      findings: JSON.stringify(findings),
      totalFindings,
      criticalCount: counts.critical, highCount: counts.high,
      mediumCount: counts.medium, lowCount: counts.low,
      passedAudit, blockedRelease,
      conductedAt: new Date(),
      nextAuditDue: new Date(Date.now() + 180 * 24 * 60 * 60 * 1000) // +6 months
    }
  });

  if (!passedAudit) {
    await publishToArchive({
      text: `🛡️ *Security audit FAILED* — ${target}\n` +
            `Critical: ${counts.critical} | High: ${counts.high} | ` +
            `Medium: ${counts.medium} | Low: ${counts.low}\n` +
            `Release BLOCKED.\n#qa #security #audit_failed`
    }).catch(() => {});
  }

  return audit;
}

// ─── Scheduled tasks ─────────────────────────────────────────────────────────

/**
 * Daily production monitor (scheduler 08:00). Reviews recent test runs and
 * open defects; alerts the owner if production needs attention.
 */
export async function dailyProductionMonitor(userId = OWNER_ID) {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000);

  const [recentRuns, openCritical, openHigh, recentDefects] = await Promise.all([
    prisma.testRun.findMany({
      where: { userId, startedAt: { gte: since } }
    }),
    prisma.defectRecord.count({
      where: { userId, severity: 'critical', status: { in: ['open', 'acknowledged', 'in_progress'] } }
    }),
    prisma.defectRecord.count({
      where: { userId, severity: 'high', status: { in: ['open', 'acknowledged', 'in_progress'] } }
    }),
    prisma.defectRecord.findMany({
      where: { userId, createdAt: { gte: since } }
    })
  ]);

  const failedRuns = recentRuns.filter(r => r.verdict === 'failed').length;
  const needsAttention = openCritical > 0 || failedRuns > 0;

  const report = {
    date: new Date().toISOString().slice(0, 10),
    testRuns24h: recentRuns.length,
    failedRuns24h: failedRuns,
    newDefects24h: recentDefects.length,
    openCriticalDefects: openCritical,
    openHighDefects: openHigh,
    needsAttention
  };

  if (needsAttention) {
    await publishToArchive({
      text: `📋 *QA daily — внимание требуется*\n` +
            `Провалов тестов за сутки: ${failedRuns}\n` +
            `Открытых critical-дефектов: ${openCritical}\n` +
            `Открытых high-дефектов: ${openHigh}\n` +
            `#qa #daily #attention`
    }).catch(() => {});
  }

  return report;
}

/**
 * Weekly security scan (scheduler Sunday 05:00). Records a dependency-audit
 * style SecurityAudit per active repository. Actual `npm audit` output is
 * supplied by the caller (bot collects it); here we persist + flag.
 */
export async function weeklySecurityScan(auditInputs = [], userId = OWNER_ID) {
  // auditInputs: [{ target, targetRepositoryId, findings }]
  const results = [];
  for (const input of auditInputs) {
    const audit = await recordSecurityAudit({
      target: input.target,
      targetRepositoryId: input.targetRepositoryId || null,
      auditType: 'dependency_audit',
      scope: 'Weekly automated dependency vulnerability scan',
      methodology: 'npm audit + advisory cross-check',
      findings: input.findings || [],
      userId
    });
    results.push(audit);
  }

  const blocked = results.filter(a => a.blockedRelease).length;
  return {
    scannedAt: new Date().toISOString(),
    repositoriesScanned: results.length,
    repositoriesWithBlockingFindings: blocked,
    audits: results.map(a => ({ id: a.id, target: a.target, passed: a.passedAudit }))
  };
}

/**
 * Quarterly methodology review (scheduler Jan/Apr/Jul/Oct). Aggregates the
 * quarter's QA metrics and surfaces systematic weaknesses for skill updates.
 */
export async function quarterlyMethodologyReview(userId = OWNER_ID) {
  const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);

  const [runs, defects, aiEvals, audits] = await Promise.all([
    prisma.testRun.findMany({ where: { userId, startedAt: { gte: since } } }),
    prisma.defectRecord.findMany({ where: { userId, createdAt: { gte: since } } }),
    prisma.aIEvalRun.findMany({ where: { userId, conductedAt: { gte: since } } }),
    prisma.securityAudit.findMany({ where: { userId, conductedAt: { gte: since } } })
  ]);

  // Defect escape rate = defects that reached production / total
  const escaped = defects.filter(d => d.reachedProduction).length;
  const escapeRate = defects.length ? escaped / defects.length : 0;

  // Root cause clustering
  const rootCauseClusters = {};
  for (const d of defects) {
    const cat = d.rootCauseCategory || 'unclassified';
    rootCauseClusters[cat] = (rootCauseClusters[cat] || 0) + 1;
  }

  // Regression test discipline adherence
  const closedDefects = defects.filter(d => d.status === 'verified' || d.status === 'fixed');
  const withRegressionTest = closedDefects.filter(d => d.regressionTestAdded).length;
  const regressionDiscipline = closedDefects.length
    ? withRegressionTest / closedDefects.length
    : 1;

  // AI eval health
  const aiEvalPassRate = aiEvals.length
    ? aiEvals.filter(e => e.verdict === 'passed').length / aiEvals.length
    : null;
  const aiRegressions = aiEvals.filter(e => e.regressionDetected).length;

  // Test pyramid balance
  const byType = {};
  for (const r of runs) byType[r.testType] = (byType[r.testType] || 0) + 1;

  // Identify systematic weaknesses → feed into skill updates
  const weaknesses = [];
  if (escapeRate > 0.10) {
    weaknesses.push(`Defect escape rate ${(escapeRate * 100).toFixed(1)}% > 10% target — strengthen failure-modes-mapping / test-strategy-design.`);
  }
  if (regressionDiscipline < 0.95) {
    weaknesses.push(`Regression-test discipline ${(regressionDiscipline * 100).toFixed(0)}% < 95% — reinforce defect-discipline skill.`);
  }
  if (aiRegressions > 0) {
    weaknesses.push(`${aiRegressions} AI eval regression(s) detected — review ai-evals-framework prompt regression coverage.`);
  }
  const topRootCause = Object.entries(rootCauseClusters).sort((a, b) => b[1] - a[1])[0];
  if (topRootCause && topRootCause[1] >= 3) {
    weaknesses.push(`Root-cause cluster "${topRootCause[0]}" (${topRootCause[1]} defects) — candidate for a targeted skill update.`);
  }

  const review = {
    period: `${since.toISOString().slice(0, 10)} … ${new Date().toISOString().slice(0, 10)}`,
    testRuns: runs.length,
    testTypeBreakdown: byType,
    totalDefects: defects.length,
    defectEscapeRate: Number(escapeRate.toFixed(3)),
    escapeRateTarget: 0.10,
    rootCauseClusters,
    regressionTestDiscipline: Number(regressionDiscipline.toFixed(3)),
    aiEvalRuns: aiEvals.length,
    aiEvalPassRate: aiEvalPassRate != null ? Number(aiEvalPassRate.toFixed(3)) : null,
    aiEvalRegressions: aiRegressions,
    securityAudits: audits.length,
    securityAuditsFailed: audits.filter(a => !a.passedAudit).length,
    systematicWeaknesses: weaknesses,
    // Quarterly review must produce >= 1 skill change or explicit justification
    skillUpdateRequired: weaknesses.length > 0
      ? weaknesses
      : ['No systematic weakness found this quarter. Justification: metrics within targets, no root-cause cluster >= 3, no AI regressions.']
  };

  await publishToArchive({
    text: `📊 *QA quarterly review*\n` +
          `Тестовых прогонов: ${runs.length} | Дефектов: ${defects.length}\n` +
          `Escape rate: ${(escapeRate * 100).toFixed(1)}% (цель ≤10%)\n` +
          `Regression-discipline: ${(regressionDiscipline * 100).toFixed(0)}%\n` +
          (aiEvalPassRate != null ? `AI eval pass-rate: ${(aiEvalPassRate * 100).toFixed(0)}%\n` : '') +
          `Слабостей выявлено: ${weaknesses.length}\n` +
          `#qa #quarterly #methodology`
  }).catch(() => {});

  return review;
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listTestRuns(filter = {}, limit = 20) {
  const { target, testType, verdict, userId = OWNER_ID } = filter;
  const where = { userId };
  if (target) where.target = target;
  if (testType) where.testType = testType;
  if (verdict) where.verdict = verdict;
  return prisma.testRun.findMany({ where, orderBy: { startedAt: 'desc' }, take: limit });
}

export async function listDefects(filter = {}, limit = 30) {
  const { severity, status, category, project, userId = OWNER_ID } = filter;
  const where = { userId };
  if (severity) where.severity = severity;
  if (status) where.status = status;
  if (category) where.category = category;
  const defects = await prisma.defectRecord.findMany({
    where, orderBy: { createdAt: 'desc' }, take: limit
  });
  // Sort by severity within the result for triage convenience
  return defects.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

export async function listAIEvalRuns(filter = {}, limit = 20) {
  const { aiSystem, verdict, userId = OWNER_ID } = filter;
  const where = { userId };
  if (aiSystem) where.aiSystem = aiSystem;
  if (verdict) where.verdict = verdict;
  return prisma.aIEvalRun.findMany({ where, orderBy: { conductedAt: 'desc' }, take: limit });
}

/**
 * Coverage report: latest coverage figure per target from recent test runs.
 */
export async function getCoverageReport(target, userId = OWNER_ID) {
  const runs = await prisma.testRun.findMany({
    where: { userId, target, coverage: { not: null } },
    orderBy: { startedAt: 'desc' },
    take: 10
  });
  if (runs.length === 0) return { target, coverage: null, note: 'No coverage data recorded.' };
  const latest = runs[0];
  return {
    target,
    latestCoverage: latest.coverage,
    targets: COVERAGE_TARGETS,
    meetsOverallTarget: latest.coverage >= COVERAGE_TARGETS.overall,
    history: runs.map(r => ({ at: r.startedAt, coverage: r.coverage }))
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40);
}

async function publishToArchive({ text }) {
  if (!ARCHIVE_CHANNEL_ID || !TELEGRAM_TOKEN) return null;
  const resp = await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: ARCHIVE_CHANNEL_ID,
      text: text.slice(0, 4096),
      parse_mode: 'Markdown',
      disable_web_page_preview: true
    })
  });
  const data = await resp.json();
  return data.ok ? data.result : null;
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  generateTestStrategy,
  createTestRun,
  completeTestRun,
  recordDefect,
  defectNeedsHotfix,
  assignDefectToTask,
  verifyDefectFix,
  recordAIEvalRun,
  recordSecurityAudit,
  dailyProductionMonitor,
  weeklySecurityScan,
  quarterlyMethodologyReview,
  listTestRuns,
  listDefects,
  listAIEvalRuns,
  getCoverageReport
};
