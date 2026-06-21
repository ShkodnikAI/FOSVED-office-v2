// ============================================================================
// bot-engineering-handlers.js — bot.js command handlers for the Engineering dept
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 8 commands.
//
// HOW TO APPLY:
// 1. Open bot.js
// 2. Add the require for lib/engineering.js with the other lib requires
// 3. Add each handler in the command-handler section, matching bot.js style.
//    Use anchored regexes so /calc-norms etc. are not captured by /calc.
// 4. Keep the OWNER-only guard bot.js already applies.
// 5. Verify: node -c bot.js
//
// CRITICAL: every engineering output the bot sends to the owner carries the
// preliminary-work disclaimer. The handlers below already include it. Do not
// strip it — the department is a project ASSISTANT, not the engineer of record.
// ============================================================================

const engineering = require('./lib/engineering.js');

function parseArgs(text) {
  const parts = text.trim().split(/\s+/);
  parts.shift();
  return { args: parts, rest: parts.join(' ') };
}
function clip(s) { return String(s).slice(0, 4000); }

const DISCIPLINE_ALIASES = {
  'строймеханика': 'structural', 'строительная': 'structural', 'конструкция': 'structural',
  'structural': 'structural', 'кровля': 'structural', 'теплица': 'structural',
  'гидравлика': 'hydraulic', 'гидро': 'hydraulic', 'подъёмник': 'hydraulic',
  'подъемник': 'hydraulic', 'hydraulic': 'hydraulic',
  'электроника': 'power_electronics', 'инвертор': 'power_electronics',
  'коммутатор': 'power_electronics', 'power': 'power_electronics'
};

// ─── /calc <дисциплина> <задача> ─────────────────────────────────────────────
async function handleCalc(msg, bot) {
  const { args, rest } = parseArgs(msg.text);
  if (!rest) {
    // No arg → list calculations
    const calcs = await engineering.listCalculations({}, 15);
    if (!calcs.length) return bot.sendMessage(msg.chat.id,
      'Расчётов пока нет.\nИспользование: /calc <строймеханика|гидравлика|электроника> <задача>');
    return bot.sendMessage(msg.chat.id, clip(
      `🔧 *Инженерные расчёты* (${calcs.length}):\n` +
      calcs.map(c => `#${c.id} [${c.status}] ${c.title}`).join('\n')
    ), { parse_mode: 'Markdown' });
  }

  const discipline = DISCIPLINE_ALIASES[args[0]?.toLowerCase()];
  if (!discipline) {
    return bot.sendMessage(msg.chat.id, clip(
      'Укажи дисциплину первым словом: строймеханика / гидравлика / электроника.\n' +
      'Отдел работает только в этих трёх дисциплинах. Другое — вне scope ' +
      '(жёсткое правило 6), требует профильного инженера.'
    ));
  }
  const taskDescription = args.slice(1).join(' ');
  const calc = await engineering.createCalculation({
    title: taskDescription.slice(0, 80),
    discipline,
    taskDescription
  });

  await bot.sendMessage(msg.chat.id, clip(
    `🔧 *Расчёт #${calc.id}* создан — ${disciplineLabel(discipline)}\n` +
    `${calc.title}\n\n` +
    `⚠️ Отдел — *проектный ассистент*. Результат будет предварительным и ` +
    `потребует проверки дипломированным инженером.\n\n` +
    `Обязательные шаги перед расчётом:\n` +
    `1. /calc-norms ${calc.id} <нормы> — зафиксировать нормативную базу (правило 2)\n` +
    `2. /calc-loadcases ${calc.id} — перечислить расчётные случаи (правило 3)\n` +
    `Затем расчёт → /calc-verify ${calc.id} → /calc-review ${calc.id}`
  ), { parse_mode: 'Markdown' });
}

// ─── /calc-norms <calc_id> <нормы> ───────────────────────────────────────────
async function handleCalcNorms(msg, bot) {
  const { args } = parseArgs(msg.text);
  const calcId = parseInt(args[0], 10);
  if (!calcId) return bot.sendMessage(msg.chat.id,
    'Использование: /calc-norms <calc_id> <нормы, например: СП 20.13330, СП 16.13330>');
  await bot.sendMessage(msg.chat.id, clip(
    `📏 Фиксация нормативной базы для расчёта #${calcId}\n` +
    `Специалист по скиллу norm-base-fixation фиксирует: систему норм ` +
    `(РФ по умолчанию / Eurocode / IEC), конкретные документы с редакциями, ` +
    `что каждый регулирует. Через setNormBase.\n` +
    `Без нормативной базы расчёт не двинется дальше (жёсткое правило 2).`
  ));
}

// ─── /calc-loadcases <calc_id> ───────────────────────────────────────────────
async function handleCalcLoadcases(msg, bot) {
  const { args } = parseArgs(msg.text);
  const calcId = parseInt(args[0], 10);
  if (!calcId) return bot.sendMessage(msg.chat.id,
    'Использование: /calc-loadcases <calc_id>');
  await bot.sendMessage(msg.chat.id, clip(
    `📐 Перечень расчётных случаев для расчёта #${calcId}\n` +
    `Специалист по скиллу load-case-enumeration перечисляет ВСЕ нагрузки и ` +
    `комбинации: постоянные, снег (включая снеговые мешки), ветер (включая ` +
    `отрыв/подсос), эксплуатационные, аварийные. Через setLoadCases.\n` +
    `Пропущенный расчётный случай — пропущенный путь к отказу (правило 3).`
  ));
}

// ─── /calc-verify <calc_id> ──────────────────────────────────────────────────
async function handleCalcVerify(msg, bot) {
  const { args } = parseArgs(msg.text);
  const calcId = parseInt(args[0], 10);
  if (!calcId) return bot.sendMessage(msg.chat.id,
    'Использование: /calc-verify <calc_id>');
  await bot.sendMessage(msg.chat.id, clip(
    `🔎 Независимая верификация расчёта #${calcId}\n` +
    `По скиллу independent-verification: проверка размерностей (обязательно), ` +
    `оценка порядка величины, перерасчёт независимым методом. Через recordVerification.\n` +
    `Расчёт получит статус self_verified только если проверки сходятся ` +
    `(правила 7, 8). Несошедшаяся проверка = найдена ошибка, расчёт не передаётся ` +
    `инженеру до её устранения.`
  ));
}

// ─── /calc-review <calc_id> ──────────────────────────────────────────────────
async function handleCalcReview(msg, bot) {
  const { args } = parseArgs(msg.text);
  const calcId = parseInt(args[0], 10);
  if (!calcId) return bot.sendMessage(msg.chat.id,
    'Использование: /calc-review <calc_id>');

  const calc = await engineering.getCalculation(calcId);
  if (!calc) return bot.sendMessage(msg.chat.id, `Расчёт #${calcId} не найден`);

  if (calc.status === 'self_verified') {
    // Ready to send for engineer review
    try {
      await engineering.sendForEngineerReview(calcId);
      return bot.sendMessage(msg.chat.id, clip(
        `📨 Расчёт #${calcId} оформлен и передан на проверку *дипломированному инженеру*.\n` +
        `Дисклеймер приложен. Когда инженер вернёт вердикт — зафиксируй его ` +
        `повторно через /calc-review ${calcId} (бот соберёт вердикт инженера ` +
        `через recordEngineerReview).`
      ), { parse_mode: 'Markdown' });
    } catch (e) {
      return bot.sendMessage(msg.chat.id, `Не удалось передать на проверку: ${e.message}`);
    }
  }

  if (calc.status === 'sent_for_review') {
    return bot.sendMessage(msg.chat.id, clip(
      `📨 Расчёт #${calcId} уже передан инженеру.\n` +
      `Здесь фиксируется вердикт инженера (утверждён / возвращён с правками) ` +
      `и, если была ошибка — её класс. Через recordEngineerReview. Это вход в ` +
      `цикл обучения отдела.`
    ));
  }

  return bot.sendMessage(msg.chat.id, clip(
    `Расчёт #${calcId} в статусе "${calc.status}".\n` +
    `Перед передачей инженеру он должен пройти: нормы → расчётные случаи → ` +
    `расчёт → независимую верификацию (статус self_verified).`
  ));
}

// ─── /calc-show <id> ─────────────────────────────────────────────────────────
async function handleCalcShow(msg, bot) {
  const { args } = parseArgs(msg.text);
  const calcId = parseInt(args[0], 10);
  if (!calcId) return bot.sendMessage(msg.chat.id, 'Использование: /calc-show <id>');
  const calc = await engineering.getCalculation(calcId);
  if (!calc) return bot.sendMessage(msg.chat.id, `Расчёт #${calcId} не найден`);

  const norms = JSON.parse(calc.normsApplied || '[]');
  const cases = JSON.parse(calc.loadCases || '[]');
  await bot.sendMessage(msg.chat.id, clip(
    `🔧 *Расчёт #${calc.id}* — ${calc.status}\n` +
    `${calc.title}\n` +
    `Дисциплина: ${disciplineLabel(calc.discipline)}\n` +
    `Нормы: ${norms.length ? norms.map(n => n.code).join(', ') : 'не зафиксированы'}\n` +
    `Расчётных случаев: ${cases.length}\n` +
    `${calc.verdict ? `Вердикт (предв.): ${calc.verdict}\n` : ''}` +
    `${calc.safetyFactor != null ? `Запас: ${calc.safetyFactor} (треб. ${calc.safetyFactorRequired ?? 'n/a'})\n` : ''}` +
    `Дисклеймер приложен: ${calc.disclaimerIncluded ? 'да' : 'нет'}\n` +
    `${calc.engineerVerdict ? `Вердикт инженера: ${calc.engineerVerdict}\n` : ''}` +
    `\n⚠️ Любой результат отдела — предварительный, требует проверки инженером.`
  ), { parse_mode: 'Markdown' });
}

// ─── /eng-score ──────────────────────────────────────────────────────────────
async function handleEngScore(msg, bot) {
  const score = await engineering.getEngineeringScore();
  if (score.calculationsReviewed === 0) {
    return bot.sendMessage(msg.chat.id,
      `📊 Инженерный отдел — метрики\nПроверенных инженером расчётов за 90 дней пока нет.`);
  }
  await bot.sendMessage(msg.chat.id, clip(
    `📊 *Инженерный отдел — метрики* (${score.period})\n` +
    `Расчётов проверено инженером: ${score.calculationsReviewed}\n` +
    `Engineer-correction rate: ${(score.engineerCorrectionRate * 100).toFixed(0)}% ` +
    `(цель Y1 ≤${(score.correctionRateTargetY1 * 100).toFixed(0)}%)\n` +
    `Пропущенных расчётных случаев: ${(score.missedLoadCaseRate * 100).toFixed(0)}% (цель <10%)\n` +
    (score.independentAgreementRate != null
      ? `Согласие независимого метода: ${(score.independentAgreementRate * 100).toFixed(0)}% (цель ≥90%)\n` : '')
  ), { parse_mode: 'Markdown' });
}

// ─── /eng-archive [фильтр] ───────────────────────────────────────────────────
async function handleEngArchive(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filter = {};
  if (args[0]) {
    const d = DISCIPLINE_ALIASES[args[0].toLowerCase()];
    if (d) filter.discipline = d;
    else filter.status = args[0];
  }
  const calcs = await engineering.listCalculations(filter, 20);
  if (!calcs.length) return bot.sendMessage(msg.chat.id, 'Архив пуст или ничего не найдено.');
  await bot.sendMessage(msg.chat.id, clip(
    `🗄 *Архив инженерных расчётов* (${calcs.length}):\n` +
    calcs.map(c => `#${c.id} [${c.status}] ${disciplineLabel(c.discipline)} — ${c.title}`).join('\n')
  ), { parse_mode: 'Markdown' });
}

function disciplineLabel(d) {
  return ({ structural: 'строймеханика', hydraulic: 'гидравлика',
            power_electronics: 'силовая электроника' })[d] || d;
}

// ============================================================================
// REGISTRATION
// ============================================================================
//
// Register in bot.js. Use anchored regexes so /calc-norms, /calc-loadcases,
// /calc-verify, /calc-review, /calc-show are NOT captured by /calc:
//
//   bot.onText(/^\/calc-norms\b/,     msg => guard(msg) && handleCalcNorms(msg, bot));
//   bot.onText(/^\/calc-loadcases\b/, msg => guard(msg) && handleCalcLoadcases(msg, bot));
//   bot.onText(/^\/calc-verify\b/,    msg => guard(msg) && handleCalcVerify(msg, bot));
//   bot.onText(/^\/calc-review\b/,    msg => guard(msg) && handleCalcReview(msg, bot));
//   bot.onText(/^\/calc-show\b/,      msg => guard(msg) && handleCalcShow(msg, bot));
//   bot.onText(/^\/calc\b/,           msg => guard(msg) && handleCalc(msg, bot));
//   bot.onText(/^\/eng-score\b/,      msg => guard(msg) && handleEngScore(msg, bot));
//   bot.onText(/^\/eng-archive\b/,    msg => guard(msg) && handleEngArchive(msg, bot));
//
// Register the /calc-* commands BEFORE /calc, or rely on the \b anchors.

module.exports = {
  handleCalc,
  handleCalcNorms,
  handleCalcLoadcases,
  handleCalcVerify,
  handleCalcReview,
  handleCalcShow,
  handleEngScore,
  handleEngArchive
};
