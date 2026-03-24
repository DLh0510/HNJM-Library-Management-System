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
            FOREIGN KEY (category_id) REFERENCES category(id)
        );
        CREATE TABLE IF NOT EXISTS stock_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            change INTEGER NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('in','out')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES book(id)
        );
    """)
    # 兼容旧数据库：如果 price 列不存在则添加
    try:
        c.execute("ALTER TABLE book ADD COLUMN price REAL DEFAULT 0")
    except Exception:
        pass
    # 索引：加速查询
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_book_isbn ON book(isbn);
        CREATE INDEX IF NOT EXISTS idx_log_created ON stock_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_log_book ON stock_log(book_id);
    """)
    conn.commit()
    conn.close()


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


def find_book_by_isbn(isbn):
    conn = get_conn()
    row = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE b.isbn=?", (isbn,)).fetchone()
    conn.close()
    return row


def add_book(isbn, title, author, publisher, category_id, price=0):
    conn = get_conn()
    conn.execute("INSERT INTO book(isbn,title,author,publisher,price,category_id,stock) VALUES(?,?,?,?,?,?,0)",
                 (isbn, title, author, publisher, price, category_id))
    conn.commit()
    conn.close()


def update_book(book_id, title, author, publisher, category_id, price=0):
    conn = get_conn()
    conn.execute("UPDATE book SET title=?, author=?, publisher=?, price=?, category_id=? WHERE id=?",
                 (title, author, publisher, price, category_id, book_id))
    conn.commit()
    conn.close()


def delete_book(book_id):
    conn = get_conn()
    conn.execute("DELETE FROM stock_log WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM book WHERE id=?", (book_id,))
    conn.commit()
    conn.close()


def update_stock(book_id, qty, direction):
    conn = get_conn()
    sign = qty if direction == "in" else -qty
    conn.execute("UPDATE book SET stock = stock + ? WHERE id=?", (sign, book_id))
    conn.execute("INSERT INTO stock_log(book_id, change, direction, created_at) VALUES(?,?,?,datetime('now','localtime'))",
                 (book_id, qty, direction))
    conn.commit()
    conn.close()


def get_all_books():
    conn = get_conn()
    rows = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title").fetchall()
    conn.close()
    return rows


def get_stock_logs(book_id=None, limit=200):
    conn = get_conn()
    if book_id:
        rows = conn.execute("SELECT l.*, b.title, b.isbn FROM stock_log l JOIN book b ON l.book_id=b.id WHERE l.book_id=? ORDER BY l.created_at DESC", (book_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, b.title, b.isbn FROM stock_log l JOIN book b ON l.book_id=b.id ORDER BY l.created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows


def export_books_csv(filepath):
    conn = get_conn()
    rows = conn.execute("SELECT b.isbn, b.title, b.author, b.publisher, b.price, COALESCE(c.name,'') as category, b.stock FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title").fetchall()
    conn.close()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ISBN", "书名", "作者", "出版社", "单价", "分类", "库存"])
        for r in rows:
            w.writerow([r["isbn"], r["title"], r["author"], r["publisher"], r["price"], r["category"], r["stock"]])
    return len(rows)


def export_logs_csv(filepath):
    conn = get_conn()
    rows = conn.execute("SELECT l.created_at, b.isbn, b.title, l.direction, l.change FROM stock_log l JOIN book b ON l.book_id=b.id ORDER BY l.created_at DESC").fetchall()
    conn.close()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["时间", "ISBN", "书名", "类型", "数量"])
        for r in rows:
            w.writerow([r["created_at"], r["isbn"], r["title"], "入库" if r["direction"] == "in" else "出库", r["change"]])
    return len(rows)


def backup_db():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"library_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    # 保留最近 10 个备份
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")])
    for old in backups[:-10]:
        os.remove(os.path.join(BACKUP_DIR, old))
    return dest
