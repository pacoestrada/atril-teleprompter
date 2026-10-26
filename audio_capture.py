"""Qt audio input, live metering and recoverable local recording."""
from __future__ import annotations
from collections import deque
from pathlib import Path
import time
import wave
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
try:
    from PyQt5.QtMultimedia import QAudio, QAudioDeviceInfo, QAudioFormat, QAudioInput
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

from audio_core import WaveTake, pcm16


class AudioRecorder(QObject):
    changed = pyqtSignal()
    failed = pyqtSignal(str)
    levels = pyqtSignal(float, float, bool)
    waveform = pyqtSignal(object)

    def __init__(self, recovery_dir, parent=None):
        super().__init__(parent)
        self.recovery_dir = Path(recovery_dir)
        self.state = 'idle'
        self.audio = self.source = self.take = None
        self.path = None
        self.duration = 0.
        self.dirty = False
        self.gain_db = 0.
        self.pending = b''
        self.history = deque(maxlen=250)
        self._peak = self._rms = 0.
        self._clip_until = 0.
        self._last_audio = 0.
        self._closing = False
        self.rate, self.channels = 48000, 1
        self.visual_timer = QTimer(self)
        self.visual_timer.setInterval(40)
        self.visual_timer.timeout.connect(self._visuals)
        self.visual_timer.start()

    @staticmethod
    def devices():
        if not AUDIO_AVAILABLE: return []
        return [device for device in QAudioDeviceInfo.availableDevices(QAudio.AudioInput)
                if not device.isNull() and device.deviceName().strip()]

    @staticmethod
    def default_name():
        return QAudioDeviceInfo.defaultInputDevice().deviceName() if AUDIO_AVAILABLE else ''

    @staticmethod
    def choose_format(device):
        for rate in (48000, 44100, 32000, 22050, 16000, 8000):
            for channels in (1, 2):
                fmt = QAudioFormat()
                fmt.setCodec('audio/pcm'); fmt.setSampleRate(rate); fmt.setChannelCount(channels)
                fmt.setSampleSize(16); fmt.setSampleType(QAudioFormat.SignedInt)
                fmt.setByteOrder(QAudioFormat.LittleEndian)
                if device.isFormatSupported(fmt): return fmt
        raise RuntimeError("Esta entrada no admite PCM de 16 bits mono o estéreo. Prueba otra entrada o la predeterminada del sistema.")

    def _open_input(self, device):
        if not AUDIO_AVAILABLE: raise RuntimeError("Falta Qt Multimedia. Instala el paquete de audio de Atril.")
        if device is None or device.isNull(): raise RuntimeError("No hay una entrada de audio disponible")
        fmt = self.choose_format(device)
        self.rate, self.channels = fmt.sampleRate(), fmt.channelCount()
        self.pending = b''
        self._clip_until = 0.
        self.audio = QAudioInput(device, fmt, self)
        self.audio.setBufferSize(self.rate * self.channels * 2 // 5)
        self.audio.stateChanged.connect(self._audio_state)
        self.source = self.audio.start()
        if self.source is None or self.audio.error() != QAudio.NoError:
            self._close_input()
            raise RuntimeError("No se puede abrir esa entrada. Comprueba su conexión y los permisos de audio.")
        self.source.readyRead.connect(self._drain)
        self._last_audio = time.monotonic()

    def _close_input(self):
        self._closing = True
        if self.audio is not None:
            if self.source is not None:
                try: self.source.readyRead.disconnect(self._drain)
                except (TypeError, RuntimeError): pass
            self.audio.stop(); self.audio.deleteLater()
        self.audio = self.source = None
        self._closing = False
        self.pending = b''
        self._peak = self._rms = 0.

    def monitor(self, device):
        if self.state in ('recording', 'paused'): return
        self._close_input()
        try:
            self._open_input(device)
            self.state = 'monitoring'; self.history.clear(); self.changed.emit()
        except Exception as exc:
            self.state = 'stopped' if self.path else 'idle'; self.failed.emit(str(exc)); self.changed.emit()

    def stop_monitor(self):
        if self.state == 'monitoring':
            self._close_input(); self.state = 'stopped' if self.path else 'idle'; self.changed.emit()

    def start(self, device):
        if self.state in ('recording', 'paused'): return
        if self.dirty:
            raise RuntimeError("Guarda o descarta la toma anterior antes de empezar otra")
        self._close_input()
        try:
            self._open_input(device)
            new_take = WaveTake(self.recovery_dir, self.rate, self.channels)
        except Exception as exc:
            self._close_input(); self.state = 'stopped' if self.path else 'idle'
            self.failed.emit(str(exc)); self.changed.emit(); return
        if self.path: self.path.unlink(missing_ok=True)
        self.take = new_take; self.path = self.take.path
        self.duration = 0.; self.dirty = True; self.history.clear()
        self.state = 'recording'; self.changed.emit()

    def _drain(self):
        if self.source is not None:
            self.consume(bytes(self.source.readAll()))

    def consume(self, data):
        """Accept actual captured PCM; exposed separately for deterministic tests."""
        if self.state not in ('recording', 'monitoring', 'paused'): return
        self._last_audio = time.monotonic()
        # Always drain the device during pause so resume never writes old audio.
        if self.state == 'paused': self.pending = b''; return
        self.pending += data
        # Fixed 20 ms blocks keep waveform time scale independent of backend packets.
        block_size = max(1, self.rate // 50) * 2 * self.channels
        try:
            while len(self.pending) >= block_size:
                block, self.pending = self.pending[:block_size], self.pending[block_size:]
                self._process(block)
        except (OSError, ValueError, wave.Error) as exc:
            self._fail("No se pudo continuar la grabación. La toma disponible se conserva.\n" + str(exc))

    def _process(self, block):
        processed, peak, rms, clipped = pcm16(block, self.gain_db)
        self._peak = max(self._peak, peak); self._rms = rms
        if clipped: self._clip_until = time.monotonic() + 1.5
        self.history.append((peak, rms))
        if self.state == 'recording' and self.take is not None:
            self.take.append(processed)
            self.duration = self.take.duration

    def pause(self):
        if self.state == 'recording':
            self._drain(); self._flush_tail()
            if self.state == 'recording': self.state = 'paused'
            self.changed.emit()
        elif self.state == 'paused':
            self._drain(); self.pending = b''
            self.state = 'recording'; self.changed.emit()

    def _flush_tail(self):
        size = len(self.pending) // (2 * self.channels) * (2 * self.channels)
        if size:
            block, self.pending = self.pending[:size], b''
            try: self._process(block)
            except (OSError, ValueError, wave.Error) as exc: self._fail(str(exc))

    def stop(self):
        if self.state == 'recording':
            self._drain(); self._flush_tail()
        self._close_input()
        self.state = 'stopped' if self.path else 'idle'
        if self.take is not None:
            try: self.take.finish()
            except (OSError, wave.Error) as exc: self.failed.emit("Error al cerrar la toma: " + str(exc))
            self.take = None
        self.changed.emit()

    def _fail(self, message):
        # Set state first, so stop does not recurse through a failing drain.
        self.state = 'stopped'; self.stop(); self.failed.emit(message)

    def _audio_state(self, state):
        if self._closing or self.audio is None: return
        if state == QAudio.StoppedState and self.audio.error() != QAudio.NoError:
            QTimer.singleShot(0, lambda: self._fail("La entrada de audio se ha desconectado o ha dejado de responder. Guarda la toma disponible.")
                              if self.audio is not None else None)

    def _visuals(self):
        if self.state in ('recording', 'monitoring') and time.monotonic() - self._last_audio > 5:
            self._fail("La entrada no está entregando audio. Comprueba el dispositivo y guarda la toma disponible.")
        self.levels.emit(self._peak, self._rms, time.monotonic() < self._clip_until)
        self.waveform.emit(list(self.history))
        self._peak *= .65; self._rms *= .75

    def discard(self):
        self.stop()
        if self.path: self.path.unlink(missing_ok=True)
        self.path = None; self.duration = 0.; self.dirty = False
        self.history.clear(); self.state = 'idle'; self.changed.emit()

    def recover(self, path):
        if self.dirty: raise RuntimeError("Guarda la toma actual antes de recuperar otra")
        path = Path(path)
        if path.parent.resolve() != self.recovery_dir.resolve():
            raise ValueError("Selecciona una toma de la carpeta de recuperación de Atril")
        with wave.open(str(path), 'rb') as source:
            if source.getsampwidth() != 2 or source.getcomptype() != 'NONE':
                raise ValueError("Formato de recuperación no admitido")
            rate, channels, frames = source.getframerate(), source.getnchannels(), source.getnframes()
            if not frames: raise ValueError("La toma está vacía")
            # Restore only the final five seconds, without loading a long take into memory.
            source.setpos(max(0, frames - rate * 5))
            data = source.readframes(rate * 5)
        self.stop()
        if self.path and self.path != path: self.path.unlink(missing_ok=True)
        self.path, self.rate, self.channels = path, rate, channels
        self.duration = frames / rate; self.dirty = True; self.state = 'stopped'
        self.history.clear()
        step = max(1, rate // 50) * channels * 2
        for pos in range(0, len(data), step):
            _, peak, rms, _ = pcm16(data[pos:pos + step]); self.history.append((peak, rms))
        self.changed.emit()

    def recovery_files(self):
        return sorted((p for p in self.recovery_dir.glob('toma-*.wav') if p != self.path),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def shutdown(self):
        self.stop(); self.visual_timer.stop()
        if self.path and not self.dirty: self.path.unlink(missing_ok=True)
