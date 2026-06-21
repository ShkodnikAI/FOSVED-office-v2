// ============================================================================
// lib/design.js — Design Department engine
// ============================================================================
//
// Core operations for the Design department:
//   - DesignArtifact lifecycle (create, iterate, approve, hand off)
//   - Design decisions recording
//   - User research session tracking
//   - Design system management
//   - Monthly design system audit
//   - Quarterly methodology review
//   - Accessibility checks
//
// Storage: DesignArtifact in DB (primary) + GitHub for design system docs +
//          Telegram archive for approved designs (via Visual department).
// ============================================================================

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Fosved brand design tokens (default design system) ─────────────────────

export const FOSVED_DESIGN_TOKENS = {
  colors: {
    'primary-navy': '#1a2332',
    'primary-cream': '#f4f0e6',
    'accent-gold': '#c9a227',
    'accent-burgundy': '#6e2639',
    'accent-forest': '#2d4a3e',
    'neutral-grey': '#6b7280',
    'light-grey': '#d1d5db'
  },
  typography: {
    'font-heading': 'Inter Tight, sans-serif',
    'font-body': 'Inter, sans-serif',
    'font-mono': 'IBM Plex Mono, monospace'
  },
  spacing: {
    base: 8,
    'space-xs': 4, 'space-sm': 8, 'space-md': 16,
    'space-lg': 24, 'space-xl': 40, 'space-2xl': 64
  },
  grid: { columns: 12, gutter: 24, margin: 64 },
  radius: { sm: 4, md: 8, lg: 16 }
};

// Required interaction states for any interactive component
const REQUIRED_STATES = ['default', 'hover', 'focus', 'active', 'disabled', 'loading', 'error'];

// ─── DesignArtifact lifecycle ────────────────────────────────────────────────

/**
 * Create a new design artifact from a brief.
 * Forces user-task definition (per user-task-analysis skill).
 */
export async function createDesignArtifact({
  title, brief, artifactType = 'wireframe', projectName,
  projectType = 'web_app', userTasks = [], format = 'description',
  content = null, userId = OWNER_ID
}) {
  if (!projectName) throw new Error('projectName required');
  if (!userTasks || userTasks.length === 0) {
    // Per user-task-analysis discipline — flag but allow (owner may fill later)
    console.warn('[design] Artifact created without userTasks — task analysis incomplete');
  }

  const artifact = await prisma.designArtifact.create({
    data: {
      userId, title, brief, artifactType, projectName, projectType,
      userTasks: JSON.stringify(userTasks),
      format, content,
      status: 'draft',
      iterationCount: 0,
      feedbackLog: JSON.stringify([])
    }
  });

  return artifact;
}

/**
 * Record an iteration with feedback.
 */
export async function iterateDesignArtifact({ artifactId, feedback, who = 'owner' }) {
  const artifact = await prisma.designArtifact.findUnique({ where: { id: artifactId } });
  if (!artifact) throw new Error(`DesignArtifact ${artifactId} not found`);

  const log = JSON.parse(artifact.feedbackLog || '[]');
  const newIteration = artifact.iterationCount + 1;
  log.push({
    iteration: newIteration,
    date: new Date().toISOString(),
    feedback,
    who
  });

  const updated = await prisma.designArtifact.update({
    where: { id: artifactId },
    data: {
      iterationCount: newIteration,
      feedbackLog: JSON.stringify(log),
      status: 'iteration'
    }
  });

  // Per design.md: max 3 iterations without escalation
  if (newIteration > 3) {
    console.warn(`[design] Artifact ${artifactId} at iteration ${newIteration} — exceeds target of 3, consider escalation`);
  }

  return updated;
}

/**
 * Record a design decision with rationale.
 */
export async function recordDesignDecision({
  artifactId, decision, rationale, userImpact = null,
  alternativesConsidered = null, validationMethod = null, userId = OWNER_ID
}) {
  const artifact = await prisma.designArtifact.findUnique({ where: { id: artifactId } });
  if (!artifact) throw new Error(`DesignArtifact ${artifactId} not found`);

  return prisma.designDecision.create({
    data: {
      userId, artifactId, decision, rationale, userImpact,
      alternativesConsidered, validationMethod
    }
  });
}

/**
 * Mark an artifact approved, ready for dev handoff.
 * Runs final checks first.
 */
export async function approveDesignArtifact(artifactId) {
  const artifact = await prisma.designArtifact.findUnique({ where: { id: artifactId } });
  if (!artifact) throw new Error(`DesignArtifact ${artifactId} not found`);

  // Pre-approval checks
  const checks = runPreApprovalChecks(artifact);
  if (!checks.passed) {
    return {
      approved: false,
      blockers: checks.blockers,
      warnings: checks.warnings,
      message: 'Artifact has blockers — resolve before approval'
    };
  }

  const updated = await prisma.designArtifact.update({
    where: { id: artifactId },
    data: { status: 'approved', approvedAt: new Date() }
  });

  // Publish to archive (summary; full visual via Visual department integration)
  if (ARCHIVE_CHANNEL_ID && TELEGRAM_TOKEN) {
    await publishToArchive({
      text: `🎨 *Design Approved*\n\n*${artifact.title}*\nProject: ${artifact.projectName}\nType: ${artifact.artifactType}\nIterations: ${artifact.iterationCount}\nWCAG: ${artifact.wcagLevel || 'AA'}\n\nReady for dev handoff.\n\n#design #approved #${artifact.projectName.replace(/[^a-zA-Z0-9]/g, '_')}`
    });
  }

  return { approved: true, artifact: updated, warnings: checks.warnings };
}

/**
 * Pre-approval quality checks.
 */
function runPreApprovalChecks(artifact) {
  const blockers = [];
  const warnings = [];

  // WCAG level set
  if (!artifact.wcagLevel) {
    warnings.push('No WCAG level specified — defaulting to AA');
  }

  // User tasks defined
  const userTasks = JSON.parse(artifact.userTasks || '[]');
  if (userTasks.length === 0) {
    blockers.push('No user tasks defined — user-task-analysis incomplete');
  }

  // For component specs, state specs should exist
  if (artifact.artifactType === 'component_spec' && !artifact.stateSpecs) {
    blockers.push('Component spec missing state specifications (default/hover/focus/etc.)');
  }

  // Responsive variants for UI artifacts
  if (['wireframe', 'mockup'].includes(artifact.artifactType) && !artifact.hasResponsiveVariants) {
    warnings.push('No responsive variants — mobile/tablet/desktop should be specified');
  }

  return { passed: blockers.length === 0, blockers, warnings };
}

/**
 * Hand off an approved artifact to a Dev task.
 */
export async function handoffToDevTask({ artifactId, devTaskId }) {
  const artifact = await prisma.designArtifact.findUnique({ where: { id: artifactId } });
  if (!artifact) throw new Error(`DesignArtifact ${artifactId} not found`);
  if (artifact.status !== 'approved') {
    throw new Error(`Artifact ${artifactId} not approved (status: ${artifact.status})`);
  }

  return prisma.designArtifact.update({
    where: { id: artifactId },
    data: { status: 'handed_off', handedOffToDevTaskId: devTaskId }
  });
}

/**
 * Measure implementation drift 2 weeks after dev implementation.
 */
export async function measureImplementationDrift({ artifactId, driftScore, notes }) {
  // driftScore: 0-1, where 1.0 = perfect match to spec
  const updated = await prisma.designArtifact.update({
    where: { id: artifactId },
    data: { implementationDrift: driftScore, status: 'implemented' }
  });

  if (driftScore < 0.9) {
    console.warn(`[design] Artifact ${artifactId} implementation drift ${driftScore} — below 0.9 target. Notes: ${notes}`);
  }

  return updated;
}

// ─── Design system ───────────────────────────────────────────────────────────

/**
 * Get or create a design system artifact for a project.
 */
export async function getOrCreateDesignSystem({ projectName, userId = OWNER_ID }) {
  let system = await prisma.designArtifact.findFirst({
    where: { userId, projectName, artifactType: 'design_system' }
  });

  if (!system) {
    // Create from Fosved brand defaults
    system = await prisma.designArtifact.create({
      data: {
        userId,
        title: `${projectName} Design System`,
        brief: 'Design system based on Fosved brand identity',
        artifactType: 'design_system',
        projectName,
        format: 'json',
        content: JSON.stringify(FOSVED_DESIGN_TOKENS, null, 2),
        wcagLevel: 'AA',
        status: 'approved'
      }
    });
  }

  return system;
}

// ─── User research ───────────────────────────────────────────────────────────

export async function recordResearchSession({
  artifactId = null, sessionType, topic, methodology,
  participants = null, findings, recommendations, userId = OWNER_ID
}) {
  return prisma.userResearchSession.create({
    data: {
      userId, artifactId, sessionType, topic, methodology,
      participants, findings, recommendations,
      conductedAt: new Date()
    }
  });
}

// ─── Monthly design system audit ────────────────────────────────────────────

export async function monthlyDesignSystemAudit(userId = OWNER_ID) {
  const systems = await prisma.designArtifact.findMany({
    where: { userId, artifactType: 'design_system' }
  });

  const artifacts = await prisma.designArtifact.findMany({
    where: { userId, artifactType: { not: 'design_system' } }
  });

  // Component usage analysis
  const componentUsage = {};
  for (const a of artifacts) {
    const components = JSON.parse(a.componentsUsed || '[]');
    for (const c of components) {
      componentUsage[c] = (componentUsage[c] || 0) + 1;
    }
  }

  // Drift analysis
  const withDrift = artifacts.filter(a => a.implementationDrift !== null);
  const avgDrift = withDrift.length > 0
    ? withDrift.reduce((s, a) => s + a.implementationDrift, 0) / withDrift.length
    : null;

  // Iteration analysis
  const avgIterations = artifacts.length > 0
    ? artifacts.reduce((s, a) => s + a.iterationCount, 0) / artifacts.length
    : 0;
  const highIteration = artifacts.filter(a => a.iterationCount > 3).length;

  const audit = {
    month: new Date().toISOString().slice(0, 7),
    designSystems: systems.length,
    totalArtifacts: artifacts.length,
    componentUsageRanking: Object.entries(componentUsage).sort((a, b) => b[1] - a[1]).slice(0, 10),
    avgImplementationDrift: avgDrift,
    avgIterations: avgIterations,
    artifactsExceedingIterationTarget: highIteration
  };

  console.log(`[design audit] ${audit.month}:`, audit);

  if (process.env.OWNER_TELEGRAM_ID && TELEGRAM_TOKEN) {
    const text = `🎨 *Design — Monthly System Audit*\n\nArtifacts: ${audit.totalArtifacts}\nAvg iterations: ${avgIterations.toFixed(1)} (target ≤3)\nExceeding iteration target: ${highIteration}\n${avgDrift !== null ? `Avg implementation drift: ${(avgDrift*100).toFixed(0)}% (target ≥90%)` : 'No drift data yet'}`;
    await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: process.env.OWNER_TELEGRAM_ID, text, parse_mode: 'Markdown' })
    });
  }

  return audit;
}

// ─── Quarterly methodology review ───────────────────────────────────────────

export async function quarterlyMethodologyReview(userId = OWNER_ID) {
  const quarterAgo = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);

  const artifacts = await prisma.designArtifact.findMany({
    where: { userId, createdAt: { gte: quarterAgo } }
  });

  const research = await prisma.userResearchSession.findMany({
    where: { userId, conductedAt: { gte: quarterAgo } }
  });

  const review = {
    quarter: `${new Date().getFullYear()}-Q${Math.ceil((new Date().getMonth() + 1) / 3)}`,
    artifactsCreated: artifacts.length,
    artifactsApproved: artifacts.filter(a => ['approved', 'handed_off', 'implemented'].includes(a.status)).length,
    researchSessions: research.length,
    byArtifactType: artifacts.reduce((acc, a) => {
      acc[a.artifactType] = (acc[a.artifactType] || 0) + 1;
      return acc;
    }, {})
  };

  console.log(`[design quarterly] ${review.quarter}:`, review);
  return review;
}

// ─── Accessibility check helper ──────────────────────────────────────────────

/**
 * Basic accessibility check on artifact spec.
 * Real a11y testing happens in QA; this is design-time guidance.
 */
export function checkAccessibility(artifact) {
  const issues = [];

  if (!artifact.wcagLevel) {
    issues.push({ severity: 'warning', message: 'No WCAG level declared — should be AA minimum' });
  }
  if (artifact.wcagLevel === 'A') {
    issues.push({ severity: 'warning', message: 'WCAG A is below Fosved standard (AA minimum)' });
  }

  // State specs should include focus (keyboard accessibility)
  if (artifact.stateSpecs) {
    const states = JSON.parse(artifact.stateSpecs || '{}');
    if (!states.focus) {
      issues.push({ severity: 'error', message: 'Missing focus state — keyboard users cannot see focus' });
    }
  }

  if (!artifact.accessibilityNotes) {
    issues.push({ severity: 'info', message: 'No accessibility notes — consider documenting a11y considerations' });
  }

  return { passed: !issues.some(i => i.severity === 'error'), issues };
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listDesignArtifacts(filter = {}, limit = 20) {
  const { status, artifactType, projectName, userId = OWNER_ID } = filter;
  const where = { userId };
  if (status) where.status = status;
  if (artifactType) where.artifactType = artifactType;
  if (projectName) where.projectName = projectName;
  return prisma.designArtifact.findMany({ where, orderBy: { createdAt: 'desc' }, take: limit });
}

// ─── Telegram archive helper ─────────────────────────────────────────────────

async function publishToArchive({ text }) {
  if (!ARCHIVE_CHANNEL_ID || !TELEGRAM_TOKEN) return null;
  const resp = await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: ARCHIVE_CHANNEL_ID,
      text: text.slice(0, 4096),
      parse_mode: 'Markdown',
      disable_web_page_preview: true
    })
  });
  const data = await resp.json();
  return data.ok ? data.result : null;
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  FOSVED_DESIGN_TOKENS,
  createDesignArtifact,
  iterateDesignArtifact,
  recordDesignDecision,
  approveDesignArtifact,
  handoffToDevTask,
  measureImplementationDrift,
  getOrCreateDesignSystem,
  recordResearchSession,
  monthlyDesignSystemAudit,
  quarterlyMethodologyReview,
  checkAccessibility,
  listDesignArtifacts
};
