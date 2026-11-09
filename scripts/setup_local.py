import json
import os
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
root=Path(__file__).resolve().parent.parent
path=root/'.local.json'
if not path.exists():
 volunteer=secrets.token_hex(3);admin=secrets.token_hex(4)
 values=dict(secret=secrets.token_hex(32),volunteer_hash=generate_password_hash(volunteer),admin_hash=generate_password_hash(admin),volunteer_pin=volunteer,admin_pin=admin)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(values,f,indent=2)
 print('PINs gerados em .local.json (permissões 600, ignorado pelo Git).')
else:
 os.chmod(path,0o600)
 print('Configuração local existente preservada.')
