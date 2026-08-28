# Отчёт: Fosved Seal UI — глобальный редизайн миниаппа

- Дата: 2026-08-28
- Ветка: `feat/miniapp-fosved-seal`
- База: `main`
- Файл: `miniapp/index.html` (single-file SPA)

## Что сделано

Полная замена визуального слоя. Старый cream/gold каркас снят.

### Дизайн-система Seal
- Тёмный ink `#0B0D10` + поверхности `#171B22`
- Акцент champagne gold `#D4AF5A` / ivory `#F4EFE4`
- Статусы: live `#3DDC97`, warn `#F0B429`, danger `#FF6B6B`
- Шрифты: Fraunces + Outfit + JetBrains Mono

### Эргономика
- Зона тапа 48px, nav 72px + safe-area
- Горизонтальные chips чата, haptic Telegram
- `prefers-reduced-motion`

### Логотип
SVG-печать: гексагон + щит + монограмма F + золотой градиент. Встроен в topbar.

### Функционал
6 вкладок, фильтры архива, sheet превью отчётов, чат `/dept/{id}` → `/chat`, LIVE/OFF, mock fallback, API URL в настройках.
