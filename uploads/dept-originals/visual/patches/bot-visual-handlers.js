// ============================================================================
// bot-visual-handlers.js — Visual Department bot.js command handlers
// ============================================================================
//
// TARGET-STATE REFERENCE for bot.js additions.
// Apply manually: read this file, add handlers near other bot.onText handlers.
// Don't blind-copy bot.js itself.
//
// 8 commands added:
//   /visual <type> <source_type> <source_id>  — full visual generation
//   /visual-card <source_id>                  — quick Type 3 card
//   /visual-archive [filter]                  — list artifacts
//   /visual-show <id>                         — retrieve specific artifact
//   /visual-template <type>                   — inspect template spec
//   /visual-style                             — show current style guide
//   /visual-spec <source_id>                  — generate Type 5 premium spec
//   /visual-recall <id> <answer|skip>         — recall test
//
// Plus auto-hooks in /analyze, /expert, /scan (see Phase X7 in plan)
// ============================================================================

const visual = require('./lib/visual');
const isOwner = (msg) => msg.from.id === Number(process.env.OWNER_TELEGRAM_ID);

// Helper: detect source type from id pattern or owner-supplied prefix
async function detectSourceType(idStr) {
  // If prefixed like "analysis:42" or "briefing:7", parse it
  if (idStr.includes(':')) {
    const [type, id] = idStr.split(':');
    return { sourceType: type, sourceId: parseInt(id) };
  }
  // Otherwise try id as analysis first (most common), then briefing, then artifact
  const id = parseInt(idStr);
  if (isNaN(id)) return null;

  // Check existence in each table (Prisma)
  const { PrismaClient } = require('@prisma/client');
  const prisma = new PrismaClient();

  try {
    const analysis = await prisma.analysis.findUnique({ where: { id } });
    if (analysis) return { sourceType: 'analysis', sourceId: id };

    const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
    if (briefing) return { sourceType: 'briefing', sourceId: id };

    const artifact = await prisma.knowledgeArtifact.findUnique({ where: { id } });
    if (artifact) return { sourceType: 'artifact', sourceId: id };
  } catch (e) {
    console.error('[visual handlers] detectSourceType error:', e.message);
  } finally {
    await prisma.$disconnect();
  }
  return null;
}

// ─── /visual <type> <source_type> <source_id> ────────────────────────────────
//
// Examples:
//   /visual card analysis 42      → Type 3 osp_analysis_card
//   /visual compression briefing 7 → Type 1 compression for briefing #7
//   /visual memorable analysis 42  → Type 2 memorable for analysis #42
//   /visual reference client 3     → Type 4 client_reference_sheet
// ─────────────────────────────────────────────────────────────────────────────

bot.onText(/^\/visual\s+(\w+)\s+(\w+)\s+(\d+)$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const [_, vType, sType, sId] = match;
  const chatId = msg.chat.id;

  try {
    await bot.sendMessage(chatId, `🎨 Generating Type ${vType} visual for ${sType}/${sId}...`);

    let artifact;
    if (vType === 'card') {
      artifact = await visual.generateAnalysisCard({ sourceType: sType, sourceId: parseInt(sId) });
    } else if (vType === 'compression') {
      artifact = await visual.generateCompressionVisual({ sourceType: sType, sourceId: parseInt(sId) });
    } else if (vType === 'memorable') {
      artifact = await visual.generateMemorableInfographic({ sourceType: sType, sourceId: parseInt(sId) });
    } else if (vType === 'reference') {
      artifact = await visual.generateReferenceSheet({ sourceType: sType, sourceId: parseInt(sId) });
    } else {
      await bot.sendMessage(chatId, `❌ Unknown visual type: ${vType}. Use: card | compression | memorable | reference`);
      return;
    }

    if (!artifact) {
      await bot.sendMessage(chatId, `❌ Generation failed. Check logs.`);
      return;
    }

    // Send back the SVG as document
    if (artifact.format === 'svg') {
      const buf = Buffer.from(artifact.content, 'utf-8');
      await bot.sendDocument(chatId, buf, {
        caption: `✅ ${artifact.title}\n\nVisualArtifact #${artifact.id}\nType: ${artifact.type}\nTier: ${artifact.tier}\nTemplate: ${artifact.templateVersion}`
      }, {
        filename: `visual_${artifact.id}.svg`,
        contentType: 'image/svg+xml'
      });
    }

    // Publish to archive channel
    if (process.env.ARCHIVE_CHANNEL_ID) {
      await visual.publishToArchive(artifact);
    }
  } catch (e) {
    console.error('[/visual]', e);
    await bot.sendMessage(chatId, `❌ Error: ${e.message}`);
  }
});

// ─── /visual-card <source_id> ────────────────────────────────────────────────
// Quick Type 3 card — auto-detects source type
// ─────────────────────────────────────────────────────────────────────────────

bot.onText(/^\/visual-card\s+(\S+)$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;

  const detected = await detectSourceType(match[1]);
  if (!detected) {
    await bot.sendMessage(chatId, `❌ Couldn't detect source. Use /visual card <source_type> <source_id>`);
    return;
  }

  try {
    await bot.sendMessage(chatId, `🎨 Generating card for ${detected.sourceType}/${detected.sourceId}...`);
    const artifact = await visual.generateAnalysisCard(detected);
    if (artifact && artifact.format === 'svg') {
      const buf = Buffer.from(artifact.content, 'utf-8');
      await bot.sendDocument(chatId, buf, {
        caption: `✅ ${artifact.title}`
      }, {
        filename: `card_${artifact.id}.svg`,
        contentType: 'image/svg+xml'
      });
    } else {
      await bot.sendMessage(chatId, `❌ Failed to generate.`);
    }
  } catch (e) {
    await bot.sendMessage(chatId, `❌ ${e.message}`);
  }
});

// ─── /visual-archive [filter] ────────────────────────────────────────────────

bot.onText(/^\/visual-archive(?:\s+(.*))?$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;
  const filterArg = match[1];

  const filter = {};
  if (filterArg) {
    // Simple parse: "type=card" or "tier=3" or "source=analysis"
    const parts = filterArg.split(/\s+/);
    for (const p of parts) {
      const [k, v] = p.split('=');
      if (k === 'type') filter.type = v;
      if (k === 'tier') filter.tier = parseInt(v);
      if (k === 'source') filter.sourceType = v;
    }
  }

  const artifacts = await visual.listArtifacts(filter, 20);
  if (artifacts.length === 0) {
    await bot.sendMessage(chatId, `📂 Archive empty${filterArg ? ` (filter: ${filterArg})` : ''}.`);
    return;
  }

  const lines = artifacts.map(a =>
    `#${a.id} · T${a.tier} · ${a.type} · ${a.sourceType}/${a.sourceId} · ${a.createdAt.toISOString().slice(0, 10)}\n  ${a.title}`
  );
  await bot.sendMessage(chatId, `📂 Visual Archive (${artifacts.length})\n\n${lines.join('\n\n')}`);
});

// ─── /visual-show <id> ────────────────────────────────────────────────────────

bot.onText(/^\/visual-show\s+(\d+)$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;
  const id = parseInt(match[1]);

  const artifact = await visual.getArtifact(id);
  if (!artifact) {
    await bot.sendMessage(chatId, `❌ Not found: #${id}`);
    return;
  }

  await bot.sendMessage(chatId,
    `📋 *Visual Artifact #${artifact.id}*\n\n` +
    `Title: ${artifact.title}\n` +
    `Type: ${artifact.type}\n` +
    `Tier: ${artifact.tier}\n` +
    `Template: ${artifact.templateVersion}\n` +
    `Source: ${artifact.sourceType}/${artifact.sourceId}\n` +
    `Format: ${artifact.format}\n` +
    `Created: ${artifact.createdAt.toISOString().slice(0, 10)}\n` +
    `Published to channel: ${artifact.publishedToChannel ? '✓' : '✗'}\n` +
    `Recall tested: ${artifact.recallTested ? `✓ (${artifact.recallSuccess ? 'success' : 'failed'})` : '✗'}`,
    { parse_mode: 'Markdown' }
  );

  if (artifact.format === 'svg') {
    const buf = Buffer.from(artifact.content, 'utf-8');
    await bot.sendDocument(chatId, buf, {}, {
      filename: `${artifact.type}_${artifact.id}.svg`,
      contentType: 'image/svg+xml'
    });
  } else if (artifact.format === 'spec_json') {
    await bot.sendMessage(chatId, '```json\n' + artifact.content.slice(0, 3500) + '\n```', { parse_mode: 'Markdown' });
  }
});

// ─── /visual-template <type> ──────────────────────────────────────────────────

bot.onText(/^\/visual-template\s+(\S+)$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;

  const { PrismaClient } = require('@prisma/client');
  const prisma = new PrismaClient();

  try {
    const template = await prisma.visualTemplate.findUnique({ where: { type: match[1] } });
    if (!template) {
      await bot.sendMessage(chatId, `❌ Template not found: ${match[1]}\n\nAvailable: run /visual-template list`);
      return;
    }

    await bot.sendMessage(chatId,
      `📐 *Template: ${template.type}*\n\n` +
      `Tier: ${template.tier}\n` +
      `Current version: ${template.currentVersion}\n` +
      `Apply: ${template.applyTo}\n\n` +
      `Description: ${template.description || '—'}\n\n` +
      `Spec:\n\`\`\`json\n${template.spec.slice(0, 2500)}\n\`\`\``,
      { parse_mode: 'Markdown' }
    );
  } finally {
    await prisma.$disconnect();
  }
});

// ─── /visual-style ────────────────────────────────────────────────────────────

bot.onText(/^\/visual-style$/, async (msg) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;

  const brand = visual.BRAND;
  const text =
    `🎨 *Fosved Visual Department — Style Guide*\n\n` +
    `*Colors:*\n` +
    Object.entries(brand.colors).map(([k, v]) => `  ${k}: \`${v}\``).join('\n') +
    `\n\n*Typography:*\n` +
    Object.entries(brand.typography).map(([k, v]) => `  ${k}: ${v.family} ${v.weight}`).join('\n') +
    `\n\n*Canvas:*\n` +
    Object.entries(brand.canvas).map(([k, v]) => `  ${k}: ${v.w}×${v.h}`).join('\n') +
    `\n\n*Spacing:* 8px scale, 64px outer margins, 12-col grid, 24px gutters`;

  await bot.sendMessage(chatId, text, { parse_mode: 'Markdown' });
});

// ─── /visual-spec <source_id> ────────────────────────────────────────────────

bot.onText(/^\/visual-spec\s+(\S+)(?:\s+(.+))?$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;

  const detected = await detectSourceType(match[1]);
  if (!detected) {
    await bot.sendMessage(chatId, `❌ Couldn't detect source.`);
    return;
  }
  const focusTheme = match[2] || null;

  try {
    await bot.sendMessage(chatId, `📐 Generating Type 5 premium spec for ${detected.sourceType}/${detected.sourceId}...`);
    const artifact = await visual.generatePremiumSpec({ ...detected, focusTheme });
    if (!artifact) {
      await bot.sendMessage(chatId, `❌ Failed to generate.`);
      return;
    }

    await bot.sendMessage(chatId,
      `✅ Premium spec generated: #${artifact.id}\n\n` +
      `Execute manually using:\n• Midjourney v7 for base image\n• Figma for text overlays + assembly\n\n` +
      `View spec: /visual-show ${artifact.id}`
    );

    if (process.env.ARCHIVE_CHANNEL_ID) {
      await visual.publishToArchive(artifact);
    }
  } catch (e) {
    await bot.sendMessage(chatId, `❌ ${e.message}`);
  }
});

// ─── /visual-recall <id> <answer|skip> ───────────────────────────────────────

bot.onText(/^\/visual-recall\s+(\d+)\s+(.+)$/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chatId = msg.chat.id;
  const id = parseInt(match[1]);
  const answer = match[2].trim();

  if (answer.toLowerCase() === 'skip') {
    await bot.sendMessage(chatId, `⏭ Skipped recall test for #${id}`);
    return;
  }

  // Owner's answer is the recall attempt. We don't auto-judge correctness —
  // owner self-reports by including "+ success" or "+ failed" in answer.
  let recallSuccess = null;
  let note = answer;
  if (/\+\s*success$/i.test(answer)) {
    recallSuccess = true;
    note = answer.replace(/\+\s*success$/i, '').trim();
  } else if (/\+\s*failed?$/i.test(answer)) {
    recallSuccess = false;
    note = answer.replace(/\+\s*failed?$/i, '').trim();
  }

  await visual.recallTest(id, recallSuccess, note);
  await bot.sendMessage(chatId,
    `✓ Recall test recorded for #${id}\n` +
    `Outcome: ${recallSuccess === null ? 'unjudged' : recallSuccess ? 'success' : 'failed'}\n` +
    `Note: ${note}`
  );
});

// ═══════════════════════════════════════════════════════════════════════════════
// AUTO-HOOKS — add these to existing /analyze, /expert, /scan handlers
// ═══════════════════════════════════════════════════════════════════════════════
//
// At the END of /analyze success handler (after Analysis is saved + summary sent):
//
//   if (process.env.VISUAL_AUTO_GENERATION !== 'false') {
//     try {
//       const visualArtifact = await visual.generateAnalysisCard({
//         sourceType: 'analysis',
//         sourceId: analysis.id
//       });
//       if (visualArtifact && process.env.ARCHIVE_CHANNEL_ID) {
//         await visual.publishToArchive(visualArtifact);
//       }
//     } catch (e) {
//       console.error('[visual auto-gen]', e.message); // non-blocking
//     }
//   }
//
// Same pattern for /expert (sourceType: 'briefing', sourceId: briefing.id)
// Same pattern for /scan (sourceType: 'artifact', sourceId: artifact.id)
//
// ═══════════════════════════════════════════════════════════════════════════════

module.exports = {}; // file is patch reference, not standalone module
