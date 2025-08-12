
"""
harmonics_tab.py — Tkinter GUI tab for Harmonics & THD
Safe integration: no hidden scope changes; fetches via SCPI with locking and preserves RUN/STOP state.
"""
from __future__ import annotations
from typing import Optional
import csv, time, threading, math
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque

from utils.debug import log_debug
from scpi.interface import scpi_lock, safe_query
from scpi.waveform import fetch_waveform_with_fallback  # If available; we also implement a local fetch fallback
import app.app_state as app_state

from gui.harmonic.harmonics import analyze_harmonics

WINDOWS = {"Rect": "rect", "Hann": "hann", "Flat-top": "flattop"}

class HarmonicsTab:
    def __init__(self, parent: tk.Frame, ip: str, root: tk.Tk):
        self.parent = parent
        self.root = root
        self.ip = ip
        self.scope = None
        self.auto_flag = False
        self.worker = None
        self.last_capture = None  # (t, x in SI units, fs, chan_name, scale_applied)
        self._last_fetch_mode = ""
        self._last_pts = 0
        self._last_elapsed = 0.0
        self.hm_var = tk.BooleanVar(value=False)   # UI toggle
        self.spec_hist = deque(maxlen=15)          # last 15 spectra (~30 s at 2 s Auto)
        self._build_ui()

    def _shutdown(self):
        # Stop auto loop and wait briefly for the worker to exit
        self.auto_flag = False
        try:
            w = getattr(self, "worker", None)
            if w and w.is_alive():
                w.join(timeout=1.0)
        except Exception:
            pass

    # --- Dark theme helpers ---
    DARK_BG = "#111111"
    DARK_FG = "#DDDDDD"

    def _apply_dark_theme(self):
        # ttk Treeview dark style (local to this tab)
        style = ttk.Style(self.parent)
        style.configure("Dark.Treeview",
                        background=self.DARK_BG, fieldbackground=self.DARK_BG,
                        foreground=self.DARK_FG, bordercolor="#333333",
                        rowheight=22)
        style.map("Dark.Treeview",
                  background=[("selected", "#2a72b5")],
                  foreground=[("selected", "#ffffff")])
        style.configure("Dark.Treeview.Heading",
                        background="#222222", foreground=self.DARK_FG,
                        relief="flat")
        self.tree.configure(style="Dark.Treeview")
        
        # Matplotlib: figure + axes
        self.fig.patch.set_facecolor(self.DARK_BG)
        self._style_axes(self.ax)

    def _clear_persistence(self):
        self.spec_hist.clear()
        # force a redraw of just the axes styling so old lines vanish visually
        self.ax.cla()
        self._style_axes(self.ax)
        self.canvas.draw_idle()

    def _style_axes(self, ax):
        ax.set_facecolor(self.DARK_BG)
        ax.tick_params(colors=self.DARK_FG)
        ax.xaxis.label.set_color(self.DARK_FG)
        ax.yaxis.label.set_color(self.DARK_FG)
        ax.title.set_color(self.DARK_FG)
        for sp in ax.spines.values():
            sp.set_color("#444444")
        ax.grid(True, alpha=0.25, color="#666666")

    # --------- UI ----------
    def _build_ui(self):
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(3, weight=1)

        hdr = tk.Frame(self.parent, bg="#225577", padx=8, pady=8)
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 4))
        for c in range(6): hdr.columnconfigure(c, weight=1)

        tk.Label(hdr, text="Harmonics & THD (Total Harmonic Distortion)", fg="white", bg="#225577", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")

        controls = tk.Frame(self.parent, bg="#1a1a1a")
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        for c in range(14): controls.columnconfigure(c, weight=0)

        tk.Label(controls, text="Channel", fg="white", bg="#1a1a1a").grid(row=0, column=0, sticky="w", padx=(2,0))
        self.chan_var = tk.StringVar(value="CHAN1")
        ttk.Combobox(controls, textvariable=self.chan_var, values=["CHAN1","CHAN2","CHAN3","CHAN4"], width=7, state="readonly").grid(row=0, column=1, padx=0)

        tk.Label(controls, text="Window", fg="white", bg="#1a1a1a").grid(row=0, column=2, sticky="w", padx=(12,0))
        self.window_var = tk.StringVar(value="Hann")
        ttk.Combobox(controls, textvariable=self.window_var, values=list(WINDOWS.keys()), width=9, state="readonly").grid(row=0, column=3, padx=0)

        tk.Label(controls, text="# Harmonics", fg="white", bg="#1a1a1a").grid(row=0, column=4, sticky="w", padx=(12,1))
        self.nharm_var = tk.IntVar(value=25)
        ttk.Spinbox(controls, textvariable=self.nharm_var, from_=5, to=80, width=5).grid(row=0, column=5, padx=4)

        self.include_dc_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Include DC", variable=self.include_dc_var).grid(row=0, column=6, padx=(12,1))

        self.raw_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="RAW if possible", variable=self.raw_var).grid(row=0, column=7, padx=(12,1))

        self.thdn_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="THD+N", variable=self.thdn_var).grid(row=0, column=8, padx=(12,1))
        # NEW: persistence controls live in cols 9–10
        self.persist_btn = ttk.Checkbutton(controls, text="Persistence (heat-map)", variable=self.hm_var)
        self.persist_btn.grid(row=0, column=9, padx=(12,4))

        self.clear_persist = ttk.Button(controls, text="Clear trail", command=self._clear_persistence)
        self.clear_persist.grid(row=0, column=10, padx=4)

        # SHIFTED: Measure/Auto move to cols 11–12
        self.measure_btn = ttk.Button(controls, text="Measure", command=self.measure_once)
        self.measure_btn.grid(row=0, column=11, padx=(12,4))

        self.auto_btn = ttk.Button(controls, text="Auto: OFF", command=self.toggle_auto)
        self.auto_btn.grid(row=0, column=12, padx=4)

        # SHIFTED: status label goes to the new last column 13
        self.status_var = tk.StringVar(value="Idle.")
        tk.Label(controls, textvariable=self.status_var, fg="#ddd", bg="#1a1a1a").grid(row=0, column=13, sticky="e")

        # Make the rightmost column expand so the status text doesn’t collide
        controls.columnconfigure(13, weight=1)
        
        # --- compact two-row control layout (10 lines) ---
        self.clear_persist.grid_configure(row=1, column=0, padx=4, pady=(2,6))
        self.measure_btn.grid_configure(row=1, column=1, padx=4, pady=(2,6))
        self.auto_btn.grid_configure(row=1, column=2, padx=4, pady=(2,6))
        self.status_lbl = controls.grid_slaves(row=0, column=13)[0]
        self.status_lbl.grid_configure(row=1, column=3, columnspan=11, sticky="w", padx=(12,4))
        controls.columnconfigure(3, weight=0)
        controls.rowconfigure(1, weight=0)
        # smaller font for the "Window" combobox (col 3 in row 0)
        ttk.Style().configure("Small.TCombobox", font=("TkDefaultFont", 8))
        controls.grid_slaves(row=0, column=3)[0].configure(style="Small.TCombobox")

        # Plot area
        self.fig = plt.Figure(figsize=(7.5, 3.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Spectrum")
        self.ax.set_xlabel("Frequency (Hz)")
        self.ax.set_ylabel("RMS / bin (units of input)")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.parent)
        self.canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew", padx=10, pady=4)

        # Table
        table_frame = tk.Frame(self.parent, bg="#1a1a1a")
        table_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(4,12))
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        cols = ("k","f_hz","mag_rms","percent","phase_deg")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        for c,w in zip(cols, (50, 120, 120, 100, 100)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        # Export buttons
        export_bar = tk.Frame(self.parent, bg="#1a1a1a")
        export_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0,10))
        ttk.Button(export_bar, text="Save CSV", command=self.save_csv).pack(side="left", padx=4)
        ttk.Button(export_bar, text="Save Spectrum PNG", command=self.save_png).pack(side="left", padx=4)
        ttk.Button(export_bar, text="Copy Markdown Summary", command=self.copy_md).pack(side="left", padx=4)

        self._apply_dark_theme()

        self._ensure_scope()

    def _ensure_scope(self) -> bool:
        """Bind to the shared scope handle managed by the app; update status if missing."""
        try:
            self.scope = getattr(app_state, "scope", None)
        except Exception:
            self.scope = None
        if self.scope is None:
            self.status_var.set("Not connected — use SCPI tab to connect.")
            log_debug("ℹ️ Harmonics: no shared scope handle yet; connect via SCPI tab.")
            return False
        return True

    # --------- Actions ----------
    def toggle_auto(self):
        self.auto_flag = not self.auto_flag
        self.auto_btn.config(text=f"Auto: {'ON' if self.auto_flag else 'OFF'}")
        if self.auto_flag:
            # Kick off immediately if connected; otherwise retry soon.
            if self._ensure_scope():
                self.measure_once()
            else:
                self.root.after(1500, self.measure_once)
        # When turning OFF: nothing else to do — _do_measure() checks auto_flag before rescheduling.

    def measure_once(self):
        # Do not queue another worker if one is still running.
        if self.worker and self.worker.is_alive():
            return
        # Ensure we have a scope before starting the worker.
        if not self._ensure_scope():
            # If Auto is on, keep retrying every 2 s until connected
            if self.auto_flag:
                self.root.after(2000, self.measure_once)
            return

        from app import app_state
        if getattr(app_state, "is_shutting_down", False):
            return

        self.worker = threading.Thread(target=self._do_measure, daemon=True)
        self.worker.start()

    def _call_scpi_thread(self, fn, *args, **kwargs):
        """
        Execute fn on the project's SCPI loop thread if available; otherwise call directly.
        Logs which path is used so we can verify serialization.
        """
        import threading, time
        start = time.time()
        try:
            import scpi.loop as scpi_loop
        except Exception:
            scpi_loop = None

        gateways = [
            "call_sync",             # preferred
            "run_on_scpi_thread",    # alt
            "submit_sync",           # some repos
            "invoke",                # generic
            "scpi_call",             # generic
        ]

        if scpi_loop:
            for name in gateways:
                gateway = getattr(scpi_loop, name, None)
                if callable(gateway):
                    self.status_var.set(f"Using SCPI loop: {name}() …")
                    result = gateway(fn, *args, **kwargs)
                    elapsed = (time.time() - start)
                    log_debug(f"🧵 Harmonics fetch via SCPI loop gateway '{name}' in {elapsed:.2f}s")
                    return result

        # Fallback: direct call (not ideal for RAW)
        self.status_var.set("SCPI loop gateway not found — calling directly")
        result = fn(*args, **kwargs)
        elapsed = (time.time() - start)
        log_debug(f"🧵 Harmonics fetch called directly (no SCPI loop gateway) in {elapsed:.2f}s; "
                  f"thread={threading.current_thread().name}")
        return result

    def _fetch_waveform(self, chan_name: str, prefer_raw: bool = True):
        """
        Strict mode selection:
          - prefer_raw=True  -> local exclusive RAW read
          - prefer_raw=False -> local exclusive NORM read
        Always returns (t [s], y [SI], fs [Hz]) and tags _last_fetch_mode/_last_pts/_last_elapsed.
        """
        if self.scope is None:
            self._ensure_scope()
        scope = self.scope
        if scope is None:
            raise RuntimeError("No scope connection (shared handle is None)")

        # reset any "RAW failed once" guard for this measurement
        try:
            import app.app_state as _state
            _state.raw_mode_failed_once = False
        except Exception:
            pass

        # Use the same safe local path for both modes (no shared fetcher → no surprise RAW)
        return self._fetch_waveform_local_exclusive(scope, chan_name, raw=bool(prefer_raw))

    def _fetch_waveform_local_exclusive(self, scope, chan_name: str, raw: bool = True):
        """
        Serialized local read under scpi_lock.
        - Uses :TRIG:STAT? to detect run/stop (ACQ:STATE? can TMO on MSO5000).
        - Bumps VISA timeout and chunk_size for large RAW transfers.
        - STOP → read → restore RUN only if it was running before.
        Returns (t [s], y [SI], fs [Hz]) and fills:
          self._last_fetch_mode, self._last_pts, self._last_elapsed
        """
        import numpy as np, time
        with scpi_lock:
            # tell other components we're in a critical transfer (if they check it)
            try:
                import app.app_state as _state
                _state.is_scpi_busy = True
            except Exception:
                pass

            old_timeout = getattr(scope, "timeout", None)
            old_chunk   = getattr(scope, "chunk_size", None)
            was_running = False

            try:
                # --- determine acquisition state (RUN/WAIT/SING vs STOP) ---
                trig = safe_query(scope, ":TRIG:STAT?", "").strip().upper()
                # treat anything that's not explicitly STOP as "running"
                was_running = ("STOP" not in trig)

                # --- configure waveform source/format/mode ---
                scope.write(f":WAV:SOUR {chan_name}")
                scope.write(":WAV:FORM BYTE")
                if raw:
                    scope.write(":WAV:MODE RAW")
                    # full memory; set explicit RAW points if allowed
                    try:
                        scope.write(":WAV:POIN:MODE RAW")
                        scope.write(":WAV:POIN 25000000")
                    except Exception:
                        pass
                else:
                    scope.write(":WAV:MODE NORM")
                    # respect project-configured NORM points if available
                    try:
                        scope.write(":WAV:POIN:MODE RAW")
                    except Exception:
                        pass
                    try:
                        from config import WAV_POINTS
                        scope.write(f":WAV:POIN {int(WAV_POINTS)}")
                    except Exception:
                        pass

                # --- preamble (double-read helps on Rigol) ---
                scope.query(":WAV:PRE?")
                time.sleep(0.08)
                pre = scope.query(":WAV:PRE?").strip().split(",")
                # fields: ... xinc(4), xorig(5), ..., yinc(7), yorig(8), yref(9)
                xinc  = float(pre[4])
                xorig = float(pre[5])
                yinc  = float(pre[7])
                yorig = float(pre[8])
                yref  = float(pre[9])

                # --- stop only for the transfer ---
                scope.write(":STOP")

                # generous I/O settings for big RAW transfers
                try:
                    if old_timeout is None or old_timeout < 180000:
                        scope.timeout = 180000  # ms
                except Exception:
                    pass
                try:
                    if hasattr(scope, "chunk_size"):
                        if old_chunk is None or old_chunk < 8 * 1024 * 1024:
                            scope.chunk_size = 8 * 1024 * 1024
                except Exception:
                    pass

                # --- binary read with timing ---
                t0 = time.time()
                try:
                    raw_bytes = scope.query_binary_values(":WAV:DATA?", datatype="B", container=np.array)
                except OSError as oe:
                    # If the socket is being torn down during app shutdown, treat it as benign.
                    import app.app_state as _state
                    if getattr(_state, "is_shutting_down", False):
                        raise RuntimeError("Scope I/O aborted due to shutdown") from oe
                    raise
                elapsed = time.time() - t0


            finally:
                # restore I/O settings and acquisition state
                try:
                    if old_timeout is not None:
                        scope.timeout = old_timeout
                except Exception:
                    pass
                try:
                    if old_chunk is not None and hasattr(scope, "chunk_size"):
                        scope.chunk_size = old_chunk
                except Exception:
                    pass
                try:
                    scope.write(":RUN" if was_running else ":STOP")
                except Exception:
                    pass
                try:
                    import app.app_state as _state
                    _state.is_scpi_busy = False
                except Exception:
                    pass

        if raw_bytes.size == 0:
            raise RuntimeError("Empty waveform")

        # scale to SI units and build time axis
        t = xorig + np.arange(raw_bytes.size) * xinc
        y = (raw_bytes - yref) * yinc + yorig
        fs = 1.0 / float(xinc) if xinc > 0 else 1.0

        # record + log transfer info
        pts = int(raw_bytes.size)
        mib = pts / (1024 * 1024)
        rate = mib / max(elapsed, 1e-6)
        self._last_fetch_mode = "RAW-local" if raw else "NORM-local"
        self._last_pts = pts
        self._last_elapsed = float(elapsed)
        log_debug(f"⏬ {self._last_fetch_mode}/{chan_name}: {pts:,} pts ({mib:.1f} MiB) in {elapsed:.2f}s → {rate:.2f} MiB/s")

        return t, y, fs

    def _do_measure(self):
        from app import app_state
        if getattr(app_state, "is_shutting_down", False):
            return

        chan = self.chan_var.get()
        window_ui = self.window_var.get()
        window = WINDOWS.get(window_ui, "hann")
        include_dc = self.include_dc_var.get()
        prefer_raw = self.raw_var.get()
        nh = int(self.nharm_var.get())

        try:
            # 1) Fetch (will set _last_fetch_mode/pts/elapsed)
            t, y, fs = self._fetch_waveform(chan, prefer_raw=prefer_raw)

            # 2) Display-only decimation to keep UI responsive on huge RAWs
            NMAX = 1_048_576
            y_for_fft = y
            fs_for_fft = fs
            if y.size > NMAX:
                step = int(np.ceil(y.size / NMAX))
                y_for_fft = y[::step]
                fs_for_fft = fs / step

            # 3) Analyze on full-resolution data for accuracy
            res = analyze_harmonics(
                y, fs,
                n_harmonics=nh,
                window=window,
                include_dc=include_dc,
                compute_thdn=True
            )

        except Exception as e:
            from app import app_state
            if getattr(app_state, "is_shutting_down", False):
                log_debug(f"ℹ️ Harmonics worker aborting during shutdown: {e}")
                return
            # only update UI if we’re not shutting down
            try:
                self.status_var.set(f"Error: {e}")
            except Exception:
                pass
            if self.auto_flag:
                self.root.after(2000, self.measure_once)
            return

        # 4) Cache last capture
        self.last_capture = (t, y, fs, chan, 1.0)

        # 5) Update UI (plot uses decimated copy; table uses analysis results)
        self._render_plot(y_for_fft, fs_for_fft, res)
        self._render_table(res)

        # 6) Status line with capture info
        thd_pct = 100.0 * res.thd
        thdn_txt = f", THD+N={res.thdn*100:.2f}%" if res.thdn is not None else ""
        coh = res.coherence_cycles
        span = (y.size / fs) if fs > 0 else 0.0
        extra = f" | {self._last_fetch_mode}, N={y.size/1e6:.2f}M, span={span:.3f}s"
        if y_for_fft is not y:
            decim = int(np.ceil(y.size / y_for_fft.size))
            extra += f", disp decim x{decim}"
        self.status_var.set(
            f"f1={res.f1_hz:.3f} Hz, V1_rms={res.v1_rms:.6g}, THD={thd_pct:.3f}%{thdn_txt}, "
            f"cycles={coh:.2f}{extra}"
        )
        if res.warnings:
            log_debug("⚠️ " + "; ".join(res.warnings))

        # 7) Auto re-arm
        if self.auto_flag:
            self.root.after(2000, self.measure_once)

    def _render_plot(self, y: np.ndarray, fs: float, res):
        import numpy as _np, math as _math

        N = len(y)
        # For display only: use Hann to avoid ragged lines (same as your current code)
        Y = _np.fft.rfft((y - (_np.mean(y) if not res.include_dc else 0.0)) * _np.hanning(N))
        f = _np.fft.rfftfreq(N, d=1.0/fs)
        mag_rms = _np.abs(Y) / N / _math.sqrt(2)

        # Determine x-limit like before
        fmax = min(res.fs/2, 10*res.f1_hz if res.f1_hz > 0 else res.fs/2)

        # Manage persistence history
        if self.auto_flag and self.hm_var.get():
            # If frequency grid changes a lot (e.g., decimation), we still accept it—trail is visual only
            self.spec_hist.append((f.copy(), mag_rms.copy()))
        else:
            # When persistence is off, keep no history
            self.spec_hist.clear()

        # Draw
        self.ax.cla()
        self._style_axes(self.ax)

        # Plot trail (oldest first, faintest)
        if self.spec_hist:
            steps = len(self.spec_hist)
            # Use a gentle nonlinear fade so recent lines pop a bit more
            for i, (f_i, m_i) in enumerate(self.spec_hist):
                alpha = 0.12 + 0.35 * ((i + 1) / steps) ** 1.5  # 0.12..~0.47
                self.ax.plot(f_i, m_i, linewidth=1.0, alpha=alpha)

        # Plot current spectrum on top
        self.ax.plot(f, mag_rms, linewidth=1.4)

        # Limits/labels
        self.ax.set_xlim(0, max(1e-12, fmax))
        self.ax.set_xlabel("Frequency (Hz)")
        self.ax.set_ylabel("RMS amplitude")
        # Mark fundamentals/harmonics from table
        for row in res.rows:
            self.ax.axvline(row.f_hz, linestyle="--", alpha=0.25)
        if res.f1_hz > 0:
            self.ax.axvline(res.f1_hz, color="#bbbbbb", alpha=0.6)

        self.canvas.draw_idle()

    def _render_table(self, res):
        # Clear
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Defensive: if result is missing or malformed, bail quietly
        if not res or not hasattr(res, "rows"):
            return

        # If we have harmonics, render them as before
        if res.rows:
            for r in res.rows:
                self.tree.insert(
                    "", "end",
                    values=(r.k, f"{r.f_hz:.3f}", f"{r.mag_rms:.6g}", f"{r.percent:.3f}", f"{r.phase_deg:.2f}")
                )
            return

        # --- No harmonics resolvable: show at least the fundamental so the table isn't blank
        try:
            f1 = float(res.f1_hz)
        except Exception:
            f1 = 0.0
        try:
            v1 = float(res.v1_rms)
        except Exception:
            v1 = 0.0

        # We don't keep fundamental phase in the result; display 0.0° for now (display only)
        self.tree.insert("", "end", values=("1", f"{f1:.3f}", f"{v1:.6g}", "100.000", f"{0.0:.2f}"))

        # Add a small separator/placeholder row so it's obvious harmonics are not available
        self.tree.insert("", "end", values=("", "—", "—", "—", ""))

        # Brief diagnostic in status: why were there no harmonics?
        reasons = []
        try:
            nyquist = float(res.fs) / 2.0
            if f1 > 0.0 and (2.0 * f1) >= nyquist:
                reasons.append("Nyquist < 2·f1")
        except Exception:
            pass
        try:
            if hasattr(res, "coherence_cycles") and res.coherence_cycles < 3.0:
                reasons.append("<3 cycles in buffer")
        except Exception:
            pass

        if reasons:
            self.status_var.set(self.status_var.get() + "  |  " + "; ".join(reasons) + " — use RAW or widen timebase")


    # --------- Export ----------
    def save_csv(self):
        if not self.last_capture:
            messagebox.showinfo("Save CSV", "No data yet.")
            return
        t, y, fs, chan, scale = self.last_capture
        res = analyze_harmonics(y, fs, n_harmonics=int(self.nharm_var.get()),
                                window=WINDOWS.get(self.window_var.get(),"hann"),
                                include_dc=self.include_dc_var.get(), compute_thdn=True)
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            w.writerow(["timestamp", ts])
            w.writerow(["channel", chan])
            w.writerow(["fs_hz", res.fs])
            w.writerow(["window", res.window])
            w.writerow(["include_dc", res.include_dc])
            w.writerow(["f1_hz", res.f1_hz])
            w.writerow(["V1_rms", res.v1_rms])
            w.writerow(["THD", res.thd])
            w.writerow(["THD_percent", res.thd*100.0])
            w.writerow(["THD+N", "" if res.thdn is None else res.thdn])
            w.writerow(["SINAD_dB", "" if res.sinad_db is None else res.sinad_db])
            w.writerow(["SNR_dB", "" if res.snr_db is None else res.snr_db])
            w.writerow(["crest_factor", res.crest])
            w.writerow(["form_factor", res.form_factor])
            w.writerow([])
            w.writerow(["k","f_hz","mag_rms","percent","phase_deg"])
            for r in res.rows:
                w.writerow([r.k, r.f_hz, r.mag_rms, r.percent, r.phase_deg])

    def save_png(self):
        if self.canvas is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG","*.png")])
        if not path: return
        self.fig.savefig(path, dpi=150, facecolor=self.fig.get_facecolor(), edgecolor="none")


    def copy_md(self):
        if not self.last_capture:
            messagebox.showinfo("Copy Markdown", "No data yet.")
            return
        _, y, fs, _, _ = self.last_capture
        res = analyze_harmonics(y, fs, n_harmonics=int(self.nharm_var.get()),
                                window=WINDOWS.get(self.window_var.get(),"hann"),
                                include_dc=self.include_dc_var.get(), compute_thdn=True)
        lines = []
        lines.append(f"**Harmonics/THD** — f1 = {res.f1_hz:.3f} Hz, V1_rms = {res.v1_rms:.6g}, THD = {res.thd*100:.3f}%")
        if res.thdn is not None:
            lines[-1] += f", THD+N = {res.thdn*100:.3f}%"
        lines.append("")
        lines.append("| k | f (Hz) | Mag (RMS) | % of fundamental | Phase (deg) |")
        lines.append("|---:|------:|----------:|-----------------:|-----------:|")
        for r in res.rows[:15]:
            lines.append(f"| {r.k} | {r.f_hz:.2f} | {r.mag_rms:.6g} | {r.percent:.3f}% | {r.phase_deg:.2f} |")
        md = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(md)
        self.root.update()

def setup_harmonics_tab(tab_frame, ip: str, root):
    """Entry point used by main.py to mount the tab."""
    return HarmonicsTab(tab_frame, ip, root)
