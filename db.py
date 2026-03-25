import sqlite3
import os
import csv
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "library.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isbn TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            publisher TEXT DEFAULT '',
            price REAL DEFAULT 0,
            category_id INTEGER,
            stock INTEGER DEFAULT 0,
            min_stock INTEGER DEFAULT 0,
            FOREIGN KEY (category_id) REFERENCES category(id)
        );
        CREATE TABLE IF NOT EXISTS stock_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            change INTEGER NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('in','out')),
            operator TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES book(id)
        );
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            display_name TEXT DEFAULT ''
        );
    """)
    for col, typ in [("price", "REAL DEFAULT 0"), ("min_stock", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE book ADD COLUMN {col} {typ}")
        except Exception:
            pass
    try:
        c.execute("ALTER TABLE stock_log ADD COLUMN operator TEXT DEFAULT ''")
    except Exception:
        pass
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_book_isbn ON book(isbn);
        CREATE INDEX IF NOT EXISTS idx_log_created ON stock_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_log_book ON stock_log(book_id);
    """)
    # 初始账号
    for user, pwd, name in [("admin", "123456", "管理员"), ("yu", "123456", "于老师"),
                             ("li", "123456", "李老师"), ("han", "123456", "韩老师")]:
        try:
            c.execute("INSERT INTO user(username, password, display_name) VALUES(?,?,?)", (user, pwd, name))
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── 分类 ──
def get_categories():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM category ORDER BY name").fetchall()
    conn.close()
    return rows

def add_category(name):
    conn = get_conn()
    conn.execute("INSERT INTO category(name) VALUES(?)", (name,))
    conn.commit()
    conn.close()

def delete_category(cid):
    conn = get_conn()
    conn.execute("DELETE FROM category WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def rename_category(cid, new_name):
    conn = get_conn()
    conn.execute("UPDATE category SET name=? WHERE id=?", (new_name, cid))
    conn.commit()
    conn.close()


# ── 图书 ──
def find_book_by_isbn(isbn):
    conn = get_conn()
    row = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE b.isbn=?", (isbn,)).fetchone()
    conn.close()
    return row

def add_book(isbn, title, author, publisher, category_id, price=0, min_stock=0):
    conn = get_conn()
    conn.execute("INSERT INTO book(isbn,title,author,publisher,price,category_id,stock,min_stock) VALUES(?,?,?,?,?,?,0,?)",
                 (isbn, title, author, publisher, price, category_id, min_stock))
    conn.commit()
    conn.close()

def update_book(book_id, title, author, publisher, category_id, price=0, min_stock=0):
    conn = get_conn()
    conn.execute("UPDATE book SET title=?, author=?, publisher=?, price=?, category_id=?, min_stock=? WHERE id=?",
                 (title, author, publisher, price, category_id, min_stock, book_id))
    conn.commit()
    conn.close()

def delete_book(book_id):
    conn = get_conn()
    conn.execute("DELETE FROM stock_log WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM book WHERE id=?", (book_id,))
    conn.commit()
    conn.close()

def update_stock(book_id, qty, direction, operator=""):
    conn = get_conn()
    sign = qty if direction == "in" else -qty
    conn.execute("UPDATE book SET stock = stock + ? WHERE id=?", (sign, book_id))
    conn.execute("INSERT INTO stock_log(book_id, change, direction, operator, created_at) VALUES(?,?,?,?,datetime('now','localtime'))",
                 (book_id, qty, direction, operator))
    conn.commit()
    conn.close()

def get_all_books():
    conn = get_conn()
    rows = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title").fetchall()
    conn.close()
    return rows

def search_books(keyword="", category_id=None):
    conn = get_conn()
    sql = "SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE 1=1"
    params = []
    if keyword:
        sql += " AND (b.title LIKE ? OR b.author LIKE ? OR b.isbn LIKE ?)"
        k = f"%{keyword}%"
        params += [k, k, k]
    if category_id:
        sql += " AND b.category_id=?"
        params.append(category_id)
    sql += " ORDER BY b.title"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_low_stock_books():
    conn = get_conn()
    rows = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE b.min_stock > 0 AND b.stock <= b.min_stock ORDER BY b.stock").fetchall()
    conn.close()
    return rows


# ── 出入库记录 ──
def get_stock_logs(book_id=None, limit=200, direction=None, date_from=None, date_to=None, category_id=None):
    conn = get_conn()
    sql = "SELECT l.*, b.title, b.isbn FROM stock_log l JOIN book b ON l.book_id=b.id"
    conditions, params = [], []
    if book_id:
        conditions.append("l.book_id=?")
        params.append(book_id)
    if direction:
        conditions.append("l.direction=?")
        params.append(direction)
    if date_from:
        conditions.append("l.created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("l.created_at <= ?")
        params.append(date_to + " 23:59:59")
    if category_id:
        conditions.append("b.category_id=?")
        params.append(category_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY l.created_at DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


# ── 导出 ──
def export_books_csv(filepath):
    conn = get_conn()
    rows = conn.execute("SELECT b.isbn, b.title, b.author, b.publisher, b.price, COALESCE(c.name,'') as category, b.stock, b.min_stock FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title").fetchall()
    conn.close()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ISBN", "书名", "作者", "出版社", "单价", "分类", "库存", "最低库存"])
        for r in rows:
            w.writerow([r["isbn"], r["title"], r["author"], r["publisher"], r["price"], r["category"], r["stock"], r["min_stock"]])
    return len(rows)

def export_logs_csv(filepath):
    conn = get_conn()
    rows = conn.execute("SELECT l.created_at, b.isbn, b.title, l.direction, l.change, l.operator FROM stock_log l JOIN book b ON l.book_id=b.id ORDER BY l.created_at DESC").fetchall()
    conn.close()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["时间", "ISBN", "书名", "类型", "数量", "操作员"])
        for r in rows:
            w.writerow([r["created_at"], r["isbn"], r["title"], "入库" if r["direction"] == "in" else "出库", r["change"], r["operator"]])
    return len(rows)


# ── 备份 ──
def backup_db():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"library_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")])
    for old in backups[:-10]:
        os.remove(os.path.join(BACKUP_DIR, old))
    return dest


# ── 用户 ──
def verify_user(username, password):
    conn = get_conn()
    row = conn.execute("SELECT * FROM user WHERE username=? AND password=?", (username, password)).fetchone()
    conn.close()
    return row

def change_password(username, old_pwd, new_pwd):
    conn = get_conn()
    row = conn.execute("SELECT * FROM user WHERE username=? AND password=?", (username, old_pwd)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("UPDATE user SET password=? WHERE username=?", (new_pwd, username))
    conn.commit()
    conn.close()
    return True


# ── 统计 ──
def get_stats():
    conn = get_conn()
    total_books = conn.execute("SELECT COUNT(*) FROM book").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock),0) FROM book").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_in = conn.execute("SELECT COALESCE(SUM(change),0) FROM stock_log WHERE direction='in' AND created_at >= ?", (today,)).fetchone()[0]
    today_out = conn.execute("SELECT COALESCE(SUM(change),0) FROM stock_log WHERE direction='out' AND created_at >= ?", (today,)).fetchone()[0]
    low_count = conn.execute("SELECT COUNT(*) FROM book WHERE min_stock > 0 AND stock <= min_stock").fetchone()[0]
    conn.close()
    return {"total_books": total_books, "total_stock": total_stock,
            "today_in": today_in, "today_out": today_out, "low_count": low_count}
