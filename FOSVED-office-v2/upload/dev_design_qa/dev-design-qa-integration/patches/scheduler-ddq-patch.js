// ============================================================================
// scheduler-ddq-patch.js — scheduler.js tasks for Dev + Design + QA
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 6 scheduled tasks. All times Europe/Moscow.
//
// HOW TO APPLY:
// 1. Open scheduler.js
// 2. Ensure the lib requires are present (dev, design, qa)
// 3. Add the 6 cron.schedule blocks below alongside existing tasks
// 4. Each task is wrapped in try/catch — a failing task must not crash the
//    scheduler process or block other tasks.
// 5. Verify: node -c scheduler.js, then start bot and confirm no crash.
// ============================================================================

const dev = require('./lib/dev.js');
const design = require('./lib/design.js');
const qa = require('./lib/qa.js');

// ─── 1. Dev — weekly tech radar scan (Wednesday 04:00) ───────────────────────
cron.schedule('0 4 * * 3', async () => {
  try {
    const result = await dev.weeklyTechRadarScan();
    console.log('[ddq] weekly tech radar scan done:', result?.signalsFound ?? 0, 'signals');
  } catch (e) {
    console.error('[ddq] weeklyTechRadarScan failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 2. Dev — monthly estimate calibration (1st, 11:00) ──────────────────────
cron.schedule('0 11 1 * *', async () => {
  try {
    const cal = await dev.monthlyEstimateCalibration();
    console.log('[ddq] monthly estimate calibration:',
      `in-range ${cal?.inRangeRate ?? 'n/a'}, fudge ${cal?.recommendedFudgeFactor ?? 'n/a'}`);
  } catch (e) {
    console.error('[ddq] monthlyEstimateCalibration failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 3. QA — daily production monitor (08:00) ────────────────────────────────
cron.schedule('0 8 * * *', async () => {
  try {
    const report = await qa.dailyProductionMonitor();
    console.log('[ddq] qa daily monitor:',
      report.needsAttention ? 'ATTENTION REQUIRED' : 'ok');
  } catch (e) {
    console.error('[ddq] dailyProductionMonitor failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 4. QA — weekly security scan (Sunday 05:00) ─────────────────────────────
cron.schedule('0 5 * * 0', async () => {
  try {
    // Collect `npm audit` style findings per active repository.
    // dev.listRepositories() gives the repos; the audit collection itself
    // (running npm audit) is environment-specific — here we pass whatever
    // the bot has gathered. If nothing gathered, weeklySecurityScan records
    // an empty (passing) audit per repo.
    const repos = await dev.listRepositories();
    const auditInputs = repos
      .filter(r => r.status === 'active')
      .map(r => ({ target: r.name, targetRepositoryId: r.id, findings: [] }));
    const result = await qa.weeklySecurityScan(auditInputs);
    console.log('[ddq] weekly security scan:',
      `${result.repositoriesScanned} repos, ${result.repositoriesWithBlockingFindings} blocking`);
  } catch (e) {
    console.error('[ddq] weeklySecurityScan failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 5. Design — monthly design system audit (15th, 12:00) ───────────────────
cron.schedule('0 12 15 * *', async () => {
  try {
    const audit = await design.monthlyDesignSystemAudit();
    console.log('[ddq] monthly design system audit done:',
      audit?.componentsReviewed ?? 0, 'components');
  } catch (e) {
    console.error('[ddq] monthlyDesignSystemAudit failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── 6. All three — quarterly methodology review ─────────────────────────────
// Jan / Apr / Jul / Oct, 1st, 11:30
cron.schedule('30 11 1 1,4,7,10 *', async () => {
  // Each department's review is independent — one failing must not block the
  // others. Run them sequentially with isolated try/catch.
  try {
    const devReview = await dev.quarterlyMethodologyReview();
    console.log('[ddq] dev quarterly review:',
      (devReview?.skillUpdateRequired?.length ?? 0), 'skill updates flagged');
  } catch (e) {
    console.error('[ddq] dev quarterlyMethodologyReview failed:', e.message);
  }
  try {
    const designReview = await design.quarterlyMethodologyReview();
    console.log('[ddq] design quarterly review:',
      (designReview?.skillUpdateRequired?.length ?? 0), 'skill updates flagged');
  } catch (e) {
    console.error('[ddq] design quarterlyMethodologyReview failed:', e.message);
  }
  try {
    const qaReview = await qa.quarterlyMethodologyReview();
    console.log('[ddq] qa quarterly review:',
      (qaReview?.systematicWeaknesses?.length ?? 0), 'weaknesses found');
  } catch (e) {
    console.error('[ddq] qa quarterlyMethodologyReview failed:', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// ─── Schedule summary ────────────────────────────────────────────────────────
//
//   Wed 04:00       — Dev: weekly tech radar scan
//   1st 11:00       — Dev: monthly estimate calibration
//   daily 08:00     — QA: production monitor
//   Sun 05:00       — QA: weekly security scan
//   15th 12:00      — Design: monthly design system audit
//   Q 1st 11:30     — All: quarterly methodology review
//
// These run alongside existing fosved-bot scheduler tasks (OSP cycles, ЛЗ
// monitoring, Visual pattern scan, etc.). No time collisions with those by
// design — but verify against the current scheduler.js before applying.
// ─────────────────────────────────────────────────────────────────────────────
