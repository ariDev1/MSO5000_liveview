# gui/system_info.py

import tkinter as tk
from tkinter import ttk
import version as V

from scpi.data import scpi_data
from utils.debug import log_debug

def setup_system_info_tab(tab_frame, root):
    # ---------------- Left panel: text + scrollbar + bottom controls --------
    left_panel = tk.Frame(tab_frame, bg="#1a1a1a")
    left_panel.pack(side="left", fill="both", expand=True)

    # Use grid inside left_panel so controls can sit BELOW the text area
    left_panel.grid_rowconfigure(0, weight=1)
    left_panel.grid_columnconfigure(0, weight=1)

    text_widget = tk.Text(
        left_panel, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
        insertbackground="#ffffff", selectbackground="#333333", wrap="none"
    )
    text_widget.grid(row=0, column=0, sticky="nsew", padx=5, pady=(5, 0))

    scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.grid(row=0, column=1, sticky="ns", pady=(5, 0))

    text_widget.config(state=tk.DISABLED)

    after_id = [None]

    # ---------------- Host/Env helpers (local only; no SCPI) ----------------
    from functools import lru_cache
    from pathlib import Path
    import platform, sys, shutil

    def _fmt_bytes(n):
        try:
            n = float(n)
        except Exception:
            return str(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024.0:
                return f"{n:,.1f} {unit}"
            n /= 1024.0
        return f"{n:,.1f} PB"

    @lru_cache(maxsize=1)
    def _static_versions():
        vers = {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "numpy": None, "matplotlib": None, "pandas": None, "scipy": None,
            "pyvisa": None, "pyvisa_py": None,
        }
        try:
            import numpy as _np; vers["numpy"] = _np.__version__
        except Exception: pass
        try:
            import matplotlib as _mpl; vers["matplotlib"] = _mpl.__version__
        except Exception: pass
        try:
            import pandas as _pd; vers["pandas"] = _pd.__version__
        except Exception: pass
        try:
            import scipy as _sp; vers["scipy"] = _sp.__version__
        except Exception: pass
        try:
            import pyvisa as _visa; vers["pyvisa"] = _visa.__version__
        except Exception: pass
        try:
            import pyvisa_py as _vpy; vers["pyvisa_py"] = getattr(_vpy, "__version__", "installed")
        except Exception: pass
        return vers

    def _build_host_env_block():
        # psutil optional; degrade gracefully
        try:
            import psutil
            mem = psutil.virtual_memory()
            cpu_pct = psutil.cpu_percent(interval=None)
            ram_pct = mem.percent
        except Exception:
            cpu_pct = 0
            ram_pct = 0
        v = _static_versions()
        uname = platform.uname()
        total, used, free = shutil.disk_usage(Path.cwd())
        lines = [
            "Host / Environment",
            "-------------------",
            f"OS           : {uname.system} {uname.release} ({uname.machine})",
            f"Python       : {v['python']}  | NumPy {v['numpy'] or '-'}, Matplotlib {v['matplotlib'] or '-'}, "
            f"Pandas {v['pandas'] or '-'}, SciPy {v['scipy'] or '-'}",
            f"PyVISA       : {v['pyvisa'] or '-'}  | pyvisa-py {v['pyvisa_py'] or '-'}",
            f"CPU / RAM    : {cpu_pct:>4.0f}% / {ram_pct:>3.0f}%",
            f"Disk (cwd)   : free {_fmt_bytes(free)} of {_fmt_bytes(total)}",
            "",
        ]
        return "\n".join(lines)

    def _build_status_block():
        try:
            from app import app_state
        except Exception:
            try:
                import app_state
            except Exception:
                app_state = None

        def _g(name, default=False):
            return getattr(app_state, name, default) if app_state else default

        return (
            "Status\n"
            "------\n"
            f"logging={_g('is_logging_active', False)}  "
            f"power={_g('is_power_analysis_active', False)}  "
            f"scpi_busy={_g('is_scpi_busy', False)}  "
            f"shutdown={_g('is_shutting_down', False)}\n\n"
        )
    # -----------------------------------------------------------------------

    # ---------------------- Docs viewer (local .md) ------------------------
    from pathlib import Path as _Path
    docs_dir_candidates = [
        Path.cwd() / "docs",
        Path(__file__).resolve().parents[1] / "docs",  # repo root /docs
    ]
    docs_dir = next((p for p in docs_dir_candidates if p.exists()), None)

    def _scan_docs():
        if not docs_dir:
            return []
        return sorted([p for p in docs_dir.glob("*.md") if p.is_file()])

    doc_choices = _scan_docs()
    doc_var = tk.StringVar(value="")
    selected_doc_text = [""]   # cached markdown text
    selected_doc_path = [None]

    def _load_selected_doc():
        name = doc_var.get().strip()
        if not name:
            selected_doc_text[0] = ""
            selected_doc_path[0] = None
            return
        if not docs_dir:
            log_debug("[SystemInfo] docs dir not found")
            return
        path = None
        for p in _scan_docs():
            if p.stem == name or p.name == name:
                path = p
                break
        if not path:
            log_debug(f"[SystemInfo] doc not found: {name}")
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 200_000:
                text = text[:200_000] + "\n\n[... truncated ...]"
            selected_doc_text[0] = text
            selected_doc_path[0] = path
            log_debug(f"[SystemInfo] loaded doc: {path}")
        except Exception as e:
            log_debug(f"[SystemInfo] failed to load doc: {e}")

    # Bottom controls row **inside left_panel**, below the text area
    controls_row = ttk.Frame(left_panel)
    controls_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    # Docs widgets (left-aligned)
    if docs_dir:
        ttk.Label(controls_row, text="Docs:").pack(side="left", padx=(0, 4))
        cb = ttk.Combobox(
            controls_row, textvariable=doc_var, state="readonly", width=32,
            values=[p.stem for p in doc_choices]
        )
        cb.pack(side="left", padx=4)

        ttk.Button(controls_row, text="Show", command=lambda: (_load_selected_doc(), update_system_info())
                  ).pack(side="left", padx=4)
        ttk.Button(controls_row, text="Clear", command=lambda: (doc_var.set(""), selected_doc_text.__setitem__(0, ""), selected_doc_path.__setitem__(0, None), update_system_info())
                  ).pack(side="left", padx=4)

    # Copy button (also left-aligned, after docs controls)
    def copy_system_info_to_clipboard():
        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{V.APP_NAME} {V.VERSION}\n"
            f"Build Date : {V.BUILD_DATE}\n"
            f"Git Commit : {V.GIT_COMMIT}\n"
            f"Maintainer : {V.AUTHOR}\n"
            f"Project    : {V.PROJECT_URL}\n"
        )
        host_block = _build_host_env_block()
        status_block = _build_status_block()
        base_info = scpi_data.get("system_info", "")
        freq_ref = scpi_data.get("freq_ref", None)
        if freq_ref:
            base_info += f"\n{'Freq. Reference' :<18}: {freq_ref}"

        docs_block = ""
        if selected_doc_text[0]:
            title = selected_doc_path[0].name if selected_doc_path[0] else "(doc)"
            docs_block = f"\n\n{'-'*60}\nDocumentation: {title}\n{'-'*60}\n{selected_doc_text[0]}\n"

        full_text = host_block + status_block + base_info + docs_block + meta_info

        root.clipboard_clear()
        root.clipboard_append(full_text)
        root.update()
        log_debug("📋 System Info copied to clipboard")

    ttk.Button(controls_row, text="📋 Copy System Info", command=copy_system_info_to_clipboard).pack(
        side="left", padx=8
    )
    # -----------------------------------------------------------------------

    last_system_text = [""]

    def update_system_info():
        import tkinter as tk
        try:
            from app import app_state
            shutting_down = getattr(app_state, "is_shutting_down", False)
        except Exception:
            shutting_down = False

        if shutting_down or not text_widget.winfo_exists():
            return

        try:
            if not scrollbar.winfo_exists():
                text_widget.configure(yscrollcommand=None)
        except tk.TclError:
            return

        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{V.APP_NAME} {V.VERSION}\n"
            f"Build Date : {V.BUILD_DATE}\n"
            f"Git Commit : {V.GIT_COMMIT}\n"
            f"Maintainer : {V.AUTHOR}\n"
            f"Project    : {V.PROJECT_URL}\n"
        )

        host_block = _build_host_env_block()
        status_block = _build_status_block()

        base_info = scpi_data.get("system_info", "")
        freq_ref = scpi_data.get("freq_ref", None)
        if freq_ref:
            base_info += f"\n{'Freq. Reference' :<18}: {freq_ref}"

        docs_block = ""
        if selected_doc_text[0]:
            title = selected_doc_path[0].name if selected_doc_path[0] else "(doc)"
            docs_block = f"\n\n{'-'*60}\nDocumentation: {title}\n{'-'*60}\n{selected_doc_text[0]}"

        full_text = host_block + status_block + base_info + docs_block + meta_info

        try:
            if full_text != last_system_text[0]:
                scroll_position = text_widget.yview()
                sel_start = text_widget.index(tk.SEL_FIRST) if text_widget.tag_ranges(tk.SEL) else None
                sel_end   = text_widget.index(tk.SEL_LAST)  if text_widget.tag_ranges(tk.SEL) else None

                text_widget.config(state=tk.NORMAL)
                text_widget.delete("1.0", tk.END)
                text_widget.insert(tk.END, full_text)
                text_widget.config(state=tk.DISABLED)

                if sel_start and sel_end and text_widget.winfo_exists():
                    text_widget.tag_add(tk.SEL, sel_start, sel_end)
                text_widget.yview_moveto(scroll_position[0])

                last_system_text[0] = full_text
        except tk.TclError:
            return

        if not shutting_down and text_widget.winfo_exists():
            after_id[0] = root.after(2000, update_system_info)

    def _shutdown(*_):
        try:
            if after_id[0] is not None:
                root.after_cancel(after_id[0])
                after_id[0] = None
        except Exception:
            pass
        try:
            text_widget.configure(yscrollcommand=None)
        except Exception:
            pass

    tab_frame.bind("<Destroy>", _shutdown)
    update_system_info()
