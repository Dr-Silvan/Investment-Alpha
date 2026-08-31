from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure credential storage is supported on Windows only.")
    source, source_buffer = _blob(data)
    output = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    description = "투자 market data credentials" if protect else None
    if not operation(
        ctypes.byref(source), description, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def save_credentials(path: Path, api_key: str, api_secret: str) -> None:
    payload = json.dumps({"apiKey": api_key, "apiSecret": api_secret}).encode("utf-8")
    encrypted = _crypt(payload, protect=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    os.replace(temporary, path)


def load_credentials(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(_crypt(path.read_bytes(), protect=False).decode("utf-8"))
        if value.get("apiKey") and value.get("apiSecret"):
            return {"apiKey": str(value["apiKey"]), "apiSecret": str(value["apiSecret"])}
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    return None


def delete_credentials(path: Path) -> None:
    path.unlink(missing_ok=True)
