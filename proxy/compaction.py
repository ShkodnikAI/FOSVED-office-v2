"""FO-016: компакция контекста департаментов — budget + prune + summarize + offload.

Наряд #82 (пакет G, волна G1). Эталон: sst/opencode — packages/opencode/src/
session/compaction.ts + overflow.ts + ToolOutputStore. Ключевые решения:

- usable() = лимит модели − резерв ответа (opencode overflow.usable());
  бюджет = минимум по провайдерам combo-цепи департамента — гарантия, что
  запрос влезет у любого провайдера, до которого дойдёт race/фолбэк.
- prune — обратный проход по истории с защитой последних N токенов
  (opencode preserve_recent_tokens); старые крупные реплики заменяются
  плейсхолдером «[очищено: …]», оригинал остаётся в dialog_history (БД mlog).
- summarize — при переполнении после prune хвост до последнего user-хода
  суммаризируется дешёвой моделью, последний user-ход переигрывается
  дословно (opencode replay).
- offload — tool-вывод > 2000 строк / 50 КБ уезжает в файл data/tool_output/
  (retention 7 дней), в контекст возвращаются путь + первые строки
  (паттерн opencode ToolOutputStore); оригинал цитируем restore_tool_output().

Метрики пишутся в трейсы FO-004 (event=compaction) и в dialog_history как
запись-заготовка Part-типа #83 ({"part_type":"compaction", ...}).

Отказоустойчивость: отказ диска/LLM-суммаризатора не роняет диалог —
компакция деградирует до отсечения середины с плейсхолдером.

Env-ручки (все опциональны):
  FOSVED_CTX_MAX_TOKENS            — жёсткий бюджет поверх расчётного
  FOSVED_PRUNE_PROTECT_TOKENS      — защита хвоста (по умолчанию 40960,
                                     адаптивно урезается до budget//2)
  FOSVED_OFFLOAD_LINES             — порог строк для offload (2000)
  FOSVED_OFFLOAD_BYTES             — порог байт для offload (51200)
  FOSVED_TOOL_OUTPUT_RETENTION_DAYS — ретеншн offload-файлов (7)

Модуль зависит только от proxy.core (никак не от proxy.providers —
providers импортирует compaction, обратный импорт запрещён: цикл).
"""
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

from proxy.core import log, _query, _write_llm_trace

# ────────────────────────── лимиты контекста ──────────────────────────
# Консервативные окна контекста по провайдерам (токены). Значение — не
# рекламный максимум, а минимальное окно среди моделей провайдера, реально
# используемых в COMBO_CHAINS (kimi-k3, deepseek-chat, glm-4.6/glm-4-plus,
# gpt-oss-20b/120b, claude-sonnet-4, nemotron). Провайдер вне таблицы
# считается окном _UNKNOWN_PROVIDER_LIMIT (безопасно мало).
PROVIDER_CONTEXT_LIMITS = {
    "anthropic": 200000,   # claude-sonnet-4 — 200k
    "kimi": 262144,        # kimi-k3 — 256k
    "openai": 128000,
    "zai": 131072,         # glm-4-plus 128k (glm-4.6 шире — берём минимум)
    "groq": 131072,        # gpt-oss-20b — 131k
    "cerebras": 131072,    # gpt-oss-120b — 131k
    "nvidia": 131072,      # nemotron-super-49b — 128k+
    "grok": 131072,
    "deepseek": 65536,     # deepseek-chat — консервативно 64k
    "apodex": 65536,       # окно не документировано — консервативно
}
_UNKNOWN_PROVIDER_LIMIT = 32768

# Резерв ответа — зеркалит max_tok из call_llm (providers.py).
_OUTPUT_RESERVE_BIG = 16384
_OUTPUT_RESERVE_STD = 8192
_BIG_DEPTS = {"yana", "admin", "osp", "lz", "expert", "engineering"}

# ────────────────────────── offload-хранилище ──────────────────────────
TOOL_OUTPUT_DIR = os.path.join(os.environ.get("DATABASE_PATH", "./data"), "tool_output")
TOOL_OUTPUT_HEAD_LINES = 30      # сколько первых строк возвращаем в контекст
_OFFLOAD_HEAD_BYTES = 2000       # и не более стольких байт головы
_OFFLOAD_MIN_KEEP_CHARS = 400    # короче — offload не оправдан
_offload_lock = threading.Lock()
_last_cleanup_day = {"day": ""}

# Порог prune-кандидата: реплики дешевле этого числа токенов не трогаем —
# metadata-шум от их плейсхолдеров дороже экономии.
_PRUNE_MSG_MIN_TOKENS = 256


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        log.warning(f"compaction: bad env {name}, using default {default}")
        return default


def estimate_text(text):
    """Грубая оценка токенов текста: ~2 символа на токен (рус/англ микс).
    Канонический оценщик FO-016; providers.py ре-экспортирует как
    _estimate_tokens для совместимости (сообщения-list)."""
    return len(text or "") // 2


def estimate_tokens(messages):
    """Оценка токенов списка сообщений OpenAI-формата (совместимость
    с прежней providers._estimate_tokens)."""
    total = 0
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            total += len(c) // 2
        elif c is not None:
            total += len(str(c)) // 2
    return total


def resolve_output_reserve(dept):
    """Резерв на ответ — зеркально max_tok в call_llm."""
    return _OUTPUT_RESERVE_BIG if dept in _BIG_DEPTS else _OUTPUT_RESERVE_STD


def get_context_budget(dept, chain=None, provider=None):
    """usable(): бюджет входных токенов = min(окно провайдера) − резерв ответа.

    chain — combo-цепь департамента [(provider, [models]), ...] (может быть
    None); provider — известный провайдер при model_override. Флор по цепи
    гарантирует влезание у любого провайдера race/фолбэка.
    Env FOSVED_CTX_MAX_TOKENS жёстко перекрывает расчёт.
    """
    limits = []
    if provider:
        limits.append(PROVIDER_CONTEXT_LIMITS.get(provider, _UNKNOWN_PROVIDER_LIMIT))
    if chain:
        for prov_name, _models in chain:
            limits.append(PROVIDER_CONTEXT_LIMITS.get(prov_name, _UNKNOWN_PROVIDER_LIMIT))
    if not limits:
        # Цепь неизвестна — флор по всем известным провайдерам (консервативно)
        limits = list(PROVIDER_CONTEXT_LIMITS.values()) or [_UNKNOWN_PROVIDER_LIMIT]
    budget = max(min(limits) - resolve_output_reserve(dept), 2048)
    override = _env_int("FOSVED_CTX_MAX_TOKENS", 0)
    if override > 0:
        # Явный override оператора чтится дословно (осознанный выбор,
        # в том числе для тестов) — флор защищает только расчётный бюджет.
        budget = min(budget, override)
    return budget


def _msg_hash(content):
    return hashlib.sha1((content or "").encode("utf-8", "replace")).hexdigest()[:8]


# ────────────────────────── offload (ToolOutputStore) ──────────────────────────

def _tool_output_dir():
    return TOOL_OUTPUT_DIR


def _write_offload_file(content, dept):
    """Пишет оригинал tool-вывода в файл. Возвращает относительный путь."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    name = f"{dept}_{stamp}_{_msg_hash(content)}.txt"
    rel = os.path.join(day, name)
    abs_dir = os.path.join(_tool_output_dir(), day)
    os.makedirs(abs_dir, exist_ok=True)
    with open(os.path.join(_tool_output_dir(), rel), "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def _offload_placeholder(content, rel):
    """Плейсхолдер в контексте: путь + первые строки (цитируемо)."""
    lines = content.splitlines()
    head_lines = lines[:TOOL_OUTPUT_HEAD_LINES]
    head = "\n".join(head_lines)
    if len(head) > _OFFLOAD_HEAD_BYTES:
        head = head[:_OFFLOAD_HEAD_BYTES]
    total_lines = len(lines)
    meta = (f"[tool_output: offloaded id={_msg_hash(content)} path={rel} "
            f"lines={total_lines} chars={len(content)}]")
    return meta + "\n" + head + ("\n[…]" if total_lines > TOOL_OUTPUT_HEAD_LINES else "")


def restore_tool_output(ref):
    """Цитируемость: вернуть оригинал по path/id из плейсхолдера offload."""
    ref = (ref or "").strip()
    if not ref:
        return ""
    root = _tool_output_dir()
    cand = ref if os.path.isabs(ref) else os.path.join(root, ref)
    if os.path.isfile(cand):
        with open(cand, "r", encoding="utf-8") as f:
            return f.read()
    # поиск по id-хешу в пределах хранилища
    target = ref.replace("id=", "").strip()
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if target and target in fn:
                with open(os.path.join(dirpath, fn), "r", encoding="utf-8") as f:
                    return f.read()
    return ""


def cleanup_tool_output_files(retention_days=None, force=False):
    """Удаление offload-файлов старше retention_days (по mtime).
    Вызывается cron-эндпоинтом и лениво (раз в сутки) при первом offload."""
    if retention_days is None:
        retention_days = _env_int("FOSVED_TOOL_OUTPUT_RETENTION_DAYS", 7)
    removed = 0
    try:
        root = _tool_output_dir()
        if not os.path.isdir(root):
            return 0
        cutoff = time.time() - retention_days * 86400
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        removed += 1
                except OSError as e:
                    log.warning(f"compaction: cleanup skip {fn}: {e}")
        with _offload_lock:
            _last_cleanup_day["day"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except Exception as e:
        log.warning(f"compaction: cleanup failed (non-fatal): {e}")
    return removed


def _maybe_lazy_cleanup():
    """Ленивая чистка — не чаще раза в сутки, чтобы ретеншн работал даже
    без крона (крон /cron/cleanup-tool-output остаётся основной точкой)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _offload_lock:
        if _last_cleanup_day["day"] == today:
            return
        _last_cleanup_day["day"] = today
    threading.Thread(target=cleanup_tool_output_files, daemon=True).start()


def offload_giant_outputs(messages, dept):
    """Pass 1 — offload гигантских tool-выводов (opencode ToolOutputStore).
    Роли tool/function > порогов (строки/байты) → файл + плейсхолдер с путём.
    Отказ диска: сообщение остаётся как есть (диалог не роняем).
    Возвращает (messages, {"offloaded": n})."""
    lines_max = _env_int("FOSVED_OFFLOAD_LINES", 2000)
    bytes_max = _env_int("FOSVED_OFFLOAD_BYTES", 51200)
    offloaded = 0
    out = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        ok_role = role in ("tool", "function")
        if (ok_role and isinstance(content, str)
                and len(content) > _OFFLOAD_MIN_KEEP_CHARS
                and (content.count("\n") + 1 > lines_max or len(content.encode("utf-8", "replace")) > bytes_max)):
            try:
                rel = _write_offload_file(content, dept)
                out.append({**m, "content": _offload_placeholder(content, rel)})
                offloaded += 1
                continue
            except OSError as e:
                # Диск недоступен — не роняем диалог, едем с полным выводом
                log.warning(f"compaction: offload write failed (keep original): {e}")
        out.append(m)
    if offloaded:
        _maybe_lazy_cleanup()
    return out, {"offloaded": offloaded}


# ────────────────────────── prune ──────────────────────────

def prune_history(messages, budget, dept=None):
    """Pass 2 — prune: обратный проход с защитой последних N токенов хвоста
    (opencode preserve_recent_tokens). Старые крупные реплики → плейсхолдер
    «[очищено: …]»; оригинал остаётся в dialog_history (БД) — цитируемо.
    System-сообщения не трогаются. Возвращает (messages, stats)."""
    tokens_before = estimate_tokens(messages)
    protect = _env_int("FOSVED_PRUNE_PROTECT_TOKENS", 40960)
    protect = min(protect, max(budget // 2, 1024))
    convo_idx = [i for i, m in enumerate(messages) if m.get("role") != "system"]
    if not convo_idx:
        return messages, {"pruned": 0, "tokens_before": tokens_before, "tokens_after": tokens_before}

    # Хвост, который не трогаем: идём с конца, пока не наберём protect
    protected = set()
    acc = 0
    for i in reversed(convo_idx):
        if acc >= protect:
            break
        acc += estimate_tokens([messages[i]])
        protected.add(i)

    pruned = 0
    out = list(messages)
    for i in convo_idx:
        if i in protected:
            continue
        m = messages[i]
        content = m.get("content")
        if not isinstance(content, str) or len(content) // 2 < _PRUNE_MSG_MIN_TOKENS:
            continue
        out[i] = {**m, "content": (
            f"[очищено: {m.get('role', '?')} id={_msg_hash(content)} "
            f"chars={len(content)} — оригинал в dialog_history]"
        )}
        pruned += 1
    tokens_after = estimate_tokens(out)
    return out, {"pruned": pruned, "tokens_before": tokens_before, "tokens_after": tokens_after}


# ────────────────────────── summarize ──────────────────────────

_SUMMARY_SYSTEM = ("Summarize the following conversation history into a concise "
                   "context paragraph (max 300 words). Preserve key facts, decisions, "
                   "names, numbers. Output ONLY the summary, nothing else.")
_SUMMARY_INPUT_MAX_MSGS = 80
_SUMMARY_INPUT_MSG_CAP = 1500  # символов на реплику в суммаризируемом блоке


def _serialize_block(block):
    parts = []
    for m in block[-_SUMMARY_INPUT_MAX_MSGS:]:
        role = "User" if m.get("role") == "user" else "Assistant"
        c = m.get("content", "")
        if not isinstance(c, str):
            c = str(c)
        if len(c) > _SUMMARY_INPUT_MSG_CAP:
            c = c[:_SUMMARY_INPUT_MSG_CAP] + "…"
        parts.append(f"{role}: {c}")
    return "\n".join(parts)


def summarize_overflow(messages, dept, summarize_fn):
    """Pass 3 — summarize-компакция при переполнении (opencode compaction.ts):
    блок до последнего user-хода суммаризируется дешёвой моделью,
    последний user-ход (+ всё после него) переигрывается дословно.
    summarize_fn([{...}]) -> {"reply": str} | None — передаётся из providers
    (разрыв цикла импортов). Отказ суммаризатора → детерминированная деградация:
    середина отсекается с плейсхолдером, диалог не роняется.
    Возвращает (messages, stats)."""
    tokens_before = estimate_tokens(messages)
    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]
    if len(convo) <= 4:
        return messages, {"summarized": 0, "tokens_before": tokens_before,
                          "tokens_after": tokens_before, "replayed": False}

    # Хвост: последний user-ход и всё после него — дословно (replay)
    last_user_pos = None
    for i, m in enumerate(convo):
        if m.get("role") == "user":
            last_user_pos = i
    if last_user_pos is None or last_user_pos < 1:
        return messages, {"summarized": 0, "tokens_before": tokens_before,
                          "tokens_after": tokens_before, "replayed": False}

    head = convo[:last_user_pos]
    tail = convo[last_user_pos:]
    summary_msg = None
    summarized = 0

    try:
        block = _serialize_block(head)
        res = summarize_fn([
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": block},
        ])
        reply = (res or {}).get("reply", "")
        if reply and reply.strip():
            summary_msg = {"role": "system",
                           "content": f"[Сводка более раннего контекста]: {reply.strip()[:2000]}"}
            summarized = len(head)
    except Exception as e:
        log.warning(f"compaction: summarize call failed, hard-degrade: {e}")

    if summarized:
        compacted = system_msgs + [summary_msg] + tail
        replayed = True
    else:
        # Деградация без LLM: держим голову (2 первых) + хвост, середину — плейсхолдер
        drop_n = len(head) - 2
        note = {"role": "system", "content":
                f"[компакция без суммаризации: {drop_n} старых реплик отсечено]"}
        compacted = system_msgs + head[:2] + [note] + tail
        summarized = max(drop_n, 0)
        replayed = False
    tokens_after = estimate_tokens(compacted)
    return compacted, {"summarized": summarized, "tokens_before": tokens_before,
                       "tokens_after": tokens_after, "replayed": replayed}


# ────────────────────────── оркестратор ──────────────────────────

def compact_context(messages, dept, chain=None, provider=None, summarize_fn=None,
                    chat_id=None):
    """Полный конвейер компакции перед отправкой в LLM (точка: call_llm шаг 1).

    1) offload гигантских tool-выводов (независимо от бюджета);
    2) если оценочные токены > budget — prune с защитой хвоста;
    3) если всё ещё > budget — summarize (хвост-реплей последнего user-хода).
    Метрики: трейс FO-004 (event=compaction) + запись-заготовка Part #83
    в dialog_history (только при переданном chat_id, ошибку БД глотаем).
    Возвращает (messages, stats).
    """
    tokens_before = estimate_tokens(messages)
    budget = get_context_budget(dept, chain=chain, provider=provider)
    stats = {"strategy": "none", "budget": budget, "tokens_before": tokens_before,
             "tokens_after": tokens_before, "pruned": 0, "summarized": 0,
             "offloaded": 0, "replayed": False}

    messages, off = offload_giant_outputs(messages, dept)
    stats["offloaded"] = off["offloaded"]

    est = estimate_tokens(messages)
    if est > budget:
        messages, pr = prune_history(messages, budget, dept)
        stats["pruned"] = pr["pruned"]
        est = estimate_tokens(messages)
        if est > budget and summarize_fn is not None:
            messages, sm = summarize_overflow(messages, dept, summarize_fn)
            stats["summarized"] = sm["summarized"]
            stats["replayed"] = sm["replayed"]
            est = estimate_tokens(messages)

    stats["tokens_after"] = est
    if stats["pruned"] and stats["summarized"]:
        stats["strategy"] = "prune+summarize"
    elif stats["summarized"]:
        stats["strategy"] = "summarize"
    elif stats["pruned"]:
        stats["strategy"] = "prune"
    elif stats["offloaded"]:
        stats["strategy"] = "offload"

    if stats["strategy"] != "none":
        _write_llm_trace({
            "event": "compaction",
            "ts": datetime.now(timezone.utc).isoformat(),
            "dept": dept,
            "strategy": stats["strategy"],
            "tokens_before": stats["tokens_before"],
            "tokens_after": stats["tokens_after"],
            "tokens_saved": max(stats["tokens_before"] - stats["tokens_after"], 0),
            "pruned_msgs": stats["pruned"],
            "summarized_msgs": stats["summarized"],
            "offloaded_msgs": stats["offloaded"],
            "last_user_replayed": stats["replayed"],
            "budget": budget,
        })
        if chat_id:
            try:
                rec = {"part_type": "compaction", "dept": dept,
                       "strategy": stats["strategy"],
                       "tokens_before": stats["tokens_before"],
                       "tokens_after": stats["tokens_after"],
                       "pruned": stats["pruned"], "summarized": stats["summarized"],
                       "offloaded": stats["offloaded"]}
                _query("INSERT INTO dialog_history (chat_id, role, dept, content) "
                       "VALUES (?, 'system', ?, ?)",
                       (str(chat_id), dept, json.dumps(rec, ensure_ascii=False)))
            except Exception as e:
                log.warning(f"compaction: dialog_history record failed (non-fatal): {e}")
        log.info(f"Compaction dept={dept} strategy={stats['strategy']} "
                 f"tokens {stats['tokens_before']} -> {stats['tokens_after']} "
                 f"(budget={budget}, pruned={stats['pruned']}, "
                 f"summarized={stats['summarized']}, offloaded={stats['offloaded']})")
    return messages, stats
