#!/usr/bin/env python3
"""Create reproducible release sources, excluding CI and Arch checksum metadata."""
import gzip
import io
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import VERSION


def build(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    prefix = f'atril-teleprompter-{VERSION}'
    destination = output / (prefix + '.tar.gz')
    with destination.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(ROOT.rglob('*')):
                relative = path.relative_to(ROOT)
                if not path.is_file() or any(part in {'.git', '.github', 'dist', '__pycache__', '.venv'} for part in relative.parts):
                    continue
                if relative.parts[:2] == ('packaging', 'arch'):
                    continue  # These recipes contain this archive's checksum.
                content = path.read_bytes()
                info = tarfile.TarInfo(str(Path(prefix) / relative))
                info.size = len(content); info.mode = 0o755 if path.suffix == '.sh' else 0o644
                info.mtime = 0; info.uid = info.gid = 0
                archive.addfile(info, io.BytesIO(content))
    print(destination)


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist')
