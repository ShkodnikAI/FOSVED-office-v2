// patches/scheduler-legal-patch.js
// Legal — scheduler tasks for scheduler.js
//
// Use only m (minute), h (hour), now.getDate(), [0,3,6,9].includes(now.getMonth()) — никаких undefined.

const dept = require('./lib/legal');

// ═══════════════════════════════════════════════════════════════════════
// TASK 1: Daily check at 9:00
// Verifications due (signed contracts ~90 days ago — verification time)
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal DAILY ===
//
//     if (m === 0 && h === 9) {
//       try {
//         const result = await dept.runDailyCheck();
//         if (result.alerts && result.alerts.length > 0) {
//           for (const alert of result.alerts) {
//             await bot.sendMessage(OWNER_ID, alert);
//           }
//         }
//       } catch (e) {
//         console.error('[legal] daily check failed:', e.message);
//       }
//     }
//
// === END legal DAILY ===
// NOTE: 9:00 уже может быть занят (см. v4.1 transition). При коллизии — 8:30 (m === 30, h === 8).


// ═══════════════════════════════════════════════════════════════════════
// TASK 2: Monthly review — 1st of month, 10:30
// Computes pct-clean-signings
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal MONTHLY ===
//
//     if (m === 30 && h === 10 && now.getDate() === 1) {
//       try {
//         const review = await dept.runMonthlyReview();
//         await bot.sendMessage(OWNER_ID,
//           `📊 Legal — Monthly Review ready\n\n` +
//           `Period: ${review.periodStart.toLocaleDateString('ru')} - ${review.periodEnd.toLocaleDateString('ru')}\n` +
//           `Total: ${review.totalAssessments}, Clean: ${review.cleanSignings}\n` +
//           `% Clean signings: ${review.pctCleanSignings !== null ? review.pctCleanSignings.toFixed(1) + '%' : 'N/A'}\n` +
//           `(Target Y1 ≥ 80%, Y2 ≥ 90%)\n\n` +
//           `См. подробности в архиве.`
//         );
//       } catch (e) {
//         console.error('[legal] monthly review failed:', e.message);
//       }
//     }
//
// === END legal MONTHLY ===


// ═══════════════════════════════════════════════════════════════════════
// TASK 3: Quarterly methodology review — 1st of Jan/Apr/Jul/Oct at 11:30
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal QUARTERLY ===
//
//     if (m === 30 && h === 11 && now.getDate() === 1 && [0, 3, 6, 9].includes(now.getMonth())) {
//       try {
//         const review = await dept.runQuarterlyMethodologyReview();
//         await bot.sendMessage(OWNER_ID,
//           `📋 Legal — Quarterly methodology review ready.\n\nСм. архив.`
//         );
//       } catch (e) {
//         console.error('[legal] quarterly review failed:', e.message);
//       }
//     }
//
// === END legal QUARTERLY ===


// ═══════════════════════════════════════════════════════════════════════
// SCHEDULE SLOTS — Legal takes:
//   - 9:00 daily (or 8:30 if collision)
//   - 10:30 monthly (на 1-е число)
//   - 11:30 quarterly (на 1-е января/апреля/июля/октября)
//
// Verify before applying: grep -nE "h === [0-9]+" scheduler.js | sort -u
// ═══════════════════════════════════════════════════════════════════════
