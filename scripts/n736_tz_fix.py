#!/usr/bin/env python3
"""#736 TZ-1: «MSK/МСК/по Москве» → «по Минску» в пользовательских текстах
и комментариях кода (mlog + proxy/*.py). Europe/Moscow уже заменён sed'ом.
Идиоматичные дефисные формы правятся отдельно; названия переменных и
cron-времена не трогаются."""
import re
from pathlib import Path

FILES = [
    "app.mlog", "dogfood_staging.mlog", "dept/schedules.mlog",
    "dept/scheduler.mlog", "dept/kk_training.mlog", "dept/engineering.mlog",
    "proxy/routes_tail.py", "proxy/lz_github.py", "proxy/routes_sched.py",
    "proxy/core.py", "proxy/shop_supply.py", "proxy/shop_dossier.py",
    "proxy/tg_public.py",
]

# порядок важен: дефисные/составные раньше простого «MSK»
RULES = [
    (r"MSK-дату", "дату по Минску"),
    (r"MSK-дата", "дата по Минску"),
    (r"MSK-дне", "дне по Минску"),
    (r"MSK-день", "день по Минску"),
    (r"в MSK wall-clock", "в wall-clock Минска"),
    (r"Дата — MSK", "Дата — по Минску"),
    (r"Датирование — MSK", "Датирование — по Минску"),
    (r"дедуп-фильтр дат — MSK", "дедуп-фильтр дат — по Минску"),
    (r"MSK", "Минск"),
    (r"МСК", "Минск"),
    (r"по Москве", "по Минску"),
]

total = {}
for f in FILES:
    p = Path(f)
    src = p.read_text(encoding="utf-8")
    out = src
    n = 0
    for pat, rep in RULES:
        out, k = re.subn(pat, rep, out)
        n += k
    if out != src:
        p.write_text(out, encoding="utf-8")
        total[f] = n

for f, n in total.items():
    print(f"{f}: {n} замен")
print("итого:", sum(total.values()))
