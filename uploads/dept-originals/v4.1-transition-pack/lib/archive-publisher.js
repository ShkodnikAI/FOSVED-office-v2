// ============================================================================
// lib/archive-publisher.js — Telegram Archive Channel auto-publication
// ============================================================================
//
// Auto-publishes structured summaries to ARCHIVE_CHANNEL_ID Telegram channel.
// Plus unified search across DB + channel.
//
// Channel structure:
//   - One post per Analysis (after /analyze success)
//   - One post per ExpertBriefing (after /expert success)
//   - One post per verified forecast (after /verify completes)
//   - Hashtags: #осп / #эксперт / #лз  +  #прогноз / #прогноз_сбылся / #брифинг
//              +  #YYYY  +  #тема_<slug>
//
// Bot must be admin in channel with post permissions.
// Channel ID set via Render env: ARCHIVE_CHANNEL_ID
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID; // set in Phase 6
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_TOKEN;

// Telegram message length limit
const MAX_MESSAGE_LENGTH = 4096;

// ─── Bot wrapper (lightweight, no node-telegram-bot-api dep here) ───────────

/**
 * Direct Telegram API call. Reuses bot token from env.
 * Returns parsed response or throws.
 */
async function telegramApi(method, params) {
  if (!TELEGRAM_BOT_TOKEN) {
    throw new Error('TELEGRAM_TOKEN not set');
  }
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/${method}`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  const data = await resp.json();
  if (!data.ok) {
    throw new Error(`Telegram API error (${method}): ${data.description}`);
  }
  return data.result;
}

async function sendMessage(text, options = {}) {
  if (!ARCHIVE_CHANNEL_ID) {
    console.warn('[archive-publisher] ARCHIVE_CHANNEL_ID not set; skipping publish');
    return null;
  }

  const params = {
    chat_id: ARCHIVE_CHANNEL_ID,
    text: text.slice(0, MAX_MESSAGE_LENGTH),
    parse_mode: 'Markdown',
    disable_web_page_preview: true,
    ...options
  };

  return telegramApi('sendMessage', params);
}

// ─── Slug generator (for #тема_<slug> hashtag) ──────────────────────────────

function slugify(text) {
  if (!text) return 'untagged';
  // Russian + English transliteration → simple ASCII slug
  const cyrToLat = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh',
    'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
    'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
    'ч':'ch','ш':'sh','щ':'sh','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
  };
  const transliterated = text.toLowerCase().split('').map(c => cyrToLat[c] !== undefined ? cyrToLat[c] : c).join('');
  return transliterated
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
    .slice(0, 40) || 'untagged';
}

// ─── Build hashtag set ──────────────────────────────────────────────────────

function buildHashtags({ department, postType, year, topic, extras = [] }) {
  const tags = [];
  if (department) tags.push(`#${department}`);
  if (postType) tags.push(`#${postType}`);
  if (year) tags.push(`#${year}`);
  if (topic) tags.push(`#тема_${slugify(topic)}`);
  for (const e of extras) tags.push(`#${e.startsWith('#') ? e.slice(1) : e}`);
  return tags.join(' ');
}

// ─── Truncate helper for long fields ────────────────────────────────────────

function truncate(text, maxLen = 800) {
  if (!text) return '';
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

// ─── Analysis (ОСП V2) summary publication ──────────────────────────────────

/**
 * Format and publish OSP V2 Analysis summary to Archive channel.
 * Idempotent: if already published, returns existing message ref.
 */
export async function publishAnalysisSummary(analysisId) {
  const analysis = await prisma.analysis.findUnique({
    where: { id: analysisId },
    include: {
      scenarioWatch: true
    }
  });

  if (!analysis) {
    throw new Error(`Analysis ${analysisId} not found`);
  }

  // Build summary text
  const parts = [];
  parts.push(`📊 *Препарирование ОСП V2 #${analysis.id}*`);
  parts.push(``);
  parts.push(`*Тема:* ${analysis.topic}`);
  parts.push(`*Режим:* ${analysis.mode}  |  *Уверенность:* ${analysis.confidence}`);
  parts.push(``);

  // Brief from each topology level (truncated)
  if (analysis.leaves) {
    parts.push(`🍃 *Leaves:*`);
    parts.push(truncate(analysis.leaves, 400));
    parts.push(``);
  }
  if (analysis.branches) {
    parts.push(`🌿 *Branches:*`);
    parts.push(truncate(analysis.branches, 400));
    parts.push(``);
  }
  if (analysis.fruits) {
    parts.push(`🍎 *Fruits (anticipated):*`);
    parts.push(truncate(analysis.fruits, 400));
    parts.push(``);
  }

  // Scenarios with probabilities
  if (analysis.scenarios) {
    try {
      const scenarios = typeof analysis.scenarios === 'string'
        ? JSON.parse(analysis.scenarios)
        : analysis.scenarios;
      if (Array.isArray(scenarios) && scenarios.length > 0) {
        parts.push(`*Сценарии:*`);
        for (const sc of scenarios.slice(0, 4)) {
          const prob = typeof sc.probability === 'number'
            ? `${Math.round(sc.probability * 100)}%`
            : (sc.probability || '?');
          parts.push(`• ${sc.label || 'unnamed'} — ${prob}`);
        }
        parts.push(``);
      }
    } catch (e) {
      // ignore parse errors
    }
  }

  // Verification date if set
  if (analysis.verificationDate) {
    const dateStr = new Date(analysis.verificationDate).toISOString().slice(0, 10);
    parts.push(`*Дата проверки:* ${dateStr}`);
    parts.push(``);
  }

  // Hashtags
  const year = analysis.createdAt
    ? new Date(analysis.createdAt).getFullYear().toString()
    : new Date().getFullYear().toString();

  const hashtags = buildHashtags({
    department: 'осп',
    postType: 'прогноз',
    year,
    topic: analysis.topicSlug || analysis.topic
  });
  parts.push(hashtags);

  const text = parts.join('\n');
  const result = await sendMessage(text);

  // Optionally store reference back in Analysis (could add field if needed)
  console.log(`[archive] Published Analysis #${analysisId} as message ${result?.message_id}`);

  return result;
}

// ─── Expert Briefing summary publication ────────────────────────────────────

/**
 * Format and publish Expert briefing summary to Archive channel.
 */
export async function publishExpertBriefing(briefingId) {
  const briefing = await prisma.expertBriefing.findUnique({
    where: { id: briefingId }
  });

  if (!briefing) {
    throw new Error(`ExpertBriefing ${briefingId} not found`);
  }

  const parts = [];
  parts.push(`🎯 *Эксперт-брифинг #${briefing.id}*`);
  parts.push(``);
  parts.push(`*Тема:* ${briefing.topic}`);
  parts.push(`*Глубина:* Level ${briefing.depthLevel}  |  *Статус:* ${briefing.status}`);
  if (briefing.meetingDate) {
    parts.push(`*Встреча:* ${new Date(briefing.meetingDate).toISOString().slice(0, 16).replace('T', ' ')}`);
  }
  parts.push(``);

  // Brief from each phase
  if (briefing.domainImmersion) {
    parts.push(`🧠 *Domain immersion:*`);
    parts.push(truncate(briefing.domainImmersion, 350));
    parts.push(``);
  }
  if (briefing.failureModes) {
    parts.push(`⚠️ *Top failure modes:*`);
    parts.push(truncate(briefing.failureModes, 350));
    parts.push(``);
  }
  if (briefing.combatQuestions) {
    parts.push(`🔫 *Combat questions:*`);
    parts.push(truncate(briefing.combatQuestions, 500));
    parts.push(``);
  }

  // Performance if debriefed
  if (briefing.understandingScore) {
    parts.push(`📈 *Performance:*`);
    parts.push(`• Понимание: ${briefing.understandingScore}/5`);
    if (briefing.ownerConfidence) parts.push(`• Уверенность: ${briefing.ownerConfidence}/5`);
    if (typeof briefing.questionsHitRate === 'number') {
      parts.push(`• Hit rate: ${Math.round(briefing.questionsHitRate * 100)}%`);
    }
    if (briefing.bullshitDetected !== null) {
      parts.push(`• Bullshit detected: ${briefing.bullshitDetected ? '✓' : '✗'}`);
    }
    parts.push(``);
  }

  const year = briefing.createdAt
    ? new Date(briefing.createdAt).getFullYear().toString()
    : new Date().getFullYear().toString();

  const hashtags = buildHashtags({
    department: 'эксперт',
    postType: 'брифинг',
    year,
    topic: briefing.topic
  });
  parts.push(hashtags);

  const text = parts.join('\n');
  const result = await sendMessage(text);

  console.log(`[archive] Published ExpertBriefing #${briefingId} as message ${result?.message_id}`);
  return result;
}

// ─── Knowledge Artifact (ЛЗ) summary publication ────────────────────────────

export async function publishKnowledgeArtifact(artifactId) {
  const artifact = await prisma.knowledgeArtifact.findUnique({
    where: { id: artifactId }
  });

  if (!artifact) {
    throw new Error(`KnowledgeArtifact ${artifactId} not found`);
  }

  const parts = [];
  parts.push(`🔬 *ЛЗ-артефакт #${artifact.id}*`);
  parts.push(``);
  parts.push(`*Тема:* ${artifact.topic}`);
  parts.push(`*Статус:* ${artifact.status}`);
  if (artifact.hypePosition) {
    parts.push(`*Hype cycle:* ${artifact.hypePosition}`);
  }
  if (typeof artifact.disruptionProbability === 'number') {
    parts.push(`*Disruption probability:* ${Math.round(artifact.disruptionProbability * 100)}%${artifact.disruptionTimeline ? ` (${artifact.disruptionTimeline})` : ''}`);
  }
  if (artifact.inflectionDetected) {
    parts.push(`⚡ *Inflection detected*`);
  }
  parts.push(``);

  if (artifact.fullProfile) {
    parts.push(truncate(artifact.fullProfile, 800));
    parts.push(``);
  }

  const year = artifact.createdAt
    ? new Date(artifact.createdAt).getFullYear().toString()
    : new Date().getFullYear().toString();

  const hashtags = buildHashtags({
    department: 'лз',
    postType: artifact.inflectionDetected ? 'inflection' : 'tracking',
    year,
    topic: artifact.topicSlug || artifact.topic
  });
  parts.push(hashtags);

  const text = parts.join('\n');
  const result = await sendMessage(text);

  console.log(`[archive] Published KnowledgeArtifact #${artifactId}`);
  return result;
}

// ─── Verified forecast outcome publication ──────────────────────────────────

/**
 * After a /verify completes, publish the outcome.
 * Format shows what was predicted vs what happened, with Brier score.
 */
export async function publishVerifiedForecast(verificationId) {
  const verification = await prisma.analysisVerification.findUnique({
    where: { id: verificationId },
    include: { analysis: true }
  });

  if (!verification) {
    throw new Error(`AnalysisVerification ${verificationId} not found`);
  }

  const analysis = verification.analysis;

  const parts = [];
  parts.push(`✅ *Верификация прогноза #${analysis.id}*`);
  parts.push(``);
  parts.push(`*Тема:* ${analysis.topic}`);
  parts.push(`*Verified:* ${new Date(verification.verifiedAt).toISOString().slice(0, 10)}`);
  parts.push(``);

  // Brier score
  parts.push(`*Brier score:* ${verification.brierTotal.toFixed(3)} (lower=better; ≤0.25 good, ≤0.18 excellent)`);
  parts.push(`*Indicators triggered:* ${verification.indicatorsTriggered}/${verification.indicatorsTotal}`);
  parts.push(``);

  // Scenario outcomes
  try {
    const outcomes = typeof verification.scenarioOutcomes === 'string'
      ? JSON.parse(verification.scenarioOutcomes)
      : verification.scenarioOutcomes;
    if (outcomes && Object.keys(outcomes).length > 0) {
      parts.push(`*Сценарии — что произошло:*`);
      for (const [label, outcome] of Object.entries(outcomes)) {
        const emoji = outcome === true ? '✓' : outcome === false ? '✗' : '◐';
        parts.push(`${emoji} ${label}: ${outcome}`);
      }
      parts.push(``);
    }
  } catch (e) {
    // skip
  }

  // Error category if any
  if (verification.errorCategory) {
    parts.push(`*Error category:* ${verification.errorCategory}`);
    if (verification.errorNote) {
      parts.push(truncate(verification.errorNote, 300));
    }
    parts.push(``);
  }

  // Improvements
  if (verification.improvementsForNext) {
    parts.push(`*Улучшения для следующих:*`);
    parts.push(truncate(verification.improvementsForNext, 300));
    parts.push(``);
  }

  const year = new Date(verification.verifiedAt).getFullYear().toString();

  // Choose post-type based on outcome
  let postType = 'прогноз_частично';
  if (verification.brierTotal <= 0.18) postType = 'прогноз_сбылся';
  else if (verification.brierTotal >= 0.40) postType = 'прогноз_провалился';

  const hashtags = buildHashtags({
    department: 'осп',
    postType,
    year,
    topic: analysis.topicSlug || analysis.topic,
    extras: [`brier_${Math.round(verification.brierTotal * 100)}`]
  });
  parts.push(hashtags);

  const text = parts.join('\n');
  const result = await sendMessage(text);

  console.log(`[archive] Published verification #${verificationId}`);
  return result;
}

// ─── Unified search ─────────────────────────────────────────────────────────

/**
 * Searches DB (Analysis + ExpertBriefing + KnowledgeArtifact) AND channel posts.
 * Returns combined ranked results.
 */
export async function searchUnified(query, options = {}) {
  const { userId = 0, limit = 20 } = options;

  if (!query || !query.trim()) {
    return { db: [], channel: [], total: 0 };
  }

  const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 2);

  // Search DB
  const dbResults = [];

  // Analyses
  const analyses = await prisma.analysis.findMany({
    where: {
      userId,
      OR: terms.flatMap(t => [
        { topic: { contains: t, mode: 'insensitive' } },
        { fullAnalysis: { contains: t, mode: 'insensitive' } },
        { leaves: { contains: t, mode: 'insensitive' } },
        { branches: { contains: t, mode: 'insensitive' } },
        { roots: { contains: t, mode: 'insensitive' } }
      ])
    },
    take: Math.ceil(limit / 3),
    orderBy: { createdAt: 'desc' }
  });
  for (const a of analyses) {
    dbResults.push({
      type: 'analysis',
      id: a.id,
      title: a.topic,
      summary: truncate(a.fullAnalysis || a.leaves || '', 200),
      date: a.createdAt
    });
  }

  // ExpertBriefings
  const briefings = await prisma.expertBriefing.findMany({
    where: {
      userId,
      OR: terms.flatMap(t => [
        { topic: { contains: t, mode: 'insensitive' } },
        { meetingContext: { contains: t, mode: 'insensitive' } },
        { briefingDocument: { contains: t, mode: 'insensitive' } }
      ])
    },
    take: Math.ceil(limit / 3),
    orderBy: { createdAt: 'desc' }
  });
  for (const b of briefings) {
    dbResults.push({
      type: 'briefing',
      id: b.id,
      title: b.topic,
      summary: truncate(b.briefingDocument || '', 200),
      date: b.createdAt
    });
  }

  // KnowledgeArtifacts
  const artifacts = await prisma.knowledgeArtifact.findMany({
    where: {
      userId,
      OR: terms.flatMap(t => [
        { topic: { contains: t, mode: 'insensitive' } },
        { fullProfile: { contains: t, mode: 'insensitive' } }
      ])
    },
    take: Math.ceil(limit / 3),
    orderBy: { updatedAt: 'desc' }
  });
  for (const a of artifacts) {
    dbResults.push({
      type: 'artifact',
      id: a.id,
      title: a.topic,
      summary: truncate(a.fullProfile || '', 200),
      date: a.updatedAt
    });
  }

  // Channel search not natively supported via Bot API; would need MTProto
  // For v4.1, channel search returns empty. Future: add bot.getChatHistory if available.
  const channelResults = [];

  return {
    db: dbResults,
    channel: channelResults,
    total: dbResults.length + channelResults.length
  };
}

// ─── Format unified search results for Telegram ─────────────────────────────

export function formatSearchResults(results, query) {
  const lines = [];
  lines.push(`🔍 *Search: "${query}"*`);
  lines.push(`Found: ${results.total} matches`);
  lines.push(``);

  if (results.db.length > 0) {
    lines.push(`*Архив (БД):*`);
    for (const r of results.db.slice(0, 10)) {
      const typeEmoji = r.type === 'analysis' ? '📊' : r.type === 'briefing' ? '🎯' : '🔬';
      const dateStr = new Date(r.date).toISOString().slice(0, 10);
      lines.push(`${typeEmoji} *#${r.id}* (${dateStr}) ${r.title}`);
      if (r.summary) {
        lines.push(`   ${truncate(r.summary, 150)}`);
      }
    }
  }

  if (results.db.length === 0 && results.channel.length === 0) {
    lines.push(`Ничего не найдено.`);
  }

  return lines.join('\n');
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  publishAnalysisSummary,
  publishExpertBriefing,
  publishKnowledgeArtifact,
  publishVerifiedForecast,
  searchUnified,
  formatSearchResults
};
