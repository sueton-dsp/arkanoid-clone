"""
editor.py  –  Annotierungseditor
"""

import io
import math
import tkinter as tk
from tkinter import filedialog, simpledialog, colorchooser, messagebox
from dataclasses import dataclass, field
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk
from history import HistoryManager


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class Annotation:
    kind: str              # 'arrow','line','rect','text','callout',
    #                        'highlight','blur','blackout'
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
    color: str = '#FF0000'
    width: int = 3
    text: str = ''
    font_size: int = 16
    # Callout-Schweif-Spitze (zweite Maus-Position)
    tail_x: int = 0
    tail_y: int = 0


# ---------------------------------------------------------------------------
# AnnotationEditor
# ---------------------------------------------------------------------------

class AnnotationEditor:
    """
    Haupt-Editorfenster.
    Zeigt das aufgenommene Bild und ermöglicht Annotierungen.
    """

    TOOLS = [
        ('arrow',     '→',   'Pfeil'),
        ('line',      '╱',   'Linie'),
        ('rect',      '□',   'Rechteck'),
        ('text',      'T',   'Text'),
        ('callout',   '💬',  'Callout'),
        ('highlight', '▓',   'Markierung'),
        ('blur',      '≋',   'Weichzeichner'),
        ('blackout',  '■',   'Schwärzung'),
    ]

    def __init__(self, parent: tk.Tk, image: Image.Image, app,
                 history: HistoryManager | None = None):
        self.parent = parent
        self.image = image.copy()
        self.app = app
        self.history = history or HistoryManager()

        self.annotations: list[Annotation] = []
        self.undo_stack: list[list] = []

        self.active_tool = 'arrow'
        self.tool_color = '#FF0000'
        self.tool_width = 3
        self.font_size = 16

        # Zeichnungs-Hilfsvariablen
        self._drawing = False
        self._drag_item = None      # aktuell gezogenes Canvas-Objekt
        self._drag_start = (0, 0)
        self._tmp_photo = None      # temp. PhotoImage-Referenz

        # Filmstreifen-Thumbnails (Referenzen für GC)
        self._thumb_photos: list[ImageTk.PhotoImage] = []

        # Aktuell geladener Verlaufseintrag (für Autosave)
        self._current_entry_id: str | None = None

        self.win: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self._base_photo: ImageTk.PhotoImage | None = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def load_image(self, image: Image.Image, entry_id: str | None = None):
        """
        Lädt ein neues Bild in den bestehenden Editor.
        Wird aufgerufen wenn ein neuer Screenshot gemacht wird
        während der Editor bereits offen ist.
        """
        self._autosave()          # Aktuellen Stand zuerst sichern
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
        """
        Speichert den aktuellen annotierten Stand zurück in den Verlauf.
        Wird aufgerufen bevor ein anderes Bild geladen wird.
        Nur aktiv wenn Annotierungen vorhanden und ein Eintrag bekannt ist.
        """
        if not self.annotations:
            return
        if not self._current_entry_id:
            return
        try:
            self._status_var.set('Autospeicherung …')
            composite = self._composite_image()
            self.history.update(self._current_entry_id, composite)
            self._refresh_filmstrip()
        except Exception:
            pass   # Autosave-Fehler nie den Workflow unterbrechen

    def show(self, entry_id: str | None = None):
        """Editor-Fenster öffnen."""
        self._current_entry_id = entry_id
        self.win = tk.Toplevel(self.parent)
        self.win.title('Screenshot-Editor')
        self.win.attributes('-topmost', False)

        # Fenstergröße = Bildgröße (max. 90% des Bildschirms)
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        iw, ih = self.image.size
        max_w = int(sw * 0.9)
        max_h = int(sh * 0.92)
        win_w = min(iw + 120, max_w)    # 120px für Toolbar
        win_h = min(ih + 200, max_h)    # 200px für Menü + Filmstreifen + Status
        self.win.geometry(f'{win_w}x{win_h}')

        self._build_menu()
        self._build_statusbar()   # side='bottom' → zuerst packen
        self._build_filmstrip()   # side='bottom' → vor Canvas packen!
        self._build_toolbar()     # side='left'
        self._build_canvas()      # side='left', expand=True → zuletzt!
        self._bind_shortcuts()
        self._redraw_canvas()

        self.win.protocol('WM_DELETE_WINDOW', self._on_close)

    # ------------------------------------------------------------------
    # GUI-Aufbau
    # ------------------------------------------------------------------

    # Helles Design – Farben
    BG_MAIN    = '#F0F2F5'   # Fensterhintergrund
    BG_TOOLBAR = '#FFFFFF'   # Toolbar
    BG_CANVAS  = '#D8DCE0'   # Canvas-Hintergrund
    BG_STRIP   = '#F0F2F5'   # Filmstreifen
    BG_CELL    = '#FFFFFF'   # Thumbnail-Zelle
    FG_MAIN    = '#1A1A2E'   # Haupttext
    FG_MUTED   = '#666680'   # Nebentext
    ACCENT     = '#0078D4'   # Akzentfarbe (Blau)
    ACCENT_HOV = '#005FA3'   # Hover
    BTN_SEL    = '#0078D4'   # Aktiver Button
    BTN_NORM   = '#E8EAF0'   # Normaler Button
    BTN_FG     = '#1A1A2E'
    DIVIDER    = '#C8CDD8'

    def _build_menu(self):
        menubar = tk.Menu(self.win, bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                          activebackground=self.ACCENT, activeforeground='white')

        file_menu = tk.Menu(menubar, tearoff=0,
                            bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                            activebackground=self.ACCENT, activeforeground='white')
        file_menu.add_command(label='Speichern  Ctrl+S',
                              command=self.save_to_file)
        file_menu.add_command(label='In Zwischenablage  Ctrl+C',
                              command=self.copy_to_clipboard)
        file_menu.add_separator()
        file_menu.add_command(label='Schließen', command=self._on_close)
        menubar.add_cascade(label='Datei', menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0,
                            bg=self.BG_TOOLBAR, fg=self.FG_MAIN,
                            activebackground=self.ACCENT, activeforeground='white')
        edit_menu.add_command(label='Rückgängig  Ctrl+Z', command=self._undo)
        menubar.add_cascade(label='Bearbeiten', menu=edit_menu)

        self.win.config(menu=menubar, bg=self.BG_MAIN)

    def _build_toolbar(self):
        """Horizontale Werkzeugleiste oben."""
        self.toolbar = tk.Frame(self.win, bg=self.BG_TOOLBAR,
                                relief='flat', bd=0,
                                highlightthickness=1,
                                highlightbackground=self.DIVIDER)
        self.toolbar.pack(side='top', fill='x')

        # ── Werkzeug-Buttons ──────────────────────────────────────────
        self._tool_buttons: dict[str, tk.Button] = {}
        for tool_id, symbol, label in self.TOOLS:
            btn = tk.Button(
                self.toolbar,
                text=f'{symbol}  {label}',
                font=('Segoe UI', 9),
                bg=self.BTN_NORM, fg=self.BTN_FG,
                activebackground=self.ACCENT,
                activeforeground='white',
                relief='flat',
                padx=8, pady=5,
                cursor='hand2',
                command=lambda t=tool_id: self._select_tool(t)
            )
            btn.pack(side='left', padx=2, pady=4)
            self._tool_buttons[tool_id] = btn

        # ── Trennlinie ────────────────────────────────────────────────
        tk.Frame(self.toolbar, bg=self.DIVIDER,
                 width=1).pack(side='left', fill='y', padx=6, pady=4)

        # ── Farb-Button ───────────────────────────────────────────────
        tk.Label(self.toolbar, text='Farbe:',
                 bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 9)).pack(side='left', padx=(4, 2))
        self._color_btn = tk.Button(
            self.toolbar,
            text='  ██  ',
            font=('Segoe UI', 9),
            bg=self.tool_color,
            fg=self.tool_color,
            relief='flat',
            padx=4, pady=5,
            cursor='hand2',
            command=self._pick_color)
        self._color_btn.pack(side='left', padx=2, pady=4)

        # ── Trennlinie ────────────────────────────────────────────────
        tk.Frame(self.toolbar, bg=self.DIVIDER,
                 width=1).pack(side='left', fill='y', padx=6, pady=4)

        # ── Strichbreite ──────────────────────────────────────────────
        tk.Label(self.toolbar, text='Breite:',
                 bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 9)).pack(side='left', padx=(4, 2))
        self._width_var = tk.IntVar(value=self.tool_width)
        tk.Spinbox(
            self.toolbar,
            from_=1, to=20,
            textvariable=self._width_var,
            width=3,
            font=('Segoe UI', 9),
            relief='flat',
            bg=self.BTN_NORM, fg=self.FG_MAIN,
            buttonbackground=self.BTN_NORM,
            command=self._update_width
        ).pack(side='left', padx=2, pady=4)

        # ── Trennlinie ────────────────────────────────────────────────
        tk.Frame(self.toolbar, bg=self.DIVIDER,
                 width=1).pack(side='left', fill='y', padx=6, pady=4)

        # ── Schriftgröße ──────────────────────────────────────────────
        tk.Label(self.toolbar, text='Schrift:',
                 bg=self.BG_TOOLBAR, fg=self.FG_MUTED,
                 font=('Segoe UI', 9)).pack(side='left', padx=(4, 2))
        self._font_var = tk.IntVar(value=self.font_size)
        tk.Spinbox(
            self.toolbar,
            from_=8, to=72,
            textvariable=self._font_var,
            width=3,
            font=('Segoe UI', 9),
            relief='flat',
            bg=self.BTN_NORM, fg=self.FG_MAIN,
            buttonbackground=self.BTN_NORM,
            command=self._update_font
        ).pack(side='left', padx=2, pady=4)

        # ── Undo-Button rechts ────────────────────────────────────────
        tk.Button(
            self.toolbar,
            text='↩  Rückgängig',
            font=('Segoe UI', 9),
            bg=self.BTN_NORM, fg=self.BTN_FG,
            activebackground=self.ACCENT,
            activeforeground='white',
            relief='flat',
            padx=8, pady=5,
            cursor='hand2',
            command=self._undo
        ).pack(side='right', padx=2, pady=4)

        tk.Button(
            self.toolbar,
            text='📋  Kopieren',
            font=('Segoe UI', 9),
            bg=self.BTN_NORM, fg=self.BTN_FG,
            activebackground=self.ACCENT,
            activeforeground='white',
            relief='flat',
            padx=8, pady=5,
            cursor='hand2',
            command=self.copy_to_clipboard
        ).pack(side='right', padx=2, pady=4)

        tk.Button(
            self.toolbar,
            text='💾  Speichern',
            font=('Segoe UI', 9),
            bg=self.ACCENT, fg='white',
            activebackground=self.ACCENT_HOV,
            activeforeground='white',
            relief='flat',
            padx=8, pady=5,
            cursor='hand2',
            command=self.save_to_file
        ).pack(side='right', padx=2, pady=4)

        self._select_tool('arrow')

    def _build_canvas(self):
        """Zentraler Scroll-Canvas."""
        frame = tk.Frame(self.win, bg=self.BG_MAIN)
        frame.pack(side='left', fill='both', expand=True)

        hbar = tk.Scrollbar(frame, orient='horizontal')
        hbar.pack(side='bottom', fill='x')
        vbar = tk.Scrollbar(frame, orient='vertical')
        vbar.pack(side='right', fill='y')

        self.canvas = tk.Canvas(
            frame,
            bg=self.BG_CANVAS,
            xscrollcommand=hbar.set,
            yscrollcommand=vbar.set,
            cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)

        hbar.config(command=self.canvas.xview)
        vbar.config(command=self.canvas.yview)

        iw, ih = self.image.size
        self.canvas.config(scrollregion=(0, 0, iw, ih))

        self.canvas.bind('<ButtonPress-1>', self._on_mouse_down)
        self.canvas.bind('<B1-Motion>', self._on_mouse_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_mouse_up)

    def _build_filmstrip(self):
        """Filmstreifen-Panel am unteren Rand des Editors."""
        STRIP_H = 120

        # Trennlinie oben
        tk.Frame(self.win, bg=self.DIVIDER, height=1).pack(
            side='bottom', fill='x')

        # Äußerer Rahmen
        strip_frame = tk.Frame(self.win, bg=self.BG_STRIP,
                               height=STRIP_H, relief='flat')
        strip_frame.pack(side='bottom', fill='x')
        strip_frame.pack_propagate(False)

        # Titel-Label
        tk.Label(strip_frame, text='VERLAUF',
                 bg=self.BG_STRIP, fg=self.FG_MUTED,
                 font=('Segoe UI', 8, 'bold')).pack(
                     side='left', padx=(10, 4), pady=4)

        tk.Frame(strip_frame, bg=self.DIVIDER,
                 width=1).pack(side='left', fill='y', pady=6)

        # Scrollbarer Bereich für Thumbnails
        outer = tk.Frame(strip_frame, bg=self.BG_STRIP)
        outer.pack(side='left', fill='both', expand=True)

        hbar = tk.Scrollbar(outer, orient='horizontal')
        hbar.pack(side='bottom', fill='x')

        self._strip_canvas = tk.Canvas(
            outer,
            bg=self.BG_STRIP,
            height=STRIP_H - 20,
            xscrollcommand=hbar.set,
            highlightthickness=0)
        self._strip_canvas.pack(side='top', fill='both', expand=True)
        hbar.config(command=self._strip_canvas.xview)

        # Innerer Frame im Canvas für Thumbnails
        self._strip_inner = tk.Frame(self._strip_canvas, bg=self.BG_STRIP)
        self._strip_canvas.create_window(
            0, 0, anchor='nw', window=self._strip_inner)
        self._strip_inner.bind(
            '<Configure>',
            lambda e: self._strip_canvas.config(
                scrollregion=self._strip_canvas.bbox('all')))

        self._refresh_filmstrip()

    def _refresh_filmstrip(self):
        """Filmstreifen neu aufbauen (nach add/remove)."""
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
        """Erstellt ein einzelnes Thumbnail-Widget im Filmstreifen."""
        thumb_img = self.history.load_thumbnail(entry['id'])
        is_active = (entry['id'] == self._current_entry_id)

        cell = tk.Frame(self._strip_inner,
                        bg=self.ACCENT if is_active else self.BG_CELL,
                        relief='flat', bd=1,
                        highlightthickness=2,
                        highlightbackground=self.ACCENT if is_active else self.DIVIDER)
        cell.pack(side='left', padx=5, pady=5)

        # Thumbnail
        if thumb_img:
            photo = ImageTk.PhotoImage(thumb_img)
            self._thumb_photos.append(photo)
            lbl = tk.Label(cell, image=photo,
                           bg=self.ACCENT if is_active else self.BG_CELL,
                           cursor='hand2')
            lbl.pack(padx=2, pady=(3, 0))
            lbl.bind('<Button-1>',
                     lambda e, eid=entry['id']: self._load_from_history(eid))
            lbl.bind('<Enter>',
                     lambda e, c=cell: c.config(
                         highlightbackground=self.ACCENT))
            lbl.bind('<Leave>',
                     lambda e, c=cell, eid=entry['id']: c.config(
                         highlightbackground=self.ACCENT
                         if eid == self._current_entry_id else self.DIVIDER))
        else:
            tk.Label(cell, text='?', bg=self.BG_CELL, fg=self.FG_MUTED,
                     width=14, height=5).pack()

        # Zeitstempel
        tk.Label(cell,
                 text=entry.get('timestamp_display', '')[-8:],
                 bg=self.ACCENT if is_active else self.BG_CELL,
                 fg='white' if is_active else self.FG_MUTED,
                 font=('Segoe UI', 7)).pack()

        # Löschen-Button
        tk.Button(cell, text='✕',
                  font=('Segoe UI', 7),
                  bg=self.BTN_NORM, fg=self.FG_MUTED,
                  activebackground='#CC0000',
                  activeforeground='white',
                  relief='flat', padx=2, pady=0,
                  cursor='hand2',
                  command=lambda eid=entry['id']: self._delete_history_entry(eid)
                  ).pack(fill='x', padx=2, pady=(0, 3))

    def _load_from_history(self, entry_id: str):
        """Lädt einen Screenshot aus dem Verlauf in den Editor."""
        img = self.history.load_image(entry_id)
        if img is None:
            messagebox.showwarning('Verlauf',
                                   'Bild nicht mehr verfügbar.',
                                   parent=self.win)
            return
        # Aktuellen Stand autospeichern bevor gewechselt wird
        self._autosave()
        # Annotierungen zurücksetzen und neues Bild laden
        self._current_entry_id = entry_id
        self.undo_stack.clear()
        self.annotations.clear()
        self.image = img
        self._redraw_canvas()
        self._status_var.set('Bild aus Verlauf geladen')

    def _delete_history_entry(self, entry_id: str):
        """Entfernt einen Eintrag aus dem Verlauf."""
        self.history.remove(entry_id)
        self._refresh_filmstrip()
        self._status_var.set('Eintrag aus Verlauf gelöscht')

    def _build_statusbar(self):
        self._status_var = tk.StringVar(value='Bereit')
        bar = tk.Label(self.win, textvariable=self._status_var,
                       anchor='w', bg=self.DIVIDER, fg=self.FG_MUTED,
                       font=('Segoe UI', 9), padx=8, pady=3)
        bar.pack(side='bottom', fill='x')

    def _bind_shortcuts(self):
        self.win.bind('<Control-z>', lambda e: self._undo())
        self.win.bind('<Control-s>', lambda e: self.save_to_file())
        self.win.bind('<Control-c>', lambda e: self.copy_to_clipboard())
        for i, (tool_id, _, _) in enumerate(self.TOOLS):
            key = str(i + 1)
            self.win.bind(key, lambda e, t=tool_id: self._select_tool(t))

    # ------------------------------------------------------------------
    # Tool-Steuerung
    # ------------------------------------------------------------------

    def _select_tool(self, tool_id: str):
        self.active_tool = tool_id
        for tid, btn in self._tool_buttons.items():
            btn.config(
                bg=self.BTN_SEL if tid == tool_id else self.BTN_NORM,
                fg='white' if tid == tool_id else self.BTN_FG)
        self._update_status()

    def _pick_color(self):
        c = colorchooser.askcolor(color=self.tool_color,
                                  parent=self.win,
                                  title='Farbe wählen')
        if c and c[1]:
            self.tool_color = c[1]
            self._color_btn.config(bg=self.tool_color, fg=self.tool_color)

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
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        return int(x), int(y)

    def _on_mouse_down(self, event):
        self._drawing = True
        x, y = self._canvas_coords(event)
        self._drag_start = (x, y)
        self._drag_item = None

        if self.active_tool == 'text':
            self._handle_text(x, y)
            self._drawing = False
        elif self.active_tool == 'callout':
            self._handle_callout_start(x, y)

    def _on_mouse_drag(self, event):
        if not self._drawing:
            return
        x, y = self._canvas_coords(event)
        x0, y0 = self._drag_start
        self._draw_preview(x0, y0, x, y)

    def _on_mouse_up(self, event):
        if not self._drawing:
            return
        self._drawing = False
        x, y = self._canvas_coords(event)
        x0, y0 = self._drag_start

        if abs(x - x0) < 2 and abs(y - y0) < 2:
            self._clear_preview()
            return

        if self.active_tool == 'callout':
            return   # Callout wird separat behandelt

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
        c = self.tool_color
        w = self.tool_width

        if tool == 'arrow':
            self.canvas.create_line(
                x0, y0, x1, y1,
                fill=c, width=w,
                arrow=tk.LAST, arrowshape=(16, 20, 6),
                tag='preview')
        elif tool == 'line':
            self.canvas.create_line(
                x0, y0, x1, y1,
                fill=c, width=w, tag='preview')
        elif tool == 'rect':
            self.canvas.create_rectangle(
                x0, y0, x1, y1,
                outline=c, width=w, tag='preview')
        elif tool in ('highlight', 'blur', 'blackout'):
            fill = c if tool == 'highlight' else (
                'gray' if tool == 'blur' else 'black')
            stip = 'gray50' if tool == 'highlight' else ''
            self.canvas.create_rectangle(
                x0, y0, x1, y1,
                outline=c if tool == 'highlight' else fill,
                fill=fill,
                stipple=stip,
                width=1, tag='preview')

    def _clear_preview(self):
        self.canvas.delete('preview')

    # ------------------------------------------------------------------
    # Annotierung erstellen
    # ------------------------------------------------------------------

    def _make_annotation(self, x0, y0, x1, y1) -> Annotation | None:
        tool = self.active_tool
        if tool not in ('arrow', 'line', 'rect',
                        'highlight', 'blur', 'blackout'):
            return None
        return Annotation(
            kind=tool,
            x1=x0, y1=y0, x2=x1, y2=y1,
            color=self.tool_color,
            width=self.tool_width)

    def _handle_text(self, x, y):
        """Inline-Texteingabe via Dialog."""
        text = simpledialog.askstring(
            'Text eingeben', 'Beschriftung:',
            parent=self.win)
        if text:
            ann = Annotation(
                kind='text',
                x1=x, y1=y, x2=x, y2=y,
                color=self.tool_color,
                font_size=self.font_size,
                text=text)
            self._commit(ann)

    def _handle_callout_start(self, x, y):
        """Erster Klick: Textbox-Position. Zweiter Klick: Schweif-Spitze."""
        text = simpledialog.askstring(
            'Callout-Text', 'Beschriftung:',
            parent=self.win)
        if not text:
            self._drawing = False
            return

        self._callout_text = text
        self._callout_x = x
        self._callout_y = y
        self._status_var.set(
            'Schweif-Spitze setzen: Klicke auf das Ziel des Callouts')

        # Warte auf zweiten Klick
        self.canvas.bind('<ButtonPress-1>', self._handle_callout_tip)

    def _handle_callout_tip(self, event):
        """Zweiter Klick: Schweif-Spitze."""
        self.canvas.bind('<ButtonPress-1>', self._on_mouse_down)
        x, y = self._canvas_coords(event)
        ann = Annotation(
            kind='callout',
            x1=self._callout_x, y1=self._callout_y,
            x2=self._callout_x + 120, y2=self._callout_y + 40,
            color=self.tool_color,
            width=self.tool_width,
            font_size=self.font_size,
            text=self._callout_text,
            tail_x=x, tail_y=y)
        self._commit(ann)
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
        """Basisebene + alle Annotierungen neu zeichnen."""
        self.canvas.delete('annotation')
        self.canvas.delete('base')

        self._base_photo = ImageTk.PhotoImage(self.image)
        self.canvas.create_image(
            0, 0, anchor='nw',
            image=self._base_photo, tag='base')

        iw, ih = self.image.size
        self.canvas.config(scrollregion=(0, 0, iw, ih))

        for ann in self.annotations:
            self._draw_annotation_on_canvas(ann)

    def _draw_annotation_on_canvas(self, ann: Annotation):
        c = ann.color
        w = ann.width
        tag = 'annotation'

        if ann.kind == 'arrow':
            self.canvas.create_line(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, width=w,
                arrow=tk.LAST, arrowshape=(16, 20, 6),
                tag=tag)

        elif ann.kind == 'line':
            self.canvas.create_line(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, width=w, tag=tag)

        elif ann.kind == 'rect':
            self.canvas.create_rectangle(
                ann.x1, ann.y1, ann.x2, ann.y2,
                outline=c, width=w, tag=tag)

        elif ann.kind == 'text':
            self.canvas.create_text(
                ann.x1, ann.y1,
                text=ann.text, fill=c,
                font=('Segoe UI', ann.font_size, 'bold'),
                anchor='nw', tag=tag)

        elif ann.kind == 'callout':
            # Hintergrundrechteck
            self.canvas.create_rectangle(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill='white', outline=c, width=w, tag=tag)
            # Schweif
            mx = (ann.x1 + ann.x2) // 2
            self.canvas.create_polygon(
                mx - 8, ann.y2,
                mx + 8, ann.y2,
                ann.tail_x, ann.tail_y,
                fill='white', outline=c, width=w, tag=tag)
            # Text
            self.canvas.create_text(
                ann.x1 + 6, ann.y1 + 6,
                text=ann.text, fill=c,
                font=('Segoe UI', ann.font_size),
                anchor='nw', tag=tag)

        elif ann.kind == 'highlight':
            self.canvas.create_rectangle(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill=c, stipple='gray50',
                outline='', tag=tag)

        elif ann.kind == 'blur':
            # Vorschau: grau gestippled
            self.canvas.create_rectangle(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill='gray', stipple='gray50',
                outline='gray', tag=tag)

        elif ann.kind == 'blackout':
            self.canvas.create_rectangle(
                ann.x1, ann.y1, ann.x2, ann.y2,
                fill='black', outline='black', tag=tag)

    # ------------------------------------------------------------------
    # PIL-Composite (für Speichern)
    # ------------------------------------------------------------------

    def _composite_image(self) -> Image.Image:
        """Bild + alle Annotierungen als PIL-Image rendern."""
        img = self.image.copy().convert('RGBA')

        for ann in self.annotations:
            img = self._apply_annotation(img, ann)

        return img.convert('RGB')

    def _apply_annotation(self, img: Image.Image,
                          ann: Annotation) -> Image.Image:
        draw = ImageDraw.Draw(img, 'RGBA')

        def color_rgba(hex_color, alpha=255):
            h = hex_color.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return r, g, b, alpha

        c = color_rgba(ann.color)
        w = ann.width

        if ann.kind == 'arrow':
            draw.line([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                      fill=c, width=w)
            # Pfeilkopf
            angle = math.atan2(ann.y2 - ann.y1, ann.x2 - ann.x1)
            size = max(12, w * 4)
            for a in [angle + 2.5, angle - 2.5]:
                px = ann.x2 - size * math.cos(a)
                py = ann.y2 - size * math.sin(a)
                draw.line([(ann.x2, ann.y2), (int(px), int(py))],
                          fill=c, width=w)

        elif ann.kind == 'line':
            draw.line([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                      fill=c, width=w)

        elif ann.kind == 'rect':
            draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                           outline=c, width=w)

        elif ann.kind == 'text':
            try:
                font = ImageFont.truetype('segoeui.ttf', ann.font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((ann.x1, ann.y1), ann.text,
                      fill=c, font=font)

        elif ann.kind == 'callout':
            bg = (255, 255, 255, 230)
            draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                           fill=bg, outline=c, width=w)
            mx = (ann.x1 + ann.x2) // 2
            draw.polygon(
                [(mx - 8, ann.y2), (mx + 8, ann.y2),
                 (ann.tail_x, ann.tail_y)],
                fill=bg, outline=c)
            try:
                font = ImageFont.truetype('segoeui.ttf', ann.font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((ann.x1 + 6, ann.y1 + 6), ann.text,
                      fill=c, font=font)

        elif ann.kind == 'highlight':
            overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            ov_draw = ImageDraw.Draw(overlay)
            hc = color_rgba(ann.color, 100)
            ov_draw.rectangle([(ann.x1, ann.y1), (ann.x2, ann.y2)],
                               fill=hc)
            img = Image.alpha_composite(img, overlay)

        elif ann.kind == 'blur':
            x1, y1 = min(ann.x1, ann.x2), min(ann.y1, ann.y2)
            x2, y2 = max(ann.x1, ann.x2), max(ann.y1, ann.y2)
            if x2 > x1 and y2 > y1:
                region = img.crop((x1, y1, x2, y2))
                blurred = region.filter(
                    ImageFilter.GaussianBlur(radius=15))
                img.paste(blurred, (x1, y1))

        elif ann.kind == 'blackout':
            x1, y1 = min(ann.x1, ann.x2), min(ann.y1, ann.y2)
            x2, y2 = max(ann.x1, ann.x2), max(ann.y1, ann.y2)
            draw.rectangle([(x1, y1), (x2, y2)],
                           fill=(0, 0, 0, 255))

        del draw
        return img

    # ------------------------------------------------------------------
    # Speichern / Clipboard
    # ------------------------------------------------------------------

    def save_to_file(self):
        default = datetime.now().strftime('screenshot_%Y%m%d_%H%M%S.png')
        path = filedialog.asksaveasfilename(
            parent=self.win,
            defaultextension='.png',
            initialfile=default,
            filetypes=[
                ('PNG-Bild', '*.png'),
                ('JPEG-Bild', '*.jpg'),
                ('Alle Dateien', '*.*')
            ])
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
            data = output.getvalue()[14:]   # BMP-Dateiheader entfernen
            output.close()
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            self._status_var.set('In Zwischenablage kopiert')
        except ImportError:
            # Fallback: via tkinter (nur intern nutzbar)
            messagebox.showinfo(
                'Zwischenablage',
                'pywin32 nicht verfügbar.\n'
                'Bitte speichere das Bild als Datei.',
                parent=self.win)

    # ------------------------------------------------------------------
    def _on_close(self):
        self.win.destroy()
        self.app.on_editor_closed()
