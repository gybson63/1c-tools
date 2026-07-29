"""Desktop GUI for cfe-from-diff: pick own commits, preview objects/diff, build CFE."""

from __future__ import annotations

import contextlib
import queue
import shutil
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cfe_tools.cancel import CancelledError, request_cancel
from cfe_tools.cancel import reset as cancel_reset
from cfe_tools.git_staging import (
    CommitInfo,
    GitError,
    commit_is_mine,
    get_file_diff,
    get_git_identity,
    list_changed_files,
    list_commits,
    map_repo_paths_to_objects,
    prepare_pair_from_git,
    range_for_commit,
    resolve_cf_location,
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
from cfe_tools.orchestrator import RunReport, run_cfe_from_diff, validate_extension_names
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
        self._commits_all: list[CommitInfo] = []
        self._git_author_name: str = ""
        self._git_author_email: str = ""
        self._changed_repo_paths: list[str] = []
        self._path_to_object: dict[str, str] = {}  # dump_rel -> borrow_spec or ""
        self._busy = False
        self._log_q: queue.Queue[str] = queue.Queue()
        self._save_after_id: str | None = None
        self._refresh_commits_after_id: str | None = None
        self._loading_settings = False
        self._progress_win: tk.Toplevel | None = None
        self.var_progress = tk.StringVar(value="")

        self._build_vars()
        self._settings_loaded = bool(load_settings())
        self._load_persisted_settings()
        self._build_ui()
        self._attach_settings_traces()
        self._update_git_hint()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_log)
        if self._settings_loaded:
            self.log(f"Загружены настройки: {settings_path()}")
        # Re-apply visibility after settings load
        self._toggle_build_section()
        # Commit list is empty until loaded — refresh once CF path is known
        self.root.after(200, self._maybe_auto_refresh_commits)

    # ------------------------------------------------------------------ UI
    def _build_vars(self) -> None:
        self.var_name = tk.StringVar(value="K7_XXXXX")
        self.var_purpose = tk.StringVar(value="Адаптация")
        self.var_prefix = tk.StringVar(value="")
        self.var_config = tk.StringVar(value="")
        self.var_git_hint = tk.StringVar(value="")
        self.var_output = tk.StringVar(value="")
        self.var_ib_path = tk.StringVar(value="")
        self.var_ibcmd = tk.StringVar(value="")
        self.var_user = tk.StringVar(value="")
        self.var_password = tk.StringVar(value="")
        self.var_changes = tk.StringVar(value="")
        self.var_diff_from = tk.StringVar(value="")
        self.var_diff_to = tk.StringVar(value="")
        self.var_commit_search = tk.StringVar(value="")
        self.var_git_identity = tk.StringVar(value="")
        self.var_skip_build = tk.BooleanVar(value=True)
        self.var_dry_run = tk.BooleanVar(value=False)
        self.var_force = tk.BooleanVar(value=False)
        self.var_keep_changes = tk.BooleanVar(value=False)
        self.var_own_commits_only = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="Готово")

        self._string_vars: dict[str, tk.StringVar] = {
            "name": self.var_name,
            "purpose": self.var_purpose,
            "prefix": self.var_prefix,
            "config": self.var_config,
            "output": self.var_output,
            "ib_path": self.var_ib_path,
            "ibcmd": self.var_ibcmd,
            "user": self.var_user,
        }
        self._bool_vars: dict[str, tk.BooleanVar] = {
            "skip_build": self.var_skip_build,
            "force": self.var_force,
            "own_commits_only": self.var_own_commits_only,
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
            # Migrate old git_repo + dump_prefix → config (Configuration.xml)
            if not self.var_config.get().strip():
                old_repo = data.get("git_repo")
                old_prefix = data.get("dump_prefix")
                if isinstance(old_repo, str) and old_repo.strip():
                    if isinstance(old_prefix, str) and old_prefix.strip():
                        joined = Path(old_repo.strip()) / Path(old_prefix.strip().replace("\\", "/"))
                        self.var_config.set(str(joined))
                    else:
                        self.var_config.set(old_repo.strip())
            # Prefer Configuration.xml if a dump directory was saved earlier
            cfg_val = self.var_config.get().strip()
            if cfg_val:
                cfg_path = Path(cfg_val)
                if cfg_path.is_dir():
                    xml = cfg_path / "Configuration.xml"
                    if xml.is_file():
                        self.var_config.set(str(xml))
                elif cfg_path.name.lower() != "configuration.xml":
                    sibling = cfg_path.parent / "Configuration.xml"
                    if sibling.is_file():
                        self.var_config.set(str(sibling))
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
        self.var_config.trace_add("write", self._on_config_changed)

    def _on_config_changed(self, *_args: object) -> None:
        self._update_git_hint()
        self._schedule_auto_refresh_commits()

    def _update_git_hint(self, *_args: object) -> None:
        cf = self.var_config.get().strip()
        if not cf:
            self.var_git_hint.set("")
            return
        try:
            root, prefix = resolve_cf_location(cf)
            pref = prefix or "(корень репозитория)"
            self.var_git_hint.set(f"git: {root}  ·  префикс: {pref}")
        except GitError as exc:
            self.var_git_hint.set(str(exc))

    def _schedule_auto_refresh_commits(self, *_args: object) -> None:
        if self._loading_settings:
            return
        if self._refresh_commits_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._refresh_commits_after_id)
        self._refresh_commits_after_id = self.root.after(700, self._maybe_auto_refresh_commits)

    def _maybe_auto_refresh_commits(self) -> None:
        self._refresh_commits_after_id = None
        if self._busy:
            return
        cf = self.var_config.get().strip()
        if not cf:
            return
        try:
            resolve_cf_location(cf)
        except GitError:
            return
        self.refresh_commits()

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

    def _browse_file(
        self,
        var: tk.StringVar,
        save: bool = False,
        *,
        title: str = "",
        filetypes: list[tuple[str, str]] | None = None,
    ) -> None:
        types = filetypes or [("Все файлы", "*.*"), ("Программы", "*.exe")]
        if save:
            path = filedialog.asksaveasfilename(title=title or None, filetypes=types)
        else:
            path = filedialog.askopenfilename(title=title or None, filetypes=types)
        if path:
            var.set(path)

    def _browse_configuration_xml(self, var: tk.StringVar) -> None:
        self._browse_file(
            var,
            title="Выберите Configuration.xml выгрузки CF (не каталог репозитория)",
            filetypes=[
                ("Configuration.xml", "Configuration.xml"),
                ("XML-файлы", "*.xml"),
                ("Все файлы", "*.*"),
            ],
        )

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
        browse_config_xml: bool = False,
    ) -> None:
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=0, sticky="w", padx=2, pady=2)
        tip(lbl, hint)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=2, pady=2)
        tip(entry, hint)
        if browse_config_xml:
            btn = ttk.Button(parent, text="…", width=3, command=lambda: self._browse_configuration_xml(var))
            tip(btn, "Выбрать файл Configuration.xml (не папку)")
        elif is_dir:
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
        tip(lbl, "Имя расширения 1С: буквы, цифры, «_» (например K7_20486). Без «-».")
        ent = ttk.Entry(frm, textvariable=self.var_name)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "Имя расширения 1С: буквы, цифры, «_» (например K7_20486). Без «-».")
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
        tip(lbl, "NamePrefix (буквы, цифры, «_»). Пусто — «<имя>_». Без «-».")
        ent = ttk.Entry(frm, textvariable=self.var_prefix)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        tip(ent, "NamePrefix (буквы, цифры, «_»). Пусто — «<имя>_». Без «-».")
        r += 1

        self._add_path_row(
            frm,
            r,
            "Configuration.xml",
            self.var_config,
            hint="Файл Configuration.xml из hierarchical XML-выгрузки основной CF "
            "(выберите именно файл, не папку и не корень репозитория). "
            "Корень git и префикс выгрузки определяются по расположению файла",
            is_dir=False,
            browse_config_xml=True,
        )
        r += 1

        hint = ttk.Label(frm, textvariable=self.var_git_hint, foreground="#555555")
        hint.grid(row=r, column=1, columnspan=2, sticky="ew", padx=2, pady=(0, 4))
        tip(hint, "Автоматически: корень git-репозитория и относительный префикс выгрузки CF")
        r += 1

        self._add_path_row(
            frm,
            r,
            "Каталог результата",
            self.var_output,
            hint="Куда записать XML расширения; файл .cfe при сборке будет здесь же: <имя>.cfe",
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
        tip(
            self._build_frm,
            "Параметры сборки двоичного .cfe через ibcmd (нужна файловая ИБ). "
            "Файл .cfe будет записан в каталог результата как «<имя расширения>.cfe»",
        )
        br = 0
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

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, padx=2, pady=2)
        btn_ref = ttk.Button(btns, text="Обновить список", command=self.refresh_commits)
        btn_ref.pack(side=tk.LEFT, padx=2)
        tip(btn_ref, "Загрузить коммиты текущей ветки из git")
        chk_own = ttk.Checkbutton(
            btns,
            text="Только свои",
            variable=self.var_own_commits_only,
            command=self._apply_commit_filters,
        )
        chk_own.pack(side=tk.LEFT, padx=4)
        tip(
            chk_own,
            "Показывать только коммиты, где автор совпадает с git user.name или user.email. "
            "Если список пуст — сверьте «Я: …» с колонкой «Автор»",
        )
        btn_prev = ttk.Button(btns, text="Показать изменения", command=self.preview_changes)
        btn_prev.pack(side=tk.LEFT, padx=2)
        tip(btn_prev, "Показать изменённые объекты и файлы для диапазона «С»…«По»")
        id_lbl = ttk.Label(btns, textvariable=self.var_git_identity, foreground="#555555")
        id_lbl.pack(side=tk.LEFT, padx=8)
        tip(id_lbl, "Текущий git user.name / user.email для фильтра «Только свои»")

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

        search_frm = ttk.Frame(frm)
        search_frm.pack(fill=tk.X, padx=2, pady=2)
        lbl = ttk.Label(search_frm, text="Поиск")
        lbl.pack(side=tk.LEFT)
        tip(lbl, "Фильтр по хешу, автору или тексту сообщения (без учёта регистра)")
        ent_search = ttk.Entry(search_frm, textvariable=self.var_commit_search)
        ent_search.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        tip(ent_search, "Подстрока в хеше, авторе или сообщении; список обновляется при вводе")
        self.var_commit_search.trace_add("write", lambda *_a: self._apply_commit_filters())

        tree_frm = ttk.Frame(frm)
        tree_frm.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        cols = ("hash", "date", "author", "subject")
        self.commit_tree = ttk.Treeview(tree_frm, columns=cols, show="headings", height=10, selectmode="browse")
        self.commit_tree.heading("hash", text="Хеш")
        self.commit_tree.heading("date", text="Дата")
        self.commit_tree.heading("author", text="Автор")
        self.commit_tree.heading("subject", text="Сообщение")
        self.commit_tree.column("hash", width=200, stretch=False)
        self.commit_tree.column("date", width=130, stretch=False)
        self.commit_tree.column("author", width=120, stretch=False)
        self.commit_tree.column("subject", width=240, stretch=True)
        tip(
            self.commit_tree,
            "Клик по коммиту — сразу показать его изменения (С = родитель, По = коммит)",
        )
        scroll = ttk.Scrollbar(tree_frm, orient=tk.VERTICAL, command=self.commit_tree.yview)
        self.commit_tree.configure(yscrollcommand=scroll.set)
        self.commit_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.commit_tree.bind("<<TreeviewSelect>>", self._on_commit_select)

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

        log_bar = ttk.Frame(log_frm)
        log_bar.pack(fill=tk.X, padx=2, pady=(2, 0))
        btn_copy = ttk.Button(log_bar, text="Копировать", command=self._copy_log)
        btn_copy.pack(side=tk.RIGHT, padx=2)
        tip(btn_copy, "Скопировать журнал в буфер обмена (выделение — только его, иначе весь текст)")
        btn_save = ttk.Button(log_bar, text="Сохранить…", command=self._save_log)
        btn_save.pack(side=tk.RIGHT, padx=2)
        tip(btn_save, "Сохранить журнал в текстовый файл")

        log_body = ttk.Frame(log_frm)
        log_body.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.log_text = tk.Text(log_body, height=10, wrap=tk.WORD, font=("Consolas", 9))
        tip(self.log_text, "Подробный журнал работы инструмента")
        lscroll = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lscroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lscroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        self._log_q.put(msg)

    def _log_contents(self) -> str:
        return self.log_text.get("1.0", "end-1c")

    def _copy_log(self) -> None:
        try:
            selected = self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            selected = ""
        text = selected if selected else self._log_contents()
        if not text.strip():
            self.var_status.set("Журнал пуст")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.var_status.set("Скопировано выделение журнала" if selected else "Журнал скопирован в буфер обмена")

    def _save_log(self) -> None:
        text = self._log_contents()
        if not text.strip():
            messagebox.showinfo("Журнал", "Журнал пуст — нечего сохранять.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить журнал",
            defaultextension=".txt",
            filetypes=[
                ("Текстовые файлы", "*.txt"),
                ("Все файлы", "*.*"),
            ],
            initialfile="cfe-from-diff-log.txt",
        )
        if not path:
            return
        try:
            Path(path).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить журнал:\n{exc}")
            return
        self.var_status.set(f"Журнал сохранён: {path}")
        self.log(f"Журнал сохранён: {path}")

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

    def _show_progress(self, status: str) -> None:
        """Модальное окно прогресса с кнопкой «Отменить»; блокирует основное окно."""
        if self._progress_win is not None:
            self.var_progress.set(status)
            with contextlib.suppress(tk.TclError):
                self._progress_win.update_idletasks()
            return

        win = tk.Toplevel(self.root)
        win.title("Выполняется…")
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self._request_cancel)

        frm = ttk.Frame(win, padding=16)
        frm.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self.var_progress.set(status)
        # Явная подпись этапа: без неё окно выглядит «пустым» при долгой операции.
        lbl = ttk.Label(
            frm,
            textvariable=self.var_progress,
            wraplength=380,
            justify=tk.LEFT,
            anchor="w",
            font=("Segoe UI", 10),
        )
        lbl.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        tip(lbl, "Текущий этап операции.")

        bar = ttk.Progressbar(frm, mode="indeterminate", length=380)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        bar.start(12)

        btn = ttk.Button(frm, text="Отменить", command=self._request_cancel)
        btn.grid(row=2, column=0)
        tip(btn, "Прервать текущую операцию. Уже запущенные внешние процессы будут остановлены.")

        win.update_idletasks()
        req_w = max(win.winfo_reqwidth(), 420)
        req_h = win.winfo_reqheight()
        win.minsize(420, max(req_h, 110))
        rw = self.root.winfo_rootx()
        rh = self.root.winfo_rooty()
        ww = self.root.winfo_width()
        wh = self.root.winfo_height()
        win.geometry(f"+{rw + (ww - req_w) // 2}+{rh + (wh - req_h) // 2}")

        win.grab_set()
        self._progress_win = win
        self._progress_bar = bar

    def _hide_progress(self) -> None:
        win = self._progress_win
        self._progress_win = None
        if win is None:
            return
        with contextlib.suppress(tk.TclError):
            if getattr(self, "_progress_bar", None) is not None:
                self._progress_bar.stop()
            win.grab_release()
            win.destroy()

    def _set_progress(self, status: str) -> None:
        def apply(msg: str = status) -> None:
            self.var_progress.set(msg)
            self.var_status.set(msg)
            win = self._progress_win
            if win is not None:
                with contextlib.suppress(tk.TclError):
                    win.update_idletasks()

        self.root.after(0, apply)

    def _report_progress(self, status: str) -> None:
        """Update progress window / status and append a journal line."""
        self._set_progress(status)
        self.log(status)

    def _request_cancel(self) -> None:
        request_cancel()
        self.var_progress.set("Отмена…")
        self.var_status.set("Отмена…")
        self.log("[ОТМЕНА] Запрошена остановка операции…")

    def _run_bg(
        self,
        work: Callable[[], None],
        status: str = "Выполняется…",
        *,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        if self._busy:
            self.var_status.set("Дождитесь завершения текущей операции…")
            return

        cancel_reset()
        # Показать окно и текст этапа сразу в UI-потоке (до старта фоновой работы).
        self._set_busy(True, status)
        self._show_progress(status)

        def runner() -> None:
            cancelled = False
            failed = False
            try:
                work()
            except CancelledError:
                cancelled = True
                self.log("[ОТМЕНА] Операция прервана пользователем.")
            except Exception as exc:  # noqa: BLE001 — show in UI
                failed = True
                self.log(f"[ERROR] {exc}")
                err = str(exc)

                def show_error(msg: str = err) -> None:
                    messagebox.showerror("Ошибка", msg)

                self.root.after(0, show_error)
            finally:

                def finish_ui() -> None:
                    self._hide_progress()
                    self._set_busy(False, "Отменено" if cancelled else "Готово")
                    if on_done is not None and not cancelled and not failed:
                        on_done()

                self.root.after(0, finish_ui)

        threading.Thread(target=runner, daemon=True).start()

    def _cfe_path_for(self, name: str, output: str) -> str:
        """Путь .cfe: каталог результата / <имя расширения>.cfe."""
        return str(Path(output) / f"{name}.cfe")

    def _resolve_git(self) -> tuple[str, str]:
        """Return (git_repo, dump_prefix) from Configuration.xml path."""
        cf = self.var_config.get().strip()
        if not cf:
            raise GitError("Укажите файл Configuration.xml выгрузки CF (не каталог репозитория)")
        root, prefix = resolve_cf_location(cf)
        return str(root), prefix

    def _collect_params(self) -> PipelineParams:
        purpose_ui = self.var_purpose.get().strip()
        if purpose_ui in PURPOSE_UI_TO_API:
            purpose = PURPOSE_UI_TO_API[purpose_ui]
        elif purpose_ui in PURPOSE_API_TO_UI:
            purpose = purpose_ui
        else:
            purpose = "Customization"
        name = self.var_name.get().strip()
        output = self.var_output.get().strip()
        cfe = self._cfe_path_for(name, output) if name and output else ""
        git_repo, dump_prefix = "", ""
        cf = self.var_config.get().strip()
        if cf:
            with contextlib.suppress(GitError):
                git_repo, dump_prefix = self._resolve_git()
        return PipelineParams(
            name=name,
            config=cf,
            git_repo=git_repo,
            dump_prefix=dump_prefix,
            output=output,
            cfe=cfe,
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
        if not p.config:
            raise GitError("Укажите файл Configuration.xml выгрузки CF (не каталог репозитория)")
        if not p.git_repo:
            # Force a clear error from resolve
            self._resolve_git()
        if not p.diff_from or not p.diff_to:
            raise GitError("Укажите диапазон «С»…«По» или идентификатор коммита")

    def _validate_run(self, p: PipelineParams) -> None:
        self._validate_preview(p)
        validate_extension_names(p.name, p.prefix or None)
        if not p.output:
            raise ValueError("Укажите каталог результата")
        if not p.skip_build and not p.ib_path:
            raise ValueError("Укажите каталог ИБ или включите «Только XML»")

    # ------------------------------------------------------------------ commits / preview
    def refresh_commits(self) -> None:
        def work() -> None:
            repo, prefix = self._resolve_git()
            name, email = "", ""
            try:
                name, email = get_git_identity(repo)
                self.log(f"Я (git): {name} <{email}>")
            except GitError as exc:
                self.log(f"[ПРЕДУПРЕЖДЕНИЕ] {exc}")
            pref = prefix or "(корень)"
            self.log(f"CF → git: {repo}  ·  префикс: {pref}")
            self.log("Загрузка коммитов…")
            commits = list_commits(repo, max_count=150, own_only=False)
            self._commits_all = commits
            self._git_author_name = name
            self._git_author_email = email

            def apply_ui() -> None:
                if name or email:
                    self.var_git_identity.set(f"Я: {name} <{email}>".strip())
                else:
                    self.var_git_identity.set("Я: (не задано в git config)")
                self._apply_commit_filters()

            self.root.after(0, apply_ui)
            self.log(f"Загружено коммитов: {len(commits)}")
            if not commits:
                self.log("Список пуст: в текущей ветке нет коммитов (проверьте каталог конфигурации / git).")

        self._run_bg(work, "Загрузка коммитов…")

    def _apply_commit_filters(self, *_args: object) -> None:
        own_only = bool(self.var_own_commits_only.get())
        query = self.var_commit_search.get().strip().lower()
        filtered: list[CommitInfo] = []
        for c in self._commits_all:
            if own_only and not commit_is_mine(
                c,
                author_name=self._git_author_name,
                author_email=self._git_author_email,
            ):
                continue
            if query:
                hay = f"{c.hash} {c.short_hash} {c.author_name} {c.author_email} {c.subject}".lower()
                if query not in hay:
                    continue
            filtered.append(c)
        self._commits = filtered
        self._fill_commits(filtered)
        if own_only and self._commits_all and not filtered and not query:
            who = self.var_git_identity.get() or "git user"
            self.var_status.set(f"Нет коммитов для {who}; сверьте колонку «Автор» или снимите «Только свои»")

    def _fill_commits(self, commits: list[CommitInfo]) -> None:
        self.commit_tree.delete(*self.commit_tree.get_children())
        for c in commits:
            self.commit_tree.insert(
                "",
                tk.END,
                iid=c.hash,
                values=(c.hash, c.author_date[:19], c.author_name, c.subject),
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
        c = self._selected_commit()
        if not c:
            return
        self.var_status.set(f"Выбран: {c.short_hash} — {c.subject}")
        if self._busy:
            return
        if self.var_diff_to.get().strip() == c.hash:
            return
        self.apply_commit(c.hash)

    def apply_commit(self, commit_id: str) -> None:
        """Set DiffFrom/DiffTo from commit (parent..commit) and preview changes."""
        commit_id = commit_id.strip()
        if not commit_id:
            return
        result: dict[str, str] = {}

        def work() -> None:
            repo, _prefix = self._resolve_git()
            from_rev, to_rev = range_for_commit(repo, commit_id)
            result["from"] = from_rev
            result["to"] = to_rev
            self.log(f"Коммит {to_rev[:12]}: С={from_rev[:12]} По={to_rev[:12]}")

        def after_ok() -> None:
            self.var_diff_from.set(result["from"])
            self.var_diff_to.set(result["to"])
            self.preview_changes()

        self._run_bg(work, "Разбор коммита…", on_done=after_ok)

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
            service = {"version", "configdumpinfo.xml", "configuration.xml"}
            notable = [u for u in unmapped if Path(u).name.lower() not in service]
            for u in notable[:20]:
                self.log(f"[WARN] Не включён в расширение (не объект метаданных): {u}")
            if len(notable) > 20:
                self.log(f"[WARN] …и ещё {len(notable) - 20}")

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

    def _confirm_cfe_overwrite(self, p: PipelineParams) -> bool:
        """Ask to overwrite existing .cfe; return False if user cancels."""
        if p.skip_build or p.dry_run or not p.cfe:
            return True
        cfe_path = Path(p.cfe)
        if not cfe_path.is_file():
            return True
        return bool(
            messagebox.askyesno(
                "Файл уже существует",
                f"Файл .cfe уже существует:\n{cfe_path}\n\nПерезаписать?",
                icon="warning",
            )
        )

    def run_pipeline(self) -> None:
        try:
            p = self._collect_params()
            self._validate_run(p)
        except (ValueError, GitError) as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        if not self._confirm_cfe_overwrite(p):
            self.var_status.set("Отменено")
            self.log("[ОТМЕНА] Перезапись .cfe отклонена пользователем.")
            return

        def work() -> None:
            p = self._collect_params()
            self._validate_run(p)
            self._report_progress("Подготовка базы и изменений из git…")
            self.log("=== Подготовка базы и изменений из git ===")
            pair = prepare_pair_from_git(
                p.git_repo,
                p.diff_from,
                p.diff_to,
                dump_prefix=p.dump_prefix or None,
                on_progress=self._report_progress,
            )
            for w in pair.changes.warnings:
                self.log(f"[ПРЕДУПРЕЖДЕНИЕ] {w}")
            self.log(f"База из git ({p.diff_from}): {pair.config_dir}")
            self.log(f"Изменения ({p.diff_to}): {pair.changes.staging_dir} ({pair.changes.exported} файлов)")

            try:
                self._report_progress("Предварительный анализ изменений…")
                inv = build_inventory(pair.config_dir, pair.changes.staging_dir)
                self.log(
                    f"Инвентаризация: изменено={len(inv.changed_files)} "
                    f"заимствовать={len(inv.borrow_objects)} новые={len(inv.new_objects)} "
                    f"модули={len(inv.bsl_files)} макеты={len(inv.template_files)}"
                )
                for w in inv.warnings:
                    self.log(f"[ПРЕДУПРЕЖДЕНИЕ] {w}")
            except CancelledError:
                for d in pair.temp_dirs:
                    shutil.rmtree(d, ignore_errors=True)
                raise
            except Exception as exc:  # noqa: BLE001
                self.log(f"[ПРЕДУПРЕЖДЕНИЕ] не удалось построить инвентаризацию: {exc}")

            self.log("=== Сборка расширения ===")
            if not p.skip_build:
                self.log(f"Файл .cfe: {p.cfe}")
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
                    on_progress=self._report_progress,
                )
            except (CancelledError, CfeInitError, CfeBorrowError, IbcmdError, FileNotFoundError, ValueError) as exc:
                if isinstance(exc, CancelledError):
                    self.log("[ОТМЕНА] Сборка прервана.")
                else:
                    self.log(f"[ОШИБКА] {exc}")
                raise
            finally:
                for d in pair.temp_dirs:
                    shutil.rmtree(d, ignore_errors=True)
                if pair.temp_dirs:
                    self.log("Временные каталоги удалены")

            self._log_report(report)
            summary = (
                f"Заимствовано: {len(report.borrowed)}\n"
                f"Новых объектов: {len(report.new_objects)}\n"
                f"Модулей BSL: {len(report.bsl_files)}\n"
                f"Макетов (СКД/XML): {len(report.template_files)}\n"
                f"Собран .cfe: {'да' if report.built else 'нет'}"
            )
            if report.validate_errors:
                summary += f"\n\nЗамечаний cfe-validate: {report.validate_errors}\n(см. журнал; .cfe всё равно собран)"
            self.root.after(0, lambda s=summary: messagebox.showinfo("Готово", s))  # type: ignore[misc]

        self._run_bg(work, "Подготовка базы и изменений из git…")

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
        self.log(f"  Макеты:        {len(report.template_files)}")
        for t in report.template_files:
            self.log(f"    - {t}")
        self.log(f"  Собран .cfe:   {'да' if report.built else 'нет'}")
        if report.cfe:
            self.log(f"  Файл .cfe:     {report.cfe}")
        for w in report.warnings:
            self.log(f"  [ПРЕДУПРЕЖДЕНИЕ] {w}")


def _ensure_stdio() -> None:
    """Under pythonw stdout/stderr are None — provide safe stubs for print/reconfigure."""

    class _DevNull:
        encoding = "utf-8"
        errors = "replace"

        def write(self, s: object) -> int:
            if s is None:
                return 0
            return len(str(s))

        def flush(self) -> None:
            return None

        def reconfigure(self, **_kwargs: object) -> None:
            return None

        def isatty(self) -> bool:
            return False

        @property
        def buffer(self) -> None:
            return None

    if sys.stdout is None:
        sys.stdout = _DevNull()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _DevNull()  # type: ignore[assignment]


def main() -> int:
    _ensure_stdio()
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
