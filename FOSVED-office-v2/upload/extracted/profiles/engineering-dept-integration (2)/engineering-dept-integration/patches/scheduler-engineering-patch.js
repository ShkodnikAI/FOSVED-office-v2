// ============================================================================
// scheduler-engineering-patch.js — scheduler.js tasks for the Engineering dept
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 3 scheduled tasks. All times Europe/Moscow.
//
// HOW TO APPLY:
// 1. Open scheduler.js
// 2. Ensure the lib/engineering.js require is present
// 3. Add the 3 cron.schedule blocks below
// 4. Each is wrapped in try/catch — a failing task must not crash the
//    scheduler or block other tasks.
// 5. Verify: node -c scheduler.js
// ============================================================================

const engineering = require('./lib/engineering.js');

// ─── 1. Weekly — engineer-correction review (Thursday 10:00) ─────────────────
// Surfaces calculations the engineer returned with corrections in the past
// week — an early signal of error patterns before the monthly aggregation.
cron.schedule('0 10 * * 4', async () => {
  try {
    const corrected = await engineering.listCalculations({ status: 'engineer_corrected' }, 50);
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const recent = corrected.filter(c => c.reviewedAt && new Date(c.reviewedAt).getTime() >= cutoff);
    if (recent.length > 0) {
      console.log('[engineering] calculations corrected by engineer this week:', recent.length);
      // bot surfaces these to the owner — left to bot.js notification logic
    }
  } catch (e) {
    console.error('[engineering] weekly correction review failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 2. Monthly — performance review (1st, 10:30) ────────────────────────────
// Methodology learning loop level 2: aggregate engineer-reviewed calculations,
// compute correction rate and other metrics, cluster error classes.
cron.schedule('30 10 1 * *', async () => {
  try {
    const review = await engineering.monthlyPerformanceReview();
    console.log('[engineering] monthly performance review:',
      `${review.calculationsReviewed} calculations reviewed`);
  } catch (e) {
    console.error('[engineering] monthlyPerformanceReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 3. Quarterly — methodology review (Jan/Apr/Jul/Oct 1st, 11:00) ──────────
// Methodology learning loop level 3: systematic weaknesses, skill updates
// flagged. The quarterly review also reminds to run the semi-annual norm
// review (norms get revised — applied editions must stay current).
cron.schedule('0 11 1 1,4,7,10 *', async () => {
  try {
    const review = await engineering.quarterlyMethodologyReview();
    console.log('[engineering] quarterly methodology review:',
      (review.skillUpdateRequired?.length ?? 0), 'items flagged');
  } catch (e) {
    console.error('[engineering] quarterlyMethodologyReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── Schedule summary ────────────────────────────────────────────────────────
//
//   Thu 10:00       — weekly engineer-correction review
//   1st 10:30       — monthly performance review
//   Q 1st 11:00     — quarterly methodology review
//
// The methodology also specifies a semi-annual NORM review (norms are revised
// over time; applied editions must be confirmed current). When a norm-currency
// check function is built, add a 4th task: cron '0 11 1 1,7 *'. Until then,
// the quarterly review's output explicitly reminds the owner to check norm
// currency. Not a separate task in v1.0.
// ─────────────────────────────────────────────────────────────────────────────
