// patches/scheduler-finance-patch.js
// Finance — scheduler tasks for scheduler.js
//
// INSTRUCTIONS:
// 1. Open scheduler.js
// 2. Locate the main setInterval callback
// 3. Insert the marked blocks inside that callback
// 4. Use existing variables: m (minute), h (hour), dow, now
//
// CRITICAL: never use undefined min/hour/date — only m, h, now.getDate().

const dept = require('./lib/finance');

// ═══════════════════════════════════════════════════════════════════════
// TASK 1: Daily check at 8:00
// Checks: forecasts with verification date due, overdue invoices
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance DAILY ===
//
// Inside scheduler.js setInterval callback, add:
//
//     if (m === 0 && h === 8) {
//       try {
//         const result = await dept.runDailyCheck();
//         if (result.alerts && result.alerts.length > 0) {
//           for (const alert of result.alerts) {
//             await bot.sendMessage(OWNER_ID, alert);
//           }
//         }
//       } catch (e) {
//         console.error('[finance] daily check failed:', e.message);
//       }
//     }
//
// === END finance DAILY ===


// ═══════════════════════════════════════════════════════════════════════
// TASK 2: Monthly review — 1st of month, 10:00
// Aggregates last month's verifications, computes MAPE by forecast type
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance MONTHLY ===
//
// Inside scheduler.js setInterval callback, add:
//
//     if (m === 0 && h === 10 && now.getDate() === 1) {
//       try {
//         const review = await dept.runMonthlyReview();
//         const mapeData = review.mapeByType ? JSON.parse(review.mapeByType) : {};
//         let report = `📊 Finance — Monthly Review ready\n\n`;
//         report += `Period: ${review.periodStart.toLocaleDateString('ru')} - ${review.periodEnd.toLocaleDateString('ru')}\n`;
//         report += `Total verifications: ${review.totalForecasts}\n`;
//         report += `  ✓ Verified: ${review.verifiedCount}\n`;
//         report += `  ⚠ Partial: ${review.partialCount}\n`;
//         report += `  ✗ Missed: ${review.missedCount}\n\n`;
//         report += `MAPE by type:\n`;
//         for (const [type, value] of Object.entries(mapeData)) {
//           report += `  ${type}: ${value.toFixed(2)}%\n`;
//         }
//         report += `\nПодробности в архиве.`;
//         await bot.sendMessage(OWNER_ID, report);
//       } catch (e) {
//         console.error('[finance] monthly review failed:', e.message);
//       }
//     }
//
// === END finance MONTHLY ===


// ═══════════════════════════════════════════════════════════════════════
// TASK 3: Quarterly methodology review — 1st of Jan/Apr/Jul/Oct at 11:00
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance QUARTERLY ===
//
// Inside scheduler.js setInterval callback, add:
//
//     if (m === 0 && h === 11 && now.getDate() === 1 && [0, 3, 6, 9].includes(now.getMonth())) {
//       try {
//         const review = await dept.runQuarterlyMethodologyReview();
//         await bot.sendMessage(
//           OWNER_ID,
//           `📋 Finance — Quarterly methodology review ready.\n\n` +
//           `См. подробности в архиве.`
//         );
//       } catch (e) {
//         console.error('[finance] quarterly review failed:', e.message);
//       }
//     }
//
// === END finance QUARTERLY ===


// ═══════════════════════════════════════════════════════════════════════
// COLLISION CHECK
// ═══════════════════════════════════════════════════════════════════════
//
// Before applying, run:
//   grep -nE "h === [0-9]+" scheduler.js | sort -u
//
// Finance tasks claim:
//   - 8:00 daily (overlap risk with QA daily at 8:00 — check if QA exists in target)
//   - 10:00 on 1st of month (claim this slot)
//   - 11:00 on 1st of quarter (claim this slot)
//
// If QA daily 8:00 already exists, change finance daily to 7:30 (m === 30, h === 7).
