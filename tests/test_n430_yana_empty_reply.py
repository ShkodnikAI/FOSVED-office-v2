"""Гвард наряда #430: пустое сообщение Яны после досье не отправляется.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/430
YanaCheckShop различает «маркера не было» ("") и «досье-поток отработал,
текста нет» (SHOP_HANDLED: пустой остаток при живом досье + все отказные
ветки). HandleYana при отработанном потоке выходит до футера/записи —
«Яна + модель/токены» без текста не уходит.
Запуск: python -m pytest tests/test_n430_yana_empty_reply.py -v
Живой тест: test_n430v1.mlog (в корне, конвенция репо; 5 проверок).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
YANA = (REPO_ROOT / "dept" / "yana.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def test_checkshop_returns_handled_flag_on_empty_remainder():
    # модель ответила только маркером → не пустая строка, а флаг:
    # вызывающий обязан отличить «поток отработал» от «маркера не было»
    assert 'if remainder == "" then { return "SHOP_HANDLED" }' in YANA


def test_checkshop_refusal_branches_flag_handled():
    # отказ уже отправлен владельцу — поток отработан, текста нет
    block = YANA.split("pattern YanaCheckShop")[1].split("pattern YanaCheckRemind")[0]
    assert block.count('return "SHOP_HANDLED"') == 4, \
        "все ветки «поток отработал» (3 отказа + пустой остаток) должны возвращать флаг"
    # старые пустые возвраты остались только на «маркера не было / битый маркер»
    assert 'return ""' in block


def test_handle_yana_exits_before_footer_and_memory():
    # #430 A.1: ранний выход до RecordAssistantMessage/AutoMemorize/футера
    assert "let mut shop_handled = 0.0" in YANA
    assert "let shop_handled = 1.0" in YANA
    block = YANA.split("if shop_handled == 1.0")[1][:200]
    assert 'return ""' in block
    # выход раньше RecordAssistantMessage
    early = YANA.split("if shop_handled == 1.0")[0]
    assert "RecordAssistantMessage(chat_id, dept, final_reply)" in YANA
    assert YANA.index("if shop_handled == 1.0") < YANA.index("RecordAssistantMessage(chat_id, dept, final_reply)")


def test_app_guard_for_empty_reply_kept():
    # #409: гвард «пустой ответ не отправляется» в app.mlog не тронут
    assert "if length(reply) > 0.0 then" in APP
    assert 'text: "Яна\\n\\n" + reply' in APP


def test_no_flag_leak_into_visible_text():
    # SHOP_HANDLED не начинается с "[SHOP:" — повторная вырезка/показ не сработает
    assert 'return "SHOP_HANDLED"' in YANA
    block = YANA.split("pattern YanaCheckShop")[1].split("pattern YanaCheckRemind")[0]
    assert "SHOP_HANDLED" not in block.split("if contains(reply")[0], \
        "флаг не должен покидать поток до проверки маркера"
