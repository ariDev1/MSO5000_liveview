
"""
gui/noise_inspector.py — Noise Inspector tab (read-only, with presets)

Methods: PSD+CFAR, Spectrogram (persistence), MSC, Multitaper, Spectral Kurtosis,
Cepstrum, Matched Filter, AR Spectrum.

- Safe snapshot via local exclusive SCPI read (NORM), patterned after Harmonics tab.
- Analysis runs on a worker thread; UI remains responsive.
- Saves PNG/CSV into oszi_csv/noise_inspector/…
- GridSpec layout: main plot gets all height; preview row is collapsed.
- Per-method presets for quick operator setup.
"""

from __future__ import annotations

import os, csv, time, math, glob, json, queue, threading, datetime as _dt
import tkinter as tk
from tkinter import ttk

import numpy as np

from collections import deque

from utils.debug import log_debug
from scpi.interface import scpi_lock, safe_query
import app.app_state as app_state

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import EngFormatter


# -------------------- SCPI waveform fetch (exclusive, NORM) --------------------
def _fetch_waveform_local_exclusive(scope, chan_name: str, raw: bool = False):
    """Exclusive read under scpi_lock; defaults to NORM for responsiveness.
       Returns (t[s], y[SI], fs[Hz])."""
    import time as _time
    import numpy as _np
    raw_bytes = _np.array([], dtype=_np.uint8)
    with scpi_lock:
        try:
            app_state.is_scpi_busy = True
        except Exception:
            pass

        old_timeout = getattr(scope, "timeout", None)
        old_chunk   = getattr(scope, "chunk_size", None)
        was_running = False

        try:
            trig = safe_query(scope, ":TRIG:STAT?", "").strip().upper()
            was_running = ("STOP" not in trig)

            scope.write(f":WAV:SOUR {chan_name}")
            scope.write(":WAV:FORM BYTE")
            if raw:
                scope.write(":WAV:MODE RAW")
                try:
                    scope.write(":WAV:POIN:MODE RAW")
                    scope.write(":WAV:POIN 25000000")
                except Exception:
                    pass
            else:
                scope.write(":WAV:MODE NORM")
                try:
                    from config import WAV_POINTS
                    scope.write(f":WAV:POIN {int(WAV_POINTS)}")
                except Exception:
                    pass

            # Double-read preamble
            scope.query(":WAV:PRE?"); _time.sleep(0.08)
            pre = scope.query(":WAV:PRE?").strip().split(",")
            xinc  = float(pre[4]); xorig = float(pre[5])
            yinc  = float(pre[7]); yorig = float(pre[8]); yref = float(pre[9])

            scope.write(":STOP")
            try:
                if old_timeout is None or old_timeout < 180000:
                    scope.timeout = 180000
            except Exception: pass
            try:
                if hasattr(scope, "chunk_size"):
                    if old_chunk is None or old_chunk < 8*1024*1024:
                        scope.chunk_size = 8*1024*1024
            except Exception: pass

            t0 = _time.time()
            import numpy as _np
            raw_bytes = scope.query_binary_values(":WAV:DATA?", datatype="B", container=_np.array)
            elapsed = _time.time() - t0
            log_debug(f"[Noise] :WAV:DATA? {chan_name} took {elapsed:.2f}s, N={raw_bytes.size}")

        finally:
            try:
                if old_timeout is not None: scope.timeout = old_timeout
            except Exception: pass
            try:
                if old_chunk is not None and hasattr(scope, "chunk_size"):
                    scope.chunk_size = old_chunk
            except Exception: pass
            try:
                scope.write(":RUN" if was_running else ":STOP")
            except Exception: pass
            try:
                app_state.is_scpi_busy = False
            except Exception: pass

    if raw_bytes.size == 0:
        raise RuntimeError("Empty waveform")

    t = xorig + np.arange(raw_bytes.size) * xinc
    y = (raw_bytes - yref) * yinc + yorig
    fs = 1.0 / float(xinc) if xinc > 0 else 1.0
    return t, y, fs


def _fetch_multi_waveform_exclusive(scope, chan_pair: tuple[str, str]):
    """Fetch two channels under one exclusive window. Returns ((tA,yA,FsA),(tB,yB,FsB))."""
    t1, y1, fs1 = _fetch_waveform_local_exclusive(scope, chan_pair[0], raw=False)
    t2, y2, fs2 = _fetch_waveform_local_exclusive(scope, chan_pair[1], raw=False)
    return (t1, y1, fs1), (t2, y2, fs2)


# -------------------------------- GUI class -----------------------------------
class NoiseInspectorTab:
    def __init__(self, parent, root):
        self.frame = parent
        self.root = root
        self.scope = getattr(app_state, "scope", None)

        # Worker infra
        self._q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

        self.auto_flag = False  # Auto re-run like Harmonics

        # Plot colors
        self._col_curve   = "#6fa8dc"  # main curve
        self._col_detect  = "#ffcc33"  # detection lines
        self._col_select  = "#ff6666"  # selection marker

        # Persistence trail for heatmap-like effect (1-D methods)
        self._persist_store = {}           # key -> deque[(x, y)]
        self._persist_max = 12             # number of past curves to show
        self._persist_key = None           # last key to reset on method/chan change

        # --- Bicoherence state ---
        self._bacc = None  # persistent accumulator when "accumulate" enabled
        self.bico_accum = tk.BooleanVar(value=True)
        self.bico_vmax  = tk.DoubleVar(value=1.0)  # color bar max (0..1)

        # State
        self._last_result = None  # for saving with params



        # ---- Per-method presets ----
        self._presets = {
            "PSD+CFAR": {
                "Default": {"nfft": 4096, "seglen": 4096, "overlap": 0.5, "pfa": 1e-3, "smooth_bins": 31},
                "Fast scan": {"nfft": 2048, "seglen": 2048, "overlap": 0.25, "pfa": 1e-3, "smooth_bins": 31},
                "High resolution": {"nfft": 16384, "seglen": 16384, "overlap": 0.75, "pfa": 1e-3, "smooth_bins": 41},
                "Low false alarm": {"pfa": 1e-4, "smooth_bins": 41}
            },
            "Spectrogram": {
                "Default": {"nfft": 4096, "hop": 2048, "pfa": 1e-3, "smooth_bins": 31, "topk": 8},
                "Fast scan": {"nfft": 2048, "hop": 1024, "pfa": 1e-3, "smooth_bins": 21, "topk": 6},
                "High resolution": {"nfft": 8192, "hop": 2048, "pfa": 1e-3, "smooth_bins": 41, "topk": 10}
            },
            "MSC": {
                "Default": {"nfft": 4096, "seglen": 512, "overlap": 0.5, "msc_thr": 0.5},
                "Deep": {"nfft": 8192, "seglen": 1024, "overlap": 0.75, "msc_thr": 0.6},
                "Fast scan": {"nfft": 2048, "seglen": 256, "overlap": 0.25, "msc_thr": 0.5}
            },
            "Multitaper": {
                "Default": {"k_tapers": 6, "nfft": 4096, "seglen": 4096, "overlap": 0.5, "pfa": 1e-3, "smooth_bins": 31},
                "High resolution": {"k_tapers": 8, "nfft": 8192, "seglen": 8192, "overlap": 0.75, "pfa": 1e-3, "smooth_bins": 41},
                "Fast scan": {"k_tapers": 4, "nfft": 2048, "seglen": 2048, "overlap": 0.25, "pfa": 1e-3, "smooth_bins": 31}
            },
            "Spectral Kurtosis": {
                "Default": {"nfft": 4096, "hop": 2048, "sk_thr": 2.5},
                "Transient hunt": {"nfft": 4096, "hop": 1024, "sk_thr": 2.0},
                "Strict": {"nfft": 4096, "hop": 2048, "sk_thr": 3.5}
            },
            "Cepstrum": {
                "Default": {"nfft": 4096, "qmin_ms": 0.02, "qmax_ms": 5.0, "topk": 3},
                "Low rate": {"nfft": 4096, "qmin_ms": 1.0, "qmax_ms": 50.0, "topk": 3},
                "Wide search": {"nfft": 8192, "qmin_ms": 0.02, "qmax_ms": 50.0, "topk": 5}
            },
            "Matched Filter": {"Default": {}},
            "AR Spectrum": {
                "Default": {"ar_order": 32, "nfft": 4096},
                "Sharp peaks": {"ar_order": 64, "nfft": 8192},
                "Fast scan": {"ar_order": 24, "nfft": 2048}
            },
            "Cyclostationary": {
                "Default": {"nfft": 4096, "hop": 2048, "alpha_max": 5000.0},
                "Deep":    {"nfft": 8192, "hop": 2048, "alpha_max": 10000.0},
                "Fast":    {"nfft": 2048, "hop": 1024, "alpha_max": 3000.0}
            },
            "Bicoherence": {
                "Default": {"nfft": 512, "seglen": 512, "overlap": 0.75},
                "Fast": {"nfft": 256, "seglen": 256, "overlap": 0.5}
            }
        }

        self.auto_interval_s = tk.DoubleVar(value=2.0)   # seconds
        self.lock_to_len      = tk.BooleanVar(value=False)
        self.auto_log_csv     = tk.BooleanVar(value=True)
        self.auto_log_only_hits = tk.BooleanVar(value=True)
        
        self._build_ui()
        self.root.after(100, self._poll_results)
    # -- UI --
    def _build_ui(self):
        # Top control row
        top = ttk.Frame(self.frame); top.pack(side="top", fill="x", padx=6, pady=(6,4))
        self.ch_var = tk.StringVar(value="CHAN1")
        self.method = tk.StringVar(value="PSD+CFAR")
        self.len_s = tk.StringVar(value="1")
        self.csv_path = tk.StringVar(value="")  # used when Length = From CSV

        ttk.Label(top, text="Channel(s)").pack(side="left")
        chan_values = ["CHAN1","CHAN2","CHAN3","CHAN4",
                       "CHAN1&CHAN2","CHAN1&CHAN3","CHAN1&CHAN4",
                       "CHAN2&CHAN3","CHAN2&CHAN4","CHAN3&CHAN4"]
        ttk.Combobox(top, textvariable=self.ch_var, values=chan_values,
                     width=12, state="readonly").pack(side="left", padx=4)

        ttk.Label(top, text="Method").pack(side="left", padx=(8,0))
        ttk.Combobox(top, textvariable=self.method,
                     values=["PSD+CFAR","Spectrogram","MSC","Multitaper","Spectral Kurtosis","Cepstrum","Matched Filter","AR Spectrum","Cyclostationary","Bicoherence"],
                     width=12, state="readonly").pack(side="left", padx=4)

        ttk.Label(top, text="Preset").pack(side="left", padx=(8,0))
        self.preset = tk.StringVar(value="Default")
        self.preset_box = ttk.Combobox(top, textvariable=self.preset, values=["Default"], width=14, state="readonly")
        self.preset_box.pack(side="left", padx=4)

        ttk.Label(top, text="Length [s]").pack(side="left", padx=(8,0))
        ttk.Combobox(top, textvariable=self.len_s,
                     values=["0.5","1","2","5","From CSV"], width=10,
                     state="readonly").pack(side="left", padx=4)

        self.analyze_btn = ttk.Button(top, text="Analyze", command=self._on_analyze)
        self.analyze_btn.pack(side="left", padx=8)
        
        self.auto_btn = ttk.Button(top, text="Auto: OFF", style="Action.TButton", command=self.toggle_auto)
        self.auto_btn.pack(side="left", padx=4)
        self.log_chk = ttk.Checkbutton(top, text="Auto Log CSV", variable=self.auto_log_csv, style="Dark.TCheckbutton")
        self.log_hits_chk = ttk.Checkbutton(top, text="Only on detections", variable=self.auto_log_only_hits, style="Dark.TCheckbutton")
        self.log_chk.pack(side="left", padx=(8,0))
        self.log_hits_chk.pack(side="left", padx=(6,0))

        self.status = ttk.Label(top, text="", width=64)
        self.status.pack(side="left", padx=8)

        # CSV row (used for From CSV and Matched Filter template path)
        self.csv_row = ttk.Frame(self.frame); self.csv_row.pack_forget()
        self.csv_label = ttk.Label(self.csv_row, text="CSV Path"); self.csv_label.pack(side="left", padx=(6,4))
        self.csv_entry = ttk.Entry(self.csv_row, textvariable=self.csv_path, width=60); self.csv_entry.pack(side="left", padx=4)
        self.csv_hint = ttk.Label(self.csv_row, text="(leave empty → auto-pick latest in oszi_csv/)"); self.csv_hint.pack(side="left", padx=4)

        def _on_len_change(*_):
            # Show when analyzing from CSV or when Matched Filter needs a template path
            if self.len_s.get() == "From CSV" or self.method.get() == "Matched Filter":
                self.csv_row.pack(side="top", fill="x", padx=6, pady=(0,6))
            else:
                self.csv_row.pack_forget()
            self._context_reset("length changed")

        def _on_method_change(*_):
            # Switch label when Matched Filter is selected
            if self.method.get() == "Matched Filter":
                self.csv_label.configure(text="Template Path")
                self.csv_row.pack(side="top", fill="x", padx=6, pady=(0,6))
            else:
                self.csv_label.configure(text="CSV Path")
                if self.len_s.get() == "From CSV":
                    self.csv_row.pack(side="top", fill="x", padx=6, pady=(0,6))
                else:
                    self.csv_row.pack_forget()
            # Refresh presets for the new method
            self._refresh_preset_choices()
            self._bacc = None  # reset any running bicoherence accumulator on method change
            self._context_reset("length changed")

        self.len_s.trace_add("write", _on_len_change)
        self.method.trace_add("write", _on_method_change)
        self.ch_var.trace_add("write",  lambda *_: self._context_reset("channel changed"))

        def _on_preset_change(*_):
            self._apply_preset(self.method.get(), self.preset.get())
            self._context_reset("preset changed")

        self.preset.trace_add("write", _on_preset_change)


        # Advanced panel
        self.adv_open = tk.BooleanVar(value=False)
        self.adv = ttk.Frame(self.frame); self.adv.pack_forget()

        # Advanced variables
        self.nfft = tk.IntVar(value=4096)
        self.seglen = tk.IntVar(value=4096)
        self.overlap = tk.DoubleVar(value=0.5)
        self.pfa = tk.DoubleVar(value=1e-3)
        self.smooth_bins = tk.IntVar(value=31)
        self.topk = tk.IntVar(value=8)
        self.msc_thr = tk.DoubleVar(value=0.5)
        self.hop = tk.IntVar(value=2048)  # STFT hop
        self.k_tapers = tk.IntVar(value=6)
        self.sk_thr = tk.DoubleVar(value=2.5)
        self.qmin_ms = tk.DoubleVar(value=0.02)
        self.qmax_ms = tk.DoubleVar(value=5.0)
        self.ar_order = tk.IntVar(value=32)
        self.alpha_max = tk.DoubleVar(value=5000.0)   # Hz
        self.db_floor  = tk.DoubleVar(value=-40.0)    # dB floor for image display

        row1 = ttk.Frame(self.adv); row1.pack(side="top", fill="x", padx=6, pady=2)
        for label, var, w in [("NFFT", self.nfft, 8),
                              ("SegLen", self.seglen, 8),
                              ("Overlap", self.overlap, 8),
                              ("Pfa", self.pfa, 10),
                              ("SmoothBins", self.smooth_bins, 10),
                              ("TopK", self.topk, 6)]:
            ttk.Label(row1, text=label).pack(side="left", padx=(0,4))
            ttk.Entry(row1, textvariable=var, width=w).pack(side="left", padx=(0,8))

        row2 = ttk.Frame(self.adv); row2.pack(side="top", fill="x", padx=6, pady=2)
        ttk.Label(row2, text="MSC_thr").pack(side="left", padx=(0,4))
        ttk.Entry(row2, textvariable=self.msc_thr, width=8).pack(side="left", padx=(0,8))
        ttk.Label(row2, text="Hop (Spectrogram)").pack(side="left", padx=(0,4))
        ttk.Entry(row2, textvariable=self.hop, width=10).pack(side="left", padx=(0,8))

        row3 = ttk.Frame(self.adv); row3.pack(side="top", fill="x", padx=6, pady=2)
        for label, var, w in [("K_tapers", self.k_tapers, 8), ("SK_thr", self.sk_thr, 8),
                              ("qmin_ms", self.qmin_ms, 8), ("qmax_ms", self.qmax_ms, 8),
                              ("AR_order", self.ar_order, 8)]:
            ttk.Label(row3, text=label).pack(side="left", padx=(0,4))
            ttk.Entry(row3, textvariable=var, width=w).pack(side="left", padx=(0,8))

        ttk.Label(row3, text="α_max (Hz)").pack(side="left", padx=(0,4))
        ttk.Entry(row3, textvariable=self.alpha_max, width=10).pack(side="left", padx=(0,8))
        ttk.Label(row3, text="dB_floor").pack(side="left", padx=(0,4))
        ttk.Entry(row3, textvariable=self.db_floor, width=8).pack(side="left", padx=(0,8))

        # --- Bicoherence controls (appear in Advanced panel) ---
        row_bico = ttk.Frame(self.adv); row_bico.pack(side="top", fill="x", padx=6, pady=2)
        ttk.Checkbutton(row_bico, text="Bico: accumulate across runs",
                        variable=self.bico_accum, style="Dark.TCheckbutton").pack(side="left", padx=(0,10))
        ttk.Label(row_bico, text="Bico vmax").pack(side="left", padx=(0,4))
        ttk.Entry(row_bico, textvariable=self.bico_vmax, width=6).pack(side="left", padx=(0,10))
        ttk.Button(row_bico, text="Clear Bico", command=self._clear_bico).pack(side="left", padx=(0,10))

        # Matplotlib figure with GridSpec
        fig = Figure(figsize=(5, 4.8), dpi=100)
        self.gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 0.0001], hspace=0.06)
        self.ax_main = fig.add_subplot(self.gs[0])
        self.ax_prev = fig.add_subplot(self.gs[1])
        for ax in (self.ax_main, self.ax_prev):
            ax.set_facecolor("#1a1a1a"); fig.patch.set_facecolor("#1a1a1a")
            for s in ax.spines.values(): s.set_color("#cccccc")
            ax.tick_params(axis="both", colors="white")
            ax.xaxis.label.set_color("white"); ax.yaxis.label.set_color("white"); ax.title.set_color("white")
        self.ax_prev.set_visible(False)

        self.canvas = FigureCanvasTkAgg(fig, master=self.frame)
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True, padx=0, pady=(0,0))

        # Results table — Harmonics-like style
        self.headers = {
            "PSD+CFAR": ("Type","f0_Hz","SNR_dB","BW_Hz","Notes"),
            "Spectrogram": ("Type","f0_Hz","Occup_%","BW_Hz","Notes"),
            "MSC": ("Type","f0_Hz","MSC","BW_Hz","Notes"),
            "Multitaper": ("Type","f0_Hz","SNR_dB","BW_Hz","Notes"),
            "Spectral Kurtosis": ("Type","f0_Hz","SK","BW_Hz","Notes"),
            "Cepstrum": ("Type","f0_Hz","SNR_dB","BW_Hz","Notes"),
            "Matched Filter": ("Type","f0_Hz","SNR_dB","BW_Hz","Notes"),
            "AR Spectrum": ("Type","f0_Hz","SNR_dB","BW_Hz","Notes"),
            "Cyclostationary": ("Type","f0_Hz","α_Hz","SCD_dB","BW_Hz","Notes"),
            "Bicoherence": ("Type","f1_Hz","f2_Hz","b2","Notes"),
        }
        init_cols = self.headers.get(self.method.get(), self.headers["PSD+CFAR"])
        self.table = ttk.Treeview(self.frame, columns=init_cols, show="headings", height=5)

        _style = ttk.Style(self.frame)
        _style.configure("Dark.Treeview",
                         background="#111111", fieldbackground="#111111",
                         foreground="#DDDDDD", bordercolor="#333333",
                         rowheight=22)
        _style.map("Dark.Treeview",
                   background=[("selected", "#2a72b5")],
                   foreground=[("selected", "#ffffff")])
        _style.configure("Dark.Treeview.Heading",
                         background="#222222", foreground="#DDDDDD",
                         relief="flat")
        self.table.configure(style="Dark.Treeview")

        widths  = {"Type":80, "f0_Hz":120, "SNR_dB":90, "Occup_%":90, "MSC":90, "SK":90, "BW_Hz":100, "Notes":300}
        anchors = {"Type":"w", "Notes":"w"}
        for c in init_cols:
            self.table.heading(c, text=c, anchor=("w" if c in ("Type","Notes") else "e"))
            self.table.column(c, width=widths.get(c, 100), anchor=anchors.get(c, "e"), stretch=(c=="Notes"))
        self.table.pack(side="top", fill="x", padx=6, pady=(0,6))
        self.table.bind("<<TreeviewSelect>>", self._on_row_select)

        # Bottom buttons + Advanced toggle
        self.btns = ttk.Frame(self.frame); self.btns.pack(side="top", fill="x", padx=6, pady=(0,8))
        ttk.Button(self.btns, text="Save CSV", command=self._save_csv).pack(side="left", padx=4)
        ttk.Button(self.btns, text="Save PNG", command=self._save_png).pack(side="left", padx=4)
        ttk.Button(self.btns, text="⭮ Clear", command=lambda: self._context_reset("manual clear")).pack(side="left", padx=6)
        ttk.Button(self.btns, text="🧊 3D Surface", command=self._open_surface3d).pack(side="left", padx=6)
        self.adv_btn = ttk.Button(self.btns, text="Advanced ▾", style="Action.TButton", command=self._toggle_advanced)
        self.adv_btn.pack(side="left", padx=8)

        self._eng = EngFormatter(unit="Hz")

        # Initialize Preset list for current method and apply Default
        self._refresh_preset_choices()
        self.preset.trace_add("write", _on_preset_change)

    def _refresh_preset_choices(self):
        m = self.method.get()
        presets = list(self._presets.get(m, {"Default": {}}).keys())
        presets = ["Default"] + [p for p in presets if p != "Default"]
        self.preset_box["values"] = presets
        self.preset.set("Default")

    def _apply_preset(self, method: str, name: str):
        params = self._presets.get(method, {}).get(name, {})
        if not params:
            return
        var_map = {
            "nfft": self.nfft, "seglen": self.seglen, "overlap": self.overlap,
            "pfa": self.pfa, "smooth_bins": self.smooth_bins, "topk": self.topk,
            "msc_thr": self.msc_thr, "hop": self.hop, "k_tapers": self.k_tapers,
            "sk_thr": self.sk_thr, "qmin_ms": self.qmin_ms, "qmax_ms": self.qmax_ms,
            "ar_order": self.ar_order,
            "alpha_max": self.alpha_max,   # <-- add
            "db_floor": self.db_floor      # <-- add
        }
        for k, v in params.items():
            if k in var_map:
                try: var_map[k].set(v)
                except Exception: pass
        self.status.config(text=f"{method} preset: {name}")

    def _clear_bico(self):
        self._bacc = None
        try: self.status.config(text="Bicoherence accumulator cleared")
        except Exception: pass

    def _toggle_advanced(self):
        new_state = not self.adv_open.get()
        self.adv_open.set(new_state)
        if new_state:
            try: self.adv.pack_forget()
            except Exception: pass
            self.adv.pack(side="top", fill="x", padx=6, pady=(0,6))
            try: self.adv_btn.config(text="Advanced ▴")
            except Exception: pass
        else:
            self.adv.pack_forget()
            try: self.adv_btn.config(text="Advanced ▾")
            except Exception: pass

    def _open_surface3d(self):
        """Open (or focus) the shared 3D surface window."""
        try:
            from gui.surface3d import ensure_surface3d
            ensure_surface3d(self.root)
            self.status.config(text="3D Surface ready")
        except Exception as e:
            self.status.config(text="3D Surface not available (gui/surface3d.py missing).")
            try:
                from utils.debug import log_debug
                log_debug(f"[Noise] 3D Surface unavailable: {e}")
            except Exception:
                pass

    # -- Auto mode (like Harmonics) --
    def toggle_auto(self):
        self.auto_flag = not self.auto_flag
        try:
            self.auto_btn.config(text=f"Auto: {'ON' if self.auto_flag else 'OFF'}")
        except Exception:
            pass
        # Kick off immediately if idle and not From CSV
        if self.auto_flag and self.len_s.get() != "From CSV":
            if not (self._worker and self._worker.is_alive()):
                self._on_analyze()

    def _auto_rearm(self, delay_ms: int = 2000):
        # Schedule another run if Auto is ON, we are idle, and not in From CSV mode
        if self.auto_flag and self.len_s.get() != "From CSV":
            if not (self._worker and self._worker.is_alive()):
                try:
                    self.root.after(delay_ms, self._on_analyze)
                except Exception:
                    pass

    def _context_reset(self, reason: str = ""):
        """Hard reset of the Noise Inspector *UI state only*.
        Does not touch any files or scope settings."""
        # 1) Pause Auto temporarily
        was_auto = bool(getattr(self, "auto_flag", False))
        self.auto_flag = False
        try: self.auto_btn.config(text="Auto: OFF")
        except Exception: pass

        # 2) Ask running worker to stop and wait briefly
        try:
            if self._worker and self._worker.is_alive():
                self._stop.set()
                self.status.config(text=f"Reset ({reason}) — waiting for worker…")
                self._worker.join(timeout=1.2)  # don't block GUI
        except Exception:
            pass

        # 3) Drain result queue (old payloads no longer valid)
        import queue as _q
        try:
            while True:
                self._q.get_nowait()
        except _q.Empty:
            pass

        # 4) Reset per-method accumulators/persistence
        self._bacc = None
        try:
            self._persist_store.clear()
            self._persist_key = None
        except Exception:
            # present in this file already; ignore if not yet created
            pass
        self._last_result = None

        # 5) Clear table
        try:
            for item in self.table.get_children():
                self.table.delete(item)
        except Exception:
            pass

        # 6) Clear the plots and redraw in dark theme
        for ax in (self.ax_main, self.ax_prev):
            try:
                ax.clear()
                # hard reset so image/aspect state from Bicoherence cannot leak
                ax.set_aspect("auto", adjustable="box")
                ax.images.clear()
                ax.set_xlim(auto=True); ax.set_ylim(auto=True)
                ax.autoscale(enable=True)

                ax.set_facecolor("#1a1a1a")
                for s in ax.spines.values(): s.set_color("#cccccc")
                ax.tick_params(axis="both", colors="white")
                ax.xaxis.label.set_color("white")
                ax.yaxis.label.set_color("white")
                ax.title.set_color("white")
            except Exception:
                pass

        try:
            self.ax_prev.set_visible(False)
            self.canvas.draw_idle()
        except Exception:
            pass

        self._set_running(False)
        try: self.status.config(text=f"Reset done ({reason}).")
        except Exception: pass

        # 7) Restore Auto if it was on and we are not in CSV mode
        if was_auto and self.len_s.get() != "From CSV":
            self.auto_flag = True
            try: self.auto_btn.config(text="Auto: ON")
            except Exception: pass
            # start a fresh run with the new context
            try: self.root.after(80, self._on_analyze)
            except Exception: pass

    # -- Run / Stop --
    def _set_running(self, running: bool):
        for widget in (self.analyze_btn,):
            widget.config(text="Stop" if running else "Analyze")
        for child in self.frame.winfo_children():
            if isinstance(child, ttk.Frame):
                for w in child.winfo_children():
                    if isinstance(w, (ttk.Combobox, ttk.Entry, ttk.Button)) and w not in (
                        self.analyze_btn, getattr(self, 'auto_btn', None),
                        getattr(self, 'auto_spin', None), getattr(self, 'lock_chk', None),
                        getattr(self, 'log_chk', None), getattr(self, 'log_hits_chk', None)
                    ):
                        try:
                            if isinstance(w, ttk.Combobox):
                                w.config(state="disabled" if running else "readonly")
                            elif isinstance(w, ttk.Entry) or isinstance(w, ttk.Button):
                                w.config(state="disabled" if running else "normal")
                        except Exception:
                            pass

    def _on_analyze(self):
        if self._worker and self._worker.is_alive():
            self._stop.set(); self.status.config(text="Stopping…"); return
        self._stop.clear(); self._set_running(True)
        ch = self.ch_var.get(); method = self.method.get(); length_s = self.len_s.get()
        try:
            length = float(length_s) if length_s != "From CSV" else float("nan")
        except Exception:
            length = 1.0
        args = (ch, method, length, self.csv_path.get())
        self._worker = threading.Thread(target=self._worker_run, args=args, daemon=True)
        self._worker.start()

    # -- Worker --
    def _worker_run(self, ch: str, method: str, length: float, csv_path: str):
        try:
            t0 = time.time()
            scope = getattr(app_state, "scope", None)

            # Initialize optional B-channel holders
            yB = None; fsB = None; metaB = None

            # Acquire
            if math.isnan(length):  # From CSV
                yA, fsA, metaA = self._load_csv_for_channel(ch.split("&")[0], csv_path)
                if "&" in ch:
                    yB, fsB, metaB = self._load_csv_for_channel(ch.split("&")[1], csv_path)
                    if abs(fsA - fsB) / max(fsA, fsB) > 1e-6:
                        raise RuntimeError("CSV Fs mismatch for channel pair")
            else:
                if scope is None:
                    raise RuntimeError("Scope not connected")
                if "&" in ch:
                    A, B = ch.split("&", 1)
                    (tA, yA, fsA), (tB, yB, fsB) = _fetch_multi_waveform_exclusive(scope, (A, B))
                else:
                    tA, yA, fsA = _fetch_waveform_local_exclusive(scope, ch, raw=False)
                if length > 0:
                    NA = int(min(yA.size, max(128, round(length * fsA)))); yA = yA[-NA:]
                    if yB is not None:
                        NB = int(min(yB.size, max(128, round(length * fsB)))); yB = yB[-NB:]

            if self._stop.is_set(): raise RuntimeError("Analysis stopped by user")

            params = {
                "nfft": int(self.nfft.get()),
                "seglen": int(self.seglen.get()),
                "overlap": float(self.overlap.get()),
                "pfa": float(self.pfa.get()),
                "smooth_bins": int(self.smooth_bins.get()),
                "topk": int(self.topk.get()),
                "msc_thr": float(self.msc_thr.get()),
                "hop": int(self.hop.get()),
                "k_tapers": int(self.k_tapers.get()),
                "sk_thr": float(self.sk_thr.get()),
                "qmin_ms": float(self.qmin_ms.get()),
                "qmax_ms": float(self.qmax_ms.get()),
                "ar_order": int(self.ar_order.get()),
            }

            if method == "PSD+CFAR":
                from gui.noise.psd_cfar import run_psd_cfar
                r = run_psd_cfar(yA, fsA, stop_event=self._stop,
                                 nfft=params["nfft"], seglen=params["seglen"],
                                 overlap=params["overlap"], pfa=params["pfa"],
                                 smooth_bins=params["smooth_bins"])
            elif method == "Spectrogram":
                from gui.noise.spectrogram import run_spectro
                r = run_spectro(yA, fsA, stop_event=self._stop,
                                nfft=params["nfft"], hop=params["hop"],
                                pfa=params["pfa"], smooth_bins=params["smooth_bins"],
                                topk=params["topk"])
            elif method == "MSC":
                if yB is None:
                    raise RuntimeError("MSC requires a channel pair like CHAN1&CHAN2")
                from gui.noise.coherence import run_msc
                r = run_msc(yA, yB, fsA, stop_event=self._stop,
                            nfft=params["nfft"], seglen=params["seglen"],
                            overlap=params["overlap"], thr=params["msc_thr"])
            elif method == "Multitaper":
                from gui.noise.multitaper import run_multitaper
                r = run_multitaper(yA, fsA, stop_event=self._stop,
                                   K=params["k_tapers"], nfft=params["nfft"],
                                   seglen=params["seglen"], overlap=params["overlap"],
                                   pfa=params["pfa"], smooth_bins=params["smooth_bins"])
            elif method == "Spectral Kurtosis":
                from gui.noise.kurtosis import run_spectral_kurtosis
                r = run_spectral_kurtosis(yA, fsA, stop_event=self._stop,
                                          nfft=params["nfft"], hop=params["hop"],
                                          sk_thr=params["sk_thr"])
            elif method == "Cepstrum":
                from gui.noise.cepstrum import run_cepstrum
                r = run_cepstrum(yA, fsA, stop_event=self._stop,
                                  nfft=params["nfft"], qmin_ms=params["qmin_ms"],
                                  qmax_ms=params["qmax_ms"], topk=params["topk"])
            elif method == "Matched Filter":
                from gui.noise.matched import run_matched_filter
                r = run_matched_filter(yA, fsA, template_path=csv_path, stop_event=self._stop)
            elif method == "AR Spectrum":
                from gui.noise.ar_spectrum import run_ar_spectrum
                r = run_ar_spectrum(yA, fsA, order=params["ar_order"], nfft=params["nfft"], stop_event=self._stop)
            elif method == "Cyclostationary":
                from gui.noise.cyclo import run_cyclo
                r = run_cyclo(yA, fsA, stop_event=self._stop,
                              nfft=int(self.nfft.get()),
                              hop=int(self.hop.get()),
                              alpha_max=float(self.alpha_max.get()),
                              db_floor=float(self.db_floor.get()),
                              normalize=True)

            elif method == "Bicoherence":
                # Lazy import: keine harte Abhängigkeit
                from gui.noise.cyclo_bispec import BicoherenceAccumulator
                import numpy as np

                n_avail = len(yA)
                nfft_req = int(self.nfft.get())

                # NFFT an vorhandene Punkte anpassen (power-of-two, min. 128)
                if n_avail < nfft_req:
                    nfft = 1 << int(np.floor(np.log2(max(128, n_avail))))
                    if nfft > n_avail:
                        nfft = max(32, n_avail)  # Sicherheitsnetz
                else:
                    nfft = nfft_req

                noverlap = int(max(0, min(0.95, float(self.overlap.get()))) * nfft)
                adj_note = "" if nfft == nfft_req else f" (NFFT→{nfft} due to {n_avail} pts)"

                # persistent vs one-shot
                if self.bico_accum.get():
                    acc = self._bacc
                    if (acc is None) or (acc.nfft != nfft) or (acc.noverlap != noverlap):
                        acc = BicoherenceAccumulator(nfft=nfft, noverlap=noverlap, window="hann", demean=True)
                        self._bacc = acc
                else:
                    acc = BicoherenceAccumulator(nfft=nfft, noverlap=noverlap, window="hann", demean=True)

                # Update + Heatmap
                acc.update(yA, fsA)
                f, _B, b2 = acc.results()

                # -------- Peak-Picker (Top-K) für Tabelle/CSV --------
                try:
                    K = int(self.topk.get())
                except Exception:
                    K = 8

                det_rows = []
                b2_work = b2.copy()
                if b2_work.size:
                    # DC + Ränder unterdrücken
                    b2_work[0, :] = 0; b2_work[:, 0] = 0
                    b2_work[-1, :] = 0; b2_work[:, -1] = 0

                    b2_max = float(np.nanmax(b2_work)) if np.isfinite(np.nanmax(b2_work)) else 0.0
                    thr = max(0.2, 0.5 * b2_max)

                    try:
                        from scipy.ndimage import maximum_filter
                        locmax = (b2_work == maximum_filter(b2_work, size=3, mode="nearest")) & (b2_work >= thr)
                        ii, jj = np.nonzero(locmax)
                        vals = b2_work[ii, jj]
                        if vals.size > 0:
                            order = np.argsort(vals)[::-1][:K]
                            ii, jj, vals = ii[order], jj[order], vals[order]
                            for i, j, v in zip(ii, jj, vals):
                                det_rows.append({
                                    "type": "b2-peak",
                                    "f1_Hz": float(f[j]),
                                    "f2_Hz": float(f[i]),
                                    "b2": float(v),
                                    "notes": f"f3≈{(f[j]+f[i]):.1f} Hz"
                                })
                    except Exception:
                        # Fallback ohne SciPy: global Top-K
                        flat = b2_work.ravel()
                        if flat.size > 0:
                            idx = np.argpartition(flat, -K)[-K:]
                            order = np.argsort(flat[idx])[::-1]
                            ii, jj = np.unravel_index(idx[order], b2_work.shape)
                            for i, j in zip(ii, jj):
                                v = float(b2_work[i, j])
                                if v <= 0: 
                                    continue
                                det_rows.append({
                                    "type": "b2-peak",
                                    "f1_Hz": float(f[j]),
                                    "f2_Hz": float(f[i]),
                                    "b2": v,
                                    "notes": f"f3≈{(f[j]+f[i]):.1f} Hz"
                                })

                # Result-Payload (mit Detections!)
                r = {
                    "method": "Bicoherence",
                    "image": b2,
                    "extent": [f[0], f[-1], f[0], f[-1]],
                    "xlabel": "f1 (Hz)",
                    "ylabel": "f2 (Hz)",
                    "title": "Bicoherence" + adj_note,
                    "vmin": 0.0,
                    "vmax": float(self.bico_vmax.get()),
                    "df_Hz": float(fsA) / max(1, nfft),
                    "detections": det_rows,
                    "aspect": "equal",
                    "draw_diag": True,
                    "interpolation": "nearest"
                }


            else:
                raise NotImplementedError(f"Unknown method: {method}")

            r["elapsed_s"] = time.time() - t0
            r["meta"] = {"chan": ch, "Fs": float(fsA), "N": int(len(yA)), "params": params}
            self._last_result = r
            self._q.put(("result", r))
        except Exception as e:
            self._q.put(("error", str(e)))

    # -- CSV load helper --
    def _load_csv_for_channel(self, chan: str, path_hint: str):
        import pandas as pd
        path = (path_hint or "").strip()
        if path and os.path.exists(path):
            df = pd.read_csv(path)
        else:
            candidates = sorted(glob.glob(os.path.join("oszi_csv", f"{chan}_*.csv")))
            if not candidates:
                raise RuntimeError(f"No CSV files found for {chan} under oszi_csv/")
            df = pd.read_csv(candidates[-1])

        if "t" in df.columns and "y" in df.columns:
            t = df["t"].to_numpy()
            y = df["y"].to_numpy(dtype=float)
            fs = 1.0 / float(np.median(np.diff(t))) if len(t) > 1 else 1.0
        else:
            y = df.iloc[:, -1].to_numpy(dtype=float)
            fs = float(df.attrs.get("Fs", 1.0)) if hasattr(df, "attrs") else 1.0
        return y, fs, {"csv": True, "path": path or candidates[-1]}

    # -- Tk polling --
    def _poll_results(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "result":
                    self._show_result(payload); self._auto_log_result(payload); self._set_running(False); self._auto_rearm()
                elif kind == "error":
                    self.status.config(text=f"Error: {payload}")
                    log_debug(f"[Noise] Error: {payload}")
                    self._set_running(False); self._auto_rearm()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    # -- Rendering --
    def _show_result(self, r: dict):
        method = r.get("method","")
        ax = self.ax_main; ax2 = self.ax_prev
        for a in (ax, ax2):
            a.clear()
            a.set_aspect("auto", adjustable="box")
            a.set_xlim(auto=True); a.set_ylim(auto=True)
            a.autoscale(enable=True)
            a.set_facecolor("#1a1a1a")
            for s in a.spines.values(): s.set_color("#cccccc")
            a.tick_params(axis="both", colors="white")
            a.xaxis.label.set_color("white"); a.yaxis.label.set_color("white"); a.title.set_color("white")
            a.xaxis.set_major_formatter(self._eng)
            # Hide scientific offset texts that overlap title
            a.get_xaxis().get_offset_text().set_visible(False)
            a.get_yaxis().get_offset_text().set_visible(False)

        if "image" in r:
            img = r["image"]
            extent = r.get("extent", None)

            # Build imshow kwargs once
            imshow_kwargs = dict(origin="lower")
            if extent is not None:
                imshow_kwargs["extent"] = extent
            if r.get("interpolation") is not None:
                imshow_kwargs["interpolation"] = r["interpolation"]
            if (r.get("vmin") is not None) or (r.get("vmax") is not None):
                imshow_kwargs["vmin"] = r.get("vmin")
                imshow_kwargs["vmax"] = r.get("vmax")

            ax.imshow(img, aspect=r.get("aspect", "auto"), **imshow_kwargs)

            # Axes formatting + labels/title (always)
            ax.yaxis.set_major_formatter(self._eng)
            ax.set_ylabel(r.get("ylabel", "Frequency (Hz)"))
            ax.set_xlabel(r.get("xlabel", "Time (s)"))
            ax.set_title(r.get("title", method if method else "Spectrogram"), pad=6)

            # Optional visual cue for triangular domains (e.g., bicoherence)
            if r.get("draw_diag") and extent is not None:
                xmin, xmax, ymin, ymax = extent
                ax.plot([xmin, xmax], [ymax, ymin], linestyle="--", linewidth=0.8, color="#666666")

        else:
            x = r["plot_x"]; y = r["plot_y"]
            # Build a key per method+channel so trails reset when context changes
            key = f"{method}|{r.get('meta', {}).get('chan','')}"
            # Reset trail when method/chan changes
            if key != self._persist_key:
                self._persist_key = key
                self._persist_store[key] = deque(maxlen=self._persist_max)

            # Only accumulate when Auto is ON (keeps single-run plots clean)
            if getattr(self, "auto_flag", False):
                self._persist_store.setdefault(key, deque(maxlen=self._persist_max)).append((np.asarray(x), np.asarray(y)))

            # Draw the trail (older → lower alpha), then draw current on top
            hist = list(self._persist_store.get(key, []))
            if len(hist) > 1:
                steps = len(hist) - 1
                for i, (xi, yi) in enumerate(hist[:-1]):  # all but newest
                    # alpha ramp ~ Harmonics style
                    alpha = 0.12 + 0.35 * ((i + 1) / steps) ** 1.5
                    self.ax_main.plot(xi, yi, linewidth=1.0, alpha=alpha, color=self._col_curve, zorder=1)

            ax.plot(x, y, linewidth=0.9, color=self._col_curve, zorder=3)
            ax.set_title(method, pad=6)
            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel("Value (dB)" if method!="MSC" else "MSC")
            for d in r.get("detections", []):
                f0 = d.get("f0_Hz")
                if f0 is not None:
                    ax.axvline(float(f0), linestyle="--", linewidth=0.8, color=self._col_detect)

        ax2.set_visible(False)
        self.gs.set_height_ratios([1.0, 0.0001])
        ax.figure.subplots_adjust(top=0.96, bottom=0.12, left=0.08, right=0.98, hspace=0.06)

        cols = self.headers.get(method, self.headers["PSD+CFAR"])
        self.table["columns"] = cols
        widths  = {"Type":80, "f0_Hz":120, "SNR_dB":90, "Occup_%":90, "MSC":90, "SK":90, "BW_Hz":100, "Notes":300}
        anchors = {"Type":"w", "Notes":"w"}
        for c in cols:
            self.table.heading(c, text=c, anchor=("w" if c in ("Type","Notes") else "e"))
            self.table.column(c, width=widths.get(c, 100), anchor=anchors.get(c, "e"), stretch=(c=="Notes"))

        for iid in self.table.get_children(): self.table.delete(iid)

        for d in r.get("detections", []):
            if method == "Bicoherence":
                row = (
                    d.get("type", "b2-peak"),
                    round(float(d.get("f1_Hz", 0.0)), 3),
                    round(float(d.get("f2_Hz", 0.0)), 3),
                    round(float(d.get("b2", 0.0)), 3),
                    d.get("notes", "")
                )
            else:
                # ← dein bisheriger Code für andere Methoden (unverändert)
                metric_keys = ("SNR_dB","Occup_%","MSC","SK","Score","Value")
                val = 0.0
                for _k in metric_keys:
                    if _k in d:
                        val = d[_k]; break
                row = (d.get("type","line"),
                       round(float(d.get("f0_Hz", 0.0)), 3),
                       round(float(val), 3),
                       round(float(d.get("BW_Hz", 0.0)), 3),
                       d.get("notes",""))

            self.table.insert("", "end", values=row)

        df = r.get("df_Hz", None)
        df_txt = f", Δf≈{self._eng.format_data(df)}" if df is not None else ""
        self.status.config(text=f"{method} — {len(r.get('detections',[]))} detections; {r.get('elapsed_s',0):.2f}s{df_txt}")
        
        # --- 3D surface streaming (visualization-only; no data alteration) ---
        try:
            from gui.surface3d import push_surface_line
        except Exception:
            push_surface_line = None

        # Only for 1-D methods (skip if an image is present) and only when Auto is ON,
        # mirroring your persistence rule to keep single-run plots clean.
        if push_surface_line and "image" not in r:
            try:
                push_surface_line(y, x=x, t=time.time())
            except Exception:
                pass


        self.canvas.draw_idle()

    def _on_row_select(self, _event=None):
        sel = self.table.selection()
        if not sel or not self._last_result: return
        r = self._last_result; method = r.get("method","")
        if method not in ("PSD+CFAR","MSC","Multitaper","AR Spectrum","Cepstrum"): return
        try:
            f0 = float(self.table.item(sel[0], "values")[1])
        except Exception:
            return
        self.ax_main.axvline(f0, linestyle="-", linewidth=1.2, color=self._col_select)
        self.canvas.draw_idle()

    # -- Saving --
    
    # -- Auto CSV logging --
    def _auto_log_result(self, r: dict):
        """Append results to a daily CSV if auto logging is enabled.
        Writes one row per detection, or a summary row when no detections (if configured).
        """
        try:
            if not self.auto_flag or not self.auto_log_csv.get():
                return
        except Exception:
            return

        dets = list(r.get("detections", []))
        try:
            if self.auto_log_only_hits.get() and len(dets) == 0:
                return
        except Exception:
            pass

        import csv, datetime as _dt, json as _json
        outdir = os.path.join("oszi_csv", "noise_inspector", "logs")
        os.makedirs(outdir, exist_ok=True)
        day = _dt.datetime.now().strftime("%Y%m%d")
        path = os.path.join(outdir, f"NI_auto_{day}.csv")

        ts = _dt.datetime.now().isoformat(timespec="seconds")
        method = r.get("method","")
        meta = r.get("meta", {})
        chan = meta.get("chan","")
        Fs = meta.get("Fs","")
        N = meta.get("N","")
        df = r.get("df_Hz", None)
        elapsed = r.get("elapsed_s", 0.0)
        params = meta.get("params", {})

        need_header = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if need_header:
                w.writerow(["timestamp","method","chan","Fs","N","df_Hz","elapsed_s","det_index","type","f0_Hz","metric","BW_Hz","notes","params_json"])
            metric_keys = ("SNR_dB","Occup_%","MSC","SK","Score","Value")
            if dets:
                for i, d in enumerate(dets):
                    val = ""
                    for k in metric_keys:
                        if k in d:
                            val = d[k]; break
                    w.writerow([ts, method, chan, Fs, N, df, f"{elapsed:.3f}", i,
                                d.get("type",""), d.get("f0_Hz",""), val, d.get("BW_Hz",""), d.get("notes",""),
                                _json.dumps(params, separators=(",",":"))])
            else:
                w.writerow([ts, method, chan, Fs, N, df, f"{elapsed:.3f}", -1, "", "", "", "", "no detections",
                            _json.dumps(params, separators=(",",":"))])
        try:
            self.status.config(text=f"Auto-logged to {path}")
        except Exception:
            pass
    def _save_png(self):
        try:
            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            outdir = os.path.join("oszi_csv", "noise_inspector")
            os.makedirs(outdir, exist_ok=True)
            path = os.path.join(outdir, f"NI_{ts}_plot.png")
            self.canvas.figure.savefig(path, dpi=150, facecolor=self.canvas.figure.get_facecolor())
            log_debug(f"[Noise] Saved plot → {path}")
            self.status.config(text=f"Saved {path}")
        except Exception as e:
            self.status.config(text=f"Save PNG error: {e}")
            log_debug(f"[Noise] Save PNG error: {e}")

    def _save_csv(self):
        try:
            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            outdir = os.path.join("oszi_csv", "noise_inspector")
            os.makedirs(outdir, exist_ok=True)
            path = os.path.join(outdir, f"NI_{ts}_results.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                if self._last_result:
                    meta = self._last_result.get("meta", {})
                    params = meta.get("params", {})
                    header = {"method": self._last_result.get("method",""),
                              "chan": meta.get("chan",""),
                              "Fs": meta.get("Fs",""),
                              "N": meta.get("N",""),
                              "params": params}
                    w.writerow([f"# {json.dumps(header)}"])
                w.writerow(self.table["columns"])
                for iid in self.table.get_children():
                    w.writerow(self.table.item(iid, "values"))
            log_debug(f"[Noise] Saved detections → {path}")
            self.status.config(text=f"Saved {path}")
        except Exception as e:
            self.status.config(text=f"Save CSV error: {e}")
            log_debug(f"[Noise] Save CSV error: {e}")


def setup_noise_inspector_tab(tab_frame, ip, root):
    view = NoiseInspectorTab(tab_frame, root)
    return view.frame
