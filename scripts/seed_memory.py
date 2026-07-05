#!/usr/bin/env python3
"""
Seed FosvedMemory with initial knowledge base from SKILL_FOSVED_MEMORY_AGENT.md.
Run once on first deploy, or to re-seed after DB reset.

Usage:
    python3 scripts/seed_memory.py [--db data/memory.db] [--force]
"""

import sys
import os

# Add parent dir to path so we can import lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.fosved_memory import FosvedMemory


INITIAL_MEMORIES = [
    # ═══════════════════ FACTS ═══════════════════
    {"content": "Архитектура: 3 процесса — reverse_proxy(10000), Metalogos(10001), llm_proxy(4000)", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "Metalogos v0.7.10, 66 builtins, Rust, ubuntu:24.04", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "14 отделов: yana, osp, lz, expert, marketing, finance, legal, dev, design, qa, visual, engineering, kavalnya, admin", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "164 скилла, 20 SQLite таблиц, 7 LLM провайдеров", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "Telegram bot: @fosved_office_v2_bot, owner: 2044005421", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "Render deploy, auto-deploy on git push, service srv-d8gjquflk1mc73evf02g", "type": "fact", "confidence": 1.0, "source": "architecture"},
    {"content": "app.mlog — главный файл (~1500 строк), webhook handler, DELEGATE routing", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "llm_proxy.py — Python proxy (~2000 строк), LLM failover + Mini App HTML generation", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "file_cache*.mlog — транслитерированные профили и скиллы (парсер крашится на кириллице)", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "reverse_proxy.py — Flask proxy на порту 10000, маршрутизирует к Metalogos и llm_proxy", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "entrypoint.sh — стартовый скрипт: llm_proxy → mlog serve → reverse_proxy с healthcheck", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "bin/mlog — Rust binary, парсит .mlog файлы. contains() и has_field() возвращают Bool, не Float", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "Render Docker context limit: 100MB. Без .dockerignore контекст 143MB — silent failure", "type": "fact", "confidence": 1.0, "source": "deploy"},
    {"content": ".dockerignore критически важен: исключает skills/, upload/, __pycache__, отчёты, .git", "type": "fact", "confidence": 1.0, "source": "deploy"},
    {"content": "memory { persist: ... } синтаксис НЕ поддерживается текущим mlog binary — вызывает parse error", "type": "fact", "confidence": 1.0, "source": "code"},
    {"content": "Dockerfile: COPY bin/mlog ПЕРЕД COPY . . (иначе бинарник перезаписывается)", "type": "fact", "confidence": 1.0, "source": "deploy"},

    # ═══════════════════ DECISIONS ═══════════════════
    {"content": "Палитра: 14 утверждённых цветов, Яна = RAL 7016 антрацит (#293133)", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Бейджи: ✓ ФАКТ (#16a34a), ◆ АНАЛИЗ (#2563eb), ⚡ ГИПОТЕЗА (#ca8a04)", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Дизайн-система: Cormorant Garamond + DM Sans + DM Mono, чёрно-золотая (#0F0F0F + #C9A84C)", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Админ = системный агент, НЕ отдел. Ироничный перфекционист. Цвет: #1e40af", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Single-tenant. Multi-tenant через /factory", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Пост-процессор вместо обучения LLM форматированию", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},
    {"content": "Язык общения: русский", "type": "decision", "confidence": 1.0, "source": "owner"},
    {"content": "Цвета отделов только в отчётах, оболочка — чёрно-золотая", "type": "decision", "confidence": 1.0, "source": "owner_2026-06"},

    # ═══════════════════ ERRORS ═══════════════════
    {"content": "ДВЕ ВЕРСИИ (ROOT vs fosved-v2) — никогда больше. Одна версия, один Dockerfile", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "DeptColor через write_file = race condition. Использовать if-else или make_list", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "report_css.txt отсутствовал → BuildReport падал", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "__replace() → replace(). Underscore-версии deprecated", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "/cron/* без CRON_SECRET — любой мог триггерить", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "whisper_transcribe вызывался но builtin не существовал → crash", "type": "error", "confidence": 0.9, "source": "audit_23"},
    {"content": "file_cache_skills.mlog содержал stubs вместо реальных скиллов", "type": "error", "confidence": 0.8, "source": "stress_26"},
    {"content": "Агент удалил всё из репо — ВСЕГДА git status перед rm", "type": "error", "confidence": 0.8, "source": "narad_27"},
    {"content": "contains() == 1.0 — type mismatch. contains() возвращает Bool, не Float. Использовать просто contains(...)", "type": "error", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},
    {"content": "has_field() == 1.0 — type mismatch. has_field() возвращает Bool, не Float", "type": "error", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},
    {"content": ".dockerignore не был закоммичен в GitHub — Docker context 143MB, silent failure на Render", "type": "error", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},
    {"content": "memory { persist: './data/memory.db' } в app.mlog — несуществующий синтаксис, parse error mlog binary", "type": "error", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},
    {"content": "Explicit COPY Dockerfile вместо COPY . . — пропускает config/, skills_index/, report_css.txt", "type": "error", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},

    # ═══════════════════ LEARNINGS ═══════════════════
    {"content": "LLM игнорирует инструкции по форматированию → auto_enrich пост-процессор", "type": "learning", "confidence": 0.9, "source": "30_narads"},
    {"content": "Наряды >5 одновременно перегружают агента → 4 мега-наряда последовательно", "type": "learning", "confidence": 0.9, "source": "30_narads"},
    {"content": "Каждая сессия: MEGA_NARADS + 1-2 файла по теме. Не больше", "type": "learning", "confidence": 0.9, "source": "30_narads"},
    {"content": "Python proxy обязателен — Metalogos не справляется с LLM failover и HTML", "type": "learning", "confidence": 0.9, "source": "30_narads"},
    {"content": "context.mlog существовал но не импортировался = мёртвый код. Всегда проверять импорты", "type": "learning", "confidence": 0.8, "source": "audit_23"},
    {"content": "84/85 = архитектура рабочая. Проблемы были в реализации, не в дизайне", "type": "learning", "confidence": 0.8, "source": "stress_26"},
    {"content": "Render silent failure при большом Docker context — ВСЕГДА проверять размер через API", "type": "learning", "confidence": 0.9, "source": "deploy_fix_2026-06-27"},
    {"content": "Bool vs Float в mlog — contains/has_field возвращают Bool. Сравнение с числом = type mismatch", "type": "learning", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},

    # ═══════════════════ PREFERENCES ═══════════════════
    {"content": "Стиль Админа: ироничный перфекционист", "type": "preference", "confidence": 1.0, "source": "owner"},
    {"content": "Бейджи: иконка + текст вместе (✓ ФАКТ), не просто иконка", "type": "preference", "confidence": 0.9, "source": "owner"},
    {"content": "Dockerfile: ubuntu:24.04, не debian", "type": "preference", "confidence": 0.8, "source": "owner"},

    # ═══════════════════ CONTEXT ═══════════════════
    {"content": "OWNER_TELEGRAM_ID=2044005421, бот @fosved_office_v2_bot", "type": "context", "confidence": 1.0, "source": "config"},
    {"content": "GitHub: ShkodnikAI/FOSVED-office-v2, branch main", "type": "context", "confidence": 1.0, "source": "config"},
    {"content": "Render service ID: srv-d8gjquflk1mc73evf02g, auto-deploy", "type": "context", "confidence": 1.0, "source": "config"},

    # ═══════════════════ RELATIONSHIPS ═══════════════════
    {"content": "app.mlog импортирует dept/context.mlog", "type": "relationship", "confidence": 1.0, "source": "code"},
    {"content": "dept/miniapp.mlog — mini app экраны, guard для yana → SendTelegramReply", "type": "relationship", "confidence": 1.0, "source": "code"},
    {"content": "reverse_proxy.py → mlog serve (10001) → llm_proxy.py (4000)", "type": "relationship", "confidence": 1.0, "source": "architecture"},

    # ═══════════════════ PATTERNS ═══════════════════
    {"content": "При конвергенции ROOT+fosved-v2 — scheduler теряется. Всегда проверять /cron/*", "type": "pattern", "confidence": 0.9, "source": "30_narads"},
    {"content": "Render deploy fails silently при >100MB context. Проверять через API: GET /v1/services/{id}/deploys", "type": "pattern", "confidence": 0.9, "source": "deploy_fix_2026-06-27"},

    # ═══════════════════ OBSERVATIONS ═══════════════════
    {"content": "Стресс-тест 26: 84/85, единственный fail — 404 на несуществующий report", "type": "observation", "confidence": 0.8, "source": "stress_test_26"},
    {"content": "Сервер жив после deploy fix, /version возвращает version=e1c8b5a anti_format=0", "type": "observation", "confidence": 1.0, "source": "deploy_fix_2026-06-27"},

    # ═══════════════════ COMMITMENTS ═══════════════════
    {"content": "Наряд 28 (Админ) — передать агенту после стресс-теста", "type": "commitment", "confidence": 0.8, "source": "plan"},
    {"content": "Остальные 8 miniapp экранов по NARAD-29 после подтверждения Yana fix", "type": "commitment", "confidence": 0.8, "source": "plan"},

    # ═══════════════════ ARTIFACTS ═══════════════════
    {"content": "REBUILD_PLAN.md — полная карта проекта, 4 мега-наряда", "type": "artifact", "confidence": 0.9, "source": "code"},
    {"content": "SKILL_FOSVED_MEMORY_AGENT.md — спецификация Memanto-style памяти", "type": "artifact", "confidence": 1.0, "source": "skill"},

    # ═══════════════════ GOALS ═══════════════════
    {"content": "Цель: 80+/85 на стресс-тесте (достигнуто: 84/85)", "type": "goal", "confidence": 0.9, "source": "plan"},
    {"content": "Цель: 85/85 на следующем стресс-тесте (404 на несуществующий report)", "type": "goal", "confidence": 0.8, "source": "plan"},
]


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'data/memory.db'
    force = '--force' in sys.argv

    # Ensure data dir exists
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)

    # Check if already seeded
    if not force and os.path.exists(db_path):
        test_mem = FosvedMemory(db_path)
        existing = test_mem.stats()
        if existing['total_active'] > 0:
            print(f"DB already has {existing['total_active']} memories. Use --force to re-seed.")
            print(f"By type: {existing['by_type']}")
            return

    mem = FosvedMemory(db_path)
    inserted = mem.seed(INITIAL_MEMORIES)

    stats = mem.stats()
    print(f"Seeded {inserted}/{len(INITIAL_MEMORIES)} memories")
    print(f"Total active: {stats['total_active']}")
    print(f"By type:")
    for t, info in stats['by_type'].items():
        print(f"  {t}: {info['count']} (avg conf: {info['avg_confidence']})")

    # Verify recall works
    print(f"\n--- Recall test ---")
    results = mem.recall("architecture", type_filter="fact", limit=3)
    for r in results:
        print(f"  [{r['type']}] {r['content'][:80]}")

    mem.close()


if __name__ == '__main__':
    main()