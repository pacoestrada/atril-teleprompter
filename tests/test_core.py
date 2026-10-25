import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (DEFAULTS, MAX_FILE, atomic_write, clean_settings, import_document,
                  load_session, save_session, validate_text, word_count)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def test_text_encodings(self):
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            path = self.root / "guion.txt"
            path.write_bytes("Málaga, acción.\r\nPaco Estrada".encode(encoding))
            self.assertEqual(import_document(path), "Málaga, acción.\nPaco Estrada")

    def test_docx_paragraphs_tabs_and_breaks(self):
        path = self.root / "guion.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hola</w:t><w:tab/><w:t>Paco</w:t><w:br/><w:t>¿Qué tal?</w:t></w:r></w:p><w:p><w:r><w:t>Fin</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(import_document(path), "Hola\tPaco\n¿Qué tal?\n\nFin")

    def test_odt_spaces_and_formatting(self):
        path = self.root / "guion.odt"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("content.xml", '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><text:h>Título</text:h><text:p>Hola<text:s text:c="2"/><text:span>Paco</text:span><text:line-break/>Fin</text:p></office:text></office:body></office:document-content>')
        self.assertEqual(import_document(path), "Título\n\nHola  Paco\nFin")

    def test_zip_bomb_guard(self):
        path = self.root / "grande.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"x" * (MAX_FILE + 1))
        with self.assertRaisesRegex(ValueError, "demasiado grande"):
            import_document(path)

    def test_no_external_xml_entities(self):
        path = self.root / "entidad.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", '<!DOCTYPE a [<!ENTITY secret SYSTEM "file:///etc/passwd">]><a>&secret;</a>')
        with self.assertRaisesRegex(ValueError, "XML"):
            import_document(path)

    def test_bad_binary_and_size(self):
        with self.assertRaises(ValueError): validate_text("hola\0")
        with self.assertRaises(ValueError): validate_text("a"*1_000_001)
        with self.assertRaises(ValueError): validate_text(None)

    def test_unicode_word_count(self):
        self.assertEqual(word_count("¡Hola, Paco! GNU/Linux: voz propia."), 6)

    def test_session_roundtrip(self):
        p = self.root / "prueba.atril"
        state = {"text": "Mi guion ñ", "title": "Prueba", "settings": DEFAULTS,
                 "progress": .427, "elapsed": 22.4}
        save_session(p, state)
        actual = load_session(p)
        for k, v in state.items(): self.assertEqual(actual[k], v)

    def test_invalid_session(self):
        p = self.root / "mala.atril"
        for value in ([], {}, {"format":"atril-session", "version":99, "text":"a"}):
            p.write_text(json.dumps(value))
            with self.assertRaises(ValueError): load_session(p)

    def test_untrusted_settings_clamped(self):
        actual = clean_settings({"font_size":2000, "width":-4, "speed":"inf", "spacing":None,
                                 "countdown":-1, "mirror":"false", "theme":"invalid"})
        self.assertEqual(actual["font_size"], 100)
        self.assertEqual(actual["width"], 45)
        self.assertEqual(actual["speed"], DEFAULTS["speed"])
        self.assertEqual(actual["countdown"], 0)
        self.assertFalse(actual["mirror"])
        self.assertEqual(actual["theme"], "noche")

    def test_atomic_replace_and_no_temporaries(self):
        p = self.root / "carpeta/guion.txt"
        atomic_write(p, "versión uno")
        atomic_write(p, "versión dos")
        self.assertEqual(p.read_text(), "versión dos")
        self.assertEqual(list(p.parent.iterdir()), [p])


if __name__ == "__main__": unittest.main()
