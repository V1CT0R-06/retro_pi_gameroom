#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from app.database import backup
path=Path(sys.argv[1]) if len(sys.argv)>1 else root/'data/tournament.sqlite3'
if not path.exists():sys.exit('Base de dados inexistente.')
destination=path.parent/'backups'/('manual-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
backup(path,destination);print(destination)
