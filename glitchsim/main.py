# -*- coding: utf-8 -*-
"""
花屏模拟器 GlitchSim —— 屏线故障悬浮层
======================================================================
一个**完全透明的 Windows 分层窗口（Layered Window）**：只在屏幕上画
"屏线（LVDS/eDP 排线）接触不良"的彩色竖条纹，底下的桌面原样透出来，
鼠标键盘照常使用，按 ESC 立刻恢复。

* 不需要底图、不截取屏幕、不写文件、不联网、不写注册表
* 窗口带 WS_EX_TRANSPARENT，鼠标点击直接穿透到下面的真实桌面
* 依赖：numpy（仅用于像素缓冲），标准库 ctypes 调 Win32

用法：
    python main.py                 # 默认强度 0.6，按 ESC 退出
    python main.py --intensity 0.9 --duration 10
    python main.py --preview preview   # 导出效果图（不建窗口）
    python main.py --selftest          # 自检 + 性能基准
"""

import argparse
import atexit
import configparser
import ctypes
import os
import random
import re
import struct
import sys
import time
import zlib
from ctypes import wintypes

import numpy as np

APP_NAME = "GlitchSim"

# ======================================================================
# Win32 常量
# ======================================================================
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

PM_REMOVE = 0x0001
WM_QUIT = 0x0012
WM_DESTROY = 0x0002
WM_USER = 0x0400
WM_TRAY = WM_USER + 1
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_COMMAND = 0x0111
WM_NULL = 0x0000
MF_STRING = 0x0000
TPM_LEFTALIGN, TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0000, 0x0002, 0x0100
IDM_EXIT, IDM_TOGGLE = 1001, 1002

NIM_ADD, NIM_DELETE, NIM_SETVERSION = 0, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_ESCAPE, VK_Q = 0x1B, 0x51
VK_CONTROL, VK_MENU, VK_SHIFT = 0x11, 0x12, 0x10
VK_LWIN, VK_RWIN = 0x5B, 0x5C
CSIDL_STARTUP = 0x0007

# ---- 可配置的退出热键：支持 ctrl / alt / shift / win 修饰，多个用逗号分隔 ----
VK_NAMES = {
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "enter": 0x0D, "return": 0x0D,
    "tab": 0x09, "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24,
    "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C,
    "scrolllock": 0x91, "pause": 0x13,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "minus": 0xBD, "-": 0xBD, "plus": 0xBB, "=": 0xBB, "lbracket": 0xDB, "[": 0xDB,
    "rbracket": 0xDD, "]": 0xDD, "semicolon": 0xBA, ";": 0xBA, "quote": 0xDE,
    "'": 0xDE, "comma": 0xBC, ",": 0xBC, "period": 0xBE, ".": 0xBE, "slash": 0xBF,
    "/": 0xBF, "backslash": 0xDC, "\\": 0xDC, "grave": 0xC0, "`": 0xC0,
}
for _i in range(1, 25):
    VK_NAMES["f%d" % _i] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_NAMES[_c] = 0x41 + ord(_c) - ord("a")
for _n in range(10):
    VK_NAMES[str(_n)] = 0x30 + _n


def parse_hotkeys(spec):
    """'esc, ctrl+alt+q, f8' -> [(vk, ctrl, alt, shift, win), ...]"""
    out = []
    for part in str(spec).split(","):
        part = part.strip().lower()
        if not part:
            continue
        mods = {"ctrl": False, "alt": False, "shift": False, "win": False}
        key = None
        for tok in part.split("+"):
            tok = tok.strip()
            if tok in ("ctrl", "control"):
                mods["ctrl"] = True
            elif tok in ("alt", "menu"):
                mods["alt"] = True
            elif tok == "shift":
                mods["shift"] = True
            elif tok in ("win", "super", "meta"):
                mods["win"] = True
            else:
                key = tok
        if key is None:
            continue
        vk = VK_NAMES.get(key)
        if vk is None:
            print("[warn] 无法识别的按键，已忽略：%s" % key)
            continue
        out.append((vk, mods["ctrl"], mods["alt"], mods["shift"], mods["win"]))
    return out


def hotkey_hit(vk, ctrl, alt, shift, win, hk):
    """未配置修饰键时宽容匹配（只认主键）；配置了则要求这些修饰键都按下。"""
    mvk, mctrl, malt, mshift, mwin = hk
    if vk != mvk:
        return False
    if mctrl and not ctrl:
        return False
    if malt and not alt:
        return False
    if mshift and not shift:
        return False
    if mwin and not win:
        return False
    return True

HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32
_gdi32 = ctypes.windll.gdi32

try:
    _user32.SetProcessDPIAware()
except Exception:
    pass

LPCWSTR = wintypes.LPCWSTR
HANDLE_T = ctypes.c_void_p


def _sig(fn, argtypes, restype):
    """显式声明签名，否则 64 位句柄/指针会被截断成 32 位 int。"""
    try:
        fn.argtypes = argtypes
        fn.restype = restype
    except Exception:
        pass


_sig(_user32.GetSystemMetrics, [ctypes.c_int], ctypes.c_int)
_sig(_kernel32.GetModuleHandleW, [LPCWSTR], wintypes.HMODULE)
_sig(_user32.DefWindowProcW,
     [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t)
_sig(_user32.LoadIconW, [wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HICON)
_sig(_user32.CreatePopupMenu, [], ctypes.c_void_p)
_sig(_user32.AppendMenuW,
     [ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, LPCWSTR], wintypes.BOOL)
_sig(_user32.TrackPopupMenu,
     [ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      wintypes.HWND, ctypes.c_void_p], wintypes.BOOL)
_sig(_user32.DestroyMenu, [ctypes.c_void_p], wintypes.BOOL)
_sig(_user32.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL)
_sig(_user32.PostMessageW,
     [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
_sig(_user32.PostQuitMessage, [ctypes.c_int], None)
_sig(_user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL)
_sig(_user32.GetAsyncKeyState, [ctypes.c_int], ctypes.c_short)
_sig(_user32.PeekMessageW,
     [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
      wintypes.UINT], wintypes.BOOL)
_sig(_user32.UnhookWindowsHookEx, [ctypes.c_void_p], wintypes.BOOL)
_sig(_shell32.Shell_NotifyIconW, [wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL)
_sig(_gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC)
_sig(_gdi32.DeleteDC, [wintypes.HDC], wintypes.BOOL)
_sig(_gdi32.SelectObject, [wintypes.HDC, ctypes.c_void_p], ctypes.c_void_p)
_sig(_gdi32.DeleteObject, [ctypes.c_void_p], wintypes.BOOL)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


_sig(_gdi32.CreateDIBSection,
     [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
      HANDLE_T, wintypes.DWORD], wintypes.HBITMAP)
_sig(_user32.UpdateLayeredWindow,
     [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
      ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
      wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD], wintypes.BOOL)


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uTimeout", wintypes.UINT),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HICON),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", LPCWSTR),
                ("lpszClassName", LPCWSTR), ("hIconSm", wintypes.HICON)]


_sig(_user32.RegisterClassExW, [ctypes.POINTER(WNDCLASSEXW)], wintypes.ATOM)
_sig(_user32.CreateWindowExW,
     [wintypes.DWORD, LPCWSTR, LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
      ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
      wintypes.LPVOID], wintypes.HWND)
_sig(_user32.SetWindowPos,
     [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      ctypes.c_int, wintypes.UINT], wintypes.BOOL)


# ======================================================================
# 屏线竖条纹
# ======================================================================
# 真实观感：位置固定（坏的就是那几根）、纯色、全高、边缘锐利、成簇出现；
# 偶发整片区域发白发绿（接触不良），偶发整屏闪一下。没有噪点、没有马赛克。

VLINE_PALETTE = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255),
    (255, 255, 0), (255, 255, 255), (0, 0, 0), (168, 168, 168),
    (255, 255, 255), (0, 0, 0),
]


class VLine(object):
    __slots__ = ("x", "w", "bgra", "blink")

    def __init__(self, x, w, bgra, blink):
        self.x = x
        self.w = w
        self.bgra = bgra
        self.blink = blink


def _premul(rgb, a):
    """UpdateLayeredWindow 要求预乘 alpha 的 BGRA。"""
    r, g, b = rgb
    k = a / 255.0
    return (int(b * k), int(g * k), int(r * k), int(a))


def build_vlines(rnd, sw, sh, p):
    """生成一次"坏掉的屏线"：1~2 个故障区 + 孤立细线 + 宽色带 + 半透明泛色区。"""
    lines = []
    thin = max(1, int(round(sw / 1080.0)))           # 1080p -> 1px；4K -> 2px
    for _ in range(rnd.randint(1, 3)):               # 故障区：密集同色细线
        cx = rnd.uniform(0.0, 0.98) * sw
        cw = rnd.uniform(0.06, 0.34) * sw * (0.5 + 0.5 * p)
        gap = rnd.uniform(1.5, 8.0) * (sw / 1920.0)
        main = rnd.choice(VLINE_PALETTE)
        x = cx
        while x < min(cx + cw, sw):
            col = main if rnd.random() < 0.72 else rnd.choice(VLINE_PALETTE)
            lines.append(VLine(int(x), rnd.randint(max(1, thin - 1), thin + 1),
                               _premul(col, 255), rnd.random() < 0.12))
            x += gap * rnd.uniform(0.6, 1.6)
    for _ in range(rnd.randint(2, 4 + int(14 * p))):  # 孤立细线
        lines.append(VLine(int(rnd.uniform(0, sw)), rnd.randint(1, max(2, thin + 1)),
                           _premul(rnd.choice(VLINE_PALETTE), 255),
                           rnd.random() < 0.35))
    for _ in range(rnd.randint(0, 1 + int(2 * p))):   # 宽色带
        lines.append(VLine(int(rnd.uniform(0, sw)),
                           rnd.randint(max(4, sw // 240), max(8, sw // 60)),
                           _premul(rnd.choice([(0, 0, 0), (255, 255, 255), (0, 255, 0),
                                               (255, 0, 255), (0, 0, 255)]), 255),
                           rnd.random() < 0.2))
    # 半透明泛色区（接触不良导致的一片发白 / 发绿）
    washes = []
    for _ in range(rnd.randint(0, 2)):
        x = int(rnd.uniform(0, sw))
        w = int(rnd.uniform(0.06, 0.30) * sw * (0.5 + 0.5 * p))
        washes.append((x, w, _premul(rnd.choice([(230, 255, 230), (255, 235, 235),
                                                 (235, 235, 255), (255, 255, 220),
                                                 (225, 225, 225)]), 46)))
    lines.sort(key=lambda L: L.x)
    cap = int(26 + 70 * p)
    if len(lines) > cap:
        lines = rnd.sample(lines, cap)
        lines.sort(key=lambda L: L.x)
    return lines, washes


def render_frame(buf, vstate, rnd, t):
    """把竖条纹画进 BGRA 缓冲（其余保持全透明）。"""
    buf[:] = 0
    lines, washes = vstate
    for x, w, bgra in washes:
        buf[:, x:x + w] = bgra
    for L in lines:
        if L.blink and rnd.random() < 0.08:          # 接触不良 -> 偶发消失
            continue
        buf[:, L.x:L.x + L.w] = L.bgra
    if rnd.random() < 0.015:                         # 极偶发整屏闪一下
        k = rnd.random()
        buf[:] = (26, 26, 26, 26) if k < 0.5 else (0, 0, 0, 40)


# ======================================================================
# 透明悬浮窗口
# ======================================================================

class Overlay(object):
    def __init__(self):
        self.hwnd = None
        self.hdc_mem = None
        self.bmp = None
        self.buf = None
        self.old_bmp = None
        self.hook = None
        self.tray = False
        self._hook_cb = None
        self._wnd_cb = None
        self.sw = _user32.GetSystemMetrics(0)
        self.sh = _user32.GetSystemMetrics(1)

    # ---------- 窗口 ----------
    def create(self):
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        def _wnd(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY and (lparam & 0xFFFF) in (WM_RBUTTONUP, 0x0204):
                self._popup()
                return 0
            if msg == WM_TRAY and (lparam & 0xFFFF) == WM_LBUTTONDBLCLK:
                self.on_cmd(IDM_TOGGLE)
                return 0
            if msg == WM_COMMAND:
                self.on_cmd(wparam & 0xFFFF)
                return 0
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_cb = WNDPROC(_wnd)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = ctypes.cast(self._wnd_cb, ctypes.c_void_p)
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "GlitchSimOverlay"
        wc.hCursor = _user32.LoadIconW(None, ctypes.c_void_p(32512))
        if not _user32.RegisterClassExW(ctypes.byref(wc)):
            raise RuntimeError("RegisterClassExW 失败")

        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        self.hwnd = _user32.CreateWindowExW(
            ex, "GlitchSimOverlay", "GlitchSim", WS_POPUP,
            0, 0, self.sw, self.sh, None, None, _kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            raise RuntimeError("CreateWindowExW 失败")

        self._make_dib()
        _user32.SetWindowPos(self.hwnd, wintypes.HWND(HWND_TOPMOST),
                             0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        return self

    def _make_dib(self):
        """创建 32bpp DIB section，并用 numpy 直接映射到它的像素内存。"""
        hdc = _user32.GetDC(0)
        self.hdc_mem = _gdi32.CreateCompatibleDC(hdc)
        _user32.ReleaseDC(0, hdc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(bmi)
        bmi.biWidth = self.sw
        bmi.biHeight = -self.sh                      # 负值 = 自上而下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        ppv = ctypes.c_void_p()
        self.bmp = _gdi32.CreateDIBSection(self.hdc_mem, ctypes.byref(bmi),
                                           DIB_RGB_COLORS, ctypes.byref(ppv), None, 0)
        if not self.bmp:
            raise RuntimeError("CreateDIBSection 失败")
        self.old_bmp = _gdi32.SelectObject(self.hdc_mem, self.bmp)
        arr_t = ctypes.c_uint8 * (self.sw * self.sh * 4)
        self.buf = np.ctypeslib.as_array(arr_t.from_address(ppv.value)).reshape(
            self.sh, self.sw, 4)

    def present(self):
        """把缓冲推到分层窗口上（每像素 alpha，非透明处悬浮在桌面之上）。"""
        pt = wintypes.POINT(0, 0)
        size = wintypes.SIZE(self.sw, self.sh)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        _user32.UpdateLayeredWindow(self.hwnd, None, None, ctypes.byref(size),
                                    self.hdc_mem, ctypes.byref(pt), 0,
                                    ctypes.byref(blend), ULW_ALPHA)

    # ---------- 键盘钩子：保证 ESC 永不丢失 ----------
    def install_hook(self, on_key):
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)

        def _proc(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                try:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    on_key(int(kb.vkCode))
                except Exception:
                    pass
            return _user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

        self._hook_cb = HOOKPROC(_proc)
        _sig(_user32.SetWindowsHookExW,
             [ctypes.c_int, HOOKPROC, wintypes.HMODULE, wintypes.DWORD], ctypes.c_void_p)
        _sig(_user32.CallNextHookEx,
             [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM],
             ctypes.c_ssize_t)
        self.hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_cb, _kernel32.GetModuleHandleW(None), 0)

    # ---------- 托盘 ----------
    def add_tray(self, tip="花屏模拟器", balloon=None):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = _user32.LoadIconW(None, ctypes.c_void_p(32512))
        nid.szTip = tip
        if balloon:
            nid.uFlags |= NIF_INFO
            nid.szInfo = balloon
            nid.szInfoTitle = "花屏模拟器"
            nid.dwInfoFlags = NIIF_INFO
            nid.uTimeout = 5000
        self.tray = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if self.tray:
            v = NOTIFYICONDATAW()
            ctypes.memmove(ctypes.byref(v), ctypes.byref(nid), ctypes.sizeof(nid))
            v.uVersion = 4
            _shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(v))
        return self.tray

    def _popup(self):
        hmenu = _user32.CreatePopupMenu()
        if not hmenu:
            return
        _user32.AppendMenuW(hmenu, MF_STRING, IDM_TOGGLE, "暂停 / 继续(&P)")
        _user32.AppendMenuW(hmenu, MF_STRING, IDM_EXIT, "退出并恢复(&X)")
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self.hwnd)
        cmd = _user32.TrackPopupMenu(hmenu, TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                     pt.x, pt.y, 0, self.hwnd, None)
        _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        _user32.DestroyMenu(hmenu)
        if cmd:
            self.on_cmd(cmd)

    on_cmd = lambda self, cmd: None                  # 由外部替换

    # ---------- 消息泵 ----------
    def pump(self):
        msg = wintypes.MSG()
        while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT:
                return False
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        return True

    def cleanup(self):
        try:
            if self.tray:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(nid)
                nid.hWnd = self.hwnd
                nid.uID = 1
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        try:
            if self.hook:
                _user32.UnhookWindowsHookEx(self.hook)
        except Exception:
            pass
        try:
            if self.hdc_mem and self.old_bmp:
                _gdi32.SelectObject(self.hdc_mem, self.old_bmp)
            if self.bmp:
                _gdi32.DeleteObject(self.bmp)
            if self.hdc_mem:
                _gdi32.DeleteDC(self.hdc_mem)
        except Exception:
            pass


def startup_dir():
    """用户级"启动"文件夹路径（不动注册表）。"""
    _sig(_shell32.SHGetSpecialFolderPathW,
         [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int, wintypes.BOOL], wintypes.BOOL)
    buf = ctypes.create_unicode_buffer(260)
    if _shell32.SHGetSpecialFolderPathW(0, buf, CSIDL_STARTUP, 0) and buf.value:
        return buf.value
    return os.path.join(os.environ.get("APPDATA", ""),
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def self_command():
    """返回启动本程序所需的命令行（打包后是 exe，源码运行时是 python main.py）。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))


def autostart_path():
    d = startup_dir()
    return os.path.join(d, "GlitchSim.vbs") if d else ""


def autostart_enabled():
    p = autostart_path()
    return bool(p) and os.path.exists(p)


def sync_autostart(desired, quiet=False):
    """把实际开机启动状态对齐到 desired，返回 (ok, 说明)；状态一致时什么都不做。"""
    cur = autostart_enabled()
    if cur == bool(desired):
        return True, "开机启动已为 %s" % ("开" if desired else "关")
    ok, msg = set_autostart(bool(desired))
    if not quiet:
        print("[autostart] " + msg)
    return ok, msg


def config_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__)),
        "config.ini")


def write_config_autostart(enable):
    """把 autostart 写回 config.ini（保留注释与其它内容，失败静默）。"""
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        hit = False
        for i, ln in enumerate(lines):
            if re.match(r"^\s*autostart\s*=", ln, re.I):
                lines[i] = "autostart = %s\n" % ("true" if enable else "false")
                hit = True
                break
        if not hit:
            lines.append("\nautostart = %s\n" % ("true" if enable else "false"))
        # 必须用 utf-8-sig（带 BOM）：否则中文注释在记事本等 ANSI 编辑器里会变成乱码
        with open(path, "w", encoding="utf-8-sig") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


def set_autostart(enable):
    """在"启动"文件夹放/删一个 VBS 启动器（wscript 执行，无黑窗）。"""
    d = startup_dir()
    if not d or not os.path.isdir(d):
        return False, "找不到启动文件夹：%s" % d
    path = os.path.join(d, "GlitchSim.vbs")
    if not enable:
        if os.path.exists(path):
            os.remove(path)
            return True, "已取消开机启动（删除 %s）" % path
        return True, "当前本来就没设开机启动"
    body = 'CreateObject("WScript.Shell").Run "%s", 0, False' % \
           self_command().replace('"', '""')
    for enc in ("mbcs", "utf-8-sig"):
        try:
            with open(path, "w", encoding=enc) as f:
                f.write(body + "\n")
            break
        except Exception:
            continue
    return True, "已设置开机启动 -> %s" % path


# ======================================================================
# 配置
# ======================================================================
DEFAULTS = {
    "intensity": 0.6,        # 0.1 ~ 1.0，竖线密度 / 条数
    "fps": 60,
    "duration": 0,           # 秒，0 = 直到按退出键
    "delay": 0.0,            # 启动后延迟 N 秒再出现（开机启动场景很有用）
    "exit_keys": "esc, ctrl+alt+q",   # 自定义退出键，多个用逗号分隔
    "hint": True,            # 托盘气泡提示退出键
    "autostart": False,      # 开机启动；程序每次启动会把它同步到"启动"文件夹
}


def load_config(args):
    cfg = dict(DEFAULTS)
    explicit = set()
    path = config_path()
    if os.path.exists(path):
        try:
            cp = configparser.ConfigParser()
            cp.read(path, encoding="utf-8-sig")      # -sig：兼容记事本存出的带 BOM 文件
            sec = cp["glitch"] if "glitch" in cp else cp[cp.default_section]
            for k in list(cfg):
                if k in sec:
                    v = sec[k].strip()
                    explicit.add(k)
                    if isinstance(cfg[k], bool):
                        cfg[k] = v.lower() in ("1", "true", "yes", "on", "开")
                    elif isinstance(cfg[k], int):
                        cfg[k] = int(float(v))
                    elif isinstance(cfg[k], float):
                        cfg[k] = float(v)
        except Exception as e:
            print("[warn] config.ini 读取失败：", e)
    for k in list(cfg):
        v = getattr(args, k, None)
        if v is not None:
            cfg[k] = v
    cfg["intensity"] = min(1.0, max(0.1, float(cfg["intensity"])))
    cfg["fps"] = int(cfg["fps"]) if int(cfg["fps"]) in (30, 60, 120) else 60
    cfg["duration"] = max(0.0, float(cfg["duration"]))
    cfg["delay"] = max(0.0, float(cfg["delay"]))
    cfg["_explicit"] = explicit          # 只有 ini 里显式写了的配置才做"同步"
    return cfg


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="花屏模拟器（屏线故障悬浮层）")
    ap.add_argument("--intensity", type=float, help="强度 0.1~1.0")
    ap.add_argument("--fps", type=int, choices=[30, 60, 120])
    ap.add_argument("--duration", type=float, help="N 秒后自动恢复，0=直到按退出键")
    ap.add_argument("--delay", type=float, help="启动后延迟 N 秒再出现")
    ap.add_argument("--exit-keys", dest="exit_keys",
                    help='自定义退出键，如 "f8" 或 "ctrl+shift+k, esc"')
    ap.add_argument("--no-hint", dest="hint", action="store_false", help="不弹托盘提示")
    ap.add_argument("--autostart", choices=["on", "off"], help="设置 / 取消开机启动")
    ap.add_argument("--preview", metavar="DIR", help="导出效果图 PNG（不建窗口）")
    ap.add_argument("--selftest", action="store_true", help="自检 + 性能基准")
    return ap.parse_args(argv)


# ======================================================================
# 预览 / 自检（调试用，不建窗口）
# ======================================================================

def save_png(path, rgb):
    """最小 PNG 编码器（无第三方依赖）。"""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[i].tobytes() for i in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def fake_bg(w, h):
    """预览用的假桌面背景（仅为了看清楚竖线效果）。"""
    bg = np.zeros((h, w, 3), np.float32)
    bg[:, :] = (30, 90, 160)
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    bg *= (0.55 + 0.45 * (1 - ys))
    for (x0, y0, x1, y1) in [(0.10, 0.10, 0.62, 0.72), (0.34, 0.32, 0.88, 0.90)]:
        X0, Y0 = int(x0 * w), int(y0 * h)
        X1, Y1 = int(x1 * w), int(y1 * h)
        bg[Y0:Y1, X0:X1] = (242, 242, 242)
        bg[Y0:min(Y1, Y0 + int(0.035 * h)), X0:X1] = (0, 90, 158)
    bg[int(0.93 * h):, :] = (28, 28, 30)
    return bg


def run_preview(outdir, sw=1280, sh=720):
    os.makedirs(outdir, exist_ok=True)
    buf = np.zeros((sh, sw, 4), np.uint8)
    bg = fake_bg(sw, sh)
    for p in (0.3, 0.6, 1.0):
        rnd = random.Random(int(p * 100))
        render_frame(buf, build_vlines(rnd, sw, sh, p), rnd, 1.0)
        a = (buf[:, :, 3:4].astype(np.float32) / 255.0)
        fg = buf[:, :, 2::-1].astype(np.float32)     # BGRA -> RGB
        out = (bg * (1 - a) + fg * a).clip(0, 255).astype(np.uint8)
        path = os.path.join(outdir, "vlines_%.1f.png" % p)
        save_png(path, out)
        print("  强度 %.1f -> %s" % (p, path))


def run_selftest(sw=1920, sh=1080):
    print("自检：分辨率 %dx%d" % (sw, sh))
    buf = np.zeros((sh, sw, 4), np.uint8)
    rnd = random.Random(0)
    t = time.perf_counter()
    for i in range(60):
        render_frame(buf, build_vlines(rnd, sw, sh, 0.6), rnd, i * 0.016)
    dt = (time.perf_counter() - t) / 60 * 1000
    print("  渲染(含重建) %6.2f ms/帧" % dt)
    vs = build_vlines(rnd, sw, sh, 0.6)
    t = time.perf_counter()
    for i in range(60):
        render_frame(buf, vs, rnd, i * 0.016)
    dt = (time.perf_counter() - t) / 60 * 1000
    print("  渲染(稳态)   %6.2f ms/帧  ≈ %.0f FPS（不含 UpdateLayeredWindow）"
          % (dt, 1000.0 / max(0.01, dt)))

    # 量化校验：竖线是否全高贯穿、是否有不透明像素、覆盖率是否合理
    lines, washes = vs
    render_frame(buf, vs, random.Random(1), 1.0)
    alpha = buf[:, :, 3]
    cols = np.where((alpha > 0).any(axis=0))[0]
    opaque = np.where(alpha == 255)[0]
    cov = 100.0 * len(cols) / sw
    print("  竖线 %d 条，泛色区 %d 处" % (len(lines), len(washes)))
    print("  可见列 %d / %d（覆盖率 %.1f%%），最高不透明度 %d"
          % (len(cols), sw, cov, int(alpha.max())))
    ok = len(cols) > 0 and alpha.max() > 0 and cov < 60
    # 竖线必须"全高贯穿"：取一根不透明线，检查它是否从上到下都在
    streak = 0
    for x in range(sw):
        if (alpha[:, x] > 0).all():
            streak += 1
    print("  全高贯穿的列 %d 条" % streak)
    ok = ok and streak > 0
    print("自检通过" if ok else "自检【失败】")
    return 0 if ok else 1


# ======================================================================
# 主程序
# ======================================================================

def main(argv=None):
    args = parse_args(argv)
    if args.autostart:
        ok, msg = set_autostart(args.autostart == "on")
        if ok:
            write_config_autostart(args.autostart == "on")   # 保持 config.ini 与实际一致
        print(msg)
        return 0 if ok else 1
    if args.preview:
        run_preview(args.preview)
        return 0
    if args.selftest:
        return run_selftest()
    if sys.platform != "win32":
        print("仅支持 Windows")
        return 1

    cfg = load_config(args)
    # 开机启动：以 config.ini 为准，程序每次启动自动对齐（ini 里没写就不动）
    if "autostart" in cfg.get("_explicit", set()):
        try:
            sync_autostart(cfg["autostart"], quiet=True)
        except Exception as e:
            print("[warn] 同步开机启动失败：", e)

    hotkeys = parse_hotkeys(cfg["exit_keys"])
    hotkeys.append((VK_Q, True, True, False, False))     # Ctrl+Alt+Q：不可关闭的兜底
    if not hotkeys:
        print("[warn] 未配置任何退出键，已回退到 ESC")
        hotkeys.append((VK_ESCAPE, False, False, False, False))

    state = {"running": True, "paused": False,
             "intensity": cfg["intensity"], "dirty": False}
    ov = Overlay()

    def on_key(vk):
        ctrl = bool(_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt = bool(_user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        shift = bool(_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        win = bool(_user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or \
            bool(_user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
        for hk in hotkeys:
            if hotkey_hit(vk, ctrl, alt, shift, win, hk):
                state["running"] = False
                return
        if vk in (0xBB, 0x6B):                       # +
            state["intensity"] = min(1.0, round(state["intensity"] + 0.1, 2))
            state["dirty"] = True
        elif vk in (0xBD, 0x6D):                     # -
            state["intensity"] = max(0.1, round(state["intensity"] - 0.1, 2))
            state["dirty"] = True

    def on_cmd(cmd):
        if cmd == IDM_EXIT:
            state["running"] = False
        elif cmd == IDM_TOGGLE:
            state["paused"] = not state["paused"]
            state["dirty"] = True

    try:
        ov.create()
    except Exception as e:
        print("创建悬浮层失败：", e)
        return 1

    ov.on_cmd = on_cmd
    ov.install_hook(on_key)
    tip = "退出键：" + str(cfg["exit_keys"]).strip().rstrip(",")
    ov.add_tray(balloon=(tip + "（或 Ctrl+Alt+Q）") if cfg["hint"] else None)
    atexit.register(ov.cleanup)

    rnd = random.Random()
    vstate = build_vlines(rnd, ov.sw, ov.sh, state["intensity"])
    vkey = (ov.sw, ov.sh, round(state["intensity"], 1))

    # 提高定时器精度，保证 60fps 稳定
    try:
        winmm = ctypes.windll.winmm
        winmm.timeBeginPeriod(1)
        _end_period = lambda: winmm.timeEndPeriod(1)
    except Exception:
        _end_period = lambda: None

    interval = 1.0 / cfg["fps"]
    start = time.perf_counter()
    last = 0.0
    frames = 0
    try:
        while state["running"]:
            if not ov.pump():
                break
            now = time.perf_counter() - start
            if cfg["duration"] and now > cfg["delay"] + cfg["duration"]:
                break
            if now < cfg["delay"]:                   # 延迟期间什么都不画（全透明）
                time.sleep(min(0.05, max(0.001, cfg["delay"] - now)))
                continue
            if now - last < interval:
                time.sleep(max(0.0005, (interval - (now - last)) * 0.5))
                continue
            last = now

            key = (ov.sw, ov.sh, round(state["intensity"], 1))
            if key != vkey or state.get("dirty"):
                vstate = build_vlines(rnd, ov.sw, ov.sh, state["intensity"])
                vkey = key
                state["dirty"] = False

            if state["paused"]:
                ov.buf[:] = 0
            else:
                render_frame(ov.buf, vstate, rnd, now)
            ov.present()
            frames += 1
    finally:
        ov.buf[:] = 0
        ov.present()
        ov.cleanup()
        _end_period()

    if frames:
        print("已恢复，平均 FPS：%.1f" % (frames / max(0.001, time.perf_counter() - start)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
