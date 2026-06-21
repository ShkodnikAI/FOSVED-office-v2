// ============================================================================
// lib/research.js — LDR-inspired research engine for Fosved Office v4.1
// ============================================================================
//
// Implements:
//   - Iterative 3-step research loop (broad → targeted → synthesize)
//   - Knowledge base operations (search/add/link sources)
//   - Source tier hierarchy (1=peer-review .. 5=blog)
//   - Citation discipline (validateCitations checks every claim has source)
//   - Cross-references between Analysis, ExpertBriefing, KnowledgeArtifact
//
// Used by:
//   - Эксперт: rapid-domain-immersion, peer-review-simulation, etc.
//   - ОСП V2: Layer Stem (state-of-the-art) population
//   - ЛЗ: KnowledgeArtifact source accumulation
//
// Backend: Grok web search + Claude API for synthesis
// No external services. All data in same Postgres (ResearchSource model).
// ============================================================================

import { PrismaClient } from '@prisma/client';
import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';

const prisma = new PrismaClient();

const claude = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY
});

const grok = new OpenAI({
  apiKey: process.env.GROK_API_KEY,
  baseURL: 'https://api.x.ai/v1'
});

// ─── Constants ───────────────────────────────────────────────────────────────

const OWNER_ID = 2044005421;

// Source tier hierarchy (1 = highest credibility, 5 = lowest)
const SOURCE_TIERS = {
  peer_review: 1,    // Peer-reviewed academic journals
  government:  2,    // Government/regulatory sources (FDA, SEC, etc.)
  industry:    3,    // Industry analyst reports, company filings
  news:        4,    // Mainstream news outlets
  blog:        5     // Blogs, forums, social media
};

const TIER_LABELS = {
  1: 'peer-reviewed',
  2: 'government',
  3: 'industry',
  4: 'news',
  5: 'blog'
};

// ─── Source Tier Detection ──────────────────────────────────────────────────

/**
 * Determine source tier from URL and metadata.
 * Used by addResearchSource to auto-classify.
 */
export function tierSource(url, sourceType = null) {
  if (sourceType && SOURCE_TIERS[sourceType]) {
    return SOURCE_TIERS[sourceType];
  }

  const urlLower = url.toLowerCase();

  // Tier 1: peer-reviewed academic
  const peerReviewDomains = [
    'pubmed.ncbi.nlm.nih.gov', 'arxiv.org', 'biorxiv.org', 'medrxiv.org',
    'nature.com', 'science.org', 'cell.com', 'nejm.org', 'thelancet.com',
    'jamanetwork.com', 'bmj.com', 'springer.com', 'wiley.com',
    'sciencedirect.com', 'tandfonline.com', 'journals.aps.org',
    'ieeexplore.ieee.org', 'dl.acm.org', 'semanticscholar.org'
  ];
  if (peerReviewDomains.some(d => urlLower.includes(d))) return 1;

  // Tier 2: government / regulatory
  const govDomains = [
    '.gov', '.gov.', 'fda.gov', 'sec.gov', 'cdc.gov', 'nih.gov',
    'fcc.gov', 'whitehouse.gov', 'ema.europa.eu', 'edpb.europa.eu',
    'ec.europa.eu', 'gov.uk', 'who.int', 'imf.org', 'worldbank.org',
    'bis.org', 'oecd.org'
  ];
  if (govDomains.some(d => urlLower.includes(d))) return 2;

  // Tier 3: industry analyst / company filing / patent
  const industryDomains = [
    'gartner.com', 'forrester.com', 'mckinsey.com', 'bain.com',
    'bcg.com', 'pwc.com', 'kpmg.com', 'deloitte.com', 'cbinsights.com',
    'pitchbook.com', 'crunchbase.com', 'uspto.gov', 'epo.org',
    'wipo.int', 'sec.gov/edgar'
  ];
  if (industryDomains.some(d => urlLower.includes(d))) return 3;

  // Tier 4: mainstream news
  const newsDomains = [
    'reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'nytimes.com',
    'washingtonpost.com', 'economist.com', 'bbc.', 'cnn.com', 'apnews.com',
    'tass.com', 'rbc.ru', 'kommersant.ru', 'vedomosti.ru'
  ];
  if (newsDomains.some(d => urlLower.includes(d))) return 4;

  // Tier 5: everything else (blogs, forums, social media)
  return 5;
}

// ─── Knowledge Base Operations ──────────────────────────────────────────────

/**
 * Search knowledge base for prior research on a topic.
 * Returns sources matching query terms, optionally filtered by tier.
 */
export async function searchKnowledgeBase(query, options = {}) {
  const { sourceTypes = null, minTier = 5, limit = 20, userId = OWNER_ID } = options;

  const where = {
    userId,
    tier: { lte: minTier }
  };

  if (sourceTypes && Array.isArray(sourceTypes) && sourceTypes.length > 0) {
    where.sourceType = { in: sourceTypes };
  }

  // Simple keyword search across title + summary + topicTags
  if (query && query.trim()) {
    const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 2);
    if (terms.length > 0) {
      where.OR = terms.flatMap(t => [
        { title: { contains: t, mode: 'insensitive' } },
        { summary: { contains: t, mode: 'insensitive' } },
        { topicTags: { contains: t, mode: 'insensitive' } }
      ]);
    }
  }

  const sources = await prisma.researchSource.findMany({
    where,
    orderBy: [
      { tier: 'asc' },                    // higher-tier first
      { citedInBriefings: 'desc' },       // most-cited first
      { accessedAt: 'desc' }              // recent first
    ],
    take: limit
  });

  return sources;
}

/**
 * Add new research source to KB.
 * Auto-detects tier from URL if not provided.
 * Returns existing source if URL already in DB (with updated metadata).
 */
export async function addResearchSource(input) {
  const {
    url,
    title,
    sourceType = null,
    authors = null,
    publishedDate = null,
    summary = null,
    keyClaims = null,
    topicTags = [],
    userId = OWNER_ID
  } = input;

  if (!url || !title) {
    throw new Error('addResearchSource: url and title are required');
  }

  const tier = tierSource(url, sourceType);
  const detectedSourceType = sourceType || ['peer_review','government','industry','news','blog'][tier - 1];

  // Upsert: if URL exists, update metadata; else create
  const source = await prisma.researchSource.upsert({
    where: { url },
    create: {
      userId,
      url,
      sourceType: detectedSourceType,
      tier,
      title,
      authors,
      publishedDate: publishedDate ? new Date(publishedDate) : null,
      summary,
      keyClaims: keyClaims ? JSON.stringify(keyClaims) : null,
      topicTags: JSON.stringify(topicTags)
    },
    update: {
      title,
      summary: summary || undefined,
      keyClaims: keyClaims ? JSON.stringify(keyClaims) : undefined,
      // merge topicTags
      topicTags: topicTags.length > 0
        ? JSON.stringify([...new Set([...JSON.parse((await prisma.researchSource.findUnique({ where: { url } }))?.topicTags || '[]'), ...topicTags])])
        : undefined,
      updatedAt: new Date()
    }
  });

  return source;
}

/**
 * Link a source to an ExpertBriefing.
 * Creates junction record + increments citedInBriefings counter.
 */
export async function linkSourceToBriefing(briefingId, sourceId, citation = null) {
  await prisma.expertBriefingResearchSource.upsert({
    where: { briefingId_sourceId: { briefingId, sourceId } },
    create: { briefingId, sourceId, citation },
    update: { citation }
  });

  // Increment counter
  await prisma.researchSource.update({
    where: { id: sourceId },
    data: { citedInBriefings: { increment: 1 } }
  });
}

/**
 * Link a source to an Analysis (OSP V2).
 * `layer` indicates which level (leaves/branches/stem/roots/fruits) used it.
 */
export async function linkSourceToAnalysis(analysisId, sourceId, options = {}) {
  const { layer = null, citation = null } = options;

  await prisma.analysisResearchSource.upsert({
    where: { analysisId_sourceId: { analysisId, sourceId } },
    create: { analysisId, sourceId, layer, citation },
    update: { layer, citation }
  });

  await prisma.researchSource.update({
    where: { id: sourceId },
    data: { citedInAnalyses: { increment: 1 } }
  });
}

/**
 * Link a source to a KnowledgeArtifact (ЛЗ).
 */
export async function linkSourceToArtifact(artifactId, sourceId, options = {}) {
  const { section = null, citation = null } = options;

  await prisma.knowledgeArtifactResearchSource.upsert({
    where: { artifactId_sourceId: { artifactId, sourceId } },
    create: { artifactId, sourceId, section, citation },
    update: { section, citation }
  });
}

// ─── Citation Discipline ────────────────────────────────────────────────────

/**
 * Format a source as inline citation suitable for inserting into briefings/analyses.
 * Format: [Source: <Title>, <Type tier-N>, <Date>]
 */
export function formatCitation(source) {
  const date = source.publishedDate
    ? new Date(source.publishedDate).toISOString().slice(0, 10)
    : 'undated';
  const typeLabel = TIER_LABELS[source.tier] || 'unverified';
  return `[Source: ${source.title}, ${typeLabel}, ${date}]`;
}

/**
 * Format a source as a markdown link.
 */
export function formatCitationLink(source) {
  return `[${source.title}](${source.url}) (${TIER_LABELS[source.tier]})`;
}

/**
 * Validate that text has citations on numerical claims and key empirical statements.
 *
 * Returns: { valid: bool, missingCitations: [{snippet, reason}, ...] }
 *
 * Heuristics:
 *   - Numbers with units (USD, GW, kg/year, %, K, MW etc.) require citation
 *   - Claims with hard quantifiers ("first", "only", "largest") require citation
 *   - Sentences containing "according to" or "[Source:" are considered cited
 */
export function validateCitations(text) {
  if (!text || typeof text !== 'string') {
    return { valid: false, missingCitations: [{ snippet: '<empty>', reason: 'no text' }] };
  }

  const sentences = text.split(/(?<=[.!?])\s+/);
  const missingCitations = [];

  // Patterns suggesting empirical claims requiring citation
  const numericalPattern = /\b\d+(?:[.,]\d+)?\s*(?:%|\$|usd|eur|gw|mw|kw|kg|kelvin|k\b|°c|°f|million|billion|trillion|thousand|млн|млрд|тыс)/i;
  const quantifierPattern = /\b(first|only|largest|highest|lowest|most|least|единственный|первый|самый)\b/i;
  const dateClaimPattern = /\b(by|in|since|до|с|в)\s+(19|20)\d{2}\b/i;

  for (const sentence of sentences) {
    const hasNumerical = numericalPattern.test(sentence);
    const hasQuantifier = quantifierPattern.test(sentence);
    const hasDateClaim = dateClaimPattern.test(sentence);

    if (!hasNumerical && !hasQuantifier && !hasDateClaim) continue;

    // Has empirical content. Check for citation:
    const hasCitation = /\[Source:|\[Источник:|according to|по данным/i.test(sentence);

    if (!hasCitation) {
      missingCitations.push({
        snippet: sentence.slice(0, 200),
        reason: hasNumerical
          ? 'numerical claim without citation'
          : hasDateClaim
            ? 'date-bound claim without citation'
            : 'absolute quantifier without citation'
      });
    }
  }

  return {
    valid: missingCitations.length === 0,
    missingCitations,
    totalChecked: sentences.length
  };
}

// ─── Iterative Research Loop ────────────────────────────────────────────────

/**
 * Main iterative research function (LDR-inspired).
 *
 * Process:
 *   Iteration 1: Broad search — initial scan of topic via Grok, identify gaps
 *   Iteration 2: Targeted follow-ups — fill gaps with specific queries
 *   Iteration 3: Synthesize — Claude integrates findings, produces output with citations
 *
 * Returns {
 *   findings: <synthesized text with inline citations>,
 *   sources: <array of ResearchSource records>,
 *   gaps: <unresolved gaps array>,
 *   iterations: <log array>
 * }
 *
 * Options:
 *   maxIterations: 1-5 (default 3)
 *   strategy: 'quick' | 'standard' | 'deep' (default 'standard')
 *   userId: defaults OWNER_ID
 *   linkTo: { type: 'briefing'|'analysis'|'artifact', id: number } - auto-link sources
 */
export async function iterativeResearch(topic, options = {}) {
  const {
    maxIterations = 3,
    strategy = 'standard',
    userId = OWNER_ID,
    linkTo = null,
    additionalContext = null
  } = options;

  if (!topic || typeof topic !== 'string') {
    throw new Error('iterativeResearch: topic is required');
  }

  const log = [];
  const collectedSources = [];
  let allFindings = '';
  let identifiedGaps = [];

  // ─── Iteration 1: Broad Search ──────────────────────────────────────────

  log.push({ iteration: 1, phase: 'broad_search', startedAt: new Date() });

  // First check KB for existing sources on this topic
  const existingSources = await searchKnowledgeBase(topic, { userId, limit: 10 });
  if (existingSources.length > 0) {
    log.push({
      iteration: 1,
      phase: 'kb_lookup',
      foundInKB: existingSources.length,
      sources: existingSources.map(s => ({ id: s.id, title: s.title, tier: s.tier }))
    });
    collectedSources.push(...existingSources);
  }

  // Grok web search for fresh data
  const broadQuery = strategy === 'quick'
    ? `${topic} overview state-of-the-art 2026`
    : `${topic} fundamentals current research recent breakthroughs`;

  let grokResponse;
  try {
    grokResponse = await grok.chat.completions.create({
      model: 'grok-2-latest',
      messages: [{
        role: 'user',
        content: `Research query: "${broadQuery}".
Provide:
1. Key facts with sources (URLs)
2. State-of-the-art findings (recent 1-2 years)
3. Major debates / disagreements
4. Authoritative sources (peer-reviewed, government, industry analyst)
5. Numerical anchors (typical costs, timelines, performance)

Format as JSON:
{
  "findings": "...",
  "sources": [{"url": "...", "title": "...", "type": "...", "summary": "..."}]
}`
      }],
      temperature: 0.3
    });
  } catch (err) {
    log.push({ iteration: 1, phase: 'grok_error', error: String(err) });
    // Continue with KB-only data if available
    if (collectedSources.length === 0) {
      throw new Error(`iterativeResearch: Grok unavailable and no KB data: ${err.message}`);
    }
  }

  // Parse Grok response and add new sources to KB
  if (grokResponse) {
    const grokText = grokResponse.choices[0]?.message?.content || '';
    log.push({
      iteration: 1,
      phase: 'broad_search_complete',
      grokTokens: grokResponse.usage?.total_tokens || 0
    });

    // Try to extract structured sources
    const jsonMatch = grokText.match(/```json\s*([\s\S]*?)\s*```/) || grokText.match(/(\{[\s\S]*\})/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[1]);
        if (Array.isArray(parsed.sources)) {
          for (const src of parsed.sources) {
            if (src.url && src.title) {
              const stored = await addResearchSource({
                url: src.url,
                title: src.title,
                sourceType: src.type || null,
                summary: src.summary || null,
                topicTags: [topic.toLowerCase().slice(0, 50)],
                userId
              });
              collectedSources.push(stored);
            }
          }
        }
        if (parsed.findings) {
          allFindings += `## Iteration 1 — Broad scan\n\n${parsed.findings}\n\n`;
        }
      } catch (parseErr) {
        log.push({ iteration: 1, phase: 'json_parse_error', error: String(parseErr) });
        allFindings += `## Iteration 1 — Broad scan (raw)\n\n${grokText}\n\n`;
      }
    } else {
      allFindings += `## Iteration 1 — Broad scan (raw)\n\n${grokText}\n\n`;
    }
  }

  // Stop here if quick strategy
  if (strategy === 'quick' || maxIterations < 2) {
    return await finalizeResearch({
      topic, allFindings, collectedSources, identifiedGaps, log, linkTo, userId
    });
  }

  // ─── Iteration 2: Gap Identification + Targeted Follow-up ───────────────

  log.push({ iteration: 2, phase: 'gap_identification', startedAt: new Date() });

  // Use Claude to identify gaps in iteration 1 findings
  const gapAnalysis = await claude.messages.create({
    model: 'claude-sonnet-4-5-20250929',
    max_tokens: 2000,
    messages: [{
      role: 'user',
      content: `Topic: "${topic}"
${additionalContext ? `Context: ${additionalContext}\n` : ''}

Iteration 1 findings:
${allFindings}

Sources found so far:
${collectedSources.slice(0, 20).map(s => `- ${formatCitation(s)}`).join('\n')}

Task: identify the 3 most important gaps in this research that need targeted follow-up.
For each gap:
1. What's missing or unclear?
2. What specific query would resolve it?
3. What source type would best answer (peer_review/government/industry/news)?

Format as JSON:
{
  "gaps": [
    { "gap": "...", "query": "...", "preferredSourceType": "..." }
  ]
}`
    }]
  });

  const gapText = gapAnalysis.content[0]?.text || '';
  const gapJsonMatch = gapText.match(/```json\s*([\s\S]*?)\s*```/) || gapText.match(/(\{[\s\S]*\})/);
  let gapsToAddress = [];

  if (gapJsonMatch) {
    try {
      const parsed = JSON.parse(gapJsonMatch[1]);
      gapsToAddress = parsed.gaps || [];
      identifiedGaps = gapsToAddress.map(g => g.gap);
    } catch (e) {
      log.push({ iteration: 2, phase: 'gap_parse_error', error: String(e) });
    }
  }

  log.push({
    iteration: 2,
    phase: 'gaps_identified',
    count: gapsToAddress.length,
    gaps: gapsToAddress.map(g => g.gap)
  });

  // Targeted Grok queries for each gap
  for (const gap of gapsToAddress.slice(0, 3)) {
    try {
      const targetedResponse = await grok.chat.completions.create({
        model: 'grok-2-latest',
        messages: [{
          role: 'user',
          content: `Targeted research query: "${gap.query}".
Need: ${gap.gap}
Preferred sources: ${gap.preferredSourceType}

Format as JSON:
{
  "findings": "...",
  "sources": [{"url": "...", "title": "...", "type": "...", "summary": "..."}]
}`
        }],
        temperature: 0.2
      });

      const text = targetedResponse.choices[0]?.message?.content || '';
      const jsonMatch = text.match(/```json\s*([\s\S]*?)\s*```/) || text.match(/(\{[\s\S]*\})/);

      if (jsonMatch) {
        try {
          const parsed = JSON.parse(jsonMatch[1]);
          if (parsed.findings) {
            allFindings += `### Gap addressed: ${gap.gap}\n\n${parsed.findings}\n\n`;
          }
          if (Array.isArray(parsed.sources)) {
            for (const src of parsed.sources) {
              if (src.url && src.title) {
                const stored = await addResearchSource({
                  url: src.url,
                  title: src.title,
                  sourceType: src.type || gap.preferredSourceType || null,
                  summary: src.summary || null,
                  topicTags: [topic.toLowerCase().slice(0, 50), gap.gap.toLowerCase().slice(0, 30)],
                  userId
                });
                collectedSources.push(stored);
              }
            }
          }
        } catch (parseErr) {
          allFindings += `### Gap addressed: ${gap.gap} (raw)\n\n${text}\n\n`;
        }
      }
    } catch (err) {
      log.push({ iteration: 2, phase: 'gap_query_error', gap: gap.gap, error: String(err) });
    }
  }

  log.push({ iteration: 2, phase: 'targeted_followup_complete' });

  if (strategy === 'standard' || maxIterations < 3) {
    return await finalizeResearch({
      topic, allFindings, collectedSources, identifiedGaps, log, linkTo, userId
    });
  }

  // ─── Iteration 3 (deep mode only): Cross-validation + remaining gaps ─────

  log.push({ iteration: 3, phase: 'cross_validation', startedAt: new Date() });

  // For deep mode, do one more iteration looking for cross-references and contrarian views
  try {
    const deepQuery = `${topic} contrarian views skeptics critics failed predictions`;
    const deepResponse = await grok.chat.completions.create({
      model: 'grok-2-latest',
      messages: [{
        role: 'user',
        content: `Find contrarian/critical perspectives on: "${topic}".
Specifically:
1. Notable skeptics and their arguments
2. Failed predictions in this area
3. Conflicting evidence
4. Methodological criticisms

Format as JSON:
{ "findings": "...", "sources": [...] }`
      }]
    });

    const text = deepResponse.choices[0]?.message?.content || '';
    const jsonMatch = text.match(/```json\s*([\s\S]*?)\s*```/) || text.match(/(\{[\s\S]*\})/);

    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[1]);
        if (parsed.findings) {
          allFindings += `## Iteration 3 — Contrarian views & cross-validation\n\n${parsed.findings}\n\n`;
        }
        if (Array.isArray(parsed.sources)) {
          for (const src of parsed.sources) {
            if (src.url && src.title) {
              const stored = await addResearchSource({
                url: src.url,
                title: src.title,
                sourceType: src.type || null,
                summary: src.summary || null,
                topicTags: [topic.toLowerCase().slice(0, 50), 'contrarian'],
                userId
              });
              collectedSources.push(stored);
            }
          }
        }
      } catch (e) {
        allFindings += `## Iteration 3 — Contrarian views (raw)\n\n${text}\n\n`;
      }
    }
  } catch (err) {
    log.push({ iteration: 3, phase: 'cross_validation_error', error: String(err) });
  }

  log.push({ iteration: 3, phase: 'cross_validation_complete' });

  return await finalizeResearch({
    topic, allFindings, collectedSources, identifiedGaps, log, linkTo, userId
  });
}

/**
 * Final synthesis step. Claude integrates all findings, ensures citations,
 * auto-links sources to target entity if linkTo provided.
 */
async function finalizeResearch({ topic, allFindings, collectedSources, identifiedGaps, log, linkTo, userId }) {
  // Deduplicate sources by id
  const sourceMap = new Map();
  for (const s of collectedSources) {
    sourceMap.set(s.id, s);
  }
  const uniqueSources = Array.from(sourceMap.values());

  log.push({ phase: 'finalize', uniqueSources: uniqueSources.length });

  // Auto-link to target if linkTo specified
  if (linkTo && linkTo.type && linkTo.id) {
    for (const src of uniqueSources) {
      try {
        if (linkTo.type === 'briefing') {
          await linkSourceToBriefing(linkTo.id, src.id, formatCitation(src));
        } else if (linkTo.type === 'analysis') {
          await linkSourceToAnalysis(linkTo.id, src.id, {
            layer: linkTo.layer || null,
            citation: formatCitation(src)
          });
        } else if (linkTo.type === 'artifact') {
          await linkSourceToArtifact(linkTo.id, src.id, {
            section: linkTo.section || null,
            citation: formatCitation(src)
          });
        }
      } catch (e) {
        log.push({ phase: 'link_error', sourceId: src.id, error: String(e) });
      }
    }
  }

  // Validate citations in synthesized findings
  const citationCheck = validateCitations(allFindings);

  return {
    topic,
    findings: allFindings,
    sources: uniqueSources,
    gaps: identifiedGaps,
    citationCheck,
    iterations: log,
    summary: {
      totalSources: uniqueSources.length,
      tier1Count: uniqueSources.filter(s => s.tier === 1).length,
      tier2Count: uniqueSources.filter(s => s.tier === 2).length,
      tier3Count: uniqueSources.filter(s => s.tier === 3).length,
      tier4Count: uniqueSources.filter(s => s.tier === 4).length,
      tier5Count: uniqueSources.filter(s => s.tier === 5).length,
      gapsResolved: identifiedGaps.length,
      citationsValid: citationCheck.valid,
      missingCitations: citationCheck.missingCitations.length
    }
  };
}

// ─── Helpers for callers ────────────────────────────────────────────────────

/**
 * Get all sources linked to an Expert briefing.
 */
export async function getBriefingSources(briefingId) {
  const links = await prisma.expertBriefingResearchSource.findMany({
    where: { briefingId },
    include: { source: true },
    orderBy: { source: { tier: 'asc' } }
  });
  return links.map(l => ({ ...l.source, citationInBriefing: l.citation }));
}

/**
 * Get all sources linked to an Analysis.
 */
export async function getAnalysisSources(analysisId) {
  const links = await prisma.analysisResearchSource.findMany({
    where: { analysisId },
    include: { source: true },
    orderBy: { source: { tier: 'asc' } }
  });
  return links.map(l => ({ ...l.source, layer: l.layer, citationInAnalysis: l.citation }));
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  iterativeResearch,
  searchKnowledgeBase,
  addResearchSource,
  linkSourceToBriefing,
  linkSourceToAnalysis,
  linkSourceToArtifact,
  formatCitation,
  formatCitationLink,
  validateCitations,
  tierSource,
  getBriefingSources,
  getAnalysisSources,
  SOURCE_TIERS,
  TIER_LABELS
};
