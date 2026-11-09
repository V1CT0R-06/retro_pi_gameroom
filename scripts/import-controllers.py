#!/usr/bin/env python3
"""Read a mapped card on the Mac, without mounting ext4 or writing to the card."""
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from flash import listing,eligible,diskinfo
from library import controller_entries
from master import tool
ROOT=Path(__file__).resolve().parent.parent

def main():
 if sys.platform!='darwin':raise ValueError('Este comando é para macOS.')
 rows=listing()
 for row in rows:print(f"{row['DeviceIdentifier']} · {row.get('MediaName','?')} · {row['TotalSize']/1e9:.2f} GB")
 identifier=input('Cartão que já arrancou e onde testaste os dois comandos (ex.: disk4): ').removeprefix('/dev/')
 if identifier not in {r['DeviceIdentifier'] for r in rows} or not eligible(diskinfo(identifier)):raise ValueError('Disco recusado.')
 if input('Se testaste os dois comandos, escreve TESTEI DOIS COMANDOS: ')!='TESTEI DOIS COMANDOS':raise ValueError('Cancelado; não foi declarado um mapeamento validado.')
 print('Leitura apenas do cartão; não será formatado nem alterado.')
 # debugfs defaults to read-only. The data partition is number 2 in our master.
 result=subprocess.run(['sudo',tool('debugfs'),'-R','cat /system/configs/emulationstation/es_input.cfg','/dev/r'+identifier+'s2'],capture_output=True,check=True)
 if not result.stdout.strip():raise ValueError('Não existe mapeamento personalizado neste cartão. Se ambos os comandos já funcionam, não é necessário importar.')
 with tempfile.TemporaryDirectory(prefix='glua-controller-') as folder:
  candidate=Path(folder)/'es_input.cfg';candidate.write_bytes(result.stdout)
  entries=controller_entries(candidate)
  destination=ROOT/'controllers/es_input.cfg';destination.parent.mkdir(exist_ok=True)
  if destination.exists():shutil.copy2(destination,destination.with_suffix('.cfg.previous'))
  shutil.copy2(candidate,destination)
 config_path=ROOT/'config/controllers.json';config=json.loads(config_path.read_text())
 config.update(validated=True,players_tested=2,source='controllers/es_input.cfg')
 config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
 print('Mapeamentos lidos:',entries)
 print('Executa ./prepare.sh uma vez e depois ./flash.sh nos restantes cartões. GUIDs/modelos diferentes podem exigir novo mapeamento.')
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,subprocess.CalledProcessError,ET.ParseError) as e:sys.exit(str(e))
