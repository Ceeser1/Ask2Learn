"""Detects whether it's a good moment to pop a quiz: not gaming, not away."""

import ctypes
from ctypes import wintypes

from appconfig import IDENTITY

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# SHQueryUserNotificationState results that mean "leave me alone"
QUNS_BUSY = 2                   # fullscreen app
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # exclusive-fullscreen game
QUNS_PRESENTATION_MODE = 4
QUNS_QUIET_TIME = 6
_BLOCKING_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE, QUNS_QUIET_TIME}

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
MONITOR_DEFAULTTONEAREST = 2
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def make_dpi_aware() -> None:
    """Without this, window/monitor sizes are scaled and fullscreen checks misfire."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _windows_says_busy() -> bool:
    state = ctypes.c_int(0)
    if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in _BLOCKING_STATES


def _foreground_is_fullscreen() -> bool:
    """Catches borderless-windowed games, which Windows doesn't always report as busy."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    if cls.value in _SHELL_CLASSES:
        return False

    # Normal maximized windows (browser, editor) keep their title bar style.
    if user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION == WS_CAPTION:
        return False

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    m = info.rcMonitor
    return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def is_busy() -> bool:
    """True while gaming / fullscreen / presenting."""
    return _windows_says_busy() or _foreground_is_fullscreen()


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def force_foreground(hwnd: int) -> bool:
    """Bring our window to the front even while another app (a fullscreen game) has the focus.

    Windows only lets the app that has the focus hand it over, so a background app has to borrow
    the foreground thread's input queue for a moment. If that's refused, a tapped Alt key counts as
    "the user just pressed something" and unlocks SetForegroundWindow."""
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    me = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True))
    try:
        user32.ShowWindow(hwnd, 9)              # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    if not ok:
        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        ok = bool(user32.SetForegroundWindow(hwnd))
    return ok


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

SHOW_EVENT = IDENTITY["show_event"].format(instance=IDENTITY["instance"])   # main.py sets the real one


def acquire_single_instance(name: str):
    """Returns a mutex handle, or None if another copy is already running."""
    handle = kernel32.CreateMutexW(None, False, name)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def create_show_event():
    """Event a second launch sets to ask the running copy to show its window."""
    return kernel32.CreateEventW(None, False, False, SHOW_EVENT)


def signal_show() -> bool:
    EVENT_MODIFY_STATE = 0x0002
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT)
    if not handle:
        return False
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    return True


def wait_for_event(handle, timeout_ms: int) -> bool:
    return kernel32.WaitForSingleObject(handle, timeout_ms) == 0
