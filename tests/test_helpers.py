import json
import re
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app.app import create_app
from app.database import connect
from werkzeug.security import check_password_hash,generate_password_hash

class HelperAccountsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.pin_hash=generate_password_hash('shared-test-pin')
  cls.admin_hash=generate_password_hash('admin-test-password')
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'event.sqlite3'
  self.config=dict(TESTING=True,SECRET_KEY='tests-only',DATABASE=str(self.path),ADMIN_USERNAME='owner',ADMIN_HASH=self.admin_hash,VOLUNTEER_HASH=self.pin_hash)
  self.app=create_app(self.config);self.admin=self.app.test_client()
  with self.admin.session_transaction() as s:s.update(role='admin',volunteer='Owner',csrf='test')
 def tearDown(self):self.temp.cleanup()
 def post(self,path,values,client=None):
  client=client or self.admin
  with client.session_transaction() as s:csrf=s.get('csrf','test')
  return client.post(path,json=values,headers={'X-CSRF-Token':csrf})
 def create(self,username='ana',password='test-password',**extra):
  values=dict(username=username,display_name='Ana',password=password);values.update(extra)
  return self.post('/admin/helpers',values)
 def login(self,client,username='ana',password='test-password'):
  client.get('/login')
  with client.session_transaction() as s:csrf=s['csrf']
  return client.post('/login',data=dict(csrf=csrf,volunteer=username,pin=password))
 def delete(self,uid,username='ana',**extra):
  values=dict(confirmation='APAGAR '+username,reason='Fim do turno');values.update(extra)
  return self.post(f'/admin/helpers/{uid}/delete',values)
 def test_create_hashed_account_login_and_permissions(self):
  created=self.create(role='admin');self.assertEqual(created.status_code,201)
  with connect(self.path) as db:
   row=db.execute('SELECT * FROM helpers').fetchone()
   self.assertNotEqual(row['password_hash'],'test-password');self.assertTrue(check_password_hash(row['password_hash'],'test-password'))
  client=self.app.test_client();self.assertEqual(self.login(client,'ANA').status_code,302)
  self.assertEqual(client.get('/volunteer/racing').status_code,200)
  self.assertEqual(client.get('/admin').status_code,403)
  self.assertEqual(client.get('/admin/helpers').status_code,403)
  self.assertEqual(self.post('/admin/helpers',dict(username='evil',password='test-password'),client).status_code,403)
  self.assertEqual(self.post('/api/players',dict(nickname='Participant'),client).status_code,201)
  with client.session_transaction() as s:self.assertEqual(s['role'],'volunteer')
 def test_invalid_duplicate_and_reserved_names(self):
  self.assertEqual(self.create('ana').status_code,201)
  self.assertEqual(self.create(' ANA ').status_code,409)
  for name in ['a','name with spaces','owner','OWNER','x'*41]:self.assertEqual(self.create(name).status_code,400)
  self.assertEqual(self.create('another',password='short').status_code,400)
  self.assertEqual(self.create('another',display_name='\x00bad').status_code,400)
  self.assertEqual(self.create('another',password=None).status_code,400)
 def test_csrf_and_public_permissions(self):
  client=self.app.test_client()
  self.assertEqual(client.get('/admin/helpers').status_code,403)
  self.assertEqual(client.get('/admin/helpers/1/delete').status_code,403)
  self.assertEqual(self.admin.post('/admin/helpers',json=dict(username='ana',password='test-password')).status_code,400)
  self.assertEqual(self.admin.post('/admin/helpers/shared-pin',json=dict(enabled='0')).status_code,400)
 def test_delete_revokes_open_sessions_and_preserves_results(self):
  uid=self.create().json['id'];client=self.app.test_client();self.login(client)
  pid=self.post('/api/players',dict(nickname='Player'),client).json['id']
  self.post('/api/attempt/racing',dict(player=pid,action='manual',time='01:23.45',token=secrets.token_hex(16)),client)
  self.assertEqual(self.delete(uid).status_code,200)
  self.assertEqual(client.get('/volunteer/racing').status_code,403)
  self.assertIn('Player',client.get('/leaderboard/racing').text)
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT volunteer FROM attempts').fetchone()[0],'Ana (ana)')
   rows=db.execute('SELECT * FROM audit').fetchall();self.assertEqual(len(rows),2)
   self.assertEqual(rows[-1]['action'],'helper_deleted');self.assertIsNone(rows[-1]['attempt_id'])
   self.assertEqual(json.loads(rows[-1]['before_json'])['username'],'ana')
   self.assertNotIn('password',json.dumps([dict(r) for r in rows]))
   self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
  self.assertEqual(self.login(client).status_code,200)
  self.assertEqual(client.get('/volunteer/racing').status_code,403)
 def test_delete_confirmation_and_stale_account_ids(self):
  uid=self.create().json['id'];old=self.app.test_client();self.login(old)
  self.assertEqual(self.admin.get(f'/admin/helpers/{uid}/delete').status_code,200)
  self.assertEqual(self.delete(uid,confirmation='yes').status_code,400)
  self.assertEqual(self.delete(uid,reason='').status_code,400)
  self.assertEqual(self.delete(uid).status_code,200)
  new_uid=self.create().json['id'];self.assertGreater(new_uid,uid)
  self.assertEqual(self.delete(uid).status_code,404)
  self.assertEqual(old.get('/volunteer/platformers').status_code,403)
 def test_disable_shared_pin_and_reenable_does_not_restore_old_sessions(self):
  legacy=self.app.test_client();self.assertEqual(self.login(legacy,'Any Helper','shared-test-pin').status_code,302)
  uid=self.create(disable_shared_pin='on').json['id']
  self.assertEqual(self.admin.get('/admin').status_code,200)
  named=self.app.test_client();self.assertEqual(self.login(named).status_code,302)
  self.assertEqual(named.get('/volunteer/platformers').status_code,200)
  self.post('/admin/helpers/shared-pin',dict(enabled='1'))
  # The old browser did not make any request while the PIN was disabled.
  self.assertEqual(legacy.get('/volunteer/platformers').status_code,403)
  self.assertEqual(self.login(legacy,'Other Helper','shared-test-pin').status_code,302)
  self.assertEqual(named.get('/volunteer/platformers').status_code,200)
  self.assertEqual(self.delete(uid).status_code,200)
 def test_disabled_pin_cannot_login_and_known_account_cannot_fall_back(self):
  self.create();client=self.app.test_client()
  self.assertEqual(self.login(client,'ana','shared-test-pin').status_code,200)
  self.assertEqual(client.get('/volunteer/racing').status_code,403)
  self.post('/admin/helpers/shared-pin',dict(enabled='0'))
  self.assertEqual(self.login(client,'Legacy','shared-test-pin').status_code,200)
  self.assertEqual(client.get('/volunteer/racing').status_code,403)
  self.assertEqual(self.login(client,'owner','admin-test-password').status_code,302)
  self.assertEqual(client.get('/admin/helpers').status_code,200)
 def test_reset_and_restart_preserve_helpers_and_pin_setting(self):
  self.create(disable_shared_pin='on')
  self.post('/api/players',dict(nickname='Test Player'))
  html=self.admin.get('/admin/reset').text;snapshot=re.search(r'name="snapshot" value="([^"]+)"',html)[1]
  response=self.post('/admin/reset',dict(snapshot=snapshot,reason='Test data',confirmation='APAGAR TODOS OS DADOS'))
  self.assertEqual(response.status_code,200)
  new_app=create_app(self.config);client=new_app.test_client()
  self.assertEqual(self.login(client).status_code,302);self.assertEqual(client.get('/volunteer/racing').status_code,200)
  legacy=new_app.test_client();self.assertEqual(self.login(legacy,'Legacy','shared-test-pin').status_code,200)
  self.assertEqual(legacy.get('/volunteer/racing').status_code,403)
 def test_deletion_rolls_back_if_audit_fails(self):
  uid=self.create().json['id']
  with connect(self.path) as db:
   db.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON audit WHEN NEW.action='helper_deleted' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.delete(uid)
  with connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM helpers').fetchone()[0],1)
 def test_html_forms_and_no_password_disclosure(self):
  self.assertEqual(self.admin.get('/admin/helpers').status_code,200)
  response=self.admin.post('/admin/helpers',data=dict(csrf='test',username='ana',password='test-password',display_name='Ana',disable_shared_pin='on'))
  self.assertEqual(response.status_code,302)
  html=self.admin.get('/admin/helpers').text;self.assertIn('ana',html);self.assertNotIn('test-password',html);self.assertNotIn('scrypt:',html)
  self.assertNotIn('test-password',self.admin.get('/admin/export/audit.csv').text)
 def test_legacy_database_gets_accounts_without_losing_tournament_rows(self):
  # Simulate an existing installation before account management was added.
  with connect(self.path) as db:
   db.execute('DROP TABLE helpers');db.execute('DROP TABLE app_settings')
   db.execute("INSERT INTO participants(id,nickname,name_key) VALUES (1,'Existing Player','existing player')")
   db.execute("INSERT INTO attempts(id,participant_id,challenge_id,number,status,volunteer,token) VALUES (1,1,'racing',1,'failed','Original volunteer','legacy-test-token-12345')")
  upgraded=create_app(self.config)
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT nickname FROM participants').fetchone()[0],'Existing Player')
   self.assertEqual(db.execute('SELECT volunteer FROM attempts').fetchone()[0],'Original volunteer')
   self.assertEqual(db.execute('SELECT COUNT(*) FROM helpers').fetchone()[0],0)
  client=upgraded.test_client()
  with client.session_transaction() as s:s.update(role='admin',volunteer='Owner',csrf='test')
  self.assertEqual(client.get('/admin/helpers').status_code,200)
