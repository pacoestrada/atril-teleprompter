#!/usr/bin/python3
"""Atril Teleprónter — Paco Estrada / Compilando Podcast."""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QIcon, QKeySequence, QPainter, QPalette,
                         QPixmap, QPolygonF, QTextBlockFormat, QTextCursor,
                         QTextDocument, QTextOption, QAbstractTextDocumentLayout)
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QShortcut,
    QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core import (DEFAULTS, DEMO, VERSION, atomic_write, clean_settings,
                  import_document, load_session, save_session, validate_text, word_count)

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
COLORS = {"noche": ("#0c1220", "#f4f2ee", "#172f37"),
          "papel": ("#f6f0e4", "#202534", "#e0e8db"),
          "contraste": ("#000000", "#ffffff", "#202000")}

STYLE = """
QWidget { color: #e9edf7; font-family: 'DejaVu Sans'; font-size: 13px; }
QMainWindow, QDialog { background: #101624; }
QFrame#header { background: #181f32; border: 1px solid #303a55; border-radius: 16px; }
QLabel#brand { font-size: 29px; font-weight: 800; color: #f5f6fc; }
QLabel#eyebrow { color: #5ee0d1; font-size: 11px; font-weight: 700; }
QLabel#muted { color: #a9b4cc; font-size: 12px; }
QLabel#section { color: #c3a8ff; font-weight: 700; font-size: 11px; }
QLabel#value { color: #66e5d7; font-weight: 700; }
QLabel#status { background: #263249; color: #9debe2; border-radius: 10px; padding: 6px 12px; font-size: 11px; font-weight: 700; }
QFrame#panel, QFrame#transport { background: #192132; border: 1px solid #2a354e; border-radius: 14px; }
QFrame#scriptbar { background: #192132; border-radius: 10px; }
QFrame#shortcuts { background: #151d2d; border: 1px solid #2a354e; border-radius: 10px; }
QPushButton { background: #28334b; border: 1px solid #3a4864; border-radius: 9px; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #354563; border-color: #8b9dbe; }
QPushButton:pressed { background: #1c273d; }
QPushButton:focus { border: 2px solid #63e4d4; }
QPushButton:disabled { color: #6e7b91; background: #222c3f; border-color: #2a354a; }
QPushButton#primary { background: #62e4ce; border-color: #62e4ce; color: #102729; font-size: 14px; font-weight: 800; }
QPushButton#primary:hover { background: #8af5e3; }
QPushButton#accent { background: #7760cf; border-color: #9b85ea; color: white; }
QPushButton#accent:hover { background: #9078e8; }
QPushButton#small { padding: 7px 10px; font-size: 12px; }
QSlider { background: transparent; min-height: 22px; }
QSlider::groove:horizontal { border: 0; height: 5px; background: #34415c; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #56cfbf; border-radius: 2px; }
QSlider::handle:horizontal { background: #effefb; border: 3px solid #56cfbf; width: 13px; margin: -6px 0; border-radius: 9px; }
QSlider::groove:horizontal:focus { background: #7b67af; }
QCheckBox { spacing: 9px; padding: 4px 0; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #5b6986; background: #28334b; }
QCheckBox::indicator:checked { background: #62e4ce; border: 4px solid #24685f; }
QComboBox { background: #273249; border: 1px solid #40506d; border-radius: 7px; padding: 7px; min-height: 18px; }
QComboBox:focus { border-color: #62e4ce; }
QComboBox QAbstractItemView { background: #273249; selection-background-color: #6553a2; color: #ffffff; }
QPlainTextEdit { background: #0c1220; color: #f2f3f8; border: 1px solid #3e4c68; border-radius: 10px; padding: 12px; font-size: 18px; selection-background-color: #6954a8; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical { background: #182134; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #54637e; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #e8ecf6; color: #172238; border: 1px solid #5f708c; padding: 6px; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, tip="", name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setToolTip(tip or text)
    widget.setAccessibleName(tip or text)
    return widget


def clock(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


class ReadingCanvas(QWidget):
    moved = pyqtSignal()
    toggleRequested = pyqtSignal()
    manualMove = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(250, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Zona de lectura. Clic para iniciar o pausar; rueda para desplazarse.")
        self.setToolTip("Clic: iniciar o pausar · Rueda: mover y pausar · F11: pantalla completa")
        self.document = QTextDocument(self)
        self.document.setDocumentMargin(0)
        self.text = ""
        self.settings = dict(DEFAULTS)
        self.offset = 0.
        self.maximum = 0.
        self.text_width = 400.
        self.line_height = 60.
        self.countdown_number = 0
        self.lines = []
        self._press = None

    @property
    def progress(self):
        return self.offset / self.maximum if self.maximum > 0 else 0.

    @property
    def guide_y(self):
        return min(self.height() * .28, 115.)

    def anchor(self):
        if not self.lines:
            return (0, 0.)
        chosen = self.lines[0]
        for line in self.lines:
            if line[0] <= self.offset:
                chosen = line
            else:
                break
        return chosen[2], (self.offset - chosen[0]) / max(1., chosen[1])

    def restore_anchor(self, anchor):
        if not self.lines:
            self.set_offset(0)
            return
        chosen = self.lines[0]
        for line in self.lines:
            if line[2] <= anchor[0]:
                chosen = line
            else:
                break
        self.set_offset(chosen[0] + anchor[1] * chosen[1])

    def rebuild(self, preserve=True):
        anchor = self.anchor() if preserve else (0, 0.)
        font = QFont("DejaVu Sans")
        font.setPixelSize(self.settings["font_size"])
        font.setWeight(QFont.Medium)
        self.document.setDefaultFont(font)
        self.document.setPlainText(self.text)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(option)
        cursor = QTextCursor(self.document)
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(self.settings["spacing"], QTextBlockFormat.ProportionalHeight)
        fmt.setBottomMargin(self.settings["font_size"] * .25)
        cursor.setBlockFormat(fmt)
        self.text_width = max(120., (self.width() - 100.) * self.settings["width"] / 100.)
        self.document.setTextWidth(self.text_width)
        self.document.documentLayout().documentSize()
        self.lines = []
        block = self.document.begin()
        while block.isValid():
            layout = block.layout()
            y = self.document.documentLayout().blockBoundingRect(block).y()
            for index in range(layout.lineCount()):
                line = layout.lineAt(index)
                self.lines.append((y + line.y(), line.height() * self.settings["spacing"] / 100.,
                                   block.position() + line.textStart()))
            block = block.next()
        self.line_height = self.settings["font_size"] * 1.2 * self.settings["spacing"] / 100.
        self.maximum = max(0., self.document.size().height()) if self.text.strip() else 0.
        self.restore_anchor(anchor)

    def set_text(self, text):
        self.text = text
        self.rebuild(False)

    def set_offset(self, value):
        self.offset = max(0., min(self.maximum, float(value)))
        self.update()
        self.moved.emit()

    def resizeEvent(self, event):
        self.rebuild()
        super().resizeEvent(event)

    def wheelEvent(self, event):
        if event.pixelDelta().y():
            delta = -event.pixelDelta().y()
        else:
            delta = -event.angleDelta().y() / 120. * self.line_height
        self.manualMove.emit(delta)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.pos()
            self.setFocus(Qt.MouseFocusReason)

    def mouseReleaseEvent(self, event):
        if self._press is not None and (event.pos() - self._press).manhattanLength() < 8:
            self.toggleRequested.emit()
        self._press = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg, fg, band = COLORS[self.settings["theme"]]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(self.rect()), 14, 14)
        if self.settings["guide"]:
            painter.setBrush(QColor(band))
            painter.drawRoundedRect(QRectF(10, self.guide_y - 4, self.width() - 20,
                                           self.line_height + 8), 8, 8)
            painter.setBrush(QColor("#ff927d"))
            mid = self.guide_y + self.line_height / 2
            painter.drawPolygon(QPolygonF([QPointF(17, mid-7), QPointF(28, mid), QPointF(17, mid+7)]))
        painter.save()
        painter.setClipRect(QRectF(36, 15, self.width()-72, self.height()-30))
        if self.settings["mirror"]:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        painter.translate((self.width() - self.text_width) / 2, self.guide_y - self.offset)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.Text, QColor(fg))
        context.clip = QRectF(0, self.offset - self.guide_y, self.text_width, self.height())
        self.document.documentLayout().draw(painter, context)
        painter.restore()
        if not self.text.strip():
            painter.setPen(QColor(fg))
            font = QFont("DejaVu Sans"); font.setPixelSize(23); painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "Tu próxima historia empieza aquí.\n\nAbre un guion o pulsa Editar.")
        if self.countdown_number:
            painter.fillRect(self.rect(), QColor(12, 18, 32, 224))
            font = QFont("DejaVu Sans"); font.setPixelSize(118); font.setBold(True)
            painter.setFont(font); painter.setPen(QColor("#68ead5"))
            painter.drawText(self.rect(), Qt.AlignCenter, str(self.countdown_number))


class ScriptEditor(QDialog):
    def __init__(self, text, parent):
        super().__init__(parent)
        self.setWindowTitle("Editar guion · Atril")
        self.original = text
        self.resize(min(850, parent.width()), min(640, parent.height()))
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 22, 22, 22); layout.setSpacing(12)
        layout.addWidget(label("Dale voz a tu guion", "brand"))
        layout.addWidget(label("Escribe o pega el texto. Los controles de lectura no interfieren al editar.", "muted"))
        self.editor = QPlainTextEdit(); self.editor.setPlainText(text)
        self.editor.setAccessibleName("Texto del guion")
        self.editor.setPlaceholderText("Pega aquí tu guion…")
        layout.addWidget(self.editor, 1)
        self.count = label("", "muted"); layout.addWidget(self.count)
        self.editor.textChanged.connect(self.update_count); self.update_count()
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(button("Cancelar", self.reject))
        row.addWidget(button("Aplicar guion", self.apply, "Aplicar el texto y volver a la lectura", "primary"))
        layout.addLayout(row)

    def update_count(self):
        self.count.setText(f"{word_count(self.editor.toPlainText()):,} palabras · Texto sin formato".replace(",", "."))

    def apply(self):
        try:
            validate_text(self.editor.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Guion demasiado largo", str(exc)); return
        self.accept()

    def reject(self):
        if self.editor.toPlainText() != self.original:
            reply = QMessageBox.question(self, "Descartar cambios", "¿Descartar los cambios de este editor?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        super().reject()


class AtrilWindow(QMainWindow):
    def __init__(self, session_path=None, restore=True):
        super().__init__()
        self.setWindowTitle("Atril Teleprónter · Paco Estrada")
        self.setWindowIcon(QIcon(str(ASSETS / "atril.png")))
        self.session_path = Path(session_path) if session_path else (
            Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) /
            "atril-teleprompter" / "session.json")
        self.settings = dict(DEFAULTS)
        self.title = "Bienvenido a Atril"
        self.text = DEMO
        self.elapsed = 0.
        self.playing = False
        self.finished = False
        self.countdown_until = None
        self._last_tick = time.monotonic()
        self._last_stats = 0.
        self._pending_progress = 0.
        self._pending_anchor = None
        self._initializing = True
        self._save_error_shown = False
        self._restore_error = ""
        self._was_maximized = False
        self._normal_geometry = None
        self.previous_path = self.session_path.with_name("previous.atril")
        if restore and self.session_path.exists():
            try:
                state = load_session(self.session_path)
                self.text, self.title, self.settings = state["text"], state["title"], state["settings"]
                self.elapsed, self._pending_progress = state["elapsed"], state["progress"]
                self._pending_anchor = state.get("anchor")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._restore_error = str(exc)
                # Keep the unreadable original; never overwrite it with the demo.
                self.session_path = self.session_path.with_name("session-recovered.json")
        self.words = word_count(self.text)
        self.build_ui()
        self.create_shortcuts()
        self.sync_controls()
        self.canvas.set_text(self.text)
        self._initializing = False
        self.save_timer = QTimer(self); self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.persist)
        self.timer = QTimer(self); self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick); self.timer.start(16)
        self.periodic_save = QTimer(self); self.periodic_save.timeout.connect(self.persist)
        self.periodic_save.start(5000)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1280, screen.width()-40), min(860, screen.height()-60))
        self.setMinimumSize(680, 480)
        self.move(screen.x() + (screen.width()-self.width())//2,
                  screen.y() + (screen.height()-self.height())//2)
        QTimer.singleShot(0, self.restore_position)

    def build_ui(self):
        main = QWidget(); self.setCentralWidget(main)
        root = QVBoxLayout(main); root.setContentsMargins(18, 14, 18, 12); root.setSpacing(12)
        header = QFrame(); header.setObjectName("header")
        row = QHBoxLayout(header); row.setContentsMargins(16, 10, 16, 10); row.setSpacing(14)
        icon = QLabel(); icon.setPixmap(QPixmap(str(ASSETS / "atril.png")).scaled(68, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(icon)
        identity = QVBoxLayout(); identity.setSpacing(0)
        identity.addWidget(label("ATRIL", "brand"))
        identity.addWidget(label("TELEPRÓNTER · PACO ESTRADA", "eyebrow"))
        row.addLayout(identity); row.addStretch()
        self.tagline = label("Tu voz. Tu ritmo.", "muted"); row.addWidget(self.tagline)
        logo = QLabel(); logo.setPixmap(QPixmap(str(ASSETS / "compilando-podcast-logo.jpg")).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAccessibleName("Logo de Compilando Podcast"); logo.setToolTip("Compilando Podcast · Paco Estrada")
        row.addWidget(logo)
        root.addWidget(header)

        body = QHBoxLayout(); body.setSpacing(12)
        self.panel_scroll = QScrollArea(); self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.panel_scroll.setFixedWidth(248)
        panel = QFrame(); panel.setObjectName("panel")
        controls = QVBoxLayout(panel); controls.setContentsMargins(17, 16, 17, 16); controls.setSpacing(11)
        controls.addWidget(label("A TU MEDIDA", "section"))
        self.sliders = {}; self.values = {}
        self.add_slider(controls, "speed", "Velocidad", 8, 180)
        self.add_slider(controls, "font_size", "Tamaño de letra", 24, 100)
        self.add_slider(controls, "width", "Ancho del texto", 45, 100)
        self.add_slider(controls, "spacing", "Interlineado", 115, 190)
        controls.addWidget(label("PREPARA LA LECTURA", "section"))
        self.countdown_combo = QComboBox()
        for n in range(6): self.countdown_combo.addItem("Sin cuenta atrás" if n==0 else f"Cuenta atrás de {n} s", n)
        self.countdown_combo.setAccessibleName("Cuenta atrás inicial")
        self.countdown_combo.currentIndexChanged.connect(lambda index: self.change_setting("countdown", index))
        controls.addWidget(self.countdown_combo)
        self.guide_check = QCheckBox("Guía de lectura")
        self.guide_check.toggled.connect(lambda value: self.change_setting("guide", value)); controls.addWidget(self.guide_check)
        self.mirror_check = QCheckBox("Texto en espejo   ·   M")
        self.mirror_check.setToolTip("Invierte solo el texto para un cristal de teleprónter")
        self.mirror_check.toggled.connect(lambda value: self.change_setting("mirror", value)); controls.addWidget(self.mirror_check)
        self.theme_combo = QComboBox()
        for text, key in [("Noche · azul profundo", "noche"), ("Papel · fondo cálido", "papel"), ("Contraste · blanco y negro", "contraste")]:
            self.theme_combo.addItem(text, key)
        self.theme_combo.setAccessibleName("Colores de la lectura")
        self.theme_combo.currentIndexChanged.connect(lambda i: self.change_setting("theme", self.theme_combo.itemData(i)))
        controls.addWidget(self.theme_combo)
        controls.addStretch(1)
        note = label("Hecho para tu voz.\nFunciona sin conexión.", "muted"); controls.addWidget(note)
        controls.addWidget(button("Atajos y ayuda", self.help_dialog, "Todos los atajos · F1", "small"))
        self.previous_button = button("Recuperar guion anterior", self.recover_previous,
                                      "Recupera el guion que reemplazaste por última vez", "small")
        self.previous_button.setEnabled(self.previous_path.exists())
        controls.addWidget(self.previous_button)
        self.panel_scroll.setWidget(panel); body.addWidget(self.panel_scroll)

        workspace = QVBoxLayout(); workspace.setSpacing(10)
        scriptbar = QFrame(); scriptbar.setObjectName("scriptbar")
        strip = QHBoxLayout(scriptbar); strip.setContentsMargins(12, 8, 10, 8)
        self.title_label = label(self.title)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title_label.setMinimumWidth(70)
        strip.addWidget(self.title_label, 1)
        self.open_button = button("Abrir", self.open_dialog, "Abrir TXT, DOCX, ODT, MD o sesión · Ctrl+O", "small")
        self.edit_button = button("Editar", self.edit_script, "Editar o pegar guion · Ctrl+E", "accent")
        self.save_button = button("Guardar", self.export_text, "Guardar texto · Ctrl+S", "small")
        strip.addWidget(self.open_button); strip.addWidget(self.edit_button); strip.addWidget(self.save_button)
        workspace.addWidget(scriptbar)
        self.canvas = ReadingCanvas(); self.canvas.settings = dict(self.settings)
        self.canvas.toggleRequested.connect(self.toggle)
        self.canvas.manualMove.connect(self.manual_move)
        self.canvas.moved.connect(self.update_stats)
        workspace.addWidget(self.canvas, 1)
        body.addLayout(workspace, 1); root.addLayout(body, 1)

        transport = QFrame(); transport.setObjectName("transport")
        layout = QVBoxLayout(transport); layout.setContentsMargins(13, 11, 13, 10); layout.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(10)
        self.play_button = button("▶  Comenzar", self.toggle, "Iniciar / pausar lectura · Espacio", "primary")
        self.play_button.setMinimumWidth(150); top.addWidget(self.play_button)
        self.reset_button = button("↶  Inicio", self.reset, "Volver al principio · Inicio")
        top.addWidget(self.reset_button)
        self.status_label = label("EN PAUSA", "status"); top.addWidget(self.status_label)
        top.addStretch()
        self.time_label = label("00:00", "value"); top.addWidget(self.time_label)
        self.controls_button = button("Ajustes", self.toggle_controls, "Mostrar / ocultar ajustes · C", "small")
        top.addWidget(self.controls_button)
        self.full_button = button("⛶  Pantalla", self.toggle_fullscreen, "Pantalla completa · F11", "small")
        top.addWidget(self.full_button)
        layout.addLayout(top)
        progress = QHBoxLayout(); progress.setSpacing(12)
        self.progress_slider = QSlider(Qt.Horizontal); self.progress_slider.setRange(0, 10000)
        self.progress_slider.setAccessibleName("Posición del guion")
        self.progress_slider.sliderPressed.connect(self.pause)
        self.progress_slider.valueChanged.connect(self.seek_slider)
        progress.addWidget(self.progress_slider, 1)
        self.progress_label = label("0 %", "muted"); self.progress_label.setMinimumWidth(40)
        progress.addWidget(self.progress_label); layout.addLayout(progress)
        self.info_label = label("", "muted"); layout.addWidget(self.info_label)
        root.addWidget(transport)

        shortcuts = QFrame(); shortcuts.setObjectName("shortcuts")
        keys = QGridLayout(shortcuts); keys.setContentsMargins(12, 8, 12, 8); keys.setHorizontalSpacing(16); keys.setVerticalSpacing(5)
        for i, (key, action) in enumerate([("ESPACIO", "iniciar / pausar"), ("↑  ↓", "velocidad"),
            ("←  →", "mover una línea"), ("+  −", "tamaño de letra"), ("F11", "pantalla completa"),
            ("ESC", "pausar / salir"), ("C", "mostrar ajustes"), ("CTRL+E", "editar guion")]):
            item = QLabel(f'<span style="color:#77e5d7; font-weight:700">{key}</span> &nbsp; <span style="color:#bbc5d9">{action}</span>')
            item.setWordWrap(True); item.setMinimumWidth(0)
            keys.addWidget(item, i//4, i%4)
        self.shortcuts_frame = shortcuts; root.addWidget(shortcuts)

    def add_slider(self, layout, key, title, low, high):
        row = QHBoxLayout(); name = label(title); row.addWidget(name); row.addStretch()
        value = label("", "value"); row.addWidget(value); layout.addLayout(row)
        slider = QSlider(Qt.Horizontal); slider.setRange(low, high)
        slider.setAccessibleName(title); name.setBuddy(slider)
        slider.setToolTip(title + (" · píxeles lógicos por segundo" if key == "speed" else ""))
        slider.valueChanged.connect(lambda value, k=key: self.change_setting(k, value))
        self.sliders[key] = slider; self.values[key] = value; layout.addWidget(slider)

    def create_shortcuts(self):
        self.shortcuts = []
        bindings = {"Space": self.toggle, "F11": self.toggle_fullscreen, "Escape": self.escape,
            "Home": self.reset, "End": lambda: self.jump(1.), "C": self.toggle_controls,
            "M": lambda: self.mirror_check.setChecked(not self.mirror_check.isChecked()),
            "Up": lambda: self.sliders["speed"].setValue(self.settings["speed"]+4),
            "Down": lambda: self.sliders["speed"].setValue(self.settings["speed"]-4),
            "Left": lambda: self.manual_move(-self.canvas.line_height),
            "Right": lambda: self.manual_move(self.canvas.line_height),
            "PgUp": lambda: self.manual_move(-self.canvas.height()*.7),
            "PgDown": lambda: self.manual_move(self.canvas.height()*.7),
            "+": lambda: self.sliders["font_size"].setValue(self.settings["font_size"]+2),
            "=": lambda: self.sliders["font_size"].setValue(self.settings["font_size"]+2),
            "-": lambda: self.sliders["font_size"].setValue(self.settings["font_size"]-2),
            "Ctrl+O": self.open_dialog, "Ctrl+E": self.edit_script, "Ctrl+S": self.export_text,
            "Ctrl+Shift+S": self.export_session, "Ctrl+N": self.new_script, "F1": self.help_dialog}
        for key, action in bindings.items():
            shortcut = QShortcut(QKeySequence(key), self); shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(action)
            shortcut.setAutoRepeat(key in ("Up", "Down", "Left", "Right", "+", "-", "="))
            self.shortcuts.append(shortcut)

    def sync_controls(self):
        for key, widget in self.sliders.items():
            widget.blockSignals(True); widget.setValue(self.settings[key]); widget.blockSignals(False)
        for widget, value in [(self.guide_check, self.settings["guide"]), (self.mirror_check, self.settings["mirror"])]:
            widget.blockSignals(True); widget.setChecked(value); widget.blockSignals(False)
        self.countdown_combo.blockSignals(True); self.countdown_combo.setCurrentIndex(self.settings["countdown"]); self.countdown_combo.blockSignals(False)
        self.theme_combo.blockSignals(True); self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.settings["theme"])); self.theme_combo.blockSignals(False)
        self.update_values()

    def update_values(self):
        for key, widget in self.values.items():
            suffix = {"speed": " px/s", "font_size": " px", "width": " %", "spacing": " %"}[key]
            widget.setText(str(self.settings[key]) + suffix)

    def change_setting(self, key, value):
        self.settings[key] = value
        self.canvas.settings = dict(self.settings)
        self.update_values()
        if key in ("font_size", "width", "spacing"):
            self.canvas.rebuild()
        else:
            self.canvas.update()
        self.update_stats()
        self.schedule_save()

    def restore_position(self):
        if self._pending_anchor is not None and self._pending_progress < .9999:
            self.canvas.restore_anchor(self._pending_anchor)
        else:
            self.canvas.set_offset(self._pending_progress * self.canvas.maximum)
        self.title_label.setText(self.title); self.title_label.setToolTip(self.title)
        self.update_stats(); self.canvas.setFocus()
        if self._restore_error:
            QMessageBox.warning(self, "No se pudo recuperar la sesión", "La sesión anterior no se ha podido leer. Se conserva el archivo original.\n\n" + self._restore_error)

    def state(self):
        return {"text": self.text, "title": self.title, "settings": self.settings,
                "progress": self.canvas.progress, "elapsed": self.elapsed,
                "anchor": self.canvas.anchor()}

    def schedule_save(self):
        if not self._initializing and hasattr(self, "save_timer"):
            self.save_timer.start(650)

    def persist(self):
        if self._initializing:
            return True
        try:
            save_session(self.session_path, self.state())
            self._save_error_shown = False
            return True
        except (OSError, ValueError) as exc:
            if not self._save_error_shown:
                self._save_error_shown = True
                self.pause()
                QMessageBox.warning(self, "No se pudo guardar la sesión", "El guion sigue en pantalla, pero no se ha guardado automáticamente. Usa Guardar para conservar el texto.\n\n" + str(exc))
            return False

    def tick(self):
        now = time.monotonic()
        delta = max(0., min(.15, now - self._last_tick)); self._last_tick = now
        if self.countdown_until is not None:
            remaining = self.countdown_until - now
            if remaining <= 0:
                self.countdown_until = None; self.canvas.countdown_number = 0
                self.playing = True; self.update_status()
            else:
                self.canvas.countdown_number = math.ceil(remaining)
            self.canvas.update()
        elif self.playing:
            self.elapsed += delta
            self.canvas.set_offset(self.canvas.offset + self.settings["speed"] * delta)
            if self.canvas.offset >= self.canvas.maximum:
                self.playing = False; self.finished = True
                self.update_status(); self.persist()
        if now - self._last_stats > .2:
            self.update_stats(); self._last_stats = now

    def toggle(self):
        if self.playing or self.countdown_until is not None:
            self.pause(); return
        if not self.text.strip():
            self.edit_script(); return
        if self.canvas.progress >= .9999:
            self.reset()
        self.finished = False
        if self.canvas.offset < 1 and self.settings["countdown"] > 0:
            self.countdown_until = time.monotonic() + self.settings["countdown"]
            self.canvas.countdown_number = self.settings["countdown"]
        else:
            self.playing = True
        self._last_tick = time.monotonic(); self.canvas.update(); self.update_status()

    def pause(self):
        self.playing = False; self.countdown_until = None; self.canvas.countdown_number = 0
        self.canvas.update(); self.update_status(); self.schedule_save()

    def update_status(self):
        if self.countdown_until is not None:
            state, text = "PREPÁRATE", "■  Cancelar"
        elif self.playing:
            state, text = "LEYENDO", "Ⅱ  Pausar"
        elif self.finished:
            state, text = "FIN DEL GUION", "↻  Repetir"
        else:
            state, text = "EN PAUSA", "▶  Continuar" if self.canvas.offset > 1 else "▶  Comenzar"
        self.status_label.setText(state); self.play_button.setText(text)

    def update_stats(self):
        if not hasattr(self, "progress_slider"):
            return
        progress = self.canvas.progress
        if not self.progress_slider.isSliderDown():
            self.progress_slider.blockSignals(True)
            self.progress_slider.setValue(round(progress*10000)); self.progress_slider.blockSignals(False)
        self.progress_label.setText(f"{int(progress*100)} %")
        self.time_label.setText(clock(self.elapsed))
        remaining = (self.canvas.maximum-self.canvas.offset) / max(1, self.settings["speed"])
        self.info_label.setText(f"{self.words} palabras   ·   Restante aprox. {clock(remaining)}   ·   Rueda del ratón para mover y pausar")

    def seek_slider(self, value):
        self.pause(); self.finished = False
        self.canvas.set_offset(self.canvas.maximum * value / 10000.)
        self.update_status()

    def manual_move(self, delta):
        self.pause(); self.finished = False
        self.canvas.set_offset(self.canvas.offset + delta); self.update_status()

    def jump(self, fraction):
        self.pause(); self.canvas.set_offset(self.canvas.maximum*fraction); self.update_status()

    def reset(self):
        self.pause(); self.elapsed = 0.; self.finished = False
        self.canvas.set_offset(0.); self.update_status(); self.update_stats()

    def toggle_controls(self):
        self.panel_scroll.setVisible(not self.panel_scroll.isVisible())
        self.canvas.setFocus()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._normal_geometry: self.restoreGeometry(self._normal_geometry)
            if self._was_maximized: self.showMaximized()
            self.full_button.setText("⛶  Pantalla")
        else:
            self._was_maximized = self.isMaximized(); self._normal_geometry = self.saveGeometry()
            self.showFullScreen(); self.full_button.setText("⛶  Salir")
        self.canvas.setFocus()

    def escape(self):
        self.pause()
        if self.isFullScreen(): self.toggle_fullscreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "tagline"):
            self.tagline.setVisible(self.width() >= 900)
            self.status_label.setVisible(self.width() >= 840)
            if self.width() < 950: self.panel_scroll.hide()

    def edit_script(self):
        self.pause()
        dialog = ScriptEditor(self.text, self)
        if dialog.exec_() == QDialog.Accepted:
            text = validate_text(dialog.editor.toPlainText())
            if text != self.text:
                self.apply_script(text, "Mi guion" if self.title == "Bienvenido a Atril" else self.title)

    def apply_script(self, text, title):
        self.pause()
        if self.text.strip() and self.text != text:
            try:
                save_session(self.previous_path, self.state())
                self.previous_button.setEnabled(True)
            except OSError as exc:
                QMessageBox.warning(self, "No se pudo conservar el guion anterior", str(exc))
                return False
        self.text = text; self.title = title; self.words = word_count(text)
        self.elapsed = 0.; self.finished = False
        self.canvas.set_text(text)
        self.title_label.setText(title); self.title_label.setToolTip(title)
        self.update_status(); self.update_stats(); self.persist()
        return True

    def recover_previous(self):
        self.pause()
        try:
            state = load_session(self.previous_path)
            self.apply_session(state)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "No se pudo recuperar el guion", str(exc))

    def apply_session(self, state):
        if not self.apply_script(state["text"], state["title"]):
            return False
        self.settings = state["settings"]
        self.canvas.settings = dict(self.settings); self.sync_controls(); self.canvas.rebuild(False)
        if state.get("anchor") is not None and state["progress"] < .9999:
            self.canvas.restore_anchor(state["anchor"])
        else:
            self.canvas.set_offset(state["progress"] * self.canvas.maximum)
        self.elapsed = state["elapsed"]
        self.update_status(); self.update_stats(); self.persist()
        return True

    def new_script(self):
        self.pause()
        answer = QMessageBox.question(self, "Nuevo guion", "¿Crear un guion vacío? Si quieres conservar el actual, guárdalo antes con Ctrl+S.",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.apply_script("", "Mi guion"); self.edit_script()

    def open_dialog(self):
        self.pause()
        name, _ = QFileDialog.getOpenFileName(self, "Abrir guion", str(Path.home()),
            "Guiones (*.txt *.md *.docx *.odt *.atril);;Texto (*.txt *.md);;Word y LibreOffice (*.docx *.odt);;Sesión de Atril (*.atril)")
        if name: self.open_path(Path(name))

    def open_path(self, path):
        self.pause()
        try:
            if path.suffix.lower() == ".atril":
                state = load_session(path)
                return self.apply_session(state)
            else:
                return self.apply_script(import_document(path), path.stem)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, ET.ParseError) as exc:
            QMessageBox.warning(self, "No se pudo abrir el guion", str(exc)); return False

    def export_text(self):
        self.pause()
        path = self.save_dialog("Guardar guion de texto", "txt", "Texto UTF-8 (*.txt)")
        if path is None: return
        try:
            atomic_write(path, self.text)
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))

    def safe_title(self):
        import re
        return re.sub(r'[^\w .-]', '_', self.title).strip('. ')[:100] or "Mi-guion"

    def export_session(self):
        self.pause()
        path = self.save_dialog("Guardar sesión y punto de lectura", "atril", "Sesión de Atril (*.atril)")
        if path is None: return
        try:
            save_session(path, self.state())
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))

    def save_dialog(self, title, extension, file_filter):
        dialog = QFileDialog(self, title, str(Path.home()))
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setNameFilter(file_filter)
        dialog.setDefaultSuffix(extension)
        dialog.selectFile(self.safe_title() + "." + extension)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return Path(dialog.selectedFiles()[0])

    def help_dialog(self):
        self.pause()
        dialog = QDialog(self); dialog.setWindowTitle("Atajos y ayuda · Atril")
        dialog.resize(580, 580)
        outer = QVBoxLayout(dialog); outer.setContentsMargins(22, 20, 22, 20)
        outer.addWidget(label("Tu voz. Tu ritmo.", "brand"))
        view = QPlainTextEdit(); view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit {font-size: 14px;}")
        view.setPlainText("ATRIL TELEPRÓNTER · " + VERSION + "\nPaco Estrada · Compilando Podcast\n\n"
            "ESPACIO / clic en el texto  Iniciar o pausar\n↑ / ↓  Aumentar o reducir velocidad\n← / →  Retroceder o avanzar una línea\nAvPág / RePág  Mover una pantalla\n+ / −  Cambiar tamaño de letra\nInicio / Fin  Ir al inicio o al final\nRueda  Mover el guion y pausar\nF11  Entrar o salir de pantalla completa\nEsc  Pausar y salir de pantalla completa\nC  Mostrar u ocultar ajustes\nM  Invertir el texto para un cristal\nCtrl+E  Editar o pegar guion\nCtrl+O  Abrir guion o sesión\nCtrl+S  Guardar guion como TXT\nCtrl+Mayús+S  Guardar sesión .atril\nCtrl+N  Crear guion vacío\nF1  Mostrar esta ayuda\n\n"
            "La cuenta atrás se usa al comenzar desde el inicio. Al reanudar una pausa, el texto continúa inmediatamente.\n\n"
            "La velocidad se expresa en píxeles lógicos por segundo. El tiempo restante es orientativo y depende del tamaño de letra, el ancho y el ritmo.\n\n"
            "TXT y MD se leen como texto. DOCX y ODT se importan sin formato; no se muestran imágenes, notas ni comentarios.\n\n"
            "El guion, ajustes y posición se guardan automáticamente en este ordenador. Una sesión .atril permite llevarlos a otro equipo. No hay sincronización en la nube.\n\n"
            "Atril desplaza el texto a velocidad fija; no escucha tu voz ni graba audio o vídeo.\n\n"
            "Software libre · GPL-3.0-or-later\nLogo de Compilando Podcast: su titular.")
        outer.addWidget(view, 1)
        outer.addWidget(button("Listo", dialog.accept, name="primary")); dialog.exec_()

    def closeEvent(self, event):
        self.pause()
        if not self.persist():
            reply = QMessageBox.question(self, "Cerrar sin guardar", "No se ha podido guardar la sesión. ¿Cerrar de todos modos?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
        event.accept()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Atril Teleprónter · Paco Estrada / Compilando Podcast")
    parser.add_argument("guion", nargs="?", help="TXT, MD, DOCX, ODT o sesión .atril")
    parser.add_argument("--version", action="version", version="Atril Teleprónter " + VERSION)
    args = parser.parse_args()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QApplication.setApplicationName("atril-teleprompter")
    QApplication.setApplicationDisplayName("Atril Teleprónter")
    QApplication.setOrganizationName("Paco Estrada")
    QApplication.setDesktopFileName("es.compilando.AtrilTeleprompter")
    app = QApplication(sys.argv)
    app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    window = AtrilWindow(); window.show()
    if args.guion:
        QTimer.singleShot(10, lambda: window.open_path(Path(args.guion)))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
