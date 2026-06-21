// lib/legal.js
// Legal department business logic
//
// Responsibilities:
//   - Save department results to LegalAssessment archive
//   - Publish results to Telegram ARCHIVE_CHANNEL_ID (full contract texts as files)
//   - Run verification (90 days after signing)
//   - Run monthly review (pct-clean-signings)
//   - Compute risk maps, drafts, red flag analyses
//
// Inputs:
//   /legal <запрос>          -> general / route to skill
//   /legal-nda               -> NDA quick template
//   /legal-msa               -> MSA quick template
//   /legal-review <text/file>-> redFlagAnalysis
//   /legal-risk-map <task>   -> riskMapping
//   /legal-verify <id>       -> verifyResult
//   /legal-archive [filter]  -> searchArchive
//   /legal-score             -> getMetricSnapshot (pct-clean-signings)
//   /legal-templates         -> listTemplates

const { db } = require('../db');
const { publishToArchive } = require('./archive-publisher');
const fs = require('fs');
const path = require('path');

// ─── KNOWLEDGE PACKS LOADING ────────────────────────────────────────

const KNOWLEDGE_BASE = path.join(__dirname, '..', 'library', 'knowledge', 'legal');

function loadJurisdiction(jurisdiction) {
  const file = path.join(KNOWLEDGE_BASE, 'jurisdictions', `${jurisdiction}.md`);
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, 'utf8');
}

function loadBusinessForm(form) {
  const file = path.join(KNOWLEDGE_BASE, 'business-forms', `${form}.md`);
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, 'utf8');
}

function loadCompatibilityMatrix() {
  return fs.readFileSync(path.join(KNOWLEDGE_BASE, 'compatibility-matrix.md'), 'utf8');
}

function getContextForRequest({ jurisdiction, businessForm, counterpartyJurisdiction, counterpartyForm }) {
  if (!jurisdiction || !businessForm) {
    return {
      ready: false,
      missing: { jurisdiction: !jurisdiction, businessForm: !businessForm },
    };
  }
  return {
    ready: true,
    ownJurisdictionKnowledge: loadJurisdiction(jurisdiction),
    ownFormKnowledge: loadBusinessForm(businessForm),
    counterpartyJurisdictionKnowledge: counterpartyJurisdiction ? loadJurisdiction(counterpartyJurisdiction) : null,
    counterpartyFormKnowledge: counterpartyForm ? loadBusinessForm(counterpartyForm) : null,
    compatibilityMatrix: loadCompatibilityMatrix(),
    isCrossJurisdictional: counterpartyJurisdiction && counterpartyJurisdiction !== jurisdiction,
    isCrossForm: counterpartyForm && counterpartyForm !== businessForm,
  };
}

// ─── MANDATORY DISCLAIMER ───────────────────────────────────────────

const DISCLAIMER = `

⚠ Этот документ — draft + risk map, не финальный юридический документ. ` +
  `Перед подписанием договора на критичные суммы обязательна проверка лицензированным юристом. ` +
  `Knowledge packs могут устареть — для критичных сделок сверяйтесь с актуальной нормативной базой.`;

function withDisclaimer(text) {
  return text + DISCLAIMER;
}

// ─── CORE: SAVE & ARCHIVE ───────────────────────────────────────────

/**
 * Save a Legal result. For long documents (contracts), publishes as Telegram file.
 */
async function saveResult(payload, bot, ownerId) {
  if (!payload.shortTitle || !payload.fullResult) {
    throw new Error('legal.saveResult: missing required fields');
  }
  if (!payload.jurisdiction || !payload.businessForm) {
    throw new Error('legal.saveResult: jurisdiction and businessForm are required');
  }

  // Add mandatory disclaimer
  const resultWithDisclaimer = withDisclaimer(payload.fullResult);

  // Save to DB
  const record = await db.legalAssessment.create({
    data: {
      shortTitle: payload.shortTitle,
      fullResult: resultWithDisclaimer,
      documentType: payload.documentType || 'analysis',  // NDA | MSA | SLA | TZ | analysis | risk_map | red_flag_review
      confidence: payload.confidence || 'medium',
      status: 'published',
      verificationDate: payload.verificationDate || null,
      jurisdiction: payload.jurisdiction,
      businessForm: payload.businessForm,
      counterpartyJurisdiction: payload.counterpartyJurisdiction || null,
      counterpartyForm: payload.counterpartyForm || null,
      riskLevel: payload.riskLevel || 'medium',
      clientId: payload.clientId || null,
      projectId: payload.projectId || null,
      createdAt: new Date(),
    },
  });

  try {
    // Long documents (contracts) — as file
    const isLongDocument = resultWithDisclaimer.length > 3000 ||
                           ['NDA', 'MSA', 'SLA', 'TZ'].includes(payload.documentType);

    let archiveMsg;
    if (isLongDocument && bot && ownerId) {
      // Save as .md file and send as Document
      const tmpFile = `/tmp/legal_${record.id}.md`;
      fs.writeFileSync(tmpFile, resultWithDisclaimer);

      archiveMsg = await publishToArchive({
        department: 'legal',
        type: payload.documentType || 'document',
        title: payload.shortTitle,
        body: `📄 Document attached as file. Type: ${payload.documentType || 'analysis'}\nJurisdiction: ${payload.jurisdiction}\nRisk level: ${payload.riskLevel || 'medium'}\n\nSee attached .md file.`,
        attachFile: tmpFile,
        metadata: {
          recordId: record.id,
          documentType: payload.documentType,
          jurisdiction: payload.jurisdiction,
        },
      });

      // Clean up tmp file
      fs.unlinkSync(tmpFile);
    } else {
      // Short results — as message
      archiveMsg = await publishToArchive({
        department: 'legal',
        type: payload.documentType || 'analysis',
        title: payload.shortTitle,
        body: resultWithDisclaimer,
        metadata: {
          recordId: record.id,
          documentType: payload.documentType,
          jurisdiction: payload.jurisdiction,
        },
      });
    }

    await db.legalAssessment.update({
      where: { id: record.id },
      data: {
        archiveMessageId: archiveMsg.message_id,
        archiveChannelId: archiveMsg.chat_id,
      },
    });

    return { ...record, archiveMessageId: archiveMsg.message_id };
  } catch (e) {
    console.error('[legal] archive publication failed:', e.message);
    return record;
  }
}

// ─── VERIFICATION ───────────────────────────────────────────────────

/**
 * Verify a past legal work — 90 days after signing.
 * Checks: were there post-signing problems that should have been predicted?
 */
async function verifyResult(id, verification) {
  const record = await db.legalAssessment.findUnique({ where: { id } });
  if (!record) throw new Error(`Record ${id} not found`);

  // Categorize outcome
  // - clean: no rewrites, no disputes
  // - rewrite: post-signing rewrites needed (legal department's miss)
  // - dispute: dispute arose (may or may not be legal's miss)
  const outcome = verification.outcome;  // clean | rewrite | dispute

  const v = await db.legalAssessmentVerification.create({
    data: {
      assessmentId: id,
      outcome,
      rewriteWasPredictable: verification.rewriteWasPredictable || null,
      disputeNature: verification.disputeNature || null,
      notes: verification.notes || '',
      verifiedAt: new Date(),
    },
  });

  await db.legalAssessment.update({
    where: { id },
    data: { status: outcome === 'clean' ? 'verified-clean' : outcome },
  });

  return v;
}

// ─── DAILY CHECK ────────────────────────────────────────────────────

async function runDailyCheck() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today.getTime() + 86400000);

  const alerts = [];

  // Assessments ready for verification
  const dueAssessments = await db.legalAssessment.findMany({
    where: {
      status: 'published',
      verificationDate: { gte: today, lt: tomorrow },
    },
  });
  for (const a of dueAssessments) {
    alerts.push(`📋 Legal assessment #${a.id} (${a.shortTitle}) — verification date наступил. Требуется проверка post-signing статуса.`);
  }

  // Templates approaching expiration (TODO when ContractTemplate model is used)

  return { checked: dueAssessments.length, alerts };
}

// ─── MONTHLY REVIEW ─────────────────────────────────────────────────

async function runMonthlyReview() {
  const monthAgo = new Date();
  monthAgo.setMonth(monthAgo.getMonth() - 1);

  const verifications = await db.legalAssessmentVerification.findMany({
    where: { verifiedAt: { gte: monthAgo } },
    include: { assessment: true },
  });

  const total = verifications.length;
  const clean = verifications.filter(v => v.outcome === 'clean').length;
  const rewrites = verifications.filter(v => v.outcome === 'rewrite').length;
  const disputes = verifications.filter(v => v.outcome === 'dispute').length;
  const predictableRewrites = verifications.filter(v => v.outcome === 'rewrite' && v.rewriteWasPredictable).length;

  const pctClean = total > 0 ? (clean / total) * 100 : null;
  const pctPredictableMissed = total > 0 ? (predictableRewrites / total) * 100 : null;

  const review = await db.legalMonthlyReview.create({
    data: {
      periodStart: monthAgo,
      periodEnd: new Date(),
      totalAssessments: total,
      cleanSignings: clean,
      rewriteCount: rewrites,
      disputeCount: disputes,
      predictableRewritesCount: predictableRewrites,
      pctCleanSignings: pctClean,
      pctPredictableMissed: pctPredictableMissed,
      improvements: '',
    },
  });

  await publishToArchive({
    department: 'legal',
    type: 'monthly_review',
    title: `Legal — отчёт за ${monthAgo.toLocaleDateString('ru')}`,
    body: formatMonthlyReview(review),
    metadata: { reviewId: review.id },
  });

  return review;
}

function formatMonthlyReview(review) {
  return [
    `📊 **Legal — Monthly Review**`,
    ``,
    `Период: ${review.periodStart.toLocaleDateString('ru')} - ${review.periodEnd.toLocaleDateString('ru')}`,
    ``,
    `**Verifications:** ${review.totalAssessments}`,
    `  ✓ Clean signings: ${review.cleanSignings}`,
    `  ⚠ Required rewrites: ${review.rewriteCount}`,
    `  ✗ Disputes: ${review.disputeCount}`,
    ``,
    `**% Clean signings:** ${review.pctCleanSignings !== null ? review.pctCleanSignings.toFixed(1) + '%' : 'N/A'}`,
    `   Target Y1: ≥ 80%`,
    `   Target Y2: ≥ 90%`,
    ``,
    `**% Predictable rewrites (methodology gap):** ${review.pctPredictableMissed !== null ? review.pctPredictableMissed.toFixed(1) + '%' : 'N/A'}`,
    `   (если высокий — обновить anti-patterns в skills)`,
    ``,
    `См. подробности в архиве.`,
  ].join('\n');
}

// ─── QUARTERLY METHODOLOGY REVIEW ───────────────────────────────────

async function runQuarterlyMethodologyReview() {
  // TODO: aggregate 3 months of verifications, identify patterns of misses
  return { reviewed: 0 };
}

// ─── SEARCH ─────────────────────────────────────────────────────────

async function searchArchive(filter) {
  return db.legalAssessment.findMany({
    where: filter || {},
    orderBy: { createdAt: 'desc' },
    take: 20,
  });
}

// ─── METRIC SNAPSHOT ────────────────────────────────────────────────

async function getMetricSnapshot() {
  const monthAgo = new Date();
  monthAgo.setMonth(monthAgo.getMonth() - 1);

  const verifications = await db.legalAssessmentVerification.findMany({
    where: { verifiedAt: { gte: monthAgo } },
  });

  const total = verifications.length;
  const clean = verifications.filter(v => v.outcome === 'clean').length;
  const pctClean = total > 0 ? (clean / total) * 100 : null;

  return {
    department: 'legal',
    metric: 'pct-clean-signings',
    value: pctClean,
    unit: '%',
    sampleSize: total,
    period: 'last 30 days',
    target: { y1: '≥ 80%', y2: '≥ 90%' },
  };
}

// ─── TEMPLATES ──────────────────────────────────────────────────────

async function listTemplates() {
  if (!db.contractTemplate) {
    return [];
  }
  return db.contractTemplate.findMany({
    where: { status: 'active' },
    orderBy: [{ documentType: 'asc' }, { jurisdiction: 'asc' }],
  });
}

// ─── EXPORTS ────────────────────────────────────────────────────────

module.exports = {
  saveResult,
  verifyResult,
  runDailyCheck,
  runMonthlyReview,
  runQuarterlyMethodologyReview,
  searchArchive,
  getMetricSnapshot,
  listTemplates,
  getContextForRequest,
  loadJurisdiction,
  loadBusinessForm,
  loadCompatibilityMatrix,
  withDisclaimer,
  DISCLAIMER,
};
