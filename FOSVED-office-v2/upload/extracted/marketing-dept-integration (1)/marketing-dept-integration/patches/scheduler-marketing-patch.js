// ============================================================================
// scheduler-marketing-patch.js — scheduler.js tasks for the Marketing dept
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 3 scheduled tasks. All times Europe/Moscow.
//
// HOW TO APPLY:
// 1. Open scheduler.js
// 2. Ensure the lib/marketing.js require is present
// 3. Add the 3 cron.schedule blocks below alongside existing tasks
// 4. Each task is wrapped in try/catch — a failing task must not crash the
//    scheduler or block other tasks.
// 5. Verify: node -c scheduler.js
// ============================================================================

const marketing = require('./lib/marketing.js');

// ─── 1. Daily — campaign-verification due check (09:00) ──────────────────────
// Surfaces campaigns whose verification date has arrived. The methodology's
// learning loop level 1 (per-task verification) depends on this nudge.
cron.schedule('0 9 * * *', async () => {
  try {
    // Campaigns completed but not yet verified, completed long enough ago for
    // actuals to have settled (~2 weeks).
    const cutoff = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000);
    const completed = await marketing.listCampaigns({ status: 'completed' }, 50);
    const due = completed.filter(c => c.completedAt && new Date(c.completedAt) <= cutoff);
    if (due.length > 0) {
      console.log('[marketing] campaigns due for verification:', due.length);
      // bot surfaces these to the owner — left to bot.js notification logic
    }
  } catch (e) {
    console.error('[marketing] daily verification-due check failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 2. Monthly — performance review (1st, 09:30) ────────────────────────────
// Methodology learning loop level 2: aggregate the month's verifications,
// compute metrics, cluster errors, choose 1-2 improvements.
cron.schedule('30 9 1 * *', async () => {
  try {
    const review = await marketing.monthlyPerformanceReview();
    console.log('[marketing] monthly performance review:',
      `${review.campaignsVerified} campaigns verified`);
  } catch (e) {
    console.error('[marketing] monthlyPerformanceReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 3. Quarterly — methodology review (Jan/Apr/Jul/Oct 1st, 10:00) ──────────
// Methodology learning loop level 3: systematic weaknesses across the quarter,
// skill updates flagged (or explicit justification of none).
cron.schedule('0 10 1 1,4,7,10 *', async () => {
  try {
    const review = await marketing.quarterlyMethodologyReview();
    console.log('[marketing] quarterly methodology review:',
      (review.skillUpdateRequired?.length ?? 0), 'items flagged');
  } catch (e) {
    console.error('[marketing] quarterlyMethodologyReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── Schedule summary ────────────────────────────────────────────────────────
//
//   daily 09:00      — verification-due check (campaigns ready to verify)
//   1st 09:30        — monthly performance review
//   Q 1st 10:00      — quarterly methodology review
//
// These run alongside existing fosved-bot scheduler tasks. The methodology
// also mentions an optional semi-annual channel review — that can be added
// later as a 4th task (cron '0 10 1 1,7 *') calling a channel-review function
// if one is built; not included in v1.0.
// ─────────────────────────────────────────────────────────────────────────────
