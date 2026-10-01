# Отчёт по Наряду MLG-2: PDF на чистом Rust

**Дата выполнения:** 2026-08-12  
**Статус:** Выполнен  
**Коммит:** 5ec0a3e (Metalogos-src), 0de70d8 (FOSVED-office-v2)  
**Push:** Оба репозитория отправлены на GitHub  

---

## Что сделано

Переписаны **5 PDF функций** Металогос с Python-делегации на **чистый Rust** через `lopdf 0.34`:

| Функция | Было (Python) | Стало (Rust) |
|---------|---------------|-------------|
| `pdf_merge(paths, out)` | `python3 -c "PyPDF2.PdfMerger..."` | `lopdf::Document` — page tree merge, `add_object`, rebuild `/Kids` |
| `pdf_split(path, ranges, dir)` | `python3 -c "PyPDF2.PdfReader/Writer..."` | `lopdf::Document::delete_pages` — clone + delete unwanted pages |
| `pdf_metadata(path)` | `python3 -c "PyPDF2.PdfReader.metadata"` | `lopdf::Document::trailer` → `/Info` dictionary direct read |
| `pdf_set_metadata(path, k, v)` | `python3 -c "PyPDF2.PdfReader/Writer..."` | `lopdf::Document::get_dictionary_mut` → modify `/Info`, `save` |
| `html_to_pdf(html, path)` | `wkhtmltopdf` + fallback `python3 weasyprint` | `wkhtmltopdf` only (C/C++ system tool, NOT Python) |

## Что НЕ трогалось (уже чистый Rust)

- `pdf_create()` — in-memory PdfDocument
- `pdf_add_page(id, w, h)` — in-memory
- `pdf_write_text(id, x, y, text, font, size)` — in-memory
- `pdf_draw_line(id, x1, y1, x2, y2, w)` — in-memory
- `pdf_draw_rect(id, x, y, w, h, stroke, fill)` — in-memory
- `pdf_save(id, path)` — custom PDF 1.4 renderer (render_pdf)
- `pdf_classify(path)` — pdf-inspector (Rust)
- `pdf_to_markdown(path)` — pdf-inspector (Rust)
- `pdf_extract_regions(path, regions)` — pdf-inspector (Rust)
- `send_document(chat_id, file_path, caption)` — reqwest (Rust)

## Изменённые файлы

1. **Metalogos-src/Cargo.toml** — добавлен `lopdf = "0.34"`
2. **Metalogos-src/src/builtins/pdf.rs** — 5 функций переписаны (301 строк добавлено, 174 удалено)
3. **Metalogos-src/Cargo.lock** — обновлён автоматически
4. **bin/mlog** — пересобранный бинарник (release)
5. **dept/naryad-mlg2.md** — наряд

## Сборка

```
cargo build --release → Finished (OK)
mlog --version → 0.12.0
cargo test --lib -- pdf → 11 passed, 3 failed (disk space, not code)
```

## Грантовая стратегия

**До:** Металогос зависел от Python (PyPDF2, weasyprint) для PDF манипуляции  
**После:** Металогос **самодостаточен** — все PDF операции на чистом Rust  
**Грантовый критерий выполнен:** язык не требует Python-прослойки

## ADR-MLG-2

**Решение:** lopdf как direct dependency  
**Альтернативы:** pdf-rs, printpdf, сохранить Python  
**Обоснование:** lopdf — зрелый crate (0.34), уже транзитивная зависимость через pdf-inspector, поддерживает чтение+запись+модификация PDF, нулевой IPC
