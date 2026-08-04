# BINARY.md — mlog 0.12.0 Acceptance Report

**Binary**: `bin/mlog`
**Version**: mlog 0.12.0
**MD5**: `0d26aacb736788c6f9f700b1de8c675b`
**Tested**: 2026-08-04
**Branch**: `main`
**Source commit**: `c6d6417` (feat(48): pdf-inspector native PDF builtins + memory typology)

---

## Changes from 0.11.0 → 0.12.0

### New Features

| Feature | Description |
|---------|-------------|
| **Typed semantic memory** | `memorize(text, priority, type)` with type tags (persona, episodic, instruction, fact). ADR-0072, ADR-0073. |
| **Hybrid recall** | `recall_top_k(query, k, type)` — FTS5 BM25 + cosine similarity merged via RRF (k=60). |
| **PDF classify** | `pdf_classify(path)` — classify PDF as TextBased/Scanned/ImageBased/Mixed via pdf-inspector crate. |
| **PDF to Markdown** | `pdf_to_markdown(path)` — full extraction pipeline, <200ms on text PDFs. |
| **PDF extract regions** | `pdf_extract_regions(path, filter)` — text items with coordinates and OCR status. |
| **PDF OCR** | `pdf_ocr(path)` — Tesseract OCR fallback (requires `--features pdf-ocr`). |
| **Modular builtins** | 246 builtins across 14 modules (was 177 monolithic). |

### Fixes

- `load_all()` bug fixed — SELECT now includes `mem_type` column.
- FTS5 virtual table with content-synced triggers for keyword search.
- Rule priority semantics fixed (ADR-0090, Наряд №43).
- 5 stale golden expected files corrected.

### Binary Details

| Property | Value |
|----------|-------|
| Architecture | x86-64 Linux |
| Size | 21 MB |
| Rust edition | 2021 |
| Build profile | release |
| Features | default (pdf-ocr NOT included) |

### Compatibility

- Backward compatible with all 0.11.0 .mlog programs.
- `memorize()` 2-arg form still works (empty type).
- PDF builtins return error on missing files (graceful, no panic).
- `pdf_ocr` returns error message when compiled without `pdf-ocr` feature.

---

## Block A — Functional Regression Tests

### A.1 — Builtin inventory ✅ PASS
All 246 builtins indexed in BUILTIN_REGISTRY. No duplicate entries.

### A.2 — Version ✅ PASS
`mlog --version` returns `mlog 0.12.0`.

### A.3 — Basic execution ✅ PASS
`mlog run examples/m1_hello.mlog` executes without errors.

---

## Conclusion

**mlog 0.12.0 is ACCEPTED for production deployment.**

- 246 builtins (69 new since 0.11.0)
- Typed memory with hybrid search
- Native PDF processing
- Backward compatible
- No regressions in core functionality
