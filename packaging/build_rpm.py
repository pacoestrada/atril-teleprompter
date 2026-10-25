#!/usr/bin/env python3
"""Build the native noarch RPM without changing the host system."""
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import VERSION


def build(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atril-rpm-") as directory:
        top = Path(directory)
        for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS", "tmp", "rpmdb"):
            (top/name).mkdir()
        prefix = f"atril-teleprompter-{VERSION}"
        source = top/"SOURCES"/(prefix+".tar.gz")
        with tarfile.open(source, "w:gz") as tar:
            for path in sorted(ROOT.rglob('*')):
                relative = path.relative_to(ROOT)
                if path.is_file() and not any(part in (".git", "dist", "__pycache__", ".venv") for part in relative.parts):
                    tar.add(path, arcname=str(Path(prefix)/relative), recursive=False)
        spec = top/"SPECS/atril-teleprompter.spec"
        content = (ROOT/"packaging/atril-teleprompter.spec").read_text()
        content = "\n".join("Version:        "+VERSION if line.startswith("Version:") else line for line in content.splitlines()) + "\n"
        spec.write_text(content)
        subprocess.run(["rpmbuild", "-ba", str(spec), "--define", f"_topdir {top}",
                        "--define", f"_tmppath {top/'tmp'}", "--define", f"_dbpath {top/'rpmdb'}"], check=True)
        for path in (top/"RPMS").rglob("*.rpm"):
            destination = output/path.name
            shutil.copy2(path, destination)
            print(destination)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv)>1 else ROOT/"dist")
