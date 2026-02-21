"""
screenshot_tool.py  –  Snagit-ähnliches Screenshot-Tool
========================================================
Start:  python screenshot_tool.py

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
import tkinter as tk
from tkinter import messagebox

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


# ---------------------------------------------------------------------------
# Hauptanwendung
# ---------------------------------------------------------------------------

class ScreenshotApp:
    """
    Haupt-Controller.
    Zeigt ein kleines Steuerungsfenster und registriert globale Hotkeys.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Screenshot-Tool')
        self.root.resizable(False, False)
        self._editor_open = False
        self._capturing = False       # verhindert nur doppeltes Capture, nicht Editor
        self._active_editor = None    # Referenz auf den aktuell offenen Editor

        from capture import CaptureEngine
        from history import HistoryManager
        self.engine = CaptureEngine()
        self.history = HistoryManager()

        self._build_ui()
        self._register_hotkeys()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.root.configure(bg='#2D2D2D')
        self.root.geometry('260x310')

        # Titel
        tk.Label(
            self.root,
            text='📷  Screenshot-Tool',
            bg='#2D2D2D', fg='white',
            font=('Segoe UI', 12, 'bold')
        ).pack(pady=(16, 8))

        # Buttons
        buttons = [
            ('Region auswählen\n[Print Screen]',
             self.start_region),
            ('Vollbild\n[Ctrl+Shift+F]',
             self.start_fullscreen),
            ('Fenster auswählen\n[Ctrl+Shift+W]',
             self.start_window),
            ('Scrolling Capture\n[Ctrl+Shift+S]',
             self.start_scrolling),
        ]

        for label, cmd in buttons:
            tk.Button(
                self.root,
                text=label,
                font=('Segoe UI', 9),
                bg='#3C3C3C', fg='white',
                activebackground='#0078D4',
                relief='flat',
                width=24,
                command=cmd
            ).pack(padx=12, pady=4)

        # Status
        self._status_var = tk.StringVar(value='Bereit')
        tk.Label(
            self.root,
            textvariable=self._status_var,
            bg='#2D2D2D', fg='#AAAAAA',
            font=('Segoe UI', 8),
            wraplength=240
        ).pack(pady=(8, 4))

        # Schließen
        tk.Button(
            self.root,
            text='Beenden',
            font=('Segoe UI', 9),
            bg='#5C2020', fg='white',
            activebackground='#8B0000',
            relief='flat',
            width=24,
            command=self.root.quit
        ).pack(padx=12, pady=(4, 16))

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
        from capture import RegionOverlay
        overlay = RegionOverlay(self.root, self._on_captured)
        overlay.show()

    # ------------------------------------------------------------------
    def start_fullscreen(self):
        if self._capturing:
            return
        self._capturing = True
        self._set_status('Vollbild wird aufgenommen …')
        self.root.withdraw()
        self.root.after(300, self._do_fullscreen)

    def _do_fullscreen(self):
        try:
            img = self.engine.capture_fullscreen()
            self._on_captured(img)
        except Exception as e:
            self._capturing = False
            self._show_error(f'Vollbild-Fehler: {e}')

    # ------------------------------------------------------------------
    def start_window(self):
        if self._capturing:
            return
        self._capturing = True
        from capture import WindowPickerDialog
        picker = WindowPickerDialog(self.root)
        result = picker.show()
        if result is None:
            self._capturing = False
            return
        hwnd, title = result
        self._set_status(f'Fenster wird aufgenommen: {title}')
        self.root.withdraw()
        self.root.after(300, lambda: self._do_window(hwnd))

    def _do_window(self, hwnd):
        try:
            img = self.engine.capture_window(hwnd)
            self._on_captured(img)
        except Exception as e:
            self._capturing = False
            self._show_error(f'Fenster-Fehler: {e}')

    # ------------------------------------------------------------------
    def start_scrolling(self):
        if self._capturing:
            return
        self._capturing = True
        self._set_status('Region für Scrolling auswählen …')
        self.root.withdraw()
        self.root.after(200, self._do_scrolling_pick)

    def _do_scrolling_pick(self):
        from capture import RegionOverlay

        def on_region_selected(img):
            # Wir brauchen nur die Koordinaten, nicht das Bild direkt
            # Deshalb fragen wir die Engine direkt
            pass

        # Modifizierter Flow: Region wählen → Koordinaten merken → scrollen
        overlay = _ScrollingRegionOverlay(self.root, self._on_scroll_region)
        overlay.show()

    def _on_scroll_region(self, region: tuple):
        self._set_status('Scrolling Capture läuft … bitte warten')
        self.root.after(100, lambda: self._do_scrolling(region))

    def _do_scrolling(self, region):
        try:
            img = self.engine.capture_scrolling(region)
            self._on_captured(img)
        except Exception as e:
            self._capturing = False
            self._show_error(f'Scrolling-Fehler: {e}')

    # ------------------------------------------------------------------
    # Nach erfolgreichem Capture
    # ------------------------------------------------------------------

    def _on_captured(self, image):
        self._capturing = False   # Sperre aufheben → nächster Screenshot möglich
        self.root.deiconify()
        self._set_status('Bereit')

        # Screenshot automatisch in Verlauf speichern
        entry = self.history.add(image)
        entry_id = entry['id']

        if self._active_editor and self._active_editor.win and \
                self._active_editor.win.winfo_exists():
            # Bestehenden Editor aktualisieren statt neues Fenster
            self._active_editor.load_image(image, entry_id=entry_id)
        else:
            # Neuen Editor öffnen
            from editor import AnnotationEditor
            self._active_editor = AnnotationEditor(
                self.root, image, self, self.history)
            self._active_editor.show(entry_id=entry_id)

    def on_editor_closed(self):
        self._active_editor = None
        self._set_status('Bereit')

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _set_status(self, msg: str):
        self._status_var.set(msg)
        self.root.update_idletasks()

    def _show_error(self, msg: str):
        self.root.deiconify()
        self._set_status('Fehler')
        messagebox.showerror('Fehler', msg, parent=self.root)

    # ------------------------------------------------------------------
    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Spezielles Overlay für Scrolling (gibt Koordinaten zurück, kein Bild)
# ---------------------------------------------------------------------------

class _ScrollingRegionOverlay:
    """Wie RegionOverlay, gibt aber die Bildschirmkoordinaten zurück."""

    def __init__(self, root, callback):
        self.root = root
        self.callback = callback
        self._start_x = self._start_y = 0
        self._cur_x = self._cur_y = 0

    def show(self):
        import mss
        from PIL import ImageTk, Image

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
        bg_dark = self.background.copy()
        r, g, b = bg_dark.split()
        bg_dark = Image.merge('RGB', tuple(
            c.point(lambda p: int(p * 0.5)) for c in (r, g, b)))
        self._bg_photo = ImageTk.PhotoImage(bg_dark)
        self.canvas.create_image(0, 0, anchor='nw',
                                 image=self._bg_photo)

        sw = self.win.winfo_screenwidth()
        self.canvas.create_text(
            sw // 2, 30,
            text='Scroll-Bereich auswählen (sichtbares Fenster)  |  ESC = Abbrechen',
            fill='#FFDD00',
            font=('Segoe UI', 13))

        self.canvas.bind('<ButtonPress-1>', self._on_down)
        self.canvas.bind('<B1-Motion>', self._on_drag)
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
        from PIL import ImageTk
        self.canvas.delete('sel')
        x1, y1, x2, y2 = self._rect()
        if x2 == x1 or y2 == y1:
            return
        region = self.background.crop((x1, y1, x2, y2))
        self._sel_photo = ImageTk.PhotoImage(region)
        self.canvas.create_image(x1, y1, anchor='nw',
                                 image=self._sel_photo, tag='sel')
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline='#FFDD00', width=2, tag='sel')
        lbl = f'{x2-x1} × {y2-y1} px'
        self.canvas.create_text(
            x1 + 4, y1 - 18 if y1 > 20 else y2 + 4,
            text=lbl, fill='#FFDD00',
            font=('Segoe UI', 10, 'bold'),
            anchor='nw', tag='sel')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if not check_dependencies():
        sys.exit(1)

    app = ScreenshotApp()
    app.run()
