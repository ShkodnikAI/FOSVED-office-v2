#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MON-1 (#171): разовый интерактивный вход Telethon — Render Shell / локально.

⚠️  ОБЯЗАТЕЛЬНО использовать ОТДЕЛЬНЫЙ Telegram-аккаунт (не основной личный):
    сессия = полный доступ к аккаунту; риск лимитов и бана на основном.

Использование (в Render Shell):
    python3 scripts/telegram_login.py
Env:
    TELEGRAM_API_ID / TELEGRAM_API_HASH — my.telegram.org → API development tools
    TELEGRAM_SESSION_DIR — куда положить сессию (по умолчанию /var/data/telegram_session)

Шаги: номер телефона → код из Telegram → 2FA-пароль (если включён).
После успеха: сессия lz_monitor.session с правами 0600, каталог 0700.
Скрипт НЕ часть основного процесса офиса — только установка.
"""
import os
import sys
import stat


def main():
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        print("FAIL: задай TELEGRAM_API_ID и TELEGRAM_API_HASH "
              "(my.telegram.org → API development tools)")
        return 1
    try:
        from telethon import TelegramClient
    except ImportError:
        print("FAIL: telethon не установлен (pip install 'Telethon>=1.36')")
        return 1

    sdir = os.environ.get("TELEGRAM_SESSION_DIR", "/var/data/telegram_session")
    os.makedirs(sdir, exist_ok=True)
    os.chmod(sdir, 0o700)
    session_path = os.path.join(sdir, "lz_monitor")

    print(f"Вход MON-1 (сессия: {session_path}.session)")
    print("⚠️  Используй ОТДЕЛЬНЫЙ Telegram-аккаунт, не основной личный!")
    client = TelegramClient(session_path, int(api_id), api_hash,
                            device_model="fosved-lz-monitor")
    client.start()  # интерактивно: телефон → код → 2FA
    if not client.is_user_authorized():
        print("FAIL: авторизация не завершена")
        return 1
    me = client.get_me()
    session_file = session_path + ".session"
    if os.path.exists(session_file):
        os.chmod(session_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    print(f"OK: вход выполнен: {getattr(me, 'first_name', '')} "
          f"(@{getattr(me, 'username', '')})")
    print(f"OK: сессия сохранена: {session_file} (0600)")
    print("Дальше: TG_MONITOR_ENABLED=1 на Render + TELEGRAM_API_ID/HASH в env.")
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
