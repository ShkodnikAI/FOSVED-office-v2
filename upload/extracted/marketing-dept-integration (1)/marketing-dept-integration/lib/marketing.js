// ============================================================================
// lib/marketing.js — Marketing Department engine
// ============================================================================
//
// Core operations for the Marketing (Продвижение) department:
//   - Market / audience research with data-quality grading
//   - Audience segment definition and validation
//   - Campaign creation with mandatory pre-launch forecast
//   - Campaign verification (forecast vs actual, miss diagnosis)
//   - Monthly performance review (aggregation, error clustering)
//   - Quarterly methodology review
//
// Storage: MarketResearch / AudienceSegment / MarketingCampaign /
//          CampaignVerification / MarketingMonthlyReview in DB.
//          Launched campaigns and significant research auto-published
//          to the Telegram archive.
//
// Two equal client modes: internal (Fosved products) and external (clients).
// They share methodology and archive; external research data must be
// reliability-tagged because it arrives from the client.
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Constants ───────────────────────────────────────────────────────────────

const RESEARCH_TYPES = [
  'market_sizing', 'audience_study', 'competitive', 'channel_analysis', 'trend_scan'
];

const CAMPAIGN_TYPES = ['launch', 'growth', 'retention', 'reactivation', 'brand'];

// Verification targets (from forecast-before-launch / campaign-verification skills)
const CONVERSION_TARGET_TOLERANCE = 0.25;  // actual within ±25% of forecast
const CAC_TARGET_TOLERANCE = 0.30;         // actual within ±30% of forecast
const OVEROPTIMISM_THRESHOLD = 0.50;       // forecast exceeding actual by 50%+ = overoptimistic

// Data-source reliability ordering (from market-research-methods skill)
const RELIABILITY_RANK = { high: 0, medium: 1, low: 2 };

// ─── Market research ─────────────────────────────────────────────────────────

/**
 * Create a MarketResearch record. dataSources is an array of
 *   { source, type: "behavioral|survey|expert|assumption", reliability: "high|medium|low" }
 * overallConfidence is derived from the weakest-but-most-relied-on source unless
 * explicitly provided.
 */
export async function createMarketResearch({
  title, researchType, researchQuestion, productContext = null,
  methodology, dataSources = [], findings, forecasts = [],
  recommendations, overallConfidence = null, userId = OWNER_ID
}) {
  if (!RESEARCH_TYPES.includes(researchType)) {
    throw new Error(`Unknown researchType "${researchType}". Valid: ${RESEARCH_TYPES.join(', ')}`);
  }

  // Derive confidence if not given: a body of work is no more confident than
  // its sources. If any source is "assumption" type, cap at low; else use the
  // best reliability present, downgraded one notch if mixed.
  let confidence = overallConfidence;
  if (!confidence) {
    const hasAssumption = dataSources.some(s => s.type === 'assumption');
    if (hasAssumption || dataSources.length === 0) {
      confidence = 'low';
    } else {
      const reliabilities = dataSources.map(s => s.reliability || 'low');
      const best = reliabilities.sort((a, b) => RELIABILITY_RANK[a] - RELIABILITY_RANK[b])[0];
      const allSame = reliabilities.every(r => r === reliabilities[0]);
      confidence = allSame ? best : downgrade(best);
    }
  }

  const research = await prisma.marketResearch.create({
    data: {
      userId, title, researchType, researchQuestion, productContext,
      methodology,
      dataSources: JSON.stringify(dataSources),
      overallConfidence: confidence,
      findings,
      forecasts: JSON.stringify(forecasts),
      recommendations,
      status: 'drafted',
      // verification date: forecasts checked in ~3 months by default
      verificationDate: forecasts.length
        ? new Date(Date.now() + 90 * 24 * 60 * 60 * 1000)
        : null
    }
  });

  await publishToArchive({
    text: `🔍 *Исследование рынка* — ${title}\n` +
          `Тип: ${researchType} | Достоверность: ${confidence}\n` +
          `${productContext ? `Контекст: ${productContext}\n` : ''}` +
          `Прогнозов: ${forecasts.length}\n#marketing #research`
  }).catch(() => {});

  return research;
}

/**
 * Verify a research's numeric forecasts against reality.
 */
export async function verifyMarketResearch(researchId, { forecastsHeld, verifiedNote }) {
  return prisma.marketResearch.update({
    where: { id: researchId },
    data: {
      status: 'verified',
      forecastsHeld,
      verifiedNote,
      verificationDate: new Date()
    }
  });
}

// ─── Audience segments ───────────────────────────────────────────────────────

/**
 * Create an AudienceSegment. All four required fields must be concrete
 * (hard rule 3) — the function rejects empty/placeholder values.
 */
export async function createAudienceSegment({
  name, description, painPoint, whereToReach, currentAlternative = null,
  estimatedSize = null, sizeBasis = null, researchId = null, userId = OWNER_ID
}) {
  for (const [field, value] of Object.entries({ name, description, painPoint, whereToReach })) {
    if (!value || String(value).trim().length < 3) {
      throw new Error(`Segment field "${field}" must be concrete (hard rule 3). Got: "${value}"`);
    }
  }
  if (estimatedSize != null && !sizeBasis) {
    throw new Error('Segment size requires a stated basis (hard rule 8 — no unbasis\'d numbers).');
  }

  return prisma.audienceSegment.create({
    data: {
      userId, name, description, painPoint, whereToReach, currentAlternative,
      estimatedSize, sizeBasis, researchId,
      status: 'hypothesized'
    }
  });
}

/**
 * Update a segment's validation status after a campaign or test provides
 * evidence (from campaign-verification).
 */
export async function updateSegmentValidation(segmentId, { status, validationMethod, validationNote }) {
  if (!['hypothesized', 'validated', 'disproven'].includes(status)) {
    throw new Error(`Invalid segment status "${status}".`);
  }
  return prisma.audienceSegment.update({
    where: { id: segmentId },
    data: { status, validationMethod, validationNote }
  });
}

// ─── Campaigns ───────────────────────────────────────────────────────────────

/**
 * Create a campaign in `drafted` state. No forecast yet — the forecast is added
 * separately via setCampaignForecast and is mandatory before launch.
 */
export async function createCampaign({
  title, productPromoted, campaignType, segmentId = null, researchId = null,
  positioning, coreMessage, messageVariants = [], channels = [],
  userId = OWNER_ID
}) {
  if (!CAMPAIGN_TYPES.includes(campaignType)) {
    throw new Error(`Unknown campaignType "${campaignType}". Valid: ${CAMPAIGN_TYPES.join(', ')}`);
  }
  return prisma.marketingCampaign.create({
    data: {
      userId, title, productPromoted, campaignType, segmentId, researchId,
      positioning, coreMessage,
      messageVariants: JSON.stringify(messageVariants),
      channels: JSON.stringify(channels),
      status: 'drafted'
    }
  });
}

/**
 * Attach the mandatory pre-launch forecast (hard rule 1). Moves the campaign
 * to `forecasted`. Computes a go/no-go hint from the LTV:CAC check if customer
 * value is supplied.
 */
export async function setCampaignForecast(campaignId, {
  forecastConversionRate, forecastCac, forecastReach, forecastBudget,
  forecastBasis, forecastConfidence, customerLtv = null
}) {
  if (forecastConversionRate == null || forecastCac == null || forecastReach == null) {
    throw new Error('Forecast requires conversion rate, CAC and reach (hard rule 1).');
  }

  let goNoGo = 'go';
  let goNoGoReason = 'No customer LTV supplied — economic check skipped.';
  if (customerLtv != null) {
    const ratio = customerLtv / forecastCac;
    if (ratio < 1) {
      goNoGo = 'no_go';
      goNoGoReason = `LTV:CAC ${ratio.toFixed(1)}:1 — below 1:1, campaign loses money per customer.`;
    } else if (ratio < 2) {
      goNoGo = 'rework';
      goNoGoReason = `LTV:CAC ${ratio.toFixed(1)}:1 — thin; viable but fragile.`;
    } else {
      goNoGo = 'go';
      goNoGoReason = `LTV:CAC ${ratio.toFixed(1)}:1 — healthy.`;
    }
  }

  const campaign = await prisma.marketingCampaign.update({
    where: { id: campaignId },
    data: {
      forecastConversionRate, forecastCac, forecastReach, forecastBudget,
      forecastBasis, forecastConfidence,
      status: 'forecasted'
    }
  });

  return { campaign, goNoGo, goNoGoReason };
}

/**
 * Mark the honest-claims check as passed (hard rule 2). A campaign cannot be
 * launched until claimsVerified is true.
 */
export async function verifyCampaignClaims(campaignId, { claimsNote }) {
  return prisma.marketingCampaign.update({
    where: { id: campaignId },
    data: { claimsVerified: true, claimsNote }
  });
}

/**
 * Launch a campaign. Enforces the two hard gates:
 *   - a forecast must exist (hard rule 1)
 *   - claims must be verified (hard rule 2)
 */
export async function launchCampaign(campaignId) {
  const c = await prisma.marketingCampaign.findUnique({ where: { id: campaignId } });
  if (!c) throw new Error(`Campaign ${campaignId} not found`);
  if (c.forecastConversionRate == null || c.forecastCac == null) {
    throw new Error('Cannot launch: no forecast (hard rule 1). Run setCampaignForecast first.');
  }
  if (!c.claimsVerified) {
    throw new Error('Cannot launch: claims not verified (hard rule 2). Run verifyCampaignClaims first.');
  }

  const campaign = await prisma.marketingCampaign.update({
    where: { id: campaignId },
    data: { status: 'launched', launchedAt: new Date() }
  });

  await publishToArchive({
    text: `🚀 *Кампания запущена* — ${campaign.title}\n` +
          `Продвигаем: ${campaign.productPromoted}\n` +
          `Тип: ${campaign.campaignType}\n` +
          `Прогноз: конверсия ${(campaign.forecastConversionRate * 100).toFixed(1)}%, ` +
          `CAC ${campaign.forecastCac}\n#marketing #campaign #launched`
  }).catch(() => {});

  return campaign;
}

/**
 * Record actual results and move the campaign to `completed`. Verification is
 * a separate step (verifyCampaign).
 */
export async function completeCampaign(campaignId, {
  actualConversionRate, actualCac, actualReach, actualSpend
}) {
  return prisma.marketingCampaign.update({
    where: { id: campaignId },
    data: {
      actualConversionRate, actualCac, actualReach, actualSpend,
      status: 'completed', completedAt: new Date()
    }
  });
}

// ─── Campaign verification ───────────────────────────────────────────────────

/**
 * Verify a completed campaign: compare forecast vs actual, compute accuracy,
 * detect overoptimism, and record the miss diagnosis. Closes the learning loop.
 *
 * missSource / diagnosis / lessonLearned are supplied by the analyst (the
 * campaign-verification skill produces them); this function computes the
 * numeric verdicts and persists everything.
 */
export async function verifyCampaign(campaignId, {
  missSource = null, diagnosis = null, lessonLearned = null,
  segmentRespondedAsPredicted = null
}) {
  const c = await prisma.marketingCampaign.findUnique({ where: { id: campaignId } });
  if (!c) throw new Error(`Campaign ${campaignId} not found`);
  if (c.actualConversionRate == null || c.actualCac == null) {
    throw new Error('Cannot verify: campaign has no actuals. Run completeCampaign first.');
  }

  // Accuracy deltas: |actual - forecast| / forecast
  const conversionAccuracy = relDelta(c.actualConversionRate, c.forecastConversionRate);
  const cacAccuracy = relDelta(c.actualCac, c.forecastCac);
  const reachAccuracy = (c.actualReach != null && c.forecastReach)
    ? relDelta(c.actualReach, c.forecastReach) : null;

  const conversionWithinTarget = conversionAccuracy != null
    ? conversionAccuracy <= CONVERSION_TARGET_TOLERANCE : null;
  const cacWithinTarget = cacAccuracy != null
    ? cacAccuracy <= CAC_TARGET_TOLERANCE : null;

  // Overoptimism: forecast exceeded actual by 50%+ (on conversion — the
  // headline metric). forecast / actual - 1 > 0.5
  let wasOveroptimistic = false;
  if (c.forecastConversionRate && c.actualConversionRate > 0) {
    wasOveroptimistic =
      (c.forecastConversionRate / c.actualConversionRate - 1) > OVEROPTIMISM_THRESHOLD;
  }

  const verification = await prisma.campaignVerification.create({
    data: {
      userId: c.userId,
      campaignId,
      conversionAccuracy, cacAccuracy, reachAccuracy,
      conversionWithinTarget, cacWithinTarget,
      wasOveroptimistic,
      segmentRespondedAsPredicted,
      missSource, diagnosis, lessonLearned
    }
  });

  await prisma.marketingCampaign.update({
    where: { id: campaignId },
    data: { status: 'verified' }
  });

  // If the campaign disproved/confirmed the segment, the caller should also
  // call updateSegmentValidation — surfaced here as a reminder in the result.
  await publishToArchive({
    text: `📊 *Кампания верифицирована* — ${c.title}\n` +
          `Конверсия: прогноз ${pct(c.forecastConversionRate)} → факт ${pct(c.actualConversionRate)}` +
          ` (${conversionWithinTarget ? '✅ в цели' : '⚠️ мимо'})\n` +
          `CAC: прогноз ${c.forecastCac} → факт ${c.actualCac}` +
          ` (${cacWithinTarget ? '✅ в цели' : '⚠️ мимо'})\n` +
          (wasOveroptimistic ? '🔴 Overoptimism — прогноз завышен 50%+\n' : '') +
          (missSource ? `Источник промаха: ${missSource}\n` : '') +
          `#marketing #campaign #verified`
  }).catch(() => {});

  return {
    verification,
    segmentUpdateNeeded: c.segmentId != null,
    segmentId: c.segmentId
  };
}

// ─── Monthly performance review ──────────────────────────────────────────────

/**
 * Monthly performance review (scheduler, 1st of month). Aggregates the month's
 * campaign verifications, computes the department metrics, clusters error
 * sources, and records a MarketingMonthlyReview.
 */
export async function monthlyPerformanceReview(userId = OWNER_ID) {
  const periodEnd = new Date();
  const periodStart = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);

  const verifications = await prisma.campaignVerification.findMany({
    where: { userId, verifiedAt: { gte: periodStart } }
  });

  const n = verifications.length;
  const avg = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;

  const convAccs = verifications.map(v => v.conversionAccuracy).filter(x => x != null);
  const cacAccs = verifications.map(v => v.cacAccuracy).filter(x => x != null);
  const avgConversionAccuracy = avg(convAccs);
  const avgCacAccuracy = avg(cacAccs);

  const overoptimismRate = n ? verifications.filter(v => v.wasOveroptimistic).length / n : null;
  const segmentHits = verifications.filter(v => v.segmentRespondedAsPredicted === true).length;
  const segmentJudged = verifications.filter(v => v.segmentRespondedAsPredicted != null).length;
  const segmentHitRate = segmentJudged ? segmentHits / segmentJudged : null;

  // Cluster miss sources
  const clusters = {};
  for (const v of verifications) {
    const src = v.missSource || 'none';
    clusters[src] = (clusters[src] || 0) + 1;
  }
  const errorClusters = Object.entries(clusters)
    .map(([cluster, count]) => ({ cluster, count }))
    .sort((a, b) => b.count - a.count);

  // Choose 1-2 improvements from the dominant non-"none" cluster
  const improvements = [];
  const topCluster = errorClusters.find(c => c.cluster !== 'none');
  if (topCluster && topCluster.count >= 2) {
    improvements.push(
      `Recurring miss source "${topCluster.cluster}" (${topCluster.count}× this month) — ` +
      `target the matching skill next month.`);
  }
  if (overoptimismRate != null && overoptimismRate > 0.15) {
    improvements.push(
      `Overoptimism rate ${(overoptimismRate * 100).toFixed(0)}% > 15% target — ` +
      `tighten forecast-before-launch: anchor harder on past actuals.`);
  }
  if (improvements.length === 0) {
    improvements.push('Metrics within targets this month — maintain current methodology.');
  }

  const review = await prisma.marketingMonthlyReview.create({
    data: {
      userId, periodStart, periodEnd,
      campaignsVerified: n,
      avgConversionAccuracy, avgCacAccuracy,
      overoptimismRate, segmentHitRate,
      errorClusters: JSON.stringify(errorClusters),
      improvementsChosen: JSON.stringify(improvements)
    }
  });

  await publishToArchive({
    text: `📈 *Marketing — месячный разбор*\n` +
          `Кампаний верифицировано: ${n}\n` +
          (avgConversionAccuracy != null
            ? `Средняя точность прогноза конверсии: ±${(avgConversionAccuracy * 100).toFixed(0)}%\n` : '') +
          (overoptimismRate != null
            ? `Overoptimism rate: ${(overoptimismRate * 100).toFixed(0)}% (цель ≤15%)\n` : '') +
          `Улучшений на след. месяц: ${improvements.length}\n#marketing #monthly`
  }).catch(() => {});

  return review;
}

/**
 * Quarterly methodology review (scheduler, Jan/Apr/Jul/Oct). Looks across the
 * quarter for systematic weaknesses and flags skill updates. The methodology
 * mandates at least one skill change OR an explicit justification of why none
 * is needed.
 */
export async function quarterlyMethodologyReview(userId = OWNER_ID) {
  const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);

  const [verifications, monthlyReviews] = await Promise.all([
    prisma.campaignVerification.findMany({ where: { userId, verifiedAt: { gte: since } } }),
    prisma.marketingMonthlyReview.findMany({ where: { userId, periodStart: { gte: since } } })
  ]);

  // Cluster miss sources across the quarter
  const clusters = {};
  for (const v of verifications) {
    const src = v.missSource || 'none';
    clusters[src] = (clusters[src] || 0) + 1;
  }

  const weaknesses = [];
  for (const [cluster, count] of Object.entries(clusters)) {
    if (cluster !== 'none' && count >= 3) {
      weaknesses.push(
        `Miss source "${cluster}" appeared ${count}× this quarter — persistent weakness, ` +
        `update the relevant skill (e.g. ${skillForMissSource(cluster)}).`);
    }
  }
  const overoptimismMonths = monthlyReviews.filter(
    m => m.overoptimismRate != null && m.overoptimismRate > 0.15).length;
  if (overoptimismMonths >= 2) {
    weaknesses.push(
      `Overoptimism above target in ${overoptimismMonths} month(s) — ` +
      `forecast-before-launch needs strengthening.`);
  }

  return {
    period: `${since.toISOString().slice(0, 10)} … ${new Date().toISOString().slice(0, 10)}`,
    campaignsVerified: verifications.length,
    missSourceClusters: clusters,
    systematicWeaknesses: weaknesses,
    // methodology rule: at least one skill change OR explicit justification
    skillUpdateRequired: weaknesses.length > 0
      ? weaknesses
      : ['No systematic weakness found this quarter. Justification: no miss-source ' +
         'cluster reached 3+, overoptimism within target. Methodology unchanged.']
  };
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listResearch(filter = {}, limit = 20) {
  const { researchType, status, userId = OWNER_ID } = filter;
  const where = { userId };
  if (researchType) where.researchType = researchType;
  if (status) where.status = status;
  return prisma.marketResearch.findMany({ where, orderBy: { createdAt: 'desc' }, take: limit });
}

export async function listSegments(filter = {}, limit = 30) {
  const { status, userId = OWNER_ID } = filter;
  const where = { userId };
  if (status) where.status = status;
  return prisma.audienceSegment.findMany({ where, orderBy: { createdAt: 'desc' }, take: limit });
}

export async function listCampaigns(filter = {}, limit = 20) {
  const { status, campaignType, productPromoted, userId = OWNER_ID } = filter;
  const where = { userId };
  if (status) where.status = status;
  if (campaignType) where.campaignType = campaignType;
  if (productPromoted) where.productPromoted = productPromoted;
  return prisma.marketingCampaign.findMany({ where, orderBy: { createdAt: 'desc' }, take: limit });
}

/**
 * Department metrics report (/marketing-score).
 */
export async function getMarketingScore(userId = OWNER_ID) {
  const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
  const verifications = await prisma.campaignVerification.findMany({
    where: { userId, verifiedAt: { gte: since } }
  });
  const n = verifications.length;
  if (n === 0) {
    return { period: 'last 90 days', campaignsVerified: 0, note: 'No verified campaigns yet.' };
  }
  const avg = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
  return {
    period: 'last 90 days',
    campaignsVerified: n,
    avgConversionAccuracy: avg(verifications.map(v => v.conversionAccuracy).filter(x => x != null)),
    avgCacAccuracy: avg(verifications.map(v => v.cacAccuracy).filter(x => x != null)),
    overoptimismRate: verifications.filter(v => v.wasOveroptimistic).length / n,
    conversionWithinTargetRate:
      verifications.filter(v => v.conversionWithinTarget === true).length / n
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function relDelta(actual, forecast) {
  if (forecast == null || forecast === 0 || actual == null) return null;
  return Math.abs(actual - forecast) / forecast;
}

function downgrade(reliability) {
  if (reliability === 'high') return 'medium';
  if (reliability === 'medium') return 'low';
  return 'low';
}

function pct(x) {
  return x != null ? `${(x * 100).toFixed(1)}%` : 'n/a';
}

function skillForMissSource(missSource) {
  const map = {
    overoptimism: 'forecast-before-launch',
    wrong_segment: 'audience-segmentation',
    wrong_channel: 'channel-strategy',
    wrong_message: 'positioning-and-messaging',
    external_factor: 'market-research-methods'
  };
  return map[missSource] || 'the relevant skill';
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
  createMarketResearch,
  verifyMarketResearch,
  createAudienceSegment,
  updateSegmentValidation,
  createCampaign,
  setCampaignForecast,
  verifyCampaignClaims,
  launchCampaign,
  completeCampaign,
  verifyCampaign,
  monthlyPerformanceReview,
  quarterlyMethodologyReview,
  listResearch,
  listSegments,
  listCampaigns,
  getMarketingScore
};
