"""Наряд #670 (D-fin): финансы на карточке — шов в ответах HandleFinance,
поздняя оплата просроченных счетов, время возврата.

Структурные гвардии; поведенческие проверки — mlog-тесты dept/finance.mlog.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIN = (REPO_ROOT / "dept" / "finance.mlog").read_text(encoding="utf-8")
CARD = (REPO_ROOT / "dept" / "card.mlog").read_text(encoding="utf-8")


def _block(src: str, start_marker: str) -> str:
    start = src.index(start_marker)
    nxt = src.find("\npattern ", start + 10)
    nxt2 = src.find("\ntest ", start + 10)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return src[start:min(ends)] if ends else src[start:]


def test_seam_on_all_finance_answer_sites():
    """A.1: шов подключён ко ВСЕМ точкам ответов ИИ владельцу (9 сайтов).

    FinanceCalc (:1187) — ответ КОЛЛЕГЕ (team-навык), не владельцу — без шва.
    """
    prod = FIN[: FIN.index("ТЕСТЫ (#670)")]
    sites = prod.count('CardSeamVerdict("finance", reply, 0.0)')
    assert sites == 9, f"шов должен стоять на всех 9 точках ответа владельцу, найдено {sites}"
    # каждый вызов сопровождается strip-веткой (портируемой: strip под try)
    strips = prod.count("let stripped = TryVal(try CardTailStrip(reply))")
    assert strips == 9
    # FinanceCalc — не шов (ответ коллеге)
    calc = _block(FIN, "pattern FinanceCalc(")
    assert "CardSeamVerdict" not in calc


def test_forecast_prompt_tail_instruction():
    """A.1.3: промпт FinanceCashflowForecast требует хвост с value и horizon_days."""
    forecast = _block(FIN, "pattern FinanceCashflowForecast(")
    assert "ХВОСТ ДЛЯ КАРТОЧКИ" in forecast
    assert "horizon_days" in forecast and "value" in forecast
    # контракт принимает horizon_days (иначе инструкция давала бы FAIL)
    schema = _block(CARD, "pattern CardTailSchema(")
    assert '\\"horizon_days\\":{\\"type\\":\\"number\\"}' in schema


def test_forecast_value_from_tail():
    """A.1: forecast_value заполняется из value хвоста (CardSave, kind=number)."""
    assert "UPDATE dept_archive SET forecast_value" in CARD


def test_late_payment_transitions():
    """A.2: overdue/escalation/pre_legal → paid и partially_paid разрешены."""
    tr = _block(FIN, "pattern FinanceInvoiceTransition(")
    for st in ("overdue", "escalation", "pre_legal"):
        assert f'current == "{st}"' in tr, f"нет перехода из {st}"
    assert '"partially_paid"' in tr
    # причина обязательна для поздней оплаты
    assert "причина обязательна" in tr
    # запись в историю как у остальных
    assert "INSERT INTO invoice_status_history" in tr


def test_recovery_days_metric():
    """A.3: FinanceRecoveryDays — от ПЕРВОГО overdue до paid, медиана, round(x*100)/100."""
    assert "pattern FinanceRecoveryDays() -> String" in FIN
    rec = _block(FIN, "pattern FinanceRecoveryDays(")
    # источник — invoice_status_history, точки overdue/paid
    assert "invoice_status_history" in rec
    assert "to_status = 'overdue'" in rec and "to_status = 'paid'" in rec
    assert "нет данных" in rec
    assert "round(" in rec
    # вывод в FinanceScore
    score = _block(FIN, "pattern FinanceScore(")
    assert "FinanceRecoveryDays()" in score


def test_gates_untouched():
    """Запрет прохода: гейты финансов и формат не тронуты."""
    assert "pattern FinanceRunGates(" in FIN
    assert "pattern GateNoRetroactive(" in FIN
    # новых таблиц нет: только существующие CREATE
    creates = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", FIN)
    assert creates == [], "finance.mlog не должен создавать таблицы (наряд: новых таблиц нет)"
