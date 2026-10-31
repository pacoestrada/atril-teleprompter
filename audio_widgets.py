"""Recording strip for Atril: input, gain, meters, waveform and native Save As."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import math
import shutil
import threading
import time
import wave
from PyQt5.QtCore import Qt, QThread, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient)
from PyQt5.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QSizePolicy,
    QSlider, QVBoxLayout, QWidget)
from audio_core import FORMATS, ExportCancelled, dbfs, export_audio
from audio_capture import AUDIO_AVAILABLE, AudioRecorder


def text_label(text, name=None):
    widget = QLabel(text); widget.setTextFormat(Qt.PlainText)
    if name: widget.setObjectName(name)
    return widget


def make_button(text, action, tip):
    widget = QPushButton(text); widget.setObjectName('audioButton')
    widget.setToolTip(tip); widget.setAccessibleName(tip)
    widget.clicked.connect(action)
    return widget


def timestamp(seconds):
    hours, rest = divmod(int(seconds), 3600); minutes, seconds = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


class Waveform(QWidget):
    def __init__(self):
        super().__init__()
        self.points = []; self.recording = False
        self.setMinimumSize(160, 48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(48)
        self.setAccessibleName('Forma de onda en directo: últimos cinco segundos')
        self.setToolTip('Envolvente de los últimos 5 segundos de audio · amplitud después de la ganancia')

    def set_points(self, points):
        self.points = points; self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#0c1322'))
        painter.drawRoundedRect(QRectF(self.rect()), 7, 7)
        center = self.height() / 2; width = self.width() - 16
        painter.setPen(QPen(QColor('#283c53'), 1))
        painter.drawLine(8, int(center), self.width() - 8, int(center))
        step = width / 250
        painter.setPen(QPen(QColor('#6be5cd' if self.recording else '#a995f1'), max(1., step * .7)))
        offset = 250 - len(self.points)
        for i, (peak, rms) in enumerate(self.points):
            height = max(.5, peak * (center - 5)); x = 8 + (offset + i) * step
            painter.drawLine(int(x), int(center - height), int(x), int(center + height))
        if not self.points:
            painter.setPen(QColor('#8797b4'))
            painter.drawText(self.rect(), Qt.AlignCenter, 'Forma de onda · últimos 5 s')
        painter.end()


class LevelMeter(QWidget):
    """A simulated moving-coil VU; clipping still comes directly from capture.

    The scale is linear in amplitude, with 0 VU chosen as -18 dBFS RMS.
    This is a visual reference, not a change to the recorded samples or gain.
    """
    REFERENCE_RMS = 10 ** (-18 / 20)
    SCALE_MAX = 10 ** (3 / 20)

    def __init__(self):
        super().__init__(); self.peak = self.rms = 0.; self.clipped = False
        self._position = self._velocity = self._target = 0.
        self._last_frame = time.monotonic()
        self.animation = QTimer(self)
        self.animation.setTimerType(Qt.PreciseTimer)
        self.animation.setInterval(16)
        self.animation.timeout.connect(self._animate)
        self.setFixedSize(208, 88)
        self.setAccessibleName('Vúmetro analógico: nivel de voz y piloto de saturación')
        self.setToolTip('Aguja: nivel RMS con inercia · 0 VU = −18 dBFS RMS\n'
                        'Lectura inferior: pico en dBFS · piloto rojo: saturación de entrada o de ganancia\n'
                        'La zona roja de la escala indica nivel por encima de la referencia; '
                        'el piloto avisa de saturación real.')
        self.set_levels(0., 0., False)

    def set_levels(self, peak, rms, clipped):
        changed = (peak, rms, clipped) != (self.peak, self.rms, self.clipped)
        self.peak, self.rms, self.clipped = peak, rms, clipped
        self._target = max(0., min(1., rms / self.REFERENCE_RMS / self.SCALE_MAX))
        self.setAccessibleDescription('Saturación de entrada o de ganancia' if clipped
            else f'Pico: {self._peak_text()}. Referencia: 0 VU equivale a −18 dBFS RMS.')
        self._start_animation()
        if changed: self.update()

    def _peak_text(self):
        return f'{dbfs(self.peak):.1f} dBFS' if self.peak > .001 else '−∞ dBFS'

    def _start_animation(self):
        if (self.isVisible() and not self.animation.isActive()
                and (abs(self._position - self._target) > .0001 or abs(self._velocity) > .001)):
            self._last_frame = time.monotonic()
            self.animation.start()

    def _animate(self):
        now = time.monotonic()
        elapsed = max(0., now - self._last_frame)
        self._last_frame = now
        # Exact critically damped spring step: smooth starts and returns,
        # approximately 300 ms to settle, independent of timer jitter.
        omega = 20.
        offset = self._position - self._target
        momentum = self._velocity + omega * offset
        decay = math.exp(-omega * elapsed)
        self._position = self._target + (offset + momentum * elapsed) * decay
        self._velocity = (self._velocity - omega * momentum * elapsed) * decay
        if abs(self._position - self._target) < .0001 and abs(self._velocity) < .001:
            self._position = self._target; self._velocity = 0.
            self.animation.stop()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._start_animation()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    @staticmethod
    def _dial_point(position, radius_x=86., radius_y=43.):
        angle = math.radians(-62 + 124 * position)
        return QPointF(104 + radius_x * math.sin(angle), 66 - radius_y * math.cos(angle))

    @staticmethod
    def _font(painter, size, bold=False, family='DejaVu Sans'):
        font = QFont(family); font.setPixelSize(size); font.setBold(bold)
        painter.setFont(font)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        # Draw in logical coordinates: Qt keeps edges and lettering crisp on HiDPI.
        casing = QLinearGradient(0, 0, 0, 88)
        casing.setColorAt(0, QColor('#59616a')); casing.setColorAt(.08, QColor('#252b32'))
        casing.setColorAt(1, QColor('#10151c'))
        painter.setPen(QPen(QColor('#626770'), 1)); painter.setBrush(casing)
        painter.drawRoundedRect(QRectF(.5, .5, 207, 87), 9, 9)

        face = QRectF(7, 6, 194, 62)
        paper = QLinearGradient(0, 6, 0, 68)
        paper.setColorAt(0, QColor('#ad8c50')); paper.setColorAt(.18, QColor('#e9cc8d'))
        paper.setColorAt(.55, QColor('#fae8b5')); paper.setColorAt(1, QColor('#edc575'))
        painter.setPen(QPen(QColor('#17191a'), 2)); painter.setBrush(paper)
        painter.drawRoundedRect(face, 5, 5)
        painter.save()
        window = QPainterPath(); window.addRoundedRect(face.adjusted(1, 1, -1, -1), 4, 4)
        painter.setClipPath(window)
        painter.setPen(Qt.NoPen)
        for x in (33, 175):
            light = QRadialGradient(QPointF(x, 62), 80)
            light.setColorAt(0, QColor(255, 246, 189, 155))
            light.setColorAt(1, QColor(255, 235, 157, 0))
            painter.setBrush(light); painter.drawRect(face)

        zero = 1 / self.SCALE_MAX
        for start, end, color in ((0., zero, '#403729'), (zero, 1., '#b3372b')):
            arc = QPainterPath(); arc.moveTo(self._dial_point(start))
            for step in range(1, 61):
                arc.lineTo(self._dial_point(start + (end - start) * step / 60))
            painter.setPen(QPen(QColor(color), 1.3)); painter.setBrush(Qt.NoBrush)
            painter.drawPath(arc)

        labels = {-20: '−20', -10: '−10', -5: '−5', 0: '0', 3: '+3'}
        self._font(painter, 9, True)
        for vu in (-20, -15, *range(-10, 4)):
            position = 10 ** (vu / 20) / self.SCALE_MAX
            major = vu in labels
            painter.setPen(QPen(QColor('#b3372b' if vu > 0 else '#403729'), 1.3 if major else .8))
            painter.drawLine(self._dial_point(position),
                             self._dial_point(position, 94 if major else 90, 49 if major else 46))
            if major:
                point = self._dial_point(position, 103, 57 if vu in (-20, 3) else 52)
                painter.drawText(QRectF(point.x() - 13, point.y() - 6, 26, 12), Qt.AlignCenter, labels[vu])

        self._font(painter, 15, True, 'DejaVu Serif')
        painter.setPen(QColor('#574529'))
        painter.drawText(QRectF(80, 32, 48, 21), Qt.AlignCenter, 'VU')

        # The shadow and fine red tip give depth without obscuring the scale.
        tip = self._dial_point(max(0., min(1., self._position)), 96, 49)
        pivot = QPointF(104, 68)
        painter.setPen(QPen(QColor(70, 43, 17, 55), 2.5))
        painter.drawLine(pivot + QPointF(1.5, 1), tip + QPointF(1.5, 1))
        painter.setPen(QPen(QColor('#2a2621'), 1.4)); painter.drawLine(pivot, tip)
        end = tip + (pivot - tip) * .18
        painter.setPen(QPen(QColor('#ae3528'), 1.6)); painter.drawLine(tip, end)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#2d2923'))
        painter.drawEllipse(pivot, 6, 6)

        # Capture already holds clipping for 1.5 s; never smooth that warning.
        lamp_center = QPointF(104, 58)
        if self.clipped:
            halo = QRadialGradient(lamp_center, 12)
            halo.setColorAt(0, QColor(255, 46, 26, 180)); halo.setColorAt(1, QColor(255, 46, 26, 0))
            painter.setBrush(halo); painter.drawEllipse(lamp_center, 12, 12)
        painter.setPen(QPen(QColor('#6a4833'), 1)); painter.setBrush(QColor('#41241d'))
        painter.drawEllipse(lamp_center, 4.5, 4.5)
        lens = QRadialGradient(QPointF(103, 57), 5)
        lens.setColorAt(0, QColor('#fff2c5' if self.clipped else '#a15c44'))
        lens.setColorAt(.4, QColor('#ff5a38' if self.clipped else '#703627'))
        lens.setColorAt(1, QColor('#bc2015' if self.clipped else '#42281f'))
        painter.setPen(Qt.NoPen); painter.setBrush(lens); painter.drawEllipse(lamp_center, 3.5, 3.5)
        painter.restore()

        self._font(painter, 10, self.clipped)
        painter.setPen(QColor('#ff8c73' if self.clipped else '#e1d2af'))
        painter.drawText(QRectF(18, 71, 172, 14), Qt.AlignCenter,
                         'SATURACIÓN' if self.clipped else 'PICO  ' + self._peak_text())
        for x in (9, 199):
            painter.setPen(QPen(QColor('#4b5158'), 1)); painter.setBrush(QColor('#242a31'))
            painter.drawEllipse(QPointF(x, 79), 2.5, 2.5)
            painter.drawLine(QPointF(x - 1, 80), QPointF(x + 1, 78))
        painter.end()


class ExportJob(QThread):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    progress = pyqtSignal(int)

    def __init__(self, source, destination, kind, parent=None):
        super().__init__(parent)
        self.source, self.destination, self.kind = source, destination, kind
        self.cancel_event = threading.Event()

    def run(self):
        try:
            result = export_audio(self.source, self.destination, self.kind, self.cancel_event, self.progress.emit)
            self.succeeded.emit(str(result))
        except ExportCancelled: self.cancelled.emit()
        except Exception as exc: self.failed.emit(str(exc))


class RecorderBar(QFrame):
    def __init__(self, recovery_dir, parent=None):
        super().__init__(parent)
        self.setObjectName('recorder')
        self.recorder = AudioRecorder(recovery_dir, self)
        self.last_folder = Path.home()
        self.job = None; self.progress_dialog = None
        self._close_after_save = False
        self._export_success = False
        self.build_ui()
        self.recorder.changed.connect(self.refresh_state)
        self.recorder.failed.connect(self.show_error)
        self.recorder.levels.connect(self.meter.set_levels)
        self.recorder.waveform.connect(self.wave.set_points)
        self.clock_timer = QTimer(self); self.clock_timer.setInterval(100)
        self.clock_timer.timeout.connect(self.refresh_clock); self.clock_timer.start()
        self.refresh_devices()
        self.refresh_state()

    def build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(12, 9, 12, 9); root.setSpacing(6)
        top = QHBoxLayout(); top.setSpacing(7)
        title = text_label('TU VOZ', 'section'); top.addWidget(title)
        self.devices = QComboBox(); self.devices.setMinimumWidth(110)
        self.devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.devices.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.devices.setAccessibleName('Dispositivo de entrada de audio')
        self.devices.setToolTip('Micrófonos e interfaces de audio disponibles en este ordenador')
        self.devices.currentIndexChanged.connect(self.device_changed)
        top.addWidget(self.devices, 1)
        self.refresh_button = make_button('↻', self.refresh_devices, 'Actualizar dispositivos de entrada')
        self.refresh_button.setFixedWidth(32); top.addWidget(self.refresh_button)
        self.monitor_button = make_button('Probar micro', self.toggle_monitor, 'Activar o desactivar la prueba de entrada sin grabar')
        self.monitor_button.setCheckable(True); top.addWidget(self.monitor_button)
        gain_label = text_label('Ganancia', 'muted'); top.addWidget(gain_label)
        self.gain = QSlider(Qt.Horizontal); self.gain.setRange(-24, 24); self.gain.setValue(0)
        self.gain.setMinimumWidth(65); self.gain.setMaximumWidth(120)
        self.gain.setAccessibleName('Ganancia digital de grabación en decibelios')
        self.gain.setToolTip('Ganancia digital aplicada a la grabación · −24 a +24 dB · 0 dB conserva el nivel')
        self.gain.valueChanged.connect(self.change_gain); gain_label.setBuddy(self.gain)
        top.addWidget(self.gain)
        self.gain_value = text_label('+0 dB', 'value'); self.gain_value.setFixedWidth(48)
        top.addWidget(self.gain_value); root.addLayout(top)
        visual = QHBoxLayout(); visual.setSpacing(8)
        self.wave = Waveform(); self.meter = LevelMeter()
        visual.addWidget(self.wave, 1); visual.addWidget(self.meter); root.addLayout(visual)
        controls = QHBoxLayout(); controls.setSpacing(7)
        self.record_button = make_button('● Grabar', self.record, 'Iniciar grabación · Ctrl+R')
        self.record_button.setObjectName('recordButton')
        self.pause_button = make_button('Ⅱ Pausa', self.recorder.pause, 'Pausar o reanudar audio · Ctrl+R')
        self.stop_button = make_button('■ Detener', self.recorder.stop, 'Detener grabación · Ctrl+Mayús+R')
        self.save_button = make_button('Guardar grabación', self.save, 'Guardar audio en WAV, FLAC o MP3 · Ctrl+Alt+S')
        self.recover_button = make_button('Recuperar', self.recover, 'Recuperar una toma pendiente de una sesión anterior')
        for widget in (self.record_button, self.pause_button, self.stop_button, self.save_button, self.recover_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        self.clock = text_label('00:00:00', 'value'); controls.addWidget(self.clock)
        root.addLayout(controls)
        bottom = QHBoxLayout()
        self.status = text_label('', 'muted')
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bottom.addWidget(self.status, 1)
        self.hints = text_label('Ctrl+R grabar/pausa · Ctrl+Mayús+R detener', 'muted')
        bottom.addWidget(self.hints); root.addLayout(bottom)

    def refresh_devices(self):
        if self.recorder.state in ('recording', 'paused'): return
        selected = self.devices.currentText()
        self.recorder.stop_monitor()
        self.devices.blockSignals(True); self.devices.clear()
        default = self.recorder.default_name()
        for device in self.recorder.devices():
            self.devices.addItem(device.deviceName(), device)
        index = self.devices.findText(selected)
        if index < 0: index = self.devices.findText(default)
        if index >= 0: self.devices.setCurrentIndex(index)
        self.devices.blockSignals(False)
        self.refresh_state()

    def device_changed(self):
        if self.recorder.state == 'monitoring': self.recorder.monitor(self.devices.currentData())
        self.devices.setToolTip(self.devices.currentText() or 'No hay entradas de audio disponibles')

    def toggle_monitor(self):
        if self.recorder.state == 'monitoring': self.recorder.stop_monitor()
        else: self.recorder.monitor(self.devices.currentData())
        self.refresh_state()

    def change_gain(self, value):
        self.recorder.gain_db = value; self.gain_value.setText(f'{value:+d} dB')

    def record_shortcut(self):
        if self.recorder.state in ('recording', 'paused'): self.recorder.pause()
        else: self.record()

    def record(self):
        if self.job or not self.devices.count(): return
        if self.recorder.dirty:
            answer = QMessageBox.question(self, 'Conservar la toma anterior',
                'Hay una grabación sin guardar. ¿Qué quieres hacer antes de empezar otra?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Save: self.save(); return
            if answer != QMessageBox.Discard: return
            self.recorder.discard()
        self.recorder.start(self.devices.currentData())

    def refresh_clock(self):
        self.clock.setText(timestamp(self.recorder.duration))

    def refresh_state(self):
        state = self.recorder.state; active = state in ('recording', 'paused'); busy = self.job is not None
        available = self.devices.count() > 0
        self.devices.setEnabled(not active and not busy)
        self.refresh_button.setEnabled(not active and not busy)
        self.monitor_button.setEnabled(not active and not busy and available)
        self.monitor_button.setChecked(state == 'monitoring')
        self.record_button.setEnabled(not active and not busy and available)
        self.record_button.setText('● Nueva toma' if self.recorder.path else '● Grabar')
        self.pause_button.setEnabled(active and not busy)
        self.pause_button.setText('▶ Reanudar' if state == 'paused' else 'Ⅱ Pausa')
        self.stop_button.setEnabled((active or state == 'monitoring') and not busy)
        self.save_button.setEnabled(not active and not busy and self.recorder.duration > 0)
        self.gain.setEnabled(not busy)
        self.recover_button.setVisible(bool(self.recorder.recovery_files()))
        self.recover_button.setEnabled(not active and not busy)
        self.wave.recording = state == 'recording'
        states = {'idle': 'Micrófono cerrado · listo para grabar', 'monitoring': 'Probando entrada · no se está guardando audio',
            'recording': '● GRABANDO', 'paused': 'Ⅱ Audio en pausa', 'stopped': 'Toma sin guardar' if self.recorder.dirty else 'Grabación guardada'}
        text = states[state]
        if state in ('recording', 'paused', 'stopped') and self.recorder.path:
            text += f' · {self.recorder.rate / 1000:g} kHz · ' + ('mono' if self.recorder.channels == 1 else 'estéreo')
        if not available and state == 'idle':
            text = 'No se detecta entrada · conecta un micrófono y pulsa ↻' if AUDIO_AVAILABLE else 'Falta el componente Qt Multimedia'
        if busy: text = 'Guardando grabación…'
        self.status.setText(text); self.status.setToolTip(text); self.refresh_clock()

    def show_error(self, message):
        self.refresh_state()
        self.status.setText(message.splitlines()[0]); self.status.setToolTip(message)
        QMessageBox.warning(self, 'Grabación de audio', message)

    def save(self):
        if self.job or self.recorder.state in ('recording', 'paused') or self.recorder.duration <= 0: return False
        self.recorder.stop_monitor()
        formats = list(FORMATS) if shutil.which('ffmpeg') else ['wav']
        filter_formats = {f'{FORMATS[kind]} (*.{kind})': kind for kind in formats}
        filters = list(filter_formats)
        kind = formats[0]
        dialog = QFileDialog(self, 'Guardar grabación', str(self.last_folder))
        dialog.setAcceptMode(QFileDialog.AcceptSave); dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setLabelText(QFileDialog.LookIn, 'Carpeta')
        dialog.setLabelText(QFileDialog.FileName, 'Nombre del archivo')
        dialog.setLabelText(QFileDialog.FileType, 'Formato de audio')
        dialog.setLabelText(QFileDialog.Accept, 'Guardar')
        dialog.setLabelText(QFileDialog.Reject, 'Cancelar')
        dialog.setNameFilters(filters); dialog.selectNameFilter(filters[0])
        dialog.setDefaultSuffix(kind)
        # Leave the proposed title independent of the chosen audio format.
        dialog.selectFile('Atril-' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))

        def select_format(value):
            nonlocal kind
            # Some native dialogs emit an empty filter during initialization.
            # Preserve the last valid choice instead of raising in a Qt slot.
            selected = filter_formats.get(value)
            if selected is not None:
                kind = selected
                dialog.setDefaultSuffix(kind)

        dialog.filterSelected.connect(select_format)
        if dialog.exec_() != QDialog.Accepted: return False
        files = dialog.selectedFiles()
        if not files: return False
        select_format(dialog.selectedNameFilter())
        original = Path(files[0])
        destination = original
        # Remove only known audio suffixes, including old .wav.mp3 chains.
        # Other dots (episode numbers, revisions, etc.) belong to the title.
        while destination.suffix.lower().lstrip('.') in FORMATS:
            destination = destination.with_suffix('')
        destination = destination.with_name(destination.name + '.' + kind)
        if destination != original:
            # The native dialog may have confirmed a different path. Protect
            # the actual output file after extension normalization as well.
            if destination.exists() and QMessageBox.question(self, 'Sustituir grabación',
                f'Ya existe {destination.name}. ¿Quieres sustituirlo?', QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes: return False
        self.start_export(destination, kind)
        return True

    def start_export(self, destination, kind):
        self._export_success = False
        self.progress_dialog = QProgressDialog('Guardando la grabación…', 'Cancelar', 0, 0, self)
        self.progress_dialog.setWindowTitle('Guardar grabación')
        self.progress_dialog.setWindowModality(Qt.WindowModal); self.progress_dialog.setMinimumDuration(0)
        self.job = ExportJob(self.recorder.path, destination, kind, self)
        self.progress_dialog.canceled.connect(self.job.cancel_event.set)
        self.job.succeeded.connect(self.export_success)
        self.job.failed.connect(self.export_failed)
        self.job.cancelled.connect(self.export_cancelled)
        self.job.finished.connect(self.export_finished)
        self.refresh_state(); self.job.start(); self.progress_dialog.show()

    def export_success(self, path):
        self.recorder.dirty = False; self.last_folder = Path(path).parent
        self._export_success = True; self.status.setToolTip(path)

    def export_failed(self, message):
        self._close_after_save = False
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.warning(self, 'No se pudo guardar la grabación', message + '\n\nLa toma se conserva para volver a intentarlo.')

    def export_cancelled(self):
        self._close_after_save = False

    def export_finished(self):
        if self.progress_dialog:
            self.progress_dialog.close(); self.progress_dialog.deleteLater(); self.progress_dialog = None
        self.job.deleteLater(); self.job = None
        self.refresh_state()
        if self._export_success and self._close_after_save:
            self._close_after_save = False; QTimer.singleShot(0, self.window().close)

    def recover(self):
        if self.recorder.dirty:
            QMessageBox.information(self, 'Conservar la toma actual', 'Guarda la grabación actual antes de recuperar otra.'); return
        path, _ = QFileDialog.getOpenFileName(self, 'Recuperar grabación de Atril',
            str(self.recorder.recovery_dir), 'Tomas recuperables (toma-*.wav)')
        if path:
            try: self.recorder.recover(path)
            except (OSError, ValueError, EOFError, wave.Error) as exc: self.show_error(str(exc))

    def request_close(self):
        if self.job:
            QMessageBox.information(self, 'Grabación en proceso', 'Espera a que termine el guardado o cancélalo antes de cerrar.')
            return False
        if self.recorder.dirty and self.recorder.duration <= 0:
            self.recorder.discard()
        if self.recorder.dirty:
            answer = QMessageBox.question(self, 'Guardar la grabación',
                'Hay una toma sin guardar. ¿Quieres guardarla antes de cerrar?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel: return False
            if answer == QMessageBox.Save:
                self.recorder.stop(); self._close_after_save = True
                if not self.save(): self._close_after_save = False
                return False
            self.recorder.discard()
        self.recorder.shutdown(); self.clock_timer.stop(); return True
