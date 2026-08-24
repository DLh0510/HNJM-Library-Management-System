import sqlite3
import os
import sys
import csv
import shutil
from datetime import datetime

# 数据库路径：打包后放在用户本地应用数据目录，不在桌面生成数据文件
def get_data_dir():
    if getattr(sys, 'frozen', False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "河南经贸图书出入库管理系统")
        os.makedirs(path, exist_ok=True)
        return path
    return os.path.dirname(__file__)

DB_PATH = os.path.join(get_data_dir(), "library.db")
BACKUP_DIR = os.path.join(get_data_dir(), "backups")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate_legacy_data():
    """首次升级时将旧版在 EXE 同目录生成的数据移走。"""
    if not getattr(sys, 'frozen', False):
        return
    old_dir = os.path.dirname(sys.executable)
    new_dir = get_data_dir()
    if os.path.normcase(old_dir) == os.path.normcase(new_dir):
        return
    for name in ("library.db", "api_config.json", ".last_user", "backups"):
        old_path = os.path.join(old_dir, name)
        new_path = os.path.join(new_dir, name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            shutil.move(old_path, new_path)


def init_db():
    migrate_legacy_data()
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isbn TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            publisher TEXT DEFAULT '',
            price REAL DEFAULT 0,
            category_id INTEGER,
            stock INTEGER DEFAULT 0,
            min_stock INTEGER DEFAULT 0,
            volume_note TEXT DEFAULT '',
            FOREIGN KEY (category_id) REFERENCES category(id)
        );
        CREATE TABLE IF NOT EXISTS stock_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            change INTEGER NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('in','out')),
            operator TEXT DEFAULT '',
            remark TEXT DEFAULT '',
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
    # 兼容旧数据库新增列
    for col, typ in [("price", "REAL DEFAULT 0"), ("min_stock", "INTEGER DEFAULT 0"),
                     ("volume_note", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE book ADD COLUMN {col} {typ}")
        except Exception:
            pass
    for col, typ in [("operator", "TEXT DEFAULT ''"), ("remark", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE stock_log ADD COLUMN {col} {typ}")
        except Exception:
            pass
    # 移除 isbn UNIQUE 约束不影响旧表，新表已去掉
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_book_isbn ON book(isbn);
        CREATE INDEX IF NOT EXISTS idx_log_created ON stock_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_log_book ON stock_log(book_id);
    """)
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
    """按ISBN查找图书，如有多本（套装）返回第一本"""
    conn = get_conn()
    row = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE b.isbn=?", (isbn,)).fetchone()
    conn.close()
    return row

def find_books_by_isbn(isbn):
    """按ISBN查找所有图书（套装书多册）"""
    conn = get_conn()
    rows = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id WHERE b.isbn=? ORDER BY b.volume_note", (isbn,)).fetchall()
    conn.close()
    return rows

def add_book(isbn, title, author, publisher, category_id, price=0, min_stock=0, volume_note=""):
    conn = get_conn()
    cur = conn.execute("INSERT INTO book(isbn,title,author,publisher,price,category_id,stock,min_stock,volume_note) VALUES(?,?,?,?,?,?,0,?,?)",
                 (isbn, title, author, publisher, price, category_id, min_stock, volume_note))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id

def update_book(book_id, title, author, publisher, category_id, price=0, min_stock=0, volume_note=""):
    conn = get_conn()
    conn.execute("UPDATE book SET title=?, author=?, publisher=?, price=?, category_id=?, min_stock=?, volume_note=? WHERE id=?",
                 (title, author, publisher, price, category_id, min_stock, volume_note, book_id))
    conn.commit()
    conn.close()

def set_stock(book_id, new_stock, operator=""):
    """直接设置库存数量"""
    conn = get_conn()
    old = conn.execute("SELECT stock FROM book WHERE id=?", (book_id,)).fetchone()
    if old is None:
        conn.close()
        return
    diff = new_stock - old["stock"]
    if diff == 0:
        conn.close()
        return
    conn.execute("UPDATE book SET stock=? WHERE id=?", (new_stock, book_id))
    direction = "in" if diff > 0 else "out"
    conn.execute("INSERT INTO stock_log(book_id, change, direction, operator, remark, created_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                 (book_id, abs(diff), direction, operator, "库存调整"))
    conn.commit()
    conn.close()

def delete_book(book_id):
    conn = get_conn()
    conn.execute("DELETE FROM stock_log WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM book WHERE id=?", (book_id,))
    conn.commit()
    conn.close()

def delete_stock_log(log_id):
    """删除错误的出入库记录，并撤销该记录对库存的影响。"""
    conn = get_conn()
    row = conn.execute("SELECT book_id, change, direction FROM stock_log WHERE id=?", (log_id,)).fetchone()
    if not row:
        conn.close()
        return False
    delta = row["change"] if row["direction"] == "in" else -row["change"]
    conn.execute("UPDATE book SET stock = stock - ? WHERE id=?", (delta, row["book_id"]))
    conn.execute("DELETE FROM stock_log WHERE id=?", (log_id,))
    conn.commit()
    conn.close()
    return True

def update_stock(book_id, qty, direction, operator="", remark=""):
    conn = get_conn()
    sign = qty if direction == "in" else -qty
    conn.execute("UPDATE book SET stock = stock + ? WHERE id=?", (sign, book_id))
    conn.execute("INSERT INTO stock_log(book_id, change, direction, operator, remark, created_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                 (book_id, qty, direction, operator, remark))
    conn.commit()
    conn.close()

def get_all_books():
    conn = get_conn()
    rows = conn.execute("SELECT b.*, c.name as category_name FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title, b.volume_note").fetchall()
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
    sql += " ORDER BY b.title, b.volume_note"
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
    sql = "SELECT l.*, b.title, b.isbn, b.author, b.publisher, b.price FROM stock_log l JOIN book b ON l.book_id=b.id"
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
    rows = conn.execute("SELECT b.isbn, b.title, b.author, b.publisher, b.price, COALESCE(c.name,'') as category, b.stock, b.min_stock, b.volume_note FROM book b LEFT JOIN category c ON b.category_id=c.id ORDER BY b.title, b.volume_note").fetchall()
    conn.close()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ISBN", "书名", "作者", "出版社", "单价", "分类", "库存", "最低库存", "备注"])
        for r in rows:
            w.writerow([r["isbn"], r["title"], r["author"], r["publisher"],
                        f"{r['price'] or 0:.2f}", r["category"], r["stock"], r["min_stock"], r["volume_note"]])
    return len(rows)

def export_logs_csv(filepath, direction=None, date_from=None, date_to=None, category_id=None):
    logs = get_stock_logs(direction=direction, date_from=date_from, date_to=date_to, category_id=category_id, limit=None)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["时间", "ISBN", "书名", "作者", "出版社", "单价", "类型", "数量", "操作员", "系部", "老师"])
        for r in logs:
            # 拆分备注：格式为 "系部 老师"
            remark = r["remark"] or ""
            parts = remark.split(" ", 1)
            dept = parts[0] if len(parts) > 0 else ""
            teacher = parts[1] if len(parts) > 1 else ""

            w.writerow([r["created_at"], r["isbn"], r["title"], r["author"], r["publisher"],
                        f"{r['price'] or 0:.2f}",
                        "入库" if r["direction"] == "in" else "出库", r["change"], r["operator"],
                        dept, teacher])
    return len(logs)


def _number(value, cast=float, default=0):
    try:
        return cast(str(value or "").replace("¥", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def import_csv(filepath):
    """导入本系统导出的图书列表或出入库记录 CSV。"""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        rows = list(reader)

    if {"ISBN", "书名", "库存"}.issubset(headers):
        kind = "books"
    elif {"时间", "ISBN", "书名", "类型", "数量"}.issubset(headers):
        kind = "logs"
    else:
        raise ValueError("不是本系统导出的图书列表或出入库记录 CSV")

    conn = get_conn()
    added = updated = skipped = 0
    try:
        for row in rows:
            isbn, title = (row.get("ISBN") or "").strip(), (row.get("书名") or "").strip()
            if not isbn or not title:
                skipped += 1
                continue
            if kind == "books":
                note = (row.get("备注") or "").strip()
                category = (row.get("分类") or "").strip()
                category_id = None
                if category:
                    conn.execute("INSERT OR IGNORE INTO category(name) VALUES(?)", (category,))
                    category_id = conn.execute("SELECT id FROM category WHERE name=?", (category,)).fetchone()[0]
                existing = conn.execute(
                    "SELECT id FROM book WHERE isbn=? AND title=? AND volume_note=?",
                    (isbn, title, note)).fetchone()
                values = ((row.get("作者") or "").strip(), (row.get("出版社") or "").strip(),
                          _number(row.get("单价")), category_id, _number(row.get("库存"), int),
                          _number(row.get("最低库存"), int))
                if existing:
                    conn.execute("UPDATE book SET author=?,publisher=?,price=?,category_id=?,stock=?,min_stock=? WHERE id=?",
                                 values + (existing["id"],))
                    updated += 1
                else:
                    conn.execute("INSERT INTO book(isbn,title,author,publisher,price,category_id,stock,min_stock,volume_note) VALUES(?,?,?,?,?,?,?,?,?)",
                                 (isbn, title) + values + (note,))
                    added += 1
            else:
                direction = {"入库": "in", "出库": "out"}.get((row.get("类型") or "").strip())
                qty = _number(row.get("数量"), int)
                if not direction or qty <= 0:
                    skipped += 1
                    continue
                book = conn.execute("SELECT id FROM book WHERE isbn=? AND title=? ORDER BY id LIMIT 1", (isbn, title)).fetchone()
                if not book:
                    cur = conn.execute("INSERT INTO book(isbn,title,author,publisher,price,stock) VALUES(?,?,?,?,?,0)",
                                       (isbn, title, (row.get("作者") or "").strip(),
                                        (row.get("出版社") or "").strip(), _number(row.get("单价"))))
                    book_id = cur.lastrowid
                else:
                    book_id = book["id"]
                created_at = (row.get("时间") or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                remark = " ".join(filter(None, [(row.get("系部") or "").strip(), (row.get("老师") or "").strip()]))
                duplicate = conn.execute(
                    "SELECT 1 FROM stock_log WHERE book_id=? AND change=? AND direction=? AND operator=? AND remark=? AND created_at=?",
                    (book_id, qty, direction, (row.get("操作员") or "").strip(), remark, created_at)).fetchone()
                if duplicate:
                    skipped += 1
                    continue
                conn.execute("INSERT INTO stock_log(book_id,change,direction,operator,remark,created_at) VALUES(?,?,?,?,?,?)",
                             (book_id, qty, direction, (row.get("操作员") or "").strip(), remark, created_at))
                added += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return kind, added, updated, skipped


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
