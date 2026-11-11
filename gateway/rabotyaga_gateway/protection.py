from __future__ import annotations

import os
from typing import Protocol


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class PlaintextProtector:
    """Test-only protector; production startup never selects this implementation."""

    def protect(self, value: bytes) -> bytes:
        return value

    def unprotect(self, value: bytes) -> bytes:
        return value


class WindowsDPAPIProtector:
    """Encrypt bridge keys for the current Windows account using DPAPI."""

    _entropy = b"rabotyaga-ios-gateway-v1"

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows DPAPI is required for production bridge secrets")

    @staticmethod
    def _blob(value: bytes):
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        buffer = ctypes.create_string_buffer(value)
        return DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer, DATA_BLOB

    def protect(self, value: bytes) -> bytes:
        import ctypes

        in_blob, in_buffer, blob_type = self._blob(value)
        entropy_blob, entropy_buffer, _ = self._blob(self._entropy)
        out_blob = blob_type()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "Rabotyaga Gateway",
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            del in_buffer, entropy_buffer

    def unprotect(self, value: bytes) -> bytes:
        import ctypes

        in_blob, in_buffer, blob_type = self._blob(value)
        entropy_blob, entropy_buffer, _ = self._blob(self._entropy)
        out_blob = blob_type()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            del in_buffer, entropy_buffer
