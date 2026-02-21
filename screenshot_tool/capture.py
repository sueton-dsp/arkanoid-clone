"""
capture.py  –  Screenshot-Aufnahme-Modi
Enthält: CaptureEngine, RegionOverlay
"""

import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageGrab


# ---------------------------------------------------------------------------
# RegionOverlay
# ---------------------------------------------------------------------------

class RegionOverlay:
    """
    Transparentes Vollbild-Overlay.  Der Benutzer zieht mit der Maus
    einen Bereich; nach Loslassen wird der Ausschnitt aus dem
    Pre-Capture zurückgegeben.
    """

    def __init__(self, root, callback):
        self.root = root
        self.callback = callback   # callable(PIL.Image)
        self._start_x = self._start_y = 0
        self._cur_x = self._cur_y = 0
        self.background: Image.Image | None = None

    # ------------------------------------------------------------------
    def show(self):
        """Vollbild-Overlay anzeigen und Maus-Events abfangen."""
        # 1. Hintergrund VOR dem Overlay screenshotten
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]          # alle Monitore kombiniert
            raw = sct.grab(mon)
            self.background = Image.frombytes(
                'RGB', raw.size, raw.bgra, 'raw', 'BGRX')

        # 2. Vollbild-Toplevel
        self.win = tk.Toplevel(self.root)
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-topmost', True)
        self.win.configure(cursor='crosshair')

        # Hintergrund-Bild auf Canvas
        self.canvas = tk.Canvas(
            self.win,
            highlightthickness=0,
            cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)

        # Hintergrundbild anzeigen (abgedunkelt)
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

        # Hilfetexte
        self.canvas.create_text(
            self.win.winfo_screenwidth() // 2, 30,
            text='Bereich auswählen  |  ESC = Abbrechen',
            fill='white',
            font=('Segoe UI', 14),
            tag='hint')

        # Maus-Events
        self.canvas.bind('<ButtonPress-1>', self._on_down)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)
        self.win.bind('<Escape>', lambda e: self._cancel())

    # ------------------------------------------------------------------
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
            # Zu kleiner Bereich
            return
        self.win.destroy()
        cropped = self.background.crop((x1, y1, x2, y2))
        self.callback(cropped)

    def _cancel(self):
        self.win.destroy()

    # ------------------------------------------------------------------
    def _normalized_rect(self):
        x1 = min(self._start_x, self._cur_x)
        y1 = min(self._start_y, self._cur_y)
        x2 = max(self._start_x, self._cur_x)
        y2 = max(self._start_y, self._cur_y)
        return x1, y1, x2, y2

    def _draw_selection(self):
        self.canvas.delete('selection')
        x1, y1, x2, y2 = self._normalized_rect()
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w == 0 or h == 0:
            return

        # Heller Ausschnitt im Bereich
        region_img = self.background.crop((x1, y1, x2, y2))
        region_photo = ImageTk.PhotoImage(region_img)
        # Referenz halten, damit GC es nicht löscht
        self._region_photo = region_photo
        self.canvas.create_image(x1, y1, anchor='nw',
                                 image=region_photo, tag='selection')

        # Rahmen
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline='#00D4FF', width=2,
            tag='selection')

        # Dimensionsanzeige
        lbl = f'{w} × {h} px'
        tx = x1 + 4
        ty = y1 - 18 if y1 > 20 else y2 + 4
        self.canvas.create_rectangle(
            tx - 2, ty - 2, tx + len(lbl) * 7 + 2, ty + 16,
            fill='#003344', outline='', tag='selection')
        self.canvas.create_text(
            tx, ty,
            text=lbl, fill='#00D4FF',
            font=('Segoe UI', 10, 'bold'),
            anchor='nw', tag='selection')


# ---------------------------------------------------------------------------
# WindowPickerDialog
# ---------------------------------------------------------------------------

class WindowPickerDialog:
    """Zeigt alle sichtbaren Fenster zur Auswahl."""

    def __init__(self, parent):
        self.result = None   # (hwnd, title) oder None
        self.parent = parent

    def show(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title('Fenster auswählen')
        self.dialog.geometry('500x400')
        self.dialog.grab_set()
        self.dialog.attributes('-topmost', True)

        tk.Label(
            self.dialog,
            text='Wähle das Fenster aus, das aufgenommen werden soll:',
            font=('Segoe UI', 10)
        ).pack(padx=10, pady=8, anchor='w')

        frame = tk.Frame(self.dialog)
        frame.pack(fill='both', expand=True, padx=10, pady=4)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')

        self.listbox = tk.Listbox(
            frame,
            yscrollcommand=scrollbar.set,
            font=('Segoe UI', 10),
            selectmode='single')
        self.listbox.pack(fill='both', expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.windows = self._get_windows()
        for hwnd, title in self.windows:
            self.listbox.insert('end', title)

        btn_frame = tk.Frame(self.dialog)
        btn_frame.pack(fill='x', padx=10, pady=8)
        tk.Button(btn_frame, text='Aufnehmen',
                  command=self._on_ok,
                  bg='#0078D4', fg='white',
                  font=('Segoe UI', 10)
                  ).pack(side='right', padx=4)
        tk.Button(btn_frame, text='Abbrechen',
                  command=self._on_cancel,
                  font=('Segoe UI', 10)
                  ).pack(side='right', padx=4)

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
# CaptureEngine
# ---------------------------------------------------------------------------

class CaptureEngine:
    """Kapselt alle vier Capture-Modi."""

    # ------------------------------------------------------------------
    # Vollbild
    # ------------------------------------------------------------------
    def capture_fullscreen(self) -> Image.Image:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]    # alle Monitore
            raw = sct.grab(mon)
            return Image.frombytes('RGB', raw.size, raw.bgra, 'raw', 'BGRX')

    # ------------------------------------------------------------------
    # Fenster
    # ------------------------------------------------------------------
    def capture_window(self, hwnd: int) -> Image.Image:
        try:
            import win32gui
            import win32ui
            from ctypes import windll

            # Fenster in den Vordergrund
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                raise ValueError('Fenster hat ungültige Größe')

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(save_bitmap)

            windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)

            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1)

            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            return img

        except Exception:
            # Fallback: Region via mss
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

    # ------------------------------------------------------------------
    # Scrolling Capture
    # ------------------------------------------------------------------
    def capture_scrolling(
            self,
            region: tuple,
            scroll_pause: float = 0.5,
            max_scrolls: int = 30) -> Image.Image:
        """
        region: (x1, y1, x2, y2) des sichtbaren Viewports
        Gibt ein zusammengenähtes Bild zurück.
        """
        import mss
        import pyautogui

        x1, y1, x2, y2 = region
        mon = {'left': x1, 'top': y1,
               'width': x2 - x1, 'height': y2 - y1}
        cx = x1 + (x2 - x1) // 2
        cy = y1 + (y2 - y1) // 2

        strips: list[Image.Image] = []
        prev_strip: Image.Image | None = None
        scroll_offsets: list[int] = []

        for _ in range(max_scrolls + 1):
            time.sleep(0.1)
            with mss.mss() as sct:
                raw = sct.grab(mon)
                strip = Image.frombytes(
                    'RGB', raw.size, raw.bgra, 'raw', 'BGRX')

            if prev_strip is not None:
                offset = self._find_overlap(prev_strip, strip)
                if offset is None or offset == 0:
                    # Kein neuer Inhalt → Seite zuende
                    break
                scroll_offsets.append(offset)
            strips.append(strip)
            prev_strip = strip

            # Scrollen
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

    # ------------------------------------------------------------------
    # Hilfsmethoden Scrolling
    # ------------------------------------------------------------------
    def _find_overlap(
            self,
            prev: Image.Image,
            curr: Image.Image) -> int | None:
        """
        Gibt zurück, wie viele Pixel neuer Inhalt sichtbar wurde.
        Vergleicht den unteren Teil von prev mit dem oberen Teil von curr.
        """
        try:
            import numpy as np
        except ImportError:
            # Ohne numpy: feste Schätzung
            return prev.height // 2

        pa = np.array(prev.convert('L'), dtype=np.int32)
        ca = np.array(curr.convert('L'), dtype=np.int32)
        h = pa.shape[0]
        search = min(300, h // 2)

        best_offset = None
        best_score = float('inf')

        for candidate in range(5, search):
            diff = float(np.mean(
                np.abs(pa[h - candidate:h] - ca[0:candidate])))
            if diff < best_score:
                best_score = diff
                best_offset = candidate

        if best_score > 20:
            return None        # Keine saubere Überlappung gefunden
        return h - best_offset  # sichtbare neue Pixel

    def _stitch(
            self,
            strips: list[Image.Image],
            offsets: list[int]) -> Image.Image:
        """Strips zusammennähen."""
        w = strips[0].width
        visible_heights = offsets + [strips[-1].height]

        total_h = 0
        for i, (strip, vis) in enumerate(zip(strips, visible_heights)):
            if i < len(strips) - 1:
                total_h += vis
            else:
                total_h += strip.height

        canvas = Image.new('RGB', (w, total_h), 'white')
        y = 0
        for i, (strip, vis) in enumerate(zip(strips, visible_heights)):
            if i < len(strips) - 1:
                canvas.paste(strip.crop((0, 0, w, vis)), (0, y))
                y += vis
            else:
                canvas.paste(strip, (0, y))
        return canvas
