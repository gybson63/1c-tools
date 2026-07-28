"""Desktop GUI for cfe-from-diff: pick own commits, preview objects/diff, build CFE."""

from __future__ import annotations

import contextlib
import queue
import shutil
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from cfe_tools.git_staging import (
    CommitInfo,
    GitError,
    get_file_diff,
    list_changed_files,
    list_own_commits,
    map_repo_paths_to_objects,
    prepare_pair_from_git,
    range_for_commit,
    strip_dump_prefix,
)
from cfe_tools.gui_settings import (
    PERSIST_BOOLS,
    PERSIST_STRINGS,
    load_settings,
    save_settings,
    settings_path,
)
from cfe_tools.gui_tooltip import tip
from cfe_tools.ibcmd_build import IbcmdError
from cfe_tools.inventory import build_inventory, map_path_to_object
from cfe_tools.orchestrator import RunReport, run_cfe_from_diff
from cfe_tools.vendor.cfe_borrow import CfeBorrowError
from cfe_tools.vendor.cfe_init import CfeInitError

# Подписи назначения расширения → значения API ibcmd / ConfigurationExtensionPurpose
PURPOSE_UI_TO_API = {
    "Исправление": "Patch",
    "Адаптация": "Customization",
    "Дополнение": "AddOn",
}
PURPOSE_API_TO_UI = {v: k for k, v in PURPOSE_UI_TO_API.items()}


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
        self.root.title("Сборка расширения из git-диффа")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 680)

        self._commits: list[CommitInfo] = []
        self._changed_repo_paths: list[str] = []
        self._path_to_object: dict[str, str] = {}  # dump_rel -> borrow_spec or ""
        self._busy = False
        self._log_q: queue.Queue[str] = queue.Queue()
        self._save_after_id: str | None = None
        self._loading_settings = False

        self._build_vars()
        self._settings_loaded = bool(load_settings())
        self._load_persisted_settings()
        self._build_ui()
        self._attach_settings_traces()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_log)
        if self._settings_loaded:
            self.log(f"Загружены настройки: {settings_path()}")
        # Re-apply visibility after settings load
        self._toggle_build_section()

    # ------------------------------------------------------------------ UI
    def _build_vars(self) -> None:
        self.var_name = tk.StringVar(value="K7_XXXXX")
        self.var_purpose = tk.StringVar(value="Адаптация")
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
        self.var_commit_id = tk.StringVar(value="")
        self.var_skip_build = tk.BooleanVar(value=True)
        self.var_dry_run = tk.BooleanVar(value=False)
        self.var_force = tk.BooleanVar(value=False)
        self.var_keep_changes = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Готово")

        self._string_vars: dict[str, tk.StringVar] = {
            "name": self.var_name,
            "purpose": self.var_purpose,
            "prefix": self.var_prefix,
            "git_repo": self.var_git_repo,
            "dump_prefix": self.var_dump_prefix,
            "output": self.var_output,
            "cfe": self.var_cfe,
            "ib_path": self.var_ib_path,
            "ibcmd": self.var_ibcmd,
            "user": self.var_user,
            "commit_id": self.var_commit_id,
        }
        self._bool_vars: dict[str, tk.BooleanVar] = {
            "skip_build": self.var_skip_build,
            "force": self.var_force,
        }

    def _load_persisted_settings(self) -> None:
        data = load_settings()
        if not data:
            return
        self._loading_settings = True
        try:
            for key in PERSIST_STRINGS:
                if key in data and key in self._string_vars and isinstance(data[key], str):
                    value = data[key]
                    if key == "purpose":
                        value = PURPOSE_API_TO_UI.get(value, value)
                        if value not in PURPOSE_UI_TO_API:
                            value = "Адаптация"
                    self._string_vars[key].set(value)
            for key in PERSIST_BOOLS:
                if key in data and key in self._bool_vars and isinstance(data[key], bool):
                    self._bool_vars[key].set(data[key])
            geom = data.get("geometry")
            if isinstance(geom, str) and geom.strip():
                with contextlib.suppress(tk.TclError):
                    self.root.geometry(geom)
        finally:
            self._loading_settings = False

    def _collect_settings_dict(self) -> dict:
        data: dict = {key: var.get() for key, var in self._string_vars.items()}
        # В файл пишем API-значение назначения, чтобы не ломать совместимость
        data["purpose"] = PURPOSE_UI_TO_API.get(
            self.var_purpose.get().strip(),
            "Customization",
        )
        data.update({key: bool(var.get()) for key, var in self._bool_vars.items()})
        with contextlib.suppress(tk.TclError):
            data["geometry"] = self.root.geometry()
        return data

    def _save_persisted_settings(self) -> None:
        if self._loading_settings:
            return
        with contextlib.suppress(OSError):
            path = save_settings(self._collect_settings_dict())
            self.var_status.set(f"Настройки сохранены ({path.name})")

    def _schedule_save_settings(self, *_args: object) -> None:
        if self._loading_settings:
            return
        if self._save_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(600, self._save_persisted_settings)

    def _attach_settings_traces(self) -> None:
        for string_var in self._string_vars.values():
            string_var.trace_add("write", self._schedule_save_settings)
        for bool_var in self._bool_vars.values():
            bool_var.trace_add("write", self._schedule_save_settings)

    def _on_close(self) -> None:
        if self._save_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._save_after_id)
        self._save_persisted_settings()
        self.root.destroy()

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
            path = filedialog.asksaveasfilename(
                defaultextension=".cfe",
                filetypes=[("Файл расширения", "*.cfe"), ("Все файлы", "*.*")],
            )
        else:
            path = filedialog.askopenfilename(filetypes=[("Все файлы", "*.*"), ("Программы", "*.exe")])
        if path:
            var.set(path)

    def _add_path_row(
        self,
        parent: ttk.LabelFrame | ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        *,
        hint: str,
        is_dir: bool = True,
        save: bool = False,
    ) -> None:
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, hint)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=2, pady=2)
        tip(entry, hint)
        if is_dir:
            btn = ttk.Button(parent, text="…", width=3, command=lambda: self._browse_dir(var))
            tip(btn, "Выбрать каталог")
        else:
            btn = ttk.Button(parent, text="…", width=3, command=lambda: self._browse_file(var, save=save))
            tip(btn, "Выбрать файл" if not save else "Указать файл для сохранения")
        btn.grid(row=row, column=2, padx=2)

    def _build_params(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="Параметры")
        frm.pack(fill=tk.X, padx=4, pady=4)
        frm.columnconfigure(1, weight=1)
        tip(frm, "Основные параметры сборки расширения из изменений git")

        r = 0
        lbl = ttk.Label(frm, text="Имя расширения")
        lbl.grid(row=r, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, "Имя расширения конфигурации 1С (например K7_20486)")
        ent = ttk.Entry(frm, textvariable=self.var_name)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "Имя расширения конфигурации 1С (например K7_20486)")
        r += 1

        lbl = ttk.Label(frm, text="Назначение")
        lbl.grid(row=r, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, "Назначение расширения: исправление, адаптация или дополнение")
        cmb = ttk.Combobox(
            frm,
            textvariable=self.var_purpose,
            values=list(PURPOSE_UI_TO_API.keys()),
            state="readonly",
            width=18,
        )
        cmb.grid(row=r, column=1, sticky="w", padx=2, pady=2)
        tip(cmb, "Исправление — точечные правки; Адаптация — доработка типовой; Дополнение — новые возможности")
        r += 1

        lbl = ttk.Label(frm, text="Префикс имён")
        lbl.grid(row=r, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, "NamePrefix расширения. Пусто — будет «<имя>_»")
        ent = ttk.Entry(frm, textvariable=self.var_prefix)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "NamePrefix расширения. Пусто — будет «<имя>_»")
        r += 1

        self._add_path_row(
            frm,
            r,
            "Репозиторий git",
            self.var_git_repo,
            hint="Каталог git-репозитория с hierarchical XML-выгрузкой конфигурации",
        )
        r += 1

        lbl = ttk.Label(frm, text="Префикс выгрузки")
        lbl.grid(row=r, column=0, sticky="w", padx=2, pady=2)
        tip(
            lbl,
            "Подкаталог выгрузки CF внутри репозитория (например src/cf/). Пусто — выгрузка в корне репозитория",
        )
        ent = ttk.Entry(frm, textvariable=self.var_dump_prefix)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(
            ent,
            "Подкаталог выгрузки CF внутри репозитория (например src/cf/). Пусто — выгрузка в корне репозитория",
        )
        r += 1

        self._add_path_row(
            frm,
            r,
            "Каталог результата",
            self.var_output,
            hint="Куда записать XML-исходники расширения",
        )
        r += 1

        flags = ttk.Frame(frm)
        flags.grid(row=r, column=0, columnspan=3, sticky="w", padx=2, pady=4)
        chk_xml = ttk.Checkbutton(
            flags,
            text="Только XML (без .cfe)",
            variable=self.var_skip_build,
            command=self._toggle_build_section,
        )
        chk_xml.pack(side=tk.LEFT, padx=4)
        tip(chk_xml, "Не вызывать ibcmd: сформировать только XML расширения")
        chk_force = ttk.Checkbutton(
            flags,
            text="Перезаписать результат",
            variable=self.var_force,
        )
        chk_force.pack(side=tk.LEFT, padx=4)
        tip(chk_force, "Удалить существующий каталог результата, если в нём уже есть Configuration.xml")
        r += 1

        self._build_frm = ttk.LabelFrame(frm, text="Сборка файла .cfe")
        self._build_frm.grid(row=r, column=0, columnspan=3, sticky="ew", padx=2, pady=6)
        self._build_frm.columnconfigure(1, weight=1)
        tip(self._build_frm, "Параметры сборки двоичного .cfe через ibcmd (нужна файловая ИБ)")
        br = 0
        self._add_path_row(
            self._build_frm,
            br,
            "Файл .cfe",
            self.var_cfe,
            hint="Путь выходного файла расширения .cfe",
            is_dir=False,
            save=True,
        )
        br += 1
        self._add_path_row(
            self._build_frm,
            br,
            "Каталог ИБ",
            self.var_ib_path,
            hint="Файловая информационная база, в которой уже загружена базовая конфигурация",
        )
        br += 1
        self._add_path_row(
            self._build_frm,
            br,
            "Путь к ibcmd",
            self.var_ibcmd,
            hint="ibcmd.exe платформы 1С. Пусто — поиск в PATH и Program Files\\1cv8",
            is_dir=False,
        )
        br += 1
        lbl = ttk.Label(self._build_frm, text="Пользователь ИБ")
        lbl.grid(row=br, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, "Имя пользователя информационной базы (если требуется)")
        ent = ttk.Entry(self._build_frm, textvariable=self.var_user)
        ent.grid(row=br, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "Имя пользователя информационной базы (если требуется)")
        br += 1
        lbl = ttk.Label(self._build_frm, text="Пароль ИБ")
        lbl.grid(row=br, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, "Пароль пользователя ИБ. Не сохраняется в настройках")
        ent = ttk.Entry(self._build_frm, textvariable=self.var_password, show="*")
        ent.grid(row=br, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "Пароль пользователя ИБ. Не сохраняется в настройках")

        self._toggle_build_section()

    def _toggle_build_section(self) -> None:
        if self.var_skip_build.get():
            self._build_frm.grid_remove()
        else:
            self._build_frm.grid()

    def _build_commits(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="Коммиты")
        frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tip(frm, "Выбор коммита или диапазона изменений для расширения")

        id_frm = ttk.Frame(frm)
        id_frm.pack(fill=tk.X, padx=2, pady=2)
        lbl = ttk.Label(id_frm, text="Идентификатор коммита")
        lbl.pack(side=tk.LEFT)
        tip(lbl, "Полный или короткий hash коммита. «Применить» выставит «С» = родитель, «По» = коммит")
        id_entry = ttk.Entry(id_frm, textvariable=self.var_commit_id, width=28)
        id_entry.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        tip(id_entry, "Полный или короткий hash коммита. Enter — то же, что «Применить»")
        btn_apply = ttk.Button(id_frm, text="Применить", command=self.apply_commit_id)
        btn_apply.pack(side=tk.LEFT, padx=2)
        tip(btn_apply, "Разобрать идентификатор: «По» = коммит, «С» = его родитель, показать изменения")
        id_entry.bind("<Return>", lambda _e: self.apply_commit_id())

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, padx=2, pady=2)
        btn_ref = ttk.Button(btns, text="Обновить список", command=self.refresh_commits)
        btn_ref.pack(side=tk.LEFT, padx=2)
        tip(btn_ref, "Загрузить свои коммиты текущей ветки (автор = git user.name / user.email)")
        btn_sel = ttk.Button(btns, text="Выбрать из списка", command=self.select_commit_as_to)
        btn_sel.pack(side=tk.LEFT, padx=2)
        tip(btn_sel, "Взять выделенный в списке коммит как «По» (родитель — как «С»)")
        btn_prev = ttk.Button(btns, text="Показать изменения", command=self.preview_changes)
        btn_prev.pack(side=tk.LEFT, padx=2)
        tip(btn_prev, "Показать изменённые объекты и файлы для диапазона «С»…«По»")

        range_frm = ttk.Frame(frm)
        range_frm.pack(fill=tk.X, padx=2, pady=2)
        lbl = ttk.Label(range_frm, text="С")
        lbl.pack(side=tk.LEFT)
        tip(lbl, "Начало диапазона (состояние «до», обычно родитель коммита)")
        ent_from = ttk.Entry(range_frm, textvariable=self.var_diff_from, width=18)
        ent_from.pack(side=tk.LEFT, padx=4)
        tip(ent_from, "Ревизия «до»: база для сравнения и выгрузки конфигурации")
        lbl = ttk.Label(range_frm, text="По")
        lbl.pack(side=tk.LEFT)
        tip(lbl, "Конец диапазона (состояние «после», обычно выбранный коммит)")
        ent_to = ttk.Entry(range_frm, textvariable=self.var_diff_to, width=18)
        ent_to.pack(side=tk.LEFT, padx=4)
        tip(ent_to, "Ревизия «после»: из неё берутся изменённые файлы для расширения")

        cols = ("short", "date", "subject")
        self.commit_tree = ttk.Treeview(frm, columns=cols, show="headings", height=10, selectmode="browse")
        self.commit_tree.heading("short", text="Хеш")
        self.commit_tree.heading("date", text="Дата")
        self.commit_tree.heading("subject", text="Сообщение")
        self.commit_tree.column("short", width=80, stretch=False)
        self.commit_tree.column("date", width=160, stretch=False)
        self.commit_tree.column("subject", width=360, stretch=True)
        tip(
            self.commit_tree,
            "Список своих коммитов текущей ветки. Двойной щелчок — выбрать как «По»",
        )
        scroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.commit_tree.yview)
        self.commit_tree.configure(yscrollcommand=scroll.set)
        self.commit_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0), pady=2)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        self.commit_tree.bind("<<TreeviewSelect>>", self._on_commit_select)
        self.commit_tree.bind("<Double-1>", lambda _e: self.select_commit_as_to())

    def _build_objects_and_diff(self, parent: ttk.Frame) -> None:
        paned = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        obj_frm = ttk.LabelFrame(paned, text="Изменённые объекты и файлы")
        diff_frm = ttk.LabelFrame(paned, text="Сравнение (diff)")
        paned.add(obj_frm, weight=2)
        paned.add(diff_frm, weight=3)
        tip(obj_frm, "Файлы и объекты метаданных, изменённые в выбранном диапазоне коммитов")
        tip(diff_frm, "Текстовое сравнение выбранного файла между ревизиями «С» и «По»")

        cols = ("kind", "object", "path")
        self.obj_tree = ttk.Treeview(obj_frm, columns=cols, show="headings", selectmode="browse")
        self.obj_tree.heading("kind", text="Тип")
        self.obj_tree.heading("object", text="Объект")
        self.obj_tree.heading("path", text="Файл")
        self.obj_tree.column("kind", width=90, stretch=False)
        self.obj_tree.column("object", width=220, stretch=False)
        self.obj_tree.column("path", width=420, stretch=True)
        tip(self.obj_tree, "Выберите файл, чтобы увидеть сравнение справа")
        oscroll = ttk.Scrollbar(obj_frm, orient=tk.VERTICAL, command=self.obj_tree.yview)
        self.obj_tree.configure(yscrollcommand=oscroll.set)
        self.obj_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0), pady=2)
        oscroll.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        self.obj_tree.bind("<<TreeviewSelect>>", self._on_object_select)

        self.diff_text = tk.Text(diff_frm, wrap=tk.NONE, font=("Consolas", 10))
        tip(self.diff_text, "Unified diff выбранного файла (зелёный — добавлено, красный — удалено)")
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
        btn_run = ttk.Button(bar, text="Запустить сборку", command=self.run_pipeline)
        btn_run.pack(side=tk.LEFT, padx=2)
        tip(btn_run, "Выгрузить изменения из git и собрать расширение (XML и при необходимости .cfe)")
        btn_dry = ttk.Button(bar, text="Только анализ", command=self.run_dry_run)
        btn_dry.pack(side=tk.LEFT, padx=2)
        tip(btn_dry, "Инвентаризация без записи файлов расширения")
        status = ttk.Label(bar, textvariable=self.var_status)
        status.pack(side=tk.RIGHT, padx=8)
        tip(status, "Текущее состояние операции")

        log_frm = ttk.LabelFrame(parent, text="Журнал")
        log_frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tip(log_frm, "Ход выполнения и предупреждения")
        self.log_text = tk.Text(log_frm, height=10, wrap=tk.WORD, font=("Consolas", 9))
        tip(self.log_text, "Подробный журнал работы инструмента")
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
        purpose_ui = self.var_purpose.get().strip()
        if purpose_ui in PURPOSE_UI_TO_API:
            purpose = PURPOSE_UI_TO_API[purpose_ui]
        elif purpose_ui in PURPOSE_API_TO_UI:
            purpose = purpose_ui
        else:
            purpose = "Customization"
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
            purpose=purpose,
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
            raise GitError("Укажите репозиторий git")
        if not p.diff_from or not p.diff_to:
            raise GitError("Укажите диапазон «С»…«По» или идентификатор коммита")

    def _validate_run(self, p: PipelineParams) -> None:
        self._validate_preview(p)
        if not p.name:
            raise ValueError("Укажите имя расширения")
        if not p.output:
            raise ValueError("Укажите каталог результата")
        if not p.skip_build:
            if not p.cfe:
                raise ValueError("Укажите путь к файлу .cfe или включите «Только XML»")
            if not p.ib_path:
                raise ValueError("Укажите каталог ИБ или включите «Только XML»")

    # ------------------------------------------------------------------ commits / preview
    def refresh_commits(self) -> None:
        def work() -> None:
            repo = self.var_git_repo.get().strip()
            if not repo:
                raise GitError("Укажите репозиторий git")
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
            messagebox.showinfo("Коммит", "Выберите коммит в списке или введите ID выше")
            return
        self.var_commit_id.set(c.hash)
        self.apply_commit_id()

    def apply_commit_id(self) -> None:
        def work() -> None:
            repo = self.var_git_repo.get().strip()
            commit_id = self.var_commit_id.get().strip()
            if not repo:
                raise GitError("Укажите репозиторий git")
            if not commit_id:
                raise GitError("Введите идентификатор коммита (полный или короткий хеш)")
            from_rev, to_rev = range_for_commit(repo, commit_id)
            self.root.after(0, lambda: self.var_diff_from.set(from_rev))
            self.root.after(0, lambda: self.var_diff_to.set(to_rev))
            self.root.after(0, lambda: self.var_commit_id.set(to_rev))
            self.log(f"Коммит {to_rev[:12]}: С={from_rev[:12]} По={to_rev[:12]}")
            self.root.after(0, self.preview_changes)

        self._run_bg(work, "Разбор коммита…")

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
                kind = "файл"
                if dump_rel.lower().endswith(".bsl"):
                    kind = "модуль"
                elif "/forms/" in dump_rel.lower() or "\\forms\\" in dump_rel.lower():
                    kind = "форма"
                elif dump_rel.lower().endswith(".xml"):
                    kind = "xml"
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
                text = f"(нет текстового сравнения для {repo_path})\n"
            self.root.after(0, lambda: self._show_diff(text))

        self._run_bg(work, "Загрузка сравнения…")

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
            self.log("=== Подготовка базы и изменений из git ===")
            pair = prepare_pair_from_git(
                p.git_repo,
                p.diff_from,
                p.diff_to,
                dump_prefix=p.dump_prefix or None,
            )
            for w in pair.changes.warnings:
                self.log(f"[ПРЕДУПРЕЖДЕНИЕ] {w}")
            self.log(f"База из git ({p.diff_from}): {pair.config_dir}")
            self.log(f"Изменения ({p.diff_to}): {pair.changes.staging_dir} ({pair.changes.exported} файлов)")

            try:
                inv = build_inventory(pair.config_dir, pair.changes.staging_dir)
                self.log(
                    f"Инвентаризация: изменено={len(inv.changed_files)} "
                    f"заимствовать={len(inv.borrow_objects)} новые={len(inv.new_objects)} "
                    f"модули={len(inv.bsl_files)}"
                )
                for w in inv.warnings:
                    self.log(f"[ПРЕДУПРЕЖДЕНИЕ] {w}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"[ПРЕДУПРЕЖДЕНИЕ] не удалось построить инвентаризацию: {exc}")

            self.log("=== Сборка расширения ===")
            try:
                report = run_cfe_from_diff(
                    name=p.name,
                    config=pair.config_dir,
                    changes=pair.changes.staging_dir,
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
                self.log(f"[ОШИБКА] {exc}")
                raise
            finally:
                for d in pair.temp_dirs:
                    shutil.rmtree(d, ignore_errors=True)
                if pair.temp_dirs:
                    self.log("Временные каталоги удалены")

            self._log_report(report)
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Готово",
                    f"Заимствовано: {len(report.borrowed)}\n"
                    f"Новых объектов: {len(report.new_objects)}\n"
                    f"Модулей BSL: {len(report.bsl_files)}\n"
                    f"Собран .cfe: {'да' if report.built else 'нет'}\n"
                    f"Ошибок проверки: {report.validate_errors}",
                ),
            )

        self._run_bg(work, "Сборка…")

    def _log_report(self, report: RunReport) -> None:
        self.log("=== Итог ===")
        self.log(f"  Результат:     {report.output}")
        self.log(f"  Заимствовано:  {len(report.borrowed)}")
        for b in report.borrowed:
            self.log(f"    - {b}")
        self.log(f"  Новые:         {len(report.new_objects)}")
        for n in report.new_objects:
            self.log(f"    - {n}")
        self.log(f"  Модули BSL:    {len(report.bsl_files)}")
        for b in report.bsl_files:
            self.log(f"    - {b}")
        self.log(f"  Собран .cfe:   {'да' if report.built else 'нет'}")
        if report.cfe:
            self.log(f"  Файл .cfe:     {report.cfe}")
        for w in report.warnings:
            self.log(f"  [ПРЕДУПРЕЖДЕНИЕ] {w}")


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
