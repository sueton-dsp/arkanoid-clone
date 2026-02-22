"""
screenshot_tool.py  –  Snagit-ähnliches Screenshot-Tool (Alles in einer Datei)
===============================================================================
Start:  python screenshot_tool.py
        oder Doppelklick auf start.pyw (kein Terminal-Fenster)

Abhängigkeiten (einmalig installieren):
    pip install --user Pillow mss pyautogui pywin32 keyboard numpy

Hotkeys (auch im Hintergrund aktiv):
    Print Screen       → Region auswählen
    Ctrl+Shift+F       → Vollbild
    Ctrl+Shift+W       → Fenster auswählen
    Ctrl+Shift+S       → Scrolling Capture
"""

import sys
import ctypes
import io
import json
import math
import os
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, colorchooser, messagebox
from dataclasses import dataclass
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk


# ── CMD-Fenster verstecken (Windows) ────────────────────────────────────────
try:
    import ctypes as _ct
    _ct.windll.user32.ShowWindow(
        _ct.windll.kernel32.GetConsoleWindow(), 0)
except Exception:
    pass

# DPI-Bewusstsein MUSS vor dem ersten Tk-Fenster gesetzt werden
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Abhängigkeiten prüfen
# ---------------------------------------------------------------------------

REQUIRED = {
    'PIL':       'Pillow',
    'mss':       'mss',
    'pyautogui': 'pyautogui',
    'win32gui':  'pywin32',
    'keyboard':  'keyboard',
    'numpy':     'numpy',
}

def check_dependencies() -> bool:
    missing = []
    for module, package in REQUIRED.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        root = tk.Tk()
        root.withdraw()
        cmd = 'pip install --user ' + ' '.join(missing)
        messagebox.showerror(
            'Fehlende Abhängigkeiten',
            f'Bitte führe folgenden Befehl aus und starte das Tool neu:\n\n'
            f'    {cmd}\n\n'
            f'Fehlend: {", ".join(missing)}',
        )
        root.destroy()
        return False
    return True


# ===========================================================================
# VERLAUF  –  HistoryManager
# ===========================================================================

MAX_ENTRIES = 25
THUMB_W     = 120
THUMB_H     = 80


class HistoryManager:
    """
    Verwaltet den Screenshot-Verlauf (max. 25 Einträge).

    Speicherstruktur neben der screenshot_tool.py:
        history/
            index.json
            img_*.png
            thumb_*.png
    """

    def __init__(self, history_dir: str | None = None):
        if history_dir is None:
            base = os.path.dirname(os.path.abspath(__file__))
            history_dir = os.path.join(base, 'history')

        self.history_dir = history_dir
        self.index_path  = os.path.join(history_dir, 'index.json')
        self.entries: list[dict] = []

        os.makedirs(history_dir, exist_ok=True)
        self._load_index()

    # ------------------------------------------------------------------
    def add(self, image: Image.Image) -> dict:
        now = datetime.now()
        entry_id = now.strftime('%Y%m%d_%H%M%S_%f')

        img_filename = f'img_{entry_id}.png'
        image.save(os.path.join(self.history_dir, img_filename))

        thumb = image.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
        thumb_filename = f'thumb_{entry_id}.png'
        thumb.save(os.path.join(self.history_dir, thumb_filename))

        entry = {
            'id':                entry_id,
            'filename':          img_filename,
            'thumb_filename':    thumb_filename,
            'timestamp':         now.isoformat(),
            'timestamp_display': now.strftime('%d.%m.%Y %H:%M:%S'),
        }
        self.entries.insert(0, entry)

        while len(self.entries) > MAX_ENTRIES:
            self._remove_entry(self.entries[-1])
            self.entries.pop()

        self._save_index()
        return entry

    def update(self, entry_id: str, image: Image.Image):
        entry = self._find(entry_id)
        if not entry:
            return
        image.save(os.path.join(self.history_dir, entry['filename']))
        thumb = image.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
        thumb.save(os.path.join(self.history_dir, entry['thumb_filename']))

    def remove(self, entry_id: str):
        entry = self._find(entry_id)
        if entry:
            self._remove_entry(entry)
            self.entries = [e for e in self.entries if e['id'] != entry_id]
            self._save_index()

    def load_image(self, entry_id: str) -> Image.Image | None:
        entry = self._find(entry_id)
        if not entry:
            return None
        path = os.path.join(self.history_dir, entry['filename'])
        return Image.open(path).copy() if os.path.exists(path) else None

    def load_thumbnail(self, entry_id: str) -> Image.Image | None:
        entry = self._find(entry_id)
        if not entry:
            return None
        path = os.path.join(self.history_dir, entry['thumb_filename'])
        return Image.open(path).copy() if os.path.exists(path) else None

    def get_entries(self) -> list[dict]:
        return list(self.entries)

    # ------------------------------------------------------------------
    def _find(self, entry_id: str) -> dict | None:
        for e in self.entries:
            if e['id'] == entry_id:
                return e
        return None

    def _remove_entry(self, entry: dict):
        for key in ('filename', 'thumb_filename'):
            path = os.path.join(self.history_dir, entry.get(key, ''))
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _load_index(self):
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.entries = [
                    e for e in data.get('entries', [])
                    if os.path.exists(
                        os.path.join(self.history_dir, e.get('filename', '')))
                ]
            except Exception:
                self.entries = []
        else:
            self.entries = []

    def _save_index(self):
        try:
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump({'entries': self.entries}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass


# ===========================================================================
# CAPTURE  –  RegionOverlay, WindowPickerDialog, CaptureEngine
# ===========================================================================

class RegionOverlay:
    """
    Transparentes Vollbild-Overlay.
    Benutzer zieht einen Bereich → Ausschnitt wird zurückgegeben.
    """

    def __init__(self, root, callback):
        self.root     = root
        self.callback = callback
        self._start_x = self._start_y = 0
        self._cur_x   = self._cur_y   = 0
        self.background: Image.Image | None = None

    def show(self):
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]
            raw = sct.grab(mon)
            self.background = Image.frombytes(
                'RGB', raw.size, raw.bgra, 'raw', 'BGRX')

        self.win = tk.Toplevel(self.root)
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-topmost', True)
        self.win.configure(cursor='crosshair')

        self.canvas = tk.Canvas(self.win, highlightthickness=0,
                                cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)

        # Abgedunkelter Hintergrund
        self._bg_dark = self.background.copy()
        r, g, b = self._bg_dark.split()
        factor = 0.5
        r = r.point(lambda p: int(p * factor))
        g = g.point(lambda p: int(p * factor))
        b = b.point(lambda p: int(p * factor))
        self._bg_dark = Image.merge('RGB', (r, g, b))
        self._bg_photo = ImageTk.PhotoImage(self._bg_dark)
        self.canvas.create_image(0, 0, anchor='nw',
                                 image=self._bg_photo, tag='bg')

        self.canvas.create_text(
            self.win.winfo_screenwidth() // 2, 30,
            text='Bereich auswählen  |  ESC = Abbrechen',
            fill='white', font=('Segoe UI', 14), tag='hint')

        self.canvas.bind('<ButtonPress-1>',   self._on_down)
        self.canvas.bind('<B1-Motion>',        self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)
        self.win.bind('<Escape>', lambda e: self._cancel())

    def _on_down(self, event):
        self._start_x = event.x
        self._start_y = event.y

    def _on_drag(self, event):
        self._cur_x = event.x
        self._cur_y = event.y
        self._draw_selection()

    def _on_up(self, event):
        self._cur_x = event.x
        self._cur_y = event.y
        x1, y1, x2, y2 = self._normalized_rect()
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            return
        self.win.destroy()
        self.callback(self.background.crop((x1, y1, x2, y2)))

    def _cancel(self):
        self.win.destroy()

    def _normalized_rect(self):
        return (min(self._start_x, self._cur_x),
                min(self._start_y, self._cur_y),
                max(self._start_x, self._cur_x),
                max(self._start_y, self._cur_y))

    def _draw_selection(self):
        self.canvas.delete('selection')
        x1, y1, x2, y2 = self._normalized_rect()
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w == 0 or h == 0:
            return

        region_img   = self.background.crop((x1, y1, x2, y2))
        self._region_photo = ImageTk.PhotoImage(region_img)
        self.canvas.create_image(x1, y1, anchor='nw',
                                 image=self._region_photo, tag='selection')
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                     outline='#00D4FF', width=2,
                                     tag='selection')
        lbl = f'{w} × {h} px'
        tx  = x1 + 4
        ty  = y1 - 18 if y1 > 20 else y2 + 4
        self.canvas.create_rectangle(
            tx - 2, ty - 2, tx + len(lbl) * 7 + 2, ty + 16,
            fill='#003344', outline='', tag='selection')
        self.canvas.create_text(
            tx, ty, text=lbl, fill='#00D4FF',
            font=('Segoe UI', 10, 'bold'), anchor='nw', tag='selection')


# ---------------------------------------------------------------------------

class WindowPickerDialog:
    """Zeigt alle sichtbaren Fenster zur Auswahl."""

    def __init__(self, parent):
        self.result = None
        self.parent = parent

    def show(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title('Fenster auswählen')
        self.dialog.geometry('500x400')
        self.dialog.grab_set()
        self.dialog.attributes('-topmost', True)

        tk.Label(self.dialog,
                 text='Wähle das Fenster aus, das aufgenommen werden soll:',
                 font=('Segoe UI', 10)).pack(padx=10, pady=8, anchor='w')

        frame = tk.Frame(self.dialog)
        frame.pack(fill='both', expand=True, padx=10, pady=4)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')

        self.listbox = tk.Listbox(frame, yscrollcommand=scrollbar.set,
                                  font=('Segoe UI', 10), selectmode='single')
        self.listbox.pack(fill='both', expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.windows = self._get_windows()
        for hwnd, title in self.windows:
            self.listbox.insert('end', title)

        btn_frame = tk.Frame(self.dialog)
        btn_frame.pack(fill='x', padx=10, pady=8)
        tk.Button(btn_frame, text='Aufnehmen', command=self._on_ok,
                  bg='#0078D4', fg='white',
                  font=('Segoe UI', 10)).pack(side='right', padx=4)
        tk.Button(btn_frame, text='Abbrechen', command=self._on_cancel,
                  font=('Segoe UI', 10)).pack(side='right', padx=4)

        self.parent.wait_window(self.dialog)
        return self.result

    def _on_ok(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.windows[sel[0]]
        self.dialog.destroy()

    def _on_cancel(self):
        self.dialog.destroy()

    @staticmethod
    def _get_windows():
        try:
            import win32gui
            def callback(hwnd, result):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title.strip():
                        result.append((hwnd, title))
            wins = []
            win32gui.EnumWindows(callback, wins)
            return wins
        except ImportError:
            return []


# ---------------------------------------------------------------------------

class CaptureEngine:
    """Kapselt alle vier Capture-Modi."""

    def capture_fullscreen(self) -> Image.Image:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]
            raw = sct.grab(mon)
            return Image.frombytes('RGB', raw.size, raw.bgra, 'raw', 'BGRX')

    def capture_window(self, hwnd: int) -> Image.Image:
        try:
            import win32gui, win32ui
            from ctypes import windll

            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                raise ValueError('Fenster hat ungültige Größe')

            hwnd_dc    = win32gui.GetWindowDC(hwnd)
            mfc_dc     = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc    = mfc_dc.CreateCompatibleDC()
            save_bmp   = win32ui.CreateBitmap()
            save_bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(save_bmp)
            windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)

            bmpinfo = save_bmp.GetInfo()
            bmpstr  = save_bmp.GetBitmapBits(True)
            img = Image.frombuffer(
                'RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1)

            win32gui.DeleteObject(save_bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            return img

        except Exception:
            try:
                import win32gui
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            except Exception:
                raise
            import mss
            with mss.mss() as sct:
                mon = {'left': left, 'top': top,
                       'width': right - left, 'height': bottom - top}
                raw = sct.grab(mon)
                return Image.frombytes('RGB', raw.size,
                                       raw.bgra, 'raw', 'BGRX')

    def capture_scrolling(self, region: tuple,
                          scroll_pause: float = 0.5,
                          max_scrolls: int = 30) -> Image.Image:
        import mss, pyautogui

        x1, y1, x2, y2 = region
        mon = {'left': x1, 'top': y1, 'width': x2 - x1, 'height': y2 - y1}
        cx  = x1 + (x2 - x1) // 2
        cy  = y1 + (y2 - y1) // 2

        strips: list[Image.Image] = []
        prev_strip: Image.Image | None = None
        scroll_offsets: list[int] = []

        for _ in range(max_scrolls + 1):
            time.sleep(0.1)
            with mss.mss() as sct:
                raw   = sct.grab(mon)
                strip = Image.frombytes('RGB', raw.size, raw.bgra, 'raw', 'BGRX')

            if prev_strip is not None:
                offset = self._find_overlap(prev_strip, strip)
                if offset is None or offset == 0:
                    break
                scroll_offsets.append(offset)
            strips.append(strip)
            prev_strip = strip

            pyautogui.click(cx, cy)
            pyautogui.press('pagedown')
            time.sleep(scroll_pause)

        if not strips:
            import mss
            with mss.mss() as sct:
                raw = sct.grab(mon)
                return Image.frombytes('RGB', raw.size,
                                       raw.bgra, 'raw', 'BGRX')
        return self._stitch(strips, scroll_offsets)

    def _find_overlap(self, prev: Image.Image,
                      curr: Image.Image) -> int | None:
        try:
            import numpy as np
        except ImportError:
            return prev.height // 2

        pa = np.array(prev.convert('L'), dtype=np.int32)
        ca = np.array(curr.convert('L'), dtype=np.int32)
        h  = pa.shape[0]
        search = min(300, h // 2)

        best_offset = None
        best_score  = float('inf')
        for candidate in range(5, search):
            diff = float(np.mean(np.abs(
                pa[h - candidate:h] - ca[0:candidate])))
            if diff < best_score:
                best_score  = diff
                best_offset = candidate

        if best_score > 20:
            return None
        return h - best_offset

    def _stitch(self, strips: list[Image.Image],
                offsets: list[int]) -> Image.Image:
        w = strips[0].width
        visible_heights = offsets + [strips[-1].height]
        total_h = sum(
            vis if i < len(strips) - 1 else strip.height
            for i, (strip, vis) in enumerate(zip(strips, visible_heights)))

        canvas = Image.new('RGB', (w, total_h), 'white')
        y = 0
        for i, (strip, vis) in enumerate(zip(strips, visible_heights)):
            if i < len(strips) - 1:
                canvas.paste(strip.crop((0, 0, w, vis)), (0, y))
                y += vis
            else:
                canvas.paste(strip, (0, y))
        return canvas


# ===========================================================================
# EDITOR  –  Annotation (Datenmodell) + AnnotationEditor
# ===========================================================================

@dataclass
class Annotation:
    kind:      str
    x1:        int = 0
    y1:        int = 0
    x2:        int = 0
    y2:        int = 0
    color:     str = '#FF0000'
    width:     int = 3
    text:      str = ''
    font_size: int = 16
    tail_x:    int = 0
    tail_y:    int = 0


class AnnotationEditor:
    """Annotations-Editor mit horizontaler Toolbar und Filmstreifen."""

    TOOLS = [
        ('arrow',     '→',  'Pfeil'),
        ('line',      '╱',  'Linie'),
        ('rect',      '□',  'Rechteck'),
        ('text',      'T',  'Text'),
        ('callout',   '💬', 'Callout'),
        ('highlight', '▓',  'Markierung'),
        ('blur',      '≋',  'Weichzeichner'),
        ('blackout',  '■',  'Schwärzung'),
    ]

    # Helles Design – Farben (verfeinerte Palette)
    BG_MAIN      = '#F5F7FA'
    BG_TOOLBAR   = '#FFFFFF'
    BG_CANVAS    = '#C8CDD5'
    BG_STRIP     = '#F5F7FA'
    BG_CELL      = '#FFFFFF'
    FG_MAIN      = '#1E293B'
    FG_MUTED     = '#94A3B8'
    ACCENT       = '#0078D4'
    ACCENT_HOV   = '#006ABE'
    ACCENT_LIGHT = '#EBF3FB'
    BTN_SEL      = '#0078D4'
    BTN_NORM     = '#F0F2F5'
    BTN_HOV      = '#E4E8EF'
    BTN_FG       = '#334155'
    DIVIDER      = '#E2E8F0'
    DANGER       = '#DC2626'
    DANGER_HOV   = '#B91C1C'

    def __init__(self, parent: tk.Tk, image: Image.Image, app,
                 history: HistoryManager | None = None):
        self.parent  = parent
        self.image   = image.copy()
        self.app     = app
        self.history = history or HistoryManager()

        self.annotations: list[Annotation] = []
        self.undo_stack:  list[list]        = []

        self.active_tool = 'arrow'
        self.tool_color  = '#FF0000'
        self.tool_width  = 3
        self.font_size   = 16

        self._drawing    = False
        self._drag_item  = None
        self._drag_start = (0, 0)
        self._tmp_photo  = None

        self._thumb_photos: list[ImageTk.PhotoImage] = []
        self._current_entry_id: str | None = None

        self.win:         tk.Toplevel | None        = None
        self.canvas:      tk.Canvas | None          = None
        self._base_photo: ImageTk.PhotoImage | None = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def load_image(self, image: Image.Image, entry_id: str | None = None):
        self._autosave()
        self._current_entry_id = entry_id
        self.image = image.copy()
        self.annotations.clear()
        self.undo_stack.clear()
        self._redraw_canvas()
        self._refresh_filmstrip()
        self.win.lift()
        self.win.focus_force()
        self._status_var.set('Neuer Screenshot geladen')

    def _autosave(self):
        if not self.annotations or not self._current_entry_id:
            return
        try:
            self._status_var.set('Autospeicherung …')
            self.history.update(self._current_entry_id, self._composite_image())
            self._refresh_filmstrip()
        except Exception:
            pass

    def show(self, entry_id: str | None = None):
        self._current_entry_id = entry_id
        self.win = tk.Toplevel(self.parent)
        self.win.title('Screenshot-Editor')
        self.win.attributes('-topmost', False)

        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        iw, ih = self.image.size
        win_w  = min(iw + 120, int(sw * 0.9))
        win_h  = min(ih + 230, int(sh * 0.92))
        self.win.geometry(f'{win_w}x{win_h}')

        self._build_menu()
        self._build_statusbar()   # side='bottom' → zuerst packen
        self._build_filmstrip()   # side='bottom' → vor Canvas packen!
        self._build_toolbar()     # side='top'
        self._build_canvas()      # fill='both', expand=True → zuletzt!
        self._bind_shortcuts()
        self._redraw_canvas()
        self.win.protocol('WM_DELETE_WINDOW', self._on_close)

    # ------------------------------------------------------------------
    # Hover-Hilfsmethoden
    # ------------------------------------------------------------------

    def _add_hover(self, widget: tk.Widget,
                   hover_bg: str, hover_fg: str,
                   normal_bg: str, normal_fg: str):
        widget.bind('<Enter>',
                    lambda e: widget.config(bg=hover_bg, fg=hover_fg))
        widget.bind('<Leave>',
                    lambda e: widget.config(bg=normal_bg, fg=normal_fg))

    def _add_tool_hover(self, btn: tk.Button, tool_id: str):
        def on_enter(e):
            if self.active_tool != tool_id:
                btn.config(bg=self.ACCENT_LIGHT, fg=self.ACCENT)
        def on_leave(e):
            if self.active_tool == tool_id:
                btn.config(bg=self.BTN_SEL, fg='white')
            else:
                btn.config(bg=self.BTN_NORM, fg=self.BTN_FG)
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)

    # ------------------------------------------------------------------
    # GUI-Aufbau
    # ------------------------------------------------------------------

    def _build_menu(self):
        mb = tk.Menu(self.win, bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                     activebackground=self.ACCENT, activeforeground='white')
        fm = tk.Menu(mb, tearoff=0, bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                     activebackground=self.ACCENT, activeforeground='white')
        fm.add_command(label='Speichern  Ctrl+S',       command=self.save_to_file)
        fm.add_command(label='In Zwischenablage  Ctrl+C', command=self.copy_to_clipboard)
        fm.add_separator()
        fm.add_command(label='Schließen',               command=self._on_close)
        mb.add_cascade(label='Datei', menu=fm)

        em = tk.Menu(mb, tearoff=0, bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                     activebackground=self.ACCENT, activeforeground='white')
        em.add_command(label='Rückgängig  Ctrl+Z', command=self._undo)
        mb.add_cascade(label='Bearbeiten', menu=em)
        self.win.config(menu=mb, bg=self.BG_MAIN)

    def _build_toolbar(self):
        self.toolbar = tk.Frame(self.win, bg=self.BG_TOOLBAR,
                                relief='flat', bd=0,
                                highlightthickness=1,
                                highlightbackground=self.DIVIDER)
        self.toolbar.pack(side='top', fill='x')
        inner = tk.Frame(self.toolbar, bg=self.BG_TOOLBAR)
        inner.pack(fill='x', padx=4, pady=3)

        # Werkzeug-Buttons
        self._tool_buttons: dict[str, tk.Button] = {}
        for tool_id, symbol, label in self.TOOLS:
            btn = tk.Button(
                inner, text=f'{symbol}  {label}',
                font=('Segoe UI', 9),
                bg=self.BTN_NORM, fg=self.BTN_FG,
                activebackground=self.ACCENT, activeforeground='white',
                relief='flat', padx=10, pady=5, bd=0, cursor='hand2',
                command=lambda t=tool_id: self._select_tool(t))
            btn.pack(side='left', padx=1)
            self._tool_buttons[tool_id] = btn
            self._add_tool_hover(btn, tool_id)

        tk.Frame(inner, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', padx=8, pady=2)

        # Farb-Swatch
        tk.Label(inner, text='Farbe', bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
        self._color_swatch = tk.Frame(
            inner, bg=self.tool_color, width=24, height=24,
            highlightthickness=2, highlightbackground=self.DIVIDER,
            cursor='hand2')
        self._color_swatch.pack(side='left', padx=(0, 8))
        self._color_swatch.pack_propagate(False)
        self._color_swatch.bind('<Button-1>', lambda e: self._pick_color())
        self._color_swatch.bind('<Enter>',
            lambda e: self._color_swatch.config(highlightbackground=self.ACCENT))
        self._color_swatch.bind('<Leave>',
            lambda e: self._color_swatch.config(highlightbackground=self.DIVIDER))

        tk.Frame(inner, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', padx=8, pady=2)

        # Strichbreite
        tk.Label(inner, text='Breite', bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 3))
        self._width_var = tk.IntVar(value=self.tool_width)
        tk.Spinbox(inner, from_=1, to=20, textvariable=self._width_var,
                   width=3, font=('Segoe UI', 9), relief='flat',
                   bg=self.BTN_NORM, fg=self.FG_MAIN,
                   buttonbackground=self.BTN_NORM,
                   command=self._update_width).pack(side='left', padx=(0, 8))

        tk.Frame(inner, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', padx=8, pady=2)

        # Schriftgröße
        tk.Label(inner, text='Schrift', bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 3))
        self._font_var = tk.IntVar(value=self.font_size)
        tk.Spinbox(inner, from_=8, to=72, textvariable=self._font_var,
                   width=3, font=('Segoe UI', 9), relief='flat',
                   bg=self.BTN_NORM, fg=self.FG_MAIN,
                   buttonbackground=self.BTN_NORM,
                   command=self._update_font).pack(side='left')

        # Aktions-Buttons rechts
        tk.Frame(inner, bg=self.DIVIDER, width=1).pack(
            side='right', fill='y', padx=8, pady=2)

        save_btn = tk.Button(inner, text='💾  Speichern',
            font=('Segoe UI', 9, 'bold'),
            bg=self.ACCENT, fg='white',
            activebackground=self.ACCENT_HOV, activeforeground='white',
            relief='flat', padx=12, pady=5, bd=0, cursor='hand2',
            command=self.save_to_file)
        save_btn.pack(side='right', padx=(2, 0))
        self._add_hover(save_btn, self.ACCENT_HOV, 'white',
                        self.ACCENT, 'white')

        copy_btn = tk.Button(inner, text='📋  Kopieren',
            font=('Segoe UI', 9),
            bg=self.BTN_NORM, fg=self.BTN_FG,
            activebackground=self.BTN_HOV, activeforeground=self.FG_MAIN,
            relief='flat', padx=10, pady=5, bd=0, cursor='hand2',
            command=self.copy_to_clipboard)
        copy_btn.pack(side='right', padx=2)
        self._add_hover(copy_btn, self.BTN_HOV, self.FG_MAIN,
                        self.BTN_NORM, self.BTN_FG)

        undo_btn = tk.Button(inner, text='↩  Undo',
            font=('Segoe UI', 9),
            bg=self.BTN_NORM, fg=self.BTN_FG,
            activebackground=self.BTN_HOV, activeforeground=self.FG_MAIN,
            relief='flat', padx=10, pady=5, bd=0, cursor='hand2',
            command=self._undo)
        undo_btn.pack(side='right', padx=2)
        self._add_hover(undo_btn, self.BTN_HOV, self.FG_MAIN,
                        self.BTN_NORM, self.BTN_FG)

        self._select_tool('arrow')

    def _build_canvas(self):
        frame = tk.Frame(self.win, bg=self.BG_MAIN)
        frame.pack(side='left', fill='both', expand=True)

        hbar = tk.Scrollbar(frame, orient='horizontal')
        hbar.pack(side='bottom', fill='x')
        vbar = tk.Scrollbar(frame, orient='vertical')
        vbar.pack(side='right', fill='y')

        self.canvas = tk.Canvas(frame, bg=self.BG_CANVAS,
                                xscrollcommand=hbar.set,
                                yscrollcommand=vbar.set,
                                cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        hbar.config(command=self.canvas.xview)
        vbar.config(command=self.canvas.yview)

        iw, ih = self.image.size
        self.canvas.config(scrollregion=(0, 0, iw, ih))
        self.canvas.bind('<ButtonPress-1>',   self._on_mouse_down)
        self.canvas.bind('<B1-Motion>',        self._on_mouse_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_mouse_up)

    def _build_filmstrip(self):
        STRIP_H = 132
        tk.Frame(self.win, bg=self.DIVIDER, height=1).pack(
            side='bottom', fill='x')

        strip_frame = tk.Frame(self.win, bg=self.BG_STRIP, height=STRIP_H)
        strip_frame.pack(side='bottom', fill='x')
        strip_frame.pack_propagate(False)

        hdr = tk.Frame(strip_frame, bg=self.BG_STRIP)
        hdr.pack(side='left', fill='y', padx=(12, 4))
        tk.Label(hdr, text='🗂', bg=self.BG_STRIP, fg=self.ACCENT,
                 font=('Segoe UI', 18)).pack(pady=(14, 0))
        tk.Label(hdr, text='VERLAUF', bg=self.BG_STRIP, fg=self.FG_MUTED,
                 font=('Segoe UI', 7, 'bold')).pack()

        tk.Frame(strip_frame, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', pady=12, padx=(4, 0))

        outer = tk.Frame(strip_frame, bg=self.BG_STRIP)
        outer.pack(side='left', fill='both', expand=True)

        hbar = tk.Scrollbar(outer, orient='horizontal')
        hbar.pack(side='bottom', fill='x')

        self._strip_canvas = tk.Canvas(outer, bg=self.BG_STRIP,
                                       height=STRIP_H - 20,
                                       xscrollcommand=hbar.set,
                                       highlightthickness=0)
        self._strip_canvas.pack(side='top', fill='both', expand=True)
        hbar.config(command=self._strip_canvas.xview)

        self._strip_inner = tk.Frame(self._strip_canvas, bg=self.BG_STRIP)
        self._strip_canvas.create_window(0, 0, anchor='nw',
                                          window=self._strip_inner)
        self._strip_inner.bind('<Configure>',
            lambda e: self._strip_canvas.config(
                scrollregion=self._strip_canvas.bbox('all')))

        self._refresh_filmstrip()

    def _refresh_filmstrip(self):
        for w in self._strip_inner.winfo_children():
            w.destroy()
        self._thumb_photos.clear()

        entries = self.history.get_entries()
        if not entries:
            tk.Label(self._strip_inner,
                     text='Noch keine Screenshots vorhanden',
                     bg=self.BG_STRIP, fg=self.FG_MUTED,
                     font=('Segoe UI', 9)).pack(padx=20, pady=20)
            return
        for entry in entries:
            self._add_thumb_widget(entry)

    def _add_thumb_widget(self, entry: dict):
        thumb_img = self.history.load_thumbnail(entry['id'])
        is_active = (entry['id'] == self._current_entry_id)

        card = tk.Frame(self._strip_inner, bg=self.BG_CELL,
                        highlightthickness=2,
                        highlightbackground=self.ACCENT if is_active
                                            else self.DIVIDER)
        card.pack(side='left', padx=5, pady=6)

        if is_active:
            tk.Frame(card, bg=self.ACCENT, height=3).pack(fill='x', side='top')

        if thumb_img:
            photo = ImageTk.PhotoImage(thumb_img)
            self._thumb_photos.append(photo)
            img_lbl = tk.Label(card, image=photo, bg=self.BG_CELL,
                               cursor='hand2')
            img_lbl.pack(padx=4, pady=(3 if not is_active else 0, 0))
            img_lbl.bind('<Button-1>',
                lambda e, eid=entry['id']: self._load_from_history(eid))
        else:
            img_lbl = tk.Label(card, text='?', bg=self.BG_CELL,
                               fg=self.FG_MUTED, width=14, height=5)
            img_lbl.pack(padx=4, pady=3)

        ts = entry.get('timestamp_display', '')[-8:]
        time_lbl = tk.Label(card, text=ts, bg=self.BG_CELL,
                            fg=self.ACCENT if is_active else self.FG_MUTED,
                            font=('Segoe UI', 7,
                                  'bold' if is_active else 'normal'))
        time_lbl.pack(pady=(1, 0))

        del_btn = tk.Button(card, text='✕', font=('Segoe UI', 7),
                            bg=self.BG_CELL, fg=self.FG_MUTED,
                            activebackground=self.DANGER,
                            activeforeground='white',
                            relief='flat', padx=4, pady=1,
                            bd=0, cursor='hand2',
                            command=lambda eid=entry['id']:
                                self._delete_history_entry(eid))
        del_btn.pack(fill='x', padx=3, pady=(0, 3))

        def on_card_enter(e):
            card.config(highlightbackground=self.ACCENT)
        def on_card_leave(e):
            card.config(highlightbackground=self.ACCENT if is_active
                                            else self.DIVIDER)
        for w in [card, img_lbl, time_lbl]:
            w.bind('<Enter>', on_card_enter)
            w.bind('<Leave>', on_card_leave)

        del_btn.bind('<Enter>',
            lambda e: del_btn.config(bg=self.DANGER, fg='white'))
        del_btn.bind('<Leave>',
            lambda e: del_btn.config(bg=self.BG_CELL, fg=self.FG_MUTED))

    def _load_from_history(self, entry_id: str):
        img = self.history.load_image(entry_id)
        if img is None:
            messagebox.showwarning('Verlauf', 'Bild nicht mehr verfügbar.',
                                   parent=self.win)
            return
        self._autosave()
        self._current_entry_id = entry_id
        self.undo_stack.clear()
        self.annotations.clear()
        self.image = img
        self._redraw_canvas()
        self._status_var.set('Bild aus Verlauf geladen')

    def _delete_history_entry(self, entry_id: str):
        self.history.remove(entry_id)
        self._refresh_filmstrip()
        self._status_var.set('Eintrag aus Verlauf gelöscht')

    def _build_statusbar(self):
        self._status_var = tk.StringVar(value='Bereit')
        bar = tk.Frame(self.win, bg=self.BG_TOOLBAR)
        bar.pack(side='bottom', fill='x')
        row = tk.Frame(bar, bg=self.BG_TOOLBAR)
        row.pack(fill='x', padx=10, pady=4)
        self._status_dot = tk.Label(row, text='●', bg=self.BG_TOOLBAR,
                                    fg=self.ACCENT, font=('Segoe UI', 8))
        self._status_dot.pack(side='left')
        tk.Label(row, textvariable=self._status_var, anchor='w',
                 bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 8)).pack(side='left', padx=(4, 0))

    def _bind_shortcuts(self):
        self.win.bind('<Control-z>', lambda e: self._undo())
        self.win.bind('<Control-s>', lambda e: self.save_to_file())
        self.win.bind('<Control-c>', lambda e: self.copy_to_clipboard())
        for i, (tool_id, _, _) in enumerate(self.TOOLS):
            self.win.bind(str(i + 1),
                          lambda e, t=tool_id: self._select_tool(t))

    # ------------------------------------------------------------------
    # Tool-Steuerung
    # ------------------------------------------------------------------

    def _select_tool(self, tool_id: str):
        self.active_tool = tool_id
        for tid, btn in self._tool_buttons.items():
            btn.config(bg=self.BTN_SEL if tid == tool_id else self.BTN_NORM,
                       fg='white'     if tid == tool_id else self.BTN_FG)
        self._update_status()

    def _pick_color(self):
        c = colorchooser.askcolor(color=self.tool_color,
                                  parent=self.win, title='Farbe wählen')
        if c and c[1]:
            self.tool_color = c[1]
            self._color_swatch.config(bg=self.tool_color)

    def _update_width(self):
        self.tool_width = self._width_var.get()

    def _update_font(self):
        self.font_size = self._font_var.get()

    def _update_status(self):
        labels = {t[0]: t[2] for t in self.TOOLS}
        self._status_var.set(
            f'Werkzeug: {labels.get(self.active_tool, "")}  |  '
            f'Farbe: {self.tool_color}  |  '
            f'Breite: {self.tool_width}')

    # ------------------------------------------------------------------
    # Maus-Events
    # ------------------------------------------------------------------

    def _canvas_coords(self, event):
        return int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y))

    def _on_mouse_down(self, event):
        self._drawing    = True
        x, y             = self._canvas_coords(event)
        self._drag_start = (x, y)
        self._drag_item  = None
        if self.active_tool == 'text':
            self._handle_text(x, y)
            self._drawing = False
        elif self.active_tool == 'callout':
            self._handle_callout_start(x, y)

    def _on_mouse_drag(self, event):
        if not self._drawing:
            return
        x, y    = self._canvas_coords(event)
        x0, y0  = self._drag_start
        self._draw_preview(x0, y0, x, y)

    def _on_mouse_up(self, event):
        if not self._drawing:
            return
        self._drawing = False
        x, y   = self._canvas_coords(event)
        x0, y0 = self._drag_start
        if abs(x - x0) < 2 and abs(y - y0) < 2:
            self._clear_preview()
            return
        if self.active_tool == 'callout':
            return
        ann = self._make_annotation(x0, y0, x, y)
        if ann:
            self._commit(ann)
        self._clear_preview()

    # ------------------------------------------------------------------
    # Vorschau während des Ziehens
    # ------------------------------------------------------------------

    def _draw_preview(self, x0, y0, x1, y1):
        self.canvas.delete('preview')
        tool = self.active_tool
        c, w = self.tool_color, self.tool_width

        if tool == 'arrow':
            self.canvas.create_line(x0, y0, x1, y1, fill=c, width=w,
                                    arrow=tk.LAST, arrowshape=(16, 20, 6),
                                    tag='preview')
        elif tool == 'line':
            self.canvas.create_line(x0, y0, x1, y1, fill=c, width=w,
                                    tag='preview')
        elif tool == 'rect':
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=c, width=w,
                                         tag='preview')
        elif tool in ('highlight', 'blur', 'blackout'):
            fill = c if tool == 'highlight' else (
                'gray' if tool == 'blur' else 'black')
            stip = 'gray50' if tool == 'highlight' else ''
            self.canvas.create_rectangle(
                x0, y0, x1, y1,
                outline=c if tool == 'highlight' else fill,
                fill=fill, stipple=stip, width=1, tag='preview')

    def _clear_preview(self):
        self.canvas.delete('preview')

    # ------------------------------------------------------------------
    # Annotierungen erstellen
    # ------------------------------------------------------------------

    def _make_annotation(self, x0, y0, x1, y1) -> Annotation | None:
        if self.active_tool not in ('arrow', 'line', 'rect',
                                    'highlight', 'blur', 'blackout'):
            return None
        return Annotation(kind=self.active_tool,
                          x1=x0, y1=y0, x2=x1, y2=y1,
                          color=self.tool_color, width=self.tool_width)

    def _handle_text(self, x, y):
        text = simpledialog.askstring('Text eingeben', 'Beschriftung:',
                                      parent=self.win)
        if text:
            self._commit(Annotation(kind='text', x1=x, y1=y, x2=x, y2=y,
                                    color=self.tool_color,
                                    font_size=self.font_size, text=text))

    def _handle_callout_start(self, x, y):
        text = simpledialog.askstring('Callout-Text', 'Beschriftung:',
                                      parent=self.win)
        if not text:
            self._drawing = False
            return
        self._callout_text = text
        self._callout_x    = x
        self._callout_y    = y
        self._status_var.set(
            'Schweif-Spitze setzen: Klicke auf das Ziel des Callouts')
        self.canvas.bind('<ButtonPress-1>', self._handle_callout_tip)

    def _handle_callout_tip(self, event):
        self.canvas.bind('<ButtonPress-1>', self._on_mouse_down)
        x, y = self._canvas_coords(event)
        self._commit(Annotation(
            kind='callout',
            x1=self._callout_x, y1=self._callout_y,
            x2=self._callout_x + 120, y2=self._callout_y + 40,
            color=self.tool_color, width=self.tool_width,
            font_size=self.font_size, text=self._callout_text,
            tail_x=x, tail_y=y))
        self._drawing = False
        self._update_status()

    # ------------------------------------------------------------------
    # Undo / Commit
    # ------------------------------------------------------------------

    def _commit(self, ann: Annotation):
        self.undo_stack.append([a for a in self.annotations])
        self.annotations.append(ann)
        self._redraw_canvas()

    def _undo(self):
        if self.undo_stack:
            self.annotations = self.undo_stack.pop()
            self._redraw_canvas()

    # ------------------------------------------------------------------
    # Canvas-Redraw
    # ------------------------------------------------------------------

    def _redraw_canvas(self):
        self.canvas.delete('annotation')
        self.canvas.delete('base')
        self._base_photo = ImageTk.PhotoImage(self.image)
        self.canvas.create_image(0, 0, anchor='nw',
                                 image=self._base_photo, tag='base')
        iw, ih = self.image.size
        self.canvas.config(scrollregion=(0, 0, iw, ih))
        for ann in self.annotations:
            self._draw_annotation_on_canvas(ann)

    def _draw_annotation_on_canvas(self, ann: Annotation):
        c, w, tag = ann.color, ann.width, 'annotation'

        if ann.kind == 'arrow':
            self.canvas.create_line(ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, width=w, arrow=tk.LAST, arrowshape=(16, 20, 6),
                tag=tag)
        elif ann.kind == 'line':
            self.canvas.create_line(ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, width=w, tag=tag)
        elif ann.kind == 'rect':
            self.canvas.create_rectangle(ann.x1, ann.y1, ann.x2, ann.y2,
                outline=c, width=w, tag=tag)
        elif ann.kind == 'text':
            self.canvas.create_text(ann.x1, ann.y1,
                text=ann.text, fill=c,
                font=('Segoe UI', ann.font_size, 'bold'),
                anchor='nw', tag=tag)
        elif ann.kind == 'callout':
            mx = (ann.x1 + ann.x2) // 2
            self.canvas.create_rectangle(ann.x1, ann.y1, ann.x2, ann.y2,
                fill='white', outline=c, width=w, tag=tag)
            self.canvas.create_polygon(
                mx - 8, ann.y2, mx + 8, ann.y2, ann.tail_x, ann.tail_y,
                fill='white', outline=c, width=w, tag=tag)
            self.canvas.create_text(ann.x1 + 6, ann.y1 + 6,
                text=ann.text, fill=c,
                font=('Segoe UI', ann.font_size), anchor='nw', tag=tag)
        elif ann.kind == 'highlight':
            self.canvas.create_rectangle(ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, stipple='gray50', outline='', tag=tag)
        elif ann.kind == 'blur':
            self.canvas.create_rectangle(ann.x1, ann.y1, ann.x2, ann.y2,
                fill='gray', stipple='gray50', outline='gray', tag=tag)
        elif ann.kind == 'blackout':
            self.canvas.create_rectangle(ann.x1, ann.y1, ann.x2, ann.y2,
                fill='black', outline='black', tag=tag)

    # ------------------------------------------------------------------
    # PIL-Composite (für Speichern)
    # ------------------------------------------------------------------

    def _composite_image(self) -> Image.Image:
        img = self.image.copy().convert('RGBA')
        for ann in self.annotations:
            img = self._apply_annotation(img, ann)
        return img.convert('RGB')

    def _apply_annotation(self, img: Image.Image,
                          ann: Annotation) -> Image.Image:
        draw = ImageDraw.Draw(img, 'RGBA')

        def rgba(hex_color, alpha=255):
            h = hex_color.lstrip('#')
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha

        c, w = rgba(ann.color), ann.width

        if ann.kind == 'arrow':
            draw.line([(ann.x1, ann.y1), (ann.x2, ann.y2)], fill=c, width=w)
            angle = math.atan2(ann.y2 - ann.y1, ann.x2 - ann.x1)
            size  = max(12, w * 4)
            for a in [angle + 2.5, angle - 2.5]:
                px = ann.x2 - size * math.cos(a)
                py = ann.y2 - size * math.sin(a)
                draw.line([(ann.x2, ann.y2), (int(px), int(py))],
                          fill=c, width=w)
        elif ann.kind == 'line':
            draw.line([(ann.x1, ann.y1), (ann.x2, ann.y2)], fill=c, width=w)
        elif ann.kind == 'rect':
            draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                           outline=c, width=w)
        elif ann.kind == 'text':
            try:
                font = ImageFont.truetype('segoeui.ttf', ann.font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((ann.x1, ann.y1), ann.text, fill=c, font=font)
        elif ann.kind == 'callout':
            bg = (255, 255, 255, 230)
            draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                           fill=bg, outline=c, width=w)
            mx = (ann.x1 + ann.x2) // 2
            draw.polygon([(mx - 8, ann.y2), (mx + 8, ann.y2),
                          (ann.tail_x, ann.tail_y)], fill=bg, outline=c)
            try:
                font = ImageFont.truetype('segoeui.ttf', ann.font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((ann.x1 + 6, ann.y1 + 6), ann.text,
                      fill=c, font=font)
        elif ann.kind == 'highlight':
            overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            ov_draw = ImageDraw.Draw(overlay)
            ov_draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                               fill=rgba(ann.color, 100))
            img = Image.alpha_composite(img, overlay)
        elif ann.kind == 'blur':
            x1, y1 = min(ann.x1, ann.x2), min(ann.y1, ann.y2)
            x2, y2 = max(ann.x1, ann.x2), max(ann.y1, ann.y2)
            if x2 > x1 and y2 > y1:
                region  = img.crop((x1, y1, x2, y2))
                blurred = region.filter(ImageFilter.GaussianBlur(radius=15))
                img.paste(blurred, (x1, y1))
        elif ann.kind == 'blackout':
            x1, y1 = min(ann.x1, ann.x2), min(ann.y1, ann.y2)
            x2, y2 = max(ann.x1, ann.x2), max(ann.y1, ann.y2)
            draw.rectangle([(x1, y1), (x2, y2)], fill=(0, 0, 0, 255))

        del draw
        return img

    # ------------------------------------------------------------------
    # Speichern / Clipboard
    # ------------------------------------------------------------------

    def save_to_file(self):
        default = datetime.now().strftime('screenshot_%Y%m%d_%H%M%S.png')
        path = filedialog.asksaveasfilename(
            parent=self.win, defaultextension='.png',
            initialfile=default,
            filetypes=[('PNG-Bild', '*.png'), ('JPEG-Bild', '*.jpg'),
                       ('Alle Dateien', '*.*')])
        if not path:
            return
        img = self._composite_image()
        if path.lower().endswith(('.jpg', '.jpeg')):
            img.convert('RGB').save(path, quality=95)
        else:
            img.save(path)
        self._status_var.set(f'Gespeichert: {path}')

    def copy_to_clipboard(self):
        img = self._composite_image()
        try:
            import win32clipboard
            output = io.BytesIO()
            img.convert('RGB').save(output, 'BMP')
            data = output.getvalue()[14:]
            output.close()
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            self._status_var.set('In Zwischenablage kopiert')
        except ImportError:
            messagebox.showinfo(
                'Zwischenablage',
                'pywin32 nicht verfügbar.\n'
                'Bitte speichere das Bild als Datei.',
                parent=self.win)

    def _on_close(self):
        self.win.destroy()
        self.app.on_editor_closed()


# ===========================================================================
# Spezielles Overlay für Scrolling (gibt Koordinaten zurück, kein Bild)
# ===========================================================================

class _ScrollingRegionOverlay:
    """Wie RegionOverlay, gibt aber Bildschirmkoordinaten zurück."""

    def __init__(self, root, callback):
        self.root     = root
        self.callback = callback
        self._start_x = self._start_y = 0
        self._cur_x   = self._cur_y   = 0

    def show(self):
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]
            raw = sct.grab(mon)
            self.background = Image.frombytes(
                'RGB', raw.size, raw.bgra, 'raw', 'BGRX')

        self.win = tk.Toplevel(self.root)
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-topmost', True)
        self.win.configure(cursor='crosshair')

        self.canvas = tk.Canvas(self.win, highlightthickness=0,
                                cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)

        bg_dark = self.background.copy()
        r, g, b = bg_dark.split()
        bg_dark = Image.merge('RGB', tuple(
            c.point(lambda p: int(p * 0.5)) for c in (r, g, b)))
        self._bg_photo = ImageTk.PhotoImage(bg_dark)
        self.canvas.create_image(0, 0, anchor='nw', image=self._bg_photo)

        sw = self.win.winfo_screenwidth()
        self.canvas.create_text(
            sw // 2, 30,
            text='Scroll-Bereich auswählen (sichtbares Fenster)  |  ESC = Abbrechen',
            fill='#FFDD00', font=('Segoe UI', 13))

        self.canvas.bind('<ButtonPress-1>',   self._on_down)
        self.canvas.bind('<B1-Motion>',        self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)
        self.win.bind('<Escape>', lambda e: self.win.destroy())

    def _on_down(self, e):
        self._start_x, self._start_y = e.x, e.y

    def _on_drag(self, e):
        self._cur_x, self._cur_y = e.x, e.y
        self._draw_sel()

    def _on_up(self, e):
        self._cur_x, self._cur_y = e.x, e.y
        x1, y1, x2, y2 = self._rect()
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            return
        self.win.destroy()
        self.callback((x1, y1, x2, y2))

    def _rect(self):
        return (min(self._start_x, self._cur_x),
                min(self._start_y, self._cur_y),
                max(self._start_x, self._cur_x),
                max(self._start_y, self._cur_y))

    def _draw_sel(self):
        self.canvas.delete('sel')
        x1, y1, x2, y2 = self._rect()
        if x2 == x1 or y2 == y1:
            return
        region = self.background.crop((x1, y1, x2, y2))
        self._sel_photo = ImageTk.PhotoImage(region)
        self.canvas.create_image(x1, y1, anchor='nw',
                                 image=self._sel_photo, tag='sel')
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                     outline='#FFDD00', width=2, tag='sel')
        lbl = f'{x2-x1} × {y2-y1} px'
        self.canvas.create_text(
            x1 + 4, y1 - 18 if y1 > 20 else y2 + 4,
            text=lbl, fill='#FFDD00',
            font=('Segoe UI', 10, 'bold'), anchor='nw', tag='sel')


# ===========================================================================
# HAUPTANWENDUNG  –  ScreenshotApp
# ===========================================================================

class ScreenshotApp:
    """Haupt-Controller: kleines Toolbar-Fenster + globale Hotkeys."""

    # Farben (abgestimmt auf Editor-Design)
    BG       = '#F5F7FA'
    BG_TOP   = '#FFFFFF'
    ACCENT   = '#0078D4'
    ACCENT_H = '#006ABE'
    BTN_NORM = '#F0F2F5'
    BTN_FG   = '#334155'
    FG_MUTED = '#94A3B8'
    DIVIDER  = '#E2E8F0'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Screenshot-Tool')
        self._capturing    = False
        self._active_editor = None

        self.engine  = CaptureEngine()
        self.history = HistoryManager()

        self._build_ui()
        self._register_hotkeys()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.root.configure(bg=self.BG)
        self.root.geometry('720x72')
        self.root.minsize(680, 72)
        self.root.resizable(True, False)

        bar = tk.Frame(self.root, bg=self.BG_TOP,
                       highlightthickness=1,
                       highlightbackground=self.DIVIDER)
        bar.pack(fill='both', expand=True)

        # Logo
        logo_frame = tk.Frame(bar, bg=self.BG_TOP)
        logo_frame.pack(side='left', padx=(12, 8))
        tk.Label(logo_frame, text='📷', bg=self.BG_TOP, fg=self.ACCENT,
                 font=('Segoe UI', 20)).pack(pady=(2, 0))
        tk.Label(logo_frame, text='Screenshot', bg=self.BG_TOP,
                 fg=self.FG_MUTED, font=('Segoe UI', 7, 'bold')).pack()

        tk.Frame(bar, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', pady=10, padx=(0, 6))

        # Capture-Buttons
        for icon, label, hotkey, cmd in [
            ('✂',  'Region',    'Print Screen',  self.start_region),
            ('🖥',  'Vollbild',  'Ctrl+Shift+F',  self.start_fullscreen),
            ('🪟',  'Fenster',   'Ctrl+Shift+W',  self.start_window),
            ('📜',  'Scrolling', 'Ctrl+Shift+S',  self.start_scrolling),
        ]:
            cell = tk.Frame(bar, bg=self.BG_TOP)
            cell.pack(side='left', padx=2, pady=6)
            btn = tk.Button(cell, text=f'{icon}  {label}',
                            font=('Segoe UI', 10),
                            bg=self.BTN_NORM, fg=self.BTN_FG,
                            activebackground=self.ACCENT,
                            activeforeground='white',
                            relief='flat', padx=12, pady=5, bd=0,
                            cursor='hand2', command=cmd)
            btn.pack()
            tk.Label(cell, text=hotkey, bg=self.BG_TOP, fg=self.FG_MUTED,
                     font=('Segoe UI', 7)).pack()
            btn.bind('<Enter>',
                     lambda e, b=btn: b.config(bg=self.ACCENT, fg='white'))
            btn.bind('<Leave>',
                     lambda e, b=btn: b.config(bg=self.BTN_NORM,
                                               fg=self.BTN_FG))

        tk.Frame(bar, bg=self.DIVIDER, width=1).pack(
            side='left', fill='y', pady=10, padx=4)

        # Status
        self._status_var = tk.StringVar(value='Bereit')
        status_row = tk.Frame(bar, bg=self.BG_TOP)
        status_row.pack(side='left', padx=6)
        tk.Label(status_row, text='●', bg=self.BG_TOP, fg=self.ACCENT,
                 font=('Segoe UI', 7)).pack(side='left')
        tk.Label(status_row, textvariable=self._status_var,
                 bg=self.BG_TOP, fg=self.FG_MUTED,
                 font=('Segoe UI', 8), width=18, anchor='w').pack(
                     side='left', padx=(3, 0))

        # Schließen-Button
        close_btn = tk.Button(bar, text='✕', font=('Segoe UI', 11),
                              bg=self.BG_TOP, fg=self.FG_MUTED,
                              activebackground='#DC2626',
                              activeforeground='white',
                              relief='flat', padx=10, pady=4, bd=0,
                              cursor='hand2', command=self.root.quit)
        close_btn.pack(side='right', padx=8, pady=8)
        close_btn.bind('<Enter>',
                       lambda e: close_btn.config(bg='#DC2626', fg='white'))
        close_btn.bind('<Leave>',
                       lambda e: close_btn.config(bg=self.BG_TOP,
                                                   fg=self.FG_MUTED))
        self.root.protocol('WM_DELETE_WINDOW', self.root.quit)

    # ------------------------------------------------------------------
    # Hotkeys
    # ------------------------------------------------------------------

    def _register_hotkeys(self):
        try:
            import keyboard as kb
            kb.add_hotkey('print_screen',
                          lambda: self.root.after(0, self.start_region))
            kb.add_hotkey('ctrl+shift+f',
                          lambda: self.root.after(0, self.start_fullscreen))
            kb.add_hotkey('ctrl+shift+w',
                          lambda: self.root.after(0, self.start_window))
            kb.add_hotkey('ctrl+shift+s',
                          lambda: self.root.after(0, self.start_scrolling))
        except Exception as e:
            self._set_status(f'Hotkeys nicht verfügbar: {e}')

    # ------------------------------------------------------------------
    # Capture-Aktionen
    # ------------------------------------------------------------------

    def start_region(self):
        if self._capturing:
            return
        self._capturing = True
        self._set_status('Region auswählen …')
        self.root.withdraw()
        self.root.after(150, self._do_region)

    def _do_region(self):
        overlay = RegionOverlay(self.root, self._on_captured)
        overlay.show()

    def start_fullscreen(self):
        if self._capturing:
            return
        self._capturing = True
        self._set_status('Vollbild wird aufgenommen …')
        self.root.withdraw()
        self.root.after(300, self._do_fullscreen)

    def _do_fullscreen(self):
        try:
            self._on_captured(self.engine.capture_fullscreen())
        except Exception as e:
            self._capturing = False
            self._show_error(f'Vollbild-Fehler: {e}')

    def start_window(self):
        if self._capturing:
            return
        self._capturing = True
        result = WindowPickerDialog(self.root).show()
        if result is None:
            self._capturing = False
            return
        hwnd, title = result
        self._set_status(f'Fenster wird aufgenommen: {title}')
        self.root.withdraw()
        self.root.after(300, lambda: self._do_window(hwnd))

    def _do_window(self, hwnd):
        try:
            self._on_captured(self.engine.capture_window(hwnd))
        except Exception as e:
            self._capturing = False
            self._show_error(f'Fenster-Fehler: {e}')

    def start_scrolling(self):
        if self._capturing:
            return
        self._capturing = True
        self._set_status('Region für Scrolling auswählen …')
        self.root.withdraw()
        self.root.after(200, self._do_scrolling_pick)

    def _do_scrolling_pick(self):
        _ScrollingRegionOverlay(self.root, self._on_scroll_region).show()

    def _on_scroll_region(self, region: tuple):
        self._set_status('Scrolling Capture läuft … bitte warten')
        self.root.after(100, lambda: self._do_scrolling(region))

    def _do_scrolling(self, region):
        try:
            self._on_captured(self.engine.capture_scrolling(region))
        except Exception as e:
            self._capturing = False
            self._show_error(f'Scrolling-Fehler: {e}')

    # ------------------------------------------------------------------
    # Nach erfolgreichem Capture
    # ------------------------------------------------------------------

    def _on_captured(self, image):
        self._capturing = False
        self.root.deiconify()
        self._set_status('Bereit')

        entry    = self.history.add(image)
        entry_id = entry['id']

        if (self._active_editor
                and self._active_editor.win
                and self._active_editor.win.winfo_exists()):
            self._active_editor.load_image(image, entry_id=entry_id)
        else:
            self._active_editor = AnnotationEditor(
                self.root, image, self, self.history)
            self._active_editor.show(entry_id=entry_id)

    def on_editor_closed(self):
        self._active_editor = None
        self._set_status('Bereit')

    # ------------------------------------------------------------------
    def _set_status(self, msg: str):
        self._status_var.set(msg)
        self.root.update_idletasks()

    def _show_error(self, msg: str):
        self.root.deiconify()
        self._set_status('Fehler')
        messagebox.showerror('Fehler', msg, parent=self.root)

    def run(self):
        self.root.mainloop()


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == '__main__':
    if not check_dependencies():
        sys.exit(1)
    ScreenshotApp().run()
