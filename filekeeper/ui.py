"""檔案管家（FileKeeper TW）圖形介面。

以標準庫 tkinter／ttk 打造，不需要安裝任何第三方套件。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Sequence

from .core import (
    ALL_TYPES_LABEL,
    TYPE_GROUPS,
    FileItem,
    delete_files,
    human_size,
    scan_folder,
)
from .trash import supports_system_recycle_bin

APP_TITLE = "檔案管家 FileKeeper TW"
MIN_WIDTH = 960
MIN_HEIGHT = 600

# 依序尋找可用的繁體中文字型
FONT_CANDIDATES: tuple[str, ...] = (
    "Microsoft JhengHei UI",
    "微軟正黑體",
    "Microsoft JhengHei",
    "PingFang TC",
    "Noto Sans TC",
    "Source Han Sans TC",
)

COLUMNS: tuple[str, ...] = ("名稱", "類型", "大小", "修改時間")


def _enable_high_dpi() -> None:
    """在 Windows 上啟用高 DPI 感知，避免字體模糊。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        # 高 DPI 只是畫面更好看，失敗不影響功能
        pass


class DeleteDialog(tk.Toplevel):
    """刪除前的確認視窗。

    提供「移到資源回收筒」與「永久刪除」兩種模式，永久刪除必須再勾選確認，
    避免手滑造成無法挽回的資料損失。
    """

    def __init__(self, parent: tk.Tk, items: Sequence[FileItem], *, use_recycle_bin: bool) -> None:
        super().__init__(parent)
        self.title("確認刪除")
        self.resizable(False, False)
        self.transient(parent)
        self.result: str | None = None
        self._items: list[FileItem] = list(items)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        total = sum(item.size for item in self._items)
        heading = f"即將刪除 {len(self._items)} 個檔案，共 {human_size(total)}"
        ttk.Label(body, text=heading, font=(_ui_font(), 11, "bold")).pack(anchor="w")

        preview = tk.Listbox(body, height=min(6, max(2, len(self._items))), width=64, activestyle="none")
        for item in self._items[:200]:
            preview.insert("end", f"{item.name}　（{item.size_text}）")
        preview.pack(anchor="w", pady=(8, 12))

        self.mode = tk.StringVar(value="trash" if use_recycle_bin else "permanent")
        ttk.Radiobutton(
            body,
            text="移到資源回收筒（可還原）",
            value="trash",
            variable=self.mode,
            command=self._sync_state,
            state="normal" if use_recycle_bin else "disabled",
        ).pack(anchor="w")
        ttk.Radiobutton(
            body,
            text="永久刪除（無法復原）",
            value="permanent",
            variable=self.mode,
            command=self._sync_state,
        ).pack(anchor="w", pady=(4, 0))

        self.ack = tk.BooleanVar(value=False)
        self.ack_box = ttk.Checkbutton(
            body,
            text="我了解永久刪除後無法復原",
            variable=self.ack,
            command=self._sync_state,
        )
        self.ack_box.pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(16, 0))
        self.ok_button = tk.Button(
            buttons,
            text="刪除",
            command=self._confirm,
            bg="#c0392b",
            fg="white",
            activebackground="#96281b",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=4,
            cursor="hand2",
        )
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._confirm())
        self._sync_state()
        self._center_over(parent)

    def show(self) -> str | None:
        """顯示視窗並等待使用者決定；回傳 ``"trash"``、``"permanent"`` 或 ``None``（取消）。"""
        self.grab_set()
        self.wait_window()
        return self.result

    def _center_over(self, parent: tk.Tk) -> None:
        """把視窗擺在父視窗中央偏上。"""
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _sync_state(self) -> None:
        """依目前模式決定「確認勾選框」與「刪除」按鈕是否可用。"""
        permanent = self.mode.get() == "permanent"
        self.ack_box.configure(state="normal" if permanent else "disabled")
        if not permanent:
            self.ack.set(False)
        enabled = (not permanent) or self.ack.get()
        self.ok_button.configure(
            state="normal" if enabled else "disabled",
            bg="#c0392b" if enabled else "#9aa0a6",
            cursor="hand2" if enabled else "arrow",
        )

    def _confirm(self) -> None:
        permanent = self.mode.get() == "permanent"
        if permanent and not self.ack.get():
            return
        self.result = "permanent" if permanent else "trash"
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def _ui_font() -> str:
    """取得介面可用的繁體中文字型名稱（找不到就交給 Tk 預設）。"""
    try:
        families = set(tkfont.families())
    except (tk.TclError, RuntimeError):
        return "TkDefaultFont"
    return next((name for name in FONT_CANDIDATES if name in families), "TkDefaultFont")


class FileKeeperApp:
    """主視窗：工具列、檔案清單、狀態列。"""

    _SORT_KEYS = {
        "名稱": lambda item: item.name.casefold(),
        "類型": lambda item: (item.kind_text, item.name.casefold()),
        "大小": lambda item: item.size,
        "修改時間": lambda item: item.mtime,
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.folder: Path | None = None
        self.items: list[FileItem] = []
        self._sort_column = "名稱"
        self._sort_desc = False
        self._filter_job: str | None = None
        self._status_job: str | None = None

        self.root.title(APP_TITLE)
        self.root.geometry("1120x700")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)

        self._setup_style()
        self._build()
        self._bind()
        self._set_folder(Path.home())

    # ---------------------------------------------------------------- 介面建置

    def _setup_style(self) -> None:
        """套用主題與字型設定。"""
        style = ttk.Style(self.root)
        if sys.platform.startswith("win") and "vista" in style.theme_names():
            style.theme_use("vista")

        family = _ui_font()
        self.font_family = family
        self.font_bold = (family, 10, "bold")

        for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(named).configure(family=family, size=10)
            except tk.TclError:
                continue

        style.configure("Treeview", rowheight=26, font=(family, 10))
        style.configure("Treeview.Heading", font=(family, 10, "bold"))
        style.configure("Path.TLabel", font=(family, 10, "bold"))

    def _build(self) -> None:
        """建立所有控制項。"""
        status = ttk.Frame(self.root, padding=(12, 6, 12, 8))
        status.pack(side="bottom", fill="x")
        self.status_label = ttk.Label(status, text="就緒", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.total_label = ttk.Label(status, text="", anchor="e")
        self.total_label.pack(side="right")

        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.pack(side="top", fill="both", expand=True)

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="選擇資料夾", command=self.choose_folder).pack(side="left")
        ttk.Button(toolbar, text="上一層", command=self.go_up).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="重新整理", command=self.refresh).pack(side="left", padx=(6, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(toolbar, text="搜尋檔名").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search_var, width=20).pack(side="left", padx=(6, 10))

        ttk.Label(toolbar, text="類型").pack(side="left")
        self.type_var = tk.StringVar(value=ALL_TYPES_LABEL)
        ttk.Combobox(
            toolbar,
            textvariable=self.type_var,
            state="readonly",
            width=12,
            values=[ALL_TYPES_LABEL, *TYPE_GROUPS.keys()],
        ).pack(side="left", padx=(6, 0))

        self.delete_button = tk.Button(
            toolbar,
            text="刪除選取檔案",
            command=self.delete_selected,
            bg="#c0392b",
            fg="white",
            activebackground="#96281b",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=3,
            cursor="hand2",
            font=self.font_bold,
        )
        self.delete_button.pack(side="right")

        path_bar = ttk.Frame(outer)
        path_bar.pack(fill="x", pady=(10, 4))
        self.path_label = ttk.Label(path_bar, text="", anchor="w", style="Path.TLabel")
        self.path_label.pack(side="left", fill="x", expand=True)
        self.count_label = ttk.Label(path_bar, text="", anchor="e")
        self.count_label.pack(side="right")

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True, pady=(0, 10))
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", selectmode="extended")
        widths = {"名稱": 520, "類型": 130, "大小": 110, "修改時間": 160}
        anchors = {"名稱": "w", "類型": "center", "大小": "e", "修改時間": "center"}
        for column in COLUMNS:
            self.tree.heading(column, text=column, command=lambda c=column: self.sort_by(c))
            self.tree.column(
                column,
                width=widths[column],
                anchor=anchors[column],
                stretch=(column == "名稱"),
            )
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#f6f8fa")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="開啟檔案", command=self.open_selected)
        self.menu.add_command(label="開啟所在資料夾", command=self.reveal_selected)
        self.menu.add_command(label="複製完整路徑", command=self.copy_path)
        self.menu.add_separator()
        self.menu.add_command(label="刪除選取檔案…", command=self.delete_selected)

    def _bind(self) -> None:
        """綁定事件。"""
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())
        self.tree.bind("<Button-3>", self._popup_menu)
        self.tree.bind("<Delete>", lambda _event: self.delete_selected())
        self.search_var.trace_add("write", self._on_filter_change)
        self.type_var.trace_add("write", self._on_filter_change)

    # ---------------------------------------------------------------- 資料處理

    def _set_folder(self, folder: Path) -> None:
        """切換目前管理的資料夾並重新整理清單。"""
        self.folder = Path(folder)
        self.refresh()

    def choose_folder(self) -> None:
        """跳出對話框選擇要管理的資料夾。"""
        initial = str(self.folder) if self.folder else str(Path.home())
        chosen = filedialog.askdirectory(title="選擇要管理的資料夾", initialdir=initial, mustexist=True)
        if chosen:
            self._set_folder(Path(chosen))

    def go_up(self) -> None:
        """回到上一層資料夾。"""
        if self.folder is None:
            return
        parent = self.folder.parent
        if parent == self.folder:
            self._flash("已經位在磁碟最上層")
            return
        self._set_folder(parent)

    def refresh(self) -> None:
        """依目前資料夾與篩選條件重新掃描。"""
        self._filter_job = None
        if self.folder is not None:
            self.items = scan_folder(self.folder, self.search_var.get(), self.type_var.get())
        else:
            self.items = []
        self.sort_items()
        self.render()

    def sort_items(self) -> None:
        """依目前排序設定排序清單。"""
        key = self._SORT_KEYS.get(self._sort_column)
        if key is None:
            return
        self.items.sort(key=key, reverse=self._sort_desc)

    def sort_by(self, column: str) -> None:
        """點擊欄位標題時切換排序方式。"""
        if column == self._sort_column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = column
            self._sort_desc = False
        self.sort_items()
        self.render()

    def render(self) -> None:
        """把清單內容畫到表格，並更新排序箭頭與統計。"""
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(item.name, item.kind_text, item.size_text, item.mtime_text),
                tags=("odd",) if index % 2 else (),
            )

        for column in COLUMNS:
            if column == self._sort_column:
                arrow = "▼" if self._sort_desc else "▲"
                text = f"{column} {arrow}"
            else:
                text = column
            self.tree.heading(column, text=text, command=lambda c=column: self.sort_by(c))

        self._update_counts()

    def _update_counts(self) -> None:
        """更新路徑列與狀態列的統計資訊。"""
        total = sum(item.size for item in self.items)
        self.path_label.configure(text=str(self.folder) if self.folder else "尚未選擇資料夾")
        self.count_label.configure(text=f"共 {len(self.items)} 個檔案")
        self.total_label.configure(text=f"合計 {human_size(total)}")

    # ---------------------------------------------------------------- 使用者操作

    def selected_items(self) -> list[FileItem]:
        """取得目前在表格中被選取的檔案。"""
        result: list[FileItem] = []
        for iid in self.tree.selection():
            try:
                result.append(self.items[int(iid)])
            except (ValueError, IndexError):
                continue
        return result

    def open_selected(self) -> None:
        """以系統預設程式開啟選取的檔案。"""
        items = self.selected_items()
        if items:
            self._open_path(items[0].path)

    def _open_path(self, path: Path) -> None:
        """用系統預設程式開啟單一檔案。"""
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as error:
            messagebox.showerror("無法開啟檔案", f"{path.name}\n{error}", parent=self.root)

    def reveal_selected(self) -> None:
        """在檔案總管／Finder 中顯示選取的檔案。"""
        items = self.selected_items()
        if not items:
            return
        path = items[0].path
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(f'explorer /select,"{path}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as error:
            messagebox.showerror("無法開啟資料夾", str(error), parent=self.root)

    def copy_path(self) -> None:
        """把選取檔案的完整路徑複製到剪貼簿。"""
        items = self.selected_items()
        if not items:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(str(item.path) for item in items))
        self._flash(f"已複製 {len(items)} 筆路徑")

    def delete_selected(self) -> None:
        """刪除選取的檔案（含確認流程）。"""
        items = self.selected_items()
        if not items:
            messagebox.showinfo(
                "尚未選取檔案",
                "請先在清單中選取要刪除的檔案，可按住 Ctrl 或 Shift 一次選取多個。",
                parent=self.root,
            )
            return

        dialog = DeleteDialog(self.root, items, use_recycle_bin=supports_system_recycle_bin())
        choice = dialog.show()
        if choice is None:
            return

        outcome = delete_files(items, permanent=(choice == "permanent"))
        self.refresh()
        self._flash(outcome.message)

        if outcome.has_problem:
            lines = [f"失敗：{path.name}｜{reason}" for path, reason in outcome.failed]
            lines += [f"略過：{path.name}｜{reason}" for path, reason in outcome.skipped]
            if len(lines) > 15:
                lines = lines[:15] + ["…（其餘省略）"]
            messagebox.showwarning("刪除結果", "\n".join(lines), parent=self.root)

    def handle_exception(self, exc_type, exc_value, _exc_traceback) -> None:
        """攔截介面執行時的例外，改用對話框提示。"""
        messagebox.showerror("發生錯誤", f"{exc_type.__name__}：{exc_value}", parent=self.root)

    # ---------------------------------------------------------------- 輔助

    def _on_filter_change(self, *_args) -> None:
        """搜尋或類型變動時重新掃描（延遲 250 毫秒，避免每打一個字就掃一次）。"""
        if self._filter_job is not None:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(250, self.refresh)

    def _flash(self, message: str, timeout_ms: int = 6000) -> None:
        """在狀態列短暫顯示訊息。"""
        self.status_label.configure(text=message)
        if self._status_job is not None:
            self.root.after_cancel(self._status_job)
        self._status_job = self.root.after(
            timeout_ms, lambda: self.status_label.configure(text="就緒")
        )

    def _popup_menu(self, event: tk.Event) -> None:
        """右鍵選單。"""
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        if self.tree.selection():
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()


def main() -> None:
    """程式進入點：建立主視窗並進入事件迴圈。"""
    _enable_high_dpi()
    root = tk.Tk()
    app = FileKeeperApp(root)
    root.report_callback_exception = app.handle_exception  # type: ignore[assignment]
    root.mainloop()
