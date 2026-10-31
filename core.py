"""Document import and session persistence for Atril. No network access."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET

VERSION = "2.1.0"
MAX_TEXT = 1_000_000
MAX_FILE = 8_000_000
DEFAULTS = {"speed": 44, "font_size": 42, "width": 86, "spacing": 145,
            "countdown": 3, "guide": True, "mirror": False, "theme": "noche"}
LIMITS = {"speed": (8, 180), "font_size": (24, 100), "width": (45, 100),
          "spacing": (115, 190), "countdown": (0, 5)}
DEMO = """Tu voz. Tu ritmo.

Bienvenido a Atril, el teleprónter de Paco Estrada.

Un espacio para contar historias, compartir ideas y dar voz a lo que importa.

Abre tu guion o pulsa Editar para pegar un texto. Ajusta el tamaño de letra y encuentra un ritmo cómodo.

Pulsa Espacio para comenzar. Vuelve a pulsarlo cuando necesites hacer una pausa.

Con las flechas arriba y abajo puedes cambiar la velocidad. Las flechas izquierda y derecha te permiten retroceder o avanzar una línea.

La rueda del ratón mueve el guion y pausa la lectura. Así puedes volver a una frase sin perder el control.

Pulsa F11 para entrar en pantalla completa. La tecla C oculta los ajustes para darte más espacio.

Tu guion y el punto de lectura se guardan en este ordenador. Puedes cerrar Atril y continuar más tarde.

Respira, mira al frente y disfruta de lo que vas a contar.

Compilando Podcast. Tecnología con voz propia.
"""


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w]+(?:[’'-][\w]+)*\b", text, re.UNICODE))


def validate_text(text: str) -> str:
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError("El guion debe tener menos de un millón de caracteres.")
    if "\x00" in text:
        raise ValueError("Este archivo no parece contener un guion de texto.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_settings(raw: dict | None) -> dict:
    result = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return result
    for key, (low, high) in LIMITS.items():
        try:
            value = float(raw.get(key, result[key]))
            if math.isfinite(value):
                result[key] = min(high, max(low, int(value)))
        except (ValueError, TypeError, OverflowError):
            pass
    for key in ("guide", "mirror"):
        if isinstance(raw.get(key), bool):
            result[key] = raw[key]
    if raw.get("theme") in ("noche", "papel", "contraste"):
        result["theme"] = raw["theme"]
    return result


def load_session(path: Path) -> dict:
    if path.stat().st_size > MAX_FILE:
        raise ValueError("El archivo de sesión es demasiado grande.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("format") != "atril-session" or raw.get("version") != 1:
        raise ValueError("No es una sesión compatible de Atril.")
    text = validate_text(raw.get("text"))
    try:
        progress = float(raw.get("progress", 0))
        elapsed = float(raw.get("elapsed", 0))
        if not math.isfinite(progress) or not math.isfinite(elapsed):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        progress, elapsed = 0, 0
    anchor = None
    raw_anchor = raw.get("anchor")
    if isinstance(raw_anchor, (list, tuple)) and len(raw_anchor) == 2:
        try:
            index, fraction = int(raw_anchor[0]), float(raw_anchor[1])
            if math.isfinite(fraction):
                anchor = (min(len(text), max(0, index)), min(3., max(0., fraction)))
        except (ValueError, TypeError, OverflowError):
            pass
    return {"format": "atril-session", "version": 1, "text": text,
            "title": str(raw.get("title", "Mi guion"))[:180],
            "settings": clean_settings(raw.get("settings")),
            "progress": min(1., max(0., progress)), "elapsed": min(86400., max(0., elapsed)),
            "anchor": anchor}


def atomic_write(path: Path, data: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_session(path: Path, state: dict) -> None:
    atomic_write(path, json.dumps({"format": "atril-session", "version": 1,
                                  **state}, ensure_ascii=False, indent=2, allow_nan=False))


def import_document(path: Path) -> str:
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError("El archivo supera el límite de 8 MB.")
    extension = path.suffix.lower()
    if extension in (".txt", ".md"):
        data = path.read_bytes()
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16")
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp1252")
        return validate_text(text)
    if extension not in (".docx", ".odt"):
        raise ValueError("Abre un archivo TXT, MD, DOCX, ODT o una sesión .atril.")
    member = "word/document.xml" if extension == ".docx" else "content.xml"
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(member)
        if info.file_size > MAX_FILE:
            raise ValueError("El contenido del documento es demasiado grande.")
        data = archive.read(member)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("El documento incluye estructuras XML no admitidas.")
    root = ET.fromstring(data)
    if extension == ".docx":
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(ns + "p"):
            pieces = []
            for node in paragraph.iter():
                if node.tag == ns + "t":
                    pieces.append(node.text or "")
                elif node.tag == ns + "tab":
                    pieces.append("\t")
                elif node.tag in (ns + "br", ns + "cr"):
                    pieces.append("\n")
            paragraphs.append("".join(pieces))
    else:
        ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        office = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
        skip = {ns + "note", office + "annotation"}

        def odt_text(node):
            result = node.text or ""
            for child in node:
                if child.tag in skip:
                    pass
                elif child.tag == ns + "s":
                    count = min(100, max(1, int(child.get(ns + "c", "1"))))
                    result += " " * count
                elif child.tag == ns + "tab":
                    result += "\t"
                elif child.tag == ns + "line-break":
                    result += "\n"
                else:
                    result += odt_text(child)
                result += child.tail or ""
            return result

        paragraphs = []
        def visit(node):
            if node.tag in skip:
                return
            if node.tag in (ns + "p", ns + "h"):
                paragraphs.append(odt_text(node))
                return
            for child in node:
                visit(child)
        body = root.find(".//" + office + "body")
        visit(body if body is not None else root)
    return validate_text("\n\n".join(paragraphs))
