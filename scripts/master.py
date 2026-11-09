#!/usr/bin/env python3
"""Create/verify one offline Pi 3B+ disk image using ordinary files, never devices."""
import argparse
import fcntl
import gzip
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import library
from library import digest
ROOT=Path(__file__).resolve().parent.parent
MIB=1024*1024


def tool(name):
 found=shutil.which(name)
 if found:return found
 for prefix in ('/usr/local/opt/e2fsprogs','/opt/homebrew/opt/e2fsprogs'):
  for folder in ('sbin','bin'):
   candidate=Path(prefix)/folder/name
   if candidate.exists():return str(candidate)
 raise ValueError(f'Falta {name}. Executa ./prepare.sh para instalar as ferramentas essenciais.')

def run(args,**kwargs):
 return subprocess.run([str(a) for a in args],check=True,**kwargs)

def partitions(path):
 with path.open('rb') as f:header=f.read(512)
 if len(header)!=512 or header[510:512]!=b'\x55\xaa':raise ValueError('Imagem sem MBR válido.')
 result=[]
 for index in range(4):
  _,_,kind,_,start,sectors=struct.unpack('<B3sB3sII',header[446+index*16:462+index*16])
  if sectors:result.append(dict(index=index,type=kind,start=start*512,size=sectors*512))
 if len(result)!=2 or [p['index'] for p in result]!=[0,1] or [p['type'] for p in result]!=[0x0c,0x83]:raise ValueError('Esperadas exatamente duas partições: FAT32 e Linux.')
 first,second=result
 if first['start']!=MIB or any(p['start']%MIB or p['size']%MIB for p in result) or first['start']+first['size']!=second['start'] or second['start']+second['size']!=path.stat().st_size:
  raise ValueError('Partições desalinhadas, sobrepostas ou fora dos limites da imagem.')
 return result

def copy_range(source,target,start,size,offset=0):
 with source.open('rb') as src,target.open('r+b' if target.exists() else 'wb') as dst:
  src.seek(start);dst.seek(offset)
  while size:
   block=src.read(min(size,8*MIB))
   if not block:raise ValueError('Imagem truncada durante a cópia.')
   dst.write(block);size-=len(block)

def fat_read(image,start,name):
 return subprocess.check_output([tool('mtype'),'-i',f'{image}@@{start}','::/'+name]).decode()

def disable_resize(text):
 lines=[line for line in text.splitlines() if not re.match(r'^\s*(autoresize|format-internal|sharedevice)\s*=',line)]
 return '\n'.join(lines)+'\n# GLUA: userdata já preparado; nunca reformatar no primeiro arranque.\nsharedevice=INTERNAL\nautoresize=false\n'

def source_image():
 config=library.load('images.json')
 if config['architecture']!='bcm2837' or config['model']!='Raspberry Pi 3 Model B+':raise ValueError('Só é suportada a imagem Pi 3B+ bcm2837.')
 compressed=ROOT/'cache/images'/config['url'].rsplit('/',1)[1]
 path=compressed.with_suffix('');metadata=path.with_suffix('.source.json')
 expected=dict(compressed_sha256=digest(compressed))
 cached=json.loads(metadata.read_text()) if metadata.exists() else {}
 if cached.get('compressed_sha256')==expected['compressed_sha256'] and path.exists() and digest(path)==cached.get('sha256'):return path
 temporary=Path(str(path)+'.tmp')
 print('A descomprimir imagem oficial para cache...',flush=True)
 with gzip.open(compressed,'rb') as src,temporary.open('wb') as dst:shutil.copyfileobj(src,dst,8*MIB)
 partitions(temporary);temporary.replace(path)
 metadata.write_text(json.dumps(dict(**expected,sha256=digest(path)),indent=2))
 return path

def runtime(base):
 """Read actual boot scripts/configuration from the pinned OS, not assumptions."""
 cache=ROOT/'cache/runtime';cache.mkdir(parents=True,exist_ok=True)
 first=partitions(base)[0]
 for fat_name,local_name in [('boot/batocera','batocera.squashfs'),('boot/rufomaculata','rufomaculata.squashfs')]:
  destination=cache/local_name
  # mcopy overwrites only this generated regular file; never mounts any disk.
  run([tool('mcopy'),'-o','-i',f'{base}@@{first["start"]}','::/'+fat_name,destination],stdout=subprocess.DEVNULL)
 files=['etc/init.d/S02resize','etc/init.d/S12populateshare','usr/share/emulationstation/es_systems.cfg','usr/share/batocera/datainit/system/batocera.conf','usr/share/batocera/batocera.version','usr/share/emulationstation/es_input.cfg']
 run([tool('7z'),'x','-y','-o'+str(cache/'root'),cache/'batocera.squashfs',*files],stdout=subprocess.DEVNULL)
 root=cache/'root'
 resize=(root/files[0]).read_text();populate=(root/files[1]).read_text()
 if 'autoresize' not in resize or 'format-internal' not in resize or 'mkfs.ext4' not in resize:
  raise ValueError('Comportamento de primeiro arranque desconhecido; rever esta versão antes de construir.')
 if '43.1' not in (root/'usr/share/batocera/batocera.version').read_text():raise ValueError('Versão real inesperada no sistema base.')
 if '[ ! -e "${OUT}/${FILE}" ]' not in populate or 'system/batocera.conf' not in populate:
  raise ValueError('Não foi possível confirmar preservação das configurações no primeiro arranque.')
 listing=subprocess.check_output([tool('7z'),'l','-ba',cache/'rufomaculata.squashfs'],text=True)
 cores=['fceumm','snes9x','genesisplusgx','gambatte','fbneo','pcsx_rearmed']
 for core in cores:
  if f'usr/lib/libretro/{core}_libretro.so' not in listing:raise ValueError(f'Core ausente na imagem: {core}')
 boot_files={}
 with tempfile.TemporaryDirectory(prefix='glua-boot-',dir=cache) as temporary:
  for name in ['bootcode.bin','start.elf','fixup.dat','bcm2710-rpi-3-b-plus.dtb','config.txt','cmdline.txt','boot/linux','boot/initrd.lz4','boot/batocera.board']:
   target=Path(temporary)/'asset'
   run([tool('mcopy'),'-o','-i',f'{base}@@{first["start"]}','::/'+name,target],stdout=subprocess.DEVNULL)
   if not target.stat().st_size:raise ValueError('Ficheiro de arranque vazio: '+name)
   boot_files[name]=digest(target)
 boot_files['boot/batocera']=digest(cache/'batocera.squashfs')
 boot_files['boot/rufomaculata']=digest(cache/'rufomaculata.squashfs')
 profiles=ET.parse(root/'usr/share/emulationstation/es_input.cfg').findall('inputConfig[@type="joystick"]')
 return dict(boot_files=boot_files,default_controller_profiles=len(profiles),version=(root/'usr/share/batocera/batocera.version').read_text().strip(),boot_scripts={f:digest(root/f) for f in files[:2]},cores=cores)

def userdata_size(manifest,config):
 if config.get('autoresize') is not False:raise ValueError('A imagem offline exige autoresize=false para preservar dados.')
 for key in ('userdata_min_mib','userdata_free_mib'):
  if not isinstance(config.get(key),int) or config[key]<256:raise ValueError(f'{key} deve ser >=256 MiB.')
 payload=sum(f['size'] for f in manifest)
 return max(config['userdata_min_mib']*MIB,math.ceil((payload+max(64*MIB,payload//8)+config['userdata_free_mib']*MIB)/MIB)*MIB)

def quote(value):
 if any(ord(c)<32 for c in str(value)):raise ValueError('Caminho com caracteres de controlo.')
 return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'

def verify_boot_assets(image,start,expected):
 with tempfile.TemporaryDirectory(prefix='glua-boot-check-',dir=ROOT/'cache/master') as tmp:
  asset=Path(tmp)/'asset'
  for name,sha in expected.items():
   run([tool('mcopy'),'-o','-i',f'{image}@@{start}','::/'+name,asset],stdout=subprocess.DEVNULL)
   if digest(asset)!=sha:raise ValueError('Ficheiro de arranque alterado: '+name)
 config=fat_read(image,start,'config.txt')
 if not re.search(r'^arm_64bit=1$',config,re.M) or not re.search(r'^kernel=boot/linux$',config,re.M) or not re.search(r'^initramfs boot/initrd.lz4$',config,re.M):raise ValueError('Configuração de arranque Pi 3B+ inesperada.')
 if 'dev=LABEL=BATOCERA' not in fat_read(image,start,'cmdline.txt') or fat_read(image,start,'boot/batocera.board').strip()!='bcm2837':raise ValueError('Referência ao dispositivo/placa de arranque inesperada.')

def verify_image(image,manifest,log=None,boot_expected=None):
 first,second=partitions(image)
 with image.open('rb') as stream:
  stream.seek(first['start']);fat=stream.read(512)
 if fat[510:512]!=b'\x55\xaa' or struct.unpack_from('<H',fat,11)[0]!=512 or fat[71:82].rstrip(b' ')!=b'BATOCERA':raise ValueError('FAT32/label BATOCERA inválido.')
 if boot_expected:verify_boot_assets(image,first['start'],boot_expected)
 boot=fat_read(image,first['start'],'batocera-boot.conf')
 if re.search(r'^\s*autoresize\s*=\s*true\s*$',boot,re.M) or re.search(r'^\s*format-internal\s*=',boot,re.M):raise ValueError('Imagem poderia apagar userdata no arranque.')
 if not re.search(r'^autoresize=false$',boot,re.M) or not re.search(r'^sharedevice=INTERNAL$',boot,re.M):raise ValueError('Falta autoresize=false/sharedevice=INTERNAL.')
 with tempfile.TemporaryDirectory(prefix='glua-verify-',dir=ROOT/'cache/master') as tmp:
  temp=Path(tmp);filesystem=temp/'userdata.ext4'
  copy_range(image,filesystem,second['start'],second['size'])
  with filesystem.open('rb') as f:
   f.seek(1024);sb=f.read(1024)
  if sb[56:58]!=b'\x53\xef' or sb[120:136].rstrip(b'\x00')!=b'SHARE':raise ValueError('Superbloco/label ext4 inválido.')
  blocksize=1024<<struct.unpack_from('<I',sb,24)[0]
  features=struct.unpack_from('<III',sb,92)
  if blocksize!=4096 or struct.unpack_from('<I',sb,72)[0]!=0 or not struct.unpack_from('<H',sb,58)[0]&1:raise ValueError('ext4 exige blocos 4K, creator Linux e estado limpo.')
  if any(value & ~allowed for value,allowed in zip(features,(0x103c,0x22c2,0x46b))):raise ValueError('Funcionalidades ext4 não auditadas para este kernel.')
  filesystem_bytes=struct.unpack_from('<I',sb,4)[0]*blocksize
  group_bytes=struct.unpack_from('<I',sb,32)[0]*blocksize
  padding=second['size']-filesystem_bytes
  # resize2fs can omit an incomplete final block group: the filesystem may be
  # slightly smaller than its partition, but must never extend beyond it.
  if filesystem_bytes<=0 or group_bytes<=0 or not 0<=padding<group_bytes:raise ValueError('Tamanho ext4 fora dos limites da partição.')
  run([tool('e2fsck'),'-f','-n',filesystem],stdout=log,stderr=log)
  commands=temp/'dump.commands';restored=temp/'restored';restored.mkdir()
  expected=set();extracted_files={}
  lines=[]
  for index,entry in enumerate(manifest):
   relative=Path(entry['path'])
   if relative.is_absolute() or '..' in relative.parts:raise ValueError('Manifesto com caminho inseguro.')
   target=restored/str(index)
   lines.append(f'dump {quote("/"+relative.as_posix())} {quote(target)}')
   expected.add(relative.as_posix())
  commands.write_text('\n'.join(lines)+'\n')
  run([tool('debugfs'),'-f',commands,filesystem],stdout=log,stderr=log)
  for index,entry in enumerate(manifest):
   extracted=restored/str(index);extracted_files[entry['path']]=extracted
   if not extracted.is_file() or extracted.stat().st_size!=entry['size'] or digest(extracted)!=entry['sha256']:
    raise ValueError('Ficheiro ausente/corrompido na imagem: '+entry['path'])
   if extracted.suffix=='.xml' or entry['path'].endswith(('.xml','.cfg')) and 'emulationstation/' in entry['path']:ET.parse(extracted)
  # Ensure every menu entry points to a file included in this image.
  for entry in manifest:
   if entry['path'].endswith('/gamelist.xml'):
    original=extracted_files[entry['path']]
    for game in ET.parse(original).findall('game'):
     relative=(Path(entry['path']).parent/game.findtext('path')).as_posix()
     if relative not in expected:raise ValueError('Entrada de menu sem ROM: '+relative)
  return dict(partitions=[first,second],files_verified=len(manifest),free_userdata_bytes=struct.unpack_from('<I',sb,12)[0]*blocksize,filesystem_bytes=filesystem_bytes,userdata_padding_bytes=padding,ext4_block_size=blocksize,ext4_features=[hex(f) for f in features])

def storage_plan(record,capacity,fill=False):
 """No device access. Round down to MiB; never shrink the reusable master."""
 minimum=record['image_size']
 if type(capacity) is not int or capacity<minimum:raise ValueError('Capacidade real insuficiente para o master.')
 size=max(minimum,capacity//MIB*MIB) if fill else minimum
 if size//512>0xffffffff:raise ValueError('Capacidade excede o limite MBR suportado (aprox. 2 TiB).')
 return dict(image_bytes=size,minimum_card_bytes=minimum,userdata_bytes=record.get('userdata_bytes',0)+size-minimum,
  estimated_free_bytes=record.get('free_userdata_bytes',0)+size-minimum,unused_card_bytes=capacity-size)

def expand_image(source,destination,capacity,manifest,record,log=None):
 """Grow a COPY on the Mac; never change the master or any physical device."""
 plan=storage_plan(record,capacity,True);first,second=partitions(source)
 if destination.exists():raise ValueError('A cópia temporária já existe; não será substituída.')
 if plan['image_bytes']<=source.stat().st_size:raise ValueError('O cartão não oferece espaço adicional alinhado.')
 required=3*plan['image_bytes']+sum(f['size'] for f in manifest)+1024*MIB
 if shutil.disk_usage(destination.parent).free<required:raise ValueError(f'Expansão requer pelo menos {required} bytes livres no Mac para cópias/verificação. Usa o modo compacto ou liberta espaço.')
 print(f"A preparar cópia para o cartão: {plan['image_bytes']/1e9:.2f} GB; pode demorar vários minutos...",flush=True)
 with tempfile.TemporaryDirectory(prefix='glua-grow-',dir=destination.parent) as tmp:
  filesystem=Path(tmp)/'userdata.ext4'
  copy_range(source,filesystem,second['start'],second['size'])
  run([tool('e2fsck'),'-f','-n',filesystem],stdout=log,stderr=log)
  new_size=plan['image_bytes']-second['start']
  with filesystem.open('r+b') as stream:stream.truncate(new_size)
  run([tool('resize2fs'),filesystem,str(new_size//4096)],stdout=log,stderr=log)
  with destination.open('xb') as stream:stream.truncate(plan['image_bytes'])
  copy_range(source,destination,0,second['start'])
  with destination.open('r+b') as stream:
   stream.seek(446+16*second['index']+12);stream.write(struct.pack('<I',new_size//512))
   stream.seek(446+16*second['index']+5);stream.write(b'\xfe\xff\xff')
  copy_range(filesystem,destination,0,new_size,second['start'])
  result=verify_image(destination,manifest,log,record.get('runtime_evidence',{}).get('boot_files'))
 return dict(**plan,free_userdata_bytes=result['free_userdata_bytes'],files_verified=result['files_verified'],filesystem_bytes=result['filesystem_bytes'],userdata_padding_bytes=result['userdata_padding_bytes'])

def write_readiness(record):
 (ROOT/'build/master-readiness.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
 with (ROOT/'build/READINESS.txt').open('a') as f:
  f.write(f'\nMaster: {record["image"]}\nTamanho / capacidade mínima exata: {record["image_size"]} bytes ({record["image_size"]/1e9:.2f} GB)\nUserdata (partição): {record["userdata_bytes"]/MIB:.0f} MiB; ext4: {record["filesystem_bytes"]/MIB:.0f} MiB; livre: {record["free_userdata_bytes"]/MIB:.0f} MiB\nAutoexpansão desativada; espaço além da imagem permanece não utilizado.\nSHA-256: {record["sha256"]}\n')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
 folder=ROOT/'cache/master';folder.mkdir(parents=True,exist_ok=True)
 image=folder/'glua-arcade-pi3bplus.img';metadata=folder/'master.json'
 with (folder/'build.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Master em utilização; termina a outra preparação/gravação primeiro.')
  if args.dry_run:
   print('DRY RUN: imagem comum Pi 3B+; FAT32 original + userdata ext4 preenchido no Mac; sem VM, rede de Pis ou acesso a discos.');return
  if args.verify_only:
   record=json.loads(metadata.read_text());manifest=json.loads((ROOT/'build/shared-manifest.json').read_text())
   if digest(ROOT/'build/shared-manifest.json')!=record.get('manifest_sha256'):raise ValueError('Manifesto alterado; repetir ./prepare.sh.')
   if digest(image)!=record['sha256']:raise ValueError('SHA-256 da imagem master incorreto.')
   with (folder/'verify.log').open('w') as log:verify_image(image,manifest,log,record['runtime_evidence']['boot_files'])
   print('Master novamente verificado, sem reconstrução.');return
  base=source_image();evidence=runtime(base);report=library.build()
  manifest=json.loads((ROOT/'build/shared-manifest.json').read_text());config=library.load('master.json')
  if report['errors']:raise ValueError('Resolver erros de build/readiness.json antes de criar a imagem: '+'; '.join(report['errors']))
  fingerprint=digest(base)+json.dumps(manifest,sort_keys=True)+json.dumps(config,sort_keys=True)
  for file in ['scripts/master.py','scripts/library.py','config/images.json']:fingerprint+=digest(ROOT/file)
  import hashlib
  fingerprint=hashlib.sha256(fingerprint.encode()).hexdigest()
  record=json.loads(metadata.read_text()) if metadata.exists() else {}
  if record.get('fingerprint')==fingerprint and image.exists() and digest(image)==record.get('sha256'):
   print('Master existente verificado e reutilizado:',image)
   write_readiness(record);return
  size=userdata_size(manifest,config);first,second=partitions(base)
  if (second['start']+size)//512>0xffffffff:raise ValueError('Imagem excede limites MBR suportados.')
  temporary=folder/'glua-arcade-pi3bplus.img.tmp';filesystem=folder/'userdata.ext4.tmp'
  print(f'A construir master: boot {first["size"]/MIB:.0f} MiB + userdata {size/MIB:.0f} MiB...',flush=True)
  with temporary.open('wb') as f:f.truncate(second['start']+size)
  copy_range(base,temporary,0,second['start'])
  with temporary.open('r+b') as f:
   f.seek(446+16*second['index']+12);f.write(struct.pack('<I',size//512))
   f.seek(446+16*second['index']+5);f.write(b'\xfe\xff\xff')
  bootconf=folder/'batocera-boot.conf';bootconf.write_text(disable_resize(fat_read(base,first['start'],'batocera-boot.conf')))
  run([tool('mcopy'),'-o','-i',f'{temporary}@@{first["start"]}',bootconf,'::/batocera-boot.conf'])
  with filesystem.open('wb') as f:f.truncate(size)
  with (folder/'build.log').open('w') as log:
   # Conservative ext4 features supported by the Pi kernel; all operations target files.
   run([tool('mke2fs'),'-t','ext4','-F','-b','4096','-L','SHARE','-M','/userdata','-o','linux','-m','0','-O','^orphan_file,^metadata_csum_seed','-E','lazy_itable_init=0,lazy_journal_init=0,root_owner=0:0','-d',ROOT/'build/shared',filesystem],stdout=log,stderr=log)
   copy_range(filesystem,temporary,0,size,second['start'])
   result=verify_image(temporary,manifest,log,evidence['boot_files'])
  record=dict(manifest_sha256=digest(ROOT/'build/shared-manifest.json'),fingerprint=fingerprint,sha256=digest(temporary),image=str(image.relative_to(ROOT)),image_size=temporary.stat().st_size,minimum_card_bytes=temporary.stat().st_size,userdata_bytes=size,autoresize=False,ready_to_flash=True,event_ready=False,library_complete=bool(report['games']) and not report['selected_missing'],hardware_tested=False,selected=report['selected'],selected_missing=report['selected_missing'],games=report['games'],missing=report['missing'],missing_optional=report['missing_optional'],controllers=report['controllers'],runtime_evidence=evidence,**result)
  temporary.replace(image);filesystem.unlink()
  metadata.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
  write_readiness(record)
  print(f'Master verificado: {image}\nCapacidade mínima: {record["minimum_card_bytes"]} bytes; jogos: {len(report["games"])}')
  if not report['games']:print('ATENÇÃO: ainda não foram fornecidas ROMs; imagem preparada para arranque, mas sem jogos.')
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,subprocess.CalledProcessError,ET.ParseError) as e:sys.exit(str(e))
