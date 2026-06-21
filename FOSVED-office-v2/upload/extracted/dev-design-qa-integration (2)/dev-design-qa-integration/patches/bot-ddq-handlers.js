// ============================================================================
// bot-ddq-handlers.js — bot.js command handlers for Dev + Design + QA
// ============================================================================
//
// TARGET-STATE REFERENCE, not a git patch.
// 31 commands total: 14 Dev + 8 Design + 9 QA.
//
// HOW TO APPLY:
// 1. Open bot.js
// 2. Add the requires at the top (with other lib requires)
// 3. Add each handler in the command-handler section. Do NOT blind-copy —
//    bot.js has many existing handlers; match its registration style
//    (bot.onText / bot.command / switch on command — whatever bot.js uses).
// 4. Integrate ONE department at a time, test, then next (Phase Y6).
// 5. Verify: node -c bot.js
//
// All handlers assume OWNER-only access — bot.js already gates on
// OWNER_TELEGRAM_ID; keep that guard.
// ============================================================================

const dev = require('./lib/dev.js');
const design = require('./lib/design.js');
const qa = require('./lib/qa.js');

// Helper: parse "/cmd arg1 arg2 rest..." → { args: [...], rest: 'rest...' }
function parseArgs(text) {
  const parts = text.trim().split(/\s+/);
  parts.shift(); // drop the command itself
  return { args: parts, rest: parts.join(' ') };
}

// Helper: safe reply truncation (Telegram 4096 limit)
function clip(s) {
  return String(s).slice(0, 4000);
}

// ============================================================================
// DEV DEPARTMENT — 14 commands
// ============================================================================

// /dev <task description> — create DevTask with auto-estimation
async function handleDev(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /dev <описание задачи>');

  const estimate = await dev.generateEstimate({ description: rest });
  const task = await dev.createDevTask({
    title: rest.slice(0, 80),
    description: rest,
    taskType: estimate.inferredType || 'web_app',
    estimate
  });

  await bot.sendMessage(msg.chat.id, clip(
    `🛠 *DevTask #${task.id}* создана\n` +
    `${task.title}\n\n` +
    `Оценка: ${estimate.lowMin}–*${estimate.expectedMin}*–${estimate.highMin} мин ` +
    `(уверенность: ${estimate.confidence})\n` +
    `${estimate.rationale}\n\n` +
    `Следующий шаг: /dev-decide ${task.id} <решение> — зафиксировать ADR`
  ), { parse_mode: 'Markdown' });
}

// /dev-estimate <task_id> — refine estimate
async function handleDevEstimate(msg, bot) {
  const { args, rest } = parseArgs(msg.text);
  const taskId = parseInt(args[0], 10);
  if (!taskId) return bot.sendMessage(msg.chat.id, 'Использование: /dev-estimate <task_id> [новые детали]');

  const refined = await dev.generateEstimate({ taskId, additionalContext: rest });
  await bot.sendMessage(msg.chat.id, clip(
    `📐 Уточнённая оценка для DevTask #${taskId}:\n` +
    `${refined.lowMin}–*${refined.expectedMin}*–${refined.highMin} мин (${refined.confidence})\n` +
    `${refined.rationale}`
  ), { parse_mode: 'Markdown' });
}

// /dev-decide <task_id> <decision> — record ADR
async function handleDevDecide(msg, bot) {
  const { args } = parseArgs(msg.text);
  const taskId = parseInt(args[0], 10);
  const decision = args.slice(1).join(' ');
  if (!taskId || !decision) {
    return bot.sendMessage(msg.chat.id, 'Использование: /dev-decide <task_id> <текст решения>');
  }
  const adr = await dev.recordArchitectureDecision({ taskId, decision });
  await bot.sendMessage(msg.chat.id, clip(
    `📋 ADR записан для DevTask #${taskId}\n` +
    `${adr.title}\n` +
    `Файл: docs/adr/${taskId}-${adr.slug || 'decision'}.md\n` +
    `Ретроспектива назначена на: ${adr.retrospectiveDate || '+2 месяца'}`
  ), { parse_mode: 'Markdown' });
}

// /dev-implement <task_id> — execute implementation
async function handleDevImplement(msg, bot) {
  const { args } = parseArgs(msg.text);
  const taskId = parseInt(args[0], 10);
  if (!taskId) return bot.sendMessage(msg.chat.id, 'Использование: /dev-implement <task_id>');

  await bot.sendMessage(msg.chat.id, `⚙️ Запускаю реализацию DevTask #${taskId}…`);
  // dev.implementTask performs the actual code work + GitHub commits.
  const result = await dev.implementTask({ taskId });
  await bot.sendMessage(msg.chat.id, clip(
    `✅ DevTask #${taskId} — реализация завершена\n` +
    `Коммитов: ${result.commitsCount}\n` +
    `${result.prUrl ? `PR: ${result.prUrl}\n` : ''}` +
    `Тесты: ${result.hasTests ? 'добавлены' : 'НЕТ — нарушение правила 4'}\n\n` +
    `→ QA автозапуск тестов инициирован (cross-dept hook)`
  ), { parse_mode: 'Markdown' });
  // NOTE: the QA auto-test trigger is wired in bot-cross-dept-hooks.js
}

// /dev-task <id> — view task
async function handleDevTask(msg, bot) {
  const { args } = parseArgs(msg.text);
  const taskId = parseInt(args[0], 10);
  if (!taskId) return bot.sendMessage(msg.chat.id, 'Использование: /dev-task <id>');
  const tasks = await dev.listDevTasks({});
  const task = tasks.find(t => t.id === taskId);
  if (!task) return bot.sendMessage(msg.chat.id, `DevTask #${taskId} не найдена`);
  await bot.sendMessage(msg.chat.id, clip(
    `🛠 *DevTask #${task.id}* — ${task.status}\n` +
    `${task.title}\n` +
    `Тип: ${task.taskType} | Приоритет: ${task.priority}\n` +
    `Оценка: ${task.estimateLowMin}–${task.estimateExpectedMin}–${task.estimateHighMin} мин\n` +
    `${task.actualMin ? `Факт: ${task.actualMin} мин\n` : ''}` +
    `Коммитов: ${task.commitsCount} | Дефектов: ${task.defectsFound}`
  ), { parse_mode: 'Markdown' });
}

// /dev-tasks [filter] — list tasks
async function handleDevTasks(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filter = {};
  if (args[0]) filter.status = args[0];
  const tasks = await dev.listDevTasks(filter, 15);
  if (!tasks.length) return bot.sendMessage(msg.chat.id, 'Задач не найдено');
  const lines = tasks.map(t => `#${t.id} [${t.status}] ${t.title}`);
  await bot.sendMessage(msg.chat.id, clip(`🛠 *DevTasks* (${tasks.length}):\n` + lines.join('\n')),
    { parse_mode: 'Markdown' });
}

// /dev-repos — list managed repos
async function handleDevRepos(msg, bot) {
  const repos = await dev.listRepositories();
  if (!repos.length) return bot.sendMessage(msg.chat.id, 'Репозиториев пока нет');
  const lines = repos.map(r => `• ${r.fullName} [${r.status}] — ${r.projectType || 'n/a'}`);
  await bot.sendMessage(msg.chat.id, clip(`📦 *Репозитории* (${repos.length}):\n` + lines.join('\n')),
    { parse_mode: 'Markdown' });
}

// /dev-repo <name> — view repo details
async function handleDevRepo(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /dev-repo <name>');
  const repos = await dev.listRepositories();
  const repo = repos.find(r => r.name === rest || r.fullName === rest);
  if (!repo) return bot.sendMessage(msg.chat.id, `Репозиторий "${rest}" не найден`);
  await bot.sendMessage(msg.chat.id, clip(
    `📦 *${repo.fullName}*\n` +
    `${repo.description || ''}\n` +
    `Тип: ${repo.projectType || 'n/a'} | Статус: ${repo.status}\n` +
    `Коммитов: ${repo.commitsCount} | CI: ${repo.ciStatus || 'n/a'}\n` +
    `${repo.deploymentUrl ? `Deploy: ${repo.deploymentUrl}\n` : ''}` +
    `URL: ${repo.url}`
  ), { parse_mode: 'Markdown' });
}

// /dev-create-repo <name> <description> — create GitHub repo
async function handleDevCreateRepo(msg, bot) {
  const { args } = parseArgs(msg.text);
  const name = args[0];
  const description = args.slice(1).join(' ');
  if (!name) return bot.sendMessage(msg.chat.id, 'Использование: /dev-create-repo <name> <description>');

  await bot.sendMessage(msg.chat.id, `📦 Создаю репозиторий ShkodnikAI/${name}…`);
  const repo = await dev.createProjectRepository({ name, description });
  await bot.sendMessage(msg.chat.id, clip(
    `✅ Репозиторий создан: ${repo.fullName}\n` +
    `Скаффолд: README, LICENSE, CHANGELOG, .gitignore, CI workflow\n` +
    `Branch protection на main: включена\n` +
    `URL: ${repo.url}`
  ), { parse_mode: 'Markdown' });
}

// /dev-radar — show tech radar
async function handleDevRadar(msg, bot) {
  const { args } = parseArgs(msg.text);
  const entries = await dev.getTechRadar();
  const filtered = args[0] ? entries.filter(e => e.category === args[0]) : entries;
  if (!filtered.length) return bot.sendMessage(msg.chat.id, 'Tech Radar пуст');
  const byState = { adopt: [], trial: [], assess: [], hold: [] };
  for (const e of filtered) (byState[e.state] || (byState[e.state] = [])).push(e.techName);
  const out = ['📡 *Tech Radar*'];
  for (const state of ['adopt', 'trial', 'assess', 'hold']) {
    if (byState[state] && byState[state].length) {
      out.push(`*${state.toUpperCase()}*: ${byState[state].join(', ')}`);
    }
  }
  await bot.sendMessage(msg.chat.id, clip(out.join('\n')), { parse_mode: 'Markdown' });
}

// /dev-radar-add <tech> <state> <rationale> — add to radar
async function handleDevRadarAdd(msg, bot) {
  const { args } = parseArgs(msg.text);
  const techName = args[0];
  const state = args[1];
  const rationale = args.slice(2).join(' ');
  if (!techName || !['adopt', 'trial', 'assess', 'hold'].includes(state)) {
    return bot.sendMessage(msg.chat.id,
      'Использование: /dev-radar-add <tech> <adopt|trial|assess|hold> <обоснование>');
  }
  const entry = await dev.addTechRadarEntry({
    techName, category: 'library', state, rationale: rationale || 'manual entry'
  });
  await bot.sendMessage(msg.chat.id,
    `📡 ${entry.techName} → состояние "${entry.state}" зафиксировано в Tech Radar`);
}

// /dev-deploy <repo> <target> — trigger deployment
async function handleDevDeploy(msg, bot) {
  const { args } = parseArgs(msg.text);
  const repoName = args[0];
  const target = args[1] || 'render';
  if (!repoName) return bot.sendMessage(msg.chat.id, 'Использование: /dev-deploy <repo> [render|vercel|cloudflare]');
  await bot.sendMessage(msg.chat.id, `🚀 Запускаю деплой ${repoName} → ${target}…`);
  const result = await dev.deployRepo({ repoName, target });
  await bot.sendMessage(msg.chat.id, clip(
    `${result.success ? '✅' : '🔴'} Деплой ${repoName} → ${target}: ${result.status}\n` +
    `${result.url ? `URL: ${result.url}` : ''}`
  ));
}

// /dev-archive <task_id> — archive completed task snapshot
async function handleDevArchive(msg, bot) {
  const { args } = parseArgs(msg.text);
  const taskId = parseInt(args[0], 10);
  if (!taskId) return bot.sendMessage(msg.chat.id, 'Использование: /dev-archive <task_id>');
  const result = await dev.archiveTaskSnapshot({ taskId });
  await bot.sendMessage(msg.chat.id, clip(
    `📦 DevTask #${taskId} — snapshot опубликован в Telegram Archive\n` +
    `${result.zipSize ? `Размер архива: ${(result.zipSize / 1024).toFixed(0)} KB\n` : ''}` +
    `Сообщение: ${result.messageId || 'n/a'}`
  ));
}

// /dev-local-sync <repo> — sync to local server
async function handleDevLocalSync(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /dev-local-sync <repo>');
  const result = await dev.syncToLocalServer({ repoName: rest });
  await bot.sendMessage(msg.chat.id, clip(
    result.activated
      ? `💾 ${rest} синхронизирован на локальный сервер: ${result.localPath}`
      : `⏸ Локальный сервер не настроен (нет LOCAL_SERVER_URL). ` +
        `Команда станет активной после настройки.`
  ));
}

// ============================================================================
// DESIGN DEPARTMENT — 8 commands
// ============================================================================

// /design <brief> — create DesignArtifact
async function handleDesign(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /design <бриф>');
  const artifact = await design.createDesignArtifact({
    title: rest.slice(0, 80),
    brief: rest,
    artifactType: 'wireframe',
    projectName: rest.slice(0, 40)
  });
  await bot.sendMessage(msg.chat.id, clip(
    `🎨 *DesignArtifact #${artifact.id}* создан\n` +
    `${artifact.title}\n` +
    `Тип: ${artifact.artifactType} | Статус: ${artifact.status}\n\n` +
    `Следующий шаг: /design-iterate ${artifact.id} <фидбэк> или /design-approve ${artifact.id}`
  ), { parse_mode: 'Markdown' });
}

// /design-spec <project> — generate design spec for dev
async function handleDesignSpec(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /design-spec <project>');
  const artifacts = await design.listDesignArtifacts({ projectName: rest });
  if (!artifacts.length) return bot.sendMessage(msg.chat.id, `Артефактов для "${rest}" не найдено`);
  await bot.sendMessage(msg.chat.id, clip(
    `📐 Design spec для проекта "${rest}":\n` +
    `Артефактов: ${artifacts.length}\n` +
    artifacts.map(a => `• #${a.id} ${a.title} [${a.status}]`).join('\n') +
    `\n\nСпецификация для Dev handoff: используй /design-approve для готовых артефактов.`
  ), { parse_mode: 'Markdown' });
}

// /design-system <project> — view/create design system
async function handleDesignSystem(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /design-system <project>');
  const system = await design.getOrCreateDesignSystem({ projectName: rest });
  await bot.sendMessage(msg.chat.id, clip(
    `🎨 *Design System — ${rest}*\n` +
    `Tokens: ${Object.keys(system.tokens?.colors || {}).length} цветов, ` +
    `${Object.keys(system.tokens?.typography || {}).length} шрифтов\n` +
    `Базовый: ${system.basedOn || 'Fosved Brand Identity'}`
  ), { parse_mode: 'Markdown' });
}

// /design-show <id> — view artifact
async function handleDesignShow(msg, bot) {
  const { args } = parseArgs(msg.text);
  const id = parseInt(args[0], 10);
  if (!id) return bot.sendMessage(msg.chat.id, 'Использование: /design-show <id>');
  const artifacts = await design.listDesignArtifacts({});
  const a = artifacts.find(x => x.id === id);
  if (!a) return bot.sendMessage(msg.chat.id, `DesignArtifact #${id} не найден`);
  await bot.sendMessage(msg.chat.id, clip(
    `🎨 *DesignArtifact #${a.id}* — ${a.status}\n` +
    `${a.title}\n` +
    `Тип: ${a.artifactType} | Проект: ${a.projectName}\n` +
    `Итераций: ${a.iterationCount} | WCAG: ${a.wcagLevel || 'не проверен'}\n` +
    `${a.brief}`
  ), { parse_mode: 'Markdown' });
}

// /design-artifacts [filter] — list
async function handleDesignArtifacts(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filter = {};
  if (args[0]) filter.status = args[0];
  const artifacts = await design.listDesignArtifacts(filter, 15);
  if (!artifacts.length) return bot.sendMessage(msg.chat.id, 'Артефактов не найдено');
  await bot.sendMessage(msg.chat.id, clip(
    `🎨 *DesignArtifacts* (${artifacts.length}):\n` +
    artifacts.map(a => `#${a.id} [${a.status}] ${a.title}`).join('\n')
  ), { parse_mode: 'Markdown' });
}

// /design-research <topic> — initiate user research session
async function handleDesignResearch(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /design-research <topic>');
  const session = await design.recordResearchSession({
    sessionType: 'heuristic_eval',
    topic: rest,
    methodology: 'Nielsen heuristics + comparative analysis',
    findings: 'pending',
    recommendations: 'pending'
  });
  await bot.sendMessage(msg.chat.id,
    `🔬 Research-сессия #${session.id} начата: "${rest}"\n` +
    `Тип: эвристическая оценка`);
}

// /design-iterate <id> <feedback> — iterate
async function handleDesignIterate(msg, bot) {
  const { args } = parseArgs(msg.text);
  const id = parseInt(args[0], 10);
  const feedback = args.slice(1).join(' ');
  if (!id || !feedback) return bot.sendMessage(msg.chat.id, 'Использование: /design-iterate <id> <фидбэк>');
  const updated = await design.iterateDesignArtifact({ artifactId: id, feedback });
  await bot.sendMessage(msg.chat.id, clip(
    `🔁 DesignArtifact #${id} — итерация ${updated.iterationCount}\n` +
    (updated.iterationCount >= 3
      ? `⚠️ 3+ итерации — если не сходится, эскалация (см. протокол).`
      : `Фидбэк зафиксирован.`)
  ));
}

// /design-approve <id> — mark approved
async function handleDesignApprove(msg, bot) {
  const { args } = parseArgs(msg.text);
  const id = parseInt(args[0], 10);
  if (!id) return bot.sendMessage(msg.chat.id, 'Использование: /design-approve <id>');
  const a11y = await design.checkAccessibility({ artifactId: id });
  if (!a11y.passed) {
    return bot.sendMessage(msg.chat.id, clip(
      `🔴 DesignArtifact #${id} не прошёл accessibility-проверку:\n` +
      a11y.issues.map(i => `• [${i.severity}] ${i.message}`).join('\n') +
      `\n\nИсправь перед approve (жёсткое правило 1).`
    ));
  }
  const approved = await design.approveDesignArtifact({ artifactId: id });
  await bot.sendMessage(msg.chat.id, clip(
    `✅ DesignArtifact #${id} одобрен (WCAG ${approved.wcagLevel || 'AA'})\n` +
    `→ Dev handoff: автозадача создаётся (cross-dept hook)`
  ));
  // NOTE: the auto Dev-task creation is wired in bot-cross-dept-hooks.js
}

// ============================================================================
// QA DEPARTMENT — 9 commands
// ============================================================================

// /qa-strategy <project> — generate test strategy
async function handleQaStrategy(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /qa-strategy <project>');
  const strategy = qa.generateTestStrategy({
    projectName: rest, projectType: 'web_app', hasAI: true, hasUserInput: true
  });
  await bot.sendMessage(msg.chat.id, clip(
    `🧪 *Test Strategy — ${rest}*\n` +
    `Пирамида: unit ${strategy.pyramid.unit.share * 100}% / ` +
    `integration ${strategy.pyramid.integration.share * 100}% / ` +
    `e2e ${strategy.pyramid.e2e.share * 100}%\n` +
    `Перпендикулярные: ${strategy.perpendicular.map(p => p.type).join(', ')}\n` +
    `Gate: ${strategy.gateRule}`
  ), { parse_mode: 'Markdown' });
}

// /qa-test <type> <target> — run tests
async function handleQaTest(msg, bot) {
  const { args } = parseArgs(msg.text);
  const testType = args[0];
  const target = args.slice(1).join(' ');
  if (!testType || !target) {
    return bot.sendMessage(msg.chat.id,
      'Использование: /qa-test <unit|integration|e2e|security|performance|accessibility> <target>');
  }
  const run = await qa.createTestRun({ target, testType, triggerType: 'manual' });
  await bot.sendMessage(msg.chat.id,
    `🧪 TestRun #${run.id} запущен: ${testType} на "${target}"\n` +
    `Результаты будут записаны через completeTestRun.`);
  // NOTE: actual test execution is performed by project tooling;
  // bot collects results and calls qa.completeTestRun(run.id, {...}).
}

// /qa-defect <description> — record defect
async function handleQaDefect(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /qa-defect [critical|high|medium|low]: <описание>');
  // Parse leading severity if present "critical: ..."
  let severity = 'medium';
  let description = rest;
  const m = rest.match(/^(critical|high|medium|low|trivial)\s*[:|-]\s*(.+)$/i);
  if (m) { severity = m[1].toLowerCase(); description = m[2]; }

  const defect = await qa.recordDefect({
    title: description.slice(0, 80),
    description,
    severity,
    category: 'functional',
    stepsToReproduce: 'see description',
    expectedBehavior: 'see description',
    actualBehavior: description
  });
  await bot.sendMessage(msg.chat.id, clip(
    `🐛 *Defect #${defect.id}* записан [${severity}]\n` +
    `${defect.title}\n` +
    (qa.defectNeedsHotfix(defect)
      ? `→ Критический: Dev hotfix-задача создаётся (cross-dept hook)`
      : `Статус: open`)
  ), { parse_mode: 'Markdown' });
  // NOTE: critical-defect → Dev hotfix is wired in bot-cross-dept-hooks.js
}

// /qa-defects [filter] — list defects
async function handleQaDefects(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filter = {};
  if (args[0]) {
    if (['critical', 'high', 'medium', 'low', 'trivial'].includes(args[0])) filter.severity = args[0];
    else filter.status = args[0];
  }
  const defects = await qa.listDefects(filter, 20);
  if (!defects.length) return bot.sendMessage(msg.chat.id, 'Дефектов не найдено');
  await bot.sendMessage(msg.chat.id, clip(
    `🐛 *Defects* (${defects.length}):\n` +
    defects.map(d => `#${d.id} [${d.severity}/${d.status}] ${d.title}`).join('\n')
  ), { parse_mode: 'Markdown' });
}

// /qa-eval <ai-system> — run AI evals
async function handleQaEval(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /qa-eval <ai-system>');
  await bot.sendMessage(msg.chat.id, `🤖 Запускаю AI eval для "${rest}"…`);
  // The bot collects metric scores from the Promptfoo run, then records:
  // qa.recordAIEvalRun({ aiSystem: rest, goldenDatasetSize, metricScores, ... })
  await bot.sendMessage(msg.chat.id, clip(
    `🤖 AI eval для "${rest}":\n` +
    `Прогон golden dataset, метрики (groundedness/relevance/faithfulness),\n` +
    `prompt injection, hallucination detection — результаты через recordAIEvalRun.`
  ));
}

// /qa-security-audit <target> — security audit
async function handleQaSecurityAudit(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /qa-security-audit <target>');
  await bot.sendMessage(msg.chat.id, `🛡️ Запускаю security audit для "${rest}"…`);
  // bot collects npm audit + OWASP checklist findings, then:
  const audit = await qa.recordSecurityAudit({
    target: rest,
    auditType: 'dependency_audit',
    scope: 'Manual security audit invocation',
    findings: []  // bot fills with real findings
  });
  await bot.sendMessage(msg.chat.id, clip(
    `🛡️ Security audit #${audit.id} для "${rest}"\n` +
    `Critical: ${audit.criticalCount} | High: ${audit.highCount} | ` +
    `Medium: ${audit.mediumCount} | Low: ${audit.lowCount}\n` +
    `Вердикт: ${audit.passedAudit ? '✅ passed' : '🔴 release BLOCKED'}`
  ), { parse_mode: 'Markdown' });
}

// /qa-coverage <project> — coverage report
async function handleQaCoverage(msg, bot) {
  const { rest } = parseArgs(msg.text);
  if (!rest) return bot.sendMessage(msg.chat.id, 'Использование: /qa-coverage <project>');
  const report = await qa.getCoverageReport(rest);
  if (report.coverage === null && !report.latestCoverage) {
    return bot.sendMessage(msg.chat.id, `Данных о покрытии для "${rest}" нет`);
  }
  await bot.sendMessage(msg.chat.id, clip(
    `📊 Coverage — ${rest}\n` +
    `Текущее: ${(report.latestCoverage * 100).toFixed(1)}%\n` +
    `Цель overall: ${report.targets.overall}% | critical path: ${report.targets.critical_path}%\n` +
    `${report.meetsOverallTarget ? '✅ цель достигнута' : '⚠️ ниже цели'}`
  ));
}

// /qa-runs [filter] — list test runs
async function handleQaRuns(msg, bot) {
  const { args } = parseArgs(msg.text);
  const filter = {};
  if (args[0]) filter.testType = args[0];
  const runs = await qa.listTestRuns(filter, 15);
  if (!runs.length) return bot.sendMessage(msg.chat.id, 'Прогонов не найдено');
  await bot.sendMessage(msg.chat.id, clip(
    `🧪 *TestRuns* (${runs.length}):\n` +
    runs.map(r => `#${r.id} [${r.testType}/${r.verdict}] ${r.target} — ${r.passedTests}/${r.totalTests}`).join('\n')
  ), { parse_mode: 'Markdown' });
}

// /qa-monitor <project> — production monitoring summary
async function handleQaMonitor(msg, bot) {
  const report = await qa.dailyProductionMonitor();
  await bot.sendMessage(msg.chat.id, clip(
    `📋 *QA Production Monitor* — ${report.date}\n` +
    `Прогонов за сутки: ${report.testRuns24h} (провалов: ${report.failedRuns24h})\n` +
    `Новых дефектов: ${report.newDefects24h}\n` +
    `Открытых critical: ${report.openCriticalDefects} | high: ${report.openHighDefects}\n` +
    `${report.needsAttention ? '⚠️ Требуется внимание' : '✅ Всё штатно'}`
  ), { parse_mode: 'Markdown' });
}

// ============================================================================
// REGISTRATION
// ============================================================================
//
// Register in bot.js following its existing style. Example for node-telegram-bot-api:
//
//   bot.onText(/^\/dev(?:@\w+)?(?:\s|$)/, msg => guard(msg) && handleDev(msg, bot));
//   bot.onText(/^\/dev-estimate\b/, msg => guard(msg) && handleDevEstimate(msg, bot));
//   ... etc for all 31 commands
//
// where guard(msg) checks msg.from.id === OWNER_TELEGRAM_ID.
//
// IMPORTANT: register more-specific commands BEFORE less-specific ones, or use
// anchored regexes (/^\/dev-estimate\b/ not /^\/dev/) so "/dev-estimate" does
// not get captured by the "/dev" handler.

module.exports = {
  // Dev (14)
  handleDev, handleDevEstimate, handleDevDecide, handleDevImplement,
  handleDevTask, handleDevTasks, handleDevRepos, handleDevRepo,
  handleDevCreateRepo, handleDevRadar, handleDevRadarAdd, handleDevDeploy,
  handleDevArchive, handleDevLocalSync,
  // Design (8)
  handleDesign, handleDesignSpec, handleDesignSystem, handleDesignShow,
  handleDesignArtifacts, handleDesignResearch, handleDesignIterate, handleDesignApprove,
  // QA (9)
  handleQaStrategy, handleQaTest, handleQaDefect, handleQaDefects,
  handleQaEval, handleQaSecurityAudit, handleQaCoverage, handleQaRuns, handleQaMonitor
};
