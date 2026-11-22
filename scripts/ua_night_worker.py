#!/usr/bin/env python3
"""scripts/ua_night_worker.py — #712 MEM-1 (аудит 22.11): фазы 1–2 ночного
цикла UA (Scanner → Analyzer) дочерним процессом под RLIMIT_AS.

Механизм OOM 21–22.11 02:00:20–24: Scanner работал В llm_proxy поверх
накопленной за сутки базы (403 МБ из 512) — пик чтения дерева (прежде
~790 файлов через read_text().splitlines(), 70 из 82 МБ — бинарники
bin/mlog*) выбивал лимит контейнера, убивая главный процесс. По наряду
(«запуск дочерним процессом под RLIMIT, как backup») фазы 1–2 вынесены
в отдельный процесс: даже если воркеру не хватит памяти, падает ОН
(MemoryError → rc≠0 → понятная ошибка вызывающему), а llm_proxy и
контейнер живут («тяжёлая задача падает одна, а не роняет контейнер»).

Контракт:
  вход:  argv[1] — путь выходного JSON (каталог существует);
         argv[2] — office-каталог для скана (по умолчанию /office).
  выход: JSON {'inventory': …, 'analysis': …} (форматы прежних
         _ua_scan_internal / _ua_analyze_internal, без изменения).
  rc:    0 — успех; 2 — MemoryError; 3 — ошибка записи; 1 — прочее.

Вызывается из _ua_night_cycle_impl_inner через run_tracked (RLIMIT_AS +
RSS-метки + live-срезы — весь учёт #712 к воркеру применяется как к
любой дочерней задаче: предел, метки before/after/live, громкая строка
при падении по пределу).
"""
import json
import sys
import tracemalloc

sys.path.insert(0, __file__.rsplit('/', 2)[0] or '.')

from proxy.ua_scan import scan_inventory, analyze_files  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print("usage: ua_night_worker.py <out.json> [office_dir]", file=sys.stderr)
        return 1
    out_path = argv[1]
    office_dir = argv[2] if len(argv) > 2 else '/office'

    # Пик ВОРКЕРА (tracemalloc — только python-аллокации; RLIMIT_AS —
    # вся адресная дочка) — в лог и в ответ: выбор предела для
    # run_tracked — по фактам (аудит: пределы по пикам, не с потолка).
    tracemalloc.start()
    inventory = scan_inventory(office_dir)
    analysis = analyze_files(office_dir)
    _, peak = tracemalloc.get_traced_memory()

    payload = {'inventory': inventory, 'analysis': analysis,
               'worker_peak_alloc_mb': round(peak / (1024 * 1024), 1)}
    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
    except MemoryError:
        print("[ua-worker] MemoryError при записи результата", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"[ua-worker] запись {out_path} не удалась: {e}", file=sys.stderr)
        return 3
    print(f"[ua-worker] ok: files={inventory['total_files']} "
          f"analysis={len(analysis)} peak_alloc={payload['worker_peak_alloc_mb']}MB",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except MemoryError:
        # RLIMIT_AS дочки: падаем сами, вызывающий получает rc≠0 и
        # громкую строку run_tracked — контейнер жив (цель A.4 наряда).
        print("[ua-worker] MemoryError в фазах Scanner/Analyzer", file=sys.stderr)
        sys.exit(2)
