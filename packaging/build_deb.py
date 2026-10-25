#!/usr/bin/env python3
"""Build a Debian package without root access or system changes."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import VERSION


def build(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atril-build-") as temp:
        stage = Path(temp)
        app = stage / "usr/share/atril-teleprompter"
        app.mkdir(parents=True)
        for name in ("atril.py", "core.py"):
            shutil.copy2(ROOT/name, app/name)
        shutil.copytree(ROOT/"assets", app/"assets")
        executable = stage / "usr/bin/atril-teleprompter"
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/share/atril-teleprompter/atril.py "$@"\n')
        executable.chmod(0o755)
        desktop = stage / "usr/share/applications"
        desktop.mkdir(parents=True)
        shutil.copy2(ROOT/"packaging/es.compilando.AtrilTeleprompter.desktop", desktop)
        pixmaps = stage / "usr/share/pixmaps"; pixmaps.mkdir(parents=True)
        shutil.copy2(ROOT/"assets/atril.png", pixmaps/"es.compilando.AtrilTeleprompter.png")
        documentation = stage / "usr/share/doc/atril-teleprompter"
        documentation.mkdir(parents=True)
        for name in ("README.md", "LICENSE", "THIRD_PARTY.md"):
            shutil.copy2(ROOT/name, documentation/name)
        control = stage / "DEBIAN"; control.mkdir()
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024
        (control / "control").write_text(
            f"Package: atril-teleprompter\nVersion: {VERSION}\nSection: video\nPriority: optional\n"
            f"Architecture: all\nInstalled-Size: {size}\n"
            "Maintainer: Paco Estrada\n"
            "Depends: python3 (>= 3.10), python3-pyqt5 (>= 5.15)\n"
            "Homepage: https://compilando.es\n"
            "Description: Telepronter de escritorio de Paco Estrada\n"
            " Aplicacion local para leer guiones con desplazamiento suave, teclado,\n"
            " pantalla completa, espejo y recuperacion de sesion. Compilando Podcast.\n")
        for p in stage.rglob('*'):
            if p.is_dir(): p.chmod(0o755)
            elif p != executable: p.chmod(0o644)
        destination = output / f"atril-teleprompter_{VERSION}_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(stage), str(destination)], check=True)
    print(destination)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv)>1 else ROOT/"dist")
