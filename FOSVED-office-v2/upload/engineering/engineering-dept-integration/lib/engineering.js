// ============================================================================
// lib/engineering.js — Engineering Department engine
// ============================================================================
//
// Core operations for the Engineering (Инженерный) department — a PROJECT
// ASSISTANT that prepares preliminary calculations for a licensed engineer to
// review, approve, and sign. Three disciplines: structural mechanics,
// hydraulics, power electronics.
//
//   - Calculation creation with mandatory norm base, load cases, disclaimer
//   - Lifecycle: drafted → calculated → self_verified → sent_for_review →
//     engineer_approved / engineer_corrected → archived
//   - Norm reference catalogue
//   - Design reviews (third-party / sanity-check / feasibility)
//   - Calculation verification (the engineer's review is the source of truth)
//   - Monthly performance review (correction-rate, error clustering)
//   - Quarterly methodology review
//
// CRITICAL: every output carries the preliminary-work disclaimer. The
// department never approves or signs — that is the licensed engineer's role.
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Constants ───────────────────────────────────────────────────────────────

const DISCIPLINES = ['structural', 'hydraulic', 'power_electronics'];

const ERROR_CLASSES = [
  'missed_load_case', 'wrong_coefficient', 'wrong_norm',
  'dimensional_error', 'wrong_assumption', 'method_error', 'none'
];

// The mandatory disclaimer (hard rule 1) — never removed, top and bottom.
const DISCLAIMER_TOP =
  '═══════════════════════════════════════════════════════\n' +
  '⚠ ПРЕДВАРИТЕЛЬНО — требует проверки дипломированным инженером\n' +
  '  Расчёт выполнен как вспомогательный материал. Подлежит\n' +
  '  обязательной проверке и утверждению дипломированным\n' +
  '  инженером соответствующей специальности. Не является\n' +
  '  основанием для строительства, монтажа или производства\n' +
  '  без такой проверки.\n' +
  '═══════════════════════════════════════════════════════';

const DISCLAIMER_BOTTOM =
  '═══════════════════════════════════════════════════════\n' +
  '⚠ Напоминание: документ ПРЕДВАРИТЕЛЬНЫЙ. Финальную\n' +
  '  ответственность несёт проверяющий дипломированный инженер.\n' +
  '═══════════════════════════════════════════════════════';

// Default norm system — RF. The norm system is a per-task parameter.
const DEFAULT_NORM_SYSTEM = 'RF';

// Engineer-correction-rate targets by year (department metric)
const CORRECTION_RATE_TARGETS = { year1: 0.25, year2: 0.15, year3: 0.10 };

// ─── Disclaimer ──────────────────────────────────────────────────────────────

/**
 * Wrap any engineering output in the mandatory disclaimer (hard rule 1).
 * This is applied to every result the department emits — there is no path
 * that produces output without it.
 */
export function wrapWithDisclaimer(content) {
  return `${DISCLAIMER_TOP}\n\n${content}\n\n${DISCLAIMER_BOTTOM}`;
}

// ─── Calculations ────────────────────────────────────────────────────────────

/**
 * Create an engineering calculation in `drafted` state. Norm base and load
 * cases are NOT yet set — they are mandatory and added by the dedicated
 * functions before the calculation can progress.
 */
export async function createCalculation({
  title, discipline, taskDescription, objectType = null, userId = OWNER_ID
}) {
  if (!DISCIPLINES.includes(discipline)) {
    throw new Error(
      `Unknown discipline "${discipline}". The department covers exactly: ` +
      `${DISCIPLINES.join(', ')}. Anything else is out of scope (hard rule 6) ` +
      `and requires a specialist engineer.`);
  }
  return prisma.engineeringCalculation.create({
    data: {
      userId, title, discipline, taskDescription, objectType,
      status: 'drafted', disclaimerIncluded: false
    }
  });
}

/**
 * Fix the normative base (hard rule 2). Must be done before calculation.
 * normsApplied: [{ code, title, edition, what_it_governs }]
 */
export async function setNormBase(calculationId, { normSystem = DEFAULT_NORM_SYSTEM, normsApplied = [] }) {
  if (normsApplied.length === 0) {
    throw new Error('Norm base requires at least one norm (hard rule 2). ' +
                    'A calculation without a stated norm is not verifiable.');
  }
  return prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      normSystem,
      normsApplied: JSON.stringify(normsApplied)
    }
  });
}

/**
 * Enumerate load cases (hard rule 3). Must be done before calculation.
 * loadCases: [{ caseName, type, value, unit }]
 */
export async function setLoadCases(calculationId, { loadCases = [], inputData = [], missingData = null }) {
  if (loadCases.length === 0) {
    throw new Error('At least one load case must be enumerated (hard rule 3). ' +
                    'A missed load case is a missed path to failure.');
  }
  const dataComplete = inputData.length > 0 &&
    inputData.every(d => d.certainty === 'known');
  return prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      loadCases: JSON.stringify(loadCases),
      inputData: JSON.stringify(inputData),
      dataComplete,
      missingData
    }
  });
}

/**
 * Record the calculation result. Requires that norm base and load cases were
 * set first. Moves the calculation to `calculated`.
 * assumptions: array of strings (each must be conservative — hard rule 5).
 */
export async function recordCalculationResult(calculationId, {
  method, assumptions = [], resultSummary, resultDetails,
  safetyFactor = null, safetyFactorRequired = null, verdict
}) {
  const calc = await prisma.engineeringCalculation.findUnique({ where: { id: calculationId } });
  if (!calc) throw new Error(`Calculation ${calculationId} not found`);

  // Gate: norm base and load cases must exist (hard rules 2, 3)
  const norms = JSON.parse(calc.normsApplied || '[]');
  const cases = JSON.parse(calc.loadCases || '[]');
  if (norms.length === 0) {
    throw new Error('Cannot record result: norm base not set (hard rule 2). Call setNormBase first.');
  }
  if (cases.length === 0) {
    throw new Error('Cannot record result: load cases not enumerated (hard rule 3). Call setLoadCases first.');
  }

  const safetyFactorOk = (safetyFactor != null && safetyFactorRequired != null)
    ? safetyFactor >= safetyFactorRequired
    : null;

  return prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      method,
      assumptions: JSON.stringify(assumptions),
      resultSummary, resultDetails,
      safetyFactor, safetyFactorRequired, safetyFactorOk,
      verdict,
      status: 'calculated'
    }
  });
}

/**
 * Record the independent verification (hard rules 7, 8). The calculation
 * reaches `self_verified` ONLY when verification agrees and the dimensional
 * check passed. Until then it is not sent to the reviewing engineer.
 */
export async function recordVerification(calculationId, {
  verificationMethod, verificationAgrees, dimensionalCheckOk
}) {
  if (!dimensionalCheckOk) {
    throw new Error('Dimensional check failed (hard rule 8). ' +
                    'Locate and fix the error before proceeding.');
  }
  if (!verificationAgrees) {
    // The verification did its job — it found a discrepancy. The calculation
    // is NOT self-verified; the error must be resolved first.
    await prisma.engineeringCalculation.update({
      where: { id: calculationId },
      data: { verificationMethod, verificationAgrees: false, dimensionalCheckOk: true }
    });
    throw new Error('Independent verification disagrees with the primary result ' +
                    '(hard rule 7). One method is wrong — resolve before self-verification.');
  }
  return prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      verificationMethod,
      verificationAgrees: true,
      dimensionalCheckOk: true,
      status: 'self_verified'
    }
  });
}

/**
 * Finalize a calculation for engineer review: attach the disclaimer (hard
 * rule 1) and move to `sent_for_review`. Requires `self_verified` status —
 * unverified work is never sent to the engineer.
 */
export async function sendForEngineerReview(calculationId) {
  const calc = await prisma.engineeringCalculation.findUnique({ where: { id: calculationId } });
  if (!calc) throw new Error(`Calculation ${calculationId} not found`);
  if (calc.status !== 'self_verified') {
    throw new Error(`Cannot send for review: status is "${calc.status}", not "self_verified". ` +
                    `Independent verification must pass first (hard rule 7).`);
  }

  const updated = await prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      disclaimerIncluded: true,
      status: 'sent_for_review',
      sentForReviewAt: new Date()
    }
  });

  await publishToArchive({
    text: wrapArchiveNote(
      `🔧 *Расчёт подготовлен* — ${calc.title}\n` +
      `Дисциплина: ${disciplineRu(calc.discipline)}\n` +
      `Вердикт (предварительно): ${calc.verdict || 'n/a'}\n` +
      `Передан на проверку дипломированному инженеру.\n` +
      `#engineering #calculation #${calc.discipline}`)
  }).catch(() => {});

  return updated;
}

/**
 * Record the licensed engineer's verdict on a reviewed calculation. This is
 * the verification source — the engineer's review tells the department whether
 * its preparatory work was sound. Creates the verification record that feeds
 * the learning loop.
 */
export async function recordEngineerReview(calculationId, {
  engineerVerdict,        // 'approved' | 'corrected'
  engineerNotes = null,
  errorWasSubstantive = false,
  errorClass = 'none',
  errorDescription = null,
  catchableInternally = null,
  lessonLearned = null
}) {
  if (!['approved', 'corrected'].includes(engineerVerdict)) {
    throw new Error(`engineerVerdict must be 'approved' or 'corrected'.`);
  }
  if (errorClass !== 'none' && !ERROR_CLASSES.includes(errorClass)) {
    throw new Error(`Unknown errorClass "${errorClass}". Valid: ${ERROR_CLASSES.join(', ')}`);
  }

  const calc = await prisma.engineeringCalculation.findUnique({ where: { id: calculationId } });
  if (!calc) throw new Error(`Calculation ${calculationId} not found`);

  const newStatus = engineerVerdict === 'approved' ? 'engineer_approved' : 'engineer_corrected';

  await prisma.engineeringCalculation.update({
    where: { id: calculationId },
    data: {
      engineerVerdict, engineerNotes,
      reviewedAt: new Date(),
      status: newStatus
    }
  });

  // The verification record — the learning-loop input
  const verification = await prisma.engineeringCalculationVerification.create({
    data: {
      userId: calc.userId,
      calculationId,
      engineerFoundError: engineerVerdict === 'corrected',
      errorWasSubstantive,
      errorClass: engineerVerdict === 'corrected' ? errorClass : 'none',
      errorDescription,
      catchableInternally,
      independentMethodAgreed: calc.verificationAgrees,
      lessonLearned
    }
  });

  await publishToArchive({
    text: wrapArchiveNote(
      `${engineerVerdict === 'approved' ? '✅' : '🔁'} *Расчёт проверен инженером* — ${calc.title}\n` +
      `Вердикт инженера: ${engineerVerdict === 'approved' ? 'утверждён' : 'возвращён с правками'}\n` +
      (engineerVerdict === 'corrected' && errorWasSubstantive
        ? `Класс ошибки: ${errorClass}` +
          (catchableInternally ? ' (могла быть поймана внутренней проверкой)' : '') + '\n'
        : '') +
      `#engineering #review #${calc.discipline}`)
  }).catch(() => {});

  return verification;
}

// ─── Norm references ─────────────────────────────────────────────────────────

export async function addNormReference({
  code, title, normSystem, discipline, edition = null, whatItGoverns, userId = OWNER_ID
}) {
  if (!DISCIPLINES.includes(discipline)) {
    throw new Error(`Unknown discipline "${discipline}".`);
  }
  return prisma.normReference.upsert({
    where: { userId_code: { userId, code } },
    update: { title, normSystem, discipline, edition, whatItGoverns, lastCheckedAt: new Date() },
    create: { userId, code, title, normSystem, discipline, edition, whatItGoverns, lastCheckedAt: new Date() }
  });
}

export async function listNormReferences(filter = {}) {
  const { discipline, normSystem, userId = OWNER_ID } = filter;
  const where = { userId };
  if (discipline) where.discipline = discipline;
  if (normSystem) where.normSystem = normSystem;
  return prisma.normReference.findMany({ where, orderBy: { code: 'asc' } });
}

// ─── Design reviews ──────────────────────────────────────────────────────────

/**
 * Record a design review (third-party calc review / sanity check / feasibility).
 * A review is NOT an approval — the disclaimer and that distinction are
 * enforced.
 * findings: [{ severity, finding, recommendation }]
 */
export async function recordDesignReview({
  subject, discipline, reviewType, scope, findings = [],
  verdict, recommendation, calculationId = null, userId = OWNER_ID
}) {
  if (!DISCIPLINES.includes(discipline)) {
    throw new Error(`Unknown discipline "${discipline}" — out of scope (hard rule 6).`);
  }
  const grossErrorsFound = findings.filter(f => f.severity === 'critical').length;

  const review = await prisma.designReview.create({
    data: {
      userId, subject, discipline, reviewType, scope,
      findings: JSON.stringify(findings),
      grossErrorsFound,
      verdict, recommendation,
      disclaimerIncluded: true,  // a review always carries the disclaimer + "not an approval" note
      calculationId
    }
  });

  if (grossErrorsFound > 0) {
    await publishToArchive({
      text: wrapArchiveNote(
        `🔍 *Проверка расчёта — найдены грубые ошибки* — ${subject}\n` +
        `Критических находок: ${grossErrorsFound}\n` +
        `Вердикт: ${verdict}\n` +
        `Это проверка, НЕ утверждение — решает дипломированный инженер.\n` +
        `#engineering #review #gross_error`)
    }).catch(() => {});
  }

  return review;
}

// ─── Monthly / quarterly review ──────────────────────────────────────────────

/**
 * Monthly performance review. Aggregates the month's engineer-reviewed
 * calculations, computes the correction rate and other metrics, clusters
 * error classes, chooses 1-2 improvements.
 */
export async function monthlyPerformanceReview(userId = OWNER_ID) {
  const periodEnd = new Date();
  const periodStart = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);

  const verifications = await prisma.engineeringCalculationVerification.findMany({
    where: { userId, verifiedAt: { gte: periodStart } }
  });
  const n = verifications.length;

  // Engineer-correction rate: share with a substantive error
  const substantiveErrors = verifications.filter(v => v.errorWasSubstantive).length;
  const correctionRate = n ? substantiveErrors / n : null;

  // Independent-method agreement
  const indepJudged = verifications.filter(v => v.independentMethodAgreed != null).length;
  const indepAgreed = verifications.filter(v => v.independentMethodAgreed === true).length;
  const independentAgreementRate = indepJudged ? indepAgreed / indepJudged : null;

  // Missed-load-case rate
  const missedLoadCase = verifications.filter(v => v.errorClass === 'missed_load_case').length;
  const missedLoadCaseRate = n ? missedLoadCase / n : null;

  // Disclaimer compliance (over calculations sent for review this month)
  const sent = await prisma.engineeringCalculation.findMany({
    where: { userId, sentForReviewAt: { gte: periodStart } }
  });
  const disclaimerComplianceRate = sent.length
    ? sent.filter(c => c.disclaimerIncluded).length / sent.length
    : null;

  // Error clustering
  const clusters = {};
  for (const v of verifications) {
    if (v.errorWasSubstantive) {
      clusters[v.errorClass] = (clusters[v.errorClass] || 0) + 1;
    }
  }
  const errorClusters = Object.entries(clusters)
    .map(([errorClass, count]) => ({ errorClass, count }))
    .sort((a, b) => b.count - a.count);

  // Improvements
  const improvements = [];
  const top = errorClusters[0];
  if (top && top.count >= 2) {
    improvements.push(
      `Recurring error class "${top.errorClass}" (${top.count}× this month) — ` +
      `reinforce ${skillForErrorClass(top.errorClass)}.`);
  }
  if (correctionRate != null && correctionRate > CORRECTION_RATE_TARGETS.year1) {
    improvements.push(
      `Engineer-correction rate ${(correctionRate * 100).toFixed(0)}% above the ` +
      `${(CORRECTION_RATE_TARGETS.year1 * 100).toFixed(0)}% Year-1 target — ` +
      `review which checks are missing the errors.`);
  }
  if (improvements.length === 0) {
    improvements.push('Metrics within targets this month — maintain current methodology.');
  }

  const review = await prisma.engineeringMonthlyReview.create({
    data: {
      userId, periodStart, periodEnd,
      calculationsReviewed: n,
      engineerCorrectionRate: correctionRate,
      independentAgreementRate,
      missedLoadCaseRate,
      disclaimerComplianceRate,
      errorClusters: JSON.stringify(errorClusters),
      improvementsChosen: JSON.stringify(improvements)
    }
  });

  await publishToArchive({
    text: wrapArchiveNote(
      `📋 *Инженерный отдел — месячный разбор*\n` +
      `Расчётов проверено инженером: ${n}\n` +
      (correctionRate != null
        ? `Correction rate: ${(correctionRate * 100).toFixed(0)}% (цель Y1 ≤25%)\n` : '') +
      (missedLoadCaseRate != null
        ? `Пропущенных расчётных случаев: ${(missedLoadCaseRate * 100).toFixed(0)}% (цель <10%)\n` : '') +
      (disclaimerComplianceRate != null
        ? `Дисклеймер: ${(disclaimerComplianceRate * 100).toFixed(0)}% (цель 100%)\n` : '') +
      `#engineering #monthly`)
  }).catch(() => {});

  return review;
}

/**
 * Quarterly methodology review. Systematic weaknesses across the quarter,
 * skill updates flagged (or explicit justification of none).
 */
export async function quarterlyMethodologyReview(userId = OWNER_ID) {
  const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);

  const [verifications, monthlyReviews] = await Promise.all([
    prisma.engineeringCalculationVerification.findMany({ where: { userId, verifiedAt: { gte: since } } }),
    prisma.engineeringMonthlyReview.findMany({ where: { userId, periodStart: { gte: since } } })
  ]);

  const clusters = {};
  for (const v of verifications) {
    if (v.errorWasSubstantive) clusters[v.errorClass] = (clusters[v.errorClass] || 0) + 1;
  }

  const weaknesses = [];
  for (const [errorClass, count] of Object.entries(clusters)) {
    if (count >= 3) {
      weaknesses.push(
        `Error class "${errorClass}" appeared ${count}× this quarter — persistent ` +
        `weakness; update ${skillForErrorClass(errorClass)}.`);
    }
  }
  // Catchable-internally errors are the real misses — flag if recurring
  const catchable = verifications.filter(v => v.errorWasSubstantive && v.catchableInternally).length;
  if (catchable >= 3) {
    weaknesses.push(
      `${catchable} substantive errors this quarter were catchable by the department's ` +
      `own checks (verification / dimensional / load-case) — strengthen those checks.`);
  }

  return {
    period: `${since.toISOString().slice(0, 10)} … ${new Date().toISOString().slice(0, 10)}`,
    calculationsReviewed: verifications.length,
    errorClassClusters: clusters,
    systematicWeaknesses: weaknesses,
    skillUpdateRequired: weaknesses.length > 0
      ? weaknesses
      : ['No systematic weakness found this quarter. Justification: no error-class ' +
         'cluster reached 3+, catchable-internally errors below threshold. ' +
         'Methodology unchanged. Note: also run the semi-annual norm review to ' +
         'confirm applied norms are current editions.']
  };
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listCalculations(filter = {}, limit = 20) {
  const { discipline, status, verdict, userId = OWNER_ID } = filter;
  const where = { userId };
  if (discipline) where.discipline = discipline;
  if (status) where.status = status;
  if (verdict) where.verdict = verdict;
  return prisma.engineeringCalculation.findMany({
    where, orderBy: { createdAt: 'desc' }, take: limit
  });
}

export async function getCalculation(calculationId, userId = OWNER_ID) {
  return prisma.engineeringCalculation.findFirst({
    where: { id: calculationId, userId },
    include: { verification: true }
  });
}

/**
 * Department metrics report (/eng-score).
 */
export async function getEngineeringScore(userId = OWNER_ID) {
  const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
  const verifications = await prisma.engineeringCalculationVerification.findMany({
    where: { userId, verifiedAt: { gte: since } }
  });
  const n = verifications.length;
  if (n === 0) {
    return { period: 'last 90 days', calculationsReviewed: 0,
             note: 'No engineer-reviewed calculations yet.' };
  }
  const substantive = verifications.filter(v => v.errorWasSubstantive).length;
  const missedLoadCase = verifications.filter(v => v.errorClass === 'missed_load_case').length;
  const indepJudged = verifications.filter(v => v.independentMethodAgreed != null).length;
  const indepAgreed = verifications.filter(v => v.independentMethodAgreed === true).length;
  return {
    period: 'last 90 days',
    calculationsReviewed: n,
    engineerCorrectionRate: substantive / n,
    correctionRateTargetY1: CORRECTION_RATE_TARGETS.year1,
    missedLoadCaseRate: missedLoadCase / n,
    independentAgreementRate: indepJudged ? indepAgreed / indepJudged : null
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function skillForErrorClass(errorClass) {
  const map = {
    missed_load_case: 'load-case-enumeration',
    wrong_coefficient: 'norm-base-fixation',
    wrong_norm: 'norm-base-fixation',
    dimensional_error: 'independent-verification',
    wrong_assumption: 'calculation-documentation',
    method_error: 'independent-verification'
  };
  return map[errorClass] || 'the relevant skill';
}

function disciplineRu(discipline) {
  const map = {
    structural: 'строительная механика',
    hydraulic: 'гидравлика',
    power_electronics: 'силовая электроника'
  };
  return map[discipline] || discipline;
}

// Archive notes about engineering work also carry a short preliminary marker.
function wrapArchiveNote(text) {
  return text + '\n⚠ Предварительно — финальную ответственность несёт инженер.';
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
  wrapWithDisclaimer,
  createCalculation,
  setNormBase,
  setLoadCases,
  recordCalculationResult,
  recordVerification,
  sendForEngineerReview,
  recordEngineerReview,
  addNormReference,
  listNormReferences,
  recordDesignReview,
  monthlyPerformanceReview,
  quarterlyMethodologyReview,
  listCalculations,
  getCalculation,
  getEngineeringScore
};
