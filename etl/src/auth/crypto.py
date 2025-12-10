"""Session encryption helpers for persisted WebCivil cookies."""

from __future__ import annotations

import base64
import sys
from functools import lru_cache
from typing import Any, Optional, Tuple

from ..settings import get_settings
from ..utils.log import get_logger

__all__ = ["encrypt_bytes", "decrypt_bytes"]

_LOG = get_logger(__name__)

try:  # pragma: no cover - handled via dependency management
    from cryptography.fernet import Fernet  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - surfaced on use
    Fernet = None  # type: ignore[assignment]

_FERNET_PREFIX = b"FER1"
_DPAPI_PREFIX = b"DPA1"
_IS_WINDOWS = sys.platform.startswith("win")


def _encryption_enabled() -> bool:
    return get_settings().encrypt_sessions


def _load_env_key() -> Optional[bytes]:
    key = get_settings().session_kms_key
    if not key:
        return None
    candidate = key.strip().encode("ascii", "ignore")
    if len(candidate) == 0:
        return None
    if len(candidate) != 44:
        raise ValueError("SESSION_KMS_KEY must be a urlsafe base64-encoded 32-byte key")
    # Validate base64 and Fernet compatibility
    try:
        base64.urlsafe_b64decode(candidate)
    except Exception as exc:  # pragma: no cover - validation
        raise ValueError("SESSION_KMS_KEY must be valid urlsafe base64") from exc
    return candidate


class _DPAPICipher:
    """Windows DPAPI bridge for protecting session payloads."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        self._BLOB = DATA_BLOB

    def _bytes_to_blob(self, data: bytes) -> Tuple[Any, Optional[Any]]:
        buf_ref: Optional[Any] = None
        if data:
            array_type = self._ctypes.c_byte * len(data)
            buf_ref = array_type.from_buffer_copy(data)  # keep buffer alive during DPAPI call
            blob = self._BLOB(
                len(data), self._ctypes.cast(buf_ref, self._ctypes.POINTER(self._ctypes.c_byte))
            )
        else:
            null_ptr = self._ctypes.POINTER(self._ctypes.c_byte)()
            blob = self._BLOB(0, null_ptr)
        return blob, buf_ref

    def encrypt(self, data: bytes) -> bytes:
        blob_in, buf_ref = self._bytes_to_blob(data)
        blob_out = self._BLOB()
        if not self._crypt32.CryptProtectData(
            self._ctypes.byref(blob_in),  # type: ignore[arg-type]
            None,
            None,
            None,
            None,
            0,
            self._ctypes.byref(blob_out),  # type: ignore[arg-type]
        ):
            error = self._ctypes.GetLastError()
            raise OSError(error, "CryptProtectData failed")
        try:
            return self._ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._kernel32.LocalFree(blob_out.pbData)

    def decrypt(self, data: bytes) -> bytes:
        blob_in, buf_ref = self._bytes_to_blob(data)
        blob_out = self._BLOB()
        if not self._crypt32.CryptUnprotectData(
            self._ctypes.byref(blob_in),  # type: ignore[arg-type]
            None,
            None,
            None,
            None,
            0,
            self._ctypes.byref(blob_out),  # type: ignore[arg-type]
        ):
            error = self._ctypes.GetLastError()
            raise OSError(error, "CryptUnprotectData failed")
        try:
            return self._ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._kernel32.LocalFree(blob_out.pbData)


@lru_cache(maxsize=None)
def _resolve_cipher(
    expected: Optional[str] = None, require_flag: bool = True
) -> Tuple[str, object]:
    if require_flag and not _encryption_enabled():
        raise RuntimeError("Encryption requested but ENCRYPT_SESSIONS is disabled")

    env_key = _load_env_key()
    if env_key:
        if Fernet is None:
            raise ImportError("cryptography is required for Fernet session encryption")
        cipher = Fernet(env_key)
        if expected and expected != "fernet":
            raise RuntimeError("Session payload expects DPAPI but Fernet key provided")
        return "fernet", cipher

    if expected == "fernet":
        raise RuntimeError("Session is encrypted with Fernet but SESSION_KMS_KEY is not set")

    if not _IS_WINDOWS:
        raise RuntimeError(
            "Session encryption requires SESSION_KMS_KEY when running off Windows; "
            "provide a Fernet key or set ENCRYPT_SESSIONS=false for plaintext storage."
        )

    return "dpapi", _DPAPICipher()


def encrypt_bytes(payload: bytes) -> bytes:
    if not _encryption_enabled():
        return payload

    cipher_type, cipher = _resolve_cipher()
    if cipher_type == "fernet":
        encrypted = cipher.encrypt(payload)  # type: ignore[union-attr]
        return _FERNET_PREFIX + encrypted

    encrypted = cipher.encrypt(payload)  # type: ignore[union-attr]
    return _DPAPI_PREFIX + encrypted


def decrypt_bytes(payload: bytes) -> bytes:
    if not payload:
        return payload

    if payload.startswith(_FERNET_PREFIX):
        _, cipher = _resolve_cipher("fernet", require_flag=False)
        return cipher.decrypt(payload[len(_FERNET_PREFIX) :])  # type: ignore[union-attr]

    if payload.startswith(_DPAPI_PREFIX):
        _, cipher = _resolve_cipher("dpapi", require_flag=False)
        return cipher.decrypt(payload[len(_DPAPI_PREFIX) :])  # type: ignore[union-attr]

    # No recognizable header; return plaintext as-is
    return payload
