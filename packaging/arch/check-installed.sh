#!/bin/bash
# Exercise the installed package, without importing the source checkout.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
cp -R "$project_dir/tests" "$test_dir/tests"
cd "$test_dir"
pacman -Q atril-teleprompter
pacman -Qk atril-teleprompter
atril-teleprompter --version
desktop-file-validate /usr/share/applications/es.compilando.AtrilTeleprompter.desktop
export PYTHONPATH=/usr/share/atril-teleprompter
export QT_QPA_PLATFORM=offscreen
python - <<'PY'
from pathlib import Path
import atril
assert Path(atril.__file__) == Path('/usr/share/atril-teleprompter/atril.py')
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication
app = QApplication([])
for name in ('atril.png', 'compilando-podcast-logo.jpg'):
    assert not QPixmap(str(atril.ASSETS / name)).isNull(), name
print('Installed module, application icon and Compilando logo: OK')
PY
python -m unittest discover -s tests -v
