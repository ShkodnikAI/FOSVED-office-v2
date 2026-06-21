// ============================================================================
// bot-marketing-handlers.js — bot.js command handlers for the Marketing dept
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 8 commands.
//
// HOW TO APPLY:
// 1. Open bot.js
// 2. Add the require for lib/marketing.js with the other lib requires
// 3. Add each handler in the command-handler section, matching bot.js's
//    existing registration style. Use anchored regexes so e.g.
//    /campaign-verify is not captured by /campaign.
// 4. Keep the OWNER-only guard that bot.js already applies.
// 5. Verify: node -c bot.js
// ============================================================================

const marketing = require('./lib/marketing.js');

function parseArgs(text) {
  const parts = text.trim().split(/\s+/);
  parts.shift();
  return { args: parts, rest: parts.join(' ') };
}
function clip(s) { return String(s).slice(0, 4000); }

// ─── /market-research <тема/продукт> ─────────────────────────────────────────
// Research is produced by the marketing specialist (LLM) following the
// market-research-methods skill; the handler persists the result. This handler
// shows the intake — the bot then calls marketing.createMarketResearch(...)
// with the specialist's structured output.
async function handleMarketResearch(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /market-research <тема или продукт>');
  await bot.sendMessage(msg.chat.id, clip(
    `🔍 Исследование рынка: "${rest}"\n` +
    `Специалист отдела Продвижения проводит исследование по скиллу ` +
    `market-research-methods (вопрос → сбор данных с тегами достоверности → ` +
    `findings → прогнозы). Результат сохраняется через createMarketResearch ` +
    `и публикуется в архив.`
  ));
}

// ─── /segment <продукт> ──────────────────────────────────────────────────────
async function handleSegment(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) {
    // No arg → list existing segments
    const segments = await marketing.listSegments({}, 20);
    if (!segments.length) return bot.sendMessage(msg.chat.id,
      'Сегментов пока нет. Использование: /segment <продукт> — определить сегменты.');
    return bot.sendMessage(msg.chat.id, clip(
      `👥 *Сегменты аудитории* (${segments.length}):\n` +
      segments.map(s => `#${s.id} [${s.status}] ${s.name}`).join('\n')
    ), { parse_mode: 'Markdown' });
  }
  await bot.sendMessage(msg.chat.id, clip(
    `👥 Сегментация для "${rest}"\n` +
    `Специалист определяет 2-4 конкретных сегмента по скиллу audience-segmentation ` +
    `(каждый: кто / боль / где достичь / текущая альтернатива). Сохраняется через ` +
    `createAudienceSegment — функция отклонит размытые формулировки (жёсткое правило 3).`
  ));
}

// ─── /competitors <рынок/продукт> ────────────────────────────────────────────
async function handleCompetitors(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id,
    'Использование: /competitors <рынок или продукт>');
  await bot.sendMessage(msg.chat.id, clip(
    `🔭 Анализ конкурентов: "${rest}"\n` +
    `Специалист анализирует поле по скиллу competitive-analysis — прямые/непрямые ` +
    `конкуренты, субституты, «ничего не делать». Результат: основа дифференциации. ` +
    `Сохраняется как MarketResearch (тип competitive).`
  ));
}

// ─── /campaign <продукт> ─────────────────────────────────────────────────────
async function handleCampaign(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) {
    const campaigns = await marketing.listCampaigns({}, 15);
    if (!campaigns.length) return bot.sendMessage(msg.chat.id,
      'Кампаний пока нет. Использование: /campaign <продукт> — создать кампанию.');
    return bot.sendMessage(msg.chat.id, clip(
      `📣 *Кампании* (${campaigns.length}):\n` +
      campaigns.map(c => `#${c.id} [${c.status}] ${c.title} → ${c.productPromoted}`).join('\n')
    ), { parse_mode: 'Markdown' });
  }
  await bot.sendMessage(msg.chat.id, clip(
    `📣 Кампания продвижения: "${rest}"\n` +
    `Специалист готовит кампанию: сегмент → позиционирование (positioning-and-messaging) ` +
    `→ каналы (channel-strategy). Сохраняется через createCampaign в статусе drafted.\n\n` +
    `⚠️ Кампания НЕ запустится без двух шагов:\n` +
    `1. /campaign-forecast <id> — обязательный числовой прогноз (жёсткое правило 1)\n` +
    `2. проверка заявлений honest-claims-discipline (жёсткое правило 2)`
  ));
}

// ─── /campaign-forecast <campaign_id> ────────────────────────────────────────
async function handleCampaignForecast(msg, bot) {
  const { args } = parseArgs(msg.text);
  const campaignId = parseInt(args[0], 10);
  if (!campaignId) return bot.sendMessage(msg.chat.id,
    'Использование: /campaign-forecast <campaign_id>');
  await bot.sendMessage(msg.chat.id, clip(
    `📐 Прогноз для кампании #${campaignId}\n` +
    `Специалист по скиллу forecast-before-launch фиксирует: конверсию (диапазон ` +
    `low–expected–high), CAC, охват, обоснование, уверенность. Через setCampaignForecast.\n` +
    `Если передана customerLtv — функция вернёт go/no-go по LTV:CAC ` +
    `(прогноз ниже 1:1 → запуск запрещён).`
  ));
}

// ─── /campaign-verify <campaign_id> ──────────────────────────────────────────
async function handleCampaignVerify(msg, bot) {
  const { args } = parseArgs(msg.text);
  const campaignId = parseInt(args[0], 10);
  if (!campaignId) return bot.sendMessage(msg.chat.id,
    'Использование: /campaign-verify <campaign_id>');
  await bot.sendMessage(msg.chat.id, clip(
    `📊 Верификация кампании #${campaignId}\n` +
    `По скиллу campaign-verification: прогноз vs факт (конверсия ±25%, CAC ±30%), ` +
    `детект overoptimism, диагноз источника промаха, урок. Через verifyCampaign.\n` +
    `Если кампания была привязана к сегменту — не забыть updateSegmentValidation.`
  ));
}

// ─── /marketing-score ────────────────────────────────────────────────────────
async function handleMarketingScore(msg, bot) {
  const score = await marketing.getMarketingScore();
  if (score.campaignsVerified === 0) {
    return bot.sendMessage(msg.chat.id,
      `📈 Marketing — метрики\nВерифицированных кампаний за 90 дней пока нет.`);
  }
  await bot.sendMessage(msg.chat.id, clip(
    `📈 *Marketing — метрики* (${score.period})\n` +
    `Кампаний верифицировано: ${score.campaignsVerified}\n` +
    (score.avgConversionAccuracy != null
      ? `Средняя точность прогноза конверсии: ±${(score.avgConversionAccuracy * 100).toFixed(0)}% (цель ≤25%)\n` : '') +
    (score.avgCacAccuracy != null
      ? `Средняя точность прогноза CAC: ±${(score.avgCacAccuracy * 100).toFixed(0)}% (цель ≤30%)\n` : '') +
    `Overoptimism rate: ${(score.overoptimismRate * 100).toFixed(0)}% (цель ≤15%)\n` +
    `Попадание конверсии в цель: ${(score.conversionWithinTargetRate * 100).toFixed(0)}%`
  ), { parse_mode: 'Markdown' });
}

// ─── /marketing-archive [фильтр] ─────────────────────────────────────────────
async function handleMarketingArchive(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filterWord = args[0];

  // The archive spans research + campaigns. Default: show recent of both.
  const [research, campaigns] = await Promise.all([
    marketing.listResearch(filterWord ? { status: filterWord } : {}, 10),
    marketing.listCampaigns(filterWord ? { status: filterWord } : {}, 10)
  ]);

  if (!research.length && !campaigns.length) {
    return bot.sendMessage(msg.chat.id, 'Архив пуст или ничего не найдено по фильтру.');
  }
  let out = '🗄 *Архив отдела Продвижения*\n';
  if (research.length) {
    out += `\n*Исследования* (${research.length}):\n` +
      research.map(r => `#${r.id} [${r.status}] ${r.title}`).join('\n');
  }
  if (campaigns.length) {
    out += `\n\n*Кампании* (${campaigns.length}):\n` +
      campaigns.map(c => `#${c.id} [${c.status}] ${c.title}`).join('\n');
  }
  await bot.sendMessage(msg.chat.id, clip(out), { parse_mode: 'Markdown' });
}

// ============================================================================
// REGISTRATION
// ============================================================================
//
// Register in bot.js following its existing style. Use anchored regexes so
// that /campaign-forecast and /campaign-verify are NOT captured by /campaign,
// and /market-research / /marketing-* don't collide:
//
//   bot.onText(/^\/market-research\b/,    msg => guard(msg) && handleMarketResearch(msg, bot));
//   bot.onText(/^\/segment\b/,            msg => guard(msg) && handleSegment(msg, bot));
//   bot.onText(/^\/competitors\b/,        msg => guard(msg) && handleCompetitors(msg, bot));
//   bot.onText(/^\/campaign-forecast\b/,  msg => guard(msg) && handleCampaignForecast(msg, bot));
//   bot.onText(/^\/campaign-verify\b/,    msg => guard(msg) && handleCampaignVerify(msg, bot));
//   bot.onText(/^\/campaign\b/,           msg => guard(msg) && handleCampaign(msg, bot));
//   bot.onText(/^\/marketing-score\b/,    msg => guard(msg) && handleMarketingScore(msg, bot));
//   bot.onText(/^\/marketing-archive\b/,  msg => guard(msg) && handleMarketingArchive(msg, bot));
//
// IMPORTANT: register /campaign-forecast and /campaign-verify BEFORE /campaign,
// or rely on the \b anchors to keep them distinct.

module.exports = {
  handleMarketResearch,
  handleSegment,
  handleCompetitors,
  handleCampaign,
  handleCampaignForecast,
  handleCampaignVerify,
  handleMarketingScore,
  handleMarketingArchive
};
