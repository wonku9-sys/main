"""Windows-user DPAPI for SMTP credentials, never a built-in shared password."""
import ctypes
from ctypes import wintypes
import sys


def _dpapi(payload, decrypt=False):
    if sys.platform != "win32":
        raise ValueError("발송용 메일 비밀번호의 안전한 저장은 Windows 실행판에서 설정하세요.")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(bytes(payload))
    source = Blob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("메일 비밀번호를 이 Windows 사용자 계정에서 열 수 없습니다. 관리자 설정에서 발송 계정을 다시 저장하세요.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        if target.data:
            ctypes.memset(target.data, 0, target.size)
            kernel.LocalFree(target.data)


def protect(payload):
    return _dpapi(payload)


def unprotect(payload):
    return _dpapi(payload, decrypt=True)
