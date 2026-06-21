// ============================================================================
// scheduler-kk-patch.js — scheduler.js tasks for the Kuznitsa department
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 3 scheduled tasks (METHODOLOGY.md III.5). All times Europe/Moscow.
//
// HOW TO APPLY:
// 1. Open scheduler.js
// 2. Ensure the lib/kk.js require is present
// 3. Add the 3 cron.schedule blocks below
// 4. Each is wrapped in try/catch — a failing task must not crash the
//    scheduler or block other tasks.
// 5. Verify: node -c scheduler.js
// ============================================================================

const kk = require('./lib/kk.js');

// ─── 1. Daily — departments-needing-attention check (07:30) ──────────────────
// METHODOLOGY.md III.5: the Kuznitsa checks departments for fresh monthly
// reviews with recurring errors, and alerts the owner if a department needs
// the Veteran's attention. The per-department metric data is gathered by the
// bot from each department's /score; here the recent sessions are scanned.
cron.schedule('30 7 * * *', async () => {
  try {
    const status = await kk.forgeStatus();
    const needing = status.departmentsNeedingAttention || [];
    if (needing.length > 0) {
      console.log('[kk] daily — departments needing attention:', needing.length);
      // bot surfaces these to the owner — left to bot.js notification logic
    }
  } catch (e) {
    console.error('[kk] daily attention check failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 2. Weekly — Kuznitsa status for the owner (Monday 08:00) ────────────────
// METHODOLOGY.md III.5: weekly overall Kuznitsa status — which departments
// passed through, which are in queue, which are at risk.
cron.schedule('0 8 * * 1', async () => {
  try {
    const status = await kk.forgeStatus();
    console.log('[kk] weekly status:',
      `${status.departmentsRecruited.length} recruited, ` +
      `${status.operationsInProgress.length} in progress, ` +
      `${status.departmentsNeedingAttention.length} need attention`);
    // bot delivers the weekly status to the owner — left to bot.js
  } catch (e) {
    console.error('[kk] weekly status failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 3. Monthly — aggregated review across all departments (1st, 09:00) ──────
// METHODOLOGY.md III.5: monthly aggregated report — polygon results, metric
// trends, retraining priorities. The departmentMetrics array (per-department
// sub-target tracking) is assembled by the bot from each department's monthly
// review; passed in here. If the bot has not gathered it, monthlyReview still
// records the Kuznitsa's own operation metrics.
cron.schedule('0 9 1 * *', async () => {
  try {
    // departmentMetrics: [{ department, belowTarget, consecutiveSubTargetMonths }]
    // The bot assembles this from each department's MonthlyReview records.
    const departmentMetrics = global.__fosvedDepartmentMetrics || [];
    const review = await kk.monthlyReview(departmentMetrics);
    console.log('[kk] monthly review:',
      `${review.operationsTotal} operations, ` +
      `${review.departmentsRecruited} recruited`);
  } catch (e) {
    console.error('[kk] monthlyReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── Schedule summary ────────────────────────────────────────────────────────
//
//   daily 07:30      — departments-needing-attention check
//   Mon 08:00        — weekly Kuznitsa status for the owner
//   1st 09:00        — monthly aggregated review across all departments
//
// The Kuznitsa's quarterly methodology review (METHODOLOGY.md epilogue) is a
// deliberate, owner-involved exercise rather than a silent cron job — it
// reviews and may REPLACE methodology rules (anti-pattern III.9.4: it may not
// ADD them). It is run via kk.quarterlyMethodologyReview() when the owner
// conducts the quarterly review, not on an unattended schedule. Not a cron
// task in v1.0.
// ─────────────────────────────────────────────────────────────────────────────
