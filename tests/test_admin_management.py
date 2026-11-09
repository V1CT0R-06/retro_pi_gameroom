import json
import re
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app.app import create_app
from app.database import connect

class AdminManagementTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'event.sqlite3'
  self.app=create_app(dict(TESTING=True,SECRET_KEY='test',DATABASE=str(self.path)))
  self.client=self.app.test_client();self.role('admin')
 def tearDown(self): self.temp.cleanup()
 def role(self,role):
  with self.client.session_transaction() as session:session.update(role=role,volunteer='Admin Test',csrf='test')
 def post(self,url,**values):return self.client.post(url,json=values,headers={'X-CSRF-Token':'test'})
 def player(self,name='Test Player'):return self.post('/api/players',nickname=name).json['id']
 def attempt(self,pid,cid='racing',action='manual'):
  return self.post('/api/attempt/'+cid,player=pid,action=action,time='01:23.45',token=secrets.token_hex(16)).json['id']
 def delete(self,pid,name='Test Player',**extra):
  values=dict(nickname=name,confirmation=f'APAGAR {pid}',reason='Inscrição de teste');values.update(extra)
  return self.post(f'/admin/participants/{pid}/delete',**values)
 def snapshot(self):
  response=self.client.get('/admin/reset')
  return re.search(r'name="snapshot" value="([^"]+)"',response.text)[1]
 def reset(self,snapshot,**extra):
  values=dict(snapshot=snapshot,confirmation='APAGAR TODOS OS DADOS',reason='Preparar evento');values.update(extra)
  return self.post('/admin/reset',**values)
 def test_delete_linked_attempts_audit_and_leaderboards(self):
  pid=self.player();other=self.player('Keep Player')
  aid=self.attempt(pid);keep=self.attempt(other)
  self.post(f'/admin/attempts/{aid}',status='valid',time='01:00.00',reason='Corrigir teste')
  html=self.client.get('/admin').text
  self.assertIn(f'#{pid}',html);self.assertIn('Apagar participante',html)
  self.assertIn('Test Player',self.client.get('/leaderboard/racing').text)
  self.assertEqual(self.delete(pid).status_code,200)
  html=self.client.get('/leaderboard/racing').text
  self.assertNotIn('Test Player',html);self.assertIn('Keep Player',html)
  with connect(self.path) as db:
   self.assertIsNone(db.execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone())
   self.assertEqual(db.execute('SELECT id FROM attempts').fetchone()[0],keep)
   self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
   rows=db.execute('SELECT * FROM audit ORDER BY id').fetchall()
   self.assertEqual(len(rows),2);self.assertIsNone(rows[0]['attempt_id'])
   deleted=json.loads(rows[1]['before_json'])
   self.assertEqual(deleted['participant']['id'],pid);self.assertEqual(deleted['participant']['nickname'],'Test Player')
   self.assertEqual(deleted['reason'],'Inscrição de teste');self.assertEqual(rows[1]['actor'],'Admin Test')
 def test_confirmation_reason_identity_and_no_get_deletion(self):
  pid=self.player()
  self.assertEqual(self.client.get(f'/admin/participants/{pid}/delete').status_code,200)
  for values in [dict(reason=''),dict(confirmation='APAGAR'),dict(nickname='Wrong Player')]:
   self.assertIn(self.delete(pid,**values).status_code,(400,409))
  with connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0],1)
 def test_admin_only_and_csrf(self):
  pid=self.player();self.role('volunteer')
  self.assertEqual(self.delete(pid).status_code,403)
  self.assertEqual(self.client.get(f'/admin/participants/{pid}/delete').status_code,403)
  self.assertEqual(self.client.get('/admin/reset').status_code,403)
  self.assertEqual(self.reset('wrong').status_code,403)
  self.role('admin')
  self.assertEqual(self.client.post(f'/admin/participants/{pid}/delete',json={}).status_code,400)
  self.assertEqual(self.client.post('/admin/reset',json={}).status_code,400)
  anonymous=self.app.test_client()
  self.assertEqual(anonymous.get('/admin/reset').status_code,403)
 def test_active_and_stopped_must_be_resolved(self):
  pid=self.player();aid=self.attempt(pid,'platformers','start')
  self.assertEqual(self.delete(pid).status_code,409)
  self.assertEqual(self.reset(self.snapshot()).status_code,409)
  self.post(f'/api/attempts/{aid}/stop')
  self.assertEqual(self.delete(pid).status_code,409)
  self.assertEqual(self.reset(self.snapshot()).status_code,409)
  self.post(f'/api/attempts/{aid}/failed')
  self.assertEqual(self.delete(pid).status_code,200)
 def test_unrelated_active_attempt_is_preserved(self):
  pid=self.player();other=self.player('Other Player');aid=self.attempt(other,'platformers','start')
  self.assertEqual(self.delete(pid).status_code,200)
  with connect(self.path) as db:self.assertEqual(db.execute('SELECT status FROM attempts WHERE id=?',(aid,)).fetchone()[0],'running')
 def test_delete_is_atomic_when_database_rejects_operation(self):
  pid=self.player();aid=self.attempt(pid)
  self.post(f'/admin/attempts/{aid}',status='failed',reason='Teste')
  with connect(self.path) as db:db.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON participants BEGIN SELECT RAISE(ABORT,'test rollback'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.delete(pid)
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT attempt_id FROM audit').fetchone()[0],aid)
 def test_reset_strong_confirmation_stale_form_and_audit(self):
  pid=self.player();aid=self.attempt(pid)
  self.post(f'/admin/attempts/{aid}',status='failed',reason='Teste')
  snapshot=self.snapshot()
  self.assertEqual(self.reset(snapshot,confirmation='yes').status_code,400)
  self.assertEqual(self.reset(snapshot,reason='').status_code,400)
  self.player('New Person')
  self.assertEqual(self.reset(snapshot).status_code,409)
  snapshot=self.snapshot();secret=self.app.config['SECRET_KEY']
  self.assertEqual(self.reset(snapshot).status_code,200)
  self.assertEqual(self.app.config['SECRET_KEY'],secret)
  with self.client.session_transaction() as session:self.assertEqual(session['role'],'admin')
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)
   self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
   rows=db.execute('SELECT * FROM audit ORDER BY id').fetchall()
   self.assertEqual(len(rows),2);self.assertIsNone(rows[0]['attempt_id'])
   self.assertEqual(rows[-1]['action'],'event_data_reset')
   self.assertEqual(json.loads(rows[-1]['before_json'])['attempts'],1)
  self.player('After Reset')
  self.assertEqual(self.reset(snapshot).status_code,409)
 def test_ids_are_never_reused_after_delete_or_reset(self):
  pid=self.player();aid=self.attempt(pid);self.delete(pid)
  next_pid=self.player();next_aid=self.attempt(next_pid)
  self.assertGreater(next_pid,pid);self.assertGreater(next_aid,aid)
  self.assertEqual(self.delete(pid).status_code,404)
  self.reset(self.snapshot())
  last_pid=self.player();last_aid=self.attempt(last_pid)
  self.assertGreater(last_pid,next_pid);self.assertGreater(last_aid,next_aid)
 def test_html_forms_and_dark_error_pages(self):
  pid=self.player()
  response=self.client.post(f'/admin/participants/{pid}/delete',data=dict(csrf='test',nickname='Test Player',reason='Teste',confirmation='wrong'))
  self.assertEqual(response.status_code,400)
  self.assertIn('style.css',response.text);self.assertIn('Voltar à administração',response.text)
  response=self.client.post(f'/admin/participants/{pid}/delete',data=dict(csrf='test',nickname='Test Player',reason='Teste',confirmation=f'APAGAR {pid}'))
  self.assertEqual(response.status_code,302);self.assertEqual(response.location,'/admin')
  self.player();snapshot=self.snapshot()
  response=self.client.post('/admin/reset',data=dict(csrf='test',snapshot=snapshot,reason='Teste',confirmation='APAGAR TODOS OS DADOS'))
  self.assertEqual(response.status_code,302)
 def test_reset_rolls_back_on_failure(self):
  pid=self.player();self.attempt(pid);snapshot=self.snapshot()
  with connect(self.path) as db:db.execute("CREATE TRIGGER prevent_reset BEFORE DELETE ON participants BEGIN SELECT RAISE(ABORT,'test rollback'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.reset(snapshot)
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],0)
