import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import db
import isbn_lookup


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("图书出入库管理系统")
        self.geometry("900x600")
        self.configure(bg="#f5f5f5")
        db.init_db()
        self._build_ui()
        self.scan_entry.focus_set()
        self._start_auto_backup()

    # ── 主界面 ──
    def _build_ui(self):
        top = tk.Frame(self, bg="#f5f5f5")
        top.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(top, text="扫码/输入ISBN：", font=("", 14), bg="#f5f5f5").pack(side=tk.LEFT)
        self.scan_entry = tk.Entry(top, font=("", 14), width=30)
        self.scan_entry.pack(side=tk.LEFT, padx=5)
        self.scan_entry.bind("<Return>", self._on_scan)

        tk.Button(top, text="分类管理", command=self._open_category_mgr).pack(side=tk.RIGHT, padx=5)
        tk.Button(top, text="出入库记录", command=self._open_logs).pack(side=tk.RIGHT, padx=5)
        tk.Button(top, text="图书列表", command=self._open_book_list).pack(side=tk.RIGHT, padx=5)
        tk.Button(top, text="导出数据", command=self._export_menu).pack(side=tk.RIGHT, padx=5)
        tk.Button(top, text="备份", command=self._manual_backup).pack(side=tk.RIGHT, padx=5)
        tk.Button(top, text="设置", command=self._open_settings).pack(side=tk.RIGHT, padx=5)

        hint = tk.Label(self, text="请使用扫码枪扫描图书条码，或手动输入ISBN后按回车", font=("", 12), fg="#888", bg="#f5f5f5")
        hint.pack(pady=(10, 5))

        # 最近出入库记录
        tk.Label(self, text="最近出入库记录", font=("", 12), bg="#f5f5f5", anchor="w").pack(fill=tk.X, padx=20)
        cols = ("time", "isbn", "title", "direction", "qty")
        self.recent_tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for col, hd, w in zip(cols, ("时间", "ISBN", "书名", "类型", "数量"),
                               (150, 130, 200, 60, 60)):
            self.recent_tree.heading(col, text=hd)
            self.recent_tree.column(col, width=w)
        self.recent_tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_tree.delete(*self.recent_tree.get_children())
        for log in db.get_stock_logs(limit=20):
            self.recent_tree.insert("", tk.END, values=(
                log["created_at"], log["isbn"], log["title"],
                "入库" if log["direction"] == "in" else "出库", log["change"]))

    # ── 扫码触发 ──
    def _on_scan(self, event=None):
        isbn = self.scan_entry.get().strip()
        if not isbn:
            return
        self.scan_entry.delete(0, tk.END)
        book = db.find_book_by_isbn(isbn)
        if book:
            self._open_stock_dialog(book)
        else:
            self._open_add_book(isbn, auto_lookup=True)

    # ── 出入库弹窗 ──
    def _open_stock_dialog(self, book):
        win = tk.Toplevel(self)
        win.title("图书出入库")
        win.geometry("420x350")
        win.grab_set()

        info_frame = tk.LabelFrame(win, text="图书信息", padx=10, pady=10)
        info_frame.pack(fill=tk.X, padx=15, pady=10)

        labels = [
            ("ISBN", book["isbn"]),
            ("书名", book["title"]),
            ("作者", book["author"]),
            ("出版社", book["publisher"]),
            ("单价", f"¥{book['price']:.2f}" if book["price"] else "未设置"),
            ("分类", book["category_name"] or "未分类"),
            ("当前库存", str(book["stock"])),
        ]
        for i, (k, v) in enumerate(labels):
            tk.Label(info_frame, text=f"{k}：", anchor="e", width=8).grid(row=i, column=0, sticky="e")
            tk.Label(info_frame, text=v, anchor="w").grid(row=i, column=1, sticky="w", padx=5)

        op_frame = tk.Frame(win)
        op_frame.pack(pady=10)

        tk.Label(op_frame, text="数量：").grid(row=0, column=0)
        qty_var = tk.IntVar(value=1)
        tk.Spinbox(op_frame, from_=1, to=9999, textvariable=qty_var, width=8).grid(row=0, column=1, padx=5)

        def do_stock(direction):
            qty = qty_var.get()
            if qty <= 0:
                messagebox.showwarning("提示", "数量必须大于0")
                return
            if direction == "out" and qty > book["stock"]:
                messagebox.showwarning("提示", "库存不足")
                return
            db.update_stock(book["id"], qty, direction)
            messagebox.showinfo("成功", f"{'入库' if direction == 'in' else '出库'} {qty} 本")
            win.destroy()
            self._refresh_recent()

        tk.Button(op_frame, text="入库", width=10,
                  command=lambda: do_stock("in")).grid(row=1, column=0, padx=10, pady=10)
        tk.Button(op_frame, text="出库", width=10,
                  command=lambda: do_stock("out")).grid(row=1, column=1, padx=10, pady=10)

    # ── 新增图书 ──
    def _open_add_book(self, isbn="", auto_lookup=False):
        win = tk.Toplevel(self)
        win.title("新增图书")
        win.geometry("420x400")
        win.grab_set()

        fields = {}
        for i, (label, key) in enumerate([("ISBN", "isbn"), ("书名", "title"), ("作者", "author"), ("出版社", "publisher")]):
            tk.Label(win, text=f"{label}：").grid(row=i, column=0, padx=10, pady=5, sticky="e")
            e = tk.Entry(win, width=30)
            e.grid(row=i, column=1, padx=10, pady=5)
            fields[key] = e
        fields["isbn"].insert(0, isbn)

        status_label = tk.Label(win, text="", fg="#888")
        status_label.grid(row=0, column=2, padx=5)

        tk.Label(win, text="单价(元)：").grid(row=4, column=0, padx=10, pady=5, sticky="e")
        price_var = tk.DoubleVar(value=0)
        tk.Entry(win, textvariable=price_var, width=30).grid(row=4, column=1, padx=10, pady=5)

        tk.Label(win, text="分类：").grid(row=5, column=0, padx=10, pady=5, sticky="e")
        cats = db.get_categories()
        cat_map = {c["name"]: c["id"] for c in cats}
        cat_combo = ttk.Combobox(win, values=list(cat_map.keys()), width=27, state="readonly")
        cat_combo.grid(row=5, column=1, padx=10, pady=5)

        tk.Label(win, text="入库数量：").grid(row=6, column=0, padx=10, pady=5, sticky="e")
        qty_var = tk.IntVar(value=1)
        tk.Spinbox(win, from_=1, to=9999, textvariable=qty_var, width=28).grid(row=6, column=1, padx=10, pady=5)

        def do_lookup():
            status_label.config(text="查询中...")
            def fetch():
                info = isbn_lookup.lookup(isbn)
                def update():
                    if info:
                        for key in ("title", "author", "publisher"):
                            if info.get(key) and not fields[key].get():
                                fields[key].insert(0, info[key])
                        src = info.get("_source", "")
                        status_label.config(text=f"✅ 已填充（{src}）", fg="green")
                    else:
                        status_label.config(text="未查到，请手动填写", fg="#888")
                self.after(0, update)
            threading.Thread(target=fetch, daemon=True).start()

        if auto_lookup and isbn:
            do_lookup()

        def save():
            title = fields["title"].get().strip()
            if not fields["isbn"].get().strip() or not title:
                messagebox.showwarning("提示", "ISBN和书名必填")
                return
            qty = qty_var.get()
            if qty <= 0:
                messagebox.showwarning("提示", "入库数量必须大于0")
                return
            cat_id = cat_map.get(cat_combo.get())
            try:
                price = price_var.get()
            except Exception:
                price = 0
            try:
                db.add_book(fields["isbn"].get().strip(), title, fields["author"].get().strip(),
                            fields["publisher"].get().strip(), cat_id, price)
                book = db.find_book_by_isbn(fields["isbn"].get().strip())
                db.update_stock(book["id"], qty, "in")
                messagebox.showinfo("成功", f"图书已添加，入库 {qty} 本")
                win.destroy()
                self._refresh_recent()
            except Exception as ex:
                messagebox.showerror("错误", str(ex))

        tk.Button(win, text="查询ISBN", command=do_lookup).grid(row=7, column=0, pady=15)
        tk.Button(win, text="保存并入库", command=save, width=15).grid(row=7, column=1, pady=15)

    # ── 分类管理 ──
    def _open_category_mgr(self):
        win = tk.Toplevel(self)
        win.title("分类管理")
        win.geometry("350x400")
        win.grab_set()

        listbox = tk.Listbox(win, font=("", 12))
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def refresh():
            listbox.delete(0, tk.END)
            for c in db.get_categories():
                listbox.insert(tk.END, f"{c['id']}. {c['name']}")

        btn_frame = tk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        def add():
            name = simpledialog.askstring("新增分类", "分类名称：", parent=win)
            if name and name.strip():
                try:
                    db.add_category(name.strip())
                    refresh()
                except Exception as ex:
                    messagebox.showerror("错误", str(ex))

        def rename():
            sel = listbox.curselection()
            if not sel:
                return
            cid = int(listbox.get(sel[0]).split(".")[0])
            name = simpledialog.askstring("重命名", "新名称：", parent=win)
            if name and name.strip():
                db.rename_category(cid, name.strip())
                refresh()

        def delete():
            sel = listbox.curselection()
            if not sel:
                return
            cid = int(listbox.get(sel[0]).split(".")[0])
            if messagebox.askyesno("确认", "确定删除该分类？"):
                db.delete_category(cid)
                refresh()

        tk.Button(btn_frame, text="新增", command=add).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="重命名", command=rename).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="删除", command=delete).pack(side=tk.LEFT, padx=5)
        refresh()

    # ── 图书列表 ──
    def _open_book_list(self):
        win = tk.Toplevel(self)
        win.title("图书列表")
        win.geometry("850x480")

        cols = ("isbn", "title", "author", "publisher", "price", "category", "stock")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, hd, w in zip(cols, ("ISBN", "书名", "作者", "出版社", "单价", "分类", "库存"),
                               (130, 180, 110, 130, 60, 90, 50)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        btn_frame = tk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=8)

        def refresh():
            tree.delete(*tree.get_children())
            for b in db.get_all_books():
                tree.insert("", tk.END, iid=str(b["id"]),
                            values=(b["isbn"], b["title"], b["author"], b["publisher"],
                                    f"¥{b['price']:.2f}" if b["price"] else "",
                                    b["category_name"] or "", b["stock"]))

        def get_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选择一本图书", parent=win)
                return None
            return int(sel[0])

        def edit():
            book_id = get_selected()
            if not book_id:
                return
            vals = tree.item(str(book_id), "values")
            self._open_edit_book(book_id, vals, on_done=refresh)

        def delete():
            book_id = get_selected()
            if not book_id:
                return
            vals = tree.item(str(book_id), "values")
            if messagebox.askyesno("确认删除", f"确定删除《{vals[1]}》及其所有出入库记录？", parent=win):
                db.delete_book(book_id)
                refresh()

        tk.Button(btn_frame, text="编辑", command=edit).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="删除", command=delete).pack(side=tk.LEFT, padx=5)
        refresh()

    # ── 编辑图书 ──
    def _open_edit_book(self, book_id, vals, on_done=None):
        win = tk.Toplevel(self)
        win.title("编辑图书")
        win.geometry("400x300")
        win.grab_set()

        fields = {}
        for i, (label, key, val) in enumerate([
            ("ISBN", "isbn", vals[0]),
            ("书名", "title", vals[1]),
            ("作者", "author", vals[2]),
            ("出版社", "publisher", vals[3]),
        ]):
            tk.Label(win, text=f"{label}：").grid(row=i, column=0, padx=10, pady=5, sticky="e")
            e = tk.Entry(win, width=30)
            e.insert(0, val)
            e.grid(row=i, column=1, padx=10, pady=5)
            fields[key] = e
        fields["isbn"].config(state="readonly")

        tk.Label(win, text="单价(元)：").grid(row=4, column=0, padx=10, pady=5, sticky="e")
        price_var = tk.DoubleVar(value=float(vals[4].replace("¥", "") or 0))
        tk.Entry(win, textvariable=price_var, width=30).grid(row=4, column=1, padx=10, pady=5)

        tk.Label(win, text="分类：").grid(row=5, column=0, padx=10, pady=5, sticky="e")
        cats = db.get_categories()
        cat_map = {c["name"]: c["id"] for c in cats}
        cat_combo = ttk.Combobox(win, values=list(cat_map.keys()), width=27, state="readonly")
        cat_combo.grid(row=5, column=1, padx=10, pady=5)
        if vals[5] in cat_map:
            cat_combo.set(vals[5])

        def save():
            title = fields["title"].get().strip()
            if not title:
                messagebox.showwarning("提示", "书名必填", parent=win)
                return
            cat_id = cat_map.get(cat_combo.get())
            try:
                price = price_var.get()
            except Exception:
                price = 0
            db.update_book(book_id, title, fields["author"].get().strip(),
                           fields["publisher"].get().strip(), cat_id, price)
            messagebox.showinfo("成功", "图书信息已更新", parent=win)
            win.destroy()
            if on_done:
                on_done()

        tk.Button(win, text="保存", command=save, width=15).grid(row=5, column=0, columnspan=2, pady=15)

    # ── 出入库记录 ──
    def _open_logs(self):
        win = tk.Toplevel(self)
        win.title("出入库记录")
        win.geometry("750x400")

        cols = ("time", "isbn", "title", "direction", "qty")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, hd, w in zip(cols, ("时间", "ISBN", "书名", "类型", "数量"),
                               (160, 140, 200, 60, 60)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for log in db.get_stock_logs():
            tree.insert("", tk.END, values=(
                log["created_at"], log["isbn"], log["title"],
                "入库" if log["direction"] == "in" else "出库", log["change"]))


    # ── 设置（API 优先级） ──
    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("设置 - ISBN 查询数据源")
        win.geometry("400x350")
        win.grab_set()

        tk.Label(win, text="拖拽调整优先级（上方优先），勾选启用", font=("", 11)).pack(padx=10, pady=8)

        cfg = isbn_lookup.load_config()
        frame = tk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=15)

        listbox = tk.Listbox(frame, font=("", 13), selectmode=tk.SINGLE, activestyle="none")
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        check_vars = []

        def refresh_list():
            listbox.delete(0, tk.END)
            for item in cfg:
                p = isbn_lookup.PROVIDERS.get(item["key"], {})
                name = p.get("name", item["key"])
                prefix = "✅" if item["enabled"] else "⬜"
                listbox.insert(tk.END, f" {prefix}  {name}")

        refresh_list()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.RIGHT, padx=5)

        def move(delta):
            sel = listbox.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if 0 <= j < len(cfg):
                cfg[i], cfg[j] = cfg[j], cfg[i]
                refresh_list()
                listbox.selection_set(j)

        def toggle():
            sel = listbox.curselection()
            if not sel:
                return
            i = sel[0]
            cfg[i]["enabled"] = not cfg[i]["enabled"]
            refresh_list()
            listbox.selection_set(i)

        tk.Button(btn_frame, text="⬆ 上移", width=8, command=lambda: move(-1)).pack(pady=5)
        tk.Button(btn_frame, text="⬇ 下移", width=8, command=lambda: move(1)).pack(pady=5)
        tk.Button(btn_frame, text="启用/禁用", width=8, command=toggle).pack(pady=5)

        def save():
            isbn_lookup.save_config(cfg)
            messagebox.showinfo("保存成功", "数据源优先级已更新")
            win.destroy()

        tk.Button(win, text="保存", command=save, width=15).pack(pady=10)

    # ── 导出数据 ──
    def _export_menu(self):
        win = tk.Toplevel(self)
        win.title("导出数据")
        win.geometry("300x150")
        win.grab_set()

        def export(fn, default_name):
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                                 initialfile=default_name, parent=win)
            if path:
                count = fn(path)
                messagebox.showinfo("完成", f"已导出 {count} 条记录到\n{path}")
                win.destroy()

        tk.Button(win, text="导出图书列表", width=25,
                  command=lambda: export(db.export_books_csv, "图书列表.csv")).pack(pady=15)
        tk.Button(win, text="导出出入库记录", width=25,
                  command=lambda: export(db.export_logs_csv, "出入库记录.csv")).pack(pady=5)

    # ── 备份 ──
    def _manual_backup(self):
        path = db.backup_db()
        messagebox.showinfo("备份完成", f"已备份到\n{path}")

    def _start_auto_backup(self):
        """每小时自动备份一次"""
        def do():
            try:
                db.backup_db()
            except Exception:
                pass
            self.after(3600000, do)
        self.after(3600000, do)


if __name__ == "__main__":
    App().mainloop()
