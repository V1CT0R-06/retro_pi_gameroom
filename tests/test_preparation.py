import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
import library
import master
import flash

class PreparationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.original=library.ROOT
  shutil.copytree(self.original/'config',self.root/'config');(self.root/'roms/snes').mkdir(parents=True);(self.root/'bios').mkdir();(self.root/'build').mkdir()
  library.ROOT=self.root
 def tearDown(self):library.ROOT=self.original;self.temp.cleanup()
 def report(self):return library.build()
 def select(self,*titles):
  path=self.root/'config/games.json';games=json.loads(path.read_text())
  for game in games:game['selected']=game['title'] in titles
  path.write_text(json.dumps(games))
 def include_unlisted(self):
  (self.root/'config/library.json').write_text(json.dumps(dict(include_unlisted=True)))
 def test_empty_library_has_no_playable_placeholders(self):
  r=self.report();self.assertEqual(r['games'],[])
  self.assertEqual(list((self.root/'build').rglob('gamelist.xml')),[])
 def test_region_matching_and_content_duplicates(self):
  rom=self.root/'roms/snes/Super Mario World (USA) (Rev 1).sfc';rom.write_bytes(b'TEST FIXTURE NOT A ROM')
  r=self.report();self.assertEqual(len(r['games']),1);self.assertNotIn('Super Mario World',r['missing'])
  (rom.parent/'Super Mario World (Europe).sfc').write_bytes(rom.read_bytes())
  r=self.report();self.assertTrue(r['duplicates']);self.assertEqual(len(r['games']),1)
  self.assertEqual(rom.read_bytes(),b'TEST FIXTURE NOT A ROM')
 def test_all_stations_share_all_games_including_extra_roms(self):
  (self.root/'roms/snes/Super Mario World.sfc').write_bytes(b'TEST FIXTURE 1')
  (self.root/'roms/snes/My Legal Homebrew.sfc').write_bytes(b'TEST FIXTURE 2')
  legacy=self.root/'roms/stations/4/nes';legacy.mkdir(parents=True);(legacy/'Tetris.nes').write_bytes(b'TEST FIXTURE 3')
  r=self.report();self.assertEqual(len(r['available']),3);self.assertEqual(len(r['games']),1)
  self.include_unlisted();self.select('Super Mario World','Tetris')
  r=self.report();self.assertEqual(len(r['games']),3)
  self.assertEqual({s['games'] for s in r['stations']},{3});self.assertEqual({s['library'] for s in r['stations']},{'shared'})
  self.assertFalse((self.root/'build/station-1').exists())
 def test_station_count_configurable(self):
  path=self.root/'config/stations.json';stations=json.loads(path.read_text());path.write_text(json.dumps(stations[:4]))
  self.assertEqual(len(self.report()['stations']),4)
 def test_same_name_different_content_is_not_overwritten(self):
  self.include_unlisted()
  (self.root/'roms/snes/Test.sfc').write_bytes(b'FIRST')
  folder=self.root/'roms/stations/5/snes';folder.mkdir(parents=True);(folder/'Test.sfc').write_bytes(b'SECOND')
  self.assertTrue(self.report()['errors'])
  self.assertEqual((self.root/'build/shared/roms/snes/Test.sfc').read_bytes(),b'FIRST')
 def test_cue_tracks_and_path_traversal(self):
  self.select('Crash Bandicoot')
  base=self.root/'roms/psx';base.mkdir();cue=base/'Crash Bandicoot.cue';cue.write_text('FILE "Crash.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n')
  self.assertTrue(self.report()['errors'])
  (base/'Crash.bin').write_bytes(b'TEST FIXTURE');r=self.report();self.assertEqual(len(r['games']),1)
  cue.write_text('FILE "../../outside.bin" BINARY\n');self.assertTrue(any('fora' in e for e in self.report()['errors']))
 def test_zip_validation(self):
  import zipfile
  base=self.root/'roms/snes';file=base/'Super Mario World.zip'
  with zipfile.ZipFile(file,'w') as z:z.writestr('game.sfc',b'TEST FIXTURE')
  self.assertEqual(len(library.dependencies(file,base)),1)
  with zipfile.ZipFile(file,'w') as z:z.writestr('../game.sfc',b'TEST FIXTURE')
  with self.assertRaises(ValueError):library.dependencies(file,base)
 def test_bios_copied_and_manifest_checks_every_file(self):
  (self.root/'bios/scph5501.bin').write_bytes(b'TEST BIOS')
  r=self.report();self.assertIn('INCORRETO',r['bios']['psx']['scph5501.bin'])
  manifest=json.loads((self.root/'build/shared-manifest.json').read_text())
  for f in manifest:self.assertEqual(library.digest(self.root/'build/shared'/f['path']),f['sha256'])
  self.assertEqual((self.root/'build/shared/bios/scph5501.bin').read_bytes(),b'TEST BIOS')
 def test_unvalidated_arcade_is_reported_not_shown(self):
  import zipfile
  folder=self.root/'roms/arcade';folder.mkdir()
  with zipfile.ZipFile(folder/'pbobblen.zip','w') as z:z.writestr('TEST',b'TEST FIXTURE')
  r=self.report();self.assertFalse(r['games']);self.assertTrue(r['blocked'])
 def test_controller_mapping_requires_explicit_physical_validation(self):
  self.assertIsNone(self.report()['controllers'])
  config=json.loads((self.root/'config/controllers.json').read_text());config.update(validated=True,players_tested=1)
  (self.root/'config/controllers.json').write_text(json.dumps(config))
  with self.assertRaises(ValueError):self.report()
 def test_both_controller_profiles_can_be_included_by_guid(self):
  folder=self.root/'controllers';folder.mkdir()
  names=['a','b','x','y','pageup','pagedown','start','select','hotkey','up','down','left','right']
  xml='<inputList><inputConfig type="joystick" deviceGUID="test-guid" deviceName="Test">'+''.join(f'<input name="{n}" type="button" id="{i}" value="1"/>' for i,n in enumerate(names))+'</inputConfig></inputList>'
  (folder/'es_input.cfg').write_text(xml)
  config=json.loads((self.root/'config/controllers.json').read_text());config.update(validated=True,players_tested=2)
  (self.root/'config/controllers.json').write_text(json.dumps(config));r=self.report()
  self.assertEqual(r['controllers'][0]['guid'],'test-guid');self.assertEqual((self.root/'build/shared/system/configs/emulationstation/es_input.cfg').read_text(),xml)
 def test_correct_single_board_image(self):
  image=json.loads((self.root/'config/images.json').read_text())
  self.assertEqual(image['model'],'Raspberry Pi 3 Model B+');self.assertEqual(image['architecture'],'bcm2837');self.assertNotIn('models',image)
 def test_disk_safety(self):
  safe=dict(Whole=True,Internal=False,RemovableMedia=True,VirtualOrPhysical='Physical',DeviceLocation='External',DeviceIdentifier='disk4',TotalSize=16000000000)
  self.assertTrue(flash.eligible(safe))
  for field,value in [('Internal',True),('Whole',False),('RemovableMedia',False),('DeviceLocation','Internal'),('VirtualOrPhysical','Virtual'),('DeviceIdentifier','disk4s1')]:self.assertFalse(flash.eligible(dict(safe,**{field:value})))
  self.assertFalse(flash.eligible({}))
 def test_flash_dry_run_never_writes_or_unmounts(self):
  with patch.object(flash,'ROOT',self.root),patch.object(flash,'listing',return_value=[]),patch.object(sys,'argv',['flash.py','--dry-run']),patch.object(sys,'platform','darwin'),patch.object(flash.subprocess,'run') as run:
   flash.main();run.assert_not_called()
 def test_fixed_userdata_and_disabled_destructive_resize(self):
  boot=master.disable_resize('autoresize=true\nformat-internal=ext4\nsharedevice=NETWORK\n')
  self.assertIn('autoresize=false',boot);self.assertNotIn('autoresize=true',boot);self.assertNotIn('format-internal=',boot);self.assertIn('sharedevice=INTERNAL',boot)
  config=dict(userdata_min_mib=1024,userdata_free_mib=1024,autoresize=False)
  self.assertGreater(master.userdata_size([dict(size=1000)],config),1024**3)
  with self.assertRaises(ValueError):master.userdata_size([],dict(config,autoresize=True))

 def test_deselected_titles_are_not_imported_even_with_include_unlisted(self):
  self.include_unlisted()
  (self.root/'roms/snes/F-Zero.sfc').write_bytes(b'TEST FIXTURE')
  r=self.report();self.assertEqual(len(r['available']),1);self.assertFalse(r['games'])
  self.select('F-Zero');self.assertEqual(len(self.report()['games']),1)
 def test_explicit_variant_selection(self):
  self.select('Super Mario World');path=self.root/'config/games.json';games=json.loads(path.read_text())
  for game in games:
   if game['title']=='Super Mario World':game['files']=['Super Mario World (USA).sfc']
  path.write_text(json.dumps(games));base=self.root/'roms/snes'
  (base/'Super Mario World (USA).sfc').write_bytes(b'USA TEST FIXTURE')
  (base/'Super Mario World (Europe).sfc').write_bytes(b'EU TEST FIXTURE')
  self.include_unlisted();r=self.report();self.assertEqual(len(r['games']),1)
  self.assertIn('(USA)',r['games'][0]['source'])
 def test_challenge_games_selected_by_default_and_catalog_preserved(self):
  games=json.loads((self.root/'config/games.json').read_text())
  self.assertEqual(len(games),38)
  self.assertEqual({g['title'] for g in games if g['selected']},{'Super Mario World','Street Fighter II','Super Mario Kart'})
  r=self.report();self.assertEqual(len(r['selected_missing']),3)
 def test_storage_plans_never_shrink_and_respect_actual_capacity(self):
  record=dict(image_size=100*master.MIB,userdata_bytes=35*master.MIB,free_userdata_bytes=10*master.MIB)
  fixed=master.storage_plan(record,200*master.MIB+123)
  self.assertEqual(fixed['image_bytes'],record['image_size']);self.assertEqual(fixed['unused_card_bytes'],100*master.MIB+123)
  fill=master.storage_plan(record,200*master.MIB+123,True)
  self.assertEqual(fill['image_bytes'],200*master.MIB);self.assertEqual(fill['unused_card_bytes'],123)
  with self.assertRaises(ValueError):master.storage_plan(record,99*master.MIB,True)
  with self.assertRaises(ValueError):master.storage_plan(record,3*1024**4,True)

 def test_ambiguous_selected_versions_require_explicit_choice(self):
  base=self.root/'roms/snes'
  (base/'Super Mario World (USA).sfc').write_bytes(b'USA TEST FIXTURE')
  (base/'Super Mario World (Europe).sfc').write_bytes(b'EU TEST FIXTURE')
  self.assertTrue(any('várias versões' in e for e in self.report()['errors']))
 def test_unaligned_partition_layout_is_rejected(self):
  image=self.root/'unaligned.img'
  with image.open('wb') as stream:stream.truncate(97*master.MIB)
  header=bytearray(512);header[510:512]=b'\x55\xaa'
  struct.pack_into('<B3sB3sII',header,446,0,b'\x00'*3,0x0c,b'\x00'*3,2049,64*2048)
  struct.pack_into('<B3sB3sII',header,462,0,b'\x00'*3,0x83,b'\x00'*3,65*2048,32*2048)
  with image.open('r+b') as stream:stream.write(header)
  with self.assertRaises(ValueError):master.partitions(image)

class NativeImageTests(unittest.TestCase):
 def test_native_fat_ext4_roundtrip_and_corruption_detection(self):
  try:
   for tool in ['mformat','mcopy','mtype','mke2fs','e2fsck','debugfs','resize2fs']:master.tool(tool)
  except ValueError as e:self.skipTest(str(e))
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'cache/master').mkdir(parents=True);source=root/'build/shared/roms/snes';source.mkdir(parents=True)
   (source/'Test Game.sfc').write_bytes(b'TEST FIXTURE NOT A ROM')
   (source/'gamelist.xml').write_text('<gameList><game><path>./Test Game.sfc</path><name>Test</name></game></gameList>')
   bios=root/'build/shared/bios';bios.mkdir();(bios/'test.bin').write_bytes(b'TEST BIOS')
   manifest=[dict(path=p.relative_to(root/'build/shared').as_posix(),size=p.stat().st_size,sha256=library.digest(p)) for p in (root/'build/shared').rglob('*') if p.is_file()]
   fat=root/'boot.fat';fat.touch()
   with fat.open('r+b') as stream:stream.truncate(64*master.MIB)
   with (root/'native.log').open('w') as log:
    master.run([master.tool('mformat'),'-F','-v','BATOCERA','-i',fat,'::'],stdout=log,stderr=log)
    config=root/'batocera-boot.conf';config.write_text(master.disable_resize('autoresize=true\n'))
    master.run([master.tool('mcopy'),'-i',fat,config,'::/batocera-boot.conf'],stdout=log,stderr=log)
    ext=root/'userdata.ext4';ext.touch()
    with ext.open('r+b') as stream:stream.truncate(32*master.MIB)
    master.run([master.tool('mke2fs'),'-q','-F','-t','ext4','-b','4096','-L','SHARE','-d',root/'build/shared',ext],stdout=log,stderr=log)
    image=root/'master.img';image.touch()
    with image.open('r+b') as stream:stream.truncate(97*master.MIB)
    header=bytearray(512);header[510:512]=b'\x55\xaa'
    struct.pack_into('<B3sB3sII',header,446,0,b'\x00'*3,0x0c,b'\x00'*3,2048,64*2048)
    struct.pack_into('<B3sB3sII',header,462,0,b'\x00'*3,0x83,b'\x00'*3,65*2048,32*2048)
    with image.open('r+b') as f:f.write(header)
    master.copy_range(fat,image,0,64*master.MIB,master.MIB);master.copy_range(ext,image,0,32*master.MIB,65*master.MIB)
    with patch.object(master,'ROOT',root):
     result=master.verify_image(image,manifest,log);self.assertEqual(result['files_verified'],3)
     result=master.verify_image(image,manifest,log);self.assertEqual(result['files_verified'],3)
     source_sha=library.digest(image)
     record=dict(image_size=image.stat().st_size,userdata_bytes=32*master.MIB,free_userdata_bytes=result['free_userdata_bytes'])
     for capacity in [160*master.MIB+12345,194*master.MIB+12345,224*master.MIB+12345]:
      expanded=root/f'expanded-{capacity}.img'
      grown=master.expand_image(image,expanded,capacity,manifest,record,log)
      self.assertEqual(grown['files_verified'],3)
      self.assertLessEqual(expanded.stat().st_size,capacity)
      self.assertLess(grown['unused_card_bytes'],master.MIB)
      self.assertGreater(grown['free_userdata_bytes'],result['free_userdata_bytes'])
      self.assertLessEqual(grown['filesystem_bytes'],grown['userdata_bytes'])
      self.assertGreaterEqual(grown['userdata_padding_bytes'],0)
      self.assertEqual(library.digest(image),source_sha)
     from types import SimpleNamespace
     with patch.object(master.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
      with self.assertRaises(ValueError):master.expand_image(image,root/'no-space.img',256*master.MIB,manifest,record,log)
     self.assertFalse((root/'no-space.img').exists())
     broken=[dict(item,sha256='0'*64) for item in manifest]
     with self.assertRaises(ValueError):master.verify_image(image,broken,log)

class FlashWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  folder=self.root/'cache/master';folder.mkdir(parents=True);(self.root/'build').mkdir()
  (folder/'glua-arcade-pi3bplus.img').write_bytes(b'TEST IMAGE'*52)
  self.size=(folder/'glua-arcade-pi3bplus.img').stat().st_size
  (folder/'master.json').write_text(json.dumps(dict(ready_to_flash=True,event_ready=True,image_size=self.size,minimum_card_bytes=self.size,sha256='hash',manifest_sha256='hash',games=[])))
  (self.root/'build/shared-manifest.json').write_text('[]')
  self.safe=dict(Whole=True,Internal=False,RemovableMedia=True,VirtualOrPhysical='Physical',DeviceLocation='External',DeviceIdentifier='disk4',TotalSize=16000000000,MediaName='TEST CARD')
 def tearDown(self):self.temp.cleanup()
 def invoke(self,info,confirmation='APAGAR disk4'):
  with patch.object(flash,'ROOT',self.root),patch.object(flash,'listing',return_value=[self.safe]),patch.object(flash,'diskinfo',side_effect=info),patch.object(sys,'argv',['flash.py','--disk','disk4']),patch.object(sys,'platform','darwin'),patch('builtins.input',return_value=confirmation),patch.object(library,'digest',return_value='hash'),patch.object(master,'partitions',return_value=[]),patch.object(flash.subprocess,'run') as run:
   try:flash.main()
   finally:self.calls=run.call_args_list
 def test_internal_disk_is_rejected_before_any_system_mutation(self):
  with self.assertRaises(SystemExit):self.invoke([dict(self.safe,Internal=True)])
  self.assertEqual(self.calls,[])
 def test_actual_capacity_is_checked_not_card_label(self):
  with self.assertRaises(SystemExit):self.invoke([dict(self.safe,TotalSize=self.size-1)])
  self.assertEqual(self.calls,[])
 def test_explicit_confirmation_cannot_be_skipped(self):
  with self.assertRaises(SystemExit):self.invoke([self.safe],confirmation='no')
  self.assertEqual(self.calls,[])
 def test_replaced_disk_is_rechecked(self):
  with self.assertRaises(SystemExit):self.invoke([self.safe,dict(self.safe,Internal=True)])
  self.assertEqual([call.args[0] for call in self.calls],[['sudo','-v']])
 def test_master_reused_for_two_cards_without_preparation(self):
  image=self.root/'cache/master/glua-arcade-pi3bplus.img';before=image.read_bytes()
  for _ in range(2):
   self.invoke([self.safe,self.safe])
   commands=[call.args[0] for call in self.calls]
   self.assertTrue(any(cmd[:2]==['sudo','dd'] for cmd in commands))
   self.assertEqual(commands[-1],['diskutil','eject','/dev/disk4'])
   self.assertFalse(any('prepare' in str(cmd) or 'master.py' in str(cmd) for cmd in commands))
   verifier=next(cmd for cmd in commands if cmd[:2]==['sudo',sys.executable])
   compile(verifier[3],'<flash verify>','exec')
  self.assertEqual(image.read_bytes(),before)

class ExpandedFlashTests(unittest.TestCase):
 setUp=FlashWorkflowTests.setUp
 tearDown=FlashWorkflowTests.tearDown
 def invoke(self,info,confirmation='APAGAR disk4'):
  # Exercise the real --fill-card branch, with filesystem work simulated here.
  from contextlib import ExitStack
  with ExitStack() as stack:
   stack.enter_context(patch.object(flash,'ROOT',self.root))
   stack.enter_context(patch.object(flash,'listing',return_value=[self.safe]))
   stack.enter_context(patch.object(flash,'diskinfo',side_effect=info))
   stack.enter_context(patch.object(sys,'argv',['flash.py','--disk','disk4','--fill-card']))
   stack.enter_context(patch.object(sys,'platform','darwin'))
   stack.enter_context(patch('builtins.input',return_value=confirmation))
   stack.enter_context(patch.object(library,'digest',return_value='hash'))
   stack.enter_context(patch.object(master,'partitions',return_value=[]))
   expand=stack.enter_context(patch.object(master,'expand_image',return_value=dict(image_bytes=16000000000,free_userdata_bytes=15000000000,userdata_padding_bytes=0)))
   run=stack.enter_context(patch.object(flash.subprocess,'run'))
   try:flash.main()
   finally:self.calls=run.call_args_list;self.expansions=expand.call_args_list
 def test_expansion_is_done_on_a_temporary_file_not_the_master(self):
  self.invoke([self.safe,self.safe])
  self.assertEqual(len(self.expansions),1)
  source,destination,capacity,*_=self.expansions[0].args
  self.assertNotEqual(source,destination);self.assertEqual(capacity,self.safe['TotalSize'])
  dd=next(c.args[0] for c in self.calls if c.args[0][:2]==['sudo','dd'])
  self.assertIn('if='+str(destination),dd)
  self.assertFalse(destination.exists())
