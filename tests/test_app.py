import concurrent.futures
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from app.app import create_app,parse_time
from app.database import connect,backup
from werkzeug.security import generate_password_hash

class TournamentTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.hash=generate_password_hash('123456')
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'event.sqlite3'
  self.config=dict(TESTING=True,SECRET_KEY='test-only',DATABASE=str(self.path),VOLUNTEER_HASH=self.hash,ADMIN_HASH=generate_password_hash('admin-pin'))
  self.app=create_app(self.config);self.client=self.app.test_client();self.login(self.client)
 def tearDown(self):self.temp.cleanup()
 def login(self,client,role='volunteer'):
  with client.session_transaction() as s:s.update(role=role,volunteer='Teste',csrf='csrf-test')
 def post(self,url,payload,client=None):return (client or self.client).post(url,json=payload,headers={'X-CSRF-Token':'csrf-test'})
 def player(self,name='Tux'):
  response=self.post('/api/players',{'nickname':name});self.assertEqual(response.status_code,201);return response.json['id']
 def reserve(self,pid,cid='platformers',action='start',**kw):
  return self.post('/api/attempt/'+cid,dict(player=pid,action=action,token=secrets.token_hex(16),**kw))
 def admin(self):self.login(self.client,'admin')
 def test_registration_and_duplicate(self):
  self.player('  Tux   Linux ')
  self.assertEqual(self.post('/api/players',{'nickname':'tux linux'}).status_code,409)
  self.player('Tux Linux 2')
  self.assertEqual(len(self.client.get('/api/players?q=tux').json),2)
 def test_invalid_names(self):
  for value in ['','x','x'*41,'ab\x00cd']:
   self.assertEqual(self.post('/api/players',{'nickname':value}).status_code,400)
 def test_start_stop_save_and_idempotent_transitions(self):
  pid=self.player();r=self.reserve(pid);self.assertEqual(r.status_code,201);aid=r.json['id']
  self.assertEqual(self.client.get('/api/state/platformers?player='+str(pid)).json['remaining'],2)
  time.sleep(.02)
  stopped=self.post(f'/api/attempts/{aid}/stop',{});self.assertEqual(stopped.json['status'],'stopped');self.assertGreaterEqual(stopped.json['centiseconds'],1)
  self.assertEqual(self.post(f'/api/attempts/{aid}/stop',{}).json['centiseconds'],stopped.json['centiseconds'])
  self.assertEqual(self.post(f'/api/attempts/{aid}/save',{}).json['status'],'valid')
  self.assertEqual(self.post(f'/api/attempts/{aid}/save',{}).status_code,200)
 def test_manual_times_and_validation(self):
  pid=self.player()
  for value in ['01:60.00','-1','0:00.00','abc','1:02.123','9999:00.00']:
   self.assertEqual(self.reserve(pid,'racing','manual',time=value).status_code,400)
  r=self.reserve(pid,'racing','manual',time='01:23.45');self.assertEqual(r.json['centiseconds'],8345)
  self.assertEqual(parse_time('23.45'),2345)
 def test_failed_uses_attempt(self):
  pid=self.player();aid=self.reserve(pid).json['id']
  self.assertEqual(self.post(f'/api/attempts/{aid}/failed',{}).json['status'],'failed')
  self.assertEqual(self.reserve(pid,action='failed').status_code,201)
  self.assertEqual(self.client.get(f'/api/state/platformers?player={pid}').json['remaining'],1)
 def test_three_attempts_per_challenge(self):
  pid=self.player()
  for cid in ['platformers','fighting','racing']:
   for _ in range(3):self.assertEqual(self.reserve(pid,cid,'failed').status_code,201)
   self.assertEqual(self.reserve(pid,cid,'failed').status_code,409)
  with connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],9)
 def test_active_station_lock_includes_stopped(self):
  a=self.player();b=self.player('Bit');aid=self.reserve(a).json['id']
  self.assertEqual(self.reserve(b).status_code,409)
  self.post(f'/api/attempts/{aid}/stop',{})
  self.assertEqual(self.reserve(b).status_code,409)
  self.post(f'/api/attempts/{aid}/save',{})
  self.assertEqual(self.reserve(b).status_code,201)
 def test_concurrent_timer_starts(self):
  pid=self.player()
  def start(_):
   with self.app.test_client() as client:
    self.login(client)
    return self.post('/api/attempt/platformers',dict(player=pid,action='start',token=secrets.token_hex(16)),client).status_code
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:codes=list(pool.map(start,range(8)))
  self.assertEqual(codes.count(201),1);self.assertEqual(codes.count(409),7)
 def test_concurrent_manual_limit(self):
  pid=self.player()
  def save(_):
   with self.app.test_client() as client:
    self.login(client)
    return self.post('/api/attempt/racing',dict(player=pid,action='manual',time='01:01.01',token=secrets.token_hex(16)),client).status_code
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:codes=list(pool.map(save,range(10)))
  self.assertEqual(codes.count(201),3);self.assertEqual(codes.count(409),7)
 def test_idempotent_reservation(self):
  pid=self.player();payload=dict(player=pid,action='manual',time='01:01.01',token=secrets.token_hex(16))
  a=self.post('/api/attempt/racing',payload);b=self.post('/api/attempt/racing',payload)
  self.assertEqual(a.json['id'],b.json['id'])
  self.assertEqual(len(self.client.get(f'/api/state/racing?player={pid}').json['attempts']),1)
 def test_leaderboard_best_ties_and_attempts(self):
  a=self.player();b=self.player('Bit')
  self.reserve(a,'racing','manual',time='01:10.00');self.reserve(a,'racing','manual',time='01:00.00');self.reserve(a,'racing','failed')
  self.reserve(b,'racing','manual',time='01:00.00')
  self.admin();rows=self.client.get('/admin/export/leaderboards.csv').text
  self.assertLess(rows.index('Tux'),rows.index('Bit'));self.assertIn('6000,3',rows)
  self.assertNotIn('Tux',self.client.get('/leaderboard/fighting').text)
 def test_restart_marks_running_failed(self):
  pid=self.player();self.reserve(pid)
  other=create_app(self.config);client=other.test_client();self.login(client)
  state=client.get(f'/api/state/platformers?player={pid}').json
  self.assertIsNone(state['active']);self.assertEqual(state['remaining'],2);self.assertEqual(state['attempts'][0]['status'],'failed')
  with connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],1)
 def test_stopped_time_survives_restart(self):
  aid=self.reserve(self.player()).json['id'];stopped=self.post(f'/api/attempts/{aid}/stop',{}).json
  other=create_app(self.config);client=other.test_client();self.login(client)
  saved=self.post(f'/api/attempts/{aid}/save',{},client).json
  self.assertEqual(saved['centiseconds'],stopped['centiseconds'])
 def test_admin_correction_void_and_audit(self):
  pid=self.player();aid=self.reserve(pid,'racing','manual',time='01:02.34').json['id']
  self.assertEqual(self.post(f'/admin/attempts/{aid}',dict(status='valid',time='00:45.00',reason='Erro de transcrição')).status_code,403)
  self.admin();self.assertEqual(self.post(f'/admin/attempts/{aid}',dict(status='valid',time='00:45.00',reason='Erro de transcrição')).status_code,200)
  self.assertEqual(self.post(f'/admin/attempts/{aid}',dict(status='void',reason='Jogador errado')).status_code,200)
  self.assertEqual(self.client.get(f'/api/state/racing?player={pid}').json['remaining'],3)
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],2)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],1)
 def test_persistence_and_online_backup(self):
  pid=self.player();self.reserve(pid,'racing','manual',time='01:00.00')
  saved=Path(self.temp.name)/'backup.sqlite3';backup(self.path,saved)
  with connect(saved) as db:self.assertEqual(db.execute('SELECT centiseconds FROM attempts').fetchone()[0],6000)
  app=create_app(self.config);client=app.test_client()
  self.assertIn('Tux',client.get('/leaderboard/racing').text)
 def test_permissions_csrf_and_login(self):
  anonymous=self.app.test_client();self.assertEqual(anonymous.get('/leaderboard/racing').status_code,200)
  self.assertEqual(anonymous.get('/api/players').status_code,403)
  self.assertEqual(self.client.post('/api/players',json={'nickname':'NoCSRF'}).status_code,400)
  anonymous.get('/login')
  with anonymous.session_transaction() as s:csrf=s['csrf']
  self.assertEqual(anonymous.post('/login',data=dict(csrf=csrf,pin='wrong',volunteer='A')).status_code,200)
  self.assertEqual(anonymous.post('/login',data=dict(csrf=csrf,pin='123456',volunteer='A')).status_code,302)
  self.assertEqual(anonymous.get('/volunteer/racing').status_code,200)
 def test_all_routes_and_exactly_three_boards(self):
  self.admin()
  for url in ['/','/login','/admin','/leaderboard/platformers','/leaderboard/fighting','/leaderboard/racing','/volunteer/platformers','/volunteer/fighting','/volunteer/racing','/admin/export/participants.csv','/admin/export/attempts.csv','/admin/export/leaderboards.csv','/admin/export/audit.csv','/static/volunteer.js','/static/style.css']:
   response=self.client.get(url);self.assertEqual(response.status_code,200,url);response.close()
  for cid in ['4','5','arcade','psx']:self.assertEqual(self.client.get('/leaderboard/'+cid).status_code,404)
 def test_xss_escaped_and_csv_safe(self):
  pid=self.player('<script>alert(1)</script>');self.player('=1+1')
  self.reserve(pid,'racing','manual',time='01:00.00')
  self.admin();self.assertIn("'=1+1",self.client.get('/admin/export/participants.csv').text)
  html=self.client.get('/leaderboard/racing').text
  self.assertNotIn('<script>alert(1)</script>',html)
  self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)

if __name__=='__main__':unittest.main()

class InputTests(unittest.TestCase):
 def test_non_object_json_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   app=create_app(dict(TESTING=True,SECRET_KEY='test',DATABASE=str(Path(folder)/'test.sqlite3')))
   client=app.test_client()
   with client.session_transaction() as session:session.update(role='admin',volunteer='test',csrf='test')
   for payload in [['not an object'],42,'string',None]:
    response=client.post('/api/players',json=payload,headers={'X-CSRF-Token':'test'})
    self.assertEqual(response.status_code,400)

class AccountLoginTests(unittest.TestCase):
 def test_admin_account_requires_matching_username_and_password(self):
  with tempfile.TemporaryDirectory() as folder:
   app=create_app(dict(TESTING=True,SECRET_KEY='test',DATABASE=str(Path(folder)/'accounts.sqlite3'),ADMIN_USERNAME='account-test',ADMIN_HASH=generate_password_hash('test-password'),VOLUNTEER_HASH=''))
   client=app.test_client();client.get('/login')
   with client.session_transaction() as session:csrf=session['csrf']
   for username,password in [('wrong','test-password'),('account-test','wrong')]:
    result=client.post('/login',data=dict(csrf=csrf,volunteer=username,pin=password))
    self.assertEqual(result.status_code,200)
    self.assertEqual(client.get('/admin').status_code,403)
   result=client.post('/login',data=dict(csrf=csrf,volunteer='account-test',pin='test-password'))
   self.assertEqual(result.status_code,302)
   self.assertEqual(client.get('/admin').status_code,200)
