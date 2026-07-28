"""Desktop GUI for cfe-from-diff: pick own commits, preview objects/diff, build CFE."""

from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cfe_tools.git_staging import (
    CommitInfo,
    GitError,
    commit_parent,
    get_file_diff,
    list_changed_files,
    list_own_commits,
    map_repo_paths_to_objects,
    prepare_changes_from_git,
    strip_dump_prefix,
)
from cfe_tools.ibcmd_build import IbcmdError
from cfe_tools.inventory import build_inventory, map_path_to_object
from cfe_tools.orchestrator import RunReport, run_cfe_from_diff
from cfe_tools.vendor.cfe_borrow import CfeBorrowError
from cfe_tools.vendor.cfe_init import CfeInitError


@dataclass
class PipelineParams:
    name: str
    config: str
    git_repo: str
    dump_prefix: str
    output: str
    cfe: str
    ib_path: str
    ibcmd: str
    user: str
    password: str
    purpose: str
    prefix: str
    skip_build: bool
    dry_run: bool
    force: bool
    keep_changes: bool
    changes_dir: str
    diff_from: str
    diff_to: str


class GuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("cfe-from-diff GUI")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 680)

        self._commits: list[CommitInfo] = []
        self._changed_repo_paths: list[str] = []
        self._path_to_object: dict[str, str] = {}  # dump_rel -> borrow_spec or ""
        self._busy = False
        self._log_q: queue.Queue[str] = queue.Queue()

        self._build_vars()
        self._build_ui()
        self.root.after(100, self._drain_log)

    # ------------------------------------------------------------------ UI
    def _build_vars(self) -> None:
        self.var_name = tk.StringVar(value="K7_XXXXX")
        self.var_purpose = tk.StringVar(value="Customization")
        self.var_prefix = tk.StringVar(value="")
        self.var_config = tk.StringVar(value="")
        self.var_git_repo = tk.StringVar(value="")
        self.var_dump_prefix = tk.StringVar(value="")
        self.var_output = tk.StringVar(value="")
        self.var_cfe = tk.StringVar(value="")
        self.var_ib_path = tk.StringVar(value="")
        self.var_ibcmd = tk.StringVar(value="")
        self.var_user = tk.StringVar(value="")
        self.var_password = tk.StringVar(value="")
        self.var_changes = tk.StringVar(value="")
        self.var_diff_from = tk.StringVar(value="")
        self.var_diff_to = tk.StringVar(value="")
        self.var_skip_build = tk.BooleanVar(value=True)
        self.var_dry_run = tk.BooleanVar(value=False)
        self.var_force = tk.BooleanVar(value=True)
        self.var_keep_changes = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Готово")

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        top = ttk.Frame(outer)
        bottom = ttk.Frame(outer)
        outer.add(top, weight=3)
        outer.add(bottom, weight=2)

        # --- left: params + commits ; right: objects + diff ---
        hpaned = ttk.Panedwindow(top, orient=tk.HORIZONTAL)
        hpaned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(hpaned)
        right = ttk.Frame(hpaned)
        hpaned.add(left, weight=2)
        hpaned.add(right, weight=3)

        self._build_params(left)
        self._build_commits(left)
        self._build_objects_and_diff(right)
        self._build_actions_and_log(bottom)

    def _browse_dir(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _browse_file(self, var: tk.StringVar, save: bool = False) -> None:
        if save:
            path = filedialog.asksaveasfilename(defaultextension=".cfe", filetypes=[("CFE", "*.cfe"), ("All", "*.*")])
        else:
            path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def _add_path_row(
        self,
        parent: ttk.LabelFrame | ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        *,
        is_dir: bool = True,
        save: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=2, pady=2)
        if is_dir:
            ttk.Button(parent, text="…", width=3, command=lambda: self._browse_dir(var)).grid(row=row, column=2, padx=2)
        else:
            ttk.Button(parent, text="…", width=3, command=lambda: self._browse_file(var, save=save)).grid(
                row=row, column=2, padx=2
            )

    def _build_params(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="Параметры")
        frm.pack(fill=tk.X, padx=4, pady=4)
        frm.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(frm, text="Имя расширения").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=self.var_name).grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        r += 1

        ttk.Label(frm, text="Purpose").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Combobox(
            frm,
            textvariable=self.var_purpose,
            values=["Patch", "Customization", "AddOn"],
            state="readonly",
            width=18,
        ).grid(row=r, column=1, sticky="w", padx=2, pady=2)
        r += 1

        ttk.Label(frm, text="Prefix").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=self.var_prefix).grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        r += 1

        self._add_path_row(frm, r, "Config (база)", self.var_config)
        r += 1
        self._add_path_row(frm, r, "Git repo", self.var_git_repo)
        r += 1

        ttk.Label(frm, text="DumpPrefix").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=self.var_dump_prefix).grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2
        )
        r += 1

        self._add_path_row(frm, r, "Output", self.var_output)
        r += 1
        self._add_path_row(frm, r, "CFE", self.var_cfe, is_dir=False, save=True)
        r += 1
        self._add_path_row(frm, r, "IB path", self.var_ib_path)
        r += 1
        self._add_path_row(frm, r, "ibcmd", self.var_ibcmd, is_dir=False)
        r += 1
        self._add_path_row(frm, r, "Changes dir", self.var_changes)
        r += 1

        ttk.Label(frm, text="IB user").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=self.var_user).grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        r += 1
        ttk.Label(frm, text="IB password").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=self.var_password, show="*").grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2
        )
        r += 1

        flags = ttk.Frame(frm)
        flags.grid(row=r, column=0, columnspan=3, sticky="w", padx=2, pady=4)
        ttk.Checkbutton(flags, text="Skip build", variable=self.var_skip_build).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(flags, text="Dry-run", variable=self.var_dry_run).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(flags, text="Force", variable=self.var_force).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(flags, text="Keep changes", variable=self.var_keep_changes).pack(side=tk.LEFT, padx=4)

    def _build_commits(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="Свои коммиты (текущая ветка)")
        frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, padx=2, pady=2)
        ttk.Button(btns, text="Обновить список", command=self.refresh_commits).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Выбрать как To (коммит)", command=self.select_commit_as_to).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Показать изменения", command=self.preview_changes).pack(side=tk.LEFT, padx=2)

        range_frm = ttk.Frame(frm)
        range_frm.pack(fill=tk.X, padx=2, pady=2)
        ttk.Label(range_frm, text="From").pack(side=tk.LEFT)
        ttk.Entry(range_frm, textvariable=self.var_diff_from, width=18).pack(side=tk.LEFT, padx=4)
        ttk.Label(range_frm, text="To").pack(side=tk.LEFT)
        ttk.Entry(range_frm, textvariable=self.var_diff_to, width=18).pack(side=tk.LEFT, padx=4)

        cols = ("short", "date", "subject")
        self.commit_tree = ttk.Treeview(frm, columns=cols, show="headings", height=10, selectmode="browse")
        self.commit_tree.heading("short", text="Hash")
        self.commit_tree.heading("date", text="Дата")
        self.commit_tree.heading("subject", text="Сообщение")
        self.commit_tree.column("short", width=80, stretch=False)
        self.commit_tree.column("date", width=160, stretch=False)
        self.commit_tree.column("subject", width=360, stretch=True)
        scroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.commit_tree.yview)
        self.commit_tree.configure(yscrollcommand=scroll.set)
        self.commit_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0), pady=2)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        self.commit_tree.bind("<<TreeviewSelect>>", self._on_commit_select)
        self.commit_tree.bind("<Double-1>", lambda _e: self.select_commit_as_to())

    def _build_objects_and_diff(self, parent: ttk.Frame) -> None:
        paned = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        obj_frm = ttk.LabelFrame(paned, text="Изменённые объекты / файлы")
        diff_frm = ttk.LabelFrame(paned, text="Diff")
        paned.add(obj_frm, weight=2)
        paned.add(diff_frm, weight=3)

        cols = ("kind", "object", "path")
        self.obj_tree = ttk.Treeview(obj_frm, columns=cols, show="headings", selectmode="browse")
        self.obj_tree.heading("kind", text="Тип")
        self.obj_tree.heading("object", text="Объект")
        self.obj_tree.heading("path", text="Файл")
        self.obj_tree.column("kind", width=90, stretch=False)
        self.obj_tree.column("object", width=220, stretch=False)
        self.obj_tree.column("path", width=420, stretch=True)
        oscroll = ttk.Scrollbar(obj_frm, orient=tk.VERTICAL, command=self.obj_tree.yview)
        self.obj_tree.configure(yscrollcommand=oscroll.set)
        self.obj_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0), pady=2)
        oscroll.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        self.obj_tree.bind("<<TreeviewSelect>>", self._on_object_select)

        self.diff_text = tk.Text(diff_frm, wrap=tk.NONE, font=("Consolas", 10))
        dx = ttk.Scrollbar(diff_frm, orient=tk.HORIZONTAL, command=self.diff_text.xview)
        dy = ttk.Scrollbar(diff_frm, orient=tk.VERTICAL, command=self.diff_text.yview)
        self.diff_text.configure(xscrollcommand=dx.set, yscrollcommand=dy.set)
        self.diff_text.grid(row=0, column=0, sticky="nsew")
        dy.grid(row=0, column=1, sticky="ns")
        dx.grid(row=1, column=0, sticky="ew")
        diff_frm.rowconfigure(0, weight=1)
        diff_frm.columnconfigure(0, weight=1)

        self.diff_text.tag_configure("add", foreground="#007700")
        self.diff_text.tag_configure("del", foreground="#aa0000")
        self.diff_text.tag_configure("hunk", foreground="#0000aa")
        self.diff_text.tag_configure("meta", foreground="#666666")

    def _build_actions_and_log(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(bar, text="Запустить пайплайн", command=self.run_pipeline).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Только dry-run", command=self.run_dry_run).pack(side=tk.LEFT, padx=2)
        ttk.Label(bar, textvariable=self.var_status).pack(side=tk.RIGHT, padx=8)

        log_frm = ttk.LabelFrame(parent, text="Лог")
        log_frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.log_text = tk.Text(log_frm, height=10, wrap=tk.WORD, font=("Consolas", 9))
        lscroll = ttk.Scrollbar(log_frm, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lscroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lscroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        self._log_q.put(msg)

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self._log_q.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        if status is not None:
            self.var_status.set(status)

    def _run_bg(self, work: Callable[[], None], status: str = "Выполняется…") -> None:
        if self._busy:
            messagebox.showinfo("Занято", "Дождитесь завершения текущей операции.")
            return

        def runner() -> None:
            self.root.after(0, lambda: self._set_busy(True, status))
            try:
                work()
            except Exception as exc:  # noqa: BLE001 — show in UI
                self.log(f"[ERROR] {exc}")
                err = str(exc)

                def show_error(msg: str = err) -> None:
                    messagebox.showerror("Ошибка", msg)

                self.root.after(0, show_error)
            finally:
                self.root.after(0, lambda: self._set_busy(False, "Готово"))

        threading.Thread(target=runner, daemon=True).start()

    def _collect_params(self) -> PipelineParams:
        return PipelineParams(
            name=self.var_name.get().strip(),
            config=self.var_config.get().strip(),
            git_repo=self.var_git_repo.get().strip(),
            dump_prefix=self.var_dump_prefix.get().strip(),
            output=self.var_output.get().strip(),
            cfe=self.var_cfe.get().strip(),
            ib_path=self.var_ib_path.get().strip(),
            ibcmd=self.var_ibcmd.get().strip(),
            user=self.var_user.get().strip(),
            password=self.var_password.get(),
            purpose=self.var_purpose.get().strip() or "Customization",
            prefix=self.var_prefix.get().strip(),
            skip_build=bool(self.var_skip_build.get()),
            dry_run=bool(self.var_dry_run.get()),
            force=bool(self.var_force.get()),
            keep_changes=bool(self.var_keep_changes.get()),
            changes_dir=self.var_changes.get().strip(),
            diff_from=self.var_diff_from.get().strip(),
            diff_to=self.var_diff_to.get().strip(),
        )

    def _validate_preview(self, p: PipelineParams) -> None:
        if not p.git_repo:
            raise GitError("Укажите Git repo")
        if not p.diff_from or not p.diff_to:
            raise GitError("Укажите Diff From и Diff To (или выберите коммит)")

    def _validate_run(self, p: PipelineParams) -> None:
        self._validate_preview(p)
        if not p.name:
            raise ValueError("Укажите имя расширения")
        if not p.config or not Path(p.config).is_dir():
            raise ValueError(f"Config не найден: {p.config}")
        if not p.output:
            raise ValueError("Укажите Output")
        if not p.skip_build:
            if not p.cfe:
                raise ValueError("Укажите путь CFE или включите Skip build")
            if not p.ib_path:
                raise ValueError("Укажите IB path или включите Skip build")

    # ------------------------------------------------------------------ commits / preview
    def refresh_commits(self) -> None:
        def work() -> None:
            repo = self.var_git_repo.get().strip()
            if not repo:
                raise GitError("Укажите Git repo")
            self.log(f"Загрузка своих коммитов из {repo}…")
            commits = list_own_commits(repo, max_count=150)
            self._commits = commits
            self.root.after(0, lambda: self._fill_commits(commits))
            self.log(f"Найдено коммитов: {len(commits)}")

        self._run_bg(work, "Загрузка коммитов…")

    def _fill_commits(self, commits: list[CommitInfo]) -> None:
        self.commit_tree.delete(*self.commit_tree.get_children())
        for c in commits:
            self.commit_tree.insert(
                "",
                tk.END,
                iid=c.hash,
                values=(c.short_hash, c.author_date[:19], c.subject),
            )

    def _selected_commit(self) -> CommitInfo | None:
        sel = self.commit_tree.selection()
        if not sel:
            return None
        h = sel[0]
        for c in self._commits:
            if c.hash == h:
                return c
        return None

    def _on_commit_select(self, _event: object | None = None) -> None:
        # optional: show hint in status
        c = self._selected_commit()
        if c:
            self.var_status.set(f"Выбран: {c.short_hash} — {c.subject}")

    def select_commit_as_to(self) -> None:
        c = self._selected_commit()
        if not c:
            messagebox.showinfo("Коммит", "Выберите коммит в списке")
            return

        def work() -> None:
            repo = self.var_git_repo.get().strip()
            parent = commit_parent(repo, c.hash)
            self.root.after(0, lambda: self.var_diff_to.set(c.hash))
            self.root.after(0, lambda: self.var_diff_from.set(parent))
            self.log(f"Диапазон: {parent[:10]}..{c.short_hash} — {c.subject}")
            # auto preview
            self.root.after(0, self.preview_changes)

        self._run_bg(work, "Выбор коммита…")

    def preview_changes(self) -> None:
        def work() -> None:
            p = self._collect_params()
            self._validate_preview(p)
            self.log(f"git diff {p.diff_from}..{p.diff_to}")
            files = list_changed_files(
                p.git_repo,
                p.diff_from,
                p.diff_to,
                dump_prefix=p.dump_prefix or None,
            )
            self._changed_repo_paths = files
            objects, unmapped = map_repo_paths_to_objects(files, dump_prefix=p.dump_prefix or None)
            self.log(f"Изменённых файлов: {len(files)}; объектов: {len(objects)}")
            for u in unmapped[:20]:
                self.log(f"[WARN] Не сопоставлен с метаданными: {u}")
            if len(unmapped) > 20:
                self.log(f"[WARN] …и ещё {len(unmapped) - 20}")

            rows: list[tuple[str, str, str, str]] = []
            # object-level unique first
            seen_obj: set[str] = set()
            for f in files:
                dump_rel = strip_dump_prefix(f, p.dump_prefix or None)
                ref = map_path_to_object(dump_rel)
                obj = ref.borrow_spec if ref else ""
                kind = "file"
                if dump_rel.lower().endswith(".bsl"):
                    kind = "BSL"
                elif "/forms/" in dump_rel.lower() or "\\forms\\" in dump_rel.lower():
                    kind = "Form"
                elif dump_rel.lower().endswith(".xml"):
                    kind = "XML"
                if obj and obj not in seen_obj:
                    seen_obj.add(obj)
                rows.append((kind, obj, dump_rel, f))

            self.root.after(0, lambda: self._fill_objects(rows))

        self._run_bg(work, "Анализ изменений…")

    def _fill_objects(self, rows: list[tuple[str, str, str, str]]) -> None:
        self.obj_tree.delete(*self.obj_tree.get_children())
        self._path_to_object.clear()
        for i, (kind, obj, dump_rel, repo_path) in enumerate(rows):
            iid = f"f{i}"
            self.obj_tree.insert("", tk.END, iid=iid, values=(kind, obj, dump_rel), tags=(repo_path,))
            self._path_to_object[iid] = repo_path

    def _on_object_select(self, _event: object | None = None) -> None:
        sel = self.obj_tree.selection()
        if not sel:
            return
        iid = sel[0]
        repo_path = self._path_to_object.get(iid)
        if not repo_path:
            return

        def work() -> None:
            p = self._collect_params()
            if not p.diff_from or not p.diff_to or not p.git_repo:
                return
            text = get_file_diff(p.git_repo, p.diff_from, p.diff_to, repo_path)
            if not text.strip():
                text = f"(нет текстового diff для {repo_path})\n"
            self.root.after(0, lambda: self._show_diff(text))

        self._run_bg(work, "Загрузка diff…")

    def _show_diff(self, text: str) -> None:
        self.diff_text.delete("1.0", tk.END)
        for line in text.splitlines(keepends=True):
            tag: tuple[str, ...] = ()
            if (
                line.startswith("+++")
                or line.startswith("---")
                or line.startswith("diff ")
                or line.startswith("index ")
            ):
                tag = ("meta",)
            elif line.startswith("@@"):
                tag = ("hunk",)
            elif line.startswith("+"):
                tag = ("add",)
            elif line.startswith("-"):
                tag = ("del",)
            self.diff_text.insert(tk.END, line, tag)

    # ------------------------------------------------------------------ pipeline
    def run_dry_run(self) -> None:
        self.var_dry_run.set(True)
        self.run_pipeline()

    def run_pipeline(self) -> None:
        def work() -> None:
            p = self._collect_params()
            self._validate_run(p)
            self.log("=== Подготовка staging из git ===")
            staging_arg = p.changes_dir or None
            use_temp = not staging_arg
            result = prepare_changes_from_git(
                p.git_repo,
                p.diff_from,
                p.diff_to,
                dump_prefix=p.dump_prefix or None,
                staging_dir=staging_arg,
            )
            for w in result.warnings:
                self.log(f"[WARN] {w}")
            self.log(f"Staging: {result.staging_dir} ({result.exported} файлов)")

            # Enrich object list via inventory if config available
            try:
                inv = build_inventory(p.config, result.staging_dir)
                self.log(
                    f"Inventory: changed={len(inv.changed_files)} "
                    f"borrow={len(inv.borrow_objects)} new={len(inv.new_objects)} "
                    f"bsl={len(inv.bsl_files)}"
                )
                for w in inv.warnings:
                    self.log(f"[WARN] {w}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"[WARN] inventory preview failed: {exc}")

            self.log("=== Запуск cfe-from-diff ===")
            try:
                report = run_cfe_from_diff(
                    name=p.name,
                    config=p.config,
                    changes=result.staging_dir,
                    output=p.output,
                    cfe=p.cfe or None,
                    ib_path=p.ib_path or None,
                    ibcmd=p.ibcmd or None,
                    user=p.user or None,
                    password=p.password if p.password else None,
                    purpose=p.purpose,
                    prefix=p.prefix or None,
                    skip_build=p.skip_build,
                    dry_run=p.dry_run,
                    force_output=p.force,
                )
            except (CfeInitError, CfeBorrowError, IbcmdError, FileNotFoundError, ValueError) as exc:
                self.log(f"[ERROR] {exc}")
                raise
            finally:
                if use_temp and not p.keep_changes:
                    shutil.rmtree(result.staging_dir, ignore_errors=True)
                    self.log("Временный staging удалён")
                elif use_temp and p.keep_changes:
                    self.log(f"Staging сохранён: {result.staging_dir}")

            self._log_report(report)
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Готово",
                    f"Borrowed: {len(report.borrowed)}\n"
                    f"New: {len(report.new_objects)}\n"
                    f"BSL: {len(report.bsl_files)}\n"
                    f"Built: {report.built}\n"
                    f"Validate errors: {report.validate_errors}",
                ),
            )

        self._run_bg(work, "Пайплайн…")

    def _log_report(self, report: RunReport) -> None:
        self.log("=== cfe-from-diff summary ===")
        self.log(f"  Output:   {report.output}")
        self.log(f"  Borrowed: {len(report.borrowed)}")
        for b in report.borrowed:
            self.log(f"    - {b}")
        self.log(f"  New:      {len(report.new_objects)}")
        for n in report.new_objects:
            self.log(f"    - {n}")
        self.log(f"  BSL:      {len(report.bsl_files)}")
        for b in report.bsl_files:
            self.log(f"    - {b}")
        self.log(f"  Built:    {report.built}")
        if report.cfe:
            self.log(f"  CFE:      {report.cfe}")
        for w in report.warnings:
            self.log(f"  [WARN] {w}")


def main() -> int:
    root = tk.Tk()
    # Prefer native theme on Windows
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except tk.TclError:
        pass
    GuiApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
