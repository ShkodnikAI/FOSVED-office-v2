// ============================================================================
// lib/dev.js — Dev Department engine
// ============================================================================
//
// Core operations for the Development department:
//   - DevTask lifecycle (create, estimate, implement, archive)
//   - Architecture Decision Records
//   - Tech Radar management
//   - GitHub repository operations (via github-client.js)
//   - Estimation calibration (monthly)
//   - Tech radar scanning (weekly)
//   - Quarterly methodology review
//   - Telegram archive snapshots
//   - Local server sync placeholder
//
// Triple storage: GitHub (primary) + Telegram archive (snapshots) + local (deferred)
// ============================================================================

import { PrismaClient } from '@prisma/client';
import github from './github-client.js';
import crypto from 'crypto';

const prisma = new PrismaClient();
const OWNER_ID = 2044005421;
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const ARCHIVE_CHANNEL_ID = process.env.ARCHIVE_CHANNEL_ID;

// ─── Standard project scaffold files ────────────────────────────────────────

const STANDARD_GITIGNORE = `node_modules/
.env
.env.local
.env.*.local
dist/
build/
.next/
coverage/
*.log
.DS_Store
.vscode/
.idea/
`;

const STANDARD_CI = `name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run lint --if-present
      - run: npm test --if-present
      - run: npm run build --if-present
`;

function mitLicense(year, holder) {
  return `MIT License

Copyright (c) ${year} ${holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
`;
}

function buildScaffold({ name, description, projectType }) {
  const year = new Date().getFullYear();
  const today = new Date().toISOString().slice(0, 10);

  const readme = `# ${name}

${description || 'A Fosved Office project.'}

## Quick start

\`\`\`bash
npm install
npm run dev
\`\`\`

## What this is

${description || 'Project description pending.'}

## Tech stack

- Project type: ${projectType || 'unspecified'}
- (populate as built)

## Development

- Setup: \`npm install\`
- Run dev: \`npm run dev\`
- Test: \`npm test\`
- Build: \`npm run build\`

## Environment variables

See \`.env.example\`.

## License

See LICENSE file.

## Project metadata

- Created: ${today}
- Status: alpha
- Owner: @ShkodnikAI
`;

  const changelog = `# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - ${today}
### Added
- Initial project scaffold
`;

  return [
    { path: 'README.md', content: readme },
    { path: 'LICENSE', content: mitLicense(year, '@ShkodnikAI') },
    { path: 'CHANGELOG.md', content: changelog },
    { path: '.gitignore', content: STANDARD_GITIGNORE },
    { path: '.github/workflows/ci.yml', content: STANDARD_CI },
    { path: '.env.example', content: '# Add environment variables here\n' },
    { path: 'docs/adr/.gitkeep', content: '' }
  ];
}

// ─── Estimation ──────────────────────────────────────────────────────────────

/**
 * Generate an initial estimate for a task.
 * Anchors on similar past tasks. Returns range + confidence.
 */
export async function generateEstimate({ taskType, description, userId = OWNER_ID }) {
  // Find similar completed tasks for anchoring
  const similar = await prisma.devTask.findMany({
    where: {
      userId,
      taskType,
      status: 'archived',
      actualMin: { not: null }
    },
    orderBy: { completedAt: 'desc' },
    take: 10
  });

  let low, expected, high, confidence, rationale;

  if (similar.length >= 5) {
    // Anchor on actuals
    const actuals = similar.map(t => t.actualMin).sort((a, b) => a - b);
    const median = actuals[Math.floor(actuals.length / 2)];
    const p10 = actuals[Math.floor(actuals.length * 0.1)];
    const p90 = actuals[Math.floor(actuals.length * 0.9)];

    low = p10;
    expected = median;
    high = p90;
    confidence = similar.length >= 8 ? 'high' : 'medium';
    rationale = `Anchored on ${similar.length} similar ${taskType} tasks. Median actual: ${median}min.`;
  } else if (similar.length >= 2) {
    const actuals = similar.map(t => t.actualMin);
    const avg = actuals.reduce((a, b) => a + b, 0) / actuals.length;
    low = Math.round(avg * 0.5);
    expected = Math.round(avg);
    high = Math.round(avg * 2.5);
    confidence = 'medium';
    rationale = `Anchored on ${similar.length} similar tasks (limited data). Avg: ${Math.round(avg)}min.`;
  } else {
    // No anchor — wide range, low confidence
    const defaults = {
      web_app: 480, site: 240, ai_office: 960, local_ai: 720,
      infrastructure: 240, refactor: 180, hotfix: 90
    };
    expected = defaults[taskType] || 240;
    low = Math.round(expected * 0.4);
    high = Math.round(expected * 3);
    confidence = 'low';
    rationale = `No similar tasks in archive. Default estimate for ${taskType}, wide range due to uncertainty.`;
  }

  return { estimateLowMin: low, estimateExpectedMin: expected, estimateHighMin: high, estimateConfidence: confidence, estimateRationale: rationale };
}

// ─── DevTask lifecycle ───────────────────────────────────────────────────────

export async function createDevTask({ title, description, taskType = 'web_app', priority = 'medium', sourceType = 'owner', sourceId = null, designArtifactId = null, defectId = null, userId = OWNER_ID }) {
  const estimate = await generateEstimate({ taskType, description, userId });

  const task = await prisma.devTask.create({
    data: {
      userId, title, description, taskType, priority,
      sourceType, sourceId, designArtifactId, defectId,
      ...estimate,
      status: 'estimated'
    }
  });

  return task;
}

export async function recordArchitectureDecision({ taskId, title, context, decision, alternativesConsidered, consequences, userId = OWNER_ID }) {
  const task = await prisma.devTask.findUnique({ where: { id: taskId } });
  if (!task) throw new Error(`DevTask ${taskId} not found`);

  const adr = await prisma.architectureDecision.create({
    data: {
      userId, taskId, title, context, decision,
      alternativesConsidered: typeof alternativesConsidered === 'string'
        ? alternativesConsidered : JSON.stringify(alternativesConsidered),
      consequences,
      status: 'accepted',
      // schedule retrospective 60 days out
      retrospectiveDate: new Date(Date.now() + 60 * 24 * 60 * 60 * 1000)
    }
  });

  // Write ADR file to the task's repo if it has one
  if (task.repositoryId) {
    const repo = await prisma.codeRepository.findUnique({ where: { id: task.repositoryId } });
    if (repo) {
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
      const adrContent = `# ADR ${taskId}-${slug}: ${title}

**Status:** accepted
**Date:** ${new Date().toISOString().slice(0, 10)}
**Task:** DevTask-${taskId}

## Context

${context}

## Decision

${decision}

## Alternatives Considered

${typeof alternativesConsidered === 'string' ? alternativesConsidered : JSON.stringify(alternativesConsidered, null, 2)}

## Consequences

${consequences}

## Retrospective

_(to be filled ~60 days after this decision)_
`;
      try {
        await github.putFile({
          fullName: repo.fullName,
          path: `docs/adr/${taskId}-${slug}.md`,
          content: adrContent,
          message: `docs: ADR ${taskId} — ${title}`
        });
      } catch (e) {
        console.error('[dev] ADR file write failed (non-blocking):', e.message);
      }
    }
  }

  return adr;
}

/**
 * Tech radar check — verify proposed stack is usable.
 * Returns { ok, blocked: [...], warnings: [...] }.
 */
export async function checkTechRadar(techNames, userId = OWNER_ID) {
  const blocked = [];
  const warnings = [];

  for (const tech of techNames) {
    const entry = await prisma.techRadarEntry.findUnique({
      where: { userId_techName: { userId, techName: tech } }
    });
    if (!entry) {
      warnings.push({ tech, issue: 'not_in_radar', message: `${tech} not in Tech Radar — add via /dev-radar-add` });
    } else if (entry.state === 'hold') {
      blocked.push({ tech, issue: 'on_hold', message: `${tech} is on hold: ${entry.rationale}` });
    } else if (entry.state === 'assess') {
      warnings.push({ tech, issue: 'assess_only', message: `${tech} is assess-only — promote to trial before production use` });
    }
  }

  return { ok: blocked.length === 0, blocked, warnings };
}

// ─── Repository creation ─────────────────────────────────────────────────────

export async function createProjectRepository({ name, description, projectType = 'web_app', isPrivate = true, userId = OWNER_ID }) {
  // 1. Create GitHub repo
  const ghRepo = await github.createRepository({ name, description, isPrivate });

  // 2. Seed with standard scaffold
  const scaffold = buildScaffold({ name, description, projectType });
  await github.seedRepository({ fullName: ghRepo.fullName, files: scaffold });

  // 3. Branch protection
  await github.protectMainBranch(ghRepo.fullName);

  // 4. Record in DB
  const repo = await prisma.codeRepository.create({
    data: {
      userId,
      fullName: ghRepo.fullName,
      url: ghRepo.url,
      defaultBranch: ghRepo.defaultBranch,
      name,
      description,
      projectType,
      isPublic: !isPrivate,
      status: 'active'
    }
  });

  // 5. Announce in archive channel
  if (ARCHIVE_CHANNEL_ID && TELEGRAM_TOKEN) {
    await publishToArchive({
      text: `🆕 *New repository created*\n\n*${name}*\n${description || ''}\n\nType: ${projectType}\n${ghRepo.url}\n\n#dev #repo #${name.replace(/[^a-zA-Z0-9]/g, '_')}`
    });
  }

  return repo;
}

// ─── Task archive snapshot ───────────────────────────────────────────────────

/**
 * Publish a completed task snapshot to Telegram archive.
 * Per owner decision: summary post + zip attachment (up to 50MB).
 */
export async function archiveTaskSnapshot(taskId) {
  const task = await prisma.devTask.findUnique({
    where: { id: taskId },
    include: { architectureDecisions: true, repository: true }
  });
  if (!task) throw new Error(`DevTask ${taskId} not found`);

  const summary = `📦 *Dev Task Completed: #${task.id}*

*${task.title}*
${task.description || ''}

Type: ${task.taskType}
Estimate: ${task.estimateLowMin}-${task.estimateExpectedMin}-${task.estimateHighMin}min (${task.estimateConfidence})
Actual: ${task.actualMin || '?'}min
${task.actualMin && task.estimateHighMin ?
  (task.actualMin <= task.estimateHighMin && task.actualMin >= task.estimateLowMin ? '✓ in range' : '✗ out of range') : ''}

ADRs: ${task.architectureDecisions.length}
${task.repository ? `Repo: ${task.repository.url}` : ''}
${task.prUrl ? `PR: ${task.prUrl}` : ''}
Commits: ${task.commitsCount}
Tests: ${task.hasTests ? '✓' : '✗'}
Defects found: ${task.defectsFound}

#dev #task_completed #${task.taskType}`;

  let result;
  if (task.repository) {
    // Build a zip of the repo for attachment
    try {
      const zipBuffer = await buildRepoZip(task.repository.fullName);
      if (zipBuffer && zipBuffer.length < 50 * 1024 * 1024) {
        result = await publishDocumentToArchive({
          buffer: zipBuffer,
          filename: `${task.repository.name}_task${task.id}.zip`,
          caption: summary
        });
      } else {
        // Zip too large or failed — text only
        result = await publishToArchive({ text: summary });
      }
    } catch (e) {
      console.error('[dev] Snapshot zip failed (non-blocking):', e.message);
      result = await publishToArchive({ text: summary });
    }
  } else {
    result = await publishToArchive({ text: summary });
  }

  if (result?.message_id) {
    await prisma.devTask.update({
      where: { id: taskId },
      data: { archiveSnapshotMessageId: result.message_id }
    });
  }

  return result;
}

/**
 * Build a zip of repository contents (in-memory).
 */
async function buildRepoZip(fullName) {
  // Lightweight: requires 'jszip'. Falls back to null if unavailable.
  let JSZip;
  try {
    JSZip = (await import('jszip')).default;
  } catch (e) {
    console.warn('[dev] jszip not installed — skipping zip snapshot');
    return null;
  }

  const tree = await github.getRepositoryTree(fullName);
  const zip = new JSZip();

  // Limit: don't zip huge files / too many files
  let count = 0;
  for (const item of tree) {
    if (count >= 500) break;  // safety cap
    if (item.size && item.size > 1024 * 1024) continue;  // skip files > 1MB
    try {
      const content = await github.getFileContent(fullName, item.path);
      if (content !== null) {
        zip.file(item.path, content);
        count++;
      }
    } catch (e) { /* skip unreadable */ }
  }

  return zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
}

// ─── Telegram archive helpers ────────────────────────────────────────────────

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

async function publishDocumentToArchive({ buffer, filename, caption }) {
  if (!ARCHIVE_CHANNEL_ID || !TELEGRAM_TOKEN) return null;
  const formData = new FormData();
  formData.append('chat_id', ARCHIVE_CHANNEL_ID);
  formData.append('document', new Blob([buffer]), filename);
  formData.append('caption', caption.slice(0, 1024));
  formData.append('parse_mode', 'Markdown');

  const resp = await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendDocument`, {
    method: 'POST',
    body: formData
  });
  const data = await resp.json();
  return data.ok ? data.result : null;
}

// ─── Local server sync (deferred — placeholder) ─────────────────────────────

/**
 * Sync a repository to local server.
 * Placeholder until owner sets up local server.
 */
export async function syncToLocalServer(repoFullName) {
  const localServerUrl = process.env.LOCAL_SERVER_URL;
  if (!localServerUrl) {
    return {
      synced: false,
      reason: 'LOCAL_SERVER_URL not configured. Local server sync will activate when owner sets up local server.'
    };
  }

  // When local server exists, this would:
  // 1. git clone or pull the repo to local server path
  // 2. update CodeRepository.lastSyncedAt
  // For now: placeholder
  const repo = await prisma.codeRepository.findFirst({ where: { fullName: repoFullName } });
  if (repo) {
    await prisma.codeRepository.update({
      where: { id: repo.id },
      data: { localSyncEnabled: true, lastSyncedAt: new Date() }
    });
  }
  return { synced: true, note: 'Local server sync executed (placeholder implementation)' };
}

// ─── Weekly tech radar scan ──────────────────────────────────────────────────

export async function weeklyTechRadarScan() {
  // Lightweight: log + identify radar entries needing review.
  // Full implementation: web search for ThoughtWorks radar, GitHub trending, etc.
  const staleCutoff = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
  const stale = await prisma.techRadarEntry.findMany({
    where: {
      OR: [
        { lastReviewedAt: null },
        { lastReviewedAt: { lt: staleCutoff } }
      ]
    }
  });

  console.log(`[dev radar scan] ${new Date().toISOString()} — ${stale.length} entries need review`);

  if (stale.length > 0 && process.env.OWNER_TELEGRAM_ID && TELEGRAM_TOKEN) {
    const text = `🔭 *Tech Radar — Weekly Scan*\n\n${stale.length} entries not reviewed in 90+ days:\n${stale.slice(0, 10).map(e => `• ${e.techName} (${e.state})`).join('\n')}\n\nReview via /dev-radar`;
    await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: process.env.OWNER_TELEGRAM_ID, text, parse_mode: 'Markdown' })
    });
  }

  return { staleEntries: stale.length };
}

// ─── Monthly estimate calibration ───────────────────────────────────────────

export async function monthlyEstimateCalibration(userId = OWNER_ID) {
  const monthAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);

  const completed = await prisma.devTask.findMany({
    where: {
      userId,
      completedAt: { gte: monthAgo },
      actualMin: { not: null },
      estimateExpectedMin: { not: null }
    }
  });

  if (completed.length === 0) {
    return { tasks: 0, message: 'No completed tasks with estimates this month' };
  }

  let inRange = 0, nearExpected = 0, underestimates = 0, overestimates = 0;
  let totalRatio = 0;

  for (const t of completed) {
    if (t.actualMin >= t.estimateLowMin && t.actualMin <= t.estimateHighMin) inRange++;
    const ratio = t.actualMin / t.estimateExpectedMin;
    totalRatio += ratio;
    if (Math.abs(ratio - 1) <= 0.2) nearExpected++;
    if (ratio > 1.2) underestimates++;
    if (ratio < 0.8) overestimates++;
  }

  const stats = {
    tasks: completed.length,
    inRangeRate: inRange / completed.length,
    nearExpectedRate: nearExpected / completed.length,
    avgActualToEstimateRatio: totalRatio / completed.length,
    underestimateCount: underestimates,
    overestimateCount: overestimates
  };

  // Suggest fudge factor if systematic bias
  let recommendation = '';
  if (stats.avgActualToEstimateRatio > 1.3) {
    recommendation = `Systematic underestimation detected (avg ratio ${stats.avgActualToEstimateRatio.toFixed(2)}). Consider applying ${stats.avgActualToEstimateRatio.toFixed(1)}x fudge factor to expected estimates.`;
  } else if (stats.avgActualToEstimateRatio < 0.75) {
    recommendation = `Systematic overestimation detected. Estimates can be tightened.`;
  } else {
    recommendation = `Estimation calibration is reasonable.`;
  }

  console.log(`[dev calibration] ${stats.tasks} tasks, in-range ${(stats.inRangeRate*100).toFixed(0)}%`);

  if (process.env.OWNER_TELEGRAM_ID && TELEGRAM_TOKEN) {
    const text = `📊 *Dev — Monthly Estimate Calibration*\n\nTasks: ${stats.tasks}\nIn-range: ${(stats.inRangeRate*100).toFixed(0)}% (target ≥80%)\nNear-expected (±20%): ${(stats.nearExpectedRate*100).toFixed(0)}% (target ≥60%)\nAvg actual/estimate: ${stats.avgActualToEstimateRatio.toFixed(2)}\n\n${recommendation}`;
    await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: process.env.OWNER_TELEGRAM_ID, text, parse_mode: 'Markdown' })
    });
  }

  return { ...stats, recommendation };
}

// ─── Quarterly methodology review ───────────────────────────────────────────

export async function quarterlyMethodologyReview(userId = OWNER_ID) {
  const quarterAgo = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);

  // ADR retrospectives due
  const adrsDue = await prisma.architectureDecision.findMany({
    where: { userId, retrospectiveDate: { lte: new Date() }, retrospectiveNote: null }
  });

  // Task stats
  const tasks = await prisma.devTask.findMany({
    where: { userId, completedAt: { gte: quarterAgo } }
  });

  // Tech radar churn
  const radarEntries = await prisma.techRadarEntry.findMany({ where: { userId } });

  const review = {
    quarter: `${new Date().getFullYear()}-Q${Math.ceil((new Date().getMonth() + 1) / 3)}`,
    completedTasks: tasks.length,
    adrRetrospectivesDue: adrsDue.length,
    totalRadarEntries: radarEntries.length,
    radarByState: {
      adopt: radarEntries.filter(e => e.state === 'adopt').length,
      trial: radarEntries.filter(e => e.state === 'trial').length,
      assess: radarEntries.filter(e => e.state === 'assess').length,
      hold: radarEntries.filter(e => e.state === 'hold').length
    }
  };

  console.log(`[dev quarterly] ${review.quarter}:`, review);
  return review;
}

// ─── Listings ────────────────────────────────────────────────────────────────

export async function listDevTasks(filter = {}, limit = 20) {
  const { status, taskType, priority, userId = OWNER_ID } = filter;
  const where = { userId };
  if (status) where.status = status;
  if (taskType) where.taskType = taskType;
  if (priority) where.priority = priority;
  return prisma.devTask.findMany({ where, orderBy: { createdAt: 'desc' }, take: limit });
}

export async function listRepositories(userId = OWNER_ID) {
  return prisma.codeRepository.findMany({ where: { userId }, orderBy: { updatedAt: 'desc' } });
}

export async function getTechRadar(userId = OWNER_ID) {
  const entries = await prisma.techRadarEntry.findMany({
    where: { userId },
    orderBy: [{ category: 'asc' }, { state: 'asc' }]
  });
  return entries;
}

export async function addTechRadarEntry({ techName, category, state, rationale, userId = OWNER_ID }) {
  const existing = await prisma.techRadarEntry.findUnique({
    where: { userId_techName: { userId, techName } }
  });

  if (existing) {
    // State transition — record history
    const history = JSON.parse(existing.previousStates || '[]');
    if (existing.state !== state) {
      history.push({
        state: existing.state,
        until: new Date().toISOString(),
        reason_for_change: rationale
      });
    }
    return prisma.techRadarEntry.update({
      where: { id: existing.id },
      data: { state, rationale, category, previousStates: JSON.stringify(history), lastReviewedAt: new Date() }
    });
  }

  return prisma.techRadarEntry.create({
    data: { userId, techName, category, state, rationale, lastReviewedAt: new Date() }
  });
}

// ─── Export ──────────────────────────────────────────────────────────────────

export default {
  generateEstimate,
  createDevTask,
  recordArchitectureDecision,
  checkTechRadar,
  createProjectRepository,
  archiveTaskSnapshot,
  syncToLocalServer,
  weeklyTechRadarScan,
  monthlyEstimateCalibration,
  quarterlyMethodologyReview,
  listDevTasks,
  listRepositories,
  getTechRadar,
  addTechRadarEntry
};
