#!/usr/bin/env python3
"""#739 SRC-3 A.2: первый разобранный случай — Крымский мост 17.11.

Внесение из таблицы аудита наряда (аудитор 20.11). Данные news_cache
песочницы за окно 16.11 21:00 – 18.11 21:00 (UTC+3) ОТСУТСТВУЮТ (кэш
песочницы не содержит записей 17.11 — проверено 22.11: 0 записей),
поэтому строки вносятся из таблицы аудита с пометкой происхождения.
В счёт (counted=1) — только источники из лент офиса (#737): РИА Новости.
Остальные — справочно (counted=0): лент офиса нет (Аксёнов/UA-каналы/
The Insider/Настоящее время/Moscow Times/Euromaidan/Медиазона/Ведомости/
РИА Новости Крым). Идемпотентно: повторный запуск не дублирует.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")

from proxy.core import _query  # noqa: E402
from proxy.news import (  # noqa: E402
    register_resolved_event, set_report_match, source_accuracy,
    source_rating_table, _ensure_source_tables,
)

EVENT = "Крымский мост 17.11 — обрушение пролёта"
FACT = ("атака БПЛА 17.11, обрушение автопролёта (арка в море); "
        "2 погибших (подтверждено Аксёновым позже); ж/д арка повреждена 19.11")
OUTCOME = "confirmed"
CONFIRMED_BY = "аудитор 20.11 (таблица наряда #739)"

# Таблица аудита наряда (время по Минску = UTC+3):
# (источник, время, утверждение, match, counted — в лентах офиса?)
ROWS = [
    ("Аксёнов, Telegram", "2026-11-17T01:35+03:00",
     "атака, движение остановлено", "yes", 0),      # вне лент офиса
    ("Exilenova+ (Telegram)", None, "фото, обрушение арки и пролёта, фарватер перекрыт", "yes", 0),
    ("Supernova+ (Telegram)", None, "фото, обрушение арки и пролёта", "yes", 0),
    ("Dnipro Osint (Telegram)", None, "фото, обрушение арки и пролёта", "yes", 0),
    ("Крымский ветер (Telegram)", None, "фото, обрушение арки и пролёта", "yes", 0),
    ("The Insider", "2026-11-17T06:58+03:00",
     "частичное обрушение, по неофициальным источникам, официально не подтверждено",
     "yes", 0),                                     # вне лент офиса
    # РИА Новости — лента офиса есть (#737); запись 09:08 в news_cache
    # песочницы отсутствует — время/утверждение из таблицы аудита
    ("РИА Новости", "2026-11-17T09:08+03:00",
     "Минтранс: ущерб оценивается, пострадавших, по предварительной информации, нет",
     "no", 1),                                      # В СЧЁТ
    ("Настоящее время", "2026-11-17T09:26+03:00",
     "обрушение автопролёта, 2 погибших", "yes", 0),  # вне лент офиса
    ("РИА Новости Крым", "2026-11-17T09:41+03:00",
     "ущерб оценивается, пострадавших нет", "no", 0),  # ленты нет
    ("The Moscow Times", "2026-11-17T09:52+03:00",
     "фото без арки 227 м; Кремль назвал повреждения незначительными", "yes", 0),
    ("Euromaidan Press", "2026-11-17T11:05+03:00",
     "арка автопролёта в море, ж/д арка стоит", "yes", 0),
    ("Ведомости", "2026-11-17T11:22+03:00",
     "повреждены конструкции, об обрушении нет", "partial", 0),  # ленты нет
    ("Медиазона", "2026-11-17T11:46+03:00",
     "кадры обрушения, СК: повреждения конструкции, 2 погибших", "yes", 0),
]


def main():
    _ensure_source_tables()
    ev_id, created = register_resolved_event(EVENT, FACT, OUTCOME, CONFIRMED_BY)
    print(f"событие: id={ev_id}, created={created}")
    for source, published, claim, match, counted in ROWS:
        # идемпотентность: (event, source) уже оценён — не дублируем
        rep = _query("SELECT id, match FROM source_reports "
                     "WHERE event_id = ? AND source = ?",
                     (ev_id, source), fetch=True)
        if rep:
            print(f"  пропуск (уже есть): {source}")
            continue
        rid, ok = set_report_match(EVENT, source, match, counted=counted)
        # время публикации и утверждение — уточняем, если строка создана
        # set_report_match'ом с пустыми полями
        _query("UPDATE source_reports SET published = COALESCE(NULLIF(?, ''), published), "
               "claim = COALESCE(NULLIF(?, ''), claim) WHERE id = ?",
               (published, claim, rid))
        print(f"  внесено: {source} → {match} (counted={counted}, id={rid})")
    acc, n = source_accuracy("РИА Новости")
    print(f"\nсчёт РИА Новости (единственный в лентах офиса): точн. {acc:.2f} (n={n})")
    print("таблица рейтинга:")
    for r in source_rating_table():
        print(f"  {r['source']:28s} точн.={r['accuracy']:.2f} n={r['events']} "
              f"скорость={r['speed_median_min']} {'мало данных' if r['few_data'] else ''}")


if __name__ == "__main__":
    main()
