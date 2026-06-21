// patches/bot-finance-handlers.js
// Finance — handlers for bot.js
//
// INSTRUCTIONS:
// 1. Open bot.js
// 2. At the top, where other modules are required, add:
//      const finance = require('./lib/finance');
// 3. Locate a section near similar analytical handlers
// 4. Copy each BEGIN/END marked block into bot.js
//
// Handlers use OWNER_ID from env. Pattern: more specific regex first, broader later.

const finance = require('../lib/finance');

// Helper for safe number parsing
function parseAmount(s) {
  const n = parseFloat(String(s).replace(/[,\s]/g, '').replace(/[^\d.-]/g, ''));
  return isNaN(n) ? null : n;
}

// State for multi-step interactions
const pendingFinanceVerifications = new Map();
const pendingFinanceInvoices = new Map();

// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-forecast <days>
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-forecast ===
bot.onText(/^\/finance-forecast(?:\s+(\d+))?(?:\s+(BY|RU|EU|US))?(?:\s+(ooo|ip|selfemployed))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const days = parseInt(match[1] || '30', 10);
  const jurisdiction = (match[2] || 'BY').toUpperCase();
  const businessForm = (match[3] || 'ooo').toLowerCase();

  try {
    bot.sendChatAction(msg.chat.id, 'typing');
    const record = await finance.buildCashflowForecast({ horizonDays: days, jurisdiction, businessForm });
    const archiveLink = record.archiveMessageId
      ? `\n\n📎 В архиве: https://t.me/c/${String(record.archiveChannelId).slice(4)}/${record.archiveMessageId}`
      : '';
    await bot.sendMessage(msg.chat.id, `💰 Cashflow forecast создан\n\nID: ${record.id}\nГоризонт: ${days}d\nЮрисдикция: ${jurisdiction}/${businessForm}${archiveLink}`);
  } catch (e) {
    console.error('[finance-forecast]', e);
    await bot.sendMessage(msg.chat.id, `❌ ${e.message}`);
  }
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-invoice [filter]
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-invoice ===
bot.onText(/^\/finance-invoice(?:\s+(.+))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const filterText = match[1];

  try {
    const where = {};
    if (filterText === 'overdue') where.status = 'overdue';
    else if (filterText === 'open') where.status = { in: ['issued', 'sent', 'partially-paid'] };
    else if (filterText === 'paid') where.status = 'paid';

    const invoices = await finance.listInvoices(where);

    if (invoices.length === 0) {
      return bot.sendMessage(msg.chat.id, '📭 Инвойсов нет');
    }

    const list = invoices.slice(0, 15).map(inv =>
      `#${inv.invoiceNumber} [${inv.status}] ${inv.amount} ${inv.currency}, due ${inv.dueDate.toISOString().slice(0,10)}`
    ).join('\n');

    await bot.sendMessage(msg.chat.id, `📄 Finance invoices (${invoices.length}):\n\n${list}`);
  } catch (e) {
    await bot.sendMessage(msg.chat.id, `❌ ${e.message}`);
  }
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-tax <jurisdiction> <amount> <type>
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-tax ===
bot.onText(/^\/finance-tax\s+(BY|RU|EU|US)\s+([\d.,\s]+)\s+(\S+)(?:\s+(ooo|ip|selfemployed))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const jurisdiction = match[1].toUpperCase();
  const amount = parseAmount(match[2]);
  const taxType = match[3].toLowerCase();
  const businessForm = (match[4] || 'ooo').toLowerCase();

  if (amount === null) {
    return bot.sendMessage(msg.chat.id, '❌ Некорректная сумма');
  }

  try {
    bot.sendChatAction(msg.chat.id, 'typing');
    const record = await finance.quickTaxCalc({ jurisdiction, businessForm, amount, taxType });
    const archiveLink = record.archiveMessageId
      ? `\n\n📎 https://t.me/c/${String(record.archiveChannelId).slice(4)}/${record.archiveMessageId}`
      : '';
    await bot.sendMessage(msg.chat.id, `📐 Tax calc:\n${record.fullResult}${archiveLink}`, { parse_mode: 'Markdown' });
  } catch (e) {
    await bot.sendMessage(msg.chat.id, `❌ ${e.message}\n\nИспользуйте: /finance-tax <BY|RU|EU|US> <amount> <type> [ooo|ip|selfemployed]\nПример: /finance-tax BY 100000 profit ooo`);
  }
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-verify <id>
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-verify ===
bot.onText(/^\/finance-verify\s+(\d+)(?:\s+([\d.,\s]+))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const id = parseInt(match[1], 10);
  const actualAmount = match[2] ? parseAmount(match[2]) : null;

  try {
    if (actualAmount !== null) {
      // Direct verification with actual amount
      const v = await finance.verifyForecast(id, { actualAmount });
      await bot.sendMessage(msg.chat.id, `✅ Verified #${id}\n` +
        `Outcome: ${v.outcome}\n` +
        `Forecasted: ${v.forecastedAmount}, Actual: ${v.actualAmount}\n` +
        `Error: ${v.errorPercent !== null ? v.errorPercent.toFixed(2) + '%' : 'N/A'}`);
    } else {
      // Show inline keyboard
      pendingFinanceVerifications.set(msg.from.id, { id });
      await bot.sendMessage(msg.chat.id, `Verification #${id} — выберите outcome:`, {
        reply_markup: {
          inline_keyboard: [[
            { text: '✓ Verified', callback_data: `finance_verify:${id}:verified` },
            { text: '⚠ Partial', callback_data: `finance_verify:${id}:partial` },
            { text: '✗ Missed', callback_data: `finance_verify:${id}:missed` },
          ]],
        },
      });
    }
  } catch (e) {
    await bot.sendMessage(msg.chat.id, `❌ ${e.message}`);
  }
});

// Callback handler for inline keyboard
bot.on('callback_query', async (query) => {
  if (!query.data.startsWith('finance_verify:')) return;
  const [, id, outcome] = query.data.split(':');
  try {
    const v = await finance.verifyForecast(parseInt(id), { outcome });
    await bot.editMessageText(`✅ #${id} → ${outcome}`, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
    });
    pendingFinanceVerifications.delete(query.from.id);
  } catch (e) {
    await bot.editMessageText(`❌ ${e.message}`, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
    });
  }
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-archive [filter]
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-archive ===
bot.onText(/^\/finance-archive(?:\s+(.+))?/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const filter = match[1];

  const results = await finance.searchArchive(filter);

  if (results.length === 0) {
    return bot.sendMessage(msg.chat.id, '📭 Архив пуст или нет совпадений');
  }

  const list = results.slice(0, 10).map(r =>
    `#${r.id} [${r.status}] [${r.forecastType}] ${r.shortTitle} (${r.jurisdiction}/${r.businessForm})`
  ).join('\n');

  await bot.sendMessage(msg.chat.id, `📚 Finance архив (${results.length}):\n\n${list}`);
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance-score
// ═══════════════════════════════════════════════════════════════════════

// === BEGIN finance HANDLER: /finance-score ===
bot.onText(/^\/finance-score$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;

  const snap = await finance.getMetricSnapshot();
  let display;
  if (snap.value === null) {
    display = snap.note || 'недостаточно данных';
  } else {
    display = `${snap.value.toFixed(2)}%`;
  }

  await bot.sendMessage(msg.chat.id,
    `📊 Finance\n\n` +
    `Метрика: ${snap.metric}\n` +
    `Значение: ${display}\n` +
    `Target: ${snap.target || 'N/A'}\n` +
    `Период: ${snap.period}\n` +
    `Выборка: ${snap.sampleSize}`
  );
});
// === END finance HANDLER ===


// ═══════════════════════════════════════════════════════════════════════
// HANDLER: /finance (main, general request)
// ═══════════════════════════════════════════════════════════════════════
// NOTE: This handler must be registered LAST (after all /finance-* specific handlers)
// to avoid the same /yana-style greedy match problem we fixed in Sweep 0.

// === BEGIN finance HANDLER: /finance ===
bot.onText(/^\/finance(?:\s+(.+))?$/i, async (msg, match) => {
  if (msg.from.id !== OWNER_ID) return;
  const arg = match[1]?.trim();

  // Avoid matching sub-commands
  const RESERVED = ['forecast', 'invoice', 'tax', 'verify', 'archive', 'score', 'runway', 'unit'];
  if (arg && RESERVED.includes(arg.split(/\s+/)[0].toLowerCase())) return;

  if (!arg) {
    return bot.sendMessage(msg.chat.id,
      `💰 *Finance Department*\n\n` +
      `Команды:\n` +
      `/finance-forecast <days> [BY|RU|EU|US] [ooo|ip|selfemployed]\n` +
      `/finance-invoice [filter: overdue|open|paid]\n` +
      `/finance-tax <BY|RU|EU|US> <amount> <type> [form]\n` +
      `/finance-verify <id> [actualAmount]\n` +
      `/finance-archive [filter]\n` +
      `/finance-score`,
      { parse_mode: 'Markdown' });
  }

  // For free-text — placeholder. Full NLP integration in Sweep 2 (Yana enhancement).
  await bot.sendMessage(msg.chat.id, `💰 Finance принял запрос: "${arg}"\n\n(Free-text processing — будет добавлено в Sweep 2 после прокачки Яны.)`);
});
// === END finance HANDLER ===
