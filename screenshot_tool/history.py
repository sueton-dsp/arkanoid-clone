"""
history.py  –  Screenshot-Verlauf Verwaltung
Speichert bis zu 25 Screenshots auf der Festplatte und stellt
Thumbnails für den Filmstreifen bereit.
"""

import json
import os
import shutil
from datetime import datetime
from PIL import Image

MAX_ENTRIES = 25
THUMB_W = 120
THUMB_H = 80


class HistoryManager:
    """
    Verwaltet den Screenshot-Verlauf.

    Speicherstruktur:
        <history_dir>/
            index.json          ← Metadaten (Zeitstempel, Dateinamen)
            img_001.png
            img_002.png
            ...
    """

    def __init__(self, history_dir: str | None = None):
        if history_dir is None:
            # Standard: neben der screenshot_tool.py
            base = os.path.dirname(os.path.abspath(__file__))
            history_dir = os.path.join(base, 'history')

        self.history_dir = history_dir
        self.index_path = os.path.join(history_dir, 'index.json')
        self.entries: list[dict] = []   # [{id, filename, timestamp, thumb_filename}]

        os.makedirs(history_dir, exist_ok=True)
        self._load_index()

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def add(self, image: Image.Image) -> dict:
        """
        Fügt einen Screenshot zum Verlauf hinzu.
        Gibt den neuen Eintrag zurück.
        """
        now = datetime.now()
        entry_id = now.strftime('%Y%m%d_%H%M%S_%f')

        # Vollbild speichern
        img_filename = f'img_{entry_id}.png'
        img_path = os.path.join(self.history_dir, img_filename)
        image.save(img_path)

        # Thumbnail erstellen
        thumb = image.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
        thumb_filename = f'thumb_{entry_id}.png'
        thumb_path = os.path.join(self.history_dir, thumb_filename)
        thumb.save(thumb_path)

        entry = {
            'id': entry_id,
            'filename': img_filename,
            'thumb_filename': thumb_filename,
            'timestamp': now.isoformat(),
            'timestamp_display': now.strftime('%d.%m.%Y %H:%M:%S'),
        }

        self.entries.insert(0, entry)   # neueste zuerst

        # Max. 25 Einträge behalten
        while len(self.entries) > MAX_ENTRIES:
            self._remove_entry(self.entries[-1])
            self.entries.pop()

        self._save_index()
        return entry

    def update(self, entry_id: str, image: Image.Image):
        """
        Überschreibt das gespeicherte Bild + Thumbnail eines Eintrags.
        Kein neuer Eintrag – der bestehende Eintrag wird aktualisiert.
        """
        entry = self._find(entry_id)
        if not entry:
            return
        img_path = os.path.join(self.history_dir, entry['filename'])
        image.save(img_path)
        thumb = image.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
        thumb_path = os.path.join(self.history_dir, entry['thumb_filename'])
        thumb.save(thumb_path)

    def remove(self, entry_id: str):
        """Entfernt einen Eintrag aus dem Verlauf."""
        entry = self._find(entry_id)
        if entry:
            self._remove_entry(entry)
            self.entries = [e for e in self.entries if e['id'] != entry_id]
            self._save_index()

    def load_image(self, entry_id: str) -> Image.Image | None:
        """Lädt das Vollbild eines Eintrags."""
        entry = self._find(entry_id)
        if not entry:
            return None
        path = os.path.join(self.history_dir, entry['filename'])
        if os.path.exists(path):
            return Image.open(path).copy()
        return None

    def load_thumbnail(self, entry_id: str) -> Image.Image | None:
        """Lädt das Thumbnail eines Eintrags."""
        entry = self._find(entry_id)
        if not entry:
            return None
        path = os.path.join(self.history_dir, entry['thumb_filename'])
        if os.path.exists(path):
            return Image.open(path).copy()
        return None

    def get_entries(self) -> list[dict]:
        """Gibt alle Einträge zurück (neueste zuerst)."""
        return list(self.entries)

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _find(self, entry_id: str) -> dict | None:
        for e in self.entries:
            if e['id'] == entry_id:
                return e
        return None

    def _remove_entry(self, entry: dict):
        """Löscht die Dateien eines Eintrags."""
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
                # Nur Einträge behalten, deren Dateien noch existieren
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
