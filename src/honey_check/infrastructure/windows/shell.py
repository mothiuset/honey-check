"""Operaciones del Explorador: enviar a la Papelera de reciclaje y vaciarla."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
_SHERB_NOCONFIRMATION = 0x1
_SHERB_NOPROGRESSUI = 0x2
_SHERB_NOSOUND = 0x4


class _SHFileOpStruct(ctypes.Structure):
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    )


class _QueryRecycleBinInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    )


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.SHFileOperationW.argtypes = (ctypes.POINTER(_SHFileOpStruct),)
_shell32.SHFileOperationW.restype = ctypes.c_int
_shell32.SHEmptyRecycleBinW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD)
_shell32.SHEmptyRecycleBinW.restype = ctypes.c_long
_shell32.SHQueryRecycleBinW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(_QueryRecycleBinInfo))
_shell32.SHQueryRecycleBinW.restype = ctypes.c_long


def send_to_recycle_bin(path: str) -> int:
    """0 si quedó en la Papelera (recuperable); otro valor es el código de error del Explorador."""
    operation = _SHFileOpStruct()
    operation.wFunc = _FO_DELETE
    operation.pFrom = path + "\0"  # lista terminada en doble nulo
    operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI
    result = _shell32.SHFileOperationW(ctypes.byref(operation))
    return int(result) if result or not operation.fAnyOperationsAborted else 1


def recycle_bin_usage(root: str | None = None) -> tuple[int, int]:
    """Bytes y elementos en la Papelera de todas las unidades, o de una («D:\»)."""
    info = _QueryRecycleBinInfo()
    info.cbSize = ctypes.sizeof(info)
    if _shell32.SHQueryRecycleBinW(root, ctypes.byref(info)) != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin(root: str | None = None) -> bool:
    """Vacía la Papelera de todas las unidades, o solo la de `root` («D:\»)."""
    hr = _shell32.SHEmptyRecycleBinW(
        None, root, _SHERB_NOCONFIRMATION | _SHERB_NOPROGRESSUI | _SHERB_NOSOUND
    )
    # S_OK, o E_UNEXPECTED cuando ya estaba vacía.
    return hr in (0, -2147418113)


# --- Ventanas del Explorador ----------------------------------------------------------------------
# Windows no deja que un proceso en segundo plano (el servicio de Honey Check; al frente está el
# navegador) ponga una ventana adelante: el Explorador se abría detrás de las demás. Se busca la
# ventana que acaba de abrir y se trae al frente uniendo la entrada con la ventana activa, como
# permite Windows para ese caso.

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = (_EnumProc, wintypes.LPARAM)
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_user32.BringWindowToTop.argtypes = (wintypes.HWND,)
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_SW_RESTORE = 9


def explorer_windows() -> dict[int, str]:
    """Ventanas visibles del Explorador: identificador → título."""
    found: dict[int, str] = {}

    def visit(hwnd: int, _: int) -> bool:
        name = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, name, 64)
        if name.value == "CabinetWClass" and _user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, title, 512)
            found[int(hwnd)] = title.value
        return True

    _user32.EnumWindows(_EnumProc(visit), 0)
    return found


def _to_front(hwnd: int) -> bool:
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
    foreground = _user32.GetForegroundWindow()
    theirs = _user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    mine = _kernel32.GetCurrentThreadId()
    attached = bool(theirs) and theirs != mine and _user32.AttachThreadInput(mine, theirs, True)
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(mine, theirs, False)
    return bool(_user32.GetForegroundWindow() == hwnd)


def bring_explorer_forward(before: dict[int, str], timeout_s: float = 3.0) -> bool:
    """Trae al frente la ventana del Explorador que apareció (o cambió de pestaña)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        now = explorer_windows()
        opened = [hwnd for hwnd in now if hwnd not in before]
        changed = [hwnd for hwnd, title in now.items() if before.get(hwnd) not in (None, title)]
        if opened or changed:
            return _to_front((opened or changed)[0])
        time.sleep(0.1)
    return False


# --- Elegir una carpeta o un archivo con el diálogo de Windows ------------------------------------
# El servicio corre en este equipo: puede abrir el diálogo nativo y devolver la ruta. Lleva como
# dueña la ventana que está al frente (el navegador) y se trae al frente al abrirse.

_ole32 = ctypes.WinDLL("ole32", use_last_error=True)
_comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
_BrowseCallback = ctypes.WINFUNCTYPE(
    ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM
)


class _BrowseInfo(ctypes.Structure):
    _fields_ = (
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", _BrowseCallback),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    )


class _OpenFileName(ctypes.Structure):
    _fields_ = (
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    )


_shell32.SHBrowseForFolderW.argtypes = (ctypes.POINTER(_BrowseInfo),)
_shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
_shell32.SHGetPathFromIDListW.argtypes = (ctypes.c_void_p, wintypes.LPWSTR)
_ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
_ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
_comdlg32.GetOpenFileNameW.argtypes = (ctypes.POINTER(_OpenFileName),)

_BIF_RETURNONLYFSDIRS = 0x1
_BIF_NEWDIALOGSTYLE = 0x40
_BFFM_INITIALIZED = 1
_BFFM_SETSELECTIONW = 0x467
_OFN_FILEMUSTEXIST = 0x1000
_OFN_PATHMUSTEXIST = 0x800
_OFN_NOCHANGEDIR = 0x8
_OFN_EXPLORER = 0x80000
_COINIT_APARTMENTTHREADED = 0x2
_user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


def pick_folder(title: str, initial: str | None = None) -> str | None:
    """La carpeta que el técnico elige, o None si canceló. Bloquea hasta que se cierre."""
    _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    start = ctypes.create_unicode_buffer(initial or "")

    def on_event(hwnd: int, message: int, _lparam: int, _data: int) -> int:
        if message == _BFFM_INITIALIZED:
            _to_front(hwnd)
            if start.value:
                _user32.SendMessageW(hwnd, _BFFM_SETSELECTIONW, 1, ctypes.addressof(start))
        return 0

    callback = _BrowseCallback(on_event)
    name = ctypes.create_unicode_buffer(260)
    info = _BrowseInfo(
        hwndOwner=_user32.GetForegroundWindow(),
        pszDisplayName=ctypes.cast(name, wintypes.LPWSTR),
        lpszTitle=title,
        ulFlags=_BIF_RETURNONLYFSDIRS | _BIF_NEWDIALOGSTYLE,
        lpfn=callback,
    )
    pidl = _shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return None
    path = ctypes.create_unicode_buffer(32768)
    ok = _shell32.SHGetPathFromIDListW(pidl, path)
    _ole32.CoTaskMemFree(pidl)
    return path.value if ok and path.value else None


def pick_file(title: str, patterns: str, initial: str | None = None) -> str | None:
    """El archivo que el técnico elige (`patterns`: «Controladores (*.inf)|*.inf»), o None."""
    _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    filter_text = "\0".join(patterns.split("|")) + "\0\0"
    buffer = ctypes.create_unicode_buffer(32768)
    owner = _user32.GetForegroundWindow()
    dialog = _OpenFileName(
        lStructSize=ctypes.sizeof(_OpenFileName),
        hwndOwner=owner,
        lpstrFilter=filter_text,
        nFilterIndex=1,
        lpstrFile=ctypes.cast(buffer, wintypes.LPWSTR),
        nMaxFile=len(buffer),
        lpstrInitialDir=initial,
        lpstrTitle=title,
        Flags=_OFN_FILEMUSTEXIST | _OFN_PATHMUSTEXIST | _OFN_NOCHANGEDIR | _OFN_EXPLORER,
    )
    if owner:
        _to_front(owner)  # el diálogo sale delante de su dueña
    if not _comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
        return None
    return buffer.value or None
