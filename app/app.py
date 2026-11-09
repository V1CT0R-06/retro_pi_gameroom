"""Local tournament: one process owns all monotonic timers; SQLite owns slots."""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import time
import threading
import unicodedata
from functools import wraps
from pathlib import Path
from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for, Response
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash
from .database import connect, initialize, backup, next_id

ROOT=Path(__file__).resolve().parent.parent
CHALLENGES=json.loads((ROOT/'config/challenges.json').read_text())
BY_ID={c['id']:c for c in CHALLENGES}

def parse_time(value):
 match=re.fullmatch(r'(?:(\d{1,3}):)?([0-5]?\d)\.(\d{2})',str(value).strip())
 if not match: raise ValueError('Usa MM:SS.CC (ex.: 01:23.45).')
 minutes,seconds,hundredths=match.groups()
 total=(int(minutes or 0)*60+int(seconds))*100+int(hundredths)
 if not 0<total<=3599999: raise ValueError('Tempo fora do intervalo permitido.')
 return total

def format_time(n):
 if n is None: return '—'
 return f'{n//6000:02d}:{n//100%60:02d}.{n%100:02d}'

def create_app(test_config=None):
 app=Flask(__name__)
 local=ROOT/'.local.json'
 settings=json.loads(local.read_text()) if local.exists() else {}
 app.config.update(SECRET_KEY=os.environ.get('GLUA_SECRET',settings.get('secret')),
  DATABASE=str(ROOT/'data/tournament.sqlite3'),
  VOLUNTEER_HASH=settings.get('volunteer_hash',''), ADMIN_HASH=settings.get('admin_hash',''),
  ADMIN_USERNAME=settings.get('admin_username',''),
  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=16384)
 if test_config: app.config.update(test_config)
 if not app.config['SECRET_KEY']: raise RuntimeError('Executa ./prepare.sh para gerar a configuração local.')
 initialize(app.config['DATABASE'])
 boot=secrets.token_hex(16)
 app.config['BOOT_ID']=boot
 # Only run ONE application process. Recover unfinished running timers safely.
 with connect(app.config['DATABASE']) as db:
  for row in db.execute("SELECT * FROM attempts WHERE status='running'").fetchall():
   before=dict(row)
   db.execute("UPDATE attempts SET status='failed',note='Cronómetro interrompido por reinício do servidor' WHERE id=?",(row['id'],))
   db.execute('INSERT INTO audit(attempt_id,actor,action,before_json,after_json) VALUES (?,?,?,?,?)',
    (row['id'],'servidor','restart',json.dumps(before),json.dumps({'status':'failed'})))
 last_backup=[0.0]
 backup_lock=threading.Lock()

 def db():
  if 'db' not in g: g.db=connect(app.config['DATABASE'],managed=False)
  return g.db
 @app.teardown_appcontext
 def close(_):
  if 'db' in g: g.db.close()
 @app.template_filter('clock')
 def clock(n): return format_time(n)
 @app.context_processor
 def context():
  if 'csrf' not in session: session['csrf']=secrets.token_hex(24)
  return dict(challenges=CHALLENGES,csrf=session['csrf'])
 @app.before_request
 def protect():
  if request.method=='POST' and not secrets.compare_digest(session.get('csrf','missing'),request.headers.get('X-CSRF-Token',request.form.get('csrf',''))):
   abort(400,description='Pedido expirado. Atualiza a página.')
 @app.after_request
 def headers(response):
  response.headers['X-Content-Type-Options']='nosniff'
  response.headers['X-Frame-Options']='DENY'
  response.headers['Referrer-Policy']='same-origin'
  response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; form-action 'self'"
  if request.path.startswith(('/api','/volunteer','/admin','/login')): response.headers['Cache-Control']='no-store'
  if request.method=='POST' and response.status_code<400 and time.monotonic()-last_backup[0]>60 and not app.testing:
   if backup_lock.acquire(blocking=False):
    try:
     database_path=Path(app.config['DATABASE'])
     destination=database_path.parent/'backups'/f"{database_path.stem}-auto-{time.strftime('%Y%m%d-%H%M')}.sqlite3"
     backup(database_path,destination)
     last_backup[0]=time.monotonic()
     for old in sorted(destination.parent.glob(database_path.stem+'-auto-*.sqlite3'))[:-336]:old.unlink()
    except Exception:
     app.logger.exception('Falha na cópia automática; os resultados continuam na base principal.')
    finally: backup_lock.release()
  return response
 def authorized(admin=False):
  def decorator(fn):
   @wraps(fn)
   def wrapped(*a,**kw):
    if session.get('role') not in (['admin'] if admin else ['volunteer','admin']): abort(403)
    return fn(*a,**kw)
   return wrapped
  return decorator
 def data():
  if request.is_json:
   payload=request.get_json(silent=True)
   if not isinstance(payload,dict): abort(400,description='É necessário um objeto JSON.')
   return payload
  return request.form
 def challenge(cid):
  if cid not in BY_ID: abort(404)
  return BY_ID[cid]
 def fail(message,code=409):
  if request.is_json or request.path.startswith('/api/'):
   return jsonify(error=message),code
  return render_template('error.html',message=message),code
 @app.errorhandler(HTTPException)
 def http_error(error):return fail(error.description,error.code)
 def participant(pid):
  row=db().execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone()
  if row is None: abort(404)
  return row
 def leaderboard(cid):
  return [dict(r) for r in db().execute('''SELECT p.id,p.nickname,MIN(CASE WHEN a.status='valid' THEN a.centiseconds END) AS best,
   COUNT(*) AS used FROM attempts a JOIN participants p ON p.id=a.participant_id
   WHERE a.challenge_id=? AND a.status!='void' GROUP BY p.id HAVING best IS NOT NULL
   ORDER BY best,p.id''',(cid,))]

 @app.route('/')
 def home():
  return render_template('home.html',participants=db().execute('SELECT COUNT(*) FROM participants').fetchone()[0],attempts=db().execute("SELECT COUNT(*) FROM attempts WHERE status!='void'").fetchone()[0])
 @app.route('/login',methods=['GET','POST'])
 def login():
  error=None
  if request.method=='POST':
   pin=request.form.get('pin','')
   role=None
   username=request.form.get('volunteer','').strip()[:60]
   # Slow password hashes also make brute force deliberately expensive.
   for name in ['admin','volunteer']:
    if name=='admin' and app.config['ADMIN_USERNAME'] and username!=app.config['ADMIN_USERNAME']: continue
    hashed=app.config.get(name.upper()+'_HASH')
    env=os.environ.get('GLUA_'+name.upper()+'_PIN')
    if (hashed and check_password_hash(hashed,pin)) or (env and secrets.compare_digest(env,pin)): role=name; break
   if role:
    session.clear(); session.update(role=role,volunteer=request.form.get('volunteer','').strip()[:60] or role,csrf=secrets.token_hex(24))
    return redirect(url_for('home'))
   error='Utilizador ou palavra-passe/PIN inválido.'
  return render_template('login.html',error=error)
 @app.post('/logout')
 def logout(): session.clear(); return redirect(url_for('home'))
 @app.get('/leaderboard/<cid>')
 def board(cid): return render_template('board.html',challenge=challenge(cid),rows=leaderboard(cid))
 @app.get('/volunteer/<cid>')
 @authorized()
 def volunteer(cid): return render_template('volunteer.html',challenge=challenge(cid))
 @app.get('/api/players')
 @authorized()
 def players():
  q=unicodedata.normalize('NFKC',request.args.get('q','')).casefold().strip()[:60]
  return jsonify([dict(r) for r in db().execute('SELECT id,nickname FROM participants WHERE instr(name_key,?)>0 ORDER BY nickname LIMIT 100',(q,))])
 @app.post('/api/players')
 @authorized()
 def register():
  value=data().get('nickname','')
  if not isinstance(value,str): return fail('Alcunha inválida.',400)
  nickname=' '.join(unicodedata.normalize('NFKC',value).split())
  if not 2<=len(nickname)<=40 or any(unicodedata.category(c).startswith('C') for c in nickname): return fail('Alcunha: 2–40 caracteres visíveis.',400)
  try:
   with db():
    db().execute('BEGIN IMMEDIATE')
    pid=next_id(db(),'participants')
    db().execute('INSERT INTO participants(id,nickname,name_key) VALUES (?,?,?)',(pid,nickname,nickname.casefold()))
   return jsonify(id=pid,nickname=nickname),201
  except sqlite3.IntegrityError: return fail('Alcunha já registada. Seleciona essa pessoa ou escolhe outra alcunha se forem pessoas diferentes.')
 @app.get('/api/state/<cid>')
 @authorized()
 def state(cid):
  challenge(cid)
  pid=request.args.get('player',type=int)
  history=[dict(r) for r in db().execute('SELECT * FROM attempts WHERE participant_id=? AND challenge_id=? ORDER BY id',(pid,cid))] if pid else []
  active=db().execute("SELECT a.*,p.nickname FROM attempts a JOIN participants p ON p.id=a.participant_id WHERE challenge_id=? AND status IN ('running','stopped')",(cid,)).fetchone()
  active=dict(active) if active else None
  if active and active['status']=='running': active['elapsed']=max(0,int((time.monotonic()-active['started'])*100))
  return jsonify(active=active,attempts=history,remaining=3-sum(r['status']!='void' for r in history))
 @app.post('/api/attempt/<cid>')
 @authorized()
 def reserve(cid):
  c=challenge(cid); values=data()
  token=str(values.get('token',''))
  if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',token): return fail('Identificador do pedido inválido.',400)
  try: pid=int(values.get('player',0))
  except (ValueError,TypeError): return fail('Seleciona um jogador.',400)
  participant(pid)
  action=values.get('action')
  if c['mode']=='stopwatch' and action not in ('start','failed'): return fail('Ação inválida.',400)
  if c['mode']=='manual' and action not in ('manual','failed'): return fail('Ação inválida.',400)
  result=None
  if action=='manual':
   try: result=parse_time(values.get('time',''))
   except ValueError as e: return fail(str(e),400)
  connection=db()
  try:
   connection.execute('BEGIN IMMEDIATE')
   previous=connection.execute('SELECT * FROM attempts WHERE token=?',(token,)).fetchone()
   if previous:
    if previous['participant_id']!=pid or previous['challenge_id']!=cid: connection.rollback(); return fail('Pedido repetido com dados diferentes.')
    connection.commit(); return jsonify(dict(previous))
   if connection.execute("SELECT 1 FROM attempts WHERE challenge_id=? AND status IN ('running','stopped')",(cid,)).fetchone(): connection.rollback(); return fail('Já existe uma tentativa por concluir nesta estação.')
   if not connection.execute('SELECT 1 FROM participants WHERE id=?',(pid,)).fetchone(): connection.rollback(); abort(404)
   used={r[0] for r in connection.execute("SELECT number FROM attempts WHERE participant_id=? AND challenge_id=? AND status!='void'",(pid,cid))}
   if len(used)>=3: connection.rollback(); return fail('As três tentativas já foram utilizadas.')
   number=next(n for n in (1,2,3) if n not in used)
   status={'start':'running','manual':'valid','failed':'failed'}[action]
   cur=connection.execute('INSERT INTO attempts(id,participant_id,challenge_id,number,status,centiseconds,started,boot,volunteer,token) VALUES (?,?,?,?,?,?,?,?,?,?)',(next_id(connection,'attempts'),pid,cid,number,status,result,time.monotonic() if action=='start' else None,boot,session['volunteer'],token))
   row=dict(connection.execute('SELECT * FROM attempts WHERE id=?',(cur.lastrowid,)).fetchone()); connection.commit()
   return jsonify(row),201
  except sqlite3.IntegrityError: connection.rollback(); return fail('Conflito de tentativas; atualiza a página.')
 @app.post('/api/attempts/<int:aid>/<action>')
 @authorized()
 def transition(aid,action):
  connection=db(); connection.execute('BEGIN IMMEDIATE')
  row=connection.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()
  if not row: connection.rollback(); abort(404)
  if action=='stop' and row['status']=='stopped': connection.commit(); return jsonify(dict(row))
  if action=='save' and row['status']=='valid': connection.commit(); return jsonify(dict(row))
  if action=='failed' and row['status']=='failed': connection.commit(); return jsonify(dict(row))
  if action=='stop' and row['status']=='running' and row['boot']==boot:
   cs=max(1,int((time.monotonic()-row['started'])*100))
   connection.execute("UPDATE attempts SET status='stopped',centiseconds=? WHERE id=?",(cs,aid))
  elif action=='save' and row['status']=='stopped': connection.execute("UPDATE attempts SET status='valid' WHERE id=?",(aid,))
  elif action=='failed' and row['status'] in ('running','stopped'): connection.execute("UPDATE attempts SET status='failed',centiseconds=NULL WHERE id=?",(aid,))
  else: connection.rollback(); return fail('Transição inválida; atualiza a página.')
  result=dict(connection.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()); connection.commit()
  return jsonify(result)
 @app.get('/admin')
 @authorized(admin=True)
 def admin():
  return render_template('admin.html',participants=db().execute('SELECT p.id,p.nickname,COUNT(a.id) AS attempts FROM participants p LEFT JOIN attempts a ON a.participant_id=p.id GROUP BY p.id ORDER BY p.id').fetchall(),attempts=db().execute('SELECT a.*,p.nickname FROM attempts a JOIN participants p ON p.id=a.participant_id ORDER BY a.id DESC LIMIT 200').fetchall(),audit=db().execute('SELECT * FROM audit ORDER BY id DESC LIMIT 50').fetchall())
 def reset_snapshot():
  records={table:[dict(r) for r in db().execute(f'SELECT * FROM {table} ORDER BY id')] for table in ('participants','attempts')}
  return hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()

 @app.route('/admin/participants/<int:pid>/delete',methods=['GET','POST'])
 @authorized(admin=True)
 def delete_participant(pid):
  if request.method=='GET':
   person=participant(pid)
   count=db().execute('SELECT COUNT(*) FROM attempts WHERE participant_id=?',(pid,)).fetchone()[0]
   return render_template('confirm_delete.html',person=person,count=count)
  values=data()
  reason=str(values.get('reason','')).strip()
  if not 1<=len(reason)<=300 or values.get('confirmation')!=f'APAGAR {pid}':
   return fail('Indica um motivo e escreve a confirmação exata.',400)
  connection=db();connection.execute('BEGIN IMMEDIATE')
  person=connection.execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone()
  if not person: connection.rollback();abort(404)
  if values.get('nickname')!=person['nickname']:
   connection.rollback();return fail('O participante não corresponde à confirmação. Reabre a página.')
  if connection.execute("SELECT 1 FROM attempts WHERE participant_id=? AND status IN ('running','stopped')",(pid,)).fetchone():
   connection.rollback();return fail('Resolve primeiro a tentativa ativa: guardar, marcar falha ou anular.')
  attempt_ids=[r[0] for r in connection.execute('SELECT id FROM attempts WHERE participant_id=?',(pid,))]
  # Keep previous correction audits, detaching only their live foreign keys.
  connection.execute('UPDATE audit SET attempt_id=NULL WHERE attempt_id IN (SELECT id FROM attempts WHERE participant_id=?)',(pid,))
  connection.execute('DELETE FROM attempts WHERE participant_id=?',(pid,))
  connection.execute('DELETE FROM participants WHERE id=?',(pid,))
  before=dict(participant=dict(person),attempt_ids=attempt_ids,reason=reason)
  connection.execute('INSERT INTO audit(actor,action,before_json,after_json) VALUES (?,?,?,?)',
   (session['volunteer'],'participant_deleted',json.dumps(before,ensure_ascii=False),'{}'))
  connection.commit()
  if request.is_json:return jsonify(ok=True)
  return redirect(url_for('admin'))

 @app.route('/admin/reset',methods=['GET','POST'])
 @authorized(admin=True)
 def reset_data():
  if request.method=='GET':
   snapshot=reset_snapshot();session['reset_snapshot']=snapshot
   return render_template('confirm_reset.html',snapshot=snapshot,
    participants=db().execute('SELECT COUNT(*) FROM participants').fetchone()[0],
    attempts=db().execute('SELECT COUNT(*) FROM attempts').fetchone()[0])
  values=data();reason=str(values.get('reason','')).strip()
  if values.get('confirmation')!='APAGAR TODOS OS DADOS' or not 1<=len(reason)<=300:
   return fail('Escreve APAGAR TODOS OS DADOS e indica um motivo.',400)
  connection=db();connection.execute('BEGIN IMMEDIATE')
  snapshot=reset_snapshot()
  if not session.get('reset_snapshot') or values.get('snapshot')!=session['reset_snapshot'] or snapshot!=session['reset_snapshot']:
   connection.rollback();return fail('Os dados mudaram. Reabre a confirmação e verifica os totais.')
  if connection.execute("SELECT 1 FROM attempts WHERE status IN ('running','stopped')").fetchone():
   connection.rollback();return fail('Resolve todas as tentativas ativas antes de repor os dados.')
  people=[dict(r) for r in connection.execute('SELECT id,nickname FROM participants ORDER BY id')]
  count=connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
  if not people and not count: connection.rollback();return fail('Não existem dados para apagar.')
  connection.execute('UPDATE audit SET attempt_id=NULL WHERE attempt_id IS NOT NULL')
  connection.execute('DELETE FROM attempts')
  connection.execute('DELETE FROM participants')
  connection.execute('INSERT INTO audit(actor,action,before_json,after_json) VALUES (?,?,?,?)',
   (session['volunteer'],'event_data_reset',json.dumps(dict(participants=people,attempts=count,reason=reason),ensure_ascii=False),'{}'))
  connection.commit();session.pop('reset_snapshot',None)
  if request.is_json:return jsonify(ok=True)
  return redirect(url_for('admin'))

 @app.post('/admin/attempts/<int:aid>')
 @authorized(admin=True)
 def correct(aid):
  values=data(); status=values.get('status'); reason=str(values.get('reason','')).strip()[:300]
  if status not in ('valid','failed','void') or not reason: return fail('Indica estado e motivo.',400)
  cs=None
  if status=='valid':
   try: cs=parse_time(values.get('time',''))
   except ValueError as e: return fail(str(e),400)
  connection=db(); connection.execute('BEGIN IMMEDIATE')
  row=connection.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()
  if not row: connection.rollback(); abort(404)
  if row['status']=='void': connection.rollback(); return fail('Uma tentativa anulada não pode ser restaurada; regista uma nova.')
  connection.execute('UPDATE attempts SET status=?,centiseconds=?,note=? WHERE id=?',(status,cs,reason,aid))
  connection.execute('INSERT INTO audit(attempt_id,actor,action,before_json,after_json) VALUES (?,?,?,?,?)',(aid,session['volunteer'],reason,json.dumps(dict(row)),json.dumps(dict(connection.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()))))
  connection.commit()
  if request.is_json: return jsonify(ok=True)
  return redirect(url_for('admin'))
 @app.get('/admin/export/<kind>.csv')
 @authorized(admin=True)
 def export(kind):
  if kind=='participants': rows=[dict(r) for r in db().execute('SELECT * FROM participants')]; fields=['id','nickname','name_key','created']
  elif kind=='attempts': rows=[dict(r) for r in db().execute('SELECT * FROM attempts')]; fields=['id','participant_id','challenge_id','number','status','centiseconds','started','boot','volunteer','token','note','created']
  elif kind=='leaderboards':
   rows=[dict(challenge=c['id'],rank=i,**r) for c in CHALLENGES for i,r in enumerate(leaderboard(c['id']),1)]; fields=['challenge','rank','id','nickname','best','used']
  elif kind=='audit': rows=[dict(r) for r in db().execute('SELECT * FROM audit')]; fields=['id','attempt_id','actor','action','before_json','after_json','created']
  else: abort(404)
  output=io.StringIO(); writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
  # Avoid spreadsheet formula execution when exporting user-controlled names.
  for row in rows:
   writer.writerow({k:("'"+v if isinstance(v,str) and v[:1] in ('=','+','-','@','\t','\r') else v) for k,v in row.items()})
  return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename={kind}.csv'})
 return app
