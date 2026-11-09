#!/usr/bin/env python3
"""Cache pinned official image. Never accept an unverified partial download."""
import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
CONFIG=json.loads((ROOT/'config/images.json').read_text())
def verify(path,expected):
 h=hashlib.md5()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 if h.hexdigest()!=expected:raise ValueError(f'MD5 incorreto: {path}; não será utilizado.')
 # Verify gzip CRC without retaining a second multi-GB file.
 with gzip.open(path,'rb') as f:
  while f.read(4*1024*1024):pass
 return h.hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
 directory=ROOT/'cache/images';directory.mkdir(parents=True,exist_ok=True)
 url=CONFIG['url'];path=directory/url.rsplit('/',1)[1]
 if args.dry_run:print('Imagem oficial:',url,'\nDestino:',path,'\nChecksum:',CONFIG['checksum_url']);return
 checksum=path.with_suffix(path.suffix+'.md5')
 if not args.verify_only:
  subprocess.run(['curl','-fL','--retry','3','--connect-timeout','20','--max-time','120','-o',str(checksum)+'.part',CONFIG['checksum_url']],check=True)
  Path(str(checksum)+'.part').replace(checksum)
 text=checksum.read_text();match=re.search(r'\b[0-9a-fA-F]{32}\b',text)
 if not match:raise ValueError('Checksum oficial indisponível ou inválido')
 if not path.exists():
  partial=Path(str(path)+'.part')
  if args.verify_only:raise ValueError('Imagem ainda não descarregada')
  complete=False
  if partial.exists():
   h=hashlib.md5()
   with partial.open('rb') as f:
    for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
   complete=h.hexdigest()==match[0].lower()
  if not complete:
   subprocess.run(['curl','-fL','--retry','3','--connect-timeout','20','--max-time','1800','-C','-','-o',str(partial),url],check=True)
  verify(partial,match[0].lower());partial.replace(path)
 else:verify(path,match[0].lower())
 (directory/'verified.json').write_text(json.dumps(dict(file=path.name,md5=match[0].lower(),source=url),indent=2))
 print('Imagem verificada (MD5 oficial + CRC gzip):',path)
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,subprocess.CalledProcessError) as e:sys.exit(str(e))
