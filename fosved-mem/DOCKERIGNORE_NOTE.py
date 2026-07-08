"""
═══════════════════════════════════════════════════════════════
ДОПОЛНЕНИЕ К .dockerignore
═══════════════════════════════════════════════════════════════

Проблема: текущий .dockerignore содержит строку "scripts/" —
seed_memory.py не попадёт в Docker context.

РЕШЕНИЕ: Убрать "scripts/" из .dockerignore.

Текущий .dockerignore содержит:

    .git
    skills/
    upload/
    __pycache__/
    отчёты/
    tool-results/
    scripts/          ← УДАЛИТЬ ЭТУ СТРОКУ
    *.pdf
    worklog.md
    PROJECT_CONTEXT.md
    README.md
    stress_test_detailed.json
    dept_dashboard.py
    auto_enricher.py
    requirements.txt

ВАЖНО: lib/ НЕ исключён — fosved_memory.py попадёт в контекст.

═══════════════════════════════════════════════════════════════
"""