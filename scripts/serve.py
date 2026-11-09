"""Single Waitress process; flock prevents two timer owners on one database."""
import fcntl
import os
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.app import create_app
from app.database import backup
from waitress import serve
root=Path(__file__).resolve().parent.parent
path=Path(os.environ.get('GLUA_DATABASE',str(root/'data/tournament.sqlite3'))).resolve()
path.parent.mkdir(parents=True,exist_ok=True)
lock=open(str(path)+'.lock','a')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:sys.exit('A aplicação já está a utilizar esta base de dados. Não iniciar um segundo processo.')
app=create_app({'DATABASE':str(path)})
def backup_loop():
 while True:
  try:
   folder=path.parent/'backups';backup(path,folder/(path.stem+'-'+time.strftime('%Y%m%d-%H%M')+'.sqlite3'))
   # Keep recent hourly/event snapshots; this only removes our own old backups.
   for old in sorted(folder.glob(path.stem+'-*.sqlite3'))[:-336]:old.unlink()
  except Exception as e:print('Falha no backup:',e,file=sys.stderr)
  time.sleep(300)
threading.Thread(target=backup_loop,daemon=True).start()
serve(app,host=os.environ.get('GLUA_BIND','0.0.0.0'),port=int(os.environ.get('PORT','8080')),threads=8)
