"""SQLite connections and online backups. Explicit admin deletions retain an independent audit trail."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS participants (
 id INTEGER PRIMARY KEY, nickname TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
 created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL REFERENCES participants(id),
 challenge_id TEXT NOT NULL CHECK(challenge_id IN ('platformers','fighting','racing')),
 number INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','stopped','valid','failed','void')),
 centiseconds INTEGER, started REAL, boot TEXT, volunteer TEXT NOT NULL,
 token TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT '',
 created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE UNIQUE INDEX IF NOT EXISTS occupied_slot ON attempts(participant_id,challenge_id,number) WHERE status != 'void';
CREATE UNIQUE INDEX IF NOT EXISTS active_station ON attempts(challenge_id) WHERE status IN ('running','stopped');
CREATE TABLE IF NOT EXISTS id_sequences (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT INTO id_sequences(name,value) VALUES ('participants',0) ON CONFLICT(name) DO NOTHING;
INSERT INTO id_sequences(name,value) VALUES ('attempts',0) ON CONFLICT(name) DO NOTHING;
UPDATE id_sequences SET value=MAX(value,(SELECT COALESCE(MAX(id),0) FROM participants)) WHERE name='participants';
UPDATE id_sequences SET value=MAX(value,(SELECT COALESCE(MAX(id),0) FROM attempts)) WHERE name='attempts';
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, attempt_id INTEGER REFERENCES attempts(id), actor TEXT NOT NULL,
 action TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
'''
class Connection(sqlite3.Connection):
 def __exit__(self, *args):
  try: return super().__exit__(*args)
  finally: self.close()

def connect(path,managed=True):
 db=sqlite3.connect(path,timeout=15,factory=Connection if managed else sqlite3.Connection)
 db.row_factory=sqlite3.Row
 db.execute('PRAGMA foreign_keys=ON')
 db.execute('PRAGMA journal_mode=WAL')
 db.execute('PRAGMA synchronous=FULL')
 return db

def initialize(path):
 Path(path).parent.mkdir(parents=True,exist_ok=True)
 with connect(path) as db: db.executescript(SCHEMA)

def backup(path, destination):
 Path(destination).parent.mkdir(parents=True,exist_ok=True)
 source=connect(path)
 target=sqlite3.connect(destination)
 try: source.backup(target)
 finally: target.close(); source.close()


def next_id(db, name):
 """Allocate inside BEGIN IMMEDIATE; IDs are never reused after deletion/reset."""
 db.execute('UPDATE id_sequences SET value=value+1 WHERE name=?',(name,))
 return db.execute('SELECT value FROM id_sequences WHERE name=?',(name,)).fetchone()[0]
