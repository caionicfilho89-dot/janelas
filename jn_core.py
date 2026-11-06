"""Janelas - lógica: enumeração de janelas (ctypes/user32), geometria de presets/monitores,
casamento de layouts e registro de alterações. Só Windows para as chamadas reais; a
geometria e o casamento são puros (testáveis com dados falsos)."""
import ctypes
import json
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

try:
    import psutil
except Exception:  # psutil é opcional
    psutil = None

IS_WIN = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2
SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
DWMWA_CLOAKED = 14
MONITOR_DEFAULTTONEAREST = 2

PRESETS = [
    ("1280×720", "size:1280x720"),
    ("1920×1080", "size:1920x1080"),
    ("Metade esquerda", "left"),
    ("Metade direita", "right"),
    ("Quadrante ↖", "tl"),
    ("Quadrante ↗", "tr"),
    ("Quadrante ↙", "bl"),
    ("Quadrante ↘", "br"),
]


def layouts_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Janelas", "layouts.json")


# ------------------------------------------------------------------ dados
@dataclass
class WinInfo:
    hwnd: int
    title: str
    pid: int = 0
    proc: str = ""
    rect: tuple = (0, 0, 0, 0)  # l, t, r, b
    state: str = "normal"  # normal | max | min
    topmost: bool = False
    alpha: int = 255


@dataclass
class Monitor:
    handle: int
    rect: tuple  # tela inteira
    work: tuple  # área útil (sem barra de tarefas)
    primary: bool = False


# ------------------------------------------------------------------ geometria pura
def rect_w(r):
    return r[2] - r[0]


def rect_h(r):
    return r[3] - r[1]


def preset_rect(preset, work, current=None):
    """Retângulo (l,t,r,b) do preset dentro da área útil `work`. Tamanhos fixos ficam
    centralizados e são limitados à área útil."""
    l, t, r, b = work
    w, h = r - l, b - t
    hw, hh = w // 2, h // 2
    if preset == "left":
        return (l, t, l + hw, b)
    if preset == "right":
        return (l + hw, t, r, b)
    if preset == "tl":
        return (l, t, l + hw, t + hh)
    if preset == "tr":
        return (l + hw, t, r, t + hh)
    if preset == "bl":
        return (l, t + hh, l + hw, b)
    if preset == "br":
        return (l + hw, t + hh, r, b)
    if preset.startswith("size:"):
        sw, sh = (int(x) for x in preset[5:].split("x"))
        sw, sh = min(sw, w), min(sh, h)
        return center_rect((0, 0, sw, sh), work)
    raise ValueError("preset desconhecido: %s" % preset)


def center_rect(rect, work):
    w, h = rect_w(rect), rect_h(rect)
    w, h = min(w, rect_w(work)), min(h, rect_h(work))
    x = work[0] + (rect_w(work) - w) // 2
    y = work[1] + (rect_h(work) - h) // 2
    return (x, y, x + w, y + h)


def move_to_monitor(rect, src_work, dst_work):
    """Leva o retângulo pra outra área útil mantendo a posição relativa e encolhendo se
    não couber (escala proporcional à diferença de tamanho das áreas)."""
    sw, sh = max(rect_w(src_work), 1), max(rect_h(src_work), 1)
    dw, dh = rect_w(dst_work), rect_h(dst_work)
    w = min(rect_w(rect), dw)
    h = min(rect_h(rect), dh)
    rx = (rect[0] - src_work[0]) / sw
    ry = (rect[1] - src_work[1]) / sh
    x = dst_work[0] + int(rx * dw)
    y = dst_work[1] + int(ry * dh)
    x = max(dst_work[0], min(x, dst_work[2] - w))
    y = max(dst_work[1], min(y, dst_work[3] - h))
    return (x, y, x + w, y + h)


def monitor_index_for_rect(rect, monitors):
    """Índice do monitor que mais cobre o retângulo (0 se nenhum)."""
    best, best_area = 0, -1
    for i, m in enumerate(monitors):
        a = _overlap(rect, m.rect)
        if a > best_area:
            best, best_area = i, a
    return best


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def next_monitor_index(cur, count):
    return (cur + 1) % count if count else 0


def clamp_to_any(rect, monitors):
    """Se o retângulo ficou fora de todos os monitores (monitor desconectado), traz pro primeiro."""
    if not monitors:
        return rect
    if any(_overlap(rect, m.rect) > 0 for m in monitors):
        return rect
    return move_to_monitor(rect, rect, monitors[0].work)


# ------------------------------------------------------------------ layouts
def _app_part(title):
    """Parte estável do título (a última depois de ' - ' ou ' — '), ex.: 'Bloco de Notas'."""
    for sep in (" - ", " — ", " – "):
        if sep in title:
            return title.rsplit(sep, 1)[1].strip().lower()
    return title.strip().lower()


def snapshot_entry(w):
    return {"proc": w.proc, "title": w.title, "rect": list(w.rect), "state": w.state}


def match_score(entry, w):
    """3 = mesmo processo e título igual; 2 = mesma parte final do título (ou um contém o
    outro); 1 = só o processo; 0 = não casa. Sem processo (psutil ausente) casa só por título."""
    ep, wp = (entry.get("proc") or "").lower(), (w.proc or "").lower()
    if ep and wp and ep != wp:
        return 0
    et, wt = entry.get("title", ""), w.title
    if et == wt:
        return 3
    if et and wt and (_app_part(et) == _app_part(wt) or et.lower() in wt.lower()
                      or wt.lower() in et.lower()):
        return 2
    if ep and wp:
        return 1
    return 0


def match_layout(entries, windows):
    """Casa cada entrada com no máximo uma janela (e vice-versa), do melhor escore pro pior.
    Retorna lista [(entrada, janela|None)] na ordem das entradas."""
    pairs = []
    for i, e in enumerate(entries):
        for j, w in enumerate(windows):
            s = match_score(e, w)
            if s:
                pairs.append((-s, i, j))
    pairs.sort()
    used_e, used_w, result = set(), set(), {}
    for _, i, j in pairs:
        if i in used_e or j in used_w:
            continue
        used_e.add(i)
        used_w.add(j)
        result[i] = windows[j]
    return [(e, result.get(i)) for i, e in enumerate(entries)]


def load_layouts(path=None):
    path = path or layouts_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_layouts(data, path=None):
    path = path or layouts_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ------------------------------------------------------------------ Win32
if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    HWND = wintypes.HWND
    LONG_PTR = ctypes.c_ssize_t

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT)]

    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
    MONENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [HWND]
    user32.IsWindow.argtypes = [HWND]
    user32.IsIconic.argtypes = [HWND]
    user32.IsZoomed.argtypes = [HWND]
    user32.GetWindowTextLengthW.argtypes = [HWND]
    user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowPlacement.argtypes = [HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.MoveWindow.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.BOOL]
    user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, LONG_PTR]
    user32.SetWindowLongPtrW.restype = LONG_PTR
    user32.SetLayeredWindowAttributes.argtypes = [HWND, wintypes.COLORREF, ctypes.c_ubyte,
                                                  wintypes.DWORD]
    user32.GetLayeredWindowAttributes.argtypes = [HWND, ctypes.POINTER(wintypes.COLORREF),
                                                  ctypes.POINTER(ctypes.c_ubyte),
                                                  ctypes.POINTER(wintypes.DWORD)]
    user32.MonitorFromWindow.argtypes = [HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONENUMPROC,
                                           wintypes.LPARAM]
    user32.SetForegroundWindow.argtypes = [HWND]
    dwmapi.DwmGetWindowAttribute.argtypes = [HWND, wintypes.DWORD, ctypes.c_void_p,
                                             wintypes.DWORD]


def set_dpi_aware():
    """Per-monitor v2 (com fallbacks). Chamar antes de criar a QApplication."""
    if not IS_WIN:
        return False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        return bool(user32.SetProcessDPIAware())
    except Exception:
        return False


def _proc_name(pid):
    if psutil is None or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _rect_of(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def _normal_rect(hwnd):
    """Posição 'restaurada' (útil quando a janela está maximizada/minimizada)."""
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
    r = wp.rcNormalPosition
    return (r.left, r.top, r.right, r.bottom)


def is_cloaked(hwnd):
    v = ctypes.c_int(0)
    try:
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4)
    except Exception:
        return False
    return v.value != 0


def get_ex_style(hwnd):
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def get_alpha(hwnd):
    """Opacidade atual 0-255 (255 se a janela não é layered)."""
    if not (get_ex_style(hwnd) & WS_EX_LAYERED):
        return 255
    key, a, fl = wintypes.COLORREF(), ctypes.c_ubyte(), wintypes.DWORD()
    if user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(a),
                                         ctypes.byref(fl)) and (fl.value & LWA_ALPHA):
        return a.value
    return 255


def window_info(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if user32.IsIconic(hwnd):
        state, rect = "min", _normal_rect(hwnd)
    elif user32.IsZoomed(hwnd):
        state, rect = "max", _normal_rect(hwnd)
    else:
        state, rect = "normal", _rect_of(hwnd)
    return WinInfo(hwnd=int(hwnd), title=buf.value, pid=pid.value, proc=_proc_name(pid.value),
                   rect=rect, state=state, topmost=bool(get_ex_style(hwnd) & WS_EX_TOPMOST),
                   alpha=get_alpha(hwnd))


def enum_windows(exclude_pids=()):
    """Janelas de topo visíveis, com título, que não são tool windows nem 'cloaked'
    (apps UWP em segundo plano). Ignora os PIDs em `exclude_pids`."""
    if not IS_WIN:
        return []
    out = []
    own = set(exclude_pids)

    def cb(hwnd, _lp):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            ex = get_ex_style(hwnd)
            if ex & WS_EX_TOOLWINDOW or is_cloaked(hwnd):
                return True
            info = window_info(hwnd)
            if info.pid in own or not info.title.strip():
                return True
            if info.title in ("Program Manager", "Settings") and not info.proc:
                return True
            out.append(info)
        except Exception:
            pass
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return out


def list_monitors():
    if not IS_WIN:
        return []
    mons = []

    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            m, w = mi.rcMonitor, mi.rcWork
            mons.append(Monitor(int(hmon or 0), (m.left, m.top, m.right, m.bottom),
                                (w.left, w.top, w.right, w.bottom), bool(mi.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, MONENUMPROC(cb), 0)
    mons.sort(key=lambda m: (not m.primary, m.rect[0], m.rect[1]))
    return mons


def monitor_of_window(hwnd):
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    m, w = mi.rcMonitor, mi.rcWork
    return Monitor(int(hmon or 0), (m.left, m.top, m.right, m.bottom),
                   (w.left, w.top, w.right, w.bottom), bool(mi.dwFlags & 1))


def window_exists(hwnd):
    return bool(IS_WIN and user32.IsWindow(hwnd))


# ------------------------------------------------------------------ ações
def set_topmost_raw(hwnd, on):
    return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def set_alpha_raw(hwnd, alpha):
    """alpha 0-255; 255 mantém layered (use clear_layered pra tirar)."""
    ex = get_ex_style(hwnd)
    if not ex & WS_EX_LAYERED:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
    return bool(user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, int(alpha))),
                                                  LWA_ALPHA))


def clear_layered(hwnd):
    ex = get_ex_style(hwnd)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)


def percent_to_alpha(pct):
    return round(max(20, min(100, pct)) * 255 / 100)


def alpha_to_percent(alpha):
    return round(alpha * 100 / 255)


def show(hwnd, cmd):
    user32.ShowWindow(hwnd, cmd)


def place(hwnd, rect, restore_first=True):
    """Move/redimensiona. Se estiver maximizada/minimizada, restaura antes."""
    if restore_first and (user32.IsZoomed(hwnd) or user32.IsIconic(hwnd)):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.MoveWindow(hwnd, rect[0], rect[1], rect_w(rect), rect_h(rect), True)


def bring_front(hwnd):
    user32.SetForegroundWindow(hwnd)


class Manager:
    """Aplica ações e guarda o registro do que ESTE app mudou (topmost/transparência),
    pra poder desfazer tudo depois."""

    def __init__(self):
        # hwnd -> {"topmost": bool original, "layered": bool original, "alpha": int original}
        self.registry = {}

    def _remember(self, hwnd):
        if hwnd not in self.registry:
            ex = get_ex_style(hwnd)
            self.registry[hwnd] = {"topmost": bool(ex & WS_EX_TOPMOST),
                                   "layered": bool(ex & WS_EX_LAYERED),
                                   "alpha": get_alpha(hwnd), "touched_top": False,
                                   "touched_alpha": False}
        return self.registry[hwnd]

    def set_topmost(self, hwnd, on):
        rec = self._remember(hwnd)
        rec["touched_top"] = True
        return set_topmost_raw(hwnd, on)

    def set_opacity(self, hwnd, pct):
        rec = self._remember(hwnd)
        rec["touched_alpha"] = True
        if pct >= 100 and not rec["layered"]:
            clear_layered(hwnd)
            return True
        return set_alpha_raw(hwnd, percent_to_alpha(pct))

    def changes(self):
        return {h: r for h, r in self.registry.items()
                if (r["touched_top"] or r["touched_alpha"]) and window_exists(h)}

    def restore_all(self):
        """Desfaz o que foi mudado. Retorna quantas janelas foram restauradas."""
        n = 0
        for hwnd, r in list(self.registry.items()):
            if window_exists(hwnd):
                if r["touched_top"]:
                    set_topmost_raw(hwnd, r["topmost"])
                if r["touched_alpha"]:
                    if r["layered"]:
                        set_alpha_raw(hwnd, r["alpha"])
                    else:
                        clear_layered(hwnd)
                n += 1
        self.registry.clear()
        return n

    # --- geometria sobre janelas reais
    def apply_preset(self, w, preset):
        mon = monitor_of_window(w.hwnd)
        place(w.hwnd, preset_rect(preset, mon.work))

    def center(self, w):
        mon = monitor_of_window(w.hwnd)
        cur = _rect_of(w.hwnd) if w.state == "normal" else w.rect
        place(w.hwnd, center_rect(cur, mon.work))

    def move_next_monitor(self, w):
        mons = list_monitors()
        if len(mons) < 2:
            return False
        cur = monitor_of_window(w.hwnd)
        i = monitor_index_for_rect(cur.rect, mons)
        dst = mons[next_monitor_index(i, len(mons))]
        was_max = user32.IsZoomed(w.hwnd)
        rect = move_to_monitor(_normal_rect(w.hwnd), cur.work, dst.work)
        place(w.hwnd, rect)
        if was_max:
            show(w.hwnd, SW_MAXIMIZE)
        return True

    def save_layout(self, windows):
        return [snapshot_entry(w) for w in windows]

    def apply_layout(self, entries, windows):
        """Restaura posições. Retorna (aplicadas, sem_correspondência)."""
        mons = list_monitors()
        ok, miss = 0, []
        for e, w in match_layout(entries, windows):
            if w is None:
                miss.append(e.get("title", "?"))
                continue
            rect = clamp_to_any(tuple(e["rect"]), mons)
            st = e.get("state", "normal")
            if st == "min":
                show(w.hwnd, SW_MINIMIZE)
            else:
                place(w.hwnd, rect)
                if st == "max":
                    show(w.hwnd, SW_MAXIMIZE)
            ok += 1
        return ok, miss
