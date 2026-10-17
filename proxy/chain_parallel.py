#!/usr/bin/env python3
"""proxy/chain_parallel.py — FO-026: fan-out + debate для /chain.

Плоскость параллельности (референсы: CrewAI processes/manager, AutoGen
GroupChat, multiagent-debate Du et al. 2023; прецедент параллельности в
кодовой базе — race-first-2 в proxy/providers.py).

Архитектура:
  mlog /chain parallel qa,legal <query>
    → http_post /chain/fanout {mode, depts, query, chat_id}
      → ThreadPoolExecutor: N параллельных шагов — каждый http_post в
        mlogserve POST /chain/step {dept, query, chat_id, group_id}
        (департаментские обработчики остаются mlog-паттернами)
      → судья: call_llm(dept="admin", combo="admin_analyze" → fosved-deep)
        синтезирует финал с цитированием вкладов
    → mlog получает {group_id, results, judge} и отправляет владельцу

debate: 2 департамента, ≤2 раунда: раунд 1 — независимо; раунд 2 — каждый
видит ответ другого (peer_context через тот же /chain/step); судья —
вердикт с расхождениями.

Гард-рейлы (enforced, не декларация):
  - parallel: ≤3 департаментов (4-й — громкий 400);
  - debate: ровно 2 департамента (3-й — громкий 400), раунды ≤2;
  - таймаут группы = 2 × таймаут шага (worst-департамент не держит группу);
  - упавший департамент не валит группу — судья работает на оставшихся
    с громкой пометкой «ответов N/M»;
  - каждый шаг и судья — audit_log + трейсы с общим group_id (одна сессия
    в Mini App-графиках FO-011).
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as http_requests

from flask import request, jsonify

from proxy.core import app, _log_audit, _log_error, log, _internal_auth_headers

MLOGSERVE_URL = "http://127.0.0.1:10001"
STEP_TIMEOUT_SECS = float(os.environ.get("CHAIN_STEP_TIMEOUT_SECS", "90"))
GROUP_TIMEOUT_SECS = 2 * STEP_TIMEOUT_SECS  # группа < worst-департамент × 2

MAX_PARALLEL_DEPTS = 3
MAX_DEBATE_DEPTS = 2
MAX_DEBATE_ROUNDS = 2

_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="chain-fanout")


def _invoke_step(dept, query, chat_id, group_id, round_no=1, peer_context=None):
    """Один шаг департамента: HTTP в mlogserve /chain/step (monkeypatch-friendly)."""
    payload = {"dept": dept, "query": query, "chat_id": chat_id,
               "group_id": group_id, "round": round_no}
    if peer_context:
        payload["peer_context"] = peer_context
    # #536 A.2 (эволюция #517): токен — в заголовке X-Internal-Token, не в URL
    # (query-токен утекал в журнал через текст исключений requests)
    resp = http_requests.post(f"{MLOGSERVE_URL}/chain/step", json=payload, headers=_internal_auth_headers(), timeout=STEP_TIMEOUT_SECS)
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("result", ""))


def _invoke_durable(dept, query, chat_id, chain_id, step_num, peer_context=None,
                    hash_extra=""):
    """FO-027: durable-степа — чекпоинт ДО/ПОСЛЕ, идемпотентность по
    input_hash; ok-степы переиспользуются без LLM-вызова."""
    from proxy.chain_durable import run_durable_step
    peer_ctx = peer_context if (step_num == 2 and peer_context) else None
    extra = hash_extra or (f"peer:{peer_ctx}" if peer_ctx else "")
    out = run_durable_step(dept, query, chat_id, chain_id, step_num,
                           "fanout", _invoke_step, hash_extra=extra,
                           peer_context=peer_ctx)
    return out["reply"]


def _audit_step(group_id, what, details):
    _log_audit(what, {"group_id": group_id, **details}, dept="chain")


def _fanout_once(depts, query, chat_id, group_id, round_no=1, peer_for=None):
    """Параллельный прогон списка департаментов (durable-степы FO-027).
    peer_for: {dept: peer_text} — контекст коллеги для раунда 2 debate."""
    futures = {}
    for d in depts:
        ctx = peer_for.get(d) if peer_for else None
        futures[_pool.submit(_invoke_durable, d, query, chat_id, group_id,
                             round_no, ctx)] = d
    answers, failed = {}, []
    deadline = time.monotonic() + GROUP_TIMEOUT_SECS
    for fut in as_completed(futures, timeout=max(deadline - time.monotonic(), 1)):
        d = futures[fut]
        try:
            answers[d] = fut.result()
        except Exception as e:
            failed.append(d)
            _log_error(f"chain step failed group={group_id} dept={d}: {e}",
                       source="chain", dept=d, kind="chain_step")
    return answers, failed


def _judge(query, answers, failed, group_id, mode, discrepancies=None):
    """Судья: admin_analyze-модель (fosved-deep) синтезирует финал."""
    from proxy.providers import call_llm
    contribs = "\n\n".join(
        f"=== Вклад {dept} ===\n{text}" for dept, text in answers.items())
    note = ""
    if failed:
        note = f"\n\n⚠️ ВНИМАНИЕ: ответов {len(answers)}/{len(answers) + len(failed)} — департаменты не ответили: {', '.join(failed)}."
    if mode == "debate":
        prompt = (f"Вопрос владельца: {query}\n\n"
                  f"Ниже — финальные позиции двух департаментов после дебатов "
                  f"(раунд взаимной критики). Дай вердикт: общие пункты, "
                  f"РАСХОЖДЕНИЯ (цитируя оба вклада), итоговая рекомендация.\n\n"
                  f"{contribs}{note}")
    else:
        prompt = (f"Вопрос владельца: {query}\n\n"
                  f"Ниже — независимые вклады департаментов. Синтезируй финальный "
                  f"ответ, ОБЯЗАТЕЛЬНО цитируя вклад каждого департамента по имени. "
                  f"Отметь противоречия между вкладами.\n\n{contribs}{note}")
    res = call_llm("admin", [{"role": "user", "content": prompt}],
                   combo="admin_analyze", command="")
    judge_text = res.get("reply", "") if isinstance(res, dict) else str(res)
    _audit_step(group_id, "chain_judge", {"mode": mode, "depts": list(answers.keys()),
                                          "failed": failed, "judge_chars": len(judge_text)})
    return judge_text


def _format_final(mode, group_id, judge_text, answers, failed, requested):
    head = f"Chain {mode} [{group_id[:8]}]: {len(answers)}/{len(requested)} ответов"
    if failed:
        head += f" (не ответили: {', '.join(failed)})"
    return head + "\n\n" + judge_text


@app.post("/chain/fanout")
def chain_fanout():
    """Точка входа fan-out/debate. mlog /chain parallel|debate вызывает сюда."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        mode = str(data.get("mode", "parallel"))
        depts = [str(d).strip() for d in (data.get("depts") or []) if str(d).strip()]
        query = str(data.get("query", "")).strip()
        chat_id = str(data.get("chat_id", "0"))

        if not query:
            return jsonify({"status": "error", "message": "query пуст"}), 400

        # Гард-рейлы — ENFORCED (тест на 4-й департамент — громкий отказ)
        if mode == "parallel":
            if len(depts) > MAX_PARALLEL_DEPTS:
                return jsonify({"status": "error",
                                "message": f"fan-out cap: максимум {MAX_PARALLEL_DEPTS} департаментов, получено {len(depts)}. Бюджет fan-out ≤ 3× одиночного департамента."}), 400
        elif mode == "debate":
            if len(depts) > MAX_DEBATE_DEPTS:
                return jsonify({"status": "error",
                                "message": f"debate cap: ровно {MAX_DEBATE_DEPTS} департамента, получено {len(depts)}."}), 400
            depts = depts[:MAX_DEBATE_DEPTS]
        else:
            return jsonify({"status": "error", "message": f"неизвестный mode: {mode}"}), 400
        if len(depts) < 2:
            return jsonify({"status": "error", "message": "нужно минимум 2 департамента (для одиночного используйте /chain sequential)"}), 400

        group_id = uuid.uuid4().hex
        _audit_step(group_id, "chain_fanout_start", {"mode": mode, "depts": depts})

        failed = []
        final_answers = {}
        if mode == "parallel":
            answers, failed = _fanout_once(depts, query, chat_id, group_id)
            if not answers:
                return jsonify({"status": "error",
                                "message": "все департаменты не ответили", "group_id": group_id}), 502
            final_answers = answers
            judge_text = _judge(query, answers, failed, group_id, "parallel")
            final = _format_final("parallel", group_id, judge_text, answers, failed, depts)
        else:
            # debate: раунд 1 — независимо
            a1, f1 = _fanout_once(depts, query, chat_id, group_id, round_no=1)
            # раунд 2 — каждый видит ответ другого (≤ MAX_DEBATE_ROUNDS enforced)
            peer_for = {}
            for d in depts:
                peer = next((o for o in depts if o != d), None)
                peer_for[d] = f"Ответ коллеги ({peer}):\n{a1.get(peer, '(коллега не ответил)')}" if peer else None
            a2, f2 = _fanout_once(depts, query, chat_id, group_id,
                                  round_no=2, peer_for=peer_for)
            failed = list(set(f1) | set(f2))
            # не ответивший во 2-м раунде — берём его ответ 1-го раунда
            for d in depts:
                if d in a1:
                    a2.setdefault(d, a1[d] + "\n(поправки во 2-м раунде не дал)")
            if not a2:
                return jsonify({"status": "error",
                                "message": "оба департамента не ответили", "group_id": group_id}), 502
            final_answers = a2
            judge_text = _judge(query, a2, failed, group_id, "debate",
                                discrepancies=True)
            final = _format_final("debate", group_id, judge_text, a2, failed, depts)

        return jsonify({"status": "ok", "group_id": group_id,
                        "answers": [{"dept": d, "answer": t}
                                    for d, t in final_answers.items()],
                        "failed": failed, "judge": final})
    except Exception as e:
        _log_error(f"chain fanout failed: {e}", source="chain", dept="chain",
                   kind="chain_fanout")
        return jsonify({"status": "error", "message": str(e)[:300]}), 500
