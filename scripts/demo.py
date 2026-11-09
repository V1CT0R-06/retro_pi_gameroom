#!/usr/bin/env python3
"""Optional demo is always isolated from the real competition."""
import secrets
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from app.database import connect,initialize
path=root/'data/demo.sqlite3'
if path.exists():sys.exit('A demonstração já existe: preservada. GLUA_DATABASE=data/demo.sqlite3 ./run-app.sh')
initialize(path)
with connect(path) as db:
 for i,name in enumerate(['Tux','Pinguim','Bit'],1):
  pid=db.execute('INSERT INTO participants(nickname,name_key) VALUES (?,?)',(name,name.casefold())).lastrowid
  for cid in ['platformers','fighting','racing']:
   db.execute("INSERT INTO attempts(participant_id,challenge_id,number,status,centiseconds,volunteer,token) VALUES (?,?,1,'valid',?,'DEMO',?)",(pid,cid,6000+i*135,secrets.token_hex(16)))
print('Demo criada. GLUA_DATABASE=data/demo.sqlite3 ./run-app.sh')
