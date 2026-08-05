import sqlite3
import time

DB_FILE = "promo_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            phone TEXT PRIMARY KEY,
            api_id INTEGER,
            api_hash TEXT,
            session_string TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS target_groups (
            username TEXT PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS dm_history (
            user_id INTEGER PRIMARY KEY,
            last_dm_time REAL,
            responded INTEGER DEFAULT 0,
            reconfirmed INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS casino_members (
            user_id INTEGER PRIMARY KEY,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_setting(key, default=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_account(phone, api_id, api_hash, session_string):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO accounts VALUES (?, ?, ?, ?)", (phone, api_id, api_hash, session_string))
    conn.commit()
    conn.close()

def get_accounts():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT phone, api_id, api_hash, session_string FROM accounts")
    rows = c.fetchall()
    conn.close()
    return rows

def remove_account(phone):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM accounts WHERE phone=?", (phone,))
    conn.commit()
    conn.close()

def add_group(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO target_groups VALUES (?)", (username.lower().replace("@", ""),))
    conn.commit()
    conn.close()

def get_groups():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM target_groups")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def remove_group(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM target_groups WHERE username=?", (username.lower().replace("@", ""),))
    conn.commit()
    conn.close()

def can_dm_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Check if user is in casino group cache
    c.execute("SELECT 1 FROM casino_members WHERE user_id=?", (user_id,))
    if c.fetchone():
        conn.close()
        return False, "casino_member"
    
    # Check 24hr rule
    c.execute("SELECT last_dm_time, responded FROM dm_history WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return True, "new"
    
    last_time, responded = row
    if responded:
        return False, "responded"
    
    if time.time() - last_time >= 86400: # 24 hours
        return True, "reconfirm"
    
    return False, "cooldown"

def record_dm(user_id, is_reconfirm=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if is_reconfirm:
        c.execute("UPDATE dm_history SET reconfirmed=1, last_dm_time=? WHERE user_id=?", (time.time(), user_id))
    else:
        c.execute("INSERT OR REPLACE INTO dm_history (user_id, last_dm_time, responded, reconfirmed) VALUES (?, ?, 0, 0)", (user_id, time.time()))
    conn.commit()
    conn.close()

def update_casino_members(member_ids):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM casino_members")
    now = time.time()
    c.executemany("INSERT OR IGNORE INTO casino_members VALUES (?, ?)", [(uid, now) for uid in member_ids])
    conn.commit()
    conn.close()
