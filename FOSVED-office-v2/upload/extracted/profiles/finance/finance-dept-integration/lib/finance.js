// lib/finance.js
// Finance department business logic.
//
// Responsibilities:
//   - Save forecasts/calculations to FinancialForecast archive
//   - Publish each result to ARCHIVE_CHANNEL_ID via archive-publisher
//   - Manage invoice lifecycle (states transitions, aging report)
//   - Run per-forecast verification on verificationDate
//   - Run monthly performance review (MAPE calculation)
//   - Run quarterly methodology review
//   - Provide unit economics calculations
//   - Multi-jurisdiction tax calculations
//
// Inputs from bot.js:
//   /finance <text>         -> handleQuery (LLM-routed to right sub-action)
//   /finance-forecast <N>   -> buildCashflowForecast
//   /finance-invoice        -> listInvoices (aging report)
//   /finance-verify <id>    -> verifyForecast
//   /finance-archive [q]    -> searchArchive
//   /finance-score          -> getMetricSnapshot
//   /finance-tax <jx> <amt> -> calculateTax
//   /finance-runway         -> calculateRunway
//   /finance-unit <type>    -> calculateUnitEconomics
//
// Inputs from scheduler.js:
//   runDailyCheck()          -- 8:00 daily
//   runMonthlyReview()       -- 1st of month, 10:00
//   runQuarterlyReview()     -- 1st of quarter, 10:30

const fs = require('fs');
const path = require('path');
const { db } = require('../db');
const { publishToArchive } = require('./archive-publisher');

// ─── KNOWLEDGE LOADERS ───────────────────────────────────────────────

const KNOWLEDGE_ROOT = path.join(__dirname, '..', 'library', 'knowledge', 'finance');

function loadJurisdictionKnowledge(jurisdiction) {
  const valid = ['BY', 'RU', 'EU', 'US'];
  if (!valid.includes(jurisdiction)) {
    throw new Error(`Invalid jurisdiction: ${jurisdiction}. Valid: ${valid.join(', ')}`);
  }
  const filePath = path.join(KNOWLEDGE_ROOT, 'jurisdictions', `${jurisdiction}.md`);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Jurisdiction knowledge missing: ${filePath}`);
  }
  return fs.readFileSync(filePath, 'utf8');
}

function loadBusinessFormKnowledge(businessForm) {
  const valid = ['ooo', 'ip', 'selfemployed'];
  if (!valid.includes(businessForm)) {
    throw new Error(`Invalid business form: ${businessForm}. Valid: ${valid.join(', ')}`);
  }
  const filePath = path.join(KNOWLEDGE_ROOT, 'business-forms', `${businessForm}.md`);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Business form knowledge missing: ${filePath}`);
  }
  return fs.readFileSync(filePath, 'utf8');
}

function loadCompatibilityMatrix() {
  const filePath = path.join(KNOWLEDGE_ROOT, 'compatibility-matrix.md');
  return fs.readFileSync(filePath, 'utf8');
}

function checkCompatibility(jurisdiction, businessForm) {
  // Returns: { valid: true|false, alternative: '...', notes: '...' }
  const incompatible = {
    'BY/selfemployed': {
      alternative: 'ремесленник или ИП',
      notes: 'В BY формы "самозанятый" в чистом виде нет. Ближайшие — ремесленник или ИП.',
    },
  };
  const key = `${jurisdiction}/${businessForm}`;
  if (incompatible[key]) {
    return { valid: false, ...incompatible[key] };
  }
  return { valid: true };
}

// ─── CORE: SAVE RESULT WITH ARCHIVE ──────────────────────────────────

/**
 * Save a Finance result and publish to archive.
 * @param {Object} payload
 *   - shortTitle: string (required, ≤200 chars)
 *   - fullResult: string (required, the full text)
 *   - confidence: 'low' | 'medium' | 'high'
 *   - verificationDate: Date (when to verify against reality)
 *   - jurisdiction: 'BY' | 'RU' | 'EU' | 'US' (required)
 *   - businessForm: 'ooo' | 'ip' | 'selfemployed' (required)
 *   - resultType: 'forecast' | 'tax' | 'unit_economics' | 'invoice' | 'runway' | 'other'
 *   - clientId, projectId: optional links
 *   - amount, currency: optional monetary fields
 */
async function saveResult(payload) {
  // Validate
  if (!payload.shortTitle || !payload.fullResult) {
    throw new Error('finance.saveResult: shortTitle and fullResult required');
  }
  if (!payload.jurisdiction || !payload.businessForm) {
    throw new Error('finance.saveResult: jurisdiction and businessForm required');
  }

  // Check compatibility
  const compat = checkCompatibility(payload.jurisdiction, payload.businessForm);
  if (!compat.valid) {
    console.warn(`[finance] Compatibility note: ${compat.notes}`);
    // Continue anyway — saveResult is generic, callers should resolve compat upstream
  }

  // 1. Save to DB
  const record = await db.financialForecast.create({
    data: {
      shortTitle: payload.shortTitle,
      fullResult: payload.fullResult,
      confidence: payload.confidence || 'medium',
      status: 'published',
      verificationDate: payload.verificationDate || null,
      jurisdiction: payload.jurisdiction,
      businessForm: payload.businessForm,
      resultType: payload.resultType || 'other',
      amount: payload.amount || null,
      currency: payload.currency || null,
      clientId: payload.clientId || null,
      projectId: payload.projectId || null,
      createdAt: new Date(),
    },
  });

  // 2. Publish to Telegram archive
  try {
    const archiveMsg = await publishToArchive({
      department: 'finance',
      type: payload.resultType || 'result',
      title: payload.shortTitle,
      body: payload.fullResult,
      metadata: {
        recordId: record.id,
        confidence: payload.confidence,
        verificationDate: payload.verificationDate,
        jurisdiction: payload.jurisdiction,
        businessForm: payload.businessForm,
      },
    });

    // 3. Save archive reference back
    await db.financialForecast.update({
      where: { id: record.id },
      data: {
        archiveMessageId: archiveMsg.message_id,
        archiveChannelId: archiveMsg.chat_id,
      },
    });

    return { ...record, archiveMessageId: archiveMsg.message_id, archiveChannelId: archiveMsg.chat_id };
  } catch (e) {
    console.error('[finance] archive publication failed:', e.message);
    return record;
  }
}

// ─── VERIFICATION ────────────────────────────────────────────────────

async function verifyForecast(id, verification) {
  const record = await db.financialForecast.findUnique({ where: { id } });
  if (!record) throw new Error(`Forecast #${id} not found`);

  // verification: { outcome: 'verified'|'missed'|'partial', actualValue, notes }
  // Calculate MAPE for cashflow forecasts
  let mape = null;
  if (record.resultType === 'forecast' && verification.actualValue && record.amount) {
    mape = Math.abs((verification.actualValue - record.amount) / record.amount) * 100;
  }

  const v = await db.financialForecastVerification.create({
    data: {
      forecastId: id,
      outcome: verification.outcome,
      actualValue: verification.actualValue || null,
      mape: mape,
      notes: verification.notes || '',
      verifiedAt: new Date(),
    },
  });

  // Update forecast status
  await db.financialForecast.update({
    where: { id },
    data: { status: verification.outcome },
  });

  return { verification: v, mape };
}

// ─── DAILY CHECK ─────────────────────────────────────────────────────

async function runDailyCheck() {
  const alerts = [];

  // 1. Check overdue invoices
  const overdue = await db.invoice.findMany({
    where: {
      status: { in: ['sent', 'due_soon'] },
      dueDate: { lt: new Date() },
    },
    orderBy: { dueDate: 'asc' },
  });

  if (overdue.length > 0) {
    alerts.push(`📋 Overdue invoices: ${overdue.length}\n` +
      overdue.slice(0, 5).map(inv =>
        `  #${inv.id} ${inv.clientName} — ${inv.amount} ${inv.currency} (overdue ${daysOverdue(inv.dueDate)} days)`
      ).join('\n')
    );

    // Auto-transition statuses
    for (const inv of overdue) {
      const days = daysOverdue(inv.dueDate);
      let newStatus = inv.status;
      if (days > 60) newStatus = 'pre-legal';
      else if (days > 14) newStatus = 'escalation';
      else if (days > 0) newStatus = 'overdue';
      if (newStatus !== inv.status) {
        await db.invoice.update({ where: { id: inv.id }, data: { status: newStatus } });
      }
    }
  }

  // 2. Check forecasts needing verification today
  const today = new Date();
  today.setHours(23, 59, 59);
  const todayStart = new Date(today);
  todayStart.setHours(0, 0, 0);
  const dueVerifications = await db.financialForecast.findMany({
    where: {
      status: 'published',
      verificationDate: { gte: todayStart, lte: today },
    },
  });

  if (dueVerifications.length > 0) {
    alerts.push(`📊 Forecasts due verification today: ${dueVerifications.length}\n` +
      dueVerifications.map(f => `  #${f.id} ${f.shortTitle}`).join('\n')
    );
  }

  // 3. Check upcoming tax deadlines (next 7 days)
  // TODO: implement against tax calendar from knowledge

  return { alerts, checked: overdue.length + dueVerifications.length };
}

function daysOverdue(dueDate) {
  return Math.floor((Date.now() - new Date(dueDate)) / (1000 * 60 * 60 * 24));
}

// ─── MONTHLY REVIEW ──────────────────────────────────────────────────

async function runMonthlyReview() {
  const monthAgo = new Date();
  monthAgo.setMonth(monthAgo.getMonth() - 1);

  // 1. Gather verifications from last month
  const verifications = await db.financialForecastVerification.findMany({
    where: { verifiedAt: { gte: monthAgo } },
    include: { forecast: true },
  });

  // 2. Compute MAPE per resultType
  const byType = {};
  for (const v of verifications) {
    if (!v.mape) continue;
    const type = v.forecast.resultType;
    if (!byType[type]) byType[type] = [];
    byType[type].push(v.mape);
  }

  const mapeByType = {};
  for (const [type, values] of Object.entries(byType)) {
    mapeByType[type] = {
      avg: values.reduce((a, b) => a + b, 0) / values.length,
      n: values.length,
    };
  }

  // 3. Cluster errors
  const missed = verifications.filter(v => v.outcome === 'missed');
  const errorPatterns = clusterErrors(missed);

  // 4. Save review
  const review = await db.financeMonthlyReview.create({
    data: {
      periodStart: monthAgo,
      periodEnd: new Date(),
      totalForecasts: verifications.length,
      correctForecasts: verifications.filter(v => v.outcome === 'verified').length,
      avgMape: mapeByType.forecast?.avg || null,
      mapeBreakdown: JSON.stringify(mapeByType),
      errorPatterns: JSON.stringify(errorPatterns),
      improvements: '',
    },
  });

  // 5. Publish
  await publishToArchive({
    department: 'finance',
    type: 'monthly_review',
    title: `Finance — отчёт за ${monthAgo.toLocaleDateString('ru')}`,
    body: formatMonthlyReview(review, mapeByType),
    metadata: { reviewId: review.id },
  });

  return review;
}

function clusterErrors(missedVerifications) {
  // TODO: implement actual clustering by resultType + jurisdiction + magnitude
  const byType = {};
  for (const v of missedVerifications) {
    const key = `${v.forecast?.resultType}/${v.forecast?.jurisdiction}`;
    if (!byType[key]) byType[key] = [];
    byType[key].push({ id: v.forecastId, mape: v.mape, notes: v.notes });
  }
  return byType;
}

function formatMonthlyReview(review, mapeByType) {
  let body = `📊 **Finance — Monthly Review**\n\n`;
  body += `Период: ${review.periodStart.toLocaleDateString('ru')} - ${review.periodEnd.toLocaleDateString('ru')}\n\n`;
  body += `Всего прогнозов: ${review.totalForecasts}\n`;
  body += `Верифицировано как correct: ${review.correctForecasts}\n\n`;
  body += `**MAPE по типам:**\n`;
  for (const [type, data] of Object.entries(mapeByType)) {
    body += `- ${type}: ${data.avg.toFixed(2)}% (n=${data.n})\n`;
  }
  return body;
}

// ─── QUARTERLY ────────────────────────────────────────────────────────

async function runQuarterlyReview() {
  // TODO: aggregate 3 monthly reviews, identify methodology gaps
  return { reviewed: 0 };
}

// ─── HELPER OPERATIONS ──────────────────────────────────────────────

async function searchArchive(filter) {
  return db.financialForecast.findMany({
    where: filter || {},
    orderBy: { createdAt: 'desc' },
    take: 20,
  });
}

async function getMetricSnapshot() {
  const monthAgo = new Date();
  monthAgo.setMonth(monthAgo.getMonth() - 1);

  const verifications = await db.financialForecastVerification.findMany({
    where: {
      verifiedAt: { gte: monthAgo },
      mape: { not: null },
    },
    include: { forecast: true },
  });

  const cashflow = verifications.filter(v => v.forecast?.resultType === 'forecast');
  const avgMape = cashflow.length > 0
    ? cashflow.reduce((sum, v) => sum + v.mape, 0) / cashflow.length
    : null;

  return {
    department: 'finance',
    metric: 'mape-cashflow',
    value: avgMape,
    sampleSize: cashflow.length,
    period: 'last 30 days',
  };
}

async function listInvoices(statusFilter) {
  return db.invoice.findMany({
    where: statusFilter ? { status: statusFilter } : {},
    orderBy: { dueDate: 'asc' },
  });
}

// ─── DEPARTMENT-SPECIFIC METHODS (called from bot.js handlers) ─────

async function buildCashflowForecast(opts) {
  // opts: { period: 30|60|90, jurisdiction, businessForm, openingBalance, knownInflows, knownOutflows }
  // TODO: implement full logic per cashflow-forecasting/SKILL.md
  // For now — stub that creates a structurally valid forecast
  const result = {
    period: opts.period,
    opening: opts.openingBalance || 0,
    weeks: [],
    closing: opts.openingBalance || 0,
    risks: [],
    recommendations: [],
  };
  
  const verificationDate = new Date();
  verificationDate.setDate(verificationDate.getDate() + opts.period);

  return saveResult({
    shortTitle: `Cashflow forecast ${opts.period}d (${opts.businessForm}/${opts.jurisdiction})`,
    fullResult: JSON.stringify(result, null, 2),
    confidence: 'medium',
    verificationDate,
    jurisdiction: opts.jurisdiction,
    businessForm: opts.businessForm,
    resultType: 'forecast',
    amount: result.closing,
    currency: opts.currency || 'BYN',
  });
}

async function calculateTax(opts) {
  // opts: { jurisdiction, businessForm, amount, taxType }
  // TODO: implement multi-jurisdiction tax calculations per tax-compliance-multi-jurisdiction/SKILL.md
  const result = {
    jurisdiction: opts.jurisdiction,
    businessForm: opts.businessForm,
    grossAmount: opts.amount,
    taxType: opts.taxType,
    taxAmount: null,
    netAmount: null,
    note: 'TODO: implement actual calculation logic via tax-compliance skill',
  };

  return saveResult({
    shortTitle: `Tax calculation: ${opts.taxType} ${opts.jurisdiction}`,
    fullResult: JSON.stringify(result, null, 2),
    confidence: 'low',
    jurisdiction: opts.jurisdiction,
    businessForm: opts.businessForm,
    resultType: 'tax',
    amount: opts.amount,
  });
}

async function calculateRunway(opts) {
  // opts: { currentCash, monthlyBurn }
  if (!opts.currentCash || !opts.monthlyBurn) {
    throw new Error('calculateRunway: currentCash and monthlyBurn required');
  }
  const runwayMonths = opts.currentCash / opts.monthlyBurn;
  return {
    runwayMonths: runwayMonths.toFixed(1),
    currentCash: opts.currentCash,
    monthlyBurn: opts.monthlyBurn,
    breakeven: runwayMonths < 6 ? 'CRITICAL' : runwayMonths < 12 ? 'WARNING' : 'OK',
  };
}

async function calculateUnitEconomics(opts) {
  // opts: { type: 'CAC'|'LTV'|'payback', cohort data }
  // TODO: full implementation per unit-economics-calculation/SKILL.md
  return { type: opts.type, note: 'TODO: implement via unit-economics skill' };
}

module.exports = {
  // Knowledge
  loadJurisdictionKnowledge,
  loadBusinessFormKnowledge,
  loadCompatibilityMatrix,
  checkCompatibility,

  // Core lifecycle
  saveResult,
  verifyForecast,
  searchArchive,
  getMetricSnapshot,
  listInvoices,

  // Scheduler entry points
  runDailyCheck,
  runMonthlyReview,
  runQuarterlyReview,

  // Department-specific methods
  buildCashflowForecast,
  calculateTax,
  calculateRunway,
  calculateUnitEconomics,
};
