#!/usr/bin/env python3
"""proxy/ua_scan.py — #712 MEM-1 (аудит 22.11 03:32): потоковый Scanner/
Analyzer UA (понимание кодовой базы офиса ночным циклом).

Механизм OOM 21–22.11 02:00:20–24 (две ночи одинаково): Scanner читал
~790 файлов read_text().splitlines() в память llm_proxy ПОВЕРХ
накопленной за сутки базы (бриф 21.11: 403 МБ из 512). При этом 70 из
82 МБ дерева скана — два бинарника bin/mlog* (36+33 МБ): их splitlines()
строит список из ~69k str-объектов (пик ≈ 3× размера файла), не нужный
для подсчёта строк.

Решение по наряду (аудит: «потоковое чтение, не держать все тексты
сразу, и/или дочерний процесс под RLIMIT, как backup») — сделаны ОБА:
  1. Стриминг (этот модуль): подсчёт строк — чанками по 256 КБ
     (пик памяти — константа, не зависит от размера файла); Analyzer
     держит только извлечённые факты (паттерны/маршруты), не тексты.
  2. Дочерний процесс: фазы 1–2 ночного цикла — scripts/ua_night_worker.py
     под RLIMIT_AS (run_tracked из night-cycle, как backup) — даже
     если Scanner вырастет, падает дочка, а не llm_proxy.

Маршруты /admin-ua/scan|analyze и _ua_*_internal в routes_admin.py
делегируют сюда (единая точка правды, без копий логики).
"""

import os
import re
from pathlib import Path

# Размер чанка чтения: 256 КБ — кратен странице, пик str/bytes — единицы
# МБ на ЛЮБОМ файле дерева (прежде: 36-МБ bin/mlog → список из 69k строк).
READ_CHUNK = 256 * 1024

# Те же пропуски, что были в routes_admin.SKIP_DIRS (единый набор UA).
SKIP_DIRS = {'data', '.git', 'node_modules', '__pycache__', 'отчёты',
             'tool-results', 'scripts', 'upload'}

KNOWN_BUILTINS = ['send_message', 'query', 'db_execute', 'kv_set', 'kv_get',
                  'SendTelegramReply', 'SendReport', 'DetectDepartment', 'CallLLMProxy',
                  'InitDB', 'HandleAdmin', 'HandleYana', 'HandleOSP', 'HandleLZ',
                  'list_dir', 'escape_json', 'to_string', 'to_float', 'to_int',
                  'index_of', 'substring', 'trim', 'lower', 'upper', 'starts_with',
                  'ends_with', 'contains', 'json_body', 'query_param', 'http_get']

DEFAULT_OFFICE_DIR = '/office'


def count_lines(path):
    """Число строк файла — потоково, чанками READ_CHUNK.

    read_text().splitlines() на 36-МБ bin/mlog строило пик ~100 МБ
    (bytes + str + список строк); здесь пик — один чанк (256 КБ).
    Счёт по b'\\n': файл без завершающего перевода строки учитывается
    как одна строка, если непуст — семантика прежнего splitlines().
    """
    n = 0
    ends_with_nl = False
    nonempty = False
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(READ_CHUNK)
                if not chunk:
                    break
                n += chunk.count(b'\n')
                ends_with_nl = chunk[-1:] == b'\n'
                nonempty = True
    except OSError:
        return 0
    if not nonempty:
        return 0
    # последний кусок без завершающего перевода — это строка тоже
    # (семантика splitlines: неполная последняя строка считается)
    if not ends_with_nl:
        n += 1
    return n


def _walk_office(office_dir):
    """os.walk с фильтром SKIP_DIRS (общий для scan/analyze)."""
    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield Path(root) / f


def scan_inventory(office_dir=DEFAULT_OFFICE_DIR):
    """Инвентарь файлов офиса (Scanner): пути, строки, типы, каталоги.

    Формат — прежний _ua_scan_internal (night-cycle, /admin-ua/scan):
    {'files': [..], 'total_lines', 'total_files', 'by_type', 'by_dir'},
    files отсортированы по числу строк. Разница — потоковый count_lines
    и поле size_kb из stat (как было).
    """
    inventory = {'files': [], 'total_lines': 0, 'total_files': 0,
                 'by_type': {}, 'by_dir': {}}
    office = Path(office_dir)
    for fpath in _walk_office(office):
        try:
            rel = str(fpath.relative_to(office))
            size_kb = round(fpath.stat().st_size / 1024, 1)
        except OSError:
            continue
        lines = count_lines(fpath)
        ext = fpath.suffix
        dir_name = rel.split('/')[0] if '/' in rel else 'root'
        inventory['files'].append({
            'path': rel, 'lines': lines, 'ext': ext, 'dir': dir_name,
            'size_kb': size_kb,
        })
        inventory['total_lines'] += lines
        inventory['total_files'] += 1
        inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
        inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1
    inventory['files'].sort(key=lambda x: x['lines'], reverse=True)
    return inventory


def analyze_files(office_dir=DEFAULT_OFFICE_DIR):
    """Анализ .mlog/.py (Analyzer): паттерны, маршруты, импорты, таблицы.

    Формат — прежний _ua_analyze_internal. Текст читается по одному
    файлу (максимум в дереве — ~400 КБ текста), в списке остаются
    только факты, не содержимое файлов: память результата не зависит
    от объёма дерева.
    """
    office = Path(office_dir)
    analysis = []
    for fpath in _walk_office(office):
        ext = fpath.suffix
        if ext not in ('.mlog', '.py'):
            continue
        try:
            rel = str(fpath.relative_to(office))
            content = fpath.read_text(errors='ignore')
        except OSError:
            continue

        fa = {'path': rel, 'patterns': [], 'routes': [], 'imports': [],
              'builtins_used': [], 'tables': []}

        if ext == '.mlog':
            for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                fa['patterns'].append({'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)})
            for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                fa['routes'].append({'path': m.group(1), 'method': m.group(2)})
            for m in re.finditer(r'import\s+([\w/]+)', content):
                fa['imports'].append(m.group(1))
            for b in KNOWN_BUILTINS:
                if b + '(' in content:
                    fa['builtins_used'].append(b)
            for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                fa['tables'].append(m.group(1))
        elif ext == '.py':
            for m in re.finditer(r'def\s+(\w+)\(', content):
                fa['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})
            for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                fa['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

        analysis.append(fa)
    return analysis
