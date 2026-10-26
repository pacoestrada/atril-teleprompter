"""Regression tests for Mint's empty format signal and audio filename handling."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QLineEdit, QMessageBox
from audio_core import FORMATS, WaveTake
from audio_widgets import RecorderBar

app = QApplication.instance() or QApplication([])


class AudioSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # No physical microphone is opened by these save-dialog tests.
        with patch('audio_widgets.AudioRecorder.devices', return_value=[]), \
                patch('audio_widgets.AudioRecorder.default_name', return_value=''):
            self.bar = RecorderBar(self.root / 'pending')
        self.bar.last_folder = self.root
        r = self.bar.recorder
        r.take = WaveTake(r.recovery_dir, 48000, 1)
        r.path = r.take.path; r.state = 'recording'; r.dirty = True
        r.consume(b'\x10\x00' * 12000); r.stop()

    def tearDown(self):
        self.bar.recorder.dirty = False
        self.bar.request_close(); self.bar.deleteLater()
        app.processEvents(); self.tmp.cleanup()

    def choose(self, dialog, kind, filename):
        chosen = f'{FORMATS[kind]} (*.{kind})'
        dialog.selectNameFilter(chosen)
        dialog.filterSelected.emit(chosen)
        dialog.selectFile(str(self.root / filename))
        return QDialog.Accepted

    def test_suggested_name_has_no_extension(self):
        def inspect(dialog):
            edit = dialog.findChild(QLineEdit, 'fileNameEdit')
            self.assertIsNotNone(edit)
            self.assertEqual(Path(edit.text()).suffix, '')
            return QDialog.Rejected
        with patch.object(QFileDialog, 'exec_', inspect):
            self.assertFalse(self.bar.save())

    def test_empty_and_unknown_format_signals_do_not_raise(self):
        exceptions = []
        def inspect(dialog):
            for value in ('', 'unknown format'):
                dialog.filterSelected.emit(value)
            self.choose(dialog, 'mp3', 'Prueba')
            dialog.filterSelected.emit('')
            self.assertEqual(dialog.defaultSuffix(), 'mp3')
            return QDialog.Rejected
        with patch('sys.excepthook', side_effect=lambda *args: exceptions.append(args)), \
                patch.object(QFileDialog, 'exec_', inspect):
            self.assertFalse(self.bar.save())
        self.assertEqual(exceptions, [])

    def test_format_changes_never_accumulate_extensions(self):
        for kind in FORMATS:
            for name in ('Prueba', 'Prueba.wav', 'Prueba.wav.mp3', 'Prueba.FLAC.WAV'):
                with self.subTest(kind=kind, name=name):
                    def choose(dialog): return self.choose(dialog, kind, name)
                    with patch.object(QFileDialog, 'exec_', choose), \
                            patch.object(self.bar, 'start_export') as export:
                        self.assertTrue(self.bar.save())
                        export.assert_called_once_with(self.root / ('Prueba.' + kind), kind)

    def test_empty_final_filter_keeps_last_valid_choice(self):
        def choose(dialog): return self.choose(dialog, 'flac', 'Prueba')
        with patch.object(QFileDialog, 'exec_', choose), \
                patch.object(QFileDialog, 'selectedNameFilter', return_value=''), \
                patch.object(self.bar, 'start_export') as export:
            self.assertTrue(self.bar.save())
            export.assert_called_once_with(self.root / 'Prueba.flac', 'flac')

    def test_dots_in_title_are_preserved(self):
        def choose(dialog): return self.choose(dialog, 'mp3', 'Episodio.02.version.1.wav')
        with patch.object(QFileDialog, 'exec_', choose), \
                patch.object(self.bar, 'start_export') as export:
            self.assertTrue(self.bar.save())
            export.assert_called_once_with(self.root / 'Episodio.02.version.1.mp3', 'mp3')

    def test_existing_normalized_destination_requires_confirmation(self):
        target = self.root / 'Prueba.mp3'; target.write_bytes(b'existing recording')
        def choose(dialog): return self.choose(dialog, 'mp3', 'Prueba.wav.mp3')
        with patch.object(QFileDialog, 'exec_', choose), \
                patch('audio_widgets.QMessageBox.question', return_value=QMessageBox.No) as question, \
                patch.object(self.bar, 'start_export') as export:
            self.assertFalse(self.bar.save())
            question.assert_called_once(); export.assert_not_called()
        self.assertEqual(target.read_bytes(), b'existing recording')
        self.assertTrue(self.bar.recorder.dirty)

    def test_without_ffmpeg_only_wav_is_offered(self):
        def inspect(dialog):
            self.assertEqual(dialog.nameFilters(), [f'{FORMATS["wav"]} (*.wav)'])
            dialog.selectFile(str(self.root / 'Prueba'))
            return QDialog.Accepted
        with patch('audio_widgets.shutil.which', return_value=None), \
                patch.object(QFileDialog, 'exec_', inspect), \
                patch.object(self.bar, 'start_export') as export:
            self.assertTrue(self.bar.save())
            export.assert_called_once_with(self.root / 'Prueba.wav', 'wav')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg unavailable')
    def test_selected_format_matches_exported_audio_codec(self):
        for kind, codec in [('wav', 'pcm_s16le'), ('flac', 'flac'), ('mp3', 'mp3')]:
            with self.subTest(kind=kind):
                def choose(dialog): return self.choose(dialog, kind, 'Audio-' + kind)
                with patch.object(QFileDialog, 'exec_', choose):
                    self.assertTrue(self.bar.save())
                for _ in range(150):
                    QTest.qWait(20)
                    if self.bar.job is None: break
                self.assertIsNone(self.bar.job)
                destination = self.root / ('Audio-' + kind + '.' + kind)
                info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
                    '-show_streams', '-of', 'json', str(destination)]))
                self.assertEqual(info['streams'][0]['codec_name'], codec)


if __name__ == '__main__': unittest.main()
