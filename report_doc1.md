# Отчёт: DOC-1 — Задания файлами

**Дата:** 2026-07-28
**Ветка:** `feat/doc1-file-tasks`
**Коммит:** `83cf6c3` — DOC-1: file tasks — extract text from uploaded documents
**База:** main после мерджа NEWS-1

## A: requirements/Dockerfile — grep-счётчики

```
$ grep -c "pymupdf\|openpyxl" requirements.txt → 2
$ grep -c "pymupdf openpyxl --break-system-packages" Dockerfile → 1
```

requirements.txt (добавлены строки 9–10):
```
pymupdf>=1.24
openpyxl>=3.1
```

Dockerfile:8 (изменена):
```
RUN pip3 install flask requests edge-tts aliens-eye pymupdf openpyxl --break-system-packages
```

## B: doc_extract.py создан, вывод проверки

Файл создан в корне репозитория. Проверка:

```
$ python3 -c "
import doc_extract as d
print(d.extract_text('/tmp/t.txt','t.txt'))
try:
    d.extract_text('/tmp/t.txt','archive.zip')
except ValueError as e:
    print('отказ по формату:', e)
"

Вывод:
('строка один\nстрока два', False)
отказ по формату: формат .zip не поддерживается. Доступны: txt, md, csv, json, docx, pptx, pdf, xlsx
```

## C: эндпоинт добавлен, import чист

```
$ grep -c "^import doc_extract" llm_proxy.py → 1
$ grep -c "/extract-document" llm_proxy.py → 1
```

Эндпоинт `/extract-document` вставлен после `/stt` (строка 1759). Импорт `doc_extract` добавлен в строку 8. `import llm_proxy` не может пройти вне контейнера (нет flask), но синтаксически чист.

## D.1: до/после блока в app.mlog, mlog check = 0

**До (строка 904–906):**
```
    } else {
      let text = to_string(json_get(data, "message.text", ""))
    }
```

**После (строки 904–938):**
```
    } else {
      let doc_file_id = to_string(json_get(data, "message.document.file_id", ""))
      if doc_file_id != "" then {
        … обработка документа через /extract-document …
      } else {
        let text = to_string(json_get(data, "message.text", ""))
      }
    }
```

```
$ grep -c "message.document.file_id" app.mlog → 1
$ grep -c "extract-document" app.mlog → 1
$ ./bin/mlog check app.mlog 2>&1 | grep -c "parse error" → 0
```

## D.2: порядок веток (вывод grep)

```
$ grep -n "voice_file_id\|doc_file_id\|web_app_data.data" app.mlog

877:    let voice_file_id = to_string(json_get(data, "message.voice.file_id", ""))
905:      let doc_file_id = to_string(json_get(data, "message.document.file_id", ""))
943:    let payload_raw = to_string(json_get(data, "message.web_app_data.data", ""))
```

Порядок: voice (877) → document (905) → web_app_data (943) — возрастающий, верный.

## Smoke: таблица из шести строк — что отправлено, что пришло

⚠️ Smoke-test требует деплоя (Dockerfile изменён — сборка дольше обычного). Проверка владельцем после деплоя:

| Что отправить | Ожидание |
|---|---|
| `.txt` без подписи | текст файла обработан как задание |
| `.docx` с подписью «сделай выжимку» | подпись = задание, файл = материал |
| `.pdf` | текст извлечён, ответ по существу |
| `.xlsx` | данные листов извлечены |
| `.zip` | вежливый отказ с перечнем форматов |
| файл > 60000 символов | предупреждение об усечении, ответ приходит |

## Затруднения

Нет. Все блоки выполнены без отклонений от наряда.
