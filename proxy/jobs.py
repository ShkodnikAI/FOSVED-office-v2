#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #596 A.2: фоновые задания для длинных ночных фаз.

Лимит Metalogos — таймаут http_post/http_get 1..300 с (HTTP_TIMEOUT_RANGE),
а UA-цикл и golden-evals работают дольше. Режим ?async=1 у ночных эндпоинтов
запускает работу в этом реестре и сразу отвечает {"job_id": ...}; статус —
GET .../status?job=<id> (running|done|failed + итог).

Свойства (по наряду):
- итог фазы — по статусу задания, а не по таймауту HTTP;
- повторный запрос статуса после done возвращает тот же итог
  (результат хранится в реестре, а не одноразовый);
- поток — daemon: рестарт сервиса не ждёт ночные фазы.
"""
import threading
import uuid
from datetime import datetime, timedelta

# Реестр в процессе: ночные фазы живут на том же сервисе, что и Flask.
_JOBS = {}
_LOCK = threading.Lock()
MAX_JOBS = 50          # защита от распухания: старые вытесняются
JOB_TTL = timedelta(hours=2)  # итог живёт 2 ч — повторный статус тот же


def _prune_locked(now):
    """Вытеснить просроченные и лишние задания. Вызывать под _LOCK."""
    expired = [k for k, v in _JOBS.items()
               if v.get("finished_at") and now - v["finished_at"] > JOB_TTL]
    for k in expired:
        _JOBS.pop(k, None)
    while len(_JOBS) >= MAX_JOBS:
        oldest_key = min(_JOBS, key=lambda k: _JOBS[k]["started_at"])
        _JOBS.pop(oldest_key, None)


def start_job(fn, *args, **kwargs):
    """Запустить fn в фоновом потоке. Возвращает job_id (str)."""
    job_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow()
    with _LOCK:
        _prune_locked(now)
        _JOBS[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "started_at": now,
            "finished_at": None,
        }
    t = threading.Thread(target=_run, args=(job_id, fn, args, kwargs),
                         daemon=True, name=f"n596-job-{job_id}")
    t.start()
    return job_id


def _run(job_id, fn, args, kwargs):
    try:
        result = fn(*args, **kwargs)
        with _LOCK:
            j = _JOBS.get(job_id)
            if j is not None:
                j["status"] = "done"
                j["result"] = result
                j["finished_at"] = datetime.utcnow()
    except Exception as e:  # noqa: BLE001 — итог задания, не глушим молча
        with _LOCK:
            j = _JOBS.get(job_id)
            if j is not None:
                j["status"] = "failed"
                j["error"] = str(e)[:500]
                j["finished_at"] = datetime.utcnow()


def get_job(job_id):
    """Статус задания. None — неизвестный job_id. Итог после done стабилен."""
    with _LOCK:
        j = _JOBS.get(job_id or "")
        if j is None:
            return None
        return {"status": j["status"], "result": j["result"], "error": j["error"]}
