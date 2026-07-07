# -*- coding: utf-8 -*-
"""
Glosario lateral de signos — drawer animado con búsqueda en vivo,
pestañas Palabras/Alfabeto y resaltado en tiempo real cuando el modelo
detecta un signo presente en la lista.
"""
import json
import os
import unicodedata

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QWidget, QApplication, QLayout, QStackedWidget,
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRect, QSize, QPoint,
    QTimer, pyqtSignal,
)


# ── Palette (kept in sync with run_app.py) ──────────────────────────────────
C_CARD    = "#13131F"
C_CARD2   = "#18182A"
C_BORDER  = "#1E1E35"
C_ACCENT  = "#7C6FF7"
C_TEXT    = "#F2F3FF"
C_TEXT2   = "#A3A8C2"
C_TEXT3   = "#5E6483"
C_SUCCESS = "#34D399"


# ── Data loading ────────────────────────────────────────────────────────────

def load_signs():
    """Returns (palabras_sorted_dedup, alfabeto_without_sin_signo)."""
    here   = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    path   = os.path.join(parent, "words_to_capture.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return [], []
    palabras = sorted({w for w in data.get("palabras", []) if w})
    alfabeto = [x for x in data.get("alfabeto", []) if x and x != "SIN SIGNO"]
    return palabras, alfabeto


def _normalize(s: str) -> str:
    """Lowercase + strip accents for accent-insensitive search."""
    n = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in n if not unicodedata.combining(c))


# ── FlowLayout (skips hidden children, so search filter works) ──────────────

class FlowLayout(QLayout):
    def __init__(self, parent=None, h_gap=7, v_gap=7):
        super().__init__(parent)
        self._items = []
        self._h_gap = h_gap
        self._v_gap = v_gap

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._do_layout(QRect(0, 0, w, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, dry=False)

    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        sz = QSize()
        for it in self._items:
            sz = sz.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, dry):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = eff.x(), eff.y(), 0
        for it in self._items:
            w = it.widget()
            if w is not None and not w.isVisible():
                continue
            hint = it.sizeHint()
            iw, ih = hint.width(), hint.height()
            if x + iw > eff.right() and row_h > 0:
                x = eff.x()
                y += row_h + self._v_gap
                row_h = 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), QSize(iw, ih)))
            x += iw + self._h_gap
            row_h = max(row_h, ih)
        return y + row_h - eff.y() + m.bottom()


# ── Backdrop ────────────────────────────────────────────────────────────────

class Backdrop(QFrame):
    """Semi-transparent overlay behind the drawer."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0, 0, 0, 0.55);")
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        self.clicked.emit()
        super().mousePressEvent(e)


# ── SignChip ────────────────────────────────────────────────────────────────

class SignChip(QPushButton):
    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self._name = name
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        self.setToolTip("Haz clic para copiar al portapapeles")
        self.clicked.connect(self._on_click)
        self._apply_style()

    def name(self) -> str:
        return self._name

    def _apply_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: {C_CARD2};
                color: {C_TEXT2};
                border: 1px solid {C_BORDER};
                border-radius: 9px;
                padding: 7px 14px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: #1E1E35;
                color: {C_TEXT};
                border-color: #2D2D52;
            }}
            QPushButton[active="true"] {{
                background: #2D2B52;
                color: {C_TEXT};
                border: 1px solid {C_ACCENT};
                font-weight: 700;
            }}
            QPushButton[active="true"]:hover {{
                background: #3B37A0;
                border-color: {C_ACCENT};
            }}
        """)

    def set_active(self, on: bool):
        if self._active == on:
            return
        self._active = on
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_click(self):
        QApplication.clipboard().setText(self._name)
        original = self.text()
        self.setText("¡Copiado!")
        self.setEnabled(False)
        QTimer.singleShot(900, lambda t=original: self._restore(t))

    def _restore(self, original: str):
        self.setText(original)
        self.setEnabled(True)


# ── GlossaryPanel (main drawer) ─────────────────────────────────────────────

class GlossaryPanel(QFrame):
    closed = pyqtSignal()

    DRAWER_WIDTH = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("glossaryPanel")
        self._active_chip: SignChip | None = None
        self._chips_palabras: dict[str, SignChip] = {}
        self._chips_alfabeto: dict[str, SignChip] = {}
        self._search_text = ""
        self._anim: QPropertyAnimation | None = None
        self._is_open = False

        self._apply_panel_style()
        self._build_ui()
        self._load_data()
        self.hide()

    # ─── public API ──────────────────────────────────────────────────────

    def is_open(self) -> bool:
        return self._is_open

    def total_signs(self) -> int:
        return len(self._chips_palabras) + len(self._chips_alfabeto)

    def highlight_sign(self, name: str):
        """Called by MainWindow on every consolidated prediction."""
        if not name or name == "SIN SIGNO":
            return
        # No-op if already highlighted
        if self._active_chip is not None and self._active_chip.name() == name:
            return

        target_chip = None
        target_idx  = -1
        if name in self._chips_palabras:
            target_chip = self._chips_palabras[name]; target_idx = 0
        elif name in self._chips_alfabeto:
            target_chip = self._chips_alfabeto[name]; target_idx = 1

        if target_chip is None:
            return

        if self._active_chip is not None:
            self._active_chip.set_active(False)
        target_chip.set_active(True)
        self._active_chip = target_chip

        # Auto-scroll only if visible tab matches
        if self._stack.currentIndex() == target_idx:
            sa = self._stack.widget(target_idx)
            sa.ensureWidgetVisible(target_chip, 50, 50)

    def clear_highlight(self):
        if self._active_chip is not None:
            self._active_chip.set_active(False)
            self._active_chip = None

    def open_drawer(self, anchor_rect: QRect):
        # Position just off-screen to the right
        start = QRect(anchor_rect.right() + 1, anchor_rect.top(),
                      self.DRAWER_WIDTH, anchor_rect.height())
        self.setGeometry(start)
        self.show()
        self.raise_()
        self._is_open = True

        end = QRect(anchor_rect.right() - self.DRAWER_WIDTH, anchor_rect.top(),
                    self.DRAWER_WIDTH, anchor_rect.height())
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

        QTimer.singleShot(300, self._search.setFocus)

    def close_drawer(self):
        if not self._is_open:
            return
        self._is_open = False
        cur = self.geometry()
        end = QRect(self.parent().width() + 1, cur.top(),
                    cur.width(), cur.height())
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(end)
        self._anim.finished.connect(self._after_close)
        self._anim.start()

    def reposition(self, anchor_rect: QRect):
        if self._is_open:
            self.setGeometry(
                anchor_rect.right() - self.DRAWER_WIDTH,
                anchor_rect.top(),
                self.DRAWER_WIDTH,
                anchor_rect.height(),
            )

    # ─── internals ───────────────────────────────────────────────────────

    def _after_close(self):
        self.hide()
        self.clear_highlight()
        self._search.clear()
        self.closed.emit()

    def _apply_panel_style(self):
        self.setStyleSheet(f"""
            #glossaryPanel {{
                background: {C_CARD};
                border-left: 1px solid {C_BORDER};
            }}
            QLabel#gTitle {{
                color: {C_TEXT};
                font-size: 18px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }}
            QLabel#gCount {{
                color: {C_TEXT3};
                font-size: 12px;
            }}
            QLabel#gFooter {{
                color: {C_TEXT3};
                font-size: 11px;
                font-style: italic;
            }}
            QPushButton#gClose {{
                background: transparent;
                color: {C_TEXT2};
                border: none;
                border-radius: 8px;
                font-size: 22px;
                font-weight: 300;
                padding: 0px;
                min-width: 30px; min-height: 30px;
                max-width: 30px; max-height: 30px;
            }}
            QPushButton#gClose:hover {{
                background: #1E1E35;
                color: {C_TEXT};
            }}
            QPushButton#gTab {{
                background: transparent;
                color: {C_TEXT2};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 9px 16px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton#gTab:hover {{
                color: {C_TEXT};
            }}
            QPushButton#gTab:checked {{
                color: {C_TEXT};
                border-bottom: 2px solid {C_ACCENT};
                font-weight: 600;
            }}
            QLineEdit#gSearch {{
                background: {C_CARD2};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                selection-background-color: {C_ACCENT};
            }}
            QLineEdit#gSearch:focus {{
                border: 1px solid {C_ACCENT};
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 4px 2px;
            }}
            QScrollBar::handle:vertical {{
                background: #2D2D52;
                border-radius: 3px;
                min-height: 32px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_ACCENT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # Header: title + close
        header = QHBoxLayout()
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._title_lbl = QLabel("Glosario", objectName="gTitle")
        self._count_lbl = QLabel("", objectName="gCount")
        title_box.addWidget(self._title_lbl)
        title_box.addWidget(self._count_lbl)

        self._close_btn = QPushButton("×", objectName="gClose")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_drawer)
        self._close_btn.setToolTip("Cerrar  (Esc)")

        header.addLayout(title_box, stretch=1)
        header.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        # Tabs
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self._tab_p = QPushButton("Palabras", objectName="gTab")
        self._tab_a = QPushButton("Alfabeto", objectName="gTab")
        for t in (self._tab_p, self._tab_a):
            t.setCheckable(True)
            t.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_p.setChecked(True)
        self._tab_p.clicked.connect(lambda: self._set_tab(0))
        self._tab_a.clicked.connect(lambda: self._set_tab(1))
        tabs.addWidget(self._tab_p)
        tabs.addWidget(self._tab_a)
        tabs.addStretch()

        # Search
        self._search = QLineEdit(objectName="gSearch")
        self._search.setPlaceholderText("Buscar signo...")
        self._search.textChanged.connect(self._on_search)
        self._search.setClearButtonEnabled(True)

        # Stack with two scroll areas
        self._stack = QStackedWidget()
        self._scroll_p = self._make_scroll_area("palabras")
        self._scroll_a = self._make_scroll_area("alfabeto")
        self._stack.addWidget(self._scroll_p)
        self._stack.addWidget(self._scroll_a)

        # Footer hint
        self._footer = QLabel("Haz clic en un signo para copiarlo al portapapeles",
                              objectName="gFooter")

        root.addLayout(header)
        root.addSpacing(2)
        root.addLayout(tabs)
        root.addWidget(self._search)
        root.addWidget(self._stack, stretch=1)
        root.addWidget(self._footer)

    def _make_scroll_area(self, key: str) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        flow = FlowLayout(container, h_gap=7, v_gap=7)
        flow.setContentsMargins(2, 4, 2, 8)
        sa.setWidget(container)
        setattr(self, f"_flow_{key}", flow)
        setattr(self, f"_container_{key}", container)
        return sa

    def _load_data(self):
        palabras, alfabeto = load_signs()
        for w in palabras:
            chip = SignChip(w)
            self._flow_palabras.addWidget(chip)
            self._chips_palabras[w] = chip
        for c in alfabeto:
            chip = SignChip(c)
            self._flow_alfabeto.addWidget(chip)
            self._chips_alfabeto[c] = chip
        self._count_lbl.setText(
            f"{len(self._chips_palabras)} palabras  ·  {len(self._chips_alfabeto)} letras"
        )

    def _set_tab(self, idx: int):
        self._tab_p.setChecked(idx == 0)
        self._tab_a.setChecked(idx == 1)
        self._stack.setCurrentIndex(idx)
        self._apply_search_filter()

    def _on_search(self, text: str):
        self._search_text = _normalize(text)
        self._apply_search_filter()

    def _apply_search_filter(self):
        q = self._search_text
        # Apply to BOTH lists so tab switching doesn't leave stale hidden chips
        for chips in (self._chips_palabras, self._chips_alfabeto):
            for name, chip in chips.items():
                visible = (q == "" or q in _normalize(name))
                chip.setVisible(visible)
        self._flow_palabras.invalidate()
        self._flow_palabras.activate()
        self._flow_alfabeto.invalidate()
        self._flow_alfabeto.activate()
