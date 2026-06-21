// patches/bot-legal-handlers.js
// Legal — handlers for bot.js
//
// Each handler that produces result calls dept.saveResult() → auto-archived (long docs as files).

const dept = require('../lib/legal');

// Shared state
const pendingLegalContext = new Map();   // userId -> { command, jurisdiction, businessForm, counterpartyJurisdiction, counterpartyForm }
const pendingLegalVerifications = new Map();


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /legal — main entry
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal HANDLER: /legal ===
bot.onText(/^\/legal(?:\s+(.+))?$/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const input = match[1] ? match[1].trim() : '';

  if (!input) {
    return bot.sendMessage(msg.chat.id,
      'Юрист. Что разбираем?\n\n' +
      'Команды:\n' +
      '/legal-nda — быстрый NDA\n' +
      '/legal-msa — быстрый MSA\n' +
      '/legal-review <текст> — анализ присланного договора (red flags)\n' +
      '/legal-risk-map <ситуация> — карта рисков сделки\n' +
      '/legal-verify <id> — verification прошлой работы\n' +
      '/legal-archive [фильтр] — поиск\n' +
      '/legal-score — метрика отдела\n' +
      '/legal-templates — список шаблонов\n\n' +
      'Или опишите задачу свободным текстом.'
    );
  }

  // Free-form — нужен контекст (своя jurisdiction + form)
  await bot.sendMessage(msg.chat.id, 'Юрисдикция (наша сторона)?', {
    reply_markup: {
      inline_keyboard: [[
        { text: 'BY', callback_data: 'leg_jx:BY' },
        { text: 'RU', callback_data: 'leg_jx:RU' },
        { text: 'EU', callback_data: 'leg_jx:EU' },
        { text: 'US', callback_data: 'leg_jx:US' },
      ]]
    }
  });
  pendingLegalContext.set(msg.from.id, { input });
});
// === END legal HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: callbacks
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal HANDLER: callbacks ===
bot.on('callback_query', async (query) => {
  // Jurisdiction selection
  if (query.data.startsWith('leg_jx:')) {
    const jurisdiction = query.data.split(':')[1];
    const ctx = pendingLegalContext.get(query.from.id) || {};
    ctx.jurisdiction = jurisdiction;
    pendingLegalContext.set(query.from.id, ctx);

    await bot.editMessageText(`Юрисдикция: ${jurisdiction}\n\nБизнес-форма (наша сторона)?`, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
      reply_markup: {
        inline_keyboard: [[
          { text: 'ООО', callback_data: 'leg_bf:ooo' },
          { text: 'ИП', callback_data: 'leg_bf:ip' },
          { text: 'Самозанятый', callback_data: 'leg_bf:selfemployed' },
        ]]
      }
    });
    return;
  }

  // Business form selection
  if (query.data.startsWith('leg_bf:')) {
    const businessForm = query.data.split(':')[1];
    const ctx = pendingLegalContext.get(query.from.id) || {};
    ctx.businessForm = businessForm;
    pendingLegalContext.set(query.from.id, ctx);

    // Spirit: ask if counterparty has different context
    await bot.editMessageText(
      `Наша сторона: ${ctx.jurisdiction} / ${businessForm}\n\nКонтрагент в другой юрисдикции?`,
      {
        chat_id: query.message.chat.id,
        message_id: query.message.message_id,
        reply_markup: {
          inline_keyboard: [[
            { text: 'Нет (одна юрисдикция)', callback_data: 'leg_cp:same' },
            { text: 'Да, выбрать', callback_data: 'leg_cp:choose' },
          ]]
        }
      }
    );
    return;
  }

  // Counterparty choice
  if (query.data === 'leg_cp:same') {
    const ctx = pendingLegalContext.get(query.from.id) || {};
    await bot.editMessageText(
      `Контекст: ${ctx.jurisdiction} / ${ctx.businessForm}, одна юрисдикция.\n\n` +
      `Запрос: "${ctx.input}"\n\n` +
      `_Обработка..._`,
      { chat_id: query.message.chat.id, message_id: query.message.message_id, parse_mode: 'Markdown' }
    );
    await bot.sendMessage(query.message.chat.id,
      `Контекст зафиксирован.\n\nПолная обработка свободного текста через LLM с применением скиллов legal будет реализована в Phase L5.\n\n` +
      `_Disclaimer: Этот документ — draft + risk map, не финальный юр. документ. Перед signing — обязательная проверка лицензированным юристом._`
    );
    pendingLegalContext.delete(query.from.id);
    return;
  }

  if (query.data === 'leg_cp:choose') {
    await bot.editMessageText('Юрисдикция контрагента?', {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
      reply_markup: {
        inline_keyboard: [[
          { text: 'BY', callback_data: 'leg_cpjx:BY' },
          { text: 'RU', callback_data: 'leg_cpjx:RU' },
          { text: 'EU', callback_data: 'leg_cpjx:EU' },
          { text: 'US', callback_data: 'leg_cpjx:US' },
        ]]
      }
    });
    return;
  }

  if (query.data.startsWith('leg_cpjx:')) {
    const cpJx = query.data.split(':')[1];
    const ctx = pendingLegalContext.get(query.from.id) || {};
    ctx.counterpartyJurisdiction = cpJx;
    pendingLegalContext.set(query.from.id, ctx);

    await bot.editMessageText(
      `Контекст: ${ctx.jurisdiction}/${ctx.businessForm} ↔ ${cpJx}/?\n\n` +
      `Запрос: "${ctx.input}"\n\n` +
      `Cross-jurisdictional случай. Полная обработка в Phase L5.\n\n` +
      `_Disclaimer..._`,
      { chat_id: query.message.chat.id, message_id: query.message.message_id }
    );
    pendingLegalContext.delete(query.from.id);
    return;
  }

  // Verification callbacks
  if (query.data.startsWith('leg_verify:')) {
    const [, id, outcome] = query.data.split(':');
    const pending = pendingLegalVerifications.get(query.from.id);
    const notes = pending ? pending.notes : '';

    await dept.verifyResult(parseInt(id), { outcome, notes });
    await bot.editMessageText(`✅ Verification recorded: #${id} → ${outcome}`, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
    });
    pendingLegalVerifications.delete(query.from.id);
  }
});
// === END legal HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// Other handlers: /legal-nda, /legal-msa, /legal-review, /legal-risk-map,
//                 /legal-verify, /legal-archive, /legal-score, /legal-templates
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN legal HANDLER: /legal-nda ===
bot.onText(/^\/legal-nda$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;
  await bot.sendMessage(msg.chat.id,
    'NDA генерация. Phase L5 implementation — using skill nda-msa-sla-templates.\n\n' +
    'Until then: используйте /legal "сделай NDA для клиента X в юрисдикции BY".'
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-msa ===
bot.onText(/^\/legal-msa$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;
  await bot.sendMessage(msg.chat.id,
    'MSA генерация. Phase L5 — using contract-drafting-discipline + nda-msa-sla-templates.'
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-review ===
bot.onText(/^\/legal-review(?:\s+([\s\S]+))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const text = match[1];
  if (!text) {
    return bot.sendMessage(msg.chat.id,
      'Пришлите текст договора одним сообщением после команды, или прикрепите файл и используйте /legal-review с описанием.'
    );
  }

  await bot.sendMessage(msg.chat.id,
    `Red flag analysis (${text.length} chars). Phase L5 — applies red-flag-detection skill.\n\n` +
    `Текущий placeholder: для анализа договора используйте /legal "проверь этот договор: <текст>"`
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-risk-map ===
bot.onText(/^\/legal-risk-map\s+(.+)/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const situation = match[1];
  await bot.sendMessage(msg.chat.id,
    `Risk mapping for: "${situation}"\n\n` +
    `Phase L5 — applies risk-mapping-protocol skill with full context flow.`
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-verify ===
bot.onText(/^\/legal-verify\s+(\d+)(?:\s+(.+))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const id = parseInt(match[1], 10);
  const notes = match[2] || '';

  pendingLegalVerifications.set(msg.from.id, { id, notes });

  await bot.sendMessage(msg.chat.id, `Verification для assessment #${id}. Исход?`, {
    reply_markup: {
      inline_keyboard: [[
        { text: '✓ Clean', callback_data: `leg_verify:${id}:clean` },
        { text: '⚠ Rewrite', callback_data: `leg_verify:${id}:rewrite` },
        { text: '✗ Dispute', callback_data: `leg_verify:${id}:dispute` },
      ]]
    }
  });
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-archive ===
bot.onText(/^\/legal-archive(?:\s+(.+))?$/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const filter = match[1];

  const results = await dept.searchArchive(
    filter ? { shortTitle: { contains: filter, mode: 'insensitive' } } : null
  );

  if (results.length === 0) {
    return bot.sendMessage(msg.chat.id, '📭 Архив пуст или нет совпадений');
  }

  const lines = results.slice(0, 10).map(r =>
    `#${r.id} [${r.status}] [${r.documentType}] ${r.shortTitle}`
  );

  await bot.sendMessage(msg.chat.id,
    `📚 Legal архив (${results.length}):\n\n${lines.join('\n')}`
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-score ===
bot.onText(/^\/legal-score$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;

  const snap = await dept.getMetricSnapshot();
  const display = snap.value !== null
    ? `${snap.value.toFixed(1)}${snap.unit || ''}`
    : 'недостаточно данных';

  await bot.sendMessage(msg.chat.id,
    `📊 Legal\n\n` +
    `Метрика: ${snap.metric}\n` +
    `Значение: ${display}\n` +
    `За период: ${snap.period}\n` +
    `Выборка: ${snap.sampleSize}\n` +
    `Цели Y1: ${snap.target.y1}, Y2: ${snap.target.y2}`
  );
});
// === END legal HANDLER ===

// === BEGIN legal HANDLER: /legal-templates ===
bot.onText(/^\/legal-templates$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;
  const templates = await dept.listTemplates();

  if (templates.length === 0) {
    return bot.sendMessage(msg.chat.id,
      '📋 Шаблоны не загружены. Phase L5 — addition of standard templates (NDA/MSA/SLA/TZ) for BY/RU/EU/US.'
    );
  }

  const lines = templates.map(t =>
    `#${t.id} [${t.documentType}] [${t.jurisdiction}/${t.businessForm || 'any'}] ${t.name} v${t.version}`
  );

  await bot.sendMessage(msg.chat.id,
    `📋 Доступные шаблоны (${templates.length}):\n\n${lines.join('\n')}`
  );
});
// === END legal HANDLER ===
