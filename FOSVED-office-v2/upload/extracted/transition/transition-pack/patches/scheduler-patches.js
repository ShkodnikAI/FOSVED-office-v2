// PATCH for scheduler.js — Fosved Office v4 self-improvement infrastructure
// Adds: 5-horizon improvement loops + Лаборатория знаний background scanning
//
// Apply via: import these handlers into existing scheduler.js, register cron jobs
// Existing daily/weekly tasks remain; these are additions.

import cron from 'node-cron';
import { prisma } from './lib/prisma.js';
import {
  // ОСП handlers
  triggerAnalysisVerification,
  generateMonthlyReview,
  // ЛЗ handlers
  runLaboratoryScan,
  generateLabDigest,
  reviewInflectionCandidates,
  rescoreDisruptionCandidates,
  // Кузница handlers (new)
  runMonthlyDepartmentReview,
  runQuarterlyMethodologyReview,
  runArsenalReview,
  runParadigmReview,
  // Yana handlers
  generateDailyMorningBriefing,
  generateWeeklyCrossReport,
  generateMonthlyCrossReport,
  // Macro & monitoring
  updateMacroRegime,
  scanCrossAssetDivergences,
  reviewWatchlistIndicators
} from './handlers/index.js';

// =============================================================================
// HORIZON 1 — Per-task improvements (no scheduler; happens in real-time)
// =============================================================================
// Per-task improvements happen during deconstruction protocol via calibration skill
// pre-publish checks. No cron needed.

// =============================================================================
// HORIZON 2 — Monthly performance review (1st of month)
// =============================================================================
// Triggers monthly review for each department, aggregates metrics, identifies
// improvements. If 2+ consecutive failed reviews, escalates to Forge.

cron.schedule('0 9 1 * *', async () => {
  console.log('[scheduler] Monthly review cycle starting');

  try {
    const departments = ['osp', 'lz', 'finance', 'legal', 'dev', 'ops', 'studio', 'product', 'upravlenie', 'kk'];

    for (const dept of departments) {
      try {
        const review = await runMonthlyDepartmentReview(dept);

        // Check if escalation needed
        const recent = await prisma.monthlyReview.findMany({
          where: { department: dept },
          orderBy: { createdAt: 'desc' },
          take: 2
        });

        const consecutiveFailures = recent.filter(r =>
          r.metricTrend === 'deteriorating' ||
          (r.primaryMetric && r.primaryMetric < getDepartmentTarget(dept))
        ).length;

        if (consecutiveFailures >= 2) {
          console.log(`[scheduler] Department ${dept} has ${consecutiveFailures} consecutive failures - escalating to Forge`);
          await triggerForgeDebrief(dept);
        }
      } catch (err) {
        console.error(`[scheduler] Monthly review failed for ${dept}:`, err);
      }
    }
  } catch (err) {
    console.error('[scheduler] Monthly review cycle error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// HORIZON 3 — Quarterly methodology review (1st of Jan/Apr/Jul/Oct)
// =============================================================================

cron.schedule('0 10 1 1,4,7,10 *', async () => {
  console.log('[scheduler] Quarterly methodology review starting');

  try {
    const departments = ['osp', 'lz'];  // intelligence depts get full quarterly review

    for (const dept of departments) {
      try {
        await runQuarterlyMethodologyReview(dept);
      } catch (err) {
        console.error(`[scheduler] Quarterly review failed for ${dept}:`, err);
      }
    }

    // Also re-score all KnowledgeArtifacts on quarterly basis
    await rescoreDisruptionCandidates();
  } catch (err) {
    console.error('[scheduler] Quarterly methodology review error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// HORIZON 4 — Semi-annual arsenal review (1st of Jan and Jul)
// =============================================================================
// Inventories all skills, deprecates stale ones, evaluates new techniques

cron.schedule('0 8 1 1,7 *', async () => {
  console.log('[scheduler] Semi-annual arsenal review starting');

  try {
    const period = `${new Date().getFullYear()}-${new Date().getMonth() === 0 ? 'H1' : 'H2'}`;
    await runArsenalReview(period);
  } catch (err) {
    console.error('[scheduler] Arsenal review error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// HORIZON 5 — Annual paradigm review (Dec 31)
// =============================================================================
// Reviews 6 core principles, department architecture, year debrief
// Requires owner participation — sends notification

cron.schedule('0 9 31 12 *', async () => {
  console.log('[scheduler] Annual paradigm review starting');

  try {
    const year = new Date().getFullYear().toString();
    await runParadigmReview(year);
    // Owner notification sent in handler
  } catch (err) {
    console.error('[scheduler] Paradigm review error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// Лаборатория знаний — Background tech scanning
// =============================================================================

// Every 4 hours: incremental scan of new publications and signals
cron.schedule('0 */4 * * *', async () => {
  try {
    await runLaboratoryScan({ scope: 'incremental' });
  } catch (err) {
    console.error('[scheduler] Lab incremental scan error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Daily 06:00: digest of top tech events for owner
cron.schedule('0 6 * * *', async () => {
  try {
    await generateLabDigest({ period: 'daily' });
  } catch (err) {
    console.error('[scheduler] Lab daily digest error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Weekly Monday 09:00: inflection candidates review
cron.schedule('0 9 * * 1', async () => {
  try {
    await reviewInflectionCandidates();
  } catch (err) {
    console.error('[scheduler] Inflection review error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// ОСП monitoring infrastructure
// =============================================================================

// Daily 18:00: cross-asset divergence scan (after market close US)
cron.schedule('0 18 * * 1-5', async () => {
  try {
    await scanCrossAssetDivergences();
  } catch (err) {
    console.error('[scheduler] Divergence scan error:', err);
  }
}, { timezone: 'America/New_York' });

// Daily 09:00: T-30 watchlist indicators check (for active alerts)
cron.schedule('0 9 * * *', async () => {
  try {
    await reviewWatchlistIndicators({ horizon: 'T-30', alertLevels: ['orange', 'red'] });
  } catch (err) {
    console.error('[scheduler] T-30 watchlist check error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Weekly Monday 09:00: T-60/T-90 watchlist for all scenarios
cron.schedule('0 9 * * 1', async () => {
  try {
    await reviewWatchlistIndicators({ horizons: ['T-60', 'T-90'] });
  } catch (err) {
    console.error('[scheduler] Weekly watchlist check error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Monthly 1st: T-180/T-365 watchlist for all scenarios + macro regime update
cron.schedule('0 10 1 * *', async () => {
  try {
    await reviewWatchlistIndicators({ horizons: ['T-180', 'T-365'] });
    await updateMacroRegime();
  } catch (err) {
    console.error('[scheduler] Monthly watchlist/regime check error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// Verification cycle — triggers /verify on indicator dates
// =============================================================================

// Daily check for analyses with verification dates today
cron.schedule('30 8 * * *', async () => {
  try {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    const dueVerifications = await prisma.analysisVerification.findMany({
      where: {
        expectedDate: {
          gte: today,
          lt: tomorrow
        },
        verifiedAt: null
      }
    });

    for (const verification of dueVerifications) {
      await triggerAnalysisVerification(verification.id);
    }
  } catch (err) {
    console.error('[scheduler] Verification cycle error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Pre-verification monitoring: 7 days before indicator date
cron.schedule('0 9 * * *', async () => {
  try {
    const date = new Date();
    date.setDate(date.getDate() + 7);
    date.setHours(0, 0, 0, 0);
    const nextDay = new Date(date);
    nextDay.setDate(nextDay.getDate() + 1);

    const upcoming = await prisma.analysisVerification.findMany({
      where: {
        expectedDate: { gte: date, lt: nextDay },
        verifiedAt: null
      },
      include: {} // would normally include analysis
    });

    if (upcoming.length > 0) {
      console.log(`[scheduler] ${upcoming.length} verifications coming up in 7 days - pre-monitoring`);
      // pre-verification monitoring logic
    }
  } catch (err) {
    console.error('[scheduler] Pre-verification check error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// Yana cross-departmental reports
// =============================================================================

// Daily 07:30: morning briefing
cron.schedule('30 7 * * *', async () => {
  try {
    await generateDailyMorningBriefing();
  } catch (err) {
    console.error('[scheduler] Morning briefing error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Weekly Sunday 18:00: weekly summary
cron.schedule('0 18 * * 0', async () => {
  try {
    await generateWeeklyCrossReport();
  } catch (err) {
    console.error('[scheduler] Weekly cross report error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// Monthly 28th 18:00: monthly cross report (preview to month-end)
cron.schedule('0 18 28 * *', async () => {
  try {
    await generateMonthlyCrossReport();
  } catch (err) {
    console.error('[scheduler] Monthly cross report error:', err);
  }
}, { timezone: 'Europe/Minsk' });

// =============================================================================
// Helper functions
// =============================================================================

function getDepartmentTarget(dept) {
  const targets = {
    'osp': 0.20,        // Brier score - lower is better, target by year 2
    'lz': 0.65,         // disruption_accuracy - higher is better
    'upravlenie': 0.85, // routing_accuracy - higher is better
    'finance': 0.95,    // accuracy
    'legal': 0.95,
    'dev': 0.85,
    'ops': 0.95,
    'studio': 0.80,
    'product': 0.75,
    'kk': 0.70          // pass_rate
  };
  return targets[dept] || 0.75;
}

async function triggerForgeDebrief(department) {
  // Creates a Forge training session of type 'debrief'
  await prisma.trainingSession.create({
    data: {
      type: 'debrief',
      targetDept: department,
      status: 'in_progress',
      checklistResults: JSON.stringify({
        trigger: '2_consecutive_monthly_failures',
        scheduledAt: new Date().toISOString()
      })
    }
  });

  // Notify owner via Yana
  // (notification logic uses existing telegram interface)
  console.log(`[scheduler] Forge debrief queued for ${department}`);
}

console.log('[scheduler] Fosved Office v4 schedulers registered');
