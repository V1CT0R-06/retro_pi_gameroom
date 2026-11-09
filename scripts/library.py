#!/usr/bin/env python3
"""Read-only source scan; build clean, deterministic, deployment bundles."""
import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def load(name): return json.loads((ROOT/'config'/name).read_text())
def digest(path,algorithm='sha256'):
 h=hashlib.new(algorithm)
 with path.open('rb') as source:
  for block in iter(lambda:source.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def normalized(name):
 name=re.sub(r'\([^)]*\)|\[[^]]*\]','',name)
 return re.sub(r'[^a-z0-9]','',name.casefold())
def inside(path,parent):
 if not path.resolve().is_relative_to(parent.resolve()): raise ValueError(f'Caminho fora da pasta de importação: {path}')
 return path

def dependencies(path,base,seen=None):
 seen=set() if seen is None else seen
 path=inside(path,base)
 if path in seen: raise ValueError('Referência circular no disco/playlist')
 seen.add(path)
 if not path.is_file(): raise ValueError(f'Falta ficheiro: {path.name}')
 files=[path]
 if path.suffix.lower()=='.cue':
  references=re.findall(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))',path.read_text(errors='strict'),re.M|re.I)
  if not references: raise ValueError(f'CUE sem faixas: {path.name}')
  for a,b in references:
   target=inside(path.parent/(a or b),base)
   if not target.is_file(): raise ValueError(f'Faixa em falta: {target.name}')
   files.append(target)
 elif path.suffix.lower()=='.m3u':
  for line in path.read_text().splitlines():
   if line.strip() and not line.startswith('#'):
    target=path.parent/line.strip()
    if target.suffix.lower() not in ('.cue','.chd','.pbp'): raise ValueError('M3U: usa CUE, CHD ou PBP')
    files.extend(dependencies(target,base,seen.copy()))
 elif path.suffix.lower()=='.zip':
  with zipfile.ZipFile(path) as z:
   if z.testzip(): raise ValueError('ZIP corrompido')
   if any(n.startswith('/') or '..' in Path(n).parts for n in z.namelist()): raise ValueError('ZIP com caminhos inseguros')
   expected={'.nes'} if base.name=='nes' else {'.sfc','.smc'} if base.name=='snes' else {'.gb'} if base.name=='gb' else {'.md','.bin','.gen'} if base.name=='megadrive' else None
   if expected and not any(Path(n).suffix.lower() in expected for n in z.namelist()): raise ValueError('ZIP sem ROM do sistema esperado')
 return list(dict.fromkeys(files))

def controller_entries(path):
 xml=ET.parse(path)
 if xml.getroot().tag!='inputList':raise ValueError('es_input.cfg inválido')
 entries=xml.findall('inputConfig[@type="joystick"]')
 required={'a','b','x','y','pageup','pagedown','start','select','up','down','left','right','hotkey'}
 if not entries:raise ValueError('Faltam mapeamentos de comandos.')
 for entry in entries:
  if entry.get('type')!='joystick' or not entry.get('deviceGUID') or not required.issubset({i.get('name') for i in entry.findall('input')}):
   raise ValueError('Mapeamento incompleto: validar GUID, direções, seis botões, Start/Select e Hotkey.')
  for item in entry.findall('input'):
   if item.get('type') not in ('button','axis','hat') or not str(item.get('id','')).isdigit():raise ValueError('Entrada de comando inválida.')
 return [{'guid':e.get('deviceGUID'),'name':e.get('deviceName')} for e in entries]

def validate_controllers(root):
 config=load('controllers.json')
 if not config.get('validated'):return None
 if config.get('players_tested')!=2:raise ValueError('Validar dois comandos antes de incluir o mapeamento.')
 path=inside(ROOT/config['source'],ROOT/'controllers')
 entries=controller_entries(path)
 target=root/'system/configs/emulationstation/es_input.cfg';target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
 return entries

def build():
 """One userdata tree for EVERY board, including compatible additional games."""
 stations=load('stations.json');wanted=load('games.json');systems=load('systems.json')
 selection=load('library.json')
 if type(selection.get('include_unlisted')) is not bool or any(type(g.get('selected')) is not bool for g in wanted):raise ValueError('selected e include_unlisted têm de ser true ou false.')
 for g in wanted:
  if g['system'] not in systems:raise ValueError('Sistema desconhecido: '+g['system'])
  for name in g.get('files',[]):
   if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Caminho inseguro em files.')
 def matches_game(game,system,path,base):
  return game['system']==system and (path.relative_to(base).as_posix() in game['files'] if game.get('files') else normalized(path.stem) in [normalized(a) for a in game['aliases']])
 if len({s['id'] for s in stations})!=len(stations):raise ValueError('IDs de estações repetidos.')
 if [(s['id'],s.get('challenge')) for s in stations if s.get('challenge')]!=[(1,'platformers'),(2,'fighting'),(3,'racing')]:
  raise ValueError('As três provas permanecem nas estações 1, 2 e 3.')
 if any(not s.get('enabled',True) for s in stations[:3]):raise ValueError('As três estações oficiais devem estar ativas.')
 for sid in range(1,6):
  old=ROOT/'build'/f'station-{sid}'
  if old.is_dir() and not old.is_symlink():shutil.rmtree(old)
 dest=ROOT/'build/shared';dest.mkdir(parents=True,exist_ok=True)
 # Delete only our generated bundle, never imports or tournament data.
 shutil.rmtree(dest);dest.mkdir()
 for folder in ('system/configs/emulationstation','roms','bios','saves','screenshots'):(dest/folder).mkdir(parents=True,exist_ok=True)
 report=dict(games=[],available=[],selected=[g['title'] for g in wanted if g['selected']],missing=[],missing_optional=[],selected_missing=[],errors=[],blocked=[],duplicates=[],bios={},stations=[],controllers=None)
 hashes={};trees={};candidates=[]
 arcade=load('arcade.json')
 if arcade['system']!='fbneo' or arcade['core']!='fbneo':raise ValueError('O perfil arcade suportado é FBNeo.')
 for system,extensions in systems.items():
  bases=[ROOT/'roms'/system]+sorted((ROOT/'roms/stations').glob('*/'+system))
  for base in bases:
   for path in sorted(base.rglob('*')) if base.exists() else []:
    if not path.is_file() or any(part.startswith('.') for part in path.relative_to(base).parts):continue
    inside(path,base)
    if any(ord(c)<32 for c in str(path)):raise ValueError('Nome de ficheiro com caracteres de controlo.')
    ext=path.suffix.lower()
    if ext not in extensions:
     if ext not in ('.bin','.xml','.png','.jpg','.txt'):report['blocked'].append(str(path.relative_to(ROOT))+': extensão não suportada')
     continue
    if system=='arcade' and path.name not in arcade['validated_files']:
     report['blocked'].append(str(path.relative_to(ROOT))+': romset arcade ainda não validado');continue
    matches=[g for g in wanted if matches_game(g,system,path,base)]
    # Explicitly deselected titles stay excluded even in include_unlisted mode.
    selected=any(g['selected'] for g in matches) or (not matches and selection['include_unlisted'] and not any(g['system']==system and normalized(path.stem) in [normalized(a) for a in g['aliases']] for g in wanted))
    report['available'].append(dict(system=system,source=str(path.relative_to(ROOT)),title=matches[0]['title'] if matches else path.stem,selected=selected))
    if selected:candidates.append((system,path,base))
 # A playlist is the entry point; keep its discs as dependencies, not duplicates in menu.
 referenced=set()
 for system,path,base in candidates:
  if path.suffix.lower()=='.m3u':
   try:referenced.update(p.resolve() for p in dependencies(path,base)[1:])
   except (OSError,ValueError) as e:report['errors'].append(str(e))
 for game in wanted:
  selected_matches=[(system,path,base) for system,path,base in candidates if matches_game(game,system,path,base)]
  if game['selected'] and len({digest(path) for _,path,_ in selected_matches})>1:
   report['errors'].append(game['title']+': várias versões diferentes; escolher uma em files no games.json.')
 for system,path,base in candidates:
  if path.resolve() in referenced:continue
  try:
   files=dependencies(path,base);sha=digest(path)
   identity=hashlib.sha256(json.dumps([(p.relative_to(base).as_posix(),digest(p)) for p in files]).encode()).hexdigest() if system=='psx' else sha
   if (system,identity) in hashes:
    report['duplicates'].append([hashes[(system,identity)],str(path.relative_to(ROOT))]);continue
   output_system='fbneo' if system=='arcade' else system
   for source in files:
    target=dest/'roms'/output_system/source.relative_to(base)
    if target.exists() and digest(target)!=digest(source):raise ValueError(f'Conflito de nomes na biblioteca comum: {target.name}; renomear uma versão na origem.')
   for source in files:
    target=dest/'roms'/output_system/source.relative_to(base);target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():shutil.copy2(source,target)
   matches=[g for g in wanted if matches_game(g,system,path,base)]
   title=matches[0]['title'] if matches else path.stem
   # Preserve region/revision identity whenever a title has multiple dumps.
   display=path.stem if any(g['title']==title for g in report['games']) else title
   tree=trees.setdefault(output_system,ET.Element('gameList'));entry=ET.SubElement(tree,'game')
   ET.SubElement(entry,'path').text='./'+path.relative_to(base).as_posix();ET.SubElement(entry,'name').text=display
   if title in ('Super Mario World','Street Fighter II','Super Mario Kart'):ET.SubElement(entry,'favorite').text='true'
   report['games'].append(dict(title=title,system=output_system,source=str(path.relative_to(ROOT)),path=str((Path('roms')/output_system/path.relative_to(base)).as_posix()),sha256=sha))
   hashes[(system,identity)]=str(path.relative_to(ROOT))
  except (ValueError,OSError,zipfile.BadZipFile,UnicodeError) as e:report['errors'].append(f'{path.name}: {e}')
 for game in wanted:
  if not any(g['title']==game['title'] for g in report['available']):
   report['missing_optional' if game.get('optional') else 'missing'].append(game['title'])
  if game['selected'] and not any(g['title']==game['title'] for g in report['games']):report['selected_missing'].append(game['title'])
 for source in (ROOT/'bios').rglob('*'):
  if source.is_file() and not any(p.startswith('.') for p in source.relative_to(ROOT/'bios').parts):
   inside(source,ROOT/'bios');target=dest/'bios'/source.relative_to(ROOT/'bios');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 for system,entries in load('bios.json').items():
  report['bios'][system]={name:('OK' if (dest/'bios'/name).is_file() and digest(dest/'bios'/name,'md5')==md5 else 'EM FALTA / HASH INCORRETO') for name,md5 in entries.items()}
 if any(g['system']=='psx' for g in report['games']) and not any(v=='OK' for v in report['bios']['psx'].values()):
  report['errors'].append('PS1: falta uma BIOS reconhecida; não certificar jogos até a fornecer.')
 settings={'system.hostname':'glua-arcade','global.shaderset':'none','global.bezel':'none','global.ratio':'auto','global.smooth':'0','global.rewind':'0','global.autosave':'0','global.retroachievements':'0','global.runahead':'0','global.ai_service_enabled':'0','global.retroarch.input_max_users':'2','psx.pcsx_rearmed_multitap':'disabled','psx.neon_enhancement':'disabled','psx.frameskip_pcsx':'0'}
 cores={'nes':'fceumm','snes':'snes9x','megadrive':'genesisplusgx','gb':'gambatte','fbneo':'fbneo','psx':'pcsx_rearmed'}
 for system,core in cores.items():settings.update({system+'.emulator':'libretro',system+'.core':core})
 (dest/'system/batocera.conf').write_text(''.join(f'{k}={v}\n' for k,v in settings.items()))
 es=ET.Element('config');ET.SubElement(es,'string',name='ThemeSet',value='es-theme-carbon');ET.SubElement(es,'bool',name='ParseGamelistOnly',value='true');ET.SubElement(es,'bool',name='HiddenSystemsShowGames',value='false')
 registry=ROOT/'cache/runtime/root/usr/share/emulationstation/es_systems.cfg'
 if registry.exists():
  available={s.findtext('name') for s in ET.parse(registry).findall('system')}
  ET.SubElement(es,'string',name='HiddenSystems',value=';'.join(sorted(available-set(trees))))
 ET.ElementTree(es).write(dest/'system/configs/emulationstation/es_settings.cfg',encoding='utf-8',xml_declaration=True)
 for system,tree in trees.items():ET.ElementTree(tree).write(dest/'roms'/system/'gamelist.xml',encoding='utf-8',xml_declaration=True)
 report['controllers']=validate_controllers(dest)
 for station in stations:
  report['stations'].append(dict(id=station['id'],enabled=station['enabled'],challenge=station.get('challenge'),library='shared',games=len(report['games'])))
 (dest/'system/glua-library.json').write_text(json.dumps(dict(games=report['games'],selected=report['selected'],selected_missing=report['selected_missing']),ensure_ascii=False,indent=2)+'\n')
 manifest=[dict(path=p.relative_to(dest).as_posix(),size=p.stat().st_size,sha256=digest(p)) for p in sorted(dest.rglob('*')) if p.is_file()]
 (ROOT/'build/shared-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 (ROOT/'build/readiness.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['GLUA — biblioteca única para todos os Raspberry Pi 3B+',f"ROMs disponíveis: {len(report['available'])}; jogos selecionados no manifesto: {len(report['selected'])}; jogos incluídos: {len(report['games'])}; selecionados em falta: {len(report['selected_missing'])}; erros: {len(report['errors'])}",'Comandos: '+('mapeamento fornecido e declarado validado' if report['controllers'] else 'testar primeiro os perfis incluídos; mapear apenas se necessário'),'Selecionados em falta: '+', '.join(report['selected_missing']),'Pedidos em falta: '+', '.join(report['missing']),'Opcionais em falta: '+', '.join(report['missing_optional']),'Compatibilidade/desempenho físico ainda não testados.']
 inventory=['# Biblioteca comum','', '| Jogo / ROM | Estado | Ficheiro |','|---|---|---|']
 for game in wanted:
  found=[f['source'] for f in report['available'] if f['title']==game['title']]
  state=('Selecionado' if game['selected'] else 'Não selecionado')+(' · disponível' if found else ' · em falta/bloqueado')
  inventory.append('| '+game['title'].replace('|','/')+' | '+state+' | '+', '.join(found).replace('|','/')+' |')
 for file in report['available']:
  if file['title'] not in {g['title'] for g in wanted}:inventory.append('| '+file['title'].replace('|','/')+' | '+('Incluído (include_unlisted)' if file['selected'] else 'Disponível, não selecionado')+' | '+file['source'].replace('|','/')+' |')
 inventory+=['','## Bloqueios/erros',*['- '+item for item in report['blocked']+report['errors']]]
 (ROOT/'build/LIBRARY.md').write_text('\n'.join(inventory)+'\n')
 (ROOT/'build/READINESS.txt').write_text('\n'.join(lines)+'\n');print('\n'.join(lines))
 return report
if __name__=='__main__':
 try:build()
 except (ValueError,AssertionError,OSError) as e:sys.exit(str(e))
