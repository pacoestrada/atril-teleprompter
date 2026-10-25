import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog
from atril import AtrilWindow, ScriptEditor, STYLE
from core import load_session

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion"); app.setStyleSheet(STYLE)


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"session.json"
        self.w = AtrilWindow(self.path, restore=False)
        self.w.resize(1280, 860); self.w.show(); self.w.activateWindow()
        app.processEvents(); QTest.qWait(30)
        self.w.canvas.setFocus()

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); app.processEvents(); self.tmp.cleanup()

    def test_keyboard_play_pause_speed_and_font(self):
        self.w.countdown_combo.setCurrentIndex(0)
        QTest.keyClick(self.w.canvas, Qt.Key_Space)
        self.assertTrue(self.w.playing)
        QTest.qWait(160)
        self.assertGreater(self.w.canvas.offset, 3.)
        QTest.keyClick(self.w.canvas, Qt.Key_Space)
        offset = self.w.canvas.offset
        QTest.qWait(80)
        self.assertEqual(offset, self.w.canvas.offset)
        speed = self.w.settings["speed"]
        QTest.keyClick(self.w.canvas, Qt.Key_Up)
        self.assertEqual(self.w.settings["speed"], speed+4)
        size = self.w.settings["font_size"]
        QTest.keyClick(self.w.canvas, Qt.Key_Plus)
        self.assertEqual(self.w.settings["font_size"], size+2)

    def test_countdown_cancel(self):
        self.w.toggle()
        self.assertIsNotNone(self.w.countdown_until)
        self.assertFalse(self.w.playing)
        QTest.keyClick(self.w.canvas, Qt.Key_Escape)
        self.assertIsNone(self.w.countdown_until)
        self.assertEqual(self.w.canvas.countdown_number, 0)
        self.assertFalse(self.w.playing)

    def test_countdown_enters_playback(self):
        self.w.toggle(); self.w.countdown_until = time.monotonic()-.1
        self.w.tick()
        self.assertTrue(self.w.playing)
        self.assertEqual(self.w.canvas.countdown_number, 0)

    def test_mouse_play_and_manual_move_pauses(self):
        self.w.countdown_combo.setCurrentIndex(0)
        QTest.mouseClick(self.w.canvas, Qt.LeftButton)
        self.assertTrue(self.w.playing)
        self.w.manual_move(160)
        self.assertFalse(self.w.playing)
        self.assertAlmostEqual(self.w.canvas.offset, 160, delta=5)

    def test_end_and_repeat(self):
        self.w.canvas.set_offset(self.w.canvas.maximum-1)
        self.w.playing=True; self.w._last_tick=time.monotonic()-.1; self.w.tick()
        self.assertTrue(self.w.finished)
        self.assertFalse(self.w.playing)
        self.assertEqual(self.w.canvas.progress, 1.)
        self.w.toggle()
        self.assertEqual(self.w.canvas.offset, 0.)
        self.assertIsNotNone(self.w.countdown_until)

    def test_seek_and_restore_session(self):
        self.w.progress_slider.setValue(4250)
        self.w.elapsed=35.2; self.w.persist()
        state=load_session(self.path)
        self.assertAlmostEqual(state["progress"], .425, places=4)
        self.assertEqual(state["elapsed"], 35.2)
        other=AtrilWindow(self.path, restore=True); other.resize(1280,860); other.show()
        app.processEvents()
        self.assertAlmostEqual(other.canvas.progress, .425, places=3)
        self.assertFalse(other.playing)
        other.close();other.deleteLater()

    def test_resize_preserves_reading_anchor(self):
        self.w.manual_move(630)
        before = self.w.canvas.anchor()[0]
        self.w.resize(1100,750);app.processEvents()
        after = self.w.canvas.anchor()[0]
        self.assertLess(abs(after-before), 85)

    def test_editor_shortcuts_are_normal_text(self):
        editor=ScriptEditor("",self.w)
        def type_and_check():
            editor.editor.setFocus()
            QTest.keyClicks(editor.editor,"mi texto c m + -")
            self.assertEqual(editor.editor.toPlainText(),"mi texto c m + -")
            self.assertFalse(self.w.playing)
            self.assertFalse(self.w.settings["mirror"])
            editor.accept()
        QTimer.singleShot(20,type_and_check)
        editor.exec_()

    def test_previous_script_recovery(self):
        original=self.w.text
        self.w.apply_script("Un guion nuevo", "Nuevo")
        self.assertTrue(self.w.previous_path.exists())
        self.w.recover_previous()
        self.assertEqual(self.w.text,original)
        self.w.recover_previous()
        self.assertEqual(self.w.text,"Un guion nuevo")

    def test_mirror_and_fullscreen_keep_brand_and_shortcuts(self):
        QTest.keyClick(self.w.canvas, Qt.Key_M)
        self.assertTrue(self.w.settings["mirror"])
        QTest.keyClick(self.w.canvas, Qt.Key_F11); app.processEvents()
        self.assertTrue(self.w.isFullScreen())
        self.assertTrue(self.w.shortcuts_frame.isVisible())
        self.assertTrue(self.w.findChild(type(self.w.title_label), "brand").isVisible())
        QTest.keyClick(self.w.canvas, Qt.Key_Escape); app.processEvents()
        self.assertFalse(self.w.isFullScreen())

    def test_empty_guion_and_single_line(self):
        self.w.apply_script("", "Vacío")
        self.assertEqual(self.w.canvas.maximum,0.)
        self.w.apply_script("Una sola frase.","Breve")
        self.assertGreater(self.w.canvas.maximum,0.)
        self.w.canvas.set_offset(999999)
        self.assertEqual(self.w.canvas.progress,1.)

    def test_laptop_layout(self):
        self.w.resize(1024,700);app.processEvents()
        for widget in [self.w.play_button,self.w.full_button,self.w.shortcuts_frame,self.w.canvas]:
            self.assertTrue(widget.isVisible())
            point=widget.mapTo(self.w,widget.rect().bottomRight())
            self.assertLessEqual(point.x(),self.w.width())
            self.assertLessEqual(point.y(),self.w.height())


if __name__ == "__main__": unittest.main()
