#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mlog_check_root_env.py — санкционированный запуск `mlog check --root` (наряд #717 SEC-1, п.2).

Факт наряда: на Metalogos <= 0.39.0 `check --root` ИСПОЛНяет проверяемый файл
(№953). Безвредно это только в изолированном окружении. До релиза с №953 каждый
запуск `check --root` в офисе обязан идти через эту обёртку:

  1. DATABASE_URL форсируется в sqlite::memory: (никаких боевых БД);
  2. окружение строится с нуля по НЕЙТРАЛЬНОМУ белому списку (deny-by-default):
     боевые переменные (токены, ключи, секреты, прод-конфиг) в дочерний процесс
     не попадают, даже если заданы в родительском;
  3. единственная осознанная проброска — MLOG_BIN (путь к кандидату Metalogos
     для воскресного стенда #655, rc_stand_check.sh).

Использование:
  python3 scripts/mlog_check_root_env.py app.mlog [dogfood_staging.mlog ...]
      — запускает `mlog check <entry> --root <entry>` для каждого входа в
        санитайзенном окружении; вывод транслируется, rc — от ребёнка (первый
        ненулевой побеждает, но все входы прогоняются).
  python3 scripts/mlog_check_root_env.py --print-env
      — самопроверка: печатает JSON окружения, с которым будет запущен ребёнок
        (тест tests/test_n717_sec1.py гоняет это под загрязнённым родителем).

Гварды: tests/test_n717_sec1.py (A: окружение; B: CI-гигиена; C: инвентарь п.1).
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Нейтральные переменные ОС, без которых бинарь/раннер не живут. НЕ расширять
# служебными или прод-переменными офиса: любое расширение — через наряд.
NEUTRAL_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TMPDIR", "TMP", "USER", "LOGNAME", "SHELL", "TERM", "HOSTNAME",
    "PWD", "OLDPWD", "SHLVL", "_",
)

# Осознанные проброски (не нейтральные, но нужны инфраструктуре проверки):
#   MLOG_BIN — кандидат Metalogos стенда #655 (пусто -> боевой bin/mlog).
PASSTHROUGH = ("MLOG_BIN",)

# Справочник боевых имён (НЕ используется фильтром — фильтр deny-by-default
# и режет всё, чего нет в списках выше). Список нужен тесту A.2 и людям:
# это контракт офиса из METALOGOS_ENV_ALLOWLIST_CENSUS (entrypoint.sh) +
# INTEGRATIONS_REGISTRY (proxy/core.py) + Python-слой.
PROD_ENV_VARS = (
    # секреты-учётные данные
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "TELEGRAM_ARCHIVE_CHANNEL_ID",
    "CRON_SECRET", "INTERNAL_API_TOKEN", "API_SECRET", "WEBHOOK_SECRET",
    "LOCKDOWN_PASSWORD", "TAVILY_API_KEY", "ALPHAVANTAGE_API_KEY",
    "GITHUB_TOKEN_METALOGOS", "WHISPER_API_KEY",
    # ключи провайдеров LLM
    "ZAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY", "CEREBRAS_API_KEY", "SAKANA_API_KEY", "KIMI_API_KEY",
    "QWEN_API_KEY",
    # чувствительный конфиг и прод-конфиг
    "OWNER_TELEGRAM_ID", "RENDER_URL", "RENDER_GIT_COMMIT", "SHOP_ENABLED",
    "DATABASE_PATH", "OSP_TAVILY_DAILY_BUDGET", "OSP_TAVILY_CACHE_MIN",
    "METALOGOS_LLM_MODEL", "METALOGOS_LLM_PROVIDER",
    "FORGE_GITHUB_OWNER", "FORGE_REPOS_DIR", "FORGE_RUN_ENABLED",
    "FORGE_RUN_VLIMIT_KB", "FNP_CUSTOMER", "FNP_GOAL", "FNP_NAME",
    "FNP_SLUG", "FNP_TYPE", "TEAM_MAX_CONSULTS", "TEAM_MAX_LLM_CALLS",
)


def sanitize_env(parent=None):
    """Окружение для check --root: нейтральный базис + sqlite::memory: + MLOG_BIN.

    Deny-by-default: из родителя берутся ТОЛЬКО имена из NEUTRAL_ALLOWLIST и
    PASSTHROUGH; DATABASE_URL перезаписывается принудительно.
    """
    parent = os.environ if parent is None else parent
    env = {}
    for name in NEUTRAL_ALLOWLIST:
        if name in parent:
            env[name] = parent[name]
    for name in PASSTHROUGH:
        if name in parent and parent[name]:
            env[name] = parent[name]
    # п.2 наряда: только sqlite::memory:, даже если родитель пытался навязать своё
    env["DATABASE_URL"] = "sqlite::memory:"
    return env


def mlog_bin():
    return os.environ.get("MLOG_BIN") or os.path.join(REPO, "bin", "mlog")


def run_check(entry):
    """`mlog check <entry> --root <entry>` в санитайзенном окружении; возвращает rc."""
    env = sanitize_env()
    proc = subprocess.run(
        [mlog_bin(), "check", entry, "--root", entry],
        cwd=REPO, env=env,
    )
    return proc.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entries", nargs="*", help="точки входа .mlog (например app.mlog)")
    ap.add_argument("--print-env", action="store_true",
                    help="напечатать JSON окружения ребёнка и выйти (самопроверка)")
    args = ap.parse_args()

    if args.print_env:
        print(json.dumps(sanitize_env(), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    if not args.entries:
        ap.error("укажите хотя бы один вход .mlog (или --print-env)")

    rc = 0
    for entry in args.entries:
        print(f"== n717 sanitized check --root: {entry} "
              f"(DATABASE_URL=sqlite::memory:, боевые переменные удалены) ==")
        child_rc = run_check(entry)
        print(f"== {entry}: rc={child_rc} ==")
        if child_rc != 0 and rc == 0:
            rc = child_rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
