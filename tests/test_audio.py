import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox
from audio_core import ExportCancelled, WaveTake, dbfs, export_audio, pcm16
from audio_capture import AUDIO_AVAILABLE, AudioRecorder
from atril import AtrilWindow, STYLE

app = QApplication.instance() or QApplication([])
app.setStyle('Fusion'); app.setStyleSheet(STYLE)


def tone(seconds=.1, rate=48000, amplitude=.4, channels=1):
    values = [round(amplitude * 32767 * math.sin(2 * math.pi * 440 * n / rate))
              for n in range(round(seconds * rate)) for _ in range(channels)]
    return struct.pack('<' + 'h' * len(values), *values)


class AudioCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def make_take(self):
        take = WaveTake(self.root, 48000, 1); take.append(tone(.25)); take.finish(); return take

    def test_gain_changes_samples_and_reports_clipping_without_wrapping(self):
        data = struct.pack('<5h', 1000, -1000, 20000, -20000, 32767)
        output, peak, rms, clipped = pcm16(data, 6.0206)
        self.assertEqual(struct.unpack('<5h', output), (2000, -2000, 32767, -32768, 32767))
        self.assertTrue(clipped); self.assertEqual(peak, 1.)
        self.assertGreater(rms, .7)
        self.assertLess(pcm16(data, -12)[1], .26)
        self.assertTrue(pcm16(data, -12)[3])  # clipping at source is still reported

    def test_unity_and_silence_and_dbfs(self):
        data = tone(); self.assertEqual(pcm16(data)[0], data)
        self.assertEqual(pcm16(b'\0' * 100), (b'\0' * 100, 0., 0., False))
        self.assertAlmostEqual(dbfs(.5), -6.0206, places=3)
        self.assertEqual(dbfs(0), -60)

    def test_recovery_wav_readable_before_finish(self):
        take = WaveTake(self.root, 48000, 2); payload = tone(.1, channels=2)
        take.append(payload)
        with wave.open(str(take.path)) as audio:
            self.assertEqual(audio.getnframes(), 4800)
            self.assertEqual(audio.getnchannels(), 2)
            self.assertEqual(audio.readframes(4800), payload)
        self.assertEqual(take.path.stat().st_mode & 0o777, 0o600)
        take.finish()

    def test_wav_size_limit_stops_before_corruption(self):
        take = WaveTake(self.root, 48000, 1)
        with patch('audio_core.MAX_PCM_BYTES', 100):
            with self.assertRaises(OSError): take.append(tone())
        take.finish()
        with wave.open(str(take.path)) as audio: self.assertEqual(audio.getnframes(), 0)

    def test_wav_export_exact_and_existing_file_replaced(self):
        take = self.make_take(); target = self.root / 'voice.wav'; target.write_bytes(b'old')
        export_audio(take.path, target, 'wav')
        self.assertEqual(target.read_bytes(), take.path.read_bytes())
        self.assertFalse(list(self.root.glob('.atril-export-*')))

    def test_cancel_preserves_existing_destination_and_take(self):
        take = self.make_take(); target = self.root / 'voice.wav'; target.write_bytes(b'previous')
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(ExportCancelled): export_audio(take.path, target, 'wav', cancel)
        self.assertEqual(target.read_bytes(), b'previous'); self.assertTrue(take.path.exists())
        self.assertFalse(list(self.root.glob('.atril-export-*')))

    def test_missing_encoder_leaves_original_and_destination_untouched(self):
        take = self.make_take(); target = self.root / 'voice.mp3'; target.write_bytes(b'previous')
        with patch('audio_core.shutil.which', return_value=None):
            with self.assertRaises(RuntimeError): export_audio(take.path, target, 'mp3')
        self.assertEqual(target.read_bytes(), b'previous'); self.assertTrue(take.path.exists())
        self.assertFalse(list(self.root.glob('.atril-export-*')))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg unavailable')
    def test_flac_lossless_and_mp3_decodable_with_correct_duration(self):
        take = self.make_take()
        for kind, codec in [('flac', 'flac'), ('mp3', 'mp3')]:
            with self.subTest(kind=kind):
                destination = self.root / ('recording with spaces.' + kind)
                export_audio(take.path, destination, kind)
                info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(destination)]))
                self.assertEqual(info['streams'][0]['codec_name'], codec)
                self.assertEqual(info['streams'][0]['channels'], 1)
                self.assertAlmostEqual(float(info['format']['duration']), .25, delta=.08)
                decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(destination), '-f', 's16le', '-'])
                self.assertGreater(len(decoded), 10000)
                if kind == 'flac': self.assertEqual(decoded, tone(.25))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.recorder = AudioRecorder(self.root)
        self.recorder.take = WaveTake(self.root, 48000, 1)
        self.recorder.path = self.recorder.take.path
        self.recorder.state = 'recording'; self.recorder.dirty = True
        self.recorder._last_audio = time.monotonic()

    def tearDown(self): self.recorder.shutdown(); self.tmp.cleanup()

    def test_pause_drops_audio_and_resume_starts_fresh(self):
        r = self.recorder; first = tone(.105); second = tone(.071, amplitude=.2)
        # Exercise odd byte chunks, a partial final audio block, pause and resume.
        r.consume(first[:77]); r.consume(first[77:]); r.pause()
        r.consume(tone(.2, amplitude=.8)); r.pause(); r.consume(second); r.stop()
        with wave.open(str(r.path)) as audio: self.assertEqual(audio.readframes(audio.getnframes()), first + second)
        self.assertAlmostEqual(r.duration, .176)

    def test_gain_is_recorded_and_waveform_memory_is_bounded(self):
        r = self.recorder; r.gain_db = -6
        r.consume(tone(7)); r.stop()
        self.assertEqual(len(r.history), 250)
        with wave.open(str(r.path)) as audio: self.assertEqual(audio.readframes(audio.getnframes()), pcm16(tone(7), -6)[0])

    def test_disk_error_stops_but_keeps_recovery_file(self):
        r = self.recorder; errors = []; r.failed.connect(errors.append)
        r.consume(tone(.1))
        with patch.object(r.take, 'append', side_effect=OSError('disk full')): r.consume(tone(.1))
        self.assertEqual(r.state, 'stopped'); self.assertTrue(r.path.exists()); self.assertTrue(r.dirty)
        self.assertIn('disk full', errors[0])

    def test_recovery_and_clean_shutdown_preserve_unsaved_take(self):
        r = self.recorder; r.consume(tone(.1)); r.shutdown(); path = r.path
        fresh = AudioRecorder(self.root)
        self.assertIn(path, fresh.recovery_files()); fresh.recover(path)
        self.assertAlmostEqual(fresh.duration, .1); self.assertTrue(fresh.dirty)
        fresh.dirty = False; fresh.shutdown(); self.assertFalse(path.exists())

    def test_no_audio_timeout_stops_with_explanation(self):
        r = self.recorder; errors = []; r.failed.connect(errors.append)
        r._last_audio = time.monotonic() - 6; r._visuals()
        self.assertEqual(r.state, 'stopped'); self.assertIn('no está entregando audio', errors[0])

    def test_new_recording_refuses_to_discard_unsaved_take(self):
        self.recorder.stop()
        with self.assertRaises(RuntimeError): self.recorder.start(None)
        self.assertTrue(self.recorder.path.exists())

    @unittest.skipUnless(AUDIO_AVAILABLE, 'Qt Multimedia unavailable')
    def test_input_lifecycle_uses_selected_device_and_keeps_timing(self):
        from PyQt5.QtMultimedia import QAudio
        recorder = AudioRecorder(self.root / 'device')
        class Device:
            def isNull(self): return False
            def isFormatSupported(self, fmt):
                return fmt.sampleRate() == 44100 and fmt.channelCount() == 2
        class Source(QObject):
            readyRead = pyqtSignal()
            def __init__(self): super().__init__(); self.pending = b''
            def readAll(self):
                result, self.pending = self.pending, b''
                return result
            def feed(self, data): self.pending += data; self.readyRead.emit()
        class Input(QObject):
            stateChanged = pyqtSignal(int)
            def __init__(self, device, fmt, parent):
                super().__init__(parent); self.device = device; self.source = Source()
            def setBufferSize(self, size): pass
            def start(self): return self.source
            def error(self): return QAudio.NoError
            def stop(self): self.stateChanged.emit(QAudio.StoppedState)
        device = Device()
        with patch('audio_capture.QAudioInput', Input):
            recorder.start(device)
            self.assertIs(recorder.audio.device, device)
            self.assertEqual((recorder.rate, recorder.channels), (44100, 2))
            payload = tone(.1, rate=44100, channels=2)
            recorder.source.feed(payload)
            recorder.pause(); recorder.source.feed(payload); recorder.pause()
            recorder.source.feed(payload); recorder.stop()
            self.assertIsNone(recorder.audio)
            self.assertAlmostEqual(recorder.duration, .2)
            with wave.open(str(recorder.path)) as audio:
                self.assertEqual(audio.readframes(audio.getnframes()), payload * 2)
        recorder.shutdown()



class RecorderUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.w = AtrilWindow(self.root / 'session.json', restore=False)
        self.w.resize(1024, 700); self.w.show(); self.w.activateWindow()
        app.processEvents(); QTest.qWait(30)

    def tearDown(self):
        self.w.recorder_bar.recorder.dirty = False
        self.w.close(); self.w.deleteLater(); app.processEvents(); self.tmp.cleanup()

    def fake_take(self):
        r = self.w.recorder_bar.recorder
        r.take = WaveTake(r.recovery_dir, 48000, 1); r.path = r.take.path
        r.state = 'recording'; r.dirty = True; r._last_audio = time.monotonic()
        r.consume(tone(.1)); r.changed.emit(); return r

    def test_gain_keyboard_does_not_change_reading_speed(self):
        bar = self.w.recorder_bar; bar.gain.setFocus(); app.processEvents()
        speed = self.w.settings['speed']
        QTest.keyClick(bar.gain, Qt.Key_Right); QTest.keyClick(bar.gain, Qt.Key_Up)
        self.assertEqual(self.w.settings['speed'], speed); self.assertEqual(bar.gain.value(), 2)
        self.assertEqual(bar.recorder.gain_db, 2)

    def test_record_pause_stop_shortcuts_and_independent_reading(self):
        r = self.fake_take(); self.w.canvas.setFocus(); self.w.countdown_combo.setCurrentIndex(0)
        QTest.keyClick(self.w.canvas, Qt.Key_Space); self.assertTrue(self.w.playing)
        QTest.keyClick(self.w.canvas, Qt.Key_R, Qt.ControlModifier)
        self.assertEqual(r.state, 'paused'); self.assertTrue(self.w.playing)
        QTest.keyClick(self.w.canvas, Qt.Key_R, Qt.ControlModifier)
        self.assertEqual(r.state, 'recording')
        QTest.keyClick(self.w.canvas, Qt.Key_R, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(r.state, 'stopped'); self.assertTrue(self.w.recorder_bar.save_button.isEnabled())

    def test_cancel_close_preserves_recording(self):
        r = self.fake_take()
        with patch('audio_widgets.QMessageBox.question', return_value=QMessageBox.Cancel): self.w.close()
        self.assertTrue(self.w.isVisible()); self.assertEqual(r.state, 'recording'); self.assertTrue(r.path.exists())

    def test_export_async_and_save_cancellation(self):
        r = self.fake_take(); r.stop(); bar = self.w.recorder_bar
        with patch('audio_widgets.QFileDialog.exec_', return_value=0): self.assertFalse(bar.save())
        self.assertTrue(r.dirty); self.assertTrue(r.path.exists())
        bar.start_export(self.root / 'audio.wav', 'wav')
        for _ in range(100):
            QTest.qWait(20)
            if bar.job is None: break
        self.assertIsNone(bar.job); self.assertFalse(r.dirty)
        self.assertTrue((self.root / 'audio.wav').exists())

    def test_close_after_saving_finishes_export_before_exit(self):
        r = self.fake_take(); bar = self.w.recorder_bar
        target = self.root / 'on-close.wav'
        def save():
            bar.start_export(target, 'wav'); return True
        with patch('audio_widgets.QMessageBox.question', return_value=QMessageBox.Save), patch.object(bar, 'save', side_effect=save):
            self.w.close()
            for _ in range(100):
                QTest.qWait(20)
                if not self.w.isVisible(): break
        self.assertFalse(self.w.isVisible()); self.assertTrue(target.exists())
        self.assertIsNone(bar.job)

    def test_bar_fits_laptop_and_fullscreen(self):
        for width, height in [(1024, 700), (740, 650)]:
            self.w.resize(width, height); app.processEvents()
            for widget in [self.w.recorder_bar.devices, self.w.recorder_bar.save_button,
                           self.w.recorder_bar.gain_value, self.w.recorder_bar.clock,
                           self.w.canvas, self.w.shortcuts_frame]:
                point = widget.mapTo(self.w, widget.rect().bottomRight())
                self.assertLessEqual(point.x(), self.w.width())
                self.assertLessEqual(point.y(), self.w.height())
        self.w.toggle_fullscreen(); app.processEvents()
        self.assertTrue(self.w.recorder_bar.isVisible()); self.assertTrue(self.w.shortcuts_frame.isVisible())


if __name__ == '__main__': unittest.main()
