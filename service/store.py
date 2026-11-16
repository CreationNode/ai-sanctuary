"""SQLite aggregate counters, quota buckets, and short-lived abuse records."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS keys (
                    digest TEXT PRIMARY KEY, tier TEXT NOT NULL, daily_limit INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS quota (
                    subject TEXT,bucket INTEGER,expires INTEGER,count INTEGER,
                    PRIMARY KEY(subject,bucket));
                CREATE TABLE IF NOT EXISTS totals (
                    model TEXT,day TEXT,count INTEGER,PRIMARY KEY(model,day));
                CREATE TABLE IF NOT EXISTS abuse (
                    expires INTEGER NOT NULL,model TEXT NOT NULL,prompt TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS abuse_expiry ON abuse(expires);
            """)
            db.execute("INSERT OR IGNORE INTO config VALUES ('salt', ?)", (secrets.token_hex(32),))
            self.salt = bytes.fromhex(db.execute("SELECT value FROM config WHERE key='salt'").fetchone()[0])
        if os.name == "posix":
            self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def fingerprint(self, value):
        return hmac.new(self.salt, value.encode(), hashlib.sha256).hexdigest()

    def issue(self, tier, limit):
        if tier not in ("registered", "research") or limit < 1:
            raise ValueError("Invalid key tier or quota")
        token = "sk-sanctuary-" + secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute("INSERT INTO keys VALUES (?,?,?)", (self.fingerprint(token),tier,limit))
        return token

    def identify(self, auth, ip):
        if not auth or auth == "Bearer anonymous":
            return "anonymous", "ip-" + self.fingerprint(ip), 3600, 30
        scheme, _, key = auth.partition(" ")
        if scheme.lower() != "bearer" or not key:
            raise HTTPException(401, "Use Bearer authentication")
        fingerprint = self.fingerprint(key)
        with self.connection() as db:
            row = db.execute("SELECT tier,daily_limit FROM keys WHERE digest=?", (fingerprint,)).fetchone()
        if not row:
            raise HTTPException(401, "Unknown API key")
        return row[0], "key-" + fingerprint, 86400, row[1]

    def charge(self, identity):
        tier, subject, seconds, maximum = identity
        now = int(time.time())
        bucket = now // seconds
        expires = (bucket+1)*seconds
        with self.connection() as db:
            cur = db.execute("""
                INSERT INTO quota VALUES (?,?,?,1) ON CONFLICT(subject,bucket)
                DO UPDATE SET count=count+1 WHERE count < ?
            """, (subject,bucket,expires,maximum))
            if not cur.rowcount:
                raise HTTPException(429, "Request quota exhausted", headers={"Retry-After":str(expires-now)})

    def record(self, model, tier, prompt):
        now = time.time()
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with self.connection() as db:
            db.execute("""INSERT INTO totals VALUES (?,?,1) ON CONFLICT(model,day)
                          DO UPDATE SET count=count+1""", (model,day))
            if tier != "research":
                db.execute("INSERT INTO abuse VALUES (?,?,?)", (int(now)+7*86400,model,prompt))

    def monthly(self):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.connection() as db:
            return dict(db.execute("SELECT model,sum(count) FROM totals WHERE day LIKE ? GROUP BY model",
                                   (month+"-%",)))

    def purge(self):
        now = int(time.time())
        with self.connection() as db:
            db.execute("DELETE FROM quota WHERE expires<=?",(now,))
            db.execute("DELETE FROM abuse WHERE expires<=?",(now,))
        with self.connection() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def database():
    return Store(os.environ.get("SANCTUARY_DB", "/data/sanctuary.sqlite3"))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Issue and revoke sanctuary API keys")
    parser.add_argument("action", choices=("issue","revoke","purge"))
    parser.add_argument("--tier", choices=("registered","research"), default="registered")
    parser.add_argument("--daily-limit", type=int, default=1000)
    args = parser.parse_args()
    store = database()
    if args.action == "issue":
        print(store.issue(args.tier,args.daily_limit))
    elif args.action == "revoke":
        import getpass
        with store.connection() as db:
            db.execute("DELETE FROM keys WHERE digest=?", (store.fingerprint(getpass.getpass("Key to revoke: ")),))
    else:
        store.purge()
