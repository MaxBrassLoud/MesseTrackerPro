"""Wiederverwendbare UI-Widgets."""
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QSizePolicy, QShortcut)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt


class FullSizeImageDialog(QDialog):
    """Vollbild-Dialog für Visitenkarten.

    - cards: Liste von dicts mit mind. 'id' und 'image_path'
    - start_index: Index in cards, mit dem begonnen wird
    - Pfeiltasten ← / → zum Blättern (nur wenn mehrere Karten)
    - Esc zum Schließen
    - Klick aufs Bild: zwischen 'anpassen' und 'Originalgröße' wechseln
    """

    def __init__(self, parent, cards, start_index=0):
        super().__init__(parent)
        self.setWindowTitle("Visitenkarte – Großansicht")
        self.cards = list(cards)
        self.index = max(0, min(start_index, len(self.cards) - 1))

        screen = parent.window().screen() if parent else None
        if screen:
            geo = screen.availableGeometry()
            self.resize(int(geo.width() * 0.85), int(geo.height() * 0.85))
        else:
            self.resize(1000, 800)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("padding:4px;font-size:10pt;")
        header.addWidget(self.info_label, 1)

        self.btn_prev = QPushButton("◀ Vorherige")
        self.btn_prev.setObjectName("Ghost")
        self.btn_prev.clicked.connect(self.prev_card)
        header.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Nächste ▶")
        self.btn_next.setObjectName("Ghost")
        self.btn_next.clicked.connect(self.next_card)
        header.addWidget(self.btn_next)
        v.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background:#000;border:1px solid #333;")
        self.scroll.setAlignment(Qt.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background:#000;")
        self.image_label.setSizePolicy(QSizePolicy.Ignored,
                                       QSizePolicy.Ignored)
        self.scroll.setWidget(self.image_label)
        v.addWidget(self.scroll, 1)

        footer = QLabel("← / → zum Blättern · Esc zum Schließen · "
                        "Bild anklicken zum Ein-/Auspassen")
        footer.setStyleSheet("color:#888;font-size:9pt;padding:2px;")
        footer.setAlignment(Qt.AlignCenter)
        v.addWidget(footer)

        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_card)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_card)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)

        self.fit_mode = True
        self.image_label.mousePressEvent = self._toggle_fit

        self._render()

    def _render(self):
        if not self.cards:
            self.info_label.setText("Keine Karten vorhanden.")
            self.image_label.setText("Kein Bild")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        card = self.cards[self.index]
        path = card.get("image_path") or ""
        self.info_label.setText(
            f"Karte #{card.get('id')} · {self.index + 1} von "
            f"{len(self.cards)} · {os.path.basename(path)}")
        self.btn_prev.setEnabled(self.index > 0)
        self.btn_next.setEnabled(self.index < len(self.cards) - 1)

        if not os.path.exists(path):
            self.image_label.setText("Bilddatei nicht gefunden.")
            self._pix = None
            return

        pix = QPixmap(path)
        if pix.isNull():
            self.image_label.setText("Bild konnte nicht geladen werden.")
            self._pix = None
            return

        self._pix = pix
        self._apply_size()

    def _apply_size(self):
        if not getattr(self, "_pix", None):
            return
        if self.fit_mode:
            target = self.scroll.viewport().size()
            scaled = self._pix.scaled(
                target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled)
            self.image_label.setFixedSize(scaled.size())
        else:
            self.image_label.setPixmap(self._pix)
            self.image_label.setFixedSize(self._pix.size())

    def _toggle_fit(self, event):
        self.fit_mode = not self.fit_mode
        self._apply_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "fit_mode", True):
            self._apply_size()

    def prev_card(self):
        if self.index > 0:
            self.index -= 1
            self._render()

    def next_card(self):
        if self.index < len(self.cards) - 1:
            self.index += 1
            self._render()