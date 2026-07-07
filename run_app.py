# -*- coding: utf-8 -*-
"""
LSE Translator Desktop App:
Interfaz de usuario con PyQt6 para detección en tiempo real y dictado TTS. (MODO USUARIO FINAL)
Para ejecutar desde el escritorio:  python run_app.py
"""
import sys
import os
import math
import queue
import threading
import time

import cv2
import numpy as np
import pythoncom
import win32com.client

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QLayout,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtProperty, pyqtSlot, QSize, QRectF, QRect, QPoint,
)
from PyQt6.QtGui import (
    QImage, QPixmap, QColor, QPainter, QPen,
    QBrush, QLinearGradient, QFont, QFontMetrics,
    QPainterPath, QRadialGradient,
    QShortcut, QKeySequence,
)

# ── Directory Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(BASE_DIR, "lse_model_best.keras")
ACTIONS_PATH = os.path.join(BASE_DIR, "actions.npy")

sys.path.insert(0, BASE_DIR)
from app_desktop.detector import DetectorThread, SEQUENCE_LENGTH
from app_desktop.glossary import GlossaryPanel, Backdrop, load_signs

# ── Paleta ────────────────────────────────────────────────────────────────────
C_BG       = "#08080F"
C_SURFACE  = "#0F0F1A"
C_CARD     = "#13131F"
C_CARD2    = "#18182A"
C_BORDER   = "#1E1E35"
C_ACCENT   = "#7C6FF7"
C_ACCENT2  = "#22D3EE"
C_TEXT     = "#EEF0FF"
C_TEXT2    = "#6B7280"
C_TEXT3    = "#5E6483"
C_SUCCESS  = "#34D399"
C_WARN     = "#FBBF24"
C_ERROR    = "#F87171"
C_CHIP_BG  = "#1C1C30"
C_CHIP_ACT = "#2D2B52"
C_CHIP_BD  = "#3B37A0"


# ══════════════════════════════════════════════════════════════════════════════
#  TTS Worker  (Se ejecuta en un hilo demonio para no bloquear nunca la interfaz de usuario.)
#  Sirve para dictar las palabras detectadas
# ══════════════════════════════════════════════════════════════════════════════

class TTSWorker:
    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._enabled = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def speak(self, text: str):
        if self._enabled:
            # Primero hay que vaciar la cola para que siempre digamos la última palabra.
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            self._q.put(text)

    def set_enabled(self, on: bool):
        self._enabled = on

    def _loop(self):
        # Objeto COM nuevo por palabra: evita la corrupción del estado SAPI después de N llamadas.
        pythoncom.CoInitialize()
        try:
            while True:
                text = self._q.get()
                if text is None:
                    break
                try:
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    speaker.Rate = -1
                    voices = speaker.GetVoices()
                    for i in range(voices.Count):
                        desc = voices.Item(i).GetDescription().lower()
                        if "spanish" in desc or "es-" in desc or "helena" in desc:
                            speaker.Voice = voices.Item(i)
                            break
                    speaker.Speak(text)
                    del speaker
                except Exception:
                    pass
        finally:
            pythoncom.CoUninitialize()


# ══════════════════════════════════════════════════════════════════════════════
#  FlowLayout  (Qt flow layout — envuelve chips como CSS flexbox wrap)
# ══════════════════════════════════════════════════════════════════════════════

class FlowLayout(QLayout):
    def __init__(self, parent=None, h_gap=6, v_gap=6):
        super().__init__(parent)
        self._items = []
        self._h_gap = h_gap
        self._v_gap = v_gap

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize()
        for item in self._items:
            sz = sz.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, dry):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            iw, ih = hint.width(), hint.height()
            if x + iw > eff.right() and row_h > 0:
                x = eff.x()
                y += row_h + self._v_gap
                row_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), QSize(iw, ih)))
            x += iw + self._h_gap
            row_h = max(row_h, ih)
        return y + row_h - eff.y() + m.bottom()


# ══════════════════════════════════════════════════════════════════════════════
#  Widgets personalizados
# ══════════════════════════════════════════════════════════════════════════════

class ConfidenceBar(QWidget):
    """Barra de confianza con degradado de color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._value = 0.0
        self._anim = QPropertyAnimation(self, b"bar_value", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_bar_value(self): return self._value
    def set_bar_value(self, v):
        self._value = v
        self.update()

    bar_value = pyqtProperty(float, get_bar_value, set_bar_value)

    def animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(1.0, target)))
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.setBrush(QBrush(QColor(C_BORDER)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)
        w = int(r.width() * self._value)
        if w > 6:
            grad = QLinearGradient(0, 0, w, 0)
            if self._value >= 0.80:
                grad.setColorAt(0.0, QColor("#6366F1"))
                grad.setColorAt(1.0, QColor(C_SUCCESS))
            elif self._value >= 0.65:
                grad.setColorAt(0.0, QColor(C_ACCENT))
                grad.setColorAt(1.0, QColor(C_ACCENT2))
            else:
                grad.setColorAt(0.0, QColor("#4B5563"))
                grad.setColorAt(1.0, QColor(C_ACCENT))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(r.adjusted(0, 0, -(r.width() - w), 0), 3, 3)
        p.end()


class PulsingDot(QWidget):
    """El LED de estado muestra un breve pulso de transición y luego permanece estático.
    Solo el indicador de "cargando" se mantiene animado continuamente."""

    STATUS_COLORS = {
        "idle":      "#5E6483",
        "loading":   "#FBBF24",
        "detecting": "#34D399",
        "error":     "#F87171",
    }
    TRANSITION_SECS = 1.5

    def __init__(self, size=10, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._status = "idle"
        self._phase = 0.0
        self._pulse_until = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_status(self, s: str):
        if s == self._status:
            return
        self._status = s
        # Start a fresh transition pulse window
        self._phase = 0.0
        self._pulse_until = time.monotonic() + self.TRANSITION_SECS
        if not self._timer.isActive():
            self._timer.start(40)
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        # "loading" pulses forever; anything else only during transition window
        if self._status == "loading" or time.monotonic() < self._pulse_until:
            self.update()
        else:
            self._timer.stop()
            self.update()   # one final paint with no pulse

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        cx, cy, r = s // 2, s // 2, s // 2 - 1
        color = QColor(self.STATUS_COLORS.get(self._status, "#5E6483"))

        now = time.monotonic()
        in_transition = now < self._pulse_until
        is_loading = self._status == "loading"

        if (is_loading or in_transition) and self._status in ("detecting", "loading"):
            # Outer glow — decays during transition, perpetual for loading
            if is_loading:
                env = 1.0
            else:
                # Exponential decay over the transition window
                remaining = self._pulse_until - now
                env = max(0.0, remaining / self.TRANSITION_SECS)
            pulse = env * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._phase * 1.4)))
            glow = QRadialGradient(cx, cy, r + 3)
            glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(),
                                        int(180 * pulse)))
            glow.setColorAt(1.0, Qt.GlobalColor.transparent)
            p.setBrush(QBrush(glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(0, 0, s, s)

        # Solid inner dot — always drawn
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r + 2, cy - r + 2, (r - 2) * 2, (r - 2) * 2)
        p.end()



class CameraWidget(QLabel):
    """Circulo de llenado del buffer de secuencia y animación de carga del modelo, superpuestos sobre el feed de la cámara."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 340)
        self._pixmap: QPixmap | None = None
        self._placeholder = True
        self._loading = False       # True while model is loading (pre-camera)
        self._buffer  = 0           # 0-SEQUENCE_LENGTH (post-camera warmup)
        self._phase   = 0.0
        self._timer   = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        self._phase = (self._phase + 0.09) % (2 * math.pi)
        # Redraw whenever an animation is active
        if self._loading or (not self._placeholder and self._buffer < SEQUENCE_LENGTH):
            self.update()

    def set_loading(self, on: bool):
        self._loading = on
        self.update()

    def set_buffer(self, n: int):
        self._buffer = n
        self.update()

    def update_frame(self, frame: np.ndarray):
        h, w, ch = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qt_img)
        self._placeholder = False
        self.update()

    def clear_frame(self):
        self._pixmap = None
        self._placeholder = True
        self._loading = False
        self._buffer  = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        cx, cy = r.width() // 2, r.height() // 2

        # Rounded clip
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(r), 18, 18)
        p.setClipPath(clip)

        # ── Dark background (used by all placeholder states) ──
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0.0, QColor(C_CARD))
        grad.setColorAt(1.0, QColor(C_CARD2))

        if self._placeholder or self._pixmap is None:
            p.fillRect(r, grad)

            if self._loading:
                # ── STATE 2: model loading — spinning indeterminate ring ──
                self._draw_ring_overlay(
                    p, cx, cy, r,
                    spinning=True,
                    ratio=0.0,
                    label="Cargando modelo...",
                )
            else:
                # ── STATE 1: idle — static hint text ──
                p.setPen(QColor(C_TEXT3))
                f = QFont("Segoe UI")
                f.setPixelSize(13)
                p.setFont(f)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                           "Cámara no iniciada\n\nPulsa Iniciar para comenzar")
        else:
            # ── Camera feed ──
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (r.width()  - scaled.width())  // 2
            oy = (r.height() - scaled.height()) // 2
            p.drawPixmap(ox, oy, scaled)

            if self._buffer < SEQUENCE_LENGTH:
                # ── STATE 3: buffer warmup — deterministic fill ring over feed ──
                p.fillRect(r, QColor(0, 0, 0, 105))
                self._draw_ring_overlay(
                    p, cx, cy, r,
                    spinning=False,
                    ratio=self._buffer / SEQUENCE_LENGTH,
                    label="Calibrando buffer...",
                )

        p.end()

    def _draw_ring_overlay(self, p, cx, cy, r, spinning, ratio, label):
        ring_r = max(46, min(min(r.width(), r.height()) // 6, 70))
        ring_rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)

        # Track circle
        pen = QPen(QColor(28, 28, 52), 5, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring_rect)

        # Animated arc color (accent ↔ cyan pulse)
        pulse = 0.5 + 0.5 * math.sin(self._phase)
        r1, r2 = QColor(C_ACCENT), QColor(C_ACCENT2)
        arc_col = QColor(
            int(r1.red()   * pulse + r2.red()   * (1 - pulse)),
            int(r1.green() * pulse + r2.green() * (1 - pulse)),
            int(r1.blue()  * pulse + r2.blue()  * (1 - pulse)),
        )
        pen.setColor(arc_col)
        pen.setWidth(5)
        p.setPen(pen)

        if spinning:
            # Rotating 220° arc — indeterminate spinner
            start = int((self._phase * 2 * 180 / math.pi) * 16) % (360 * 16)
            p.drawArc(ring_rect, start, -int(220 * 16))
        else:
            # Filled arc from 12 o'clock
            span = max(int(-ratio * 360 * 16), -16)
            p.drawArc(ring_rect, 90 * 16, span)

        # Centre text
        p.setBrush(Qt.BrushStyle.NoBrush)
        fnt = QFont("Segoe UI")
        fnt.setWeight(QFont.Weight.Bold)
        fnt.setPixelSize(ring_r // 2)
        p.setFont(fnt)
        if spinning:
            dot_count = int(self._phase * 1.5) % 4
            centre_txt = "." * dot_count + " " * (3 - dot_count)
        else:
            centre_txt = f"{int(ratio * 100)}%"
        p.setPen(QColor(C_TEXT))
        p.drawText(ring_rect, Qt.AlignmentFlag.AlignCenter, centre_txt)

        # Label below ring
        alpha = int(160 + 95 * math.sin(self._phase * 2))
        lbl_color = QColor(C_TEXT2)
        lbl_color.setAlpha(alpha)
        p.setPen(lbl_color)
        fnt2 = QFont("Segoe UI")
        fnt2.setPixelSize(12)
        p.setFont(fnt2)
        lbl_rect = QRectF(cx - 110, cy + ring_r + 12, 220, 20)
        p.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, label)


class WordChip(QPushButton):
    """Botón de chip para cada palabra detectada, con estilo diferenciado para la última palabra."""

    def __init__(self, text: str, is_latest: bool, on_remove, parent=None):
        super().__init__(text, parent)
        self.setToolTip("Haz clic para eliminar")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(on_remove)
        bd = C_CHIP_BD if is_latest else C_BORDER
        bg = C_CHIP_ACT if is_latest else C_CHIP_BG
        fg = C_TEXT    if is_latest else C_TEXT2
        fw = "600"     if is_latest else "400"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {fg};
                border: 1px solid {bd};
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 13px;
                font-weight: {fw};
            }}
            QPushButton:hover {{
                background: #3B1E1E;
                color: {C_ERROR};
                border-color: #5A2020;
            }}
        """)


# ══════════════════════════════════════════════════════════════════════════════
#  Parámetros estéticos globales y hoja de estilos (QSS)
# ══════════════════════════════════════════════════════════════════════════════

GLOBAL_QSS = f"""
* {{
    font-family: "Segoe UI", "SF Pro Display", sans-serif;
    font-size: 13px;
    color: {C_TEXT};
}}
QMainWindow, QWidget#root {{
    background: {C_BG};
}}
QFrame#panel {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 20px;
}}
QLabel#title {{
    font-size: 20px;
    font-weight: 700;
    color: {C_TEXT};
    letter-spacing: 0.3px;
}}
QLabel#tagline {{
    font-size: 11px;
    color: {C_TEXT2};
    letter-spacing: 0.5px;
}}
QLabel#sectionHead {{
    font-size: 10px;
    font-weight: 700;
    color: {C_TEXT3};
    letter-spacing: 1.2px;
}}
QLabel#predMain {{
    font-weight: 800;
    color: {C_TEXT};
    qproperty-alignment: AlignCenter;
}}
QLabel#predConf {{
    font-size: 13px;
    color: {C_TEXT2};
}}
QLabel#statusText {{
    font-size: 12px;
    color: {C_TEXT2};
}}
QLabel#fpsText {{
    font-size: 12px;
    color: {C_TEXT2};
}}
QLabel#handsText {{
    font-size: 12px;
    color: {C_TEXT3};
}}
QFrame#predCard {{
    background: {C_CARD2};
    border: 1px solid {C_BORDER};
    border-radius: 14px;
}}
QFrame#sentenceFrame {{
    background: {C_CARD2};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
    min-height: 54px;
}}
QPushButton#btnPrimary {{
    background: {C_ACCENT};
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    padding: 0 22px;
    min-height: 46px;
}}
QPushButton#btnPrimary:hover {{
    background: #9D97FF;
}}
QPushButton#btnPrimary:pressed {{
    background: #5A55D6;
}}
QPushButton#btnPrimary[active="true"] {{
    background: #3D1F1F;
    color: {C_ERROR};
    border: 1px solid #5A2020;
}}
QPushButton#btnPrimary[active="true"]:hover {{
    background: #4F2525;
}}
QPushButton#btnSecondary {{
    background: transparent;
    color: {C_TEXT2};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
    font-size: 13px;
    font-weight: 500;
    padding: 0 10px;
    min-height: 40px;
}}
QPushButton#btnSecondary:hover {{
    background: {C_CARD2};
    color: {C_TEXT};
    border-color: {C_ACCENT};
}}
QPushButton#btnSecondary:pressed {{
    background: {C_CARD};
}}
QPushButton#btnTts {{
    background: transparent;
    color: {C_TEXT3};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 10px;
    min-height: 22px;
}}
QPushButton#btnTts:hover {{
    color: {C_TEXT};
    border-color: {C_ACCENT};
}}
QPushButton#btnTts[on="true"] {{
    color: {C_SUCCESS};
    border-color: #1A4A35;
    background: #0D2A1F;
}}
QPushButton#btnGlossary {{
    background: transparent;
    color: {C_TEXT2};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#btnGlossary:hover {{
    color: {C_TEXT};
    border-color: {C_ACCENT};
    background: {C_CARD2};
}}
QPushButton#btnGlossary:pressed {{
    background: {C_CARD};
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Ventana principal de la aplicación, con toda la lógica de gestión de estado, interacción y coordinación de componentes.
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.detector: DetectorThread | None = None
        self._active = False
        self._tts = TTSWorker()
        self._tts_on = False
        self._sentence_words: list[str] = []   # local mirror for chip management
        self._glossary: GlossaryPanel | None = None
        self._backdrop: Backdrop | None = None
        self._build_ui()
        self._setup_shortcuts()
        self.setStyleSheet(GLOBAL_QSS)
        self.resize(1100, 650)
        self.setMinimumSize(880, 560)
        self.setWindowTitle("LSE Translator")

    # ─────────────────────────────────────────────────── UI build
    def _build_ui(self):
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(16)

        # ── Left column: camera + footer ─────────────────────────
        left = QVBoxLayout()
        left.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title   = QLabel("LSE Translator",                          objectName="title")
        tagline = QLabel("Reconocimiento de Lengua de Signos",      objectName="tagline")
        # Compute total signs once for the button badge
        try:
            _palabras, _alfabeto = load_signs()
            _total = len(_palabras) + len(_alfabeto)
        except Exception:
            _total = 0
        self._btn_glossary = QPushButton(
            f"Glosario · {_total}" if _total else "Glosario",
            objectName="btnGlossary",
        )
        self._btn_glossary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_glossary.clicked.connect(self._toggle_glossary)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._btn_glossary)
        header.addSpacing(12)
        header.addWidget(tagline)

        self.camera = CameraWidget()

        # Footer row: fps · buffer ring · hands
        foot = QHBoxLayout()
        foot.setSpacing(8)

        self._fps_dot   = PulsingDot(10)
        self._fps_lbl   = QLabel("—", objectName="fpsText")
        self._hands_lbl = QLabel("Sin manos", objectName="handsText")

        foot.addWidget(self._fps_dot)
        foot.addWidget(self._fps_lbl)
        foot.addStretch()
        foot.addWidget(self._hands_lbl)

        left.addLayout(header)
        left.addWidget(self.camera, stretch=1)
        left.addLayout(foot)

        # ── Right column: panel ───────────────────────────────────
        panel = QFrame(objectName="panel")
        panel.setFixedWidth(310)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 26, 22, 26)
        panel_layout.setSpacing(0)

        # Status row
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._status_dot = PulsingDot(10)
        self._status_lbl = QLabel("En espera", objectName="statusText")
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()

        # Prediction card
        pred_card = QFrame(objectName="predCard")
        pred_v = QVBoxLayout(pred_card)
        pred_v.setContentsMargins(18, 16, 18, 18)
        pred_v.setSpacing(4)

        ph = QLabel("SIGNO DETECTADO", objectName="sectionHead")
        self._pred_main = QLabel("—", objectName="predMain")
        self._pred_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pred_main.setWordWrap(True)
        self._pred_main.setMinimumHeight(52)
        self._pred_conf = QLabel("—", objectName="predConf")
        self._pred_conf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._conf_bar  = ConfidenceBar()

        pred_v.addWidget(ph)
        pred_v.addSpacing(6)
        pred_v.addWidget(self._pred_main)
        pred_v.addWidget(self._pred_conf)
        pred_v.addSpacing(8)
        pred_v.addWidget(self._conf_bar)

        # Sentence header row (label + TTS toggle)
        sent_head_row = QHBoxLayout()
        sent_head_row.setSpacing(6)
        sent_head = QLabel("FRASE", objectName="sectionHead")
        self._btn_tts = QPushButton("VOZ OFF", objectName="btnTts")
        self._btn_tts.setProperty("on", False)
        self._btn_tts.setCheckable(True)
        self._btn_tts.clicked.connect(self._toggle_tts)
        sent_head_row.addWidget(sent_head)
        sent_head_row.addStretch()
        sent_head_row.addWidget(self._btn_tts)

        # Sentence frame with FlowLayout for word chips
        self._sent_frame = QFrame(objectName="sentenceFrame")
        self._flow = FlowLayout(self._sent_frame, h_gap=6, v_gap=6)
        self._flow.setContentsMargins(12, 10, 12, 10)
        # Placeholder label (managed manually)
        self._sent_placeholder = QLabel("Las palabras aparecerán aquí")
        self._sent_placeholder.setStyleSheet(
            f"color:{C_TEXT3}; font-size:12px; font-style:italic; background:transparent;"
        )
        self._flow.addWidget(self._sent_placeholder)

        # Buttons
        self._btn_toggle = QPushButton("Iniciar detección", objectName="btnPrimary")
        self._btn_toggle.setProperty("active", False)
        self._btn_toggle.clicked.connect(self._toggle)

        self._btn_clear = QPushButton("Limpiar frase", objectName="btnSecondary")
        self._btn_clear.clicked.connect(self._clear)

        self._btn_copy = QPushButton("Copiar frase", objectName="btnSecondary")
        self._btn_copy.clicked.connect(self._copy_sentence)

        # Secondary buttons go in a single row, half-width each (stretch=1)
        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        secondary_row.addWidget(self._btn_clear, 1)
        secondary_row.addWidget(self._btn_copy,  1)

        # Assemble panel
        panel_layout.addLayout(status_row)
        panel_layout.addSpacing(20)
        panel_layout.addWidget(pred_card)
        panel_layout.addSpacing(20)
        panel_layout.addLayout(sent_head_row)
        panel_layout.addSpacing(8)
        panel_layout.addWidget(self._sent_frame)
        panel_layout.addStretch()
        panel_layout.addSpacing(14)   # guarantees a gap even when stretch collapses
        panel_layout.addWidget(self._btn_toggle)
        panel_layout.addSpacing(8)
        panel_layout.addLayout(secondary_row)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        panel.setGraphicsEffect(shadow)

        outer.addLayout(left, stretch=1)
        outer.addWidget(panel)

    # ─────────────────────────────────────────────────── shortcuts
    def _setup_shortcuts(self):
        bindings = [
            ("Space",  self._toggle,           "Iniciar / detener  (Espacio)"),
            ("Esc",    self._on_escape,        "Limpiar frase  (Esc)"),
            ("Ctrl+C", self._copy_sentence,    "Copiar frase  (Ctrl+C)"),
            ("V",      self._toggle_tts,       None),
            ("G",      self._toggle_glossary,  None),
        ]
        for keys, fn, _ in bindings:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(fn)

        # Expose the shortcuts in tooltips so users can discover them
        self._btn_toggle.setToolTip(bindings[0][2])
        self._btn_clear.setToolTip(bindings[1][2])
        self._btn_copy.setToolTip(bindings[2][2])
        self._btn_tts.setToolTip("Activar / desactivar voz  (V)")
        self._btn_glossary.setToolTip("Abrir glosario de signos  (G)")

    # ─────────────────────────────────────────────────── helpers
    def _update_pred_font(self, text: str):
        # Use the label's actual width when available — falls back to a
        # conservative constant if the layout hasn't run yet.
        w = self._pred_main.width()
        available = (w - 14) if w > 100 else 210
        for size in (46, 38, 30, 24, 18):
            f = self._pred_main.font()
            f.setPixelSize(size)
            f.setWeight(QFont.Weight.ExtraBold)
            if QFontMetrics(f).horizontalAdvance(text) <= available or size == 18:
                self._pred_main.setStyleSheet(
                    f"font-size:{size}px; font-weight:800; color:{C_TEXT};"
                )
                break

    def _rebuild_chips(self, words: list[str], animate_last: bool = False):
        """Clear FlowLayout and rebuild word chips. Animate newest chip if requested."""
        # Remove everything from the layout
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not words:
            ph = QLabel("Las palabras aparecerán aquí")
            ph.setStyleSheet(
                f"color:{C_TEXT3}; font-size:12px; font-style:italic; background:transparent;"
            )
            self._flow.addWidget(ph)
            return

        for i, word in enumerate(words):
            is_last = (i == len(words) - 1)
            chip = WordChip(
                word, is_last,
                on_remove=lambda checked, idx=i: self._remove_word(idx),
            )
            self._flow.addWidget(chip)

            # Fade-in animation for the newest chip
            if animate_last and is_last:
                effect = QGraphicsOpacityEffect(chip)
                chip.setGraphicsEffect(effect)
                anim = QPropertyAnimation(effect, b"opacity", chip)
                anim.setDuration(400)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()
                # Keep refs alive
                chip._fade_effect = effect
                chip._fade_anim   = anim

        # Force the frame to recalculate its size
        self._sent_frame.updateGeometry()

    def _remove_word(self, index: int):
        if index < len(self._sentence_words):
            self._sentence_words.pop(index)
            if self.detector:
                self.detector.set_sentence(list(self._sentence_words))
            self._rebuild_chips(self._sentence_words, animate_last=False)

    def _set_btn_state(self, active: bool):
        self._btn_toggle.setText("Detener" if active else "Iniciar detección")
        self._btn_toggle.setProperty("active", active)
        self._btn_toggle.style().unpolish(self._btn_toggle)
        self._btn_toggle.style().polish(self._btn_toggle)

    # ─────────────────────────────────────────────────── slots
    def _toggle(self):
        if self._active:
            self._stop()
        else:
            self._start()

    def _start(self):
        self.detector = DetectorThread(MODEL_PATH, ACTIONS_PATH)
        self.detector.frame_signal.connect(self._on_frame)
        self.detector.prediction_signal.connect(self._on_pred)
        self.detector.sentence_signal.connect(self._on_sentence)
        self.detector.fps_signal.connect(self._on_fps)
        self.detector.hands_signal.connect(self._on_hands)
        self.detector.buffer_signal.connect(self._on_buffer)
        self.detector.status_signal.connect(self._on_status)
        self.detector.error_signal.connect(self._on_error)
        self.detector.start()
        self._active = True
        self._set_btn_state(True)

    def _stop(self):
        if self.detector:
            self.detector.stop()
            self.detector = None
        self._active = False
        self.camera.clear_frame()
        self._set_btn_state(False)
        self._on_status("idle")
        self._fps_dot.set_status("idle")
        self._fps_lbl.setText("—")
        self._hands_lbl.setText("Sin manos")
        self._pred_main.setStyleSheet(
            f"font-size:46px; font-weight:800; color:{C_TEXT};"
        )
        self._pred_main.setText("—")
        self._pred_conf.setText("—")
        self._conf_bar.animate_to(0.0)

    def _clear(self):
        if self.detector:
            self.detector.request_clear()
        self._sentence_words.clear()
        self._rebuild_chips([])

    # ─────────────────────────────────────────────────── glossary
    def _ensure_glossary(self):
        if self._glossary is None:
            cw = self.centralWidget()
            self._backdrop = Backdrop(cw)
            self._backdrop.clicked.connect(self._close_glossary)
            self._backdrop.hide()
            self._glossary = GlossaryPanel(cw)

    def _toggle_glossary(self):
        self._ensure_glossary()
        if self._glossary.is_open():
            self._close_glossary()
        else:
            self._open_glossary()

    def _open_glossary(self):
        self._ensure_glossary()
        cw_rect = self.centralWidget().rect()
        self._backdrop.setGeometry(cw_rect)
        self._backdrop.show()
        self._backdrop.raise_()
        self._glossary.open_drawer(cw_rect)

    def _close_glossary(self):
        if self._glossary and self._glossary.is_open():
            self._glossary.close_drawer()
        if self._backdrop:
            self._backdrop.hide()

    def _on_escape(self):
        """Si el glosario está abierto, ciérralo. De lo contrario, limpia la frase actual."""
        if self._glossary and self._glossary.is_open():
            self._close_glossary()
        else:
            self._clear()

    def _copy_sentence(self):
        if not self._sentence_words:
            return
        QApplication.clipboard().setText(" ".join(self._sentence_words))
        # Brief flash feedback on the button
        original = self._btn_copy.text()
        self._btn_copy.setText("¡Copiado!")
        self._btn_copy.setEnabled(False)
        self._btn_copy.setStyleSheet(
            f"background:{C_SUCCESS}; color:#0A1F14; "
            f"border:1px solid {C_SUCCESS}; border-radius:12px; "
            f"font-size:13px; font-weight:600; padding:0 10px; min-height:40px;"
        )
        QTimer.singleShot(1400, lambda: self._restore_copy_btn(original))

    def _restore_copy_btn(self, text: str):
        self._btn_copy.setText(text)
        self._btn_copy.setStyleSheet("")   # fall back to QSS
        self._btn_copy.setEnabled(True)

    def _toggle_tts(self):
        self._tts_on = not self._tts_on
        self._tts.set_enabled(self._tts_on)
        self._btn_tts.setText("VOZ ON" if self._tts_on else "VOZ OFF")
        self._btn_tts.setProperty("on", self._tts_on)
        self._btn_tts.style().unpolish(self._btn_tts)
        self._btn_tts.style().polish(self._btn_tts)

    @pyqtSlot(object)
    def _on_frame(self, frame):
        self.camera.update_frame(frame)

    @pyqtSlot(str, float)
    def _on_pred(self, action: str, conf: float):
        if action:
            self._update_pred_font(action)
            self._pred_main.setText(action)
            self._pred_conf.setText(f"{int(conf * 100)} % confianza")
            self._conf_bar.animate_to(conf)
            # Mirror detection in glossary if it's open
            if self._glossary and self._glossary.is_open():
                self._glossary.highlight_sign(action)
        else:
            self._pred_main.setStyleSheet(
                f"font-size:46px; font-weight:800; color:{C_TEXT};"
            )
            self._pred_main.setText("—")
            self._pred_conf.setText("—")
            self._conf_bar.animate_to(0.0)

    @pyqtSlot(list)
    def _on_sentence(self, words: list):
        prev = self._sentence_words

        # Detect a new word: last element changed AND the list didn't shrink
        # (covers both append AND the sliding-window case when list is at max len)
        new_word = None
        if words and len(words) >= len(prev):
            if not prev or words[-1] != prev[-1]:
                new_word = words[-1]

        animate = new_word is not None
        self._sentence_words = list(words)
        self._rebuild_chips(words, animate_last=animate)

        if new_word and self._tts_on:
            self._tts.speak(new_word)

    @pyqtSlot(int)
    def _on_buffer(self, n: int):
        self.camera.set_buffer(n)

    @pyqtSlot(float)
    def _on_fps(self, fps: float):
        color = C_SUCCESS if fps >= 20 else (C_WARN if fps >= 14 else C_ERROR)
        self._fps_lbl.setText(f"<span style='color:{color}'>{fps:.1f} FPS</span>")
        self._fps_lbl.setTextFormat(Qt.TextFormat.RichText)

    @pyqtSlot(bool)
    def _on_hands(self, has: bool):
        if has:
            self._hands_lbl.setStyleSheet(f"color:{C_SUCCESS}; font-size:12px;")
            self._hands_lbl.setText("Manos detectadas")
            self._fps_dot.set_status("detecting")
        else:
            self._hands_lbl.setStyleSheet(f"color:{C_TEXT3}; font-size:12px;")
            self._hands_lbl.setText("Sin manos")
            self._fps_dot.set_status("idle")

    @pyqtSlot(str)
    def _on_status(self, status: str):
        self._status_dot.set_status(status)
        labels = {
            "idle":      "En espera",
            "loading":   "Cargando modelo...",
            "detecting": "Detectando",
            "error":     "Error",
        }
        self._status_lbl.setText(labels.get(status, status))
        # Drive the camera loading spinner
        self.camera.set_loading(status == "loading")

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._pred_main.setText("Error")
        self._pred_conf.setText(msg[:50])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._glossary and self._glossary.is_open():
            cw_rect = self.centralWidget().rect()
            if self._backdrop:
                self._backdrop.setGeometry(cw_rect)
            self._glossary.reposition(cw_rect)

    def closeEvent(self, event):
        if self.detector and self.detector.isRunning():
            self.detector.stop()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# Función principal y entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LSE Translator")
    app.setStyle("Fusion")
    win = MainWindow()

    screen = app.primaryScreen().availableGeometry()
    win.move(
        screen.x() + (screen.width()  - win.width())  // 2,
        screen.y() + (screen.height() - win.height()) // 2,
    )

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
