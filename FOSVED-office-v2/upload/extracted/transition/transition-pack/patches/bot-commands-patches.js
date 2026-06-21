// PATCH for bot.js — new command handlers for Fosved Office v4
// Adds commands for: Кузница (arsenal/paradigm/skill management), Лаборатория знаний,
// expanded ОСП commands, Yana orchestration commands.
//
// Apply by importing into existing bot.js and registering with Telegram bot framework

import { prisma } from './lib/prisma.js';
import { sendTelegramMessage } from './lib/telegram.js';

// =============================================================================
// ОСП — adaptive depth commands
// =============================================================================

// /analyze <topic> — auto-determined depth
export async function handleAnalyze(ctx) {
  const topic = ctx.message.text.replace(/^\/analyze\s+/i, '').trim();
  if (!topic) {
    return ctx.reply('Usage: /analyze <topic>');
  }

  // Auto-determine depth based on triggers
  const depthLevel = await determineDepth(topic, ctx.from.id);

  return runDeconstruction(ctx, topic, depthLevel);
}

// /quickanalyze — force level 0
export async function handleQuickAnalyze(ctx) {
  const topic = ctx.message.text.replace(/^\/quickanalyze\s+/i, '').trim();
  if (!topic) return ctx.reply('Usage: /quickanalyze <topic>');
  return runDeconstruction(ctx, topic, 0);
}

// /wargame — force level 2
export async function handleWargame(ctx) {
  const topic = ctx.message.text.replace(/^\/wargame\s+/i, '').trim();
  if (!topic) return ctx.reply('Usage: /wargame <topic>');
  return runDeconstruction(ctx, topic, 2);
}

// /deep — force level 3
export async function handleDeep(ctx) {
  const topic = ctx.message.text.replace(/^\/deep\s+/i, '').trim();
  if (!topic) return ctx.reply('Usage: /deep <topic>');
  return runDeconstruction(ctx, topic, 3);
}

// /full — force level 4 (requires confirmation due to cost)
export async function handleFull(ctx) {
  const topic = ctx.message.text.replace(/^\/full\s+/i, '').trim();
  if (!topic) return ctx.reply('Usage: /full <topic>');

  // Confirmation required for level 4
  await ctx.reply(
    `⚠️ Full intelligence operation (level 4) on:\n"${topic}"\n\n` +
    `This will activate:\n` +
    `• All Tier 1, Tier 2, Tier 3 skills\n` +
    `• Deep profiling of decision-makers\n` +
    `• Dark web research if relevant\n` +
    `• Multi-day research effort\n\n` +
    `Reply "/confirm-full ${topic}" to proceed.`
  );
}

export async function handleConfirmFull(ctx) {
  const topic = ctx.message.text.replace(/^\/confirm-full\s+/i, '').trim();
  return runDeconstruction(ctx, topic, 4);
}

async function determineDepth(topic, userId) {
  // Check active watchlist
  const watchlistMatch = await prisma.watchlistScenario.findFirst({
    where: {
      OR: [
        { scenarioName: { contains: topic.toLowerCase() } },
        { scenarioDescription: { contains: topic.toLowerCase() } }
      ],
      alertLevel: { in: ['orange', 'red', 'yellow'] }
    }
  });

  if (watchlistMatch && ['orange', 'red'].includes(watchlistMatch.alertLevel)) {
    return 3; // Deep dive for active alerts
  }

  // Check for recent misses on similar topic
  const recentMisses = await prisma.analysis.count({
    where: {
      topic: { contains: topic.substring(0, 30) },
      status: 'missed',
      createdAt: { gte: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000) }
    }
  });

  if (recentMisses >= 2) {
    return 2; // Wargame for repeated misses
  }

  // High-stakes keywords
  const highStakesPatterns = ['критично', 'важно решить', 'крупная сумма', 'инвестиция', 'critical', 'urgent'];
  if (highStakesPatterns.some(p => topic.toLowerCase().includes(p))) {
    return 3;
  }

  // Default
  return 1;
}

async function runDeconstruction(ctx, topic, depthLevel) {
  await ctx.reply(`🔬 Препарирование уровня ${depthLevel}\n"${topic}"\n\nЗапускаю протокол...`);

  // Create analysis record
  const analysis = await prisma.analysis.create({
    data: {
      topic,
      depthLevel,
      status: 'drafted'
    }
  });

  // Trigger deconstruction skill (real implementation invokes skill execution)
  // This is the entry point; actual phase execution happens in skill orchestration
  console.log(`[deconstruct] Started analysis #${analysis.id} for "${topic}" at depth ${depthLevel}`);

  return analysis;
}

// =============================================================================
// ОСП — verification commands
// =============================================================================

export async function handleVerify(ctx) {
  const args = ctx.message.text.replace(/^\/verify\s+/i, '').trim();
  const analysisId = parseInt(args);
  if (!analysisId) return ctx.reply('Usage: /verify <analysis_id>');

  const analysis = await prisma.analysis.findUnique({ where: { id: analysisId } });
  if (!analysis) return ctx.reply(`Analysis #${analysisId} not found`);

  // Trigger verification process
  await ctx.reply(`🔍 Verifying analysis #${analysisId}: "${analysis.topic}"\n\nRetrieving indicators...`);
  // Real implementation: retrieve indicators, check outcomes, compute Brier, categorize errors
}

export async function handleScore(ctx) {
  const dept = ctx.message.text.replace(/^\/score\s*/i, '').trim() || 'osp';

  const recent = await prisma.monthlyReview.findFirst({
    where: { department: dept },
    orderBy: { createdAt: 'desc' }
  });

  if (!recent) return ctx.reply(`No reviews yet for ${dept}`);

  return ctx.reply(
    `📊 ${dept.toUpperCase()} Score Report\n` +
    `Period: ${recent.period}\n` +
    `Metric: ${recent.primaryMetricName} = ${recent.primaryMetric?.toFixed(3) || 'N/A'}\n` +
    `Trend: ${recent.metricTrend}\n` +
    (recent.improvements ? `\nImprovements identified:\n${recent.improvements}` : '')
  );
}

// =============================================================================
// ОСП — watchlist commands
// =============================================================================

export async function handleWatchlist(ctx) {
  const text = ctx.message.text.replace(/^\/watchlist\s*/i, '').trim();
  const [subcommand, ...rest] = text.split(/\s+/);

  if (subcommand === 'add') {
    const scenarioName = rest.join(' ');
    if (!scenarioName) return ctx.reply('Usage: /watchlist add <scenario name>');

    const scenario = await prisma.watchlistScenario.create({
      data: {
        scenarioName,
        scenarioDescription: scenarioName,
        threshold: 'TO_BE_DEFINED',
        alertThresholds: JSON.stringify({}),
        createdBy: 'owner'
      }
    });

    return ctx.reply(
      `✅ Added scenario #${scenario.id}: "${scenarioName}"\n` +
      `Status: monitoring\n\n` +
      `Next steps:\n` +
      `• Define indicators at T-30/60/90/180/365\n` +
      `• Set alert thresholds\n` +
      `• Reply with details or use /watchlist edit ${scenario.id}`
    );
  }

  if (subcommand === 'remove') {
    const id = parseInt(rest[0]);
    if (!id) return ctx.reply('Usage: /watchlist remove <id>');
    await prisma.watchlistScenario.update({
      where: { id },
      data: { alertLevel: 'retired', retiredAt: new Date() }
    });
    return ctx.reply(`Scenario #${id} retired`);
  }

  // Default: status
  const active = await prisma.watchlistScenario.findMany({
    where: { alertLevel: { in: ['monitoring', 'yellow', 'orange', 'red'] } },
    orderBy: { alertLevel: 'desc' }
  });

  if (active.length === 0) return ctx.reply('No active watchlist scenarios');

  const summary = active.map(s =>
    `${alertEmoji(s.alertLevel)} #${s.id}: ${s.scenarioName} (${s.alertLevel})`
  ).join('\n');

  return ctx.reply(`📋 Active Watchlist:\n\n${summary}`);
}

function alertEmoji(level) {
  return { red: '🔴', orange: '🟠', yellow: '🟡', monitoring: '⚪' }[level] || '⚪';
}

export async function handleRecommend(ctx) {
  const category = ctx.message.text.replace(/^\/recommend\s*/i, '').trim();
  if (!category) return ctx.reply('Usage: /recommend <category>\nExamples: defense, energy, AI infrastructure');

  // Real implementation:
  // 1. Find recent ОСП analyses related to category
  // 2. Extract fruits from those analyses
  // 3. Run asymmetric-bet-structure on highest-conviction fruits
  // 4. Return actionable recommendations

  return ctx.reply(
    `💡 Recommendations for ${category}\n\n` +
    `(Searching recent analyses, fruits, and asymmetric structures...)`
  );
}

// =============================================================================
// Лаборатория знаний commands
// =============================================================================

export async function handleScan(ctx) {
  const text = ctx.message.text.replace(/^\/scan\s*/i, '').trim();
  const [first, ...rest] = text.split(/\s+/);

  let domain;
  let deep = false;

  if (first === 'deep') {
    deep = true;
    domain = rest.join(' ');
  } else {
    domain = text;
  }

  if (!domain) return ctx.reply('Usage: /scan <domain> or /scan deep <domain>');

  await ctx.reply(`🔬 Scanning ${domain}${deep ? ' (deep)' : ''}...`);

  // Real implementation: scan KnowledgeArtifacts in domain, return summary
  const artifacts = await prisma.knowledgeArtifact.findMany({
    where: { domain: { contains: domain.toLowerCase() } },
    orderBy: { disruptionScore: 'desc' },
    take: deep ? 20 : 10
  });

  if (artifacts.length === 0) {
    return ctx.reply(`No tracked artifacts in domain "${domain}". Use /lab-watch add to start tracking.`);
  }

  const summary = artifacts.map(a =>
    `• ${a.technology} (${a.hypeCycleStage || 'unknown'}, score: ${a.disruptionScore?.toFixed(1) || 'N/A'})`
  ).join('\n');

  return ctx.reply(`📊 ${domain.toUpperCase()} scan:\n\n${summary}`);
}

export async function handleDisrupt(ctx) {
  const tech = ctx.message.text.replace(/^\/disrupt\s+/i, '').trim();
  if (!tech) return ctx.reply('Usage: /disrupt <technology>');

  const artifact = await prisma.knowledgeArtifact.findFirst({
    where: { technology: { contains: tech } },
    orderBy: { updatedAt: 'desc' }
  });

  if (!artifact) {
    await ctx.reply(`No tracked artifact for "${tech}". Running fresh disruption scoring analysis...`);
    // Real implementation: trigger disruption-scoring skill on this technology
    return;
  }

  return ctx.reply(
    `📊 ${artifact.technology}\n\n` +
    `Hype cycle: ${artifact.hypeCycleStage}\n` +
    `Disruption score: ${artifact.disruptionScore?.toFixed(1)}\n\n` +
    `Components:\n` +
    `• Performance ratio: ${artifact.performanceRatio || 'N/A'}\n` +
    `• Cost trajectory: ${artifact.costTrajectory || 'N/A'}\n` +
    `• Patent activity: ${artifact.patentActivity || 'N/A'}\n` +
    `• Talent flow: ${artifact.talentFlow || 'N/A'}\n` +
    `• Investment: ${artifact.investmentPatterns || 'N/A'}\n\n` +
    `Time horizons:\n` +
    `• 1y: ${(artifact.disruption1Year * 100).toFixed(0)}%\n` +
    `• 3y: ${(artifact.disruption3Year * 100).toFixed(0)}%\n` +
    `• 5y: ${(artifact.disruption5Year * 100).toFixed(0)}%\n` +
    `• 10y: ${(artifact.disruption10Year * 100).toFixed(0)}%`
  );
}

export async function handleInflection(ctx) {
  const candidates = await prisma.knowledgeArtifact.findMany({
    where: {
      inflectionStage: { in: ['early_inflection', 'active'] },
      status: { in: ['tracking', 'hot'] }
    },
    orderBy: { disruptionScore: 'desc' }
  });

  if (candidates.length === 0) {
    return ctx.reply('No technologies currently approaching inflection');
  }

  const summary = candidates.map(c =>
    `🎯 ${c.technology}\n` +
    `  Stage: ${c.inflectionStage}\n` +
    `  Score: ${c.disruptionScore?.toFixed(1)}\n` +
    `  Domain: ${c.domain}`
  ).join('\n\n');

  return ctx.reply(`Inflection candidates:\n\n${summary}`);
}

// =============================================================================
// Кузница — new commands for arsenal review and skill management
// =============================================================================

export async function handleArsenalReview(ctx) {
  await ctx.reply('🔧 Initiating manual arsenal review...');

  // Trigger handler from scheduler
  const { runArsenalReview } = await import('../scheduler/handlers-patches.js');
  const period = `${new Date().getFullYear()}-Manual-${Date.now()}`;
  const review = await runArsenalReview(period);

  return ctx.reply(`Arsenal review #${review.id} created. Report sent.`);
}

export async function handleArsenalReviewStatus(ctx) {
  const id = parseInt(ctx.message.text.replace(/^\/arsenal-review-status\s+/i, '').trim());
  if (!id) return ctx.reply('Usage: /arsenal-review-status <id>');

  const review = await prisma.arsenalReview.findUnique({ where: { id } });
  if (!review) return ctx.reply(`Review #${id} not found`);

  return ctx.reply(
    `Arsenal Review #${id}\n` +
    `Period: ${review.period}\n` +
    `Status: ${review.status}\n\n` +
    `${review.ownerReport || 'Report pending'}`
  );
}

export async function handleSkillDeprecate(ctx) {
  const skillName = ctx.message.text.replace(/^\/skill-deprecate\s+/i, '').trim();
  if (!skillName) return ctx.reply('Usage: /skill-deprecate <skill-name>');

  // Move skill to _archive/ folder
  const fs = await import('fs/promises');
  const path = await import('path');

  const [dept, skill] = skillName.split('/');
  if (!dept || !skill) return ctx.reply('Format: <dept>/<skill-name>');

  const sourcePath = path.join(process.cwd(), 'skills', 'fosved', dept, skill);
  const archivePath = path.join(process.cwd(), 'skills', 'fosved', '_archive', `${dept}_${skill}_${Date.now()}`);

  try {
    await fs.mkdir(path.dirname(archivePath), { recursive: true });
    await fs.rename(sourcePath, archivePath);

    return ctx.reply(
      `✅ Deprecated: ${skillName}\n` +
      `Moved to: _archive/${path.basename(archivePath)}\n\n` +
      `Remember to update SKILLS_MAP in army.js to remove reference.`
    );
  } catch (err) {
    return ctx.reply(`Error deprecating skill: ${err.message}`);
  }
}

export async function handleSkillEvolve(ctx) {
  const args = ctx.message.text.replace(/^\/skill-evolve\s+/i, '').trim();
  const [skillName, ...rationale] = args.split(/\s+/);

  if (!skillName) return ctx.reply('Usage: /skill-evolve <skill-name> [rationale]');

  // Triggers a skill review by the Forge
  const session = await prisma.trainingSession.create({
    data: {
      type: 'recalibrate',
      targetDept: skillName.split('/')[0],
      checklistResults: JSON.stringify({
        action: 'skill_evolution',
        target_skill: skillName,
        rationale: rationale.join(' ') || 'Owner-initiated evolution'
      }),
      status: 'in_progress'
    }
  });

  return ctx.reply(
    `🔄 Skill evolution initiated for ${skillName}\n` +
    `Session #${session.id}\n\n` +
    `Forge will analyze current skill, recent usage patterns, and propose updated version.`
  );
}

export async function handleSkillStats(ctx) {
  const { computeSkillUtilization } = await import('../scheduler/handlers-patches.js');
  const stats = await computeSkillUtilization();

  if (stats.length === 0) {
    return ctx.reply('No skill usage data yet');
  }

  const sorted = stats.sort((a, b) => b.use_count_last_year - a.use_count_last_year);
  const summary = sorted.slice(0, 20).map(s =>
    `${s.name}: ${s.use_count_last_year} uses, fail rate ${(s.fail_rate * 100).toFixed(0)}%`
  ).join('\n');

  return ctx.reply(`📊 Top 20 skills by usage:\n\n${summary}`);
}

export async function handleParadigmReview(ctx) {
  const id = parseInt(ctx.message.text.replace(/^\/paradigm-review\s*/i, '').trim());

  if (!id) {
    // Show pending paradigm review if any
    const pending = await prisma.paradigmReview.findFirst({
      where: { status: 'awaiting_owner_session' },
      orderBy: { createdAt: 'desc' }
    });

    if (!pending) return ctx.reply('No pending paradigm reviews. Use /paradigm-review-init to start.');

    return ctx.reply(
      `📋 Pending Paradigm Review for ${pending.year}\n\n` +
      `Hits: ${JSON.parse(pending.hits || '[]').length}\n` +
      `Misses: ${JSON.parse(pending.misses || '[]').length}\n` +
      `Surprises: ${JSON.parse(pending.surprises || '[]').length}\n\n` +
      `Use /paradigm-review ${pending.id} to start owner session\n` +
      `This is a multi-step process — block 1-2 hours for full discussion.`
    );
  }

  // Owner is starting the session for review #id
  const review = await prisma.paradigmReview.findUnique({ where: { id } });
  if (!review) return ctx.reply(`Review #${id} not found`);

  return ctx.reply(
    `📋 Paradigm Review #${id} (${review.year}) — Session start\n\n` +
    `This review covers:\n` +
    `1. Six core principles (still valid?)\n` +
    `2. Department architecture (additions/retirements?)\n` +
    `3. Year debrief (hits/misses/surprises/learnings)\n` +
    `4. Methodology evolution (paradigm shifts needed?)\n\n` +
    `Reply with discussion notes; I'll structure into review document for your approval.\n` +
    `Use /paradigm-finalize ${id} when ready to produce ARCHITECTURE.md update.`
  );
}

export async function handleArchitectureUpdate(ctx) {
  const desc = ctx.message.text.replace(/^\/architecture-update\s+/i, '').trim();
  if (!desc) return ctx.reply('Usage: /architecture-update <description of proposed change>');

  // Architecture changes require owner approval and impact entire system
  return ctx.reply(
    `⚠️ Proposed ARCHITECTURE.md update:\n\n"${desc}"\n\n` +
    `This change requires:\n` +
    `1. Detailed proposal documenting impact\n` +
    `2. Owner approval\n` +
    `3. Coordination with all affected departments\n` +
    `4. Update to METHODOLOGY.md if principles affected\n\n` +
    `Reply "/confirm-architecture-update" to proceed with proposal generation.`
  );
}

export async function handleMethodologyVersion(ctx) {
  // Returns current methodology version and recent changes
  const recentArsenalReviews = await prisma.arsenalReview.findMany({
    orderBy: { createdAt: 'desc' },
    take: 3
  });

  const recentParadigmReviews = await prisma.paradigmReview.findMany({
    orderBy: { createdAt: 'desc' },
    take: 2
  });

  return ctx.reply(
    `📚 Methodology Status\n\n` +
    `Current version: 1.0 (May 2026)\n` +
    `Last paradigm review: ${recentParadigmReviews[0]?.year || 'never'}\n` +
    `Last arsenal review: ${recentArsenalReviews[0]?.period || 'never'}\n\n` +
    `Recent arsenal reviews:\n` +
    recentArsenalReviews.map(r => `• ${r.period} (${r.status})`).join('\n') +
    `\n\nRecent paradigm reviews:\n` +
    recentParadigmReviews.map(r => `• ${r.year} (approved: ${r.ownerApproved})`).join('\n')
  );
}

export async function handleForgeStatus(ctx) {
  const activeSessions = await prisma.trainingSession.findMany({
    where: { status: 'in_progress' },
    orderBy: { createdAt: 'desc' }
  });

  const recentArsenal = await prisma.arsenalReview.findFirst({
    orderBy: { createdAt: 'desc' }
  });

  const departmentsAtRisk = await prisma.monthlyReview.findMany({
    where: { metricTrend: 'deteriorating' },
    orderBy: { createdAt: 'desc' },
    distinct: ['department'],
    take: 10
  });

  return ctx.reply(
    `🔧 Forge Status\n\n` +
    `Active training sessions: ${activeSessions.length}\n` +
    `${activeSessions.map(s => `  • ${s.type} for ${s.targetDept}`).join('\n') || '(none)'}\n\n` +
    `Last arsenal review: ${recentArsenal?.period || 'never'} (${recentArsenal?.status || 'N/A'})\n\n` +
    `Departments showing deterioration:\n` +
    `${departmentsAtRisk.map(r => `  • ${r.department} (${r.period})`).join('\n') || '(none)'}\n\n` +
    `Use /debrief <dept> to investigate; /recalibrate-dept <dept> for full retraining (owner approval required).`
  );
}

// =============================================================================
// Yana — orchestration commands
// =============================================================================

export async function handleRoute(ctx) {
  const query = ctx.message.text.replace(/^\/route\s+/i, '').trim();
  if (!query) return ctx.reply('Usage: /route <query>');

  // Yana routing logic — return routing decision without executing
  return ctx.reply(`📍 Routing analysis for: "${query}"\n\n[Yana analyzes triggers and recommends routing]`);
}

export async function handleOrchestrate(ctx) {
  const query = ctx.message.text.replace(/^\/orchestrate\s+/i, '').trim();
  if (!query) return ctx.reply('Usage: /orchestrate <query>');

  return ctx.reply(`🔀 Multi-department orchestration for: "${query}"\n\n[Yana identifies relevant departments and coordinates parallel work]`);
}

export async function handleYanaStatus(ctx) {
  // Cross-departmental status
  const recentReviews = await prisma.monthlyReview.findMany({
    where: {
      createdAt: { gte: new Date(Date.now() - 35 * 24 * 60 * 60 * 1000) }
    },
    orderBy: { createdAt: 'desc' },
    distinct: ['department']
  });

  const summary = recentReviews.map(r =>
    `${trendEmoji(r.metricTrend)} ${r.department}: ${r.primaryMetricName} = ${r.primaryMetric?.toFixed(3) || 'N/A'} (${r.metricTrend})`
  ).join('\n');

  return ctx.reply(`📊 Office Status (Yana view):\n\n${summary}`);
}

function trendEmoji(trend) {
  return { improving: '📈', deteriorating: '📉', stable: '➡️' }[trend] || '❓';
}

// =============================================================================
// Registration helper for bot.js
// =============================================================================

export function registerV4Commands(bot) {
  // ОСП adaptive depth
  bot.command('analyze', handleAnalyze);
  bot.command('quickanalyze', handleQuickAnalyze);
  bot.command('wargame', handleWargame);
  bot.command('deep', handleDeep);
  bot.command('full', handleFull);
  bot.command('confirm-full', handleConfirmFull);

  // ОСП verification & monitoring
  bot.command('verify', handleVerify);
  bot.command('score', handleScore);
  bot.command('watchlist', handleWatchlist);
  bot.command('recommend', handleRecommend);

  // Лаборатория знаний
  bot.command('scan', handleScan);
  bot.command('disrupt', handleDisrupt);
  bot.command('inflection', handleInflection);

  // Кузница — new arsenal/paradigm management
  bot.command('arsenal-review', handleArsenalReview);
  bot.command('arsenal-review-status', handleArsenalReviewStatus);
  bot.command('skill-deprecate', handleSkillDeprecate);
  bot.command('skill-evolve', handleSkillEvolve);
  bot.command('skill-stats', handleSkillStats);
  bot.command('paradigm-review', handleParadigmReview);
  bot.command('architecture-update', handleArchitectureUpdate);
  bot.command('methodology-version', handleMethodologyVersion);
  bot.command('forge-status', handleForgeStatus);

  // Yana orchestration
  bot.command('route', handleRoute);
  bot.command('orchestrate', handleOrchestrate);
  bot.command('yana-status', handleYanaStatus);

  console.log('[bot] Fosved Office v4 commands registered');
}
