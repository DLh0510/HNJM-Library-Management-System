import csv
import os
import tempfile
import unittest

import db


class DataOperationsTest(unittest.TestCase):
    def test_import_and_delete_log_reverses_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_db, old_backups = db.DB_PATH, db.BACKUP_DIR
            db.DB_PATH, db.BACKUP_DIR = os.path.join(tmp, "library.db"), os.path.join(tmp, "backups")
            try:
                db.init_db()
                path = os.path.join(tmp, "books.csv")
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["ISBN", "书名", "作者", "出版社", "单价", "分类", "库存", "最低库存", "备注"])
                    writer.writerow(["9780000000001", "测试图书", "作者", "高等教育出版社", "12.50", "教材", "3", "1", ""])
                self.assertEqual(db.import_csv(path), ("books", 1, 0, 0))
                book = db.find_book_by_isbn("9780000000001")
                self.assertEqual(book["stock"], 3)
                db.update_stock(book["id"], 2, "in", "测试")
                log_id = db.get_stock_logs(limit=1)[0]["id"]
                self.assertTrue(db.delete_stock_log(log_id))
                self.assertEqual(db.find_book_by_isbn("9780000000001")["stock"], 3)

                logs_path = os.path.join(tmp, "logs.csv")
                with open(logs_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["时间", "ISBN", "书名", "作者", "出版社", "单价", "类型", "数量", "操作员", "系部", "老师"])
                    writer.writerow(["2026-08-24 10:00:00", "9780000000001", "测试图书", "作者", "高等教育出版社", "12.50", "出库", "1", "管理员", "教辅机构/图书馆", "张老师"])
                self.assertEqual(db.import_csv(logs_path), ("logs", 1, 0, 0))
                self.assertEqual(db.import_csv(logs_path), ("logs", 0, 0, 1))
                self.assertEqual(db.find_book_by_isbn("9780000000001")["stock"], 3)
            finally:
                db.DB_PATH, db.BACKUP_DIR = old_db, old_backups


if __name__ == "__main__":
    unittest.main()
