// PATCH for bot.js — Expert department v4.1 commands
// Adds expert briefing commands to existing v4 bot
// Apply by importing into bot.js and registering with bot

import { prisma } from './lib/prisma.js';

// =============================================================================
// /expert — main command, standard depth (level 2)
// =============================================================================

export async function handleExpert(ctx) {
  const text = ctx.message.text.replace(/^\/expert\s+/i, '').trim();
  if (!text) {
    return ctx.reply(
      'Usage: /expert <topic and meeting context>\n\n' +
      'Example: /expert termoyderny startup FusionCorp, meeting tomorrow 14:00, ' +
      'Academy of Sciences, 4 attendees, investment decision'
    );
  }

  return createExpertBriefing(ctx, text, 2);
}

// =============================================================================
// /quickexpert — quick depth (level 1, ~30 min analysis)
// =============================================================================

export async function handleQuickExpert(ctx) {
  const text = ctx.message.text.replace(/^\/quickexpert\s+/i, '').trim();
  if (!text) return ctx.reply('Usage: /quickexpert <topic>');

  return createExpertBriefing(ctx, text, 1);
}

// =============================================================================
// /deepexpert — deep due diligence (level 3, hours)
// =============================================================================

export async function handleDeepExpert(ctx) {
  const text = ctx.message.text.replace(/^\/deepexpert\s+/i, '').trim();
  if (!text) return ctx.reply('Usage: /deepexpert <topic>');

  await ctx.reply(
    `🔬 Deep Expert Briefing requested\n\n` +
    `Topic: "${text}"\n\n` +
    `Deep mode activates ALL skills including Tier 3:\n` +
    `• Pre-meeting intel on attendees\n` +
    `• Tactical meeting protocol\n` +
    `• Multi-hour research investment\n\n` +
    `Reply "/confirm-deepexpert ${text}" to proceed.`
  );
}

export async function handleConfirmDeepExpert(ctx) {
  const text = ctx.message.text.replace(/^\/confirm-deepexpert\s+/i, '').trim();
  return createExpertBriefing(ctx, text, 3);
}

// =============================================================================
// Briefing creation core
// =============================================================================

async function createExpertBriefing(ctx, text, depthLevel) {
  // Parse: topic [+ context with meeting date/time/attendees]
  const briefing = await prisma.expertBriefing.create({
    data: {
      topic: text,
      meetingContext: text,  // initial; will be refined
      depthLevel,
      status: 'requested'
    }
  });

  const depthLabel = ['Quick', 'Standard', 'Deep'][depthLevel - 1];
  const timeEstimate = ['~30 min', '~1-2 hours', '~3-6 hours'][depthLevel - 1];

  await ctx.reply(
    `🎯 Expert Briefing #${briefing.id} created\n\n` +
    `Mode: ${depthLabel} (${timeEstimate} analysis)\n` +
    `Topic: "${text.substring(0, 100)}${text.length > 100 ? '...' : ''}"\n\n` +
    `Запускаю протокол:\n` +
    `Phase 1 — Rapid Domain Immersion\n` +
    `Phase 2 — Project Deconstruction\n` +
    `Phase 3 — Failure Modes Mapping\n` +
    `Phase 4 — Combat Questions Design\n` +
    (depthLevel >= 2 ? `+ Tier 2 enrichment (economics, peer review, adjacent fields, competitors)\n` : '') +
    (depthLevel === 3 ? `+ Tier 3 (pre-meeting intel, tactical protocol)\n` : '') +
    `\nWill notify when briefing is ready.`
  );

  // Trigger actual briefing generation
  // (real implementation invokes Expert specialist with skills loaded)
  console.log(`[expert] Briefing #${briefing.id} initiated at depth ${depthLevel}`);

  return briefing;
}

// =============================================================================
// /expert-update — add context to existing briefing
// =============================================================================

export async function handleExpertUpdate(ctx) {
  const text = ctx.message.text.replace(/^\/expert-update\s+/i, '').trim();
  const match = text.match(/^(\d+)\s+(.+)$/);
  if (!match) {
    return ctx.reply('Usage: /expert-update <id> <new context info>');
  }

  const [, idStr, newInfo] = match;
  const id = parseInt(idStr);

  const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
  if (!briefing) return ctx.reply(`Briefing #${id} not found`);

  await prisma.expertBriefing.update({
    where: { id },
    data: {
      meetingContext: (briefing.meetingContext || '') + '\n\nUPDATE: ' + newInfo
    }
  });

  await ctx.reply(
    `✅ Updated briefing #${id} with new context.\n\n` +
    `If briefing is ready, consider regenerating combat questions with updated context.`
  );
}

// =============================================================================
// /expert-followup — add question post-briefing
// =============================================================================

export async function handleExpertFollowup(ctx) {
  const text = ctx.message.text.replace(/^\/expert-followup\s+/i, '').trim();
  const match = text.match(/^(\d+)\s+(.+)$/);
  if (!match) return ctx.reply('Usage: /expert-followup <id> <question>');

  const [, idStr, question] = match;
  const id = parseInt(idStr);

  const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
  if (!briefing) return ctx.reply(`Briefing #${id} not found`);

  // Append to combat questions
  const updated = (briefing.combatQuestions || '') + '\n\nFOLLOW-UP QUESTION:\n' + question;

  await prisma.expertBriefing.update({
    where: { id },
    data: { combatQuestions: updated }
  });

  await ctx.reply(`✅ Question added to briefing #${id}`);
}

// =============================================================================
// /expert-debrief — post-meeting analysis
// =============================================================================

export async function handleExpertDebrief(ctx) {
  const text = ctx.message.text.replace(/^\/expert-debrief\s*/i, '').trim();
  const match = text.match(/^(\d+)\s*(.*)$/);

  if (!match) {
    // Show debrief candidates
    const pending = await prisma.expertBriefing.findMany({
      where: { status: 'meeting_held' },
      orderBy: { meetingHeldAt: 'desc' },
      take: 5
    });

    if (pending.length === 0) {
      return ctx.reply('No pending debriefs. Use /expert-debrief <id> [notes]');
    }

    return ctx.reply(
      'Pending debriefs:\n' +
      pending.map(b => `#${b.id}: ${b.topic.substring(0, 50)}`).join('\n') +
      '\n\nUsage: /expert-debrief <id> <notes about meeting>'
    );
  }

  const [, idStr, notes] = match;
  const id = parseInt(idStr);

  const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
  if (!briefing) return ctx.reply(`Briefing #${id} not found`);

  // Save debrief notes
  await prisma.expertBriefing.update({
    where: { id },
    data: {
      debriefNotes: notes,
      status: 'debriefed',
      meetingHeldAt: briefing.meetingHeldAt || new Date()
    }
  });

  await ctx.reply(
    `📝 Debrief saved for #${id}\n\n` +
    `Now analyze:\n` +
    `1. Which combat questions worked?\n` +
    `2. What did they answer well?\n` +
    `3. What did they evade?\n` +
    `4. What was unexpected?\n` +
    `5. Updated assessment of project?\n\n` +
    `Reply with structured debrief or use /expert-rate ${id} for self-rating prompts.`
  );
}

// =============================================================================
// /expert-rate — owner self-rating after meeting
// =============================================================================

export async function handleExpertRate(ctx) {
  const id = parseInt(ctx.message.text.replace(/^\/expert-rate\s+/i, '').trim());
  if (!id) return ctx.reply('Usage: /expert-rate <id>');

  const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
  if (!briefing) return ctx.reply(`Briefing #${id} not found`);

  return ctx.reply(
    `📊 Rating prompts for briefing #${id}\n\n` +
    `Reply with your scores (1-5):\n\n` +
    `1. Understanding score: how well-prepared were you?\n` +
    `2. Owner confidence: how confident did you feel?\n` +
    `3. Question hit rate: % of combat questions that worked (0-100)\n` +
    `4. Bullshit detected: did pre-identified bullshit appear? (yes/no)\n\n` +
    `Format: /expert-scores ${id} <1-5> <1-5> <0-100> <yes/no>\n` +
    `Example: /expert-scores ${id} 4 5 70 yes`
  );
}

export async function handleExpertScores(ctx) {
  const text = ctx.message.text.replace(/^\/expert-scores\s+/i, '').trim();
  const match = text.match(/^(\d+)\s+(\d)\s+(\d)\s+(\d+)\s+(yes|no)$/i);

  if (!match) {
    return ctx.reply('Usage: /expert-scores <id> <understanding 1-5> <confidence 1-5> <hit rate 0-100> <bullshit yes/no>');
  }

  const [, idStr, understanding, confidence, hitRate, bullshit] = match;
  const id = parseInt(idStr);

  await prisma.expertBriefing.update({
    where: { id },
    data: {
      understandingScore: parseInt(understanding),
      ownerConfidence: parseInt(confidence),
      questionsHitRate: parseInt(hitRate) / 100,
      bullshitDetected: bullshit.toLowerCase() === 'yes'
    }
  });

  return ctx.reply(`✅ Scores recorded for briefing #${id}`);
}

// =============================================================================
// /expert-archive — list/view archived briefings
// =============================================================================

export async function handleExpertArchive(ctx) {
  const arg = ctx.message.text.replace(/^\/expert-archive\s*/i, '').trim();

  if (!arg) {
    // List recent briefings
    const recent = await prisma.expertBriefing.findMany({
      orderBy: { createdAt: 'desc' },
      take: 10
    });

    if (recent.length === 0) return ctx.reply('No briefings in archive yet');

    return ctx.reply(
      `📚 Recent Expert Briefings:\n\n` +
      recent.map(b =>
        `#${b.id} [${b.status}] ${b.topic.substring(0, 60)}\n  ${b.createdAt.toISOString().slice(0, 10)}`
      ).join('\n\n')
    );
  }

  // View specific briefing
  const id = parseInt(arg);
  const briefing = await prisma.expertBriefing.findUnique({ where: { id } });
  if (!briefing) return ctx.reply(`Briefing #${id} not found`);

  // Format briefing summary
  let output = `📋 Expert Briefing #${id}\n\n`;
  output += `Topic: ${briefing.topic}\n`;
  output += `Status: ${briefing.status}\n`;
  output += `Depth: Level ${briefing.depthLevel}\n`;
  if (briefing.meetingDate) output += `Meeting: ${briefing.meetingDate.toISOString().slice(0, 16)}\n`;
  output += `\n`;

  if (briefing.briefingDocument) {
    output += `📄 Briefing document:\n${briefing.briefingDocument.substring(0, 1500)}...\n\n`;
  }

  if (briefing.combatQuestions) {
    output += `🎯 Combat questions:\n${briefing.combatQuestions.substring(0, 1500)}...\n\n`;
  }

  if (briefing.understandingScore) {
    output += `📊 Performance:\n`;
    output += `  Understanding: ${briefing.understandingScore}/5\n`;
    output += `  Confidence: ${briefing.ownerConfidence}/5\n`;
    output += `  Hit rate: ${(briefing.questionsHitRate * 100).toFixed(0)}%\n`;
    output += `  Bullshit detected: ${briefing.bullshitDetected ? 'yes' : 'no'}\n`;
  }

  return ctx.reply(output);
}

// =============================================================================
// /expert-stats — overall Expert department metrics
// =============================================================================

export async function handleExpertStats(ctx) {
  const total = await prisma.expertBriefing.count();
  const debriefed = await prisma.expertBriefing.count({ where: { status: 'debriefed' } });

  const ratedBriefings = await prisma.expertBriefing.findMany({
    where: { understandingScore: { not: null } }
  });

  const avgUnderstanding = ratedBriefings.length > 0
    ? ratedBriefings.reduce((sum, b) => sum + (b.understandingScore || 0), 0) / ratedBriefings.length
    : 0;

  const avgConfidence = ratedBriefings.length > 0
    ? ratedBriefings.reduce((sum, b) => sum + (b.ownerConfidence || 0), 0) / ratedBriefings.length
    : 0;

  const avgHitRate = ratedBriefings.length > 0
    ? ratedBriefings.reduce((sum, b) => sum + (b.questionsHitRate || 0), 0) / ratedBriefings.length
    : 0;

  const bullshitDetectionRate = ratedBriefings.length > 0
    ? ratedBriefings.filter(b => b.bullshitDetected).length / ratedBriefings.length
    : 0;

  return ctx.reply(
    `📊 Expert Department Stats\n\n` +
    `Total briefings: ${total}\n` +
    `Debriefed: ${debriefed}\n` +
    `\n` +
    `Average ratings (n=${ratedBriefings.length}):\n` +
    `Understanding: ${avgUnderstanding.toFixed(1)}/5\n` +
    `Owner confidence: ${avgConfidence.toFixed(1)}/5\n` +
    `Question hit rate: ${(avgHitRate * 100).toFixed(0)}%\n` +
    `Bullshit detection: ${(bullshitDetectionRate * 100).toFixed(0)}%`
  );
}

// =============================================================================
// Registration helper for bot.js
// =============================================================================

export function registerExpertCommands(bot) {
  bot.command('expert', handleExpert);
  bot.command('quickexpert', handleQuickExpert);
  bot.command('deepexpert', handleDeepExpert);
  bot.command('confirm-deepexpert', handleConfirmDeepExpert);
  bot.command('expert-update', handleExpertUpdate);
  bot.command('expert-followup', handleExpertFollowup);
  bot.command('expert-debrief', handleExpertDebrief);
  bot.command('expert-rate', handleExpertRate);
  bot.command('expert-scores', handleExpertScores);
  bot.command('expert-archive', handleExpertArchive);
  bot.command('expert-stats', handleExpertStats);

  console.log('[bot] Expert department v4.1 commands registered');
}
