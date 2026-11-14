# Инвентарь межпроцедурных потоков: секреты / вывод LLM / ввод запроса

> Наряд **#717 (SEC-1)**, п.1. Дата фиксации: 2026-11-12, main `89ae462`, mlog 0.39.0;
> пересчёт 2026-11-14 (main `3489029` + наряд #720: +2 паттерна —
> `AdminDeptSlotActive7d`, `N720KkFixture`; источники/стоки/потоки не изменились).
> Гвард пересчёта: tests/test_n717_sec1.py C-серия — любое изменение паттернов
> без регенерации чисел §1 красит CI (случай #720 — пойман живым прогоном).
> Источник: тотальный аудит Metalogos 12.11 (`docs/projects/metalogos/audit_2026-11-12/`);
> связанные: Metalogos-#1917 (№950 — межпроцедурные сводки паттернов в решётке),
> #1920 (№953 — `check --root` без исполнения), #1921 (№954), #1922 (№955).
>
> **Зачем этот документ.** Аудит языка нашёл класс дыры: taint-метка не пересекает
> границу паттерна — `env()` читается в одном паттерне, сток живёт в другом,
> интра-процедурный аудитор не видит поток. Офис пользуется этой дырой сознательно
> («швы», dept/utils.mlog:401). После №950 язык начнёт отклонять такие потоки
> (одно релизное окно — громкие предупреждения, затем ошибки). Этот инвентарь —
> карта того, что именно потребуется чинить в окне перехода (п.3–4 наряда).

## 1. Метод и сводка

**Метод.** Машинный скан производственной поверхности (36 файлов: `app.mlog`,
`dogfood_staging.mlog`, `dept/*.mlog`, `library/*.mlog`, `memories/*.mlog`;
корневые `test_*.mlog` — фикстуры тестов, вне инвентаря). Сканер:
`scripts/n717_inventory_scan.py` (мини-лексер: комментарии вырезаются, содержимое
строк маскируется — находки не рождаются в строках и комментариях; граф вызовов
паттернов по глобальным именам, как их видит `--root`-флэттен; поток значения
идёт по ОБРАТНЫМ рёбрам: источник ← вызывающий ← … ← сток). Числа этого раздела
сверяются машиной тестом `tests/test_n717_sec1.py` — документ не может разойтись
с кодом.

**Сводка (на дату фиксации):**

| Метрика | Значение |
|---|---|
| Файлов в поверхности | 36 |
| Паттернов (вхождений) | 1401 |
| Уникальных имён паттернов | 1317 |
| Конфиг-блоков верхнего уровня с env | 6 |
| Паттернов-источников всего | 215 |
| env/env_or-читатели (имена) | 36 |
| Возврат вывода LLM (call_llm) | 177 |
| Читатели ввода запроса (json_body/query_param) | 3 |
| Паттернов-стоков (уникальных имён) | 93 |
| HTTP-маршрутов serve | 75 |
| Транзитивных потоков источник→сток | 322 |
| Прямых рёбер «источник→сток» | 121 |
| Швов — источников, чьё значение достигает стока в ДРУГОМ теле | 187 |
| Интра-процедурных потоков (источник и сток в одном теле — видит аудит сегодня) | 21 |

**Классы источников и стоков** (определения наряда п.1):
источник = паттерн, возвращающий `env`/`env_or` (секрет или конфиг), вывод
`call_llm` (LLM) или читающий `json_body`/`query_param` (ввод запроса);
сток = паттерн со стоком внутри тела: `send_message`, `http_post`, `http_get`,
`exec`, `write_file`, `print`, `respond`/`respond_html`.

### 2.0 Конфиг-блоки верхнего уровня: env вне паттернов (6)

Ключи провайдеров LLM и DATABASE_URL читает сама конфигурация рантайма (`llm { providers: [...] }`, `db { url: ... }`) — вне тел паттернов; интра-процедурный аудит паттернов их не видит вообще.

| Блок | Файл:строка | env-переменные |
|---|---|---|
| `db` | app.mlog:30 | `DATABASE_URL` |
| `llm` | app.mlog:39 | `CEREBRAS_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `KIMI_API_KEY`, `SAKANA_API_KEY`, `ZAI_API_KEY` |
| `db` | dogfood_staging.mlog:20 | `DATABASE_URL` |
| `llm` | dogfood_staging.mlog:26 | `CEREBRAS_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `KIMI_API_KEY`, `SAKANA_API_KEY`, `ZAI_API_KEY` |
| `db` | dept/forge_create_bridge.mlog:19 | `DATABASE_URL` |
| `db` | dept/osp.mlog:48 | `DATABASE_URL` |

### 2.1 Паттерны-источники: env / env_or (36)

| Паттерн | Файл:строка | env-переменные | Вид |
|---|---|---|---|
| `AdminUaToken` | dept/admin.mlog:440 | `INTERNAL_API_TOKEN` | env_or |
| `ArchiveChannelId` | dept/utils.mlog:513 | `TELEGRAM_ARCHIVE_CHANNEL_ID` | env |
| `AvKey` | dept/utils.mlog:413 | `ALPHAVANTAGE_API_KEY` | env_or |
| `BridgeCreate` | dept/forge_create_bridge.mlog:21 | `FNP_CUSTOMER`, `FNP_GOAL`, `FNP_NAME`, `FNP_SLUG`, `FNP_TYPE` | env |
| `CollectNewsSlot` | dept/scheduler.mlog:456 | `CRON_SECRET` | env |
| `DeliverDueReminders` | dogfood_staging.mlog:2302 | `OWNER_TELEGRAM_ID` | env |
| `DeliverDueReminders` | dept/yana.mlog:555 | `OWNER_TELEGRAM_ID` | env |
| `ForgeCheckPipeline` | dept/forge.mlog:827 | `FORGE_RUN_ENABLED` | env |
| `ForgeCreateRepo` | dept/forge.mlog:119 | `FORGE_GITHUB_OWNER` | env |
| `ForgeReposDir` | dept/forge.mlog:18 | `FORGE_REPOS_DIR` | env |
| `GoldenEvalsSlot` | dept/scheduler.mlog:489 | `CRON_SECRET` | env |
| `HandleLZ` | dept/lz.mlog:220 | `CRON_SECRET` | env |
| `LZDailyDigest` | dept/lz.mlog:1301 | `OWNER_TELEGRAM_ID` | env |
| `LZGateOSPReferral` | dept/lz.mlog:141 | `CRON_SECRET` | env |
| `LZInflectionDetect` | dept/lz.mlog:870 | `CRON_SECRET` | env |
| `LZProvRecord` | dept/lz.mlog:667 | `METALOGOS_LLM_MODEL`, `METALOGOS_LLM_PROVIDER` | env_or |
| `NightLzPhase` | app.mlog:1743 | `OWNER_TELEGRAM_ID` | env |
| `NightTickSlot` | dept/scheduler.mlog:746 | `CRON_SECRET` | env |
| `OSPTelegramSearch` | dept/osp.mlog:1157 | `CRON_SECRET` | env |
| `OnlinerWarmSlot` | dept/scheduler.mlog:478 | `CRON_SECRET`, `SHOP_ENABLED` | env |
| `OutboxFlush` | dept/scheduler.mlog:544 | `OWNER_TELEGRAM_ID` | env |
| `OwnerTelegramId` | dept/utils.mlog:521 | `OWNER_TELEGRAM_ID` | env |
| `RenderUrl` | dept/utils.mlog:517 | `RENDER_URL` | env |
| `ReposAccessToken` | app.mlog:2033 | `CRON_SECRET` | env |
| `RequireInternalAuth` | app.mlog:825 | `INTERNAL_API_TOKEN` | env_or |
| `RequireInternalAuth` | dogfood_staging.mlog:620 | `INTERNAL_API_TOKEN` | env_or |
| `ReviewQueueCard` | dogfood_staging.mlog:500 | `TELEGRAM_BOT_TOKEN` | env |
| `SendTelegramReply` | dogfood_staging.mlog:450 | `TELEGRAM_BOT_TOKEN` | env |
| `SendTelegramReplyMDV2` | dogfood_staging.mlog:461 | `TELEGRAM_BOT_TOKEN` | env |
| `SendTyping` | dogfood_staging.mlog:483 | `TELEGRAM_BOT_TOKEN` | env |
| `ShopTickSlot` | dept/scheduler.mlog:466 | `SHOP_ENABLED` | env |
| `TavilyCacheTtlMin` | dept/utils.mlog:439 | `OSP_TAVILY_CACHE_MIN` | env_or |
| `TavilyDailyBudget` | dept/utils.mlog:429 | `OSP_TAVILY_DAILY_BUDGET` | env_or |
| `TavilyKey` | dept/utils.mlog:404 | `TAVILY_API_KEY` | env_or |
| `TgToken` | dept/utils.mlog:397 | `TELEGRAM_BOT_TOKEN` | env |
| `WebhookBody` | app.mlog:2739 | `CRON_SECRET`, `LOCKDOWN_PASSWORD`, `OWNER_TELEGRAM_ID`, `RENDER_URL` | env |
| `_RunInScratch` | dept/forge.mlog:1026 | `METALOGOS_EXEC_TIMEOUT_SECS` | env |
| `_RunMemLimitKB` | dept/forge.mlog:930 | `FORGE_RUN_VLIMIT_KB` | env |

### 2.2 Паттерны-источники: вывод LLM — call_llm (177)

Возврат call_llm наружу; полный список имён — в JSON-выгрузке сканера (регенерация: `python3 scripts/n717_inventory_scan.py --json`). Ключевые швы-обёртки: `LZLlm` (dept/lz_seam.mlog:16), `CallLLMProxy`/`CallLLMResilient` (app.mlog), `KKAskForDept` (app.mlog:5819), хендлеры отделов (`HandleLZ`, `HandleOSP`, `HandleAdmin`, …).

### 2.3 Паттерны-источники: ввод запроса — json_body / query_param (3)

| Паттерн | Файл:строка | Вид |
|---|---|---|
| `ReposAccessGuard` | app.mlog:2039 | query_param |
| `ReposTaskPage` | app.mlog:2669 | query_param |
| `WebhookBody` | app.mlog:2739 | json_body |

### 2.4 Паттерны-стоки (93 уникальных имён)

| Паттерн | Файл:строка | Стоки |
|---|---|---|
| `AdminAnalyze` | dept/admin.mlog:682 | http_get |
| `AdminDocs` | dept/admin.mlog:757 | http_get |
| `AdminGraph` | dept/admin.mlog:768 | http_get |
| `AdminHealth` | dept/admin.mlog:860 | http_get |
| `AdminImpact` | dept/admin.mlog:781 | http_get |
| `AdminNightCycle` | dept/admin.mlog:450 | http_get |
| `AdminReplySlot` | dept/scheduler.mlog:436 | http_post |
| `AdminScan` | dept/admin.mlog:723 | http_get |
| `AdminTour` | dept/admin.mlog:734 | http_get |
| `AttachRatingRow` | dept/miniapp.mlog:162 | http_post |
| `BuildContext` | dogfood_staging.mlog:1021 | http_post |
| `BuildContext` | dept/context.mlog:9 | http_post |
| `BuildOSPContext` | dept/osp.mlog:678 | http_post |
| `CallLLMProxy` | app.mlog:717 | http_post |
| `CallLLMProxy` | dogfood_staging.mlog:537 | http_post |
| `CallLLMResilient` | app.mlog:899 | http_post |
| `CallLLMResilient` | dogfood_staging.mlog:688 | http_post |
| `CollectNewsSlot` | dept/scheduler.mlog:456 | http_get |
| `CreateDefect` | dept/qa.mlog:396 | send_message |
| `DetectDepartment` | app.mlog:1652 | http_post |
| `DetectDepartment` | dogfood_staging.mlog:1742 | http_post |
| `ExpertGenerateChart` | dept/expert.mlog:633 | http_post |
| `ForgeCreateRepo` | dept/forge.mlog:119 | http_post |
| `ForgeGateSend` | dept/forge.mlog:1332 | http_post |
| `ForgeRollback` | dept/forge.mlog:300 | exec |
| `ForgeRunScript` | dept/forge.mlog:57 | exec, write_file |
| `ForgeWriteFiles` | dept/forge.mlog:222 | exec, write_file |
| `GenerateAnalysisCardEx` | dept/visual.mlog:315 | http_post |
| `GetOwnerProfile` | dogfood_staging.mlog:1141 | http_post |
| `GetOwnerProfile` | dept/context.mlog:129 | http_post |
| `GoldenEvalsSlot` | dept/scheduler.mlog:489 | http_post |
| `HandleDesignImage` | app.mlog:1205 | http_post |
| `HandleDesignImage` | dogfood_staging.mlog:999 | http_post |
| `HandleLZ` | dept/lz.mlog:220 | http_post |
| `HandleMiniAppAction` | dept/miniapp.mlog:302 | send_message |
| `IndicatorRemindersSlot` | dept/scheduler.mlog:497 | http_post |
| `KKStructuralFetch` | dept/kk_training.mlog:390 | http_get |
| `LZDailyDigest` | dept/lz.mlog:1301 | http_post |
| `LZFactpack` | dept/lz.mlog:1011 | http_post |
| `LZGateOSPReferral` | dept/lz.mlog:141 | http_post |
| `LZInflectionDetect` | dept/lz.mlog:870 | http_post |
| `LzDailySlot` | dept/scheduler.mlog:443 | http_post |
| `MorningBrief` | dept/scheduler.mlog:132 | http_post |
| `NaradSendButtons` | dept/narad.mlog:167 | http_post |
| `NightLzPhase` | app.mlog:1743 | http_post |
| `NightSlot` | app.mlog:1793 | http_post |
| `NightSlot` | dogfood_staging.mlog:120 |  |
| `NightTickCore` | app.mlog:5929 | respond |
| `NightTickSlot` | dept/scheduler.mlog:746 | http_get, http_post |
| `NotifyDevHotfix` | dept/qa.mlog:1818 | send_message |
| `OSPBenchFetchSet` | dept/osp.mlog:2943 | http_get |
| `OSPBenchResolve` | dept/osp.mlog:3268 | http_get |
| `OSPCalibrationCurve` | dept/osp.mlog:2326 | write_file |
| `OSPCurveCommand` | dept/osp.mlog:2785 | http_post |
| `OSPTelegramSearch` | dept/osp.mlog:1157 | http_post |
| `OnlinerWarmSlot` | dept/scheduler.mlog:478 | http_post |
| `PollJobStatus` | dept/scheduler.mlog:694 | http_get |
| `PublishToArchive` | dept/utils.mlog:157 | http_post |
| `RecallLearnings` | app.mlog:1415 | http_post |
| `RecallLearnings` | dogfood_staging.mlog:1538 | http_post |
| `RecordLearning` | app.mlog:1404 | http_post |
| `RecordLearning` | dogfood_staging.mlog:1527 | http_post |
| `ReleaseGate` | dept/qa.mlog:1408 | send_message |
| `ReminderCheck` | dept/scheduler.mlog:390 | http_post |
| `RenderCardPdfViaProxy` | dept/visual.mlog:1016 | http_post |
| `RenderCardPngViaProxy` | dept/visual.mlog:1048 | http_post |
| `RenderSvgPdfViaProxy` | dept/visual.mlog:1034 | http_post |
| `ReposTaskPage` | app.mlog:2669 | respond |
| `ReviewQueueCard` | app.mlog:680 | http_post |
| `ReviewQueueCard` | dogfood_staging.mlog:500 | http_post |
| `RouteAmbiguous` | dept/route_eval.mlog:99 | http_post |
| `RunDailyCheck` | dept/legal.mlog:741 | send_message |
| `SaveDialogV2` | app.mlog:623 | http_post |
| `SaveDialogV2` | dogfood_staging.mlog:443 | http_post |
| `ScanApiSources` | dept/lz.mlog:1141 | http_post |
| `ScanGitHub` | dept/lz.mlog:1130 | http_post |
| `ScanReddit` | dept/lz.mlog:1162 | http_post |
| `ScanSocial` | dept/lz.mlog:1174 | http_post |
| `ScanTelegram` | dept/lz.mlog:1185 | http_post |
| `ScanWeb` | dept/lz.mlog:1120 | http_post |
| `ScanYouTube` | dept/lz.mlog:1151 | http_post |
| `SendAdminButtons` | dept/admin.mlog:152 | http_post |
| `SendAdminMessage` | dept/admin.mlog:145 | http_post |
| `SendReport` | dept/miniapp.mlog:188 | http_post |
| `SendReportMiniAppMessage` | dept/miniapp.mlog:173 | http_post |
| `SendTelegramReply` | app.mlog:630 | http_post |
| `SendTelegramReply` | dogfood_staging.mlog:450 | http_post |
| `SendTelegramReplyMDV2` | app.mlog:641 | http_post |
| `SendTelegramReplyMDV2` | dogfood_staging.mlog:461 | http_post |
| `SendTelegramReplyRatings` | dept/miniapp.mlog:145 | http_post |
| `SendTyping` | app.mlog:663 | http_post |
| `SendTyping` | dogfood_staging.mlog:483 | http_post |
| `SendVisualDocument` | dept/visual.mlog:67 | http_post |
| `SendVisualPhoto` | dept/visual.mlog:80 | http_post |
| `SendVoiceReply` | dept/utils.mlog:278 | http_post |
| `ShopTickSlot` | dept/scheduler.mlog:466 | http_post |
| `SnapshotToTelegramArchive` | dept/dev.mlog:1208 | send_message |
| `TavilySearch` | dept/utils.mlog:456 | http_post |
| `UpdateConsensus` | app.mlog:1378 | write_file |
| `UpdateConsensus` | dogfood_staging.mlog:1504 | write_file |
| `WebhookBody` | app.mlog:2739 | http_get, http_post, respond, send_message, write_file |
| `YanaAutoMemorize` | dogfood_staging.mlog:2152 | http_post |
| `YanaAutoMemorize` | dept/yana.mlog:405 | http_post |
| `YanaCheckShop` | dogfood_staging.mlog:2204 | http_post |
| `YanaCheckShop` | dept/yana.mlog:447 | http_post |
| `YanaNowInfo` | dogfood_staging.mlog:2095 | http_get |
| `YanaNowInfo` | dept/yana.mlog:345 | http_get |
| `YanaRecallMemories` | dogfood_staging.mlog:2117 | http_post |
| `YanaRecallMemories` | dept/yana.mlog:369 | http_post |
| `YanaWeather` | dogfood_staging.mlog:2109 | http_get |
| `YanaWeather` | dept/yana.mlog:361 | http_get |
| `_RunInScratch` | dept/forge.mlog:1026 | write_file |
| `call_python` | app.mlog:1727 | http_post |
| `call_python` | dogfood_staging.mlog:2451 | http_post |

### 2.5 Прямые рёбра «источник → сток» (121; redact — эвристика той же строки)

| Источник | Сток-паттерн | Сток-библиотеки | redact на call-site |
|---|---|---|---|
| `AdminUaToken` | `AdminAnalyze` (dept/admin.mlog:682) | http_get | да |
| `AdminUaToken` | `AdminDocs` (dept/admin.mlog:757) | http_get | да |
| `AdminUaToken` | `AdminGraph` (dept/admin.mlog:768) | http_get | да |
| `AdminUaToken` | `AdminImpact` (dept/admin.mlog:781) | http_get | да |
| `AdminAutoFix` | `AdminNightCycle` (dept/admin.mlog:450) | http_get | **нет** |
| `AdminMetricsAnalysis` | `AdminNightCycle` (dept/admin.mlog:450) | http_get | **нет** |
| `AdminProposals` | `AdminNightCycle` (dept/admin.mlog:450) | http_get | **нет** |
| `AdminUaToken` | `AdminNightCycle` (dept/admin.mlog:450) | http_get | **нет** |
| `OwnerTelegramId` | `AdminReplySlot` (dept/scheduler.mlog:436) | http_post | **нет** |
| `AdminUaToken` | `AdminScan` (dept/admin.mlog:723) | http_get | да |
| `AdminTour` | `AdminTour` (dept/admin.mlog:734) | http_get | **нет** |
| `AdminUaToken` | `AdminTour` (dept/admin.mlog:734) | http_get | да |
| `TgToken` | `AttachRatingRow` (dept/miniapp.mlog:162) | http_post | **нет** |
| `CollectNewsSlot` | `CollectNewsSlot` (dept/scheduler.mlog:456) | http_get | **нет** |
| `ForgeCreateRepo` | `ForgeCreateRepo` (dept/forge.mlog:119) | http_post | **нет** |
| `ForgeReposDir` | `ForgeCreateRepo` (dept/forge.mlog:119) | http_post | **нет** |
| `OwnerTelegramId` | `ForgeGateSend` (dept/forge.mlog:1332) | http_post | **нет** |
| `TgToken` | `ForgeGateSend` (dept/forge.mlog:1332) | http_post | **нет** |
| `ForgeReposDir` | `ForgeRollback` (dept/forge.mlog:300) | exec | **нет** |
| `ForgeCheckPipeline` | `ForgeWriteFiles` (dept/forge.mlog:222) | exec, write_file | **нет** |
| `ForgeReposDir` | `ForgeWriteFiles` (dept/forge.mlog:222) | exec, write_file | **нет** |
| `GoldenEvalsSlot` | `GoldenEvalsSlot` (dept/scheduler.mlog:489) | http_post | **нет** |
| `SendTelegramReply` | `HandleDesignImage` (app.mlog:1205) | http_post | **нет** |
| `SendTelegramReply` | `HandleDesignImage` (dogfood_staging.mlog:999) | http_post | **нет** |
| `HandleLZ` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZAllScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZChannelDigest` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZCrossDomainTransfer` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZDarkWebResearch` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZDeepResearcherProfile` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZDeepScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZEconomicsScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZEventsScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZGateOSPReferral` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZGeopoliticsScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZGithubUpdates` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZInflectionDetect` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZLeakedRoadmap` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZOrderOfBattle` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZPoliticsScan` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZTavilySearch` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `LZTelegramSearch` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `TeamSecondPass` | `HandleLZ` (dept/lz.mlog:220) | http_post | **нет** |
| `HandleMiniAppAction` | `HandleMiniAppAction` (dept/miniapp.mlog:302) | send_message | **нет** |
| `LZDailyDigest` | `LZDailyDigest` (dept/lz.mlog:1301) | http_post | **нет** |
| `TgToken` | `LZDailyDigest` (dept/lz.mlog:1301) | http_post | **нет** |
| `TavilyKey` | `LZFactpack` (dept/lz.mlog:1011) | http_post | **нет** |
| `LZGateOSPReferral` | `LZGateOSPReferral` (dept/lz.mlog:141) | http_post | да |
| `LZInflectionDetect` | `LZInflectionDetect` (dept/lz.mlog:870) | http_post | **нет** |
| `LZLlm` | `LZInflectionDetect` (dept/lz.mlog:870) | http_post | да |
| `LZProvRecord` | `LZInflectionDetect` (dept/lz.mlog:870) | http_post | **нет** |
| `OwnerTelegramId` | `LzDailySlot` (dept/scheduler.mlog:443) | http_post | **нет** |
| `TgToken` | `NaradSendButtons` (dept/narad.mlog:167) | http_post | **нет** |
| `NightLzPhase` | `NightLzPhase` (app.mlog:1743) | http_post | **нет** |
| `AdminUaToken` | `NightSlot` (app.mlog:1793) | http_post | **нет** |
| `NightLzPhase` | `NightSlot` (app.mlog:1793) | http_post | **нет** |
| `NightTickSlot` | `NightTickCore` (app.mlog:5929) | respond | **нет** |
| `NightTickSlot` | `NightTickSlot` (dept/scheduler.mlog:746) | http_get, http_post | **нет** |
| `OSPTelegramSearch` | `OSPTelegramSearch` (dept/osp.mlog:1157) | http_post | **нет** |
| `OnlinerWarmSlot` | `OnlinerWarmSlot` (dept/scheduler.mlog:478) | http_post | **нет** |
| `ArchiveChannelId` | `PublishToArchive` (dept/utils.mlog:157) | http_post | **нет** |
| `RenderUrl` | `PublishToArchive` (dept/utils.mlog:157) | http_post | **нет** |
| `TgToken` | `PublishToArchive` (dept/utils.mlog:157) | http_post | **нет** |
| `ReposTaskPage` | `ReposTaskPage` (app.mlog:2669) | respond | да |
| `ReviewQueueCard` | `ReviewQueueCard` (app.mlog:680) | http_post | **нет** |
| `SendTelegramReply` | `ReviewQueueCard` (app.mlog:680) | http_post | **нет** |
| `TgToken` | `ReviewQueueCard` (app.mlog:680) | http_post | **нет** |
| `ReviewQueueCard` | `ReviewQueueCard` (dogfood_staging.mlog:500) | http_post | **нет** |
| `SendTelegramReply` | `ReviewQueueCard` (dogfood_staging.mlog:500) | http_post | **нет** |
| `TgToken` | `SendAdminButtons` (dept/admin.mlog:152) | http_post | **нет** |
| `TgToken` | `SendAdminMessage` (dept/admin.mlog:145) | http_post | **нет** |
| `RenderUrl` | `SendReport` (dept/miniapp.mlog:188) | http_post | **нет** |
| `SendTelegramReply` | `SendReport` (dept/miniapp.mlog:188) | http_post | **нет** |
| `SendTelegramReplyMDV2` | `SendReport` (dept/miniapp.mlog:188) | http_post | **нет** |
| `TgToken` | `SendReport` (dept/miniapp.mlog:188) | http_post | **нет** |
| `SendTelegramReply` | `SendTelegramReply` (app.mlog:630) | http_post | **нет** |
| `TgToken` | `SendTelegramReply` (app.mlog:630) | http_post | **нет** |
| `SendTelegramReply` | `SendTelegramReply` (dogfood_staging.mlog:450) | http_post | **нет** |
| `SendTelegramReplyMDV2` | `SendTelegramReplyMDV2` (app.mlog:641) | http_post | **нет** |
| `TgToken` | `SendTelegramReplyMDV2` (app.mlog:641) | http_post | **нет** |
| `SendTelegramReplyMDV2` | `SendTelegramReplyMDV2` (dogfood_staging.mlog:461) | http_post | **нет** |
| `SendTelegramReply` | `SendTelegramReplyRatings` (dept/miniapp.mlog:145) | http_post | **нет** |
| `TgToken` | `SendTelegramReplyRatings` (dept/miniapp.mlog:145) | http_post | **нет** |
| `SendTyping` | `SendTyping` (app.mlog:663) | http_post | **нет** |
| `TgToken` | `SendTyping` (app.mlog:663) | http_post | **нет** |
| `SendTyping` | `SendTyping` (dogfood_staging.mlog:483) | http_post | **нет** |
| `ShopTickSlot` | `ShopTickSlot` (dept/scheduler.mlog:466) | http_post | **нет** |
| `TavilyCacheTtlMin` | `TavilySearch` (dept/utils.mlog:456) | http_post | **нет** |
| `TavilyDailyBudget` | `TavilySearch` (dept/utils.mlog:456) | http_post | **нет** |
| `TavilyKey` | `TavilySearch` (dept/utils.mlog:456) | http_post | **нет** |
| `AdminBuild` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `AdminProposals` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `AdminTour` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `CROAudit` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `DebriefDepartment` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `EveningSummary` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `GetRelevantIdeas` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleAdmin` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleExpert` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleFinance` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleKavalnya` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleLZ` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleMarketing` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleMiniAppAction` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleOSP` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `HandleVisual` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `LZAllScan` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `LZDeepResearcherProfile` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `LZDeepScan` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `ReviewQueueCard` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `SendTelegramReply` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | да |
| `SendTyping` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | да |
| `TgToken` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | **нет** |
| `WebhookBody` | `WebhookBody` (app.mlog:2739) | http_get, http_post, respond, send_message, write_file | да |
| `SendTelegramReply` | `YanaCheckShop` (dogfood_staging.mlog:2204) | http_post | **нет** |
| `SendTelegramReply` | `YanaCheckShop` (dept/yana.mlog:447) | http_post | да |
| `ForgeReposDir` | `_RunInScratch` (dept/forge.mlog:1026) | write_file | **нет** |
| `_EnvDefault` | `_RunInScratch` (dept/forge.mlog:1026) | write_file | **нет** |
| `_MaskSecrets` | `_RunInScratch` (dept/forge.mlog:1026) | write_file | да |
| `_RunInScratch` | `_RunInScratch` (dept/forge.mlog:1026) | write_file | **нет** |
| `_RunMemLimitKB` | `_RunInScratch` (dept/forge.mlog:1026) | write_file | **нет** |

### 2.6 Интра-процедурные потоки — источник и сток в одном теле (21)

Эти потоки интра-процедурный аудит видит уже сегодня (базовая линия #633).

| Паттерн | Файл:строка | Источники | Стоки |
|---|---|---|---|
| `SendTelegramReply` | dogfood_staging.mlog:450 | env | http_post |
| `SendTelegramReplyMDV2` | dogfood_staging.mlog:461 | env | http_post |
| `SendTyping` | dogfood_staging.mlog:483 | env | http_post |
| `ReviewQueueCard` | dogfood_staging.mlog:500 | env | http_post |
| `NightLzPhase` | app.mlog:1743 | env | http_post |
| `ReposTaskPage` | app.mlog:2669 | query_param | respond |
| `WebhookBody` | app.mlog:2739 | env, json_body, llm | http_get, http_post, respond, send_message, write_file |
| `AdminTour` | dept/admin.mlog:734 | llm | http_get |
| `ForgeCreateRepo` | dept/forge.mlog:119 | env | http_post |
| `_RunInScratch` | dept/forge.mlog:1026 | env | write_file |
| `LZGateOSPReferral` | dept/lz.mlog:141 | env, llm | http_post |
| `HandleLZ` | dept/lz.mlog:220 | env, llm | http_post |
| `LZInflectionDetect` | dept/lz.mlog:870 | env | http_post |
| `LZDailyDigest` | dept/lz.mlog:1301 | env, llm | http_post |
| `HandleMiniAppAction` | dept/miniapp.mlog:302 | llm | send_message |
| `OSPTelegramSearch` | dept/osp.mlog:1157 | env | http_post |
| `CollectNewsSlot` | dept/scheduler.mlog:456 | env | http_get |
| `ShopTickSlot` | dept/scheduler.mlog:466 | env | http_post |
| `OnlinerWarmSlot` | dept/scheduler.mlog:478 | env | http_post |
| `GoldenEvalsSlot` | dept/scheduler.mlog:489 | env | http_post |
| `NightTickSlot` | dept/scheduler.mlog:746 | env | http_get, http_post |

## 3. Классификация env-переменных офиса

Полный контракт боевых переменных — `METALOGOS_ENV_ALLOWLIST_CENSUS`
(entrypoint.sh:130, гвард №424) + Python-слой (`INTEGRATIONS_REGISTRY`,
proxy/core.py:381 — 14 ключей после #715 KEYS-2, и `WHISPER_API_KEY`,
proxy/core.py:163). Классы:

| Класс | Переменные | Комментарий |
|---|---|---|
| **Секреты-учётные данные** | `TELEGRAM_BOT_TOKEN`, `TAVILY_API_KEY`, `ALPHAVANTAGE_API_KEY`, `CRON_SECRET`, `INTERNAL_API_TOKEN`, `LOCKDOWN_PASSWORD`, `TELEGRAM_WEBHOOK_SECRET`, `API_SECRET`, `GITHUB_TOKEN_METALOGOS`, `WHISPER_API_KEY` | Значение = мандат; утечка в лог/ответ/URL-параметр — инцидент |
| **Ключи провайдеров LLM** | `DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `ZAI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `SAKANA_API_KEY` (+ Python-only: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `QWEN_API_KEY`) | Читает конфиг-блок `llm {}` mlog-рантайма и Python-слой `get_secret` |
| **Чувствительный конфиг (идентификаторы владельца)** | `OWNER_TELEGRAM_ID`, `TELEGRAM_ARCHIVE_CHANNEL_ID` | Не мандаты, но персональные данные; уходят в chat_id сообщений |
| **Конфиг (не секреты)** | `RENDER_URL`, `SHOP_ENABLED`, `OSP_TAVILY_DAILY_BUDGET`, `OSP_TAVILY_CACHE_MIN`, `METALOGOS_LLM_MODEL`, `METALOGOS_LLM_PROVIDER`, `METALOGOS_EXEC_TIMEOUT_SECS`, `FORGE_REPOS_DIR`, `FORGE_RUN_ENABLED`, `FORGE_RUN_VLIMIT_KB`, `FORGE_GITHUB_OWNER`, `FNP_*`, `TEAM_MAX_CONSULTS`, `TEAM_MAX_LLM_CALLS`, `DATABASE_URL` | Пороги, флаги, пути; `DATABASE_URL` — строка подключения (может нести креды СУБД, но в офисе это `sqlite:...`) |

## 4. Трассировка `TELEGRAM_BOT_TOKEN`

**Где читается.**

| Слой | Место | Вид |
|---|---|---|
| mlog | `TgToken()` — dept/utils.mlog:397 (**шов**, тело — голый `env`, без стоков) | значение |
| mlog | `SendTelegramReply` / `SendTelegramReplyMDV2` / `SendTyping` / `ReviewQueueCard` — dogfood_staging.mlog:449/460/482/499 (инлайн `env`, staging-копии без шва) | значение |
| Python | proxy/core.py:161 (`os.environ.get`), оттуда импортируют telegram.py, guardian.py, routes_admin.py, routes_tail.py, llm_proxy.py, budget.py:144 | значение |
| Python | proxy/core.py:254 — HMAC-SHA256 ключ для валидации WebAppData (миниапп) | крипто-использование, наружу не уходит |

**Куда уходит значение (mlog).** 18 сток-паттернов достижимо из `TgToken`
(машинный список §2.5/JSON): `SendTelegramReply`, `SendTelegramReplyMDV2`,
`SendTyping`, `SendTelegramReplyRatings`, `SendAdminMessage`, `SendAdminButtons`,
`NaradSendButtons`, `AttachRatingRow` (dept/miniapp), `PublishToArchive`
(dept/utils:193 — архивный канал), `SendReport` (dept/miniapp), `ReviewQueueCard`
(app:679), `ForgeGateSend` (dept/forge:1346), `LZDailyDigest` (dept/lz:1313 —
там же инлайн `env("OWNER_TELEGRAM_ID")` под `redact`), `YanaCheckShop`,
`HandleLZ`/`HandleMiniAppAction`/`HandleDesignImage` (через вложенные вызовы),
`WebhookBody` (транзитивно).

Форма ухода — всегда одна: **конкатенация в URL** `https://api.telegram.org/bot`
+ токен + `/sendMessage|/sendChatAction|/answerCallbackQuery|…` → `http_post`.
Заголовки — только `Content-Type: application/json`; **в заголовках токен не
ходит никогда**. Builtin `send_message` (30 вызовов) токен не принимает вовсе —
его добавляет сам рантайм.

**Куда уходит значение (Python).** proxy/telegram.py (`/bot{TOKEN}/sendMessage`,
voice/photo/report), proxy/guardian.py:342 (`answerCallbackQuery`), budget.py:144.

**Логи.** Токен в логи не пишется: в mlog `AuditLog`-строки несут счётчики токенов
LLM (`tokens=in+out`), не значения (проверено грепом по поверхности); в Python —
только предупреждения «TELEGRAM_BOT_TOKEN not set» (telegram.py:123,148,290,360);
вывод forge маскирует `_MaskSecrets` (dept/forge.mlog:991 — подмена значений
на `***` перед записью в БД/экран).

**Вывод для №950.** Все 18 стоков — легальный сток Bot API; миграция — не
`redact` (токен обязан дойти до Telegram), а аннотация разрешённой позиции
(allowed sink для `api.telegram.org/bot*`) либо перенос конкатенации в один
санкционированный хелпер. Инлайн-читатели dogfood_staging унифицировать с швом
`TgToken` (см. §6).

## 5. Трассировка ключей провайдеров

**mlog-слой.** Ключи провайдеров читает ТОЛЬКО конфиг-блок `llm { providers: […] }`
(app.mlog:39, dogfood_staging.mlog:26; §2.0) — 6 алиасов: deepseek/kimi/zai/groq/
cerebras/sakana, каждый `key: env("<KEY>")` + `url` конечной точки. Значения
потребляет LLM-клиент рантайма при `call_llm` (failover: auto, circuit_breaker: 3);
литеральных чтений ключей провайдеров в телах паттернов нет. Единственный
паттерн, трогающий их динамически, — `_MaskSecrets` (dept/forge.mlog:991):
`env(to_string(key))` по списку из 13 имён — значения подменяются на `***` ещё
внутри тела и наружу не уходят (маскирование forge-вывода; сканер честно помечает
его источником `env` без списка литералов — чтение динамическое).
`ALPHAVANTAGE_API_KEY` (`AvKey`, dept/utils.mlog:413) — **только проверка
наличия** (`trim(AvKey()) != ""`, dept/osp.mlog:626/661): значение наружу не
уходит, сам ключ в MCP-запрос добавляет Python-слой сервера markets.
`TAVILY_API_KEY` (`TavilyKey`, dept/utils.mlog:403) — значение уходит в ТЕЛЕ
`http_post` на `https://api.tavily.com/search` (`TavilySearch`,
dept/utils.mlog:473, `json_encode({api_key: …})`) — легальный сток Tavily API.

**Python-слой.** Единая точка чтения — `get_secret(name)` (proxy/core.py:343):
сначала `secrets_store` (БД, расшифровка `secrets_crypto`), иначе env. Дальше:

| Ключ | Точка ухода | Форма |
|---|---|---|
| все провайдеры OpenAI-совместимые | proxy/providers.py:293 | заголовок `Authorization: Bearer <key>` на `prov["url"]` |
| Anthropic | proxy/providers.py:303 | заголовок `x-api-key: <key>` (+ `anthropic-version`) |
| Z.ai SDK | proxy/providers.py:888 `_zai_headers` | `Authorization: Bearer`, `X-Z-AI-From`, `X-Chat-Id`, `X-User-Id` |
| Whisper (STT) | voice-конвейер (core.py:163) | заголовок провайдера |

**Логи.** Учёт вызовов пишет только маску: `record_call(..., mask_key(api_key), …)`
(providers.py:274,485; маска — `secrets_crypto.mask_value`, usage_by_key.py:53);
значений ключей в логах Python-слоя нет.

**Вывод для №950.** Конфиг-блок `llm {}` — привилегированная позиция рантайма,
не паттерн: после №950 ожидается, что язык даст конфигу явную аннотацию доверия
(источник-в-конфиге → легальный сток провайдера). Для mlog-паттернов ничего
не меняется — они ключей не видят.

## 6. Швы: реестр и что изменит №950

**Шов** (устоявшийся термин офиса, №312/№421) — паттерн, чьё тело читает `env`
и не содержит стоков, а значение утекает в сток ДРУГОГО паттерна через вызов.
Интра-процедурный аудитор не видит ни в одном из двух тел нарушения. Канонические
швы (комментарии в dept/utils.mlog:401-403, 511-512):

| Шов | Файл:строка | env | Основные стоки (полный список — §2.5/JSON) |
|---|---|---|---|
| `TgToken` | dept/utils.mlog:397 | `TELEGRAM_BOT_TOKEN` | 18 стоков (§4) |
| `TavilyKey` | dept/utils.mlog:403 | `TAVILY_API_KEY` | `TavilySearch` (тело POST), `LZFactpack`, `BuildOSPContext`, `HandleLZ`, `WebhookBody` |
| `AvKey` | dept/utils.mlog:413 | `ALPHAVANTAGE_API_KEY` | только presence-check (значение не уходит) |
| `ArchiveChannelId` | dept/utils.mlog:513 | `TELEGRAM_ARCHIVE_CHANNEL_ID` | `PublishToArchive`, `SendReport`, … |
| `RenderUrl` | dept/utils.mlog:517 | `RENDER_URL` | `PublishToArchive`, `SendReport`, … (ссылки в сообщениях) |
| `OwnerTelegramId` | dept/utils.mlog:521 | `OWNER_TELEGRAM_ID` | `AdminReplySlot`, `ForgeGateSend`, `LzDailySlot`, `MorningBrief`, … |
| `LZLlm` | dept/lz_seam.mlog:16 | — (вывод LLM) | `HandleLZ`, `LZInflectionDetect`, `WebhookBody` |

Машинная метрика: **187** паттернов-источников (из 215) достигают стока в другом
теле — т.е. 87 % всех потоков офиса сегодня невидимы аудиту. Из них:
env-швы (36 имён env-читателей, из них канонические 6 выше плюс инлайн-читатели
scheduler/forge/yana/osp/lz и staging-копии), LLM-швы (177 имён — вывод
`call_llm` уходит в сообщения/стоки почти без исключений), ввод запроса
(`WebhookBody` — `json_body`; `ReposAccessGuard`/`ReposTaskPage` — `query_param`).

**Что изменит №950** (по наряду аудита №950→gh#1917): решётка получит межпро-
цедурные сводки — источник внутри паттерна, параметр→сток, фикс-точка. Ожидаемое
следствие для офиса (проверяется прогоном на кандидате, п.3): сегодняшние
`SECRET_EGRESS = 9` в базовой линии #633 вырастут на все env-швы со значимым
стоком (порядка десятков находок `SECRET_EGRESS_NETWORK` на URL Bot API/Tavily),
`UNTRUSTED_EGRESS` — на ввод запроса; окно предупреждений — миграция, окно
ошибок — красный CI до её завершения.

## 7. План миграции (заготовка; уточняется прогоном п.3 на кандидате №950)

1. **Легальные стоки — аннотациями, не redact.** Токен Bot API обязан дойти до
   `api.telegram.org`; ключ Tavily — до `api.tavily.com`. Форма после №950:
   разрешённая позиция стока (allowed-sink аннотация на хелпере-отправителе)
   либо единый санкционированный хелпер на семейство стоков. Кандидаты:
   `SendTelegramReply*`/`SendTyping`/`SendAdmin*`/`NaradSendButtons` — единая
   точка `TgPost(method, body)` с одной аннотацией вместо 18.
2. **Presence-check без значения** (`AvKey`, `TeamEnvCount`, `LZProvRecord`,
   пороги/флаги) — рефактор на нераспространяющую форму (`env_or` с дефолтом +
   булев хелпер) или аннотация «значение не тейнтит».
3. **Сравнения секретов** (`SecretMatches`, `RequireInternalAuth`,
   `LOCKDOWN_PASSWORD` в `WebhookBody`) — уже под `redact(…, "hash_only")`;
   после №950 ожидается прохождение как есть, проверить на кандидате.
4. **LLM-вывод** — сегодня почти все call-site уже под `redact(…, "all")`
   (эвристика §2.5; полный аудит немаркированных — в п.3). Немаркированные
   точки добить redact на входе в сток.
5. **Staging-инлайны** — dogfood_staging.mlog (4 паттерна с инлайн
   `env("TELEGRAM_BOT_TOKEN")`) унифицировать с швом `TgToken`, чтобы миграция
   была в одной точке.
6. **Базовая линия** `mlog_baseline_gate` (#633) пересчитывается явно по
   результатам п.3 (счётчик новых находок — в комментарий гейта и PR), до
   перехода окна предупреждений — только наблюдение.

## 8. Регенерация и верификация

```bash
python3 scripts/n717_inventory_scan.py            # сводка (числа §1)
python3 scripts/n717_inventory_scan.py --json     # полная выгрузка (потоки, швы, рёбра)
python3 scripts/n717_inventory_scan.py --md       # фрагменты §2
pytest tests/test_n717_sec1.py -q                 # гварды: док не разошёлся с кодом
```

Таблицы §2 сгенерированы сканером и сверены тестом; §3–§7 — курируемые трассы
по тем же файлам. Правило поддержки: любое изменение env-чтений/стоков в
поверхности обязано обновлять этот документ (тест краснеет при расхождении
чисел §1 с живым сканом).
