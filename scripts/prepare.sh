#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-}"
echo "Sistema: $(uname -s) / $(uname -m)"
for name in python3 git curl; do command -v "$name" || { echo "Falta $name."; exit 1; }; done
python3 -c 'import sys; assert sys.version_info >= (3,10), "É necessário Python >=3.10"'
if [[ "$MODE" == --dry-run ]]; then
 python3 scripts/images.py --dry-run
 python3 scripts/master.py --dry-run
 echo 'DRY RUN: sem instalação, download, formatação ou acesso a discos.'
 exit 0
fi
[[ -x .venv/bin/python ]] || python3 -m venv .venv
if ! .venv/bin/python -c 'import flask,waitress; from importlib.metadata import version; assert version("Flask")=="3.1.3" and version("waitress")=="3.0.2"' 2>/dev/null; then
 .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python scripts/setup_local.py
if [[ "$MODE" == --skip-images || "$MODE" == --app-only ]]; then
 python3 scripts/library.py
 echo 'Aplicação preparada. Master não foi construído neste modo.'
 exit 0
fi
[[ -z "$MODE" ]] || { echo 'Opções: --dry-run, --app-only (--skip-images).'; exit 1; }
# Native filesystem tools manipulate image FILES. No VM or filesystem driver.
python3 - <<'PY'
import sys,subprocess,os
sys.path.insert(0,'scripts')
from master import tool
missing=[]
for package,names in [('e2fsprogs',['mke2fs','e2fsck','debugfs','resize2fs']),('mtools',['mcopy','mtype']),('p7zip',['7z'])]:
 try:
  for name in names:tool(name)
 except ValueError:missing.append(package)
if missing:
 import shutil
 if not shutil.which('brew'):sys.exit('Falta Homebrew para instalar: '+', '.join(missing))
 env=dict(os.environ,HOMEBREW_NO_AUTO_UPDATE='1',HOMEBREW_NO_INSTALL_CLEANUP='1',HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK='1')
 subprocess.run(['brew','install',*missing],env=env,check=True)
PY
if [[ -f cache/images/batocera-bcm2837-43.1-20260530.img.gz && -f cache/images/batocera-bcm2837-43.1-20260530.img.gz.md5 ]]; then
 python3 scripts/images.py --verify-only
else
 python3 scripts/images.py
fi
python3 scripts/master.py
echo 'Preparação concluída. Consulta build/READINESS.txt. Para cada cartão: ./flash.sh'
