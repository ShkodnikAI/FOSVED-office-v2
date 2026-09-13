#!/usr/bin/env python3
"""proxy/forge_secrets.py — FO-035 A.2: secrets_store (минимальный SEC-5).

Шифрование AES-256-GCM (тот же алгоритм, что нативные encrypt/decrypt ядра)
через cryptography (уже в requirements). Ключ — env FORGE_MASTER_KEY
(64 hex); отсутствие/битый ключ — ГРОМКАЯ ошибка, не молчаливое хранение
в открытом виде.

Почему не нативные encrypt/decrypt в mlog (зафиксировано в отчёт наряда):
ядро возвращает opaque Value::Encrypted (values.rs: Display → "[Encrypted]"),
строковой репрезентации для персистентности в SQLite из mlog нет. Схема
наряда соблюдена: secrets_store(key PK, value_encrypted, updated_at);
mlog-паттерны SetSecret/GetSecret вызывают эту плоскость через call_python
(whitelist + Guardian py_forge_secrets_*).

Мост: call_python("forge_secrets", "set", [key, plaintext]) → "ok"/"ОТКАЗ: ..."
      call_python("forge_secrets", "get", [key])               → plaintext/""
"""
import base64
import os

from proxy.core import _log_audit, _log_error, _query, log

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _CRYPTO_OK = True
except Exception as e:  # громкая диагностика при старте
    _CRYPTO_OK = False
    log.critical(f"[forge_secrets] cryptography unavailable: {e}")


def _master_key() -> bytes:
    raw = os.environ.get("FORGE_MASTER_KEY", "")
    if not raw:
        raise RuntimeError(
            "FORGE_MASTER_KEY не установлен — secrets_store отказывает "
            "(хранение в открытом виде запрещено)")
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        raise RuntimeError("FORGE_MASTER_KEY битый (ожидается 64 hex)")
    if len(key) != 32:
        raise RuntimeError(f"FORGE_MASTER_KEY должен быть 32 байта (64 hex), получено {len(key)}")
    return key


def handle(module: str, function: str, args: list):
    """Точка входа call_python-моста (вызывается как forge_secrets.<function>(*args))."""
    if module != "forge_secrets":
        return f"ОТКАЗ: unknown module {module}"
    try:
        if not _CRYPTO_OK:
            raise RuntimeError("cryptography package unavailable")
        key_bytes = _master_key()

        if function == "set":
            if len(args) < 2:
                return "ОТКАЗ: set требует (key, plaintext)"
            key, plaintext = str(args[0]), str(args[1])
            nonce = os.urandom(12)
            ct = AESGCM(key_bytes).encrypt(nonce, plaintext.encode("utf-8"), None)
            blob = "v1:" + base64.b64encode(nonce + ct).decode()
            _query("INSERT OR REPLACE INTO secrets_store (key, value_encrypted, updated_at) "
                   "VALUES (?, ?, datetime('now'))", (key, blob))
            _log_audit("forge_secret_set", {"key": key}, dept="dev")
            return "ok"

        if function == "get":
            if not args:
                return ""
            rows = _query("SELECT value_encrypted FROM secrets_store WHERE key = ?",
                          (str(args[0]),), fetch=True)
            if not rows:
                return ""
            blob = rows[0]["value_encrypted"] or ""
            if not blob.startswith("v1:"):
                _log_error(f"forge_secrets get: битый формат записи ({args[0]})",
                           source="forge", dept="dev", kind="forge_secrets")
                return ""
            raw = base64.b64decode(blob[3:])
            return AESGCM(key_bytes).decrypt(raw[:12], raw[12:], None).decode("utf-8")

        return f"ОТКАЗ: unknown function {function}"
    except Exception as e:
        _log_error(f"forge_secrets {function} failed: {e}", source="forge",
                   dept="dev", kind="forge_secrets")
        if function == "set":
            return f"ОТКАЗ: {e}"
        return ""  # get: "" при недоступности — mlog-контракт (fallback «руками»)
