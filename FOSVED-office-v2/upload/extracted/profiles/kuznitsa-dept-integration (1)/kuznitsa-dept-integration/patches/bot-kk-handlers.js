// ============================================================================
// bot-kk-handlers.js — bot.js command handlers for the Kuznitsa department
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 7 commands (METHODOLOGY.md III.3).
//
// HOW TO APPLY:
// 1. Open bot.js
// 2. Add the require for lib/kk.js with the other lib requires
// 3. Add each handler in the command-handler section, matching bot.js style.
//    Use anchored regexes.
// 4. Keep the OWNER-only guard bot.js already applies.
// 5. Verify: node -c bot.js
//
// NOTE: /recalibrate-dept is the only command that initiates a heavy,
// owner-gated operation. The handler makes the owner-approval requirement
// explicit (Kuznitsa hard rule 8).
// ============================================================================

const kk = require('./lib/kk.js');

function parseArgs(text) {
  const parts = text.trim().split(/\s+/);
  parts.shift();
  return { args: parts, rest: parts.join(' ') };
}
function clip(s) { return String(s).slice(0, 4000); }

// ─── /recruit <отдел> ────────────────────────────────────────────────────────
async function handleRecruit(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /recruit <название отдела> — создать новый отдел с нуля');

  const session = await kk.startRecruit({
    targetDepartment: rest.slice(0, 60),
    targetDescription: rest
  });

  const stages = kk.CHECKLIST_STAGES.map(s => `${s.stage}. ${s.name}`).join('\n');
  await bot.sendMessage(msg.chat.id, clip(
    `🏗 *Кузница — создание отдела "${rest}"*\n` +
    `TrainingSession #${session.id} открыта.\n\n` +
    `Ветеран проводит отдел через 10 этапов чек-листа (METHODOLOGY.md I.4):\n` +
    `${stages}\n\n` +
    `Отдел НЕ будет выпущен, пока:\n` +
    `• все 10 этапов не пройдены (жёсткое правило 1)\n` +
    `• полигон не пройден с pass-rate ≥ 70% (жёсткое правило 2)\n` +
    `• не назначен явный психотип (правило 4)\n\n` +
    `Прогресс — через updateChecklistStage / recordPolygonRun / completeRecruit.`
  ), { parse_mode: 'Markdown' });
}

// ─── /train <специалист> ─────────────────────────────────────────────────────
async function handleTrain(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /train <отдел/специалист> — собрать обучающий курс');

  const session = await kk.recordTraining({
    targetDepartment: rest.slice(0, 60),
    targetDescription: rest
  });
  await bot.sendMessage(msg.chat.id, clip(
    `📚 *Кузница — обучающая программа для "${rest}"*\n` +
    `TrainingSession #${session.id} открыта.\n` +
    `По скиллу training-program-design Ветеран собирает курс: фундамент → ` +
    `доменные знания → прецеденты (для существующего отдела — его собственный ` +
    `архив) → соседние отделы → методология. Курс адаптируется под психотип.`
  ), { parse_mode: 'Markdown' });
}

// ─── /polygon <специалист> ───────────────────────────────────────────────────
async function handlePolygon(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /polygon <отдел> — прогнать отдел через тренировочные задачи');
  await bot.sendMessage(msg.chat.id, clip(
    `🎯 *Кузница — полигон для "${rest}"*\n` +
    `По скиллу polygon-test-design: 5-10 задач с известными исходами — ` +
    `типовые, edge-кейсы, провокационные (тестируют жёсткие правила).\n` +
    `Отдел прогоняется, считается pass-rate. Результат через recordPolygonRun.\n` +
    `Порог выпуска — 70%. Ниже порога: систематические ошибки идут в Tier 1 ` +
    `скиллы отдела, полигон перезапускается.`
  ), { parse_mode: 'Markdown' });
}

// ─── /debrief <отдел> ────────────────────────────────────────────────────────
async function handleDebrief(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /debrief <отдел> — структурный разбор ошибок отдела');
  await bot.sendMessage(msg.chat.id, clip(
    `🔬 *Кузница — разбор отдела "${rest}"*\n` +
    `По скиллу debrief-protocol: разбор СТРУКТУРНЫЙ, не обвинительный ` +
    `(жёсткое правило 6).\n` +
    `Кластеризация ошибок → «почему систематически» → природа ошибки ` +
    `(обучение / психотип) → план улучшений (1-2 конкретных изменения).\n` +
    `Триггер Кузницы: два monthly review подряд ниже цели (правило 7 — ` +
    `один плохой месяц это шум). Результат через recordDebrief.`
  ), { parse_mode: 'Markdown' });
}

// ─── /assess <специалист> ────────────────────────────────────────────────────
async function handleAssess(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /assess <отдел> — оценить психотип и его соответствие функции');

  const session = await kk.recordAssessment({ targetDepartment: rest.slice(0, 60) });
  await bot.sendMessage(msg.chat.id, clip(
    `🧭 *Кузница — оценка психотипа "${rest}"*\n` +
    `${session.psychotypeRationale || ''}\n\n` +
    `По скиллу psychotype-assessment: различает ошибку ПРИРОДЫ (психотип ` +
    `не подходит — не лечится обучением, нужна recalibration) и ошибку ` +
    `ОБУЧЕНИЯ (психотип верен, не хватает скилла — лечится).`
  ), { parse_mode: 'Markdown' });
}

// ─── /recalibrate-dept <отдел> ───────────────────────────────────────────────
async function handleRecalibrateDept(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /recalibrate-dept <отдел> — полная переподготовка отдела');

  const session = await kk.startRecalibration({ targetDepartment: rest.slice(0, 60) });
  await bot.sendMessage(msg.chat.id, clip(
    `🔧 *Кузница — переподготовка отдела "${rest}"*\n` +
    `TrainingSession #${session.id} открыта — статус: ОЖИДАЕТ ОДОБРЕНИЯ ВЛАДЕЛЬЦА.\n\n` +
    `⚠️ Recalibration — тяжёлая операция (переоценка психотипа, переписывание ` +
    `Tier 1 скиллов, новый полигон). По жёсткому правилу 8 она НЕ начнётся без ` +
    `явного одобрения владельца (anti-pattern III.9.3 — игнорирование владельца).\n\n` +
    `Ветеран представляет обоснование: почему обычная итерация через monthly ` +
    `reviews не справляется. Одобрение фиксируется через approveRecalibration.\n` +
    `Применяется редко — большинство проблем решается /debrief, не recalibration.`
  ), { parse_mode: 'Markdown' });
}

// ─── /forge-status ───────────────────────────────────────────────────────────
async function handleForgeStatus(msg, bot) {
  const status = await kk.forgeStatus();

  let out = `🏭 *Статус Кузницы кадров*\n\n`;

  out += `*Отделы, прошедшие через Кузницу:*\n`;
  out += status.departmentsRecruited.length
    ? status.departmentsRecruited.map(d => `• ${d}`).join('\n') + '\n'
    : '—\n';

  out += `\n*Последние полигоны:*\n`;
  out += status.recentPolygons.length
    ? status.recentPolygons.map(p =>
        `• ${p.department}: ${(p.passRate * 100).toFixed(0)}% ${p.passed ? '✅' : '⚠️'}`).join('\n') + '\n'
    : '—\n';

  if (status.operationsInProgress.length) {
    out += `\n*Операции в работе:*\n`;
    out += status.operationsInProgress.map(o =>
      `• #${o.id} ${o.type} — ${o.department}`).join('\n') + '\n';
  }

  out += `\n*Отделы, требующие внимания:*\n`;
  out += status.departmentsNeedingAttention.length
    ? status.departmentsNeedingAttention.map(d =>
        `• ${d.department} (${d.consecutiveSubTargetMonths} мес. ниже цели) → ${d.recommendedAction}`).join('\n')
    : '— все отделы в норме';

  await bot.sendMessage(msg.chat.id, clip(out), { parse_mode: 'Markdown' });
}

// ============================================================================
// REGISTRATION
// ============================================================================
//
// Register in bot.js. Anchored regexes:
//
//   bot.onText(/^\/recruit\b/,          msg => guard(msg) && handleRecruit(msg, bot));
//   bot.onText(/^\/train\b/,            msg => guard(msg) && handleTrain(msg, bot));
//   bot.onText(/^\/polygon\b/,          msg => guard(msg) && handlePolygon(msg, bot));
//   bot.onText(/^\/debrief\b/,          msg => guard(msg) && handleDebrief(msg, bot));
//   bot.onText(/^\/assess\b/,           msg => guard(msg) && handleAssess(msg, bot));
//   bot.onText(/^\/recalibrate-dept\b/, msg => guard(msg) && handleRecalibrateDept(msg, bot));
//   bot.onText(/^\/forge-status\b/,     msg => guard(msg) && handleForgeStatus(msg, bot));
//
// No command-prefix collisions among these — but keep the \b anchors anyway.

module.exports = {
  handleRecruit,
  handleTrain,
  handlePolygon,
  handleDebrief,
  handleAssess,
  handleRecalibrateDept,
  handleForgeStatus
};
