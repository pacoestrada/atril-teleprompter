"""Recording strip for Atril: input, gain, meters, waveform and native Save As."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import shutil
import threading
import wave
from PyQt5.QtCore import Qt, QThread, QTimer, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
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
    def __init__(self):
        super().__init__(); self.peak = self.rms = 0.; self.clipped = False
        self.setFixedSize(155, 48)
        self.setAccessibleName('Vúmetro: nivel RMS y pico en dBFS')
        self.setToolTip('Barra: nivel RMS · marca: pico · rojo: saturación de entrada o de ganancia')

    def set_levels(self, peak, rms, clipped):
        self.peak, self.rms, self.clipped = peak, rms, clipped; self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#0c1322')); painter.drawRoundedRect(QRectF(self.rect()), 7, 7)
        for index in range(30):
            decibels = -60 + (index + 1) * 2
            color = '#5ed9b3' if decibels < -12 else ('#f4ca62' if decibels < -3 else '#fa7787')
            painter.setBrush(QColor(color if decibels <= dbfs(self.rms) else '#253249'))
            painter.drawRect(7 + index * 4, 7, 3, 13)
        x = 7 + round((dbfs(self.peak) + 60) / 60 * 119)
        painter.setPen(QPen(QColor('#f7f6ff'), 2)); painter.drawLine(x, 5, x, 22)
        painter.setPen(QColor('#ff8292' if self.clipped else '#b1bfd6'))
        level = f'{dbfs(self.peak):.1f} dBFS' if self.peak > .001 else '−∞ dBFS'
        painter.drawText(7, 39, 'SATURACIÓN' if self.clipped else level)
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
