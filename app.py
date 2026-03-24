import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, simpledialog, filedialog
import tkinter as tk
import threading
import db
import isbn_lookup


class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="cosmo")
        self.title("图书出入库管理系统")
        self.geometry("1125x678")
        self.minsize(900, 500)
        db.init_db()
        self._setup_style()
        self._build_ui()
        self.scan_entry.focus_set()
        self._start_auto_backup()
        self._check_low_stock()

    def _setup_style(self):
        style = ttk.Style()
        style.configure("Treeview", rowheight=28)
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        # 斑马纹
        style.map("Treeview", background=[("selected", "#0078d7")])

    def _apply_stripe(self, tree):
        """给 Treeview 加斑马纹"""
        tree.tag_configure("odd", background="#f0f0f0")
        tree.tag_configure("even", background="white")
        for i, item in enumerate(tree.get_children()):
            tree.item(item, tags=("odd" if i % 2 else "even",))

    def _build_ui(self):
        # 顶部栏
        top = ttk.Frame(self)
        top.pack(fill=X, padx=15, pady=8)

        ttk.Label(top, text="扫码/输入ISBN：", font=("", 13)).pack(side=LEFT)
        self.scan_entry = ttk.Entry(top, font=("", 13), width=25)
        self.scan_entry.pack(side=LEFT, padx=5)
        self.scan_entry.bind("<Return>", self._on_scan)

        for text, cmd in [("设置", self._open_settings), ("备份", self._manual_backup),
                          ("导出", self._export_menu), ("图书列表", self._open_book_list),
                          ("出入库记录", self._open_logs), ("分类管理", self._open_category_mgr),
                          ("库存预警", self._open_low_stock), ("批量操作", self._open_batch),
                          ("盘点", self._open_inventory)]:
            ttk.Button(top, text=text, command=cmd, bootstyle=OUTLINE).pack(side=RIGHT, padx=2)

        # 提示
        ttk.Label(self, text="请使用扫码枪扫描图书条码，或手动输入ISBN后按回车",
                  font=("", 11), foreground="gray").pack(pady=(5, 3))

        # 最近记录
        ttk.Label(self, text="最近出入库记录", font=("", 12, "bold")).pack(anchor=W, padx=15)
        cols = ("time", "isbn", "title", "direction", "qty")
        self.recent_tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        for col, hd, w in zip(cols, ("时间", "ISBN", "书名", "类型", "数量"), (160, 140, 280, 70, 70)):
            self.recent_tree.heading(col, text=hd)
            self.recent_tree.column(col, width=w, anchor=W)
        self.recent_tree.pack(fill=BOTH, expand=True, padx=15, pady=(0, 10))
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_tree.delete(*self.recent_tree.get_children())
        for log in db.get_stock_logs(limit=20):
            self.recent_tree.insert("", END, values=(
                log["created_at"], log["isbn"], log["title"],
                "入库" if log["direction"] == "in" else "出库", log["change"]))
        self._apply_stripe(self.recent_tree)

    def _check_low_stock(self):
        low = db.get_low_stock_books()
        if low:
            names = ", ".join(f"《{b['title']}》({b['stock']})" for b in low[:5])
            extra = f" 等{len(low)}本" if len(low) > 5 else ""
            messagebox.showwarning("库存预警", f"以下图书库存不足：\n{names}{extra}")

    # ── 扫码 ──
    def _on_scan(self, event=None):
        isbn = self.scan_entry.get().strip()
        if not isbn:
            return
        self.scan_entry.delete(0, END)
        book = db.find_book_by_isbn(isbn)
        if book:
            self._open_stock_dialog(book)
        else:
            self._open_add_book(isbn, auto_lookup=True)

    # ── 出入库弹窗 ──
    def _open_stock_dialog(self, book):
        win = ttk.Toplevel(self)
        win.title("图书出入库")
        win.geometry("430x380")
        win.lift()
        win.focus_force()

        info = ttk.Labelframe(win, text="图书信息", padding=10)
        info.pack(fill=X, padx=15, pady=10)
        for i, (k, v) in enumerate([
            ("ISBN", book["isbn"]), ("书名", book["title"]), ("作者", book["author"]),
            ("出版社", book["publisher"]), ("单价", f"¥{book['price']:.2f}" if book["price"] else "未设置"),
            ("分类", book["category_name"] or "未分类"), ("当前库存", str(book["stock"])),
        ]):
            ttk.Label(info, text=f"{k}：", width=8, anchor=E).grid(row=i, column=0, sticky=E)
            ttk.Label(info, text=v, anchor=W).grid(row=i, column=1, sticky=W, padx=5)

        op = ttk.Frame(win)
        op.pack(pady=10)
        ttk.Label(op, text="数量：").grid(row=0, column=0)
        qty_var = tk.IntVar(value=1)
        ttk.Spinbox(op, from_=1, to=9999, textvariable=qty_var, width=8).grid(row=0, column=1, padx=5)

        def do_stock(direction):
            qty = qty_var.get()
            if qty <= 0:
                return messagebox.showwarning("提示", "数量必须大于0")
            if direction == "out" and qty > book["stock"]:
                return messagebox.showwarning("提示", "库存不足")
            db.update_stock(book["id"], qty, direction)
            messagebox.showinfo("成功", f"{'入库' if direction == 'in' else '出库'} {qty} 本")
            win.destroy()
            self._refresh_recent()

        ttk.Button(op, text="入库", bootstyle=SUCCESS, width=10,
                   command=lambda: do_stock("in")).grid(row=1, column=0, padx=10, pady=10)
        ttk.Button(op, text="出库", bootstyle=DANGER, width=10,
                   command=lambda: do_stock("out")).grid(row=1, column=1, padx=10, pady=10)

    # ── 新增图书 ──
    def _open_add_book(self, isbn="", auto_lookup=False):
        win = ttk.Toplevel(self)
        win.title("新增图书")
        win.geometry("440x430")
        win.lift()
        win.focus_force()

        fields = {}
        for i, (label, key) in enumerate([("ISBN", "isbn"), ("书名", "title"), ("作者", "author"), ("出版社", "publisher")]):
            ttk.Label(win, text=f"{label}：").grid(row=i, column=0, padx=10, pady=4, sticky=E)
            e = ttk.Entry(win, width=30)
            e.grid(row=i, column=1, padx=10, pady=4)
            fields[key] = e
        fields["isbn"].insert(0, isbn)

        status_label = ttk.Label(win, text="", foreground="gray")
        status_label.grid(row=0, column=2, padx=5)

        ttk.Label(win, text="单价(元)：").grid(row=4, column=0, padx=10, pady=4, sticky=E)
        price_var = tk.DoubleVar(value=0)
        ttk.Entry(win, textvariable=price_var, width=30).grid(row=4, column=1, padx=10, pady=4)

        ttk.Label(win, text="分类：").grid(row=5, column=0, padx=10, pady=4, sticky=E)
        cats = db.get_categories()
        cat_map = {c["name"]: c["id"] for c in cats}
        cat_combo = ttk.Combobox(win, values=list(cat_map.keys()), width=27, state="readonly")
        cat_combo.grid(row=5, column=1, padx=10, pady=4)

        ttk.Label(win, text="最低库存：").grid(row=6, column=0, padx=10, pady=4, sticky=E)
        min_var = tk.IntVar(value=0)
        ttk.Spinbox(win, from_=0, to=9999, textvariable=min_var, width=28).grid(row=6, column=1, padx=10, pady=4)

        ttk.Label(win, text="入库数量：").grid(row=7, column=0, padx=10, pady=4, sticky=E)
        qty_var = tk.IntVar(value=1)
        ttk.Spinbox(win, from_=1, to=9999, textvariable=qty_var, width=28).grid(row=7, column=1, padx=10, pady=4)

        def do_lookup():
            status_label.config(text="查询中...")
            def fetch():
                info = isbn_lookup.lookup(isbn)
                def update():
                    if info:
                        for key in ("title", "author", "publisher"):
                            if info.get(key) and not fields[key].get():
                                fields[key].insert(0, info[key])
                        status_label.config(text=f"已填充（{info.get('_source','')}）", foreground="green")
                    else:
                        status_label.config(text="未查到", foreground="gray")
                self.after(0, update)
            threading.Thread(target=fetch, daemon=True).start()

        if auto_lookup and isbn:
            do_lookup()

        def save():
            title = fields["title"].get().strip()
            if not fields["isbn"].get().strip() or not title:
                return messagebox.showwarning("提示", "ISBN和书名必填")
            qty = qty_var.get()
            if qty <= 0:
                return messagebox.showwarning("提示", "入库数量必须大于0")
            cat_id = cat_map.get(cat_combo.get())
            try:
                price = price_var.get()
            except Exception:
                price = 0
            try:
                db.add_book(fields["isbn"].get().strip(), title, fields["author"].get().strip(),
                            fields["publisher"].get().strip(), cat_id, price, min_var.get())
                book = db.find_book_by_isbn(fields["isbn"].get().strip())
                db.update_stock(book["id"], qty, "in")
                messagebox.showinfo("成功", f"图书已添加，入库 {qty} 本")
                win.destroy()
                self._refresh_recent()
            except Exception as ex:
                messagebox.showerror("错误", str(ex))

        ttk.Button(win, text="查询ISBN", command=do_lookup).grid(row=8, column=0, pady=12)
        ttk.Button(win, text="保存并入库", bootstyle=SUCCESS, command=save).grid(row=8, column=1, pady=12)

    # ── 分类管理 ──
    def _open_category_mgr(self):
        win = ttk.Toplevel(self)
        win.title("分类管理")
        win.geometry("350x400")
        win.lift()
        win.focus_force()

        listbox = tk.Listbox(win, font=("", 12))
        listbox.pack(fill=BOTH, expand=True, padx=10, pady=10)

        def refresh():
            listbox.delete(0, END)
            for c in db.get_categories():
                listbox.insert(END, f"{c['id']}. {c['name']}")

        bf = ttk.Frame(win)
        bf.pack(fill=X, padx=10, pady=5)

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
            if not sel: return
            cid = int(listbox.get(sel[0]).split(".")[0])
            name = simpledialog.askstring("重命名", "新名称：", parent=win)
            if name and name.strip():
                db.rename_category(cid, name.strip())
                refresh()

        def delete():
            sel = listbox.curselection()
            if not sel: return
            cid = int(listbox.get(sel[0]).split(".")[0])
            if messagebox.askyesno("确认", "确定删除该分类？"):
                db.delete_category(cid)
                refresh()

        ttk.Button(bf, text="新增", command=add).pack(side=LEFT, padx=5)
        ttk.Button(bf, text="重命名", command=rename).pack(side=LEFT, padx=5)
        ttk.Button(bf, text="删除", bootstyle=DANGER, command=delete).pack(side=LEFT, padx=5)
        refresh()

    # ── 图书列表（带搜索） ──
    def _open_book_list(self):
        win = ttk.Toplevel(self)
        win.title("图书列表")
        win.geometry("950x520")

        # 搜索栏
        sf = ttk.Frame(win)
        sf.pack(fill=X, padx=10, pady=8)
        ttk.Label(sf, text="搜索：").pack(side=LEFT)
        kw_entry = ttk.Entry(sf, width=20)
        kw_entry.pack(side=LEFT, padx=5)
        ttk.Label(sf, text="分类：").pack(side=LEFT, padx=(10, 0))
        cats = db.get_categories()
        cat_map = {"全部": None}
        cat_map.update({c["name"]: c["id"] for c in cats})
        cat_combo = ttk.Combobox(sf, values=list(cat_map.keys()), width=12, state="readonly")
        cat_combo.set("全部")
        cat_combo.pack(side=LEFT, padx=5)

        cols = ("isbn", "title", "author", "publisher", "price", "category", "stock", "min_stock")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, hd, w in zip(cols, ("ISBN", "书名", "作者", "出版社", "单价", "分类", "库存", "最低库存"),
                               (120, 170, 100, 120, 55, 80, 50, 55)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=BOTH, expand=True, padx=10)

        def refresh():
            tree.delete(*tree.get_children())
            kw = kw_entry.get().strip()
            cid = cat_map.get(cat_combo.get())
            for b in db.search_books(kw, cid):
                tree.insert("", END, iid=str(b["id"]),
                            values=(b["isbn"], b["title"], b["author"], b["publisher"],
                                    f"¥{b['price']:.2f}" if b["price"] else "",
                                    b["category_name"] or "", b["stock"], b["min_stock"]))

        ttk.Button(sf, text="搜索", bootstyle=PRIMARY, command=refresh).pack(side=LEFT, padx=5)
        kw_entry.bind("<Return>", lambda e: refresh())

        bf = ttk.Frame(win)
        bf.pack(fill=X, padx=10, pady=8)

        def get_sel():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选择一本图书", parent=win)
                return None
            return int(sel[0])

        def edit():
            bid = get_sel()
            if not bid: return
            vals = tree.item(str(bid), "values")
            self._open_edit_book(bid, vals, on_done=refresh)

        def delete():
            bid = get_sel()
            if not bid: return
            vals = tree.item(str(bid), "values")
            if messagebox.askyesno("确认", f"确定删除《{vals[1]}》？", parent=win):
                db.delete_book(bid)
                refresh()

        ttk.Button(bf, text="编辑", command=edit).pack(side=LEFT, padx=5)
        ttk.Button(bf, text="删除", bootstyle=DANGER, command=delete).pack(side=LEFT, padx=5)
        refresh()

    # ── 编辑图书 ──
    def _open_edit_book(self, book_id, vals, on_done=None):
        win = ttk.Toplevel(self)
        win.title("编辑图书")
        win.geometry("420x330")
        win.lift()
        win.focus_force()

        fields = {}
        for i, (label, key, val) in enumerate([
            ("ISBN", "isbn", vals[0]), ("书名", "title", vals[1]),
            ("作者", "author", vals[2]), ("出版社", "publisher", vals[3]),
        ]):
            ttk.Label(win, text=f"{label}：").grid(row=i, column=0, padx=10, pady=4, sticky=E)
            e = ttk.Entry(win, width=30)
            e.insert(0, val)
            e.grid(row=i, column=1, padx=10, pady=4)
            fields[key] = e
        fields["isbn"].config(state="readonly")

        ttk.Label(win, text="单价(元)：").grid(row=4, column=0, padx=10, pady=4, sticky=E)
        price_var = tk.DoubleVar(value=float(vals[4].replace("¥", "") or 0))
        ttk.Entry(win, textvariable=price_var, width=30).grid(row=4, column=1, padx=10, pady=4)

        ttk.Label(win, text="分类：").grid(row=5, column=0, padx=10, pady=4, sticky=E)
        cats = db.get_categories()
        cat_map = {c["name"]: c["id"] for c in cats}
        cat_combo = ttk.Combobox(win, values=list(cat_map.keys()), width=27, state="readonly")
        cat_combo.grid(row=5, column=1, padx=10, pady=4)
        if vals[5] in cat_map:
            cat_combo.set(vals[5])

        ttk.Label(win, text="最低库存：").grid(row=6, column=0, padx=10, pady=4, sticky=E)
        min_var = tk.IntVar(value=int(vals[7] or 0))
        ttk.Spinbox(win, from_=0, to=9999, textvariable=min_var, width=28).grid(row=6, column=1, padx=10, pady=4)

        def save():
            title = fields["title"].get().strip()
            if not title:
                return messagebox.showwarning("提示", "书名必填", parent=win)
            cat_id = cat_map.get(cat_combo.get())
            try:
                price = price_var.get()
            except Exception:
                price = 0
            db.update_book(book_id, title, fields["author"].get().strip(),
                           fields["publisher"].get().strip(), cat_id, price, min_var.get())
            messagebox.showinfo("成功", "已更新", parent=win)
            win.destroy()
            if on_done: on_done()

        ttk.Button(win, text="保存", bootstyle=SUCCESS, command=save, width=15).grid(row=7, column=0, columnspan=2, pady=12)

    # ── 出入库记录（带筛选） ──
    def _open_logs(self):
        win = ttk.Toplevel(self)
        win.title("出入库记录")
        win.geometry("800x450")

        sf = ttk.Frame(win)
        sf.pack(fill=X, padx=10, pady=8)

        ttk.Label(sf, text="开始日期：").pack(side=LEFT)
        from_entry = ttk.Entry(sf, width=12)
        from_entry.pack(side=LEFT, padx=3)
        ttk.Label(sf, text="结束日期：").pack(side=LEFT, padx=(8, 0))
        to_entry = ttk.Entry(sf, width=12)
        to_entry.pack(side=LEFT, padx=3)

        ttk.Label(sf, text="类型：").pack(side=LEFT, padx=(8, 0))
        dir_combo = ttk.Combobox(sf, values=["全部", "入库", "出库"], width=6, state="readonly")
        dir_combo.set("全部")
        dir_combo.pack(side=LEFT, padx=3)

        ttk.Label(sf, text="分类：").pack(side=LEFT, padx=(8, 0))
        cats = db.get_categories()
        cat_map = {"全部": None}
        cat_map.update({c["name"]: c["id"] for c in cats})
        cat_combo = ttk.Combobox(sf, values=list(cat_map.keys()), width=10, state="readonly")
        cat_combo.set("全部")
        cat_combo.pack(side=LEFT, padx=3)

        cols = ("time", "isbn", "title", "direction", "qty")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, hd, w in zip(cols, ("时间", "ISBN", "书名", "类型", "数量"), (170, 140, 260, 70, 70)):
            tree.heading(col, text=hd)
            tree.column(col, width=w, anchor=W)
        tree.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        def refresh():
            tree.delete(*tree.get_children())
            d = dir_combo.get()
            direction = {"入库": "in", "出库": "out"}.get(d)
            cid = cat_map.get(cat_combo.get())
            for log in db.get_stock_logs(direction=direction, date_from=from_entry.get().strip() or None,
                                          date_to=to_entry.get().strip() or None, category_id=cid, limit=500):
                tree.insert("", END, values=(
                    log["created_at"], log["isbn"], log["title"],
                    "入库" if log["direction"] == "in" else "出库", log["change"]))

        ttk.Button(sf, text="筛选", bootstyle=PRIMARY, command=refresh).pack(side=LEFT, padx=5)
        refresh()

    # ── 库存预警 ──
    def _open_low_stock(self):
        win = ttk.Toplevel(self)
        win.title("库存预警")
        win.geometry("750x400")

        cols = ("isbn", "title", "stock", "min_stock", "diff")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, hd, w in zip(cols, ("ISBN", "书名", "当前库存", "最低库存", "缺口"), (140, 250, 80, 80, 80)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=BOTH, expand=True, padx=10, pady=10)

        for b in db.get_low_stock_books():
            diff = b["min_stock"] - b["stock"]
            tree.insert("", END, values=(b["isbn"], b["title"], b["stock"], b["min_stock"], diff))

        if not tree.get_children():
            ttk.Label(win, text="所有图书库存充足", font=("", 14), foreground="green").pack(pady=20)

    # ── 批量操作 ──
    def _open_batch(self):
        win = ttk.Toplevel(self)
        win.title("批量出入库")
        win.geometry("650x480")
        win.lift()
        win.focus_force()

        ttk.Label(win, text="连续扫码添加到列表，最后统一提交", font=("", 11)).pack(pady=5)

        top = ttk.Frame(win)
        top.pack(fill=X, padx=10)
        ttk.Label(top, text="扫码/ISBN：").pack(side=LEFT)
        scan = ttk.Entry(top, width=25, font=("", 13))
        scan.pack(side=LEFT, padx=5)

        ttk.Label(top, text="数量：").pack(side=LEFT, padx=(10, 0))
        qty_var = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=9999, textvariable=qty_var, width=6).pack(side=LEFT, padx=3)

        batch_list = []  # [(isbn, title, qty)]

        cols = ("isbn", "title", "qty")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=12)
        for col, hd, w in zip(cols, ("ISBN", "书名", "数量"), (160, 300, 80)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=BOTH, expand=True, padx=10, pady=5)

        def add_item(event=None):
            isbn = scan.get().strip()
            if not isbn: return
            scan.delete(0, END)
            book = db.find_book_by_isbn(isbn)
            title = book["title"] if book else f"[未录入] {isbn}"
            qty = qty_var.get()
            batch_list.append({"isbn": isbn, "title": title, "qty": qty, "book": book})
            tree.insert("", END, values=(isbn, title, qty))
            scan.focus_set()

        scan.bind("<Return>", add_item)

        def remove_sel():
            sel = tree.selection()
            if not sel: return
            idx = tree.index(sel[0])
            tree.delete(sel[0])
            batch_list.pop(idx)

        bf = ttk.Frame(win)
        bf.pack(fill=X, padx=10, pady=8)

        ttk.Button(bf, text="移除选中", command=remove_sel).pack(side=LEFT, padx=5)

        def submit(direction):
            if not batch_list:
                return messagebox.showwarning("提示", "列表为空")
            ok, fail = 0, 0
            for item in batch_list:
                book = item["book"]
                if not book:
                    fail += 1
                    continue
                if direction == "out" and item["qty"] > book["stock"]:
                    fail += 1
                    continue
                db.update_stock(book["id"], item["qty"], direction)
                ok += 1
            msg = f"成功 {ok} 本"
            if fail:
                msg += f"，失败 {fail} 本（未录入或库存不足）"
            messagebox.showinfo("完成", msg)
            win.destroy()
            self._refresh_recent()

        ttk.Button(bf, text="全部入库", bootstyle=SUCCESS, command=lambda: submit("in")).pack(side=RIGHT, padx=5)
        ttk.Button(bf, text="全部出库", bootstyle=DANGER, command=lambda: submit("out")).pack(side=RIGHT, padx=5)
        scan.focus_set()

    # ── 盘点 ──
    def _open_inventory(self):
        win = ttk.Toplevel(self)
        win.title("库存盘点")
        win.geometry("700x500")
        win.lift()
        win.focus_force()

        ttk.Label(win, text="逐本扫码，输入实际数量，与系统库存对比", font=("", 11)).pack(pady=5)

        top = ttk.Frame(win)
        top.pack(fill=X, padx=10)
        ttk.Label(top, text="扫码/ISBN：").pack(side=LEFT)
        scan = ttk.Entry(top, width=25, font=("", 13))
        scan.pack(side=LEFT, padx=5)
        ttk.Label(top, text="实际数量：").pack(side=LEFT, padx=(10, 0))
        actual_var = tk.IntVar(value=0)
        ttk.Spinbox(top, from_=0, to=99999, textvariable=actual_var, width=6).pack(side=LEFT, padx=3)

        check_list = []

        cols = ("isbn", "title", "system", "actual", "diff")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        for col, hd, w in zip(cols, ("ISBN", "书名", "系统库存", "实际数量", "差异"), (130, 220, 80, 80, 80)):
            tree.heading(col, text=hd)
            tree.column(col, width=w)
        tree.pack(fill=BOTH, expand=True, padx=10, pady=5)

        def add_check(event=None):
            isbn = scan.get().strip()
            if not isbn: return
            scan.delete(0, END)
            book = db.find_book_by_isbn(isbn)
            if not book:
                return messagebox.showwarning("提示", f"ISBN [{isbn}] 未录入", parent=win)
            actual = actual_var.get()
            diff = actual - book["stock"]
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            check_list.append({"book": book, "actual": actual, "diff": diff})
            tree.insert("", END, values=(isbn, book["title"], book["stock"], actual, diff_str))
            actual_var.set(0)
            scan.focus_set()

        scan.bind("<Return>", add_check)

        bf = ttk.Frame(win)
        bf.pack(fill=X, padx=10, pady=8)

        def apply_diff():
            if not check_list:
                return messagebox.showwarning("提示", "列表为空")
            if not messagebox.askyesno("确认", f"将按盘点结果调整 {len(check_list)} 本图书的库存？", parent=win):
                return
            for item in check_list:
                diff = item["diff"]
                if diff == 0: continue
                direction = "in" if diff > 0 else "out"
                db.update_stock(item["book"]["id"], abs(diff), direction)
            messagebox.showinfo("完成", "库存已按盘点结果调整")
            win.destroy()
            self._refresh_recent()

        ttk.Button(bf, text="应用盘点结果（调整库存）", bootstyle=WARNING, command=apply_diff).pack(side=RIGHT, padx=5)
        scan.focus_set()

    # ── 设置 ──
    def _open_settings(self):
        win = ttk.Toplevel(self)
        win.title("设置 - ISBN 查询数据源")
        win.geometry("400x350")
        win.lift()
        win.focus_force()

        ttk.Label(win, text="调整优先级（上方优先），勾选启用", font=("", 11)).pack(padx=10, pady=8)
        cfg = isbn_lookup.load_config()
        frame = ttk.Frame(win)
        frame.pack(fill=BOTH, expand=True, padx=15)

        listbox = tk.Listbox(frame, font=("", 13), selectmode=tk.SINGLE, activestyle="none")
        listbox.pack(side=LEFT, fill=BOTH, expand=True)

        def refresh_list():
            listbox.delete(0, END)
            for item in cfg:
                p = isbn_lookup.PROVIDERS.get(item["key"], {})
                name = p.get("name", item["key"])
                prefix = "[ON] " if item["enabled"] else "[OFF]"
                listbox.insert(END, f" {prefix}  {name}")
        refresh_list()

        bf = ttk.Frame(frame)
        bf.pack(side=RIGHT, padx=5)

        def move(delta):
            sel = listbox.curselection()
            if not sel: return
            i, j = sel[0], sel[0] + delta
            if 0 <= j < len(cfg):
                cfg[i], cfg[j] = cfg[j], cfg[i]
                refresh_list()
                listbox.selection_set(j)

        def toggle():
            sel = listbox.curselection()
            if not sel: return
            i = sel[0]
            cfg[i]["enabled"] = not cfg[i]["enabled"]
            refresh_list()
            listbox.selection_set(i)

        ttk.Button(bf, text="上移", width=8, command=lambda: move(-1)).pack(pady=5)
        ttk.Button(bf, text="下移", width=8, command=lambda: move(1)).pack(pady=5)
        ttk.Button(bf, text="启用/禁用", width=8, command=toggle).pack(pady=5)

        def save():
            isbn_lookup.save_config(cfg)
            messagebox.showinfo("成功", "已保存")
            win.destroy()
        ttk.Button(win, text="保存", bootstyle=SUCCESS, command=save, width=15).pack(pady=10)

    # ── 导出 ──
    def _export_menu(self):
        win = ttk.Toplevel(self)
        win.title("导出数据")
        win.geometry("300x150")
        win.lift()
        win.focus_force()

        def export(fn, name):
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                                 initialfile=name, parent=win)
            if path:
                count = fn(path)
                messagebox.showinfo("完成", f"已导出 {count} 条")
                win.destroy()

        ttk.Button(win, text="导出图书列表", width=25, command=lambda: export(db.export_books_csv, "图书列表.csv")).pack(pady=15)
        ttk.Button(win, text="导出出入库记录", width=25, command=lambda: export(db.export_logs_csv, "出入库记录.csv")).pack(pady=5)

    # ── 备份 ──
    def _manual_backup(self):
        path = db.backup_db()
        messagebox.showinfo("备份完成", f"已备份到\n{path}")

    def _start_auto_backup(self):
        def do():
            try: db.backup_db()
            except Exception: pass
            self.after(3600000, do)
        self.after(3600000, do)


if __name__ == "__main__":
    App().mainloop()
