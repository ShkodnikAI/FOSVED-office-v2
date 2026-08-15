#!/usr/bin/env python3
"""
credential_manager.py — FOSVED Office v2 Credential Manager

Система «Админ сам запрашивает ключи»:
- Скан .env на пустые ключи
- Генерация человекочитаемых запросов с ссылками
- Интеграция в утренний отчёт Яны
- Приём ключей от владельца через Telegram /admin/set-key

Автор: FOSVED Office v2
Версия: 1.0 (2026-08-14)
"""

import os
import re
import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger("fosved.credentials")


# ══════════════════════════════════════════════════════════════════════════
#  CREDENTIAL MANIFEST — единый источник правды о всех ключах
# ══════════════════════════════════════════════════════════════════════════

CREDENTIAL_MANIFEST = [
    # ── ОБЯЗАТЕЛЬНЫЕ ──────────────────────────────────────────────────────
    {
        "env_key": "TELEGRAM_BOT_TOKEN",
        "label": "Telegram Bot Token",
        "emoji": "🤖",
        "priority": "P0",
        "required": True,
        "category": "messaging",
        "why": "Яна отправляет отчёты, напоминания и отвечает через Telegram бота. Без токена — некому доставлять.",
        "how_steps": [
            "1. Откройте Telegram, найдите @BotFather",
            "2. Отправьте /newbot (или /mybots если бот уже создан)",
            "3. Задайте имя: Яна Фосвед, username: yana_fosved_bot",
            "4. BotFather вернёт токен вида 7123456789:AAH_abc...",
            "5. Скопируйте и отправьте сюда",
        ],
        "how_link": "https://t.me/BotFather",
        "how_link_text": "Открыть @BotFather",
        "example": "7123456789:AAH_abcDefGhiJklMnoPqrStUvWxYz",
        "sanctions_ok": True,
        "set_via": "/admin/set-key TELEGRAM_BOT_TOKEN <значение>",
    },
    {
        "env_key": "OWNER_TELEGRAM_ID",
        "label": "Ваш Telegram ID",
        "emoji": "👤",
        "priority": "P0",
        "required": True,
        "category": "messaging",
        "why": "Чтобы Яна знала кому отправлять отчёты. Это ваш числовой ID в Telegram.",
        "how_steps": [
            "1. Отправьте /start боту @userinfobot в Telegram",
            "2. Он вернёт ваш ID (число)",
            "3. Или: напишите вашему боту, затем откройте:",
            "   https://api.telegram.org/bot<ТОКЕН>/getUpdates",
            "4. Найдите chat.id в JSON",
        ],
        "how_link": "https://t.me/userinfobot",
        "how_link_text": "Узнать свой ID",
        "example": "2044005421",
        "sanctions_ok": True,
        "set_via": "/admin/set-key OWNER_TELEGRAM_ID <значение>",
    },
    {
        "env_key": "CRON_SECRET",
        "label": "Секрет для кронов",
        "emoji": "🔐",
        "priority": "P0",
        "required": True,
        "category": "security",
        "why": "Защищает эндпоинты сбора новостей и ЛЗ от вызова посторонними. Случайная строка.",
        "how_steps": [
            "1. Выполните в терминале:",
            "   python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"",
            "2. Скопируйте результат и отправьте сюда",
            "3. Или просто напишите любую случайную строку из 30+ символов",
        ],
        "how_link": None,
        "how_link_text": None,
        "example": "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
        "sanctions_ok": True,
        "auto_generate": True,
        "set_via": "/admin/set-key CRON_SECRET <значение>",
    },

    # ── LLM (минимум один) ───────────────────────────────────────────────
    {
        "env_key": "DEEPSEEK_API_KEY",
        "label": "DeepSeek API Key",
        "emoji": "🧠",
        "priority": "P1",
        "required": True,
        "required_group": "llm",
        "required_group_label": "LLM ключ (минимум один из группы)",
        "category": "llm",
        "why": "DeepSeek — LLM провайдер из Китая. Дешёвый (~$0.14/1M tokens), работает из-под санкций, хорошее качество на русском.",
        "how_steps": [
            "1. Откройте https://platform.deepseek.com",
            "2. Зарегистрируйтесь (email или GitHub login)",
            "3. Перейдите в API Keys → Create API Key",
            "4. Скопируйте ключ (вида sk-xxxxxxxxxxxxxxxx)",
            "5. Отправьте сюда",
        ],
        "how_link": "https://platform.deepseek.com/api_keys",
        "how_link_text": "DeepSeek API Keys",
        "example": "sk-1234567890abcdef",
        "sanctions_ok": True,
        "set_via": "/admin/set-key DEEPSEEK_API_KEY <значение>",
    },
    {
        "env_key": "GROQ_API_KEY",
        "label": "Groq API Key",
        "emoji": "⚡",
        "priority": "P1",
        "required": True,
        "required_group": "llm",
        "required_group_label": "LLM ключ (минимум один из группы)",
        "category": "llm",
        "why": "Groq — быстрый LLM inference. Бесплатный tier, работает из-под санкций. Быстрее DeepSeek, но меньше моделей.",
        "how_steps": [
            "1. Откройте https://console.groq.com",
            "2. Зарегистрируйтесь (GitHub login работает)",
            "3. Перейдите в API Keys → Create API Key",
            "4. Скопируйте ключ (вида gsk_xxxxxxxxxxxxxxxx)",
            "5. Отправьте сюда",
        ],
        "how_link": "https://console.groq.com/keys",
        "how_link_text": "Groq API Keys",
        "example": "gsk_1234567890abcdef",
        "sanctions_ok": True,
        "set_via": "/admin/set-key GROQ_API_KEY <значение>",
    },
    {
        "env_key": "ZAI_API_KEY",
        "label": "ZAI (z.ai) API Key",
        "emoji": "🔮",
        "priority": "P1",
        "required": True,
        "required_group": "llm",
        "required_group_label": "LLM ключ (минимум один из группы)",
        "category": "llm",
        "why": "Z.ai — китайский LLM провайдер. Дешёвый, работает из-под санкций.",
        "how_steps": [
            "1. Откройте https://bigmodel.cn",
            "2. Зарегистрируйтесь",
            "3. Dashboard → API Keys → Create Key",
            "4. Скопируйте и отправьте сюда",
        ],
        "how_link": "https://bigmodel.cn",
        "how_link_text": "Z.ai Dashboard",
        "example": "zai_1234567890abcdef",
        "sanctions_ok": True,
        "set_via": "/admin/set-key ZAI_API_KEY <значение>",
    },

    # ── ЖЕЛАТЕЛЬНЫЕ ──────────────────────────────────────────────────────
    {
        "env_key": "GITHUB_TOKEN_METALOGOS",
        "label": "GitHub Token (ЛЗ скан)",
        "emoji": "🐙",
        "priority": "P2",
        "required": False,
        "category": "devops",
        "why": "Увеличивает GitHub API лимит: 60 → 5000 запросов/час. Без токена ЛЗ работает, но с лимитом.",
        "how_steps": [
            "1. Откройте https://github.com/settings/tokens",
            "2. Нажмите Generate new token (classic)",
            "3. Note: fosved-lz-scan, Scope: public_repo",
            "4. Скопируйте токен (вида gph_xxx...)",
            "5. Отправьте сюда",
        ],
        "how_link": "https://github.com/settings/tokens",
        "how_link_text": "GitHub Settings → Tokens",
        "example": "ghp_1234567890abcdef",
        "sanctions_ok": True,
        "set_via": "/admin/set-key GITHUB_TOKEN_METALOGOS <значение>",
    },
    {
        "env_key": "WHISPER_API_KEY",
        "label": "Whisper API Key (голос)",
        "emoji": "🎙",
        "priority": "P3",
        "required": False,
        "category": "voice",
        "why": "Для транскрипции голосовых сообщений. Опционально — можно использовать Groq бесплатно.",
        "how_steps": [
            "1. Если используете Groq: ключ уже есть (GROQ_API_KEY)",
            "2. Если OpenAI: https://platform.openai.com/api-keys",
            "3. Укажите также WHISPER_PROVIDER=groq или openai",
        ],
        "how_link": None,
        "how_link_text": None,
        "example": "sk-... или gsk-...",
        "sanctions_ok": True,
        "set_via": "/admin/set-key WHISPER_API_KEY <значение>",
    },

    # ── ЗАБЛОКИРОВАННЫЕ САНКЦИЯМИ ────────────────────────────────────────
    {
        "env_key": "ANTHROPIC_API_KEY",
        "label": "Anthropic (Claude)",
        "emoji": "🚫",
        "priority": "PX",
        "required": False,
        "category": "llm",
        "why": "Заблокировано санкциями. Используйте DeepSeek или Groq.",
        "how_steps": [],
        "how_link": None,
        "how_link_text": None,
        "example": "",
        "sanctions_ok": False,
        "set_via": None,
    },
    {
        "env_key": "OPENAI_API_KEY",
        "label": "OpenAI (GPT)",
        "emoji": "🚫",
        "priority": "PX",
        "required": False,
        "category": "llm",
        "why": "Заблокировано санкциями. Используйте DeepSeek или Groq.",
        "how_steps": [],
        "how_link": None,
        "how_link_text": None,
        "example": "",
        "sanctions_ok": False,
        "set_via": None,
    },
    {
        "env_key": "SERPAPI_KEY",
        "label": "SerpAPI",
        "emoji": "🚫",
        "priority": "PX",
        "required": False,
        "category": "search",
        "why": "Заблокировано санкциями. НЕ НУЖЕН — RSS + GDELT полностью заменяют.",
        "how_steps": [],
        "how_link": None,
        "how_link_text": None,
        "example": "",
        "sanctions_ok": False,
        "set_via": None,
    },
]


# ══════════════════════════════════════════════════════════════════════════
#  SCANNER — обнаружение пустых ключей
# ══════════════════════════════════════════════════════════════════════════

def _is_key_set(env_key):
    """Check if an env key is actually set (non-empty, non-placeholder)."""
    val = os.environ.get(env_key, "")
    if not val:
        return False
    # Placeholder patterns: [...], <...>, xxx, TODO, your_key_here
    if val.startswith("[") and val.endswith("]"):
        return False
    if val.startswith("<") and val.endswith(">"):
        return False
    if val.lower() in ("xxx", "todo", "your_key_here", "placeholder", "changeme"):
        return False
    return True


def scan_missing_keys():
    """
    Scan environment for missing/empty credentials.
    Returns dict with: missing (list), groups (dict), summary (str).
    """
    missing = []
    set_keys = []
    blocked = []

    for cred in CREDENTIAL_MANIFEST:
        # Skip blocked-by-sanctions entirely
        if not cred.get("sanctions_ok", True):
            blocked.append(cred)
            continue

        if _is_key_set(cred["env_key"]):
            set_keys.append(cred)
        else:
            missing.append(cred)

    # Check required_group: if at least one LLM key is set, mark group as satisfied
    llm_group_keys = [c for c in missing if c.get("required_group") == "llm"]
    llm_group_set = [c for c in set_keys if c.get("required_group") == "llm"]
    llm_group_ok = len(llm_group_set) > 0

    # Categorize missing by priority
    by_priority = {"P0": [], "P1": [], "P2": [], "P3": []}
    for c in missing:
        p = c.get("priority", "P3")
        if p in by_priority:
            by_priority[p].append(c)

    return {
        "missing": missing,
        "set": set_keys,
        "blocked": blocked,
        "by_priority": by_priority,
        "llm_group_ok": llm_group_ok,
        "llm_group_missing": llm_group_keys if not llm_group_ok else [],
        "total_missing": len(missing),
        "total_set": len(set_keys),
        "total_blocked": len(blocked),
    }


def format_missing_for_telegram(scan_result):
    """
    Format missing credentials as a Telegram-friendly message.
    This is what Яна sends to the owner: «🔑 Нужны ключи».
    """
    if not scan_result["missing"]:
        return "✅ Все необходимые ключи настроены. Офис полностью боеготов."

    lines = []
    lines.append("🔑 *Необходимые ключи для работы офиса*")
    lines.append("")

    # P0 — обязательные
    p0 = scan_result["by_priority"].get("P0", [])
    if p0:
        lines.append("━━━ *ОБЯЗАТЕЛЬНЫЕ (без них не работает)* ━━━")
        for c in p0:
            lines.append(f"{c['emoji']} *{c['label']}*")
            lines.append(f"   Зачем: {c['why'][:100]}")
            if c.get("how_link"):
                lines.append(f"   👉 [{c['how_link_text']}]({c['how_link']})")
            if c.get("how_steps"):
                # Only show first 3 steps to keep message short
                for step in c["how_steps"][:3]:
                    lines.append(f"   {step}")
                if len(c["how_steps"]) > 3:
                    lines.append(f"   ...и ещё {len(c['how_steps'])-3} шагов")
            if c.get("set_via"):
                lines.append(f"   📤 {c['set_via']}")
            lines.append("")

    # P1 — LLM group
    llm_missing = scan_result.get("llm_group_missing", [])
    if llm_missing:
        lines.append("━━━ *LLM КЛЮЧ (хотя бы один)* ━━━")
        lines.append("Без LLM Яна не может анализировать, отвечать, учиться.")
        lines.append("")
        for c in llm_missing:
            lines.append(f"{c['emoji']} *{c['label']}* — {c['why'][:80]}")
            if c.get("how_link"):
                lines.append(f"   👉 [{c['how_link_text']}]({c['how_link']})")
            if c.get("set_via"):
                lines.append(f"   📤 {c['set_via']}")
            lines.append("")

    # P2 — желательные
    p2 = scan_result["by_priority"].get("P2", [])
    if p2:
        lines.append("━━━ *ЖЕЛАТЕЛЬНЫЕ (работает и без них)* ━━━")
        for c in p2:
            lines.append(f"{c['emoji']} {c['label']} — {c['why'][:80]}")
            if c.get("how_link"):
                lines.append(f"   👉 [{c['how_link_text']}]({c['how_link']})")
            lines.append("")

    # Already set
    if scan_result["total_set"] > 0:
        lines.append(f"✅ Уже настроено: {scan_result['total_set']} ключей")

    # Blocked
    if scan_result["total_blocked"] > 0:
        blocked_names = [f"{c['emoji']} {c['label']}" for c in scan_result["blocked"]]
        lines.append(f"🚫 Заблокировано санкциями: {', '.join(blocked_names)}")

    return "\n".join(lines)


def format_missing_for_morning_brief(scan_result):
    """
    Compact format for embedding in morning brief prompt.
    Returns a short text block for the LLM prompt.
    """
    if not scan_result["missing"]:
        return "Все ключи настроены ✅"

    parts = []
    p0 = scan_result["by_priority"].get("P0", [])
    llm_missing = scan_result.get("llm_group_missing", [])
    p2 = scan_result["by_priority"].get("P2", [])

    if p0:
        parts.append("Обязательные (P0): " + ", ".join(f"{c['emoji']}{c['env_key']}" for c in p0))
    if llm_missing:
        parts.append("LLM (нужен хотя бы один): " + ", ".join(f"{c['emoji']}{c['env_key']}" for c in llm_missing))
    if p2:
        parts.append("Желательные: " + ", ".join(f"{c['emoji']}{c['env_key']}" for c in p2))

    return "⚠️ НЕ ХВАТАЕТ КЛЮЧЕЙ: " + "; ".join(parts)


def format_missing_for_json(scan_result):
    """
    Full JSON format for API response.
    """
    result = {
        "status": "ok",
        "total_missing": scan_result["total_missing"],
        "total_set": scan_result["total_set"],
        "total_blocked": scan_result["total_blocked"],
        "llm_group_ok": scan_result["llm_group_ok"],
        "missing": [],
        "set": [{"env_key": c["env_key"], "label": c["label"]} for c in scan_result["set"]],
        "blocked": [{"env_key": c["env_key"], "label": c["label"], "reason": c["why"]} for c in scan_result["blocked"]],
    }

    for c in scan_result["missing"]:
        entry = {
            "env_key": c["env_key"],
            "label": c["label"],
            "emoji": c["emoji"],
            "priority": c["priority"],
            "required": c["required"],
            "category": c["category"],
            "why": c["why"],
            "how_steps": c.get("how_steps", []),
            "how_link": c.get("how_link"),
            "how_link_text": c.get("how_link_text"),
            "set_via": c.get("set_via"),
        }
        if c.get("required_group"):
            entry["required_group"] = c["required_group"]
            entry["required_group_label"] = c["required_group_label"]
        if c.get("auto_generate"):
            entry["auto_generate"] = True
        result["missing"].append(entry)

    return result


# ══════════════════════════════════════════════════════════════════════════
#  KEY SETTER — сохранение ключа в .env
# ══════════════════════════════════════════════════════════════════════════

def set_key_in_env(env_key, value, env_file_path=None):
    """
    Set a key in .env file and in current process environment.
    Returns (success: bool, message: str).
    """
    # Validate key name
    valid_keys = {c["env_key"] for c in CREDENTIAL_MANIFEST}
    if env_key not in valid_keys:
        return False, f"Unknown key: {env_key}. Valid keys: {', '.join(sorted(valid_keys))}"

    # Check sanctions
    cred = next(c for c in CREDENTIAL_MANIFEST if c["env_key"] == env_key)
    if not cred.get("sanctions_ok", True):
        return False, f"Ключ {env_key} заблокирован санкциями. Используйте DeepSeek или Groq."

    # Validate value
    if not value or len(value) < 5:
        return False, f"Значение слишком короткое ({len(value)} символов). Минимум 5."

    # Set in current process
    os.environ[env_key] = value

    # Set in .env file
    if env_file_path is None:
        env_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

    try:
        # Read existing .env
        lines = []
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        # Find and update the key
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{env_key}=") or stripped.startswith(f"{env_key} ="):
                # Preserve any inline comment
                parts = line.split('#', 1)
                lines[i] = f"{env_key}={value}"
                if len(parts) > 1:
                    lines[i] += f"  # {parts[1]}"
                lines[i] += "\n"
                found = True
                break

        if not found:
            # Append at end
            lines.append(f"{env_key}={value}\n")

        with open(env_file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        log.info(f"Key {env_key} set successfully (len={len(value)})")
        return True, f"✅ {env_key} сохранён в .env ({len(value)} символов). Перезапустите сервер для применения."

    except Exception as e:
        log.error(f"Failed to write {env_key} to .env: {e}")
        return False, f"Ошибка записи в .env: {e}"


def auto_generate_key(env_key):
    """Auto-generate a key value (for CRON_SECRET etc.)."""
    import secrets as _secrets
    cred = next((c for c in CREDENTIAL_MANIFEST if c["env_key"] == env_key), None)
    if not cred or not cred.get("auto_generate"):
        return False, f"Key {env_key} cannot be auto-generated."

    value = _secrets.token_urlsafe(32)
    return set_key_in_env(env_key, value)


# ══════════════════════════════════════════════════════════════════════════
#  PROVIDER REGISTRY — метаданные провайдеров для отчёта
# ══════════════════════════════════════════════════════════════════════════

PROVIDER_REGISTRY = {
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "name": "DeepSeek",
        "emoji": "🧠",
        "model": "deepseek-chat",
        "pricing": "~$0.14/1M input, $0.28/1M output",
        "balance_url": "https://api.deepseek.com/user/balance",
        "balance_format": "deepseek",
    },
    "groq": {
        "env_key": "GROQ_API_KEY",
        "name": "Groq",
        "emoji": "⚡",
        "model": "llama-3.3-70b-versatile",
        "pricing": "Бесплатный tier (rate-limited)",
        "balance_url": None,
        "balance_format": None,
    },
    "zai": {
        "env_key": "ZAI_API_KEY",
        "name": "Z.ai (GLM)",
        "emoji": "🔮",
        "model": "glm-4",
        "pricing": "~$0.10/1M tokens",
        "balance_url": None,
        "balance_format": None,
    },
    "grok": {
        "env_key": "GROK_API_KEY",
        "name": "Grok (xAI)",
        "emoji": "🌀",
        "model": "grok-2",
        "pricing": "$5/1M input",
        "balance_url": None,
        "balance_format": None,
    },
    "anthropic": {
        "env_key": "ANTHROPIC_API_KEY",
        "name": "Anthropic (Claude)",
        "emoji": "🚫",
        "model": "claude-sonnet-4-20250514",
        "pricing": "$3/1M input (заблокирован санкциями)",
        "balance_url": None,
        "balance_format": None,
        "sanctions_blocked": True,
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "name": "OpenAI (GPT)",
        "emoji": "🚫",
        "model": "gpt-4o",
        "pricing": "$5/1M input (заблокирован санкциями)",
        "balance_url": None,
        "balance_format": None,
        "sanctions_blocked": True,
    },
    "apodex": {
        "env_key": "APODEX_API_KEY",
        "name": "Apodex",
        "emoji": "🔹",
        "model": "—",
        "pricing": "—",
        "balance_url": None,
        "balance_format": None,
    },
}


# ══════════════════════════════════════════════════════════════════════════
#  BALANCE CHECKER — проверка балансов и rate limits
# ══════════════════════════════════════════════════════════════════════════

def _http_get_json(url, headers=None, timeout=10):
    """Simple HTTP GET returning JSON, or None on error."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def check_deepseek_balance(api_key):
    """Check DeepSeek balance. Returns dict with balance info."""
    data = _http_get_json(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if not data:
        return {"status": "error", "message": "API unavailable or invalid key"}
    # DeepSeek returns: {"balance_infos": [{"currency": "USD", "total_balance": "1.23", ...}]}
    infos = data.get("balance_infos", [])
    if infos:
        result = {"status": "ok", "balances": []}
        for info in infos:
            result["balances"].append({
                "currency": info.get("currency", "?"),
                "total": info.get("total_balance", "?"),
                "granted": info.get("granted_balance", "?"),
                "topped_up": info.get("topped_up_balance", "?"),
            })
        return result
    return {"status": "ok", "balances": [], "raw": data}


def check_github_rate_limit(token=None):
    """Check GitHub API rate limit. Returns remaining/limit."""
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "fosved-credential-checker"}
    if token:
        headers["Authorization"] = f"token {token}"
    data = _http_get_json("https://api.github.com/rate_limit", headers=headers)
    if not data:
        return {"status": "error", "message": "GitHub API unavailable"}
    resources = data.get("resources", {})
    return {
        "status": "ok",
        "core": {
            "remaining": resources.get("core", {}).get("remaining", "?"),
            "limit": resources.get("core", {}).get("limit", "?"),
        },
        "search": {
            "remaining": resources.get("search", {}).get("remaining", "?"),
            "limit": resources.get("search", {}).get("limit", "?"),
        },
    }


def check_all_balances():
    """
    Check balances/rate-limits for all configured providers.
    Returns dict keyed by provider name.
    """
    results = {}

    # DeepSeek
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if ds_key and not ds_key.startswith("["):
        results["deepseek"] = check_deepseek_balance(ds_key)

    # GitHub rate limit
    gh_key = os.environ.get("GITHUB_TOKEN_METALOGOS", os.environ.get("GITHUB_TOKEN", ""))
    results["github"] = check_github_rate_limit(gh_key if gh_key and not gh_key.startswith("[") else None)

    # Groq — no public balance API, but we can check if key is valid
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key and not groq_key.startswith("["):
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {groq_key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                models = json.loads(resp.read())
                model_count = len(models.get("data", []))
                results["groq"] = {"status": "ok", "models_available": model_count, "note": "Free tier (rate-limited)"}
        except urllib.error.HTTPError as e:
            results["groq"] = {"status": "error", "message": f"HTTP {e.code}"}
        except Exception as e:
            results["groq"] = {"status": "error", "message": str(e)[:100]}

    # ZAI — check models endpoint
    zai_key = os.environ.get("ZAI_API_KEY", "")
    if zai_key and not zai_key.startswith("["):
        results["zai"] = {"status": "ok", "note": "Key set (balance API not available)"}

    # Grok
    grok_key = os.environ.get("GROK_API_KEY", "")
    if grok_key and not grok_key.startswith("["):
        results["grok"] = {"status": "ok", "note": "Key set (balance API not available)"}

    return results


def format_provider_status(balances=None, scan_result=None):
    """
    Format active providers with balances for Telegram message.
    This is what goes into the morning report.
    """
    if balances is None:
        balances = check_all_balances()
    if scan_result is None:
        scan_result = scan_missing_keys()

    lines = []

    # ── Active LLM providers ──
    active_providers = []
    for pid, pinfo in PROVIDER_REGISTRY.items():
        if pinfo.get("sanctions_blocked"):
            continue
        key = os.environ.get(pinfo["env_key"], "")
        if key and not key.startswith("[") and key.lower() not in ("xxx", "todo"):
            active_providers.append((pid, pinfo))

    if active_providers:
        lines.append("📊 *Активные провайдеры:*")
        for pid, pinfo in active_providers:
            bal = balances.get(pid, {})
            if bal.get("status") == "ok":
                # DeepSeek — show balance
                if pid == "deepseek" and bal.get("balances"):
                    for b in bal["balances"]:
                        lines.append(f"  {pinfo['emoji']} *{pinfo['name']}* — {b['total']} {b['currency']} ({pinfo['pricing']})")
                # Groq — show models
                elif pid == "groq" and bal.get("models_available"):
                    lines.append(f"  {pinfo['emoji']} *{pinfo['name']}* — {bal['models_available']} моделей, {bal.get('note', pinfo['pricing'])}")
                else:
                    note = bal.get("note", pinfo["pricing"])
                    lines.append(f"  {pinfo['emoji']} *{pinfo['name']}* — {note}")
            else:
                lines.append(f"  {pinfo['emoji']} *{pinfo['name']}* — ⚠️ {bal.get('message', 'не удалось проверить')}")
    else:
        lines.append("📊 LLM провайдеры: ❌ ни один не настроен")

    # ── GitHub ──
    gh = balances.get("github", {})
    if gh.get("status") == "ok":
        core = gh.get("core", {})
        search = gh.get("search", {})
        gh_key = os.environ.get("GITHUB_TOKEN_METALOGOS", os.environ.get("GITHUB_TOKEN", ""))
        has_token = bool(gh_key and not gh_key.startswith("["))
        token_label = "с токеном" if has_token else "без токена (60/час)"
        lines.append(f"  🐙 *GitHub* — {core.get('remaining', '?')}/{core.get('limit', '?')} core, {search.get('remaining', '?')}/{search.get('limit', '?')} search ({token_label})")

    # ── Blocked by sanctions ──
    blocked = [p for p in PROVIDER_REGISTRY.values() if p.get("sanctions_blocked")]
    if blocked:
        blocked_str = ", ".join(p["emoji"] + p["name"] for p in blocked)
        lines.append(f"  🚫 Заблокировано: {blocked_str}")

    # ── Missing keys (compact) ──
    missing = scan_result.get("missing", [])
    if missing:
        lines.append("")
        lines.append("🔑 *Не хватает:* " + ", ".join(f"{c['emoji']}{c['label']}" for c in missing))

    return "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 60)
    print("  FOSVED CREDENTIAL MANAGER — Diagnostic")
    print("=" * 60)

    result = scan_missing_keys()

    print(f"\n  Set:     {result['total_set']} keys")
    print(f"  Missing: {result['total_missing']} keys")
    print(f"  Blocked: {result['total_blocked']} keys (sanctions)")
    print(f"  LLM OK:  {'✅' if result['llm_group_ok'] else '❌'}")

    if result['total_missing'] > 0:
        print("\n" + format_missing_for_telegram(result))

    print("\n" + "=" * 60)
    print("  PROVIDER STATUS + BALANCES")
    print("=" * 60)
    print(format_provider_status(scan_result=result))
