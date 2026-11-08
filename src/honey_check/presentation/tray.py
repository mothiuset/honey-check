"""Icono en la bandeja de Windows con la API nativa (Shell_NotifyIcon), sin dependencias.

Corre en el hilo principal con su propio bucle de mensajes. Si la bandeja no está disponible, la
aplicación sigue funcionando desde el navegador.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from importlib import resources

log = logging.getLogger(__name__)

_TITLE = "Honey Check"

_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_COMMAND = 0x0111
_WM_NULL = 0x0000
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_WM_CONTEXTMENU = 0x007B
_WM_APP = 0x8000
_WM_TRAY = _WM_APP + 1

_NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x1, 0x2, 0x4, 0x10
_NIIF_INFO = 0x1

_MF_STRING, _MF_SEPARATOR, _MF_BYPOSITION = 0x0, 0x800, 0x400
_TPM_RIGHTBUTTON, _TPM_RETURNCMD = 0x2, 0x100
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x10
_IDI_APPLICATION = 32512
_SM_CXSMICON = 49
_ICON_SIZE_FALLBACK = 16

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WindowClass(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    )


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


class _NotifyIconData(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _Guid),
        ("hBalloonIcon", wintypes.HICON),
    )


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_user32.RegisterClassExW.argtypes = (ctypes.POINTER(_WindowClass),)
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
_user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DefWindowProcW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.DefWindowProcW.restype = _LRESULT
_user32.DestroyWindow.argtypes = (wintypes.HWND,)
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostQuitMessage.argtypes = (ctypes.c_int,)
_user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.DispatchMessageW.restype = _LRESULT
_user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
_user32.RegisterWindowMessageW.restype = wintypes.UINT
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
_user32.SetMenuDefaultItem.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.UINT)
_user32.DestroyMenu.argtypes = (wintypes.HMENU,)
_user32.GetMenuItemCount.argtypes = (wintypes.HMENU,)
_user32.GetMenuStringW.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    wintypes.LPWSTR,
    ctypes.c_int,
    wintypes.UINT,
)
_user32.GetMenuDefaultItem.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.UINT)
_user32.GetMenuDefaultItem.restype = wintypes.UINT
_user32.TrackPopupMenu.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
)
_user32.TrackPopupMenu.restype = ctypes.c_int
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
_user32.LoadImageW.argtypes = (
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPVOID)
_user32.LoadIconW.restype = wintypes.HICON
_user32.DestroyIcon.argtypes = (wintypes.HICON,)
_user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
_shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(_NotifyIconData))
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL


@dataclass
class TrayActions:
    open_ui: Callable[[], None]
    start_scan: Callable[[], None]
    open_folder: Callable[[], None]
    status_text: Callable[[], str]
    exit_app: Callable[[], None]


def _load_icon() -> tuple[int, bool]:
    """Icono empaquetado; si no carga, el genérico de Windows. Devuelve (icono, es_propio)."""
    size = _user32.GetSystemMetrics(_SM_CXSMICON) or _ICON_SIZE_FALLBACK
    resource = resources.files("honey_check.presentation.web").joinpath("icon.ico")
    with resources.as_file(resource) as path:
        handle = _user32.LoadImageW(None, str(path), _IMAGE_ICON, size, size, _LR_LOADFROMFILE)
    if handle:
        return int(handle), True
    log.info("No se pudo cargar el icono propio de la bandeja")
    return int(_user32.LoadIconW(None, ctypes.c_void_p(_IDI_APPLICATION))), False


class TrayIcon:
    def __init__(self, actions: TrayActions) -> None:
        self._actions = actions
        self._items: list[tuple[str, Callable[[], None]] | None] = [
            ("Abrir Honey Check", self._actions.open_ui),
            ("Analizar equipo", self._actions.start_scan),
            ("Abrir la carpeta de inventarios", self._actions.open_folder),
            ("Estado del servicio", self._show_status),
            None,
            ("Salir de Honey Check", self._actions.exit_app),
        ]
        self._hwnd: int | None = None
        self._icon: int | None = None
        self._owns_icon = False
        self._added = False
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._taskbar_created = 0
        # Debe vivir mientras exista la ventana: Windows conserva el puntero a esta función.
        self._wndproc = _WNDPROC(self._window_proc)
        self._class_name = f"HoneyCheckTray{id(self):x}"

    # --- Bucle de mensajes -----------------------------------------------------------------------

    def run(self) -> bool:
        """Bloquea hasta `stop()`. Devuelve False si no pudo mostrarse el icono."""
        instance = _kernel32.GetModuleHandleW(None)
        window_class = _WindowClass(
            cbSize=ctypes.sizeof(_WindowClass),
            lpfnWndProc=self._wndproc,
            hInstance=instance,
            lpszClassName=self._class_name,
        )
        if not _user32.RegisterClassExW(ctypes.byref(window_class)):
            log.warning("Bandeja: no se pudo registrar la clase de ventana")
            self._ready.set()
            return False
        try:
            hwnd = _user32.CreateWindowExW(
                0, self._class_name, _TITLE, 0, 0, 0, 0, 0, None, None, instance, None
            )
            if not hwnd:
                log.warning("Bandeja: no se pudo crear la ventana")
                self._ready.set()
                return False
            self._hwnd = hwnd
            self._taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")
            self._icon, self._owns_icon = _load_icon()
            if not self._add_icon():
                log.warning("Bandeja: Windows no aceptó el icono")
                _user32.DestroyWindow(hwnd)
                self._hwnd = None
                self._ready.set()
                return False
            self._ready.set()
            # Una salida pedida antes de que el bucle existiera no debe dejarlo bloqueado.
            if self._stop_requested.is_set():
                _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            self._message_loop()
            return True
        finally:
            if self._icon and self._owns_icon:
                _user32.DestroyIcon(self._icon)
            self._icon = None
            _user32.UnregisterClassW(self._class_name, instance)

    @staticmethod
    def _message_loop() -> None:
        message = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(message))
            _user32.DispatchMessageW(ctypes.byref(message))

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == _WM_TRAY:
            event = lparam & 0xFFFF
            if event in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                self._show_menu(hwnd)
            elif event == _WM_LBUTTONDBLCLK:
                self._invoke(0)
            return 0
        if message == _WM_COMMAND:
            self._invoke((wparam & 0xFFFF) - 1)
            return 0
        if message == _WM_CLOSE:
            self._remove_icon()
            _user32.DestroyWindow(hwnd)
            return 0
        if message == _WM_DESTROY:
            self._hwnd = None
            _user32.PostQuitMessage(0)
            return 0
        if self._taskbar_created and message == self._taskbar_created:
            # El Explorador se reinició: el icono anterior ya no existe.
            self._added = False
            self._add_icon()
            return 0
        return int(_user32.DefWindowProcW(hwnd, message, wparam, lparam))

    # --- Icono -----------------------------------------------------------------------------------

    def _notify_data(self, flags: int) -> _NotifyIconData:
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        return data

    def _add_icon(self) -> bool:
        data = self._notify_data(_NIF_MESSAGE | _NIF_ICON | _NIF_TIP)
        data.uCallbackMessage = _WM_TRAY
        data.hIcon = self._icon
        data.szTip = _TITLE
        self._added = bool(_shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)))
        return self._added

    def _remove_icon(self) -> None:
        if self._added:
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._notify_data(0)))
            self._added = False

    def notify(self, message: str) -> None:
        """Una notificación nunca es crítica: si no puede mostrarse, solo se registra."""
        if self._hwnd is None or not self._added:
            return
        data = self._notify_data(_NIF_INFO)
        data.szInfo = message[:255]
        data.szInfoTitle = _TITLE
        data.dwInfoFlags = _NIIF_INFO
        if not _shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(data)):
            log.info("Notificación no mostrada")

    # --- Menú ------------------------------------------------------------------------------------

    def _build_menu(self) -> int:
        menu = _user32.CreatePopupMenu()
        for index, item in enumerate(self._items):
            if item is None:
                _user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
            else:
                _user32.AppendMenuW(menu, _MF_STRING, index + 1, item[0])
        _user32.SetMenuDefaultItem(menu, 1, 0)
        return int(menu)

    def _show_menu(self, hwnd: int) -> None:
        menu = self._build_menu()
        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        # Sin esto el menú no se cierra al hacer clic fuera (comportamiento documentado).
        _user32.SetForegroundWindow(hwnd)
        command = _user32.TrackPopupMenu(
            menu, _TPM_RIGHTBUTTON | _TPM_RETURNCMD, point.x, point.y, 0, hwnd, None
        )
        _user32.PostMessageW(hwnd, _WM_NULL, 0, 0)
        _user32.DestroyMenu(menu)
        if command:
            self._invoke(command - 1)

    def _invoke(self, index: int) -> None:
        """Las acciones van en su propio hilo: el bucle de mensajes nunca se bloquea."""
        if not 0 <= index < len(self._items):
            return
        item = self._items[index]
        if item is None:
            return
        action = item[1]

        def run() -> None:
            try:
                action()
            except Exception:  # noqa: BLE001 - una opción no debe cerrar la bandeja
                log.exception("Fallo en una opción de la bandeja")
                self.notify("No se pudo completar la acción. Consulte los logs.")

        threading.Thread(target=run, name="tray-action", daemon=True).start()

    def _show_status(self) -> None:
        self.notify(self._actions.status_text())

    # --- Control externo -------------------------------------------------------------------------

    def wait_ready(self, timeout_s: float) -> bool:
        return self._ready.wait(timeout_s)

    @property
    def is_visible(self) -> bool:
        return self._added

    def stop(self) -> None:
        self._stop_requested.set()
        hwnd = self._hwnd
        if hwnd is not None:
            _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)

    def press(self, label: str) -> None:
        """Envía a la ventana el mismo mensaje que produce elegir la opción en el menú."""
        index = next(
            i for i, item in enumerate(self._items) if item is not None and item[0] == label
        )
        _user32.PostMessageW(self._hwnd, _WM_COMMAND, index + 1, 0)

    def menu_snapshot(self) -> tuple[list[str], str]:
        """Etiquetas y opción predeterminada, leídas del menú real creado en Windows."""
        menu = self._build_menu()
        try:
            labels: list[str] = []
            for position in range(_user32.GetMenuItemCount(menu)):
                buffer = ctypes.create_unicode_buffer(128)
                if _user32.GetMenuStringW(menu, position, buffer, 128, _MF_BYPOSITION):
                    labels.append(buffer.value)
            default_position = _user32.GetMenuDefaultItem(menu, 1, 0)
            buffer = ctypes.create_unicode_buffer(128)
            _user32.GetMenuStringW(menu, default_position, buffer, 128, _MF_BYPOSITION)
            return labels, buffer.value
        finally:
            _user32.DestroyMenu(menu)
