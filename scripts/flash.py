#!/usr/bin/env python3
"""macOS external removable WHOLE disks only; no automatic target selection."""
import argparse
import fcntl
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def diskinfo(identifier):
 return plistlib.loads(subprocess.check_output(['diskutil','info','-plist',identifier]))
def eligible(info):
 return (info.get('Whole') is True and info.get('Internal') is False
  and (info.get('RemovableMedia') is True or info.get('Removable') is True)
  and info.get('VirtualOrPhysical','Physical')=='Physical'
  and info.get('DeviceLocation','External')=='External'
  and re.fullmatch(r'disk\d+',info.get('DeviceIdentifier','')) is not None
  and info.get('TotalSize',0)>0)
def listing():
 data=plistlib.loads(subprocess.check_output(['diskutil','list','-plist','external','physical']))
 rows=[]
 for identifier in data.get('WholeDisks',[]):
  info=diskinfo(identifier)
  if eligible(info):rows.append(info)
 return rows

def show_storage(plan):
 print(f"Imagem a gravar: {plan['image_bytes']} bytes ({plan['image_bytes']/1e9:.2f} GB); mínimo do master: {plan['minimum_card_bytes']} bytes.")
 print(f"Userdata total: {plan['userdata_bytes']/1e9:.2f} GB; livre estimado: {plan['estimated_free_bytes']/1e9:.2f} GB; fora das partições: {plan['unused_card_bytes']} bytes.")

def main():
 p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');p.add_argument('--disk');p.add_argument('--fill-card',action='store_true',help='Expandir uma cópia temporária offline para a capacidade real do cartão');a=p.parse_args()
 if sys.platform!='darwin':sys.exit('A gravação só é suportada no macOS.')
 rows=listing()
 print('Discos físicos externos removíveis elegíveis:')
 for d in rows:print(f"/dev/{d['DeviceIdentifier']} · {d.get('MediaName',d.get('IORegistryEntryName','?'))} · {d['TotalSize']/1e9:.2f} GB")
 if not rows:print('Nenhum cartão elegível. Leitores que não sinalizem suporte removível são recusados.')
 image=ROOT/'cache/master/glua-arcade-pi3bplus.img';metadata=ROOT/'cache/master/master.json'
 if a.dry_run:
  print('DRY RUN: master comum Pi 3B+, sem escolha de estação nem deployment.')
  if metadata.exists():
   record=json.loads(metadata.read_text());print('Master:',record['image_size'],'bytes; capacidade mínima:',record['minimum_card_bytes'],'bytes; jogos:',len(record['games']))
   print('Userdata:',record.get('userdata_bytes',0),'bytes; livre:',record.get('free_userdata_bytes',0),'bytes')
   if a.disk:
    identifier=a.disk.removeprefix('/dev/')
    if identifier not in {d['DeviceIdentifier'] for d in rows}:sys.exit('Disco recusado.')
    from master import storage_plan
    plan=storage_plan(record,diskinfo(identifier)['TotalSize'],a.fill_card)
    print('Plano sem escrita (espaço livre sujeito aos metadados da expansão):');show_storage(plan)
  else:print('Executar ./prepare.sh para construir o master.')
  print('Modo:', 'expandir cópia para o cartão' if a.fill_card else 'compacto, reutilizar master sem alterações')
  print('Seleção explícita → validar disco e SHA-256 do master → confirmação → desmontar → gravar → comparar todos os bytes → ejetar.')
  return
 if not rows:sys.exit('Liga um cartão e repete.')
 if not image.exists() or not metadata.exists():sys.exit('Executa ./prepare.sh primeiro.')
 with (metadata.parent/'build.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
  except BlockingIOError:sys.exit('Master está a ser preparado; espera que ./prepare.sh termine.')
  record=json.loads(metadata.read_text())
  from library import digest
  from master import partitions,storage_plan,expand_image
  if not record.get('ready_to_flash') or image.stat().st_size!=record['image_size'] or record['minimum_card_bytes']!=image.stat().st_size:sys.exit('Metadados do master inválidos; repetir ./prepare.sh.')
  manifest=ROOT/'build/shared-manifest.json'
  if not manifest.exists() or digest(manifest)!=record.get('manifest_sha256'):sys.exit('Manifesto não corresponde ao master; executa ./prepare.sh.')
  print('A verificar SHA-256 do master reutilizável...')
  if digest(image)!=record['sha256']:sys.exit('Master corrompido; repetir ./prepare.sh.')
  partitions(image)
  print(f"Master: {image.stat().st_size} bytes; {len(record['games'])} jogos. A mesma imagem serve todas as placas e estações.")
  if not record.get('library_complete',record['event_ready']):print('ATENÇÃO: biblioteca incompleta. Consulta build/master-readiness.json antes do evento.')
  identifier=(a.disk or input('Identificador completo do disco (ex.: disk4): ')).removeprefix('/dev/')
  if identifier not in {d['DeviceIdentifier'] for d in rows}:sys.exit('Disco recusado.')
  original=diskinfo(identifier)
  if not eligible(original) or original['TotalSize']<record['minimum_card_bytes']:sys.exit('Disco recusado ou capacidade real insuficiente.')
  plan=storage_plan(record,original['TotalSize'],a.fill_card)
  show_storage(plan)
  with tempfile.TemporaryDirectory(prefix='glua-card-',dir=metadata.parent) as temporary:
   write_image=image
   if a.fill_card and plan['image_bytes']>record['image_size']:
    write_image=Path(temporary)/'card.img'
    with (Path(temporary)/'expand.log').open('w') as log:
     expanded=expand_image(image,write_image,original['TotalSize'],json.loads(manifest.read_text()),record,log)
    print(f"Cópia verificada: {expanded['image_bytes']} bytes; userdata livre: {expanded['free_userdata_bytes']/1e9:.2f} GB; espaço de alinhamento no userdata: {expanded['userdata_padding_bytes']} bytes.")
   print(f"TODOS OS DADOS DE /dev/{identifier} ({original.get('MediaName','?')}, {original['TotalSize']/1e9:.2f} GB) SERÃO APAGADOS.")
   confirmation=f'APAGAR {identifier}'
   if input(f'Escreve exatamente {confirmation}: ')!=confirmation:sys.exit('Cancelado.')
   subprocess.run(['sudo','-v'],check=True)
   current=diskinfo(identifier)
   fingerprint=('DeviceIdentifier','TotalSize','MediaName','DiskUUID','DeviceTreePath','BusProtocol')
   if not eligible(current) or any(current.get(k)!=original.get(k) for k in fingerprint):sys.exit('O disco mudou; operação cancelada.')
   subprocess.run(['diskutil','unmountDisk','/dev/'+identifier],check=True)
   subprocess.run(['sudo','dd','if='+str(write_image),'of=/dev/r'+identifier,'bs=4m'],check=True)
   subprocess.run(['sync'],check=True)
   subprocess.run(['diskutil','unmountDisk','/dev/'+identifier],check=True)
   code='import sys; a=open(sys.argv[1],"rb"); b=open(sys.argv[2],"rb"); n=0\nwhile True:\n x=a.read(4194304)\n if not x: break\n if x!=b.read(len(x)): sys.exit("Verificação falhou; não utilizar cartão")\n n+=len(x)\nprint("Bytes verificados:",n)'
   subprocess.run(['sudo',sys.executable,'-c',code,str(write_image),'/dev/r'+identifier],check=True)
   subprocess.run(['diskutil','eject','/dev/'+identifier],check=True)
   print('Cartão verificado e ejetado. Insere em qualquer Pi 3B+ e liga. Sem deployment ou ligação de rede.')
if __name__=='__main__':
 try:main()
 except (OSError,ValueError,subprocess.CalledProcessError) as e:sys.exit(str(e))
