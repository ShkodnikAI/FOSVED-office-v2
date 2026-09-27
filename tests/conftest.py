#!/usr/bin/env python3
"""Глобальные гарантии герметичности тестов.

#408: подбор фото WB (_wb_direct_probe) — прямой HEAD в процессе. Чтобы ни
один тест, не занимающийся фото-WB, не ходил в сеть, транспорт проб по
умолчанию заглушен честным «нет ответа». Тесты, проверяющие механику проб
(#329/#408), перекрывают стаб точечно (см. test_shop3_collectors._probe_stub).
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def no_real_wb_probe(monkeypatch):
    try:
        from proxy import shop_collectors as _sc
        monkeypatch.setattr(_sc, "_wb_direct_probe", lambda url: False)
    except Exception:  # noqa: BLE001 — модуль ещё не импортирован в этом тесте
        pass
    yield
