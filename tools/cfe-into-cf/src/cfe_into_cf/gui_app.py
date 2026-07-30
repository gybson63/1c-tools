"""Tkinter GUI for cfe-into-cf."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cfe_into_cf.cancel import request_cancel
from cfe_into_cf.cancel import reset as cancel_reset
from cfe_into_cf.designer import DesignerError
from cfe_into_cf.inventory import ObjectRef
from cfe_into_cf.orchestrator import NewObjectsNotAcceptedError, run_cfe_into_cf


class NewObjectsDialog(tk.Toplevel):
    """Modal alert when Own objects will be added to the main configuration."""

    def __init__(self, master: tk.Tk | tk.Toplevel, objects: list[ObjectRef]) -> None:
        super().__init__(master)
        self.title("ВНИМАНИЕ: новые объекты")
        self.resizable(True, True)
        self.result = False
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(
            frm,
            text="В основную конфигурацию будут ДОБАВЛЕНЫ\nновые объекты метаданных",
            fg="#b00020",
            font=("Segoe UI", 12, "bold"),
            justify=tk.CENTER,
        )
        title.pack(pady=(0, 8))

        tip = ttk.Label(
            frm,
            text=(
                "Это рискованная операция: меняется структура метаданных и, часто, БД.\n"
                "Проверьте права, обмены, РИБ и совместимость перед продолжением."
            ),
            justify=tk.LEFT,
        )
        tip.pack(anchor=tk.W, pady=(0, 8))

        list_frm = ttk.Frame(frm)
        list_frm.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_frm)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(list_frm, height=12, yscrollcommand=scroll.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.listbox.yview)
        for obj in objects:
            self.listbox.insert(tk.END, obj.key)

        self.var_ok = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(
            frm,
            text="Я понимаю риск добавления новых объектов",
            variable=self.var_ok,
            command=self._sync_btn,
        )
        chk.pack(anchor=tk.W, pady=8)

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X)
        ttk.Button(btn_frm, text="Отмена", command=self._cancel).pack(side=tk.RIGHT, padx=4)
        self.btn_continue = ttk.Button(
            btn_frm,
            text="Добавить объекты и продолжить",
            command=self._continue,
            state=tk.DISABLED,
        )
        self.btn_continue.pack(side=tk.RIGHT, padx=4)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window(self)

    def _sync_btn(self) -> None:
        self.btn_continue.configure(state=tk.NORMAL if self.var_ok.get() else tk.DISABLED)

    def _cancel(self) -> None:
        self.result = False
        self.destroy()

    def _continue(self) -> None:
        if not self.var_ok.get():
            return
        self.result = True
        self.destroy()


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("cfe-into-cf — расширение → основная конфигурация")
        self.root.geometry("780x560")
        self._log_q: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self.var_extension = tk.StringVar()
        self.var_ib_path = tk.StringVar()
        self.var_ib_user = tk.StringVar()
        self.var_ib_password = tk.StringVar()
        self.var_v8 = tk.StringVar()
        self.var_repo_path = tk.StringVar()
        self.var_repo_user = tk.StringVar()
        self.var_repo_password = tk.StringVar()
        self.var_dry_run = tk.BooleanVar(value=True)
        self.var_skip_update = tk.BooleanVar(value=False)
        self.var_repo_commit = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Готово")

        self._build_ui()
        self.root.after(100, self._drain_log)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        grid = ttk.LabelFrame(outer, text="Параметры", padding=6)
        grid.pack(fill=tk.X)

        def row(label: str, var: tk.StringVar, browse: str | None = None, show: str | None = None) -> None:
            frm = ttk.Frame(grid)
            frm.pack(fill=tk.X, pady=2)
            ttk.Label(frm, text=label, width=18).pack(side=tk.LEFT)
            ent = ttk.Entry(frm, textvariable=var, show=show or "")
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            if browse == "dir":
                ttk.Button(frm, text="…", width=3, command=lambda: self._browse_dir(var)).pack(side=tk.LEFT)
            elif browse == "file":
                ttk.Button(frm, text="…", width=3, command=lambda: self._browse_file(var)).pack(side=tk.LEFT)

        row("Расширение", self.var_extension)
        row("ИБ (файловая)", self.var_ib_path, browse="dir")
        row("Пользователь ИБ", self.var_ib_user)
        row("Пароль ИБ", self.var_ib_password, show="*")
        row("1cv8.exe", self.var_v8, browse="file")
        row("Хранилище", self.var_repo_path, browse="dir")
        row("Пользователь хран.", self.var_repo_user)
        row("Пароль хранилища", self.var_repo_password, show="*")

        opts = ttk.Frame(grid)
        opts.pack(fill=tk.X, pady=4)
        ttk.Checkbutton(opts, text="Dry-run", variable=self.var_dry_run).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(opts, text="Без UpdateDBCfg", variable=self.var_skip_update).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(opts, text="Поместить в хранилище", variable=self.var_repo_commit).pack(
            side=tk.LEFT, padx=4
        )

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=6)
        self.btn_run = ttk.Button(btns, text="Запуск", command=self._start)
        self.btn_run.pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Отмена", command=self._cancel).pack(side=tk.LEFT, padx=4)
        ttk.Label(btns, textvariable=self.var_status).pack(side=tk.LEFT, padx=12)

        log_frm = ttk.LabelFrame(outer, text="Журнал", padding=4)
        log_frm.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log_frm, height=20, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)

    def _browse_dir(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _browse_file(self, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(filetypes=[("Executable", "*.exe"), ("All", "*.*")])
        if path:
            var.set(path)

    def log_msg(self, msg: str) -> None:
        self._log_q.put(msg)

    def _drain_log(self) -> None:
        while True:
            try:
                msg = self._log_q.get_nowait()
            except queue.Empty:
                break
            self.log.insert(tk.END, msg + "\n")
            self.log.see(tk.END)
        self.root.after(100, self._drain_log)

    def _cancel(self) -> None:
        request_cancel()
        self.log_msg("Запрошена отмена…")

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Занято", "Уже выполняется операция")
            return
        if not self.var_extension.get().strip():
            messagebox.showerror("Ошибка", "Укажите имя расширения")
            return
        if not self.var_ib_path.get().strip():
            messagebox.showerror("Ошибка", "Укажите путь к файловой ИБ")
            return

        cancel_reset()
        self.btn_run.configure(state=tk.DISABLED)
        self.var_status.set("Выполняется…")
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def _confirm_new_objects(self, objects: list[ObjectRef]) -> bool:
        done = threading.Event()
        decision = {"ok": False}

        def ask_and_signal() -> None:
            dlg = NewObjectsDialog(self.root, objects)
            decision["ok"] = dlg.result
            done.set()

        self.root.after(0, ask_and_signal)
        done.wait()
        return bool(decision["ok"])

    def _run_worker(self) -> None:
        accept = False
        try:
            while True:
                try:
                    report = run_cfe_into_cf(
                        extension=self.var_extension.get().strip(),
                        ib_path=self.var_ib_path.get().strip() or None,
                        ib_user=self.var_ib_user.get().strip() or None,
                        ib_password=self.var_ib_password.get() or None,
                        v8_path=self.var_v8.get().strip() or None,
                        repo_path=self.var_repo_path.get().strip() or None,
                        repo_user=self.var_repo_user.get().strip() or None,
                        repo_password=self.var_repo_password.get() or None,
                        accept_new_objects=accept,
                        dry_run=self.var_dry_run.get(),
                        skip_update_db=self.var_skip_update.get(),
                        repo_commit=self.var_repo_commit.get(),
                        on_progress=self.log_msg,
                    )
                    self.log_msg(
                        f"Готово. Own={len(report.own_objects)} Adopted={len(report.adopted_objects)} "
                        f"Merged={report.merged} Loaded={report.loaded}"
                    )
                    self.root.after(0, lambda: self.var_status.set("Готово"))
                    break
                except NewObjectsNotAcceptedError as exc:
                    if not self._confirm_new_objects(exc.inventory.own_objects):
                        self.log_msg("Отменено пользователем (новые объекты не приняты)")
                        self.root.after(0, lambda: self.var_status.set("Отменено"))
                        break
                    accept = True
                    continue
                except DesignerError as exc:
                    self.log_msg(f"[ERROR] {exc}")
                    self.root.after(0, lambda: self.var_status.set("Ошибка"))
                    break
                except Exception as exc:  # noqa: BLE001
                    self.log_msg(f"[ERROR] {exc}")
                    self.root.after(0, lambda: self.var_status.set("Ошибка"))
                    break
        finally:
            self.root.after(0, lambda: self.btn_run.configure(state=tk.NORMAL))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    App().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
