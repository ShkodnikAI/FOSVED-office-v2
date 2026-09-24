// ============================================================================
// lib/visual.js — Visual Department generation engine
// ============================================================================
//
// Generates 5 types of visual artifacts from existing fosved-bot data:
//   Type 1: Compression Visual (multi-page → one SVG)
//   Type 2: Memorable Infographic (best-practice memorable SVG)
//   Type 3: Analysis Card (templated, auto on /analyze /expert /scan)
//   Type 4: Reference Sheet (one-page reference for Client/Project/Artifact)
//   Type 5: Premium Spec (JSON spec for manual Midjourney+Figma production)
//
// All visuals stored in VisualArtifact, linked back to source by sourceType+sourceId.
// Content-hash idempotence: same data → same hash → skip regen.
// Brand palette + typography enforced in all auto-generated visuals.
//
// Dependencies: Prisma client, Anthropic SDK, archive-publisher.js
// ============================================================================

import { PrismaClient } from '@prisma/client';
import Anthropic from '@anthropic-ai/sdk';
import crypto from 'crypto';

const prisma = new PrismaClient();
const claude = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const OWNER_ID = 2044005421;

// Emergency disable via env: VISUAL_AUTO_GENERATION=false
const AUTO_GENERATION_ENABLED = process.env.VISUAL_AUTO_GENERATION !== 'false';

// ─── Brand Identity ────────────────────────────────────────────────────────

export const BRAND = {
  colors: {
    primaryNavy:    '#1a1a2e',
    primaryCream:   '#f5f1e8',
    accentGold:     '#c9a961',
    accentBurgundy: '#8b2942',
    accentForest:   '#2d5f3f',
    neutralGrey:    '#5a5a5a',
    lightGrey:      '#e0ddd5'
  },
  typography: {
    headlines: { family: 'Inter Tight, system-ui, sans-serif', weight: 700 },
    subheaders: { family: 'Inter, system-ui, sans-serif', weight: 600 },
    body: { family: 'Inter, system-ui, sans-serif', weight: 400 },
    data: { family: 'IBM Plex Mono, monospace', weight: 500 },
    captions: { family: 'Inter, system-ui, sans-serif', weight: 400, style: 'italic' }
  },
  sizes: {
    h1: 56,
    h2: 36,
    h3: 24,
    body: 16,
    caption: 12,
    data_large: 48,
    data_medium: 28,
    data_small: 18
  },
  canvas: {
    tier1_compression: { w: 1080, h: 1350 },
    tier2_memorable: { w: 1080, h: 1350 },
    tier3_card: { w: 1080, h: 1080 },
    tier4_reference: { w: 1200, h: 900 },
    tier5_premium_thumbnail: { w: 1080, h: 1080 }
  },
  spacing: {
    outerMargin: 64,
    gridColumns: 12,
    gutter: 24
  }
};

// ─── Content Hash for Idempotence ──────────────────────────────────────────

export function computeContentHash(sourceData) {
  const normalized = JSON.stringify(sourceData, Object.keys(sourceData).sort());
  return crypto.createHash('sha256').update(normalized).digest('hex').slice(0, 16);
}

// ─── Type 3: Analysis Card (most frequent, templated) ─────────────────────

export async function generateAnalysisCard({ sourceType, sourceId, templateType = null, userId = OWNER_ID }) {
  if (!AUTO_GENERATION_ENABLED) {
    console.log('[visual] Auto-generation disabled via env');
    return null;
  }

  // Determine template type from source
  if (!templateType) {
    const map = {
      'analysis': 'osp_analysis_card',
      'briefing': 'expert_briefing_card',
      'artifact': 'lz_artifact_card'
    };
    templateType = map[sourceType];
    if (!templateType) throw new Error(`No template mapping for sourceType: ${sourceType}`);
  }

  // Load source data
  const source = await loadSource(sourceType, sourceId);
  if (!source) {
    throw new Error(`Source not found: ${sourceType}/${sourceId}`);
  }

  // Compute content hash
  const contentHash = computeContentHash(source);

  // Check existing — idempotence
  const existing = await prisma.visualArtifact.findFirst({
    where: { sourceType, sourceId, type: templateType, contentHash }
  });
  if (existing) {
    console.log(`[visual] Existing artifact ${existing.id} matches hash, skipping`);
    return existing;
  }

  // Load template
  const template = await prisma.visualTemplate.findUnique({ where: { type: templateType } });
  if (!template) {
    throw new Error(`Template not found: ${templateType}`);
  }

  // Render SVG from template + source data
  const svg = await renderCardFromTemplate(template, source, sourceType);

  // Save artifact
  const artifact = await prisma.visualArtifact.create({
    data: {
      userId,
      type: templateType,
      tier: 3,
      templateVersion: template.currentVersion,
      sourceType,
      sourceId,
      title: source.title || source.topic || `${sourceType} #${sourceId}`,
      format: 'svg',
      content: svg,
      contentHash,
      generationMethod: 'auto_svg_template',
      generationLog: JSON.stringify({ templateType, generatedAt: new Date().toISOString() })
    }
  });

  console.log(`[visual] Generated VisualArtifact #${artifact.id} for ${sourceType}/${sourceId}`);
  return artifact;
}

// ─── Type 1: Compression Visual (multi-page → one image) ───────────────────

export async function generateCompressionVisual({ sourceType, sourceId, userId = OWNER_ID }) {
  const source = await loadSource(sourceType, sourceId);
  if (!source) throw new Error(`Source not found: ${sourceType}/${sourceId}`);

  const contentHash = computeContentHash({ ...source, type: 'compression' });
  const existing = await prisma.visualArtifact.findFirst({
    where: { sourceType, sourceId, type: 'compression_visual', contentHash }
  });
  if (existing) return existing;

  // Use Claude to generate compression SVG
  const prompt = buildCompressionPrompt(source, sourceType);

  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 8000,
    messages: [{ role: 'user', content: prompt }]
  });

  const svg = extractSvgFromResponse(response.content[0]?.text || '');
  if (!svg) {
    console.error('[visual] Compression generation: no SVG extracted');
    return null;
  }

  const artifact = await prisma.visualArtifact.create({
    data: {
      userId,
      type: 'compression_visual',
      tier: 1,
      templateVersion: 'v1.0',
      sourceType,
      sourceId,
      title: `Compression — ${source.title || source.topic || 'untitled'}`,
      format: 'svg',
      content: svg,
      contentHash,
      generationMethod: 'claude_svg_generation',
      generationLog: JSON.stringify({
        tokens: response.usage,
        generatedAt: new Date().toISOString()
      })
    }
  });

  return artifact;
}

// ─── Type 2: Memorable Infographic (modern best-practices) ─────────────────

export async function generateMemorableInfographic({ sourceType, sourceId, focusInsight = null, userId = OWNER_ID }) {
  const source = await loadSource(sourceType, sourceId);
  if (!source) throw new Error(`Source not found: ${sourceType}/${sourceId}`);

  const contentHash = computeContentHash({ ...source, focusInsight, type: 'memorable' });
  const existing = await prisma.visualArtifact.findFirst({
    where: { sourceType, sourceId, type: 'memorable_infographic', contentHash }
  });
  if (existing) return existing;

  const prompt = buildMemorablePrompt(source, sourceType, focusInsight);

  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 10000,
    messages: [{ role: 'user', content: prompt }]
  });

  const svg = extractSvgFromResponse(response.content[0]?.text || '');
  if (!svg) return null;

  const artifact = await prisma.visualArtifact.create({
    data: {
      userId,
      type: 'memorable_infographic',
      tier: 2,
      templateVersion: 'v1.0',
      sourceType,
      sourceId,
      title: `Memorable — ${focusInsight || source.title || source.topic}`,
      format: 'svg',
      content: svg,
      contentHash,
      generationMethod: 'claude_svg_generation',
      generationLog: JSON.stringify({ focusInsight, tokens: response.usage })
    }
  });

  return artifact;
}

// ─── Type 4: Reference Sheet (one-page reference for entity) ──────────────

export async function generateReferenceSheet({ sourceType, sourceId, userId = OWNER_ID }) {
  if (!['client', 'project', 'artifact'].includes(sourceType)) {
    throw new Error(`Reference sheet only for client/project/artifact, got: ${sourceType}`);
  }

  // Load entity + related data (timeline, projects, invoices, etc.)
  const aggregated = await aggregateEntityData(sourceType, sourceId);
  if (!aggregated) throw new Error(`Entity not found: ${sourceType}/${sourceId}`);

  const contentHash = computeContentHash({ ...aggregated, type: 'reference_sheet' });
  const existing = await prisma.visualArtifact.findFirst({
    where: { sourceType, sourceId, type: `${sourceType}_reference_sheet`, contentHash }
  });
  if (existing) return existing;

  const prompt = buildReferenceSheetPrompt(aggregated, sourceType);

  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 8000,
    messages: [{ role: 'user', content: prompt }]
  });

  const svg = extractSvgFromResponse(response.content[0]?.text || '');
  if (!svg) return null;

  const artifact = await prisma.visualArtifact.create({
    data: {
      userId,
      type: `${sourceType}_reference_sheet`,
      tier: 4,
      templateVersion: 'v1.0',
      sourceType,
      sourceId,
      title: `Reference — ${aggregated.name || aggregated.title || aggregated.topic}`,
      format: 'svg',
      content: svg,
      contentHash,
      generationMethod: 'claude_svg_generation',
      generationLog: JSON.stringify({ tokens: response.usage })
    }
  });

  return artifact;
}

// ─── Type 5: Premium Spec (JSON for manual Midjourney+Figma production) ───

export async function generatePremiumSpec({ sourceType, sourceId, focusTheme = null, userId = OWNER_ID }) {
  const source = await loadSource(sourceType, sourceId);
  if (!source) throw new Error(`Source not found: ${sourceType}/${sourceId}`);

  const contentHash = computeContentHash({ ...source, focusTheme, type: 'premium_spec' });
  const existing = await prisma.visualArtifact.findFirst({
    where: { sourceType, sourceId, type: 'premium_spec', contentHash }
  });
  if (existing) return existing;

  const prompt = buildPremiumSpecPrompt(source, sourceType, focusTheme);

  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 6000,
    messages: [{ role: 'user', content: prompt }]
  });

  // Extract JSON spec from response
  const text = response.content[0]?.text || '';
  const jsonMatch = text.match(/```json\s*([\s\S]*?)\s*```/) || text.match(/(\{[\s\S]*\})/);
  let spec = null;
  if (jsonMatch) {
    try {
      spec = JSON.parse(jsonMatch[1]);
    } catch (e) {
      console.error('[visual] Premium spec parse error:', e.message);
    }
  }

  if (!spec) return null;

  const artifact = await prisma.visualArtifact.create({
    data: {
      userId,
      type: 'premium_spec',
      tier: 5,
      templateVersion: 'v1.0',
      sourceType,
      sourceId,
      title: `Premium Spec — ${focusTheme || source.title || source.topic}`,
      format: 'spec_json',
      content: JSON.stringify(spec, null, 2),
      contentHash,
      generationMethod: 'claude_spec_generation',
      generationLog: JSON.stringify({ focusTheme, tokens: response.usage })
    }
  });

  return artifact;
}

// ─── Source loaders ────────────────────────────────────────────────────────

async function loadSource(sourceType, sourceId) {
  const id = parseInt(sourceId);
  switch (sourceType) {
    case 'analysis':
      return prisma.analysis.findUnique({
        where: { id },
        include: { scenarioWatch: true }
      });
    case 'briefing':
      return prisma.expertBriefing.findUnique({ where: { id } });
    case 'artifact':
      return prisma.knowledgeArtifact.findUnique({ where: { id } });
    case 'client':
      return prisma.client.findUnique({
        where: { id },
        include: { timeline: { take: 10, orderBy: { date: 'desc' } } }
      });
    case 'project':
      return prisma.project.findUnique({
        where: { id },
        include: { tasks: true, client: true }
      });
    case 'verification':
      return prisma.analysisVerification.findUnique({
        where: { id },
        include: { analysis: true }
      });
    default:
      return null;
  }
}

async function aggregateEntityData(sourceType, sourceId) {
  const id = parseInt(sourceId);
  if (sourceType === 'client') {
    const client = await prisma.client.findUnique({
      where: { id },
      include: {
        timeline: { take: 20, orderBy: { date: 'desc' } },
        invoices: { take: 10, orderBy: { createdAt: 'desc' } },
        projects: { take: 10 },
        analyses: { take: 5, orderBy: { createdAt: 'desc' } }
      }
    });
    return client;
  } else if (sourceType === 'project') {
    return prisma.project.findUnique({
      where: { id },
      include: {
        tasks: true,
        client: true,
        analyses: { take: 5, orderBy: { createdAt: 'desc' } }
      }
    });
  } else if (sourceType === 'artifact') {
    return prisma.knowledgeArtifact.findUnique({
      where: { id },
      include: {
        talentEvents: { take: 10, orderBy: { date: 'desc' } },
        vcEvents: { take: 10, orderBy: { date: 'desc' } }
      }
    });
  }
  return null;
}

// ─── Template-based SVG rendering ──────────────────────────────────────────

async function renderCardFromTemplate(template, source, sourceType) {
  // Parse template spec
  let spec;
  try {
    spec = JSON.parse(template.spec);
  } catch (e) {
    console.error('[visual] Template spec parse error:', e.message);
    return null;
  }

  // Use Claude to render filled SVG
  const prompt = `You are rendering a visual card following a strict template.

TEMPLATE TYPE: ${template.type}
TEMPLATE VERSION: ${template.currentVersion}
TEMPLATE SPEC:
${JSON.stringify(spec, null, 2)}

BRAND IDENTITY:
${JSON.stringify(BRAND, null, 2)}

SOURCE DATA (${sourceType}):
${JSON.stringify(source, null, 2).slice(0, 8000)}

YOUR TASK:
Generate a complete SVG (1080×1080 viewBox) that:
1. Follows the template spec EXACTLY for layout, positions, sections
2. Uses ONLY brand colors and typography
3. Fills template fields with data from source
4. Maintains anti-chartjunk discipline (every element has purpose)
5. Compresses content for 5-second readability

Respond with ONLY the SVG code, no markdown, no preamble. Start with <svg.
`;

  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 8000,
    messages: [{ role: 'user', content: prompt }]
  });

  return extractSvgFromResponse(response.content[0]?.text || '');
}

// ─── Prompt builders ───────────────────────────────────────────────────────

function buildCompressionPrompt(source, sourceType) {
  return `You are generating a Type 1 Compression Visual — converting a multi-page report into one SVG image.

PRINCIPLE: viewer should grasp ENTIRE content of source in 5-10 seconds, replacing need to read multi-page document.

BRAND PALETTE (use ONLY these colors):
${JSON.stringify(BRAND.colors, null, 2)}

TYPOGRAPHY:
${JSON.stringify(BRAND.typography, null, 2)}

CANVAS: 1080×1350 viewBox (portrait, optimized for mobile reading)

SOURCE TYPE: ${sourceType}
SOURCE DATA:
${JSON.stringify(source, null, 2).slice(0, 10000)}

REQUIRED LAYOUT (top to bottom):
1. Header band (1080×120) — title, date, source ID
2. Hero metric or main insight (1080×200) — most important single fact
3. Structured sections (4-6 panels) — each covers one aspect of source
4. Footer band (1080×80) — provenance, confidence level, hashtags

DISCIPLINE:
- Anti-chartjunk: every pixel has informational purpose
- Visual hierarchy: largest = most important
- Data-ink ratio maximized
- No decorative elements without function

Respond with ONLY the SVG code. Start with <svg viewBox="0 0 1080 1350" xmlns="http://www.w3.org/2000/svg">.
`;
}

function buildMemorablePrompt(source, sourceType, focusInsight) {
  return `You are generating a Type 2 Memorable Infographic — applying modern best practices for memorability.

PRINCIPLE: viewer should REMEMBER the key insight a week later. Apply emotional hooks, visual metaphors, scale comparisons.

BRAND PALETTE:
${JSON.stringify(BRAND.colors, null, 2)}

CANVAS: 1080×1350 viewBox

SOURCE: ${sourceType}
DATA:
${JSON.stringify(source, null, 2).slice(0, 8000)}

${focusInsight ? `FOCUS INSIGHT (centerpiece): ${focusInsight}` : ''}

APPLY THESE TECHNIQUES:
- Golden ratio proportions (1.618:1 for key compositions)
- F-pattern reading flow (most important top-left)
- Color psychology: gold for hero data, burgundy for risks, forest for positive signals
- Visual hierarchy through SIZE and CONTRAST (not bold text)
- Emotional hooks: scale comparisons (X is as big as Y), surprise (most don't know Z)
- Gestalt principles: proximity (related grouped), similarity (same type same look), closure (visual completion)
- Negative space as structural element
- Micro-typography for labels (12-14px)

DISCIPLINE: every visual element must support the key insight. Cut everything that doesn't.

Respond with ONLY the SVG code. Start with <svg viewBox="0 0 1080 1350" xmlns="http://www.w3.org/2000/svg">.
`;
}

function buildReferenceSheetPrompt(aggregated, sourceType) {
  return `You are generating a Type 4 Reference Sheet — one-page reference card for ${sourceType}.

PRINCIPLE: this is a SHEET that lives on the desk — owner returns to it for quick reminder. Dense info, scan-friendly, military-reference-card style.

BRAND PALETTE:
${JSON.stringify(BRAND.colors, null, 2)}

CANVAS: 1200×900 viewBox (landscape for reference card)

AGGREGATED DATA:
${JSON.stringify(aggregated, null, 2).slice(0, 10000)}

REQUIRED SECTIONS:
1. Header (1200×100) — entity name, type, status, last updated
2. Key facts grid (3-4 cards) — most important params with values
3. Timeline panel — last 10 events compressed
4. Metrics panel — quantitative state
5. Risks/notes panel — qualitative state
6. Related entities panel — links to projects/clients/analyses

DISCIPLINE:
- Dense but scannable: use whitespace to separate, not decorate
- Numbers in IBM Plex Mono for alignment
- Color coding consistent across all reference sheets
- Print-ready (will be exported as PDF for offline use)

Respond with ONLY the SVG code. Start with <svg viewBox="0 0 1200 900" xmlns="http://www.w3.org/2000/svg">.
`;
}

function buildPremiumSpecPrompt(source, sourceType, focusTheme) {
  return `You are generating a Type 5 Premium Spec — JSON specification for owner to manually produce a publication-quality infographic in Midjourney + Figma.

NOTE: You are NOT generating an image. You are generating SPECIFICATIONS that the owner will execute manually using:
- Midjourney v7 for base image generation
- Figma for text overlays, labels, callouts, dimensions

REFERENCE QUALITY: like the BMW iM3 blueprint, SR-71 Blackbird overview, Premium Cake Collection examples — multi-element, photorealistic where appropriate, dense informational, premium magazine-quality.

SOURCE TYPE: ${sourceType}
SOURCE DATA:
${JSON.stringify(source, null, 2).slice(0, 8000)}

${focusTheme ? `FOCUS THEME: ${focusTheme}` : ''}

GENERATE A JSON SPEC WITH THIS STRUCTURE:

\`\`\`json
{
  "title": "main title for the infographic",
  "subtitle": "subtitle explaining context",
  "format": "portrait | landscape | square",
  "dimensions": "1080×1350 | 1200×900 | 1080×1080",

  "midjourney_base_prompt": "full Midjourney prompt for generating base image — describe scene, style, color palette, mood, composition",
  "midjourney_aspect_ratio": "--ar 4:5",
  "midjourney_style_params": "--style raw --v 7",

  "color_palette": ["#hex1", "#hex2", "#hex3"],

  "text_overlays": [
    {
      "type": "headline | callout | label | annotation | caption | data_number",
      "text": "actual text",
      "position": "top-left | top-center | top-right | center | bottom-left | etc.",
      "approximate_coordinates": {"x_percent": 50, "y_percent": 10},
      "font_family": "Inter Tight | Inter | IBM Plex Mono",
      "font_size_pt": 36,
      "font_weight": "regular | medium | bold",
      "color": "#hex"
    }
  ],

  "data_visualizations": [
    {
      "type": "bar_chart | line_chart | gauge | comparison | timeline",
      "position": "...",
      "data": [...],
      "specific_instructions": "..."
    }
  ],

  "callouts_and_lines": [
    {
      "from": {"x_percent": 30, "y_percent": 40},
      "to": {"x_percent": 50, "y_percent": 50},
      "label": "callout text",
      "style": "thin line | bracket | arrow"
    }
  ],

  "production_notes": [
    "specific instruction 1 for Figma assembly",
    "specific instruction 2"
  ],

  "estimated_production_time_minutes": 90,
  "reference_examples": ["mention similar style infographics: BMW blueprint / SR-71 overview / etc."]
}
\`\`\`

Be SPECIFIC. Owner should be able to execute this without further questions.

Respond with ONLY the JSON spec wrapped in triple backticks.
`;
}

// ─── SVG extraction helper ────────────────────────────────────────────────

function extractSvgFromResponse(text) {
  if (!text) return null;
  const match = text.match(/<svg[\s\S]*?<\/svg>/);
  return match ? match[0] : null;
}

// ─── Publishing to Telegram Archive ───────────────────────────────────────

export async function publishToArchive(artifact) {
  if (!process.env.ARCHIVE_CHANNEL_ID || !process.env.TELEGRAM_TOKEN) {
    console.log('[visual] Archive channel not configured, skipping publish');
    return null;
  }

  const TELEGRAM_API = `https://api.telegram.org/bot${process.env.TELEGRAM_TOKEN}`;

  // For SVG — convert to PNG or send as document
  // For spec_json — send as text
  let result;

  if (artifact.format === 'svg') {
    // Send SVG as document (Telegram doesn't render SVG inline)
    const formData = new FormData();
    formData.append('chat_id', process.env.ARCHIVE_CHANNEL_ID);
    formData.append('document', new Blob([artifact.content], { type: 'image/svg+xml' }),
                    `${artifact.type}_${artifact.id}.svg`);
    formData.append('caption', `${artifact.title}\n\n#визуал_${artifact.type} #${artifact.sourceType}_${artifact.sourceId}`);

    const response = await fetch(`${TELEGRAM_API}/sendDocument`, {
      method: 'POST',
      body: formData
    });
    result = await response.json();
  } else if (artifact.format === 'spec_json') {
    // Send as text message
    const text = `📐 *Premium Spec для ручной продукции*\n\n*${artifact.title}*\n\n\`\`\`json\n${artifact.content.slice(0, 3000)}\n\`\`\`\n\n#визуал_premium_spec`;
    const response = await fetch(`${TELEGRAM_API}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: process.env.ARCHIVE_CHANNEL_ID,
        text,
        parse_mode: 'Markdown'
      })
    });
    result = await response.json();
  }

  if (result?.ok) {
    await prisma.visualArtifact.update({
      where: { id: artifact.id },
      data: {
        publishedToChannel: true,
        channelMessageId: result.result.message_id
      }
    });
  }

  return result;
}

// ─── Listing & retrieval ───────────────────────────────────────────────────

export async function listArtifacts(filter = {}, limit = 20) {
  const { type, tier, sourceType, sourceId, userId = OWNER_ID } = filter;
  const where = { userId };
  if (type) where.type = type;
  if (tier) where.tier = tier;
  if (sourceType) where.sourceType = sourceType;
  if (sourceId) where.sourceId = parseInt(sourceId);

  return prisma.visualArtifact.findMany({
    where,
    orderBy: { createdAt: 'desc' },
    take: limit
  });
}

export async function getArtifact(id) {
  return prisma.visualArtifact.findUnique({ where: { id: parseInt(id) } });
}

// ─── Recall Test ───────────────────────────────────────────────────────────

export async function recallTest(artifactId, ownerRecalledCorrectly, note = null) {
  return prisma.visualArtifact.update({
    where: { id: parseInt(artifactId) },
    data: {
      recallTested: true,
      recallTestedAt: new Date(),
      recallSuccess: ownerRecalledCorrectly,
      recallNote: note
    }
  });
}

export async function pickRandomArtifactForRecall(daysOld = 30, userId = OWNER_ID) {
  const cutoff = new Date(Date.now() - daysOld * 24 * 60 * 60 * 1000);
  const candidates = await prisma.visualArtifact.findMany({
    where: {
      userId,
      recallTested: false,
      createdAt: { lt: cutoff }
    },
    take: 100
  });
  if (candidates.length === 0) return null;
  return candidates[Math.floor(Math.random() * candidates.length)];
}

export async function weeklyRecallPrompt() {
  const artifact = await pickRandomArtifactForRecall();
  if (!artifact || !process.env.OWNER_TELEGRAM_ID || !process.env.TELEGRAM_TOKEN) return;

  const text = `🧠 *Weekly Visual Recall Test*\n\nАртефакт #${artifact.id} (${artifact.type})\nСоздан: ${artifact.createdAt.toISOString().slice(0, 10)}\nТема: ${artifact.title}\n\nВопрос: *что эта инфографика говорит?* Один-два предложения, без чтения архива.\n\nОтветь /visual-recall ${artifact.id} <твой ответ>\nИли пропусти: /visual-recall ${artifact.id} skip`;

  await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: process.env.OWNER_TELEGRAM_ID,
      text,
      parse_mode: 'Markdown'
    })
  });
}

// ─── Pattern scan (daily, light-weight stub) ──────────────────────────────

export async function dailyPatternScan() {
  // Light-weight version: just log timestamp.
  // Full implementation: web search for new infographic patterns, image analysis, store observations.
  console.log(`[visual pattern scan] ${new Date().toISOString()} — placeholder; full implementation in v1.1`);
}

// ─── Quarterly style evolution (heavy, run rarely) ────────────────────────

export async function quarterlyStyleEvolution() {
  const now = new Date();
  const quarter = `${now.getFullYear()}-Q${Math.ceil((now.getMonth() + 1) / 3)}`;

  // Aggregate recall stats for last quarter
  const ninetyDaysAgo = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
  const recalls = await prisma.visualArtifact.findMany({
    where: {
      recallTested: true,
      recallTestedAt: { gte: ninetyDaysAgo }
    }
  });

  const recallStats = {
    total: recalls.length,
    successful: recalls.filter(r => r.recallSuccess).length,
    rate: recalls.length > 0 ? recalls.filter(r => r.recallSuccess).length / recalls.length : null
  };

  // Coverage rate this quarter
  const totalAnalyses = await prisma.analysis.count({ where: { createdAt: { gte: ninetyDaysAgo } } });
  const totalArtifacts = await prisma.visualArtifact.count({
    where: { createdAt: { gte: ninetyDaysAgo }, sourceType: 'analysis' }
  });
  const coverageRate = totalAnalyses > 0 ? totalArtifacts / totalAnalyses : null;

  const evolution = await prisma.styleEvolution.upsert({
    where: { yearQuarter: quarter },
    create: {
      yearQuarter: quarter,
      recallStats: JSON.stringify({ ...recallStats, coverageRate }),
      reviewNote: `Auto-generated quarterly review. Recalls: ${recalls.length}, success rate: ${recallStats.rate ? (recallStats.rate * 100).toFixed(1) + '%' : 'no data'}. Coverage: ${coverageRate ? (coverageRate * 100).toFixed(1) + '%' : 'no data'}.`
    },
    update: {
      recallStats: JSON.stringify({ ...recallStats, coverageRate })
    }
  });

  console.log(`[visual quarterly] Evolution recorded for ${quarter}: recall rate ${recallStats.rate}, coverage ${coverageRate}`);
  return evolution;
}

// ─── Template seeding ─────────────────────────────────────────────────────

export async function seedDefaultTemplates() {
  const templates = [
    {
      type: 'osp_analysis_card',
      tier: 3,
      currentVersion: 'v1.0',
      applyTo: 'auto_on_analysis_complete',
      description: 'Auto-generated card for every OSP Analysis. 5-level topology summary.',
      spec: JSON.stringify({
        canvas: { w: 1080, h: 1080 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1080, h: 120 }, fields: ['topic', 'createdAt', 'confidence'] },
          { name: 'topology_5_level', area: { x: 0, y: 120, w: 1080, h: 600 },
            subsections: ['leaves', 'branches', 'stem', 'roots', 'fruits'] },
          { name: 'scenarios', area: { x: 0, y: 720, w: 540, h: 280 }, fields: ['scenarios'] },
          { name: 'verification', area: { x: 540, y: 720, w: 540, h: 280 }, fields: ['verificationDate', 'watchUntil'] },
          { name: 'footer', area: { x: 0, y: 1000, w: 1080, h: 80 }, fields: ['id', 'hashtags'] }
        ]
      })
    },
    {
      type: 'expert_briefing_card',
      tier: 3,
      currentVersion: 'v1.0',
      applyTo: 'auto_on_briefing_complete',
      description: 'Auto-generated card for every Expert Briefing. Combat questions + failure modes.',
      spec: JSON.stringify({
        canvas: { w: 1080, h: 1080 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1080, h: 120 }, fields: ['topic', 'meetingDate', 'depthLevel'] },
          { name: 'combat_questions', area: { x: 0, y: 120, w: 1080, h: 400 }, fields: ['top_5_combat_questions'] },
          { name: 'failure_modes', area: { x: 0, y: 520, w: 540, h: 400 }, fields: ['top_3_failure_modes'] },
          { name: 'red_flags', area: { x: 540, y: 520, w: 540, h: 400 }, fields: ['red_flags'] },
          { name: 'footer', area: { x: 0, y: 920, w: 1080, h: 160 }, fields: ['understandingScore', 'hashtags'] }
        ]
      })
    },
    {
      type: 'lz_artifact_card',
      tier: 3,
      currentVersion: 'v1.0',
      applyTo: 'auto_on_artifact_update',
      description: 'Auto-generated card for KnowledgeArtifact. Hype cycle position + disruption gauge.',
      spec: JSON.stringify({
        canvas: { w: 1080, h: 1080 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1080, h: 120 }, fields: ['topic', 'status', 'lastScannedAt'] },
          { name: 'hype_cycle_position', area: { x: 0, y: 120, w: 540, h: 400 }, fields: ['hypePosition'] },
          { name: 'disruption_gauge', area: { x: 540, y: 120, w: 540, h: 400 }, fields: ['disruptionProbability', 'disruptionTimeline'] },
          { name: 'key_findings', area: { x: 0, y: 520, w: 1080, h: 480 }, fields: ['fullProfile'] },
          { name: 'footer', area: { x: 0, y: 1000, w: 1080, h: 80 }, fields: ['inflectionDetected', 'hashtags'] }
        ]
      })
    },
    {
      type: 'verification_dashboard',
      tier: 2,
      currentVersion: 'v1.0',
      applyTo: 'on_request',
      description: 'Dashboard showing predicted vs actual for an AnalysisVerification.',
      spec: JSON.stringify({
        canvas: { w: 1080, h: 1080 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1080, h: 100 }, fields: ['topic', 'verifiedAt'] },
          { name: 'brier_gauge', area: { x: 0, y: 100, w: 540, h: 400 }, fields: ['brierTotal'] },
          { name: 'scenario_outcomes_chart', area: { x: 540, y: 100, w: 540, h: 400 }, fields: ['scenarioOutcomes'] },
          { name: 'indicators_panel', area: { x: 0, y: 500, w: 1080, h: 280 }, fields: ['indicatorsTriggered', 'indicatorsTotal'] },
          { name: 'lessons_panel', area: { x: 0, y: 780, w: 1080, h: 300 }, fields: ['errorCategory', 'improvementsForNext'] }
        ]
      })
    },
    {
      type: 'client_reference_sheet',
      tier: 4,
      currentVersion: 'v1.0',
      applyTo: 'on_request',
      description: 'One-page reference sheet for a Client entity.',
      spec: JSON.stringify({
        canvas: { w: 1200, h: 900 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1200, h: 100 }, fields: ['name', 'company', 'tier', 'status'] },
          { name: 'contact_panel', area: { x: 0, y: 100, w: 400, h: 300 }, fields: ['email', 'phone'] },
          { name: 'financial_panel', area: { x: 400, y: 100, w: 400, h: 300 }, fields: ['totalRevenue', 'invoiceCount'] },
          { name: 'projects_panel', area: { x: 800, y: 100, w: 400, h: 300 }, fields: ['activeProjects', 'completedProjects'] },
          { name: 'timeline', area: { x: 0, y: 400, w: 1200, h: 400 }, fields: ['timeline'] },
          { name: 'footer', area: { x: 0, y: 800, w: 1200, h: 100 }, fields: ['lastEnrichedAt'] }
        ]
      })
    },
    {
      type: 'project_reference_sheet',
      tier: 4,
      currentVersion: 'v1.0',
      applyTo: 'on_request',
      description: 'One-page reference sheet for a Project entity.',
      spec: JSON.stringify({
        canvas: { w: 1200, h: 900 },
        sections: [
          { name: 'header', area: { x: 0, y: 0, w: 1200, h: 100 }, fields: ['name', 'type', 'status', 'progress'] },
          { name: 'team_panel', area: { x: 0, y: 100, w: 400, h: 300 }, fields: ['team'] },
          { name: 'deadlines_panel', area: { x: 400, y: 100, w: 400, h: 300 }, fields: ['deadline', 'taskCount'] },
          { name: 'client_panel', area: { x: 800, y: 100, w: 400, h: 300 }, fields: ['client'] },
          { name: 'tasks_panel', area: { x: 0, y: 400, w: 1200, h: 400 }, fields: ['tasks'] },
          { name: 'footer', area: { x: 0, y: 800, w: 1200, h: 100 }, fields: ['annotation'] }
        ]
      })
    },
    {
      type: 'compression_visual_long',
      tier: 1,
      currentVersion: 'v1.0',
      applyTo: 'on_request',
      description: 'Multi-page report → one image. For long-form sources.',
      spec: JSON.stringify({
        canvas: { w: 1080, h: 1350 },
        sections: ['header', 'hero_insight', 'sections_grid_4to6', 'footer'],
        density: 'high',
        readability_target_seconds: 10
      })
    },
    {
      type: 'premium_spec_template',
      tier: 5,
      currentVersion: 'v1.0',
      applyTo: 'manual_only',
      description: 'JSON spec template for premium publication-quality infographics. Owner executes manually in Midjourney + Figma.',
      spec: JSON.stringify({
        outputFormat: 'json_spec',
        executionTools: ['Midjourney v7', 'Figma'],
        estimatedManualTimeMinutes: 90,
        referenceQualityExamples: ['BMW iM3 blueprint', 'SR-71 Blackbird overview', 'Premium Cake Collection']
      })
    }
  ];

  let count = 0;
  for (const t of templates) {
    await prisma.visualTemplate.upsert({
      where: { type: t.type },
      create: t,
      update: { spec: t.spec, currentVersion: t.currentVersion, description: t.description }
    });
    count++;
  }
  return count;
}

// ─── Listings for inspection ──────────────────────────────────────────────

export async function listTemplates() {
  return prisma.visualTemplate.findMany({ orderBy: { tier: 'asc' } });
}

// ─── Default Export ───────────────────────────────────────────────────────

export default {
  BRAND,
  computeContentHash,
  generateAnalysisCard,
  generateCompressionVisual,
  generateMemorableInfographic,
  generateReferenceSheet,
  generatePremiumSpec,
  publishToArchive,
  listArtifacts,
  getArtifact,
  recallTest,
  pickRandomArtifactForRecall,
  weeklyRecallPrompt,
  dailyPatternScan,
  quarterlyStyleEvolution,
  seedDefaultTemplates,
  listTemplates
};
