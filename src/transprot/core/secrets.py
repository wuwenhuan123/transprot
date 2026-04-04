from __future__ import annotations

import ctypes
import sys
from abc import ABC, abstractmethod
from ctypes import wintypes

from transprot.core.errors import SecretStoreError

_SECRET_TARGET = "TransProt:translation_api_key"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class SecretStore(ABC):
    @abstractmethod
    def load_api_key(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_api_key(self, api_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_api_key(self) -> None:
        raise NotImplementedError

    def has_api_key(self) -> bool:
        return bool(self.load_api_key().strip())


if sys.platform == "win32":
    LPBYTE = ctypes.POINTER(ctypes.c_ubyte)

    class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
        _fields_ = [
            ("Keyword", ctypes.c_wchar_p),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", LPBYTE),
        ]


    PCREDENTIAL_ATTRIBUTEW = ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)


    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", ctypes.c_wchar_p),
            ("Comment", ctypes.c_wchar_p),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", LPBYTE),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", PCREDENTIAL_ATTRIBUTEW),
            ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]


    PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
    _ADVAPI32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _ADVAPI32.CredReadW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCREDENTIALW)]
    _ADVAPI32.CredReadW.restype = wintypes.BOOL
    _ADVAPI32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    _ADVAPI32.CredWriteW.restype = wintypes.BOOL
    _ADVAPI32.CredDeleteW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD]
    _ADVAPI32.CredDeleteW.restype = wintypes.BOOL
    _ADVAPI32.CredFree.argtypes = [ctypes.c_void_p]
    _ADVAPI32.CredFree.restype = None
else:
    CREDENTIALW = None
    PCREDENTIALW = None
    _ADVAPI32 = None


class WindowsCredentialSecretStore(SecretStore):
    def __init__(self, target_name: str = _SECRET_TARGET) -> None:
        if sys.platform != "win32" or _ADVAPI32 is None:
            raise SecretStoreError("当前版本仅支持通过 Windows Credential Manager 存储 API 密钥。")
        self._target_name = target_name

    def load_api_key(self) -> str:
        credential_ptr = PCREDENTIALW()
        success = _ADVAPI32.CredReadW(self._target_name, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr))
        if not success:
            error_code = ctypes.get_last_error()
            if error_code == _ERROR_NOT_FOUND:
                return ""
            raise SecretStoreError(self._build_error_message("读取", error_code))

        try:
            credential = credential_ptr.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
                return ""
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-16-le").rstrip("\x00")
        finally:
            _ADVAPI32.CredFree(credential_ptr)

    def save_api_key(self, api_key: str) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise SecretStoreError("API 密钥不能为空。")

        encoded_key = normalized_key.encode("utf-16-le")
        blob = ctypes.create_string_buffer(encoded_key)
        credential = CREDENTIALW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = self._target_name
        credential.Comment = "TransProt translation API key"
        credential.CredentialBlobSize = len(encoded_key)
        credential.CredentialBlob = ctypes.cast(blob, LPBYTE)
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = "TransProt"

        success = _ADVAPI32.CredWriteW(ctypes.byref(credential), 0)
        if not success:
            raise SecretStoreError(self._build_error_message("保存", ctypes.get_last_error()))

    def clear_api_key(self) -> None:
        success = _ADVAPI32.CredDeleteW(self._target_name, _CRED_TYPE_GENERIC, 0)
        if success:
            return
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_NOT_FOUND:
            return
        raise SecretStoreError(self._build_error_message("清除", error_code))

    @staticmethod
    def _build_error_message(action: str, error_code: int) -> str:
        return f"无法{action} Windows Credential Manager 中的 API 密钥：{ctypes.WinError(error_code).strerror}"


def create_secret_store() -> SecretStore:
    return WindowsCredentialSecretStore()
