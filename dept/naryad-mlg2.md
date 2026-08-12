# Наряд MLG-2: Расширение Металогос — PDF на чистом Rust

**Дата:** 2026-08-12  
**Приоритет:** Высокий (грантовая стратегия: язык самодостаточен)  
**Статус:** В работе  
**Заказчик:** Хозяин  

---

## Контекст

Наряд MLG-1 добавил функции создания/манипуляции PDF в Металогос, но 5 из них делегируют в Python (PyPDF2/weasyprint). Это нарушает стратегию гранта: **Металогос должен быть самодостаточен** — не зависеть от Python-прослойки.

## Проблема

| Функция | Текущая реализация | Проблема |
|---------|-------------------|----------|
| `pdf_merge(paths, out)` | `python3 -c "PyPDF2.PdfMerger..."` | Python-зависимость |
| `pdf_split(path, ranges, dir)` | `python3 -c "PyPDF2.PdfReader/Writer..."` | Python-зависимость |
| `pdf_metadata(path)` | `python3 -c "PyPDF2.PdfReader.metadata"` | Python-зависимость |
| `pdf_set_metadata(path, k, v)` | `python3 -c "PyPDF2.PdfReader/Writer..."` | Python-зависимость |
| `html_to_pdf(html, path)` | `wkhtmltopdf` → fallback `python3 -c "weasyprint..."` | Python-fallback |

## Решение

Переписать все 5 функций на **чистый Rust** через `lopdf` — direct dependency.

### Шаги

1. **Cargo.toml**: добавить `lopdf = "0.34"` в dependencies
2. **pdf.rs → builtin_pdf_merge**: переписать на `lopdf::Document` API — загрузить каждый PDF, скопировать страницы, записать результат
3. **pdf.rs → builtin_pdf_split**: переписать на `lopdf::Document` — загрузить, извлечь диапазоны страниц, записать части
4. **pdf.rs → builtin_pdf_metadata**: переписать на `lopdf::Document` — прочитать `/Info` dictionary напрямую
5. **pdf.rs → builtin_pdf_set_metadata**: переписать на `lopdf::Document` — модифицировать `/Info` dictionary, записать
6. **pdf.rs → builtin_html_to_pdf**: убрать Python weasyprint fallback; оставить только `wkhtmltopdf` (системный инструмент, не Python), добавить fallback через Rust `printpdf` crate или ошибку
7. **Скомпилировать**: `cargo build --release`, заменить `bin/mlog`
8. **Протестировать**: запустить тесты `cargo test -- phase48 pdf`
9. **Git**: commit + push

### Чистый Rust (уже OK)

Эти функции уже на чистом Rust — НЕ трогаем:
- `pdf_create()` — in-memory PdfDocument
- `pdf_add_page(id, w, h)` — in-memory
- `pdf_write_text(id, x, y, text, font, size)` — in-memory
- `pdf_draw_line(id, x1, y1, x2, y2, w)` — in-memory
- `pdf_draw_rect(id, x, y, w, h, stroke, fill)` — in-memory
- `pdf_save(id, path)` — custom PDF 1.4 renderer (render_pdf)
- `pdf_classify(path)` — pdf-inspector (Rust)
- `pdf_to_markdown(path)` — pdf-inspector (Rust)
- `pdf_extract_regions(path, regions)` — pdf-inspector (Rust)

### Критерии приёмки

- [ ] `pdf_merge` работает без Python
- [ ] `pdf_split` работает без Python
- [ ] `pdf_metadata` работает без Python
- [ ] `pdf_set_metadata` работает без Python
- [ ] `html_to_pdf` не имеет Python fallback
- [ ] `cargo build --release` без ошибок
- [ ] `cargo test` проходит
- [ ] Git commit + push выполнены

## Архитектурное решение (ADR-MLG-2)

**Выбор:** lopdf как direct dependency  
**Альтернативы:** pdf-rs, printpdf, juvinall/pdf  
**Обоснование:** lopdf — самый зрелый Rust PDF crate (2k+ stars), уже в dependency tree через pdf-inspector, поддерживает чтение+запись+модификацию PDF объектов, нулевой IPC

---

*Наряд составлен автоматизированно, выполняется согласно METHODOLOGY.md*
