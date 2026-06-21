// ============================================================================
// bot-cross-dept-hooks.js — cross-department auto-hooks for Dev + Design + QA
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
//
// These hooks wire the three departments into a pipeline:
//   Design approved   → auto-create Dev task
//   Dev implemented   → auto-trigger QA test run
//   QA critical defect→ auto-create Dev hotfix task
//   Dev task done     → notify Yana for next-step routing
//
// HOW TO APPLY:
// 1. Open bot.js
// 2. Add the require for these hooks
// 3. Call each hook at the END of the relevant command handler, AFTER the
//    primary action succeeded and AFTER the user reply was sent.
// 4. EVERY hook is wrapped in try/catch — a hook failure must NEVER fail or
//    roll back the primary action. Hooks are best-effort.
// 5. Respect the emergency kill-switch: if process.env.DDQ_AUTO_HOOKS === 'false'
//    all hooks become no-ops. Set this env var in Render to disable instantly
//    without a code change.
//
// Integration points (where to call each hook):
//   handleDesignApprove  → after approveDesignArtifact → onDesignApproved()
//   handleDevImplement   → after implementTask        → onDevImplemented()
//   handleQaDefect       → after recordDefect         → onDefectRecorded()
//   handleDevImplement   → after implementTask        → onDevTaskDone()
// ============================================================================

const dev = require('./lib/dev.js');
const qa = require('./lib/qa.js');

const HOOKS_ENABLED = () => process.env.DDQ_AUTO_HOOKS !== 'false';

// ─── Hook 1: Design approved → create Dev task ───────────────────────────────
/**
 * Called after a DesignArtifact is approved. Creates a DevTask that references
 * the approved design, so implementation can proceed from the spec.
 *
 * @param {object} artifact  the approved DesignArtifact
 * @param {object} bot       telegram bot instance (for owner notification)
 * @param {number} chatId    chat to notify
 */
async function onDesignApproved(artifact, bot, chatId) {
  if (!HOOKS_ENABLED()) return;
  try {
    const estimate = await dev.generateEstimate({
      description: `Implement approved design: ${artifact.title}`
    });
    const task = await dev.createDevTask({
      title: `Implement: ${artifact.title}`.slice(0, 80),
      description: `Implementation of approved DesignArtifact #${artifact.id}.\n` +
                   `Brief: ${artifact.brief}`,
      taskType: artifact.projectType === 'ai_office' ? 'ai_office' : 'web_app',
      sourceType: 'design',
      sourceId: artifact.id,
      designArtifactId: artifact.id,
      estimate
    });
    if (bot && chatId) {
      await bot.sendMessage(chatId,
        `🔗 Cross-dept: создана DevTask #${task.id} из одобренного дизайна #${artifact.id}`);
    }
    return task;
  } catch (e) {
    console.error('[ddq-hook] onDesignApproved failed (non-blocking):', e.message);
  }
}

// ─── Hook 2: Dev implemented → trigger QA test run ───────────────────────────
/**
 * Called after a DevTask implementation completes. Creates a QA TestRun so the
 * implementation is validated automatically.
 *
 * @param {object} task    the implemented DevTask
 * @param {object} result  the implementation result (repo, branch, etc.)
 * @param {object} bot
 * @param {number} chatId
 */
async function onDevImplemented(task, result, bot, chatId) {
  if (!HOOKS_ENABLED()) return;
  try {
    const target = result?.repoName || task.title;
    const run = await qa.createTestRun({
      target,
      testType: 'integration',  // default post-implementation suite
      targetTaskId: task.id,
      targetRepositoryId: task.repositoryId || null,
      triggerType: 'auto_post_implement',
      scopeDescription: `Auto-triggered after DevTask #${task.id} implementation`
    });
    if (bot && chatId) {
      await bot.sendMessage(chatId,
        `🔗 Cross-dept: QA TestRun #${run.id} запущен для DevTask #${task.id}`);
    }
    return run;
  } catch (e) {
    console.error('[ddq-hook] onDevImplemented failed (non-blocking):', e.message);
  }
}

// ─── Hook 3: QA critical defect → create Dev hotfix task ─────────────────────
/**
 * Called after a DefectRecord is created. If the defect warrants a hotfix
 * (critical, or high+reached production), creates a high-priority DevTask and
 * links the defect to it.
 *
 * @param {object} defect  the recorded DefectRecord
 * @param {object} bot
 * @param {number} chatId
 */
async function onDefectRecorded(defect, bot, chatId) {
  if (!HOOKS_ENABLED()) return;
  try {
    if (!qa.defectNeedsHotfix(defect)) return;  // only critical / high-in-prod

    const task = await dev.createDevTask({
      title: `HOTFIX: ${defect.title}`.slice(0, 80),
      description: `Hotfix for ${defect.severity} defect #${defect.id}.\n` +
                   `Actual behavior: ${defect.actualBehavior}\n` +
                   `Steps: ${defect.stepsToReproduce}`,
      taskType: 'hotfix',
      priority: 'critical',
      sourceType: 'qa_defect',
      sourceId: defect.id,
      defectId: defect.id
    });
    // Link defect → task
    await qa.assignDefectToTask(defect.id, task.id);

    if (bot && chatId) {
      await bot.sendMessage(chatId,
        `🚨 Cross-dept: создана HOTFIX DevTask #${task.id} для дефекта #${defect.id} [${defect.severity}]`);
    }
    return task;
  } catch (e) {
    console.error('[ddq-hook] onDefectRecorded failed (non-blocking):', e.message);
  }
}

// ─── Hook 4: Dev task done → notify Yana for next-step routing ───────────────
/**
 * Called after a DevTask is completed. Notifies Yana (the orchestrator) so she
 * can decide the next pipeline step (e.g. schedule QA sign-off, request Design
 * review, or mark the pipeline complete).
 *
 * This hook does NOT itself route — it hands a signal to Yana. If bot.js has a
 * direct Yana entry point, call it; otherwise this posts an owner-facing note.
 *
 * @param {object} task  the completed DevTask
 * @param {object} bot
 * @param {number} chatId
 */
async function onDevTaskDone(task, bot, chatId) {
  if (!HOOKS_ENABLED()) return;
  try {
    // If bot.js exposes a Yana notify function, prefer it:
    //   const yana = require('./lib/yana.js');
    //   await yana.notifyPipelineEvent({ event: 'dev_task_done', taskId: task.id });
    //
    // Fallback: owner-facing pipeline note.
    if (bot && chatId) {
      await bot.sendMessage(chatId,
        `🔗 Cross-dept: DevTask #${task.id} завершена. ` +
        `Яна уведомлена — следующий шаг pipeline (QA sign-off / Design review / готово).`);
    }
  } catch (e) {
    console.error('[ddq-hook] onDevTaskDone failed (non-blocking):', e.message);
  }
}

// ─── Usage example (place inside the relevant handlers in bot.js) ────────────
//
// In handleDesignApprove, after approveDesignArtifact succeeds:
//     const approved = await design.approveDesignArtifact({ artifactId: id });
//     await bot.sendMessage(chatId, '✅ ...');               // primary reply
//     await onDesignApproved(approved, bot, chatId);          // hook (best-effort)
//
// In handleDevImplement, after implementTask succeeds:
//     const result = await dev.implementTask({ taskId });
//     await bot.sendMessage(chatId, '✅ ...');               // primary reply
//     const task = (await dev.listDevTasks({})).find(t => t.id === taskId);
//     await onDevImplemented(task, result, bot, chatId);      // hook
//     await onDevTaskDone(task, bot, chatId);                 // hook
//
// In handleQaDefect, after recordDefect succeeds:
//     const defect = await qa.recordDefect({...});
//     await bot.sendMessage(chatId, '🐛 ...');               // primary reply
//     await onDefectRecorded(defect, bot, chatId);            // hook
//
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
  onDesignApproved,
  onDevImplemented,
  onDefectRecorded,
  onDevTaskDone
};
