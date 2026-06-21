// ============================================================================
// lib/kk.js — Kuznitsa (Veteran department) engine
// ============================================================================
//
// Core operations for the Kuznitsa (Кузница кадров) — the recursive department
// that creates and re-trains all other departments. Per METHODOLOGY.md Part III.
//
//   - recruit: run a new department through the 10-stage checklist
//   - train: assemble a training curriculum for a specialist
//   - polygon: run a specialist through training tasks, compute pass-rate
//   - debrief: structural error analysis of a struggling department
//   - assess: psychotype assessment / fit check
//   - recalibrate: full retraining (owner-approval-gated)
//   - forge-status: overall Kuznitsa status
//   - monthly aggregation across all departments
//   - quarterly methodology review (may only REPLACE rules, not add)
//
// Storage: TrainingSession / KuznitsaMonthlyReview in DB. Significant
// operations auto-published to the Telegram archive.
//
// The Kuznitsa is recursive — built by the methodology it teaches.
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Constants ───────────────────────────────────────────────────────────────

const OPERATION_TYPES = [
  'recruit', 'train', 'polygon', 'debrief', 'assess', 'recalibrate', 'forge_status'
];

// The 10-stage checklist (METHODOLOGY.md I.4)
const CHECKLIST_STAGES = [
  { stage: 1,  name: 'Specification' },
  { stage: 2,  name: 'Profile (library/<dept>.md)' },
  { stage: 3,  name: 'Skills (3 tiers, 8-15 total)' },
  { stage: 4,  name: 'Archive (Prisma models)' },
  { stage: 5,  name: 'Commands' },
  { stage: 6,  name: 'Scheduler integration' },
  { stage: 7,  name: 'army.js registration' },
  { stage: 8,  name: 'Yana registration' },
  { stage: 9,  name: 'Polygon (5-10 tasks)' },
  { stage: 10, name: 'Polygon run (pass-rate >= 70%)' }
];

// The 7 psychotypes (METHODOLOGY.md II.1)
const PSYCHOTYPES = [
  'pedant', 'paranoid', 'pragmatist', 'experimenter', 'empath', 'methodist', 'mediator'
];

// Department → psychotype mapping (METHODOLOGY.md II.2) — used by assess
const DEPT_PSYCHOTYPE_MAP = {
  osp:         { primary: 'paranoid',     secondary: 'pedant' },
  finance:     { primary: 'pedant',       secondary: 'methodist' },
  legal:       { primary: 'paranoid',     secondary: 'pedant' },
  dev:         { primary: 'pragmatist',   secondary: 'methodist' },
  marketing:   { primary: 'empath',       secondary: 'experimenter' },
  operations:  { primary: 'methodist',    secondary: 'pedant' },
  ai_studio:   { primary: 'experimenter', secondary: 'pragmatist' },
  upravlenie:  { primary: 'mediator',     secondary: 'empath' },
  kk:          { primary: 'methodist',    secondary: 'paranoid' },
  engineering: { primary: 'paranoid',     secondary: 'pedant' }
};

// The polygon release gate (METHODOLOGY.md — Kuznitsa hard rule 2)
const POLYGON_PASS_GATE = 0.70;

// Kuznitsa metric targets (METHODOLOGY.md II.3.9)
const KK_TARGETS = {
  newSpecialistPassRate: 0.70,
  quarterlyImprovementRate: 0.15,
  reworkRate: 0.20
};

// ─── Recruit — create a new department ───────────────────────────────────────

/**
 * Open a recruit session. Initializes the 10-stage checklist, all stages
 * not-done. The actual stage work is performed by the Veteran specialist
 * following the methodology-application + specialist-creation skills; this
 * records progress.
 */
export async function startRecruit({ targetDepartment, targetDescription = null, userId = OWNER_ID }) {
  const checklist = CHECKLIST_STAGES.map(s => ({ ...s, done: false, note: null }));
  return prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'recruit',
      targetDepartment,
      targetDescription,
      checklistStages: JSON.stringify(checklist),
      checklistComplete: false,
      status: 'in_progress'
    }
  });
}

/**
 * Mark a checklist stage done (or not) with a note. Recomputes whether the
 * whole checklist is complete.
 */
export async function updateChecklistStage(sessionId, { stage, done, note = null }) {
  const session = await prisma.trainingSession.findUnique({ where: { id: sessionId } });
  if (!session) throw new Error(`TrainingSession ${sessionId} not found`);

  const checklist = JSON.parse(session.checklistStages || '[]');
  const target = checklist.find(s => s.stage === stage);
  if (!target) throw new Error(`Stage ${stage} not found in checklist`);
  target.done = done;
  target.note = note;

  const checklistComplete = checklist.every(s => s.done);

  return prisma.trainingSession.update({
    where: { id: sessionId },
    data: {
      checklistStages: JSON.stringify(checklist),
      checklistComplete
    }
  });
}

/**
 * Set the psychotype for a recruit session (stage 1/3 work).
 */
export async function setSessionPsychotype(sessionId, {
  psychotypeAssigned, psychotypeRationale, psychotypeFitsFunction = true
}) {
  return prisma.trainingSession.update({
    where: { id: sessionId },
    data: { psychotypeAssigned, psychotypeRationale, psychotypeFitsFunction }
  });
}

/**
 * Complete a recruit session. Enforces the two hard gates:
 *   - all 10 checklist stages done (hard rule 1)
 *   - polygon pass-rate >= 70% (hard rule 2)
 */
export async function completeRecruit(sessionId) {
  const session = await prisma.trainingSession.findUnique({ where: { id: sessionId } });
  if (!session) throw new Error(`TrainingSession ${sessionId} not found`);

  if (!session.checklistComplete) {
    const checklist = JSON.parse(session.checklistStages || '[]');
    const pending = checklist.filter(s => !s.done).map(s => `${s.stage}. ${s.name}`);
    throw new Error(`Cannot complete recruit: checklist incomplete (hard rule 1). ` +
                    `Pending stages: ${pending.join('; ')}`);
  }
  if (session.polygonPassRate == null || session.polygonPassRate < POLYGON_PASS_GATE) {
    throw new Error(`Cannot complete recruit: polygon pass-rate ` +
                    `${session.polygonPassRate != null ? (session.polygonPassRate * 100).toFixed(0) + '%' : 'not run'} ` +
                    `is below the 70% gate (hard rule 2). Iterate skills and re-run the polygon.`);
  }
  if (!session.psychotypeAssigned) {
    throw new Error(`Cannot complete recruit: no psychotype assigned (hard rule 4 / ` +
                    `anti-pattern III.9.2 cookie-cutter). Run psychotype-assessment.`);
  }

  const updated = await prisma.trainingSession.update({
    where: { id: sessionId },
    data: {
      status: 'completed',
      completedAt: new Date(),
      outcomeSummary: `Department "${session.targetDepartment}" recruited: ` +
        `all 10 stages complete, polygon ${(session.polygonPassRate * 100).toFixed(0)}%, ` +
        `psychotype ${session.psychotypeAssigned}.`
    }
  });

  await publishToArchive({
    text: `🏗 *Кузница — отдел создан* — ${session.targetDepartment}\n` +
          `Все 10 этапов чек-листа пройдены\n` +
          `Полигон: ${(session.polygonPassRate * 100).toFixed(0)}% (порог 70%)\n` +
          `Психотип: ${session.psychotypeAssigned}\n#kuznitsa #recruit #completed`
  }).catch(() => {});

  return updated;
}

// ─── Polygon ─────────────────────────────────────────────────────────────────

/**
 * Record a polygon run. Computes pass-rate and whether the 70% gate is met.
 * Can attach to an existing recruit session or create a standalone polygon
 * session.
 * systematicErrors: array of strings — error patterns found across tasks.
 */
export async function recordPolygonRun({
  sessionId = null, targetDepartment, tasksTotal, tasksPassed,
  systematicErrors = [], userId = OWNER_ID
}) {
  if (tasksTotal < 5 || tasksTotal > 10) {
    // METHODOLOGY.md I.4 stage 9 — polygon is 5-10 tasks
    console.warn(`[kk] polygon has ${tasksTotal} tasks; methodology specifies 5-10.`);
  }
  const passRate = tasksTotal > 0 ? tasksPassed / tasksTotal : 0;
  const passed = passRate >= POLYGON_PASS_GATE;

  if (sessionId) {
    const updated = await prisma.trainingSession.update({
      where: { id: sessionId },
      data: {
        polygonTasksTotal: tasksTotal,
        polygonTasksPassed: tasksPassed,
        polygonPassRate: passRate,
        polygonPassed: passed,
        systematicErrors: JSON.stringify(systematicErrors)
      }
    });
    await announcePolygon(targetDepartment, passRate, passed, systematicErrors);
    return updated;
  }

  // Standalone polygon session
  const session = await prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'polygon',
      targetDepartment,
      polygonTasksTotal: tasksTotal,
      polygonTasksPassed: tasksPassed,
      polygonPassRate: passRate,
      polygonPassed: passed,
      systematicErrors: JSON.stringify(systematicErrors),
      status: 'completed',
      completedAt: new Date(),
      outcomeSummary: `Polygon: ${tasksPassed}/${tasksTotal} (${(passRate * 100).toFixed(0)}%) — ` +
        `${passed ? 'PASSED' : 'BELOW GATE'}`
    }
  });
  await announcePolygon(targetDepartment, passRate, passed, systematicErrors);
  return session;
}

async function announcePolygon(dept, passRate, passed, systematicErrors) {
  await publishToArchive({
    text: `🎯 *Кузница — полигон* — ${dept}\n` +
          `Pass-rate: ${(passRate * 100).toFixed(0)}% — ${passed ? '✅ порог пройден' : '⚠️ ниже порога 70%'}\n` +
          (systematicErrors.length
            ? `Систематические ошибки: ${systematicErrors.length}\n` +
              `→ передать в Tier 1 скиллы отдела\n`
            : '') +
          `#kuznitsa #polygon`
  }).catch(() => {});
}

// ─── Train ───────────────────────────────────────────────────────────────────

/**
 * Record a training (curriculum) session for an existing specialist.
 */
export async function recordTraining({
  targetDepartment, targetDescription, psychotype = null, userId = OWNER_ID
}) {
  return prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'train',
      targetDepartment,
      targetDescription,
      psychotypeAssigned: psychotype,
      status: 'in_progress'
    }
  });
}

// ─── Debrief ─────────────────────────────────────────────────────────────────

/**
 * Record a structural debrief of a department (METHODOLOGY.md — debrief is
 * automatic, non-accusatory). errorNature: 'training_gap' | 'psychotype_mismatch'.
 * improvementPlan: array of concrete change strings.
 */
export async function recordDebrief({
  targetDepartment, debriefDiagnosis, errorNature = 'training_gap',
  improvementPlan = [], userId = OWNER_ID
}) {
  if (!['training_gap', 'psychotype_mismatch'].includes(errorNature)) {
    throw new Error(`errorNature must be 'training_gap' or 'psychotype_mismatch'.`);
  }

  const session = await prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'debrief',
      targetDepartment,
      debriefDiagnosis,
      errorNature,
      improvementPlan: JSON.stringify(improvementPlan),
      status: 'completed',
      completedAt: new Date(),
      outcomeSummary: errorNature === 'psychotype_mismatch'
        ? 'Error of NATURE — psychotype mismatch. Candidate for recalibration (owner approval required).'
        : `Error of TRAINING — ${improvementPlan.length} skill change(s) planned.`
    }
  });

  await publishToArchive({
    text: `🔬 *Кузница — разбор отдела* — ${targetDepartment}\n` +
          `Природа ошибки: ${errorNature === 'psychotype_mismatch'
            ? 'психотип (требует recalibration)' : 'обучение (правится скиллами)'}\n` +
          `Улучшений в плане: ${improvementPlan.length}\n` +
          `Разбор структурный, не обвинительный.\n#kuznitsa #debrief`
  }).catch(() => {});

  return session;
}

// ─── Assess ──────────────────────────────────────────────────────────────────

/**
 * Assess a department's psychotype against its catalogued mapping
 * (METHODOLOGY.md II.2). Flags a possible mismatch.
 */
export async function recordAssessment({
  targetDepartment, observedPsychotype, missPattern = null, userId = OWNER_ID
}) {
  const catalogued = DEPT_PSYCHOTYPE_MAP[targetDepartment.toLowerCase()];
  let fitsFunction = null;
  let note = '';

  if (catalogued) {
    fitsFunction = observedPsychotype
      ? (observedPsychotype === catalogued.primary || observedPsychotype === catalogued.secondary)
      : null;
    note = `Catalogued (II.2): ${catalogued.primary} + ${catalogued.secondary}. ` +
           (observedPsychotype
             ? `Observed: ${observedPsychotype} — ${fitsFunction ? 'consistent' : 'DIVERGENCE'}.`
             : 'No observed psychotype supplied.');
  } else {
    note = `Department "${targetDepartment}" not in the II.2 catalogue — new department; ` +
           `psychotype to be chosen on its work nature.`;
  }

  return prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'assess',
      targetDepartment,
      psychotypeAssigned: observedPsychotype || catalogued?.primary || null,
      psychotypeRationale: note,
      psychotypeFitsFunction: fitsFunction,
      debriefDiagnosis: missPattern,
      status: 'completed',
      completedAt: new Date(),
      outcomeSummary: note
    }
  });
}

// ─── Recalibrate (owner-approval-gated) ──────────────────────────────────────

/**
 * Open a recalibration session. Per Kuznitsa hard rule 8, recalibration
 * REQUIRES explicit owner approval — the session starts in_progress and
 * cannot proceed past planning until approveRecalibration is called.
 */
export async function startRecalibration({
  targetDepartment, debriefSessionId = null, metricBefore = null, userId = OWNER_ID
}) {
  return prisma.trainingSession.create({
    data: {
      userId,
      operationType: 'recalibrate',
      targetDepartment,
      targetDescription: debriefSessionId
        ? `Recalibration following debrief session #${debriefSessionId}`
        : 'Recalibration',
      metricBefore,
      ownerApproved: false,   // hard rule 8 — not yet approved
      status: 'in_progress',
      outcomeSummary: 'AWAITING OWNER APPROVAL — recalibration cannot proceed (hard rule 8).'
    }
  });
}

/**
 * Record explicit owner approval for a recalibration (hard rule 8).
 * Without this, the recalibration must not proceed.
 */
export async function approveRecalibration(sessionId) {
  const session = await prisma.trainingSession.findUnique({ where: { id: sessionId } });
  if (!session) throw new Error(`TrainingSession ${sessionId} not found`);
  if (session.operationType !== 'recalibrate') {
    throw new Error(`Session ${sessionId} is not a recalibration.`);
  }
  return prisma.trainingSession.update({
    where: { id: sessionId },
    data: {
      ownerApproved: true,
      ownerApprovedAt: new Date(),
      outcomeSummary: 'Owner-approved. Recalibration may proceed: re-assess psychotype, ' +
        'rewrite Tier 1, new polygon.'
    }
  });
}

/**
 * Complete a recalibration. Requires owner approval, a re-run polygon passing
 * the gate, and records the metric improvement for verification.
 */
export async function completeRecalibration(sessionId, { metricAfter }) {
  const session = await prisma.trainingSession.findUnique({ where: { id: sessionId } });
  if (!session) throw new Error(`TrainingSession ${sessionId} not found`);
  if (!session.ownerApproved) {
    throw new Error('Cannot complete recalibration: owner approval was never recorded ' +
                    '(hard rule 8). Recalibration must not have proceeded.');
  }
  if (session.polygonPassRate == null || session.polygonPassRate < POLYGON_PASS_GATE) {
    throw new Error('Cannot complete recalibration: the new polygon has not passed the ' +
                    '70% gate. Iterate and re-run.');
  }

  const improvementRate = (session.metricBefore != null && session.metricBefore !== 0)
    ? (metricAfter - session.metricBefore) / Math.abs(session.metricBefore)
    : null;

  const verified = improvementRate != null && improvementRate >= KK_TARGETS.quarterlyImprovementRate;

  const updated = await prisma.trainingSession.update({
    where: { id: sessionId },
    data: {
      metricAfter,
      improvementRate,
      status: 'completed',
      completedAt: new Date(),
      outcomeSummary: improvementRate != null
        ? `Recalibration complete. Metric improvement: ${(improvementRate * 100).toFixed(0)}% ` +
          `(target >=15%) — ${verified ? 'VERIFIED' : 'below target, debrief the recalibration itself'}.`
        : 'Recalibration complete. No baseline metric — improvement unverifiable.'
    }
  });

  await publishToArchive({
    text: `🔧 *Кузница — переподготовка завершена* — ${session.targetDepartment}\n` +
          (improvementRate != null
            ? `Улучшение метрики: ${(improvementRate * 100).toFixed(0)}% (цель ≥15%) — ` +
              `${verified ? '✅ подтверждено' : '⚠️ ниже цели'}\n`
            : '') +
          `Не забыть: уведомить Яну о новом режиме работы отдела.\n` +
          `#kuznitsa #recalibrate #completed`
  }).catch(() => {});

  return updated;
}

// ─── Monthly / quarterly ─────────────────────────────────────────────────────

/**
 * Monthly aggregation across all departments — the Kuznitsa's
 * department-of-departments view.
 * departmentMetrics (supplied by the bot, gathered from each dept's score):
 *   [{ department, belowTarget: bool, consecutiveSubTargetMonths: int }]
 */
export async function monthlyReview(departmentMetrics = [], userId = OWNER_ID) {
  const periodEnd = new Date();
  const periodStart = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);

  const sessions = await prisma.trainingSession.findMany({
    where: { userId, startedAt: { gte: periodStart } }
  });

  const recruited = sessions.filter(s => s.operationType === 'recruit' && s.status === 'completed').length;
  const recalibrated = sessions.filter(s => s.operationType === 'recalibrate' && s.status === 'completed').length;

  // New-specialist pass-rate this month
  const recruitSessions = sessions.filter(s => s.operationType === 'recruit' && s.polygonPassRate != null);
  const newSpecialistPassRate = recruitSessions.length
    ? recruitSessions.filter(s => s.polygonPassed).length / recruitSessions.length
    : null;

  // Average improvement rate from completed recalibrations
  const recalSessions = sessions.filter(s => s.operationType === 'recalibrate' && s.improvementRate != null);
  const avgImprovementRate = recalSessions.length
    ? recalSessions.reduce((a, s) => a + s.improvementRate, 0) / recalSessions.length
    : null;

  // Departments needing attention: 2+ consecutive sub-target months (hard rule 7)
  const needingAttention = departmentMetrics
    .filter(d => d.consecutiveSubTargetMonths >= 2)
    .map(d => ({
      department: d.department,
      consecutiveSubTargetMonths: d.consecutiveSubTargetMonths,
      recommendedAction: d.consecutiveSubTargetMonths >= 3
        ? '/assess psychotype — possible error of nature'
        : '/debrief — two sub-target months is a pattern'
    }));

  const review = await prisma.kuznitsaMonthlyReview.create({
    data: {
      userId, periodStart, periodEnd,
      operationsTotal: sessions.length,
      departmentsRecruited: recruited,
      departmentsRecalibrated: recalibrated,
      newSpecialistPassRate,
      avgImprovementRate,
      departmentsNeedingAttention: JSON.stringify(needingAttention)
    }
  });

  await publishToArchive({
    text: `📋 *Кузница — месячный обзор всех отделов*\n` +
          `Операций Кузницы: ${sessions.length}\n` +
          `Создано отделов: ${recruited} | Переобучено: ${recalibrated}\n` +
          (newSpecialistPassRate != null
            ? `Pass-rate новых: ${(newSpecialistPassRate * 100).toFixed(0)}% (цель ≥70%)\n` : '') +
          `Отделов требуют внимания: ${needingAttention.length}\n` +
          (needingAttention.length
            ? needingAttention.map(d => `  • ${d.department}: ${d.recommendedAction}`).join('\n') + '\n'
            : '') +
          `#kuznitsa #monthly`
  }).catch(() => {});

  return review;
}

/**
 * Quarterly methodology review. Per anti-pattern III.9.4, the methodology may
 * only have rules REPLACED, not added — this function flags growth.
 */
export async function quarterlyMethodologyReview({ methodologyLineCount = null, previousLineCount = null } = {}) {
  const methodologyGrew = (methodologyLineCount != null && previousLineCount != null)
    ? methodologyLineCount > previousLineCount
    : null;

  return {
    period: 'quarterly',
    note: 'Quarterly methodology review (METHODOLOGY.md epilogue). Reviews accumulated ' +
          'error patterns across all departments, identifies persistent methodology ' +
          'weaknesses, updates skills.',
    bloatCheck: {
      methodologyLineCount,
      previousLineCount,
      methodologyGrew,
      rule: 'Anti-pattern III.9.4 — quarterly review may only REPLACE methodology rules, ' +
            'not add. If methodologyGrew is true, a rule was added — revert or replace instead.',
      warning: methodologyGrew === true
        ? 'METHODOLOGY GREW THIS QUARTER — review what was added; the methodology size is fixed.'
        : 'No methodology growth detected.'
    },
    skillUpdateRequired: [
      'Per anti-pattern I.5.4 (pseudo-learning): the quarterly review must produce at ' +
      'least one skill change OR an explicit, specific justification of why none is needed.'
    ]
  };
}

// ─── Forge status ────────────────────────────────────────────────────────────

/**
 * Overall Kuznitsa status (/forge-status): which departments passed through,
 * which need attention, recent polygon results.
 */
export async function forgeStatus(userId = OWNER_ID) {
  const [recentSessions, lastMonthlyReview] = await Promise.all([
    prisma.trainingSession.findMany({
      where: { userId },
      orderBy: { startedAt: 'desc' },
      take: 20
    }),
    prisma.kuznitsaMonthlyReview.findFirst({
      where: { userId },
      orderBy: { periodStart: 'desc' }
    })
  ]);

  const recruited = recentSessions
    .filter(s => s.operationType === 'recruit' && s.status === 'completed')
    .map(s => s.targetDepartment);

  const recentPolygons = recentSessions
    .filter(s => s.polygonPassRate != null)
    .slice(0, 5)
    .map(s => ({
      department: s.targetDepartment,
      passRate: s.polygonPassRate,
      passed: s.polygonPassed
    }));

  const inProgress = recentSessions
    .filter(s => s.status === 'in_progress')
    .map(s => ({ id: s.id, type: s.operationType, department: s.targetDepartment }));

  let needingAttention = [];
  if (lastMonthlyReview) {
    try { needingAttention = JSON.parse(lastMonthlyReview.departmentsNeedingAttention || '[]'); }
    catch { needingAttention = []; }
  }

  return {
    departmentsRecruited: recruited,
    recentPolygons,
    operationsInProgress: inProgress,
    departmentsNeedingAttention: needingAttention,
    lastMonthlyReview: lastMonthlyReview ? lastMonthlyReview.periodStart : null
  };
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listSessions(filter = {}, limit = 20) {
  const { operationType, targetDepartment, status, userId = OWNER_ID } = filter;
  const where = { userId };
  if (operationType) where.operationType = operationType;
  if (targetDepartment) where.targetDepartment = targetDepartment;
  if (status) where.status = status;
  return prisma.trainingSession.findMany({
    where, orderBy: { startedAt: 'desc' }, take: limit
  });
}

export async function getSession(sessionId, userId = OWNER_ID) {
  return prisma.trainingSession.findFirst({ where: { id: sessionId, userId } });
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

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
  startRecruit,
  updateChecklistStage,
  setSessionPsychotype,
  completeRecruit,
  recordPolygonRun,
  recordTraining,
  recordDebrief,
  recordAssessment,
  startRecalibration,
  approveRecalibration,
  completeRecalibration,
  monthlyReview,
  quarterlyMethodologyReview,
  forgeStatus,
  listSessions,
  getSession,
  CHECKLIST_STAGES,
  PSYCHOTYPES,
  POLYGON_PASS_GATE
};
