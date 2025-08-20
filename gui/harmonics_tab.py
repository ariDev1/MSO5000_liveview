
"""
harmonics_tab.py — Tkinter GUI tab for Harmonics & THD
Safe integration: no hidden scope changes; fetches via SCPI with locking and preserves RUN/STOP state.
"""
from __future__ import annotations
from typing import Optional
import csv, time, threading, math
import os
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
from collections import deque

from utils.debug import log_debug
from scpi.interface import scpi_lock, safe_query
from scpi.waveform import fetch_waveform_with_fallback  # If available; we also implement a local fetch fallback
from scipy.signal import find_peaks
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
        self._overlay_artists = []
        self._legend_artist = None
        self._last_spec = None
        self.SPEC_COLOR = "#d0ff00"
        self._build_ui()
        # map harmonic order k -> treeview item id (stable rows; prevents flicker)
        self._tree_rows = {}
        self._selected_k = None
        self._selected_freq = None

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

    def _ensure_static_legend(self):
        """Create a single, figure-level legend once; keep it between redraws."""
        import matplotlib.lines as mlines
        import matplotlib.patches as mpatches

        if getattr(self, "_legend_artist", None) is not None:
            # already created; make sure colors match current theme
            try:
                fr = self._legend_artist.get_frame()
                fr.set_facecolor("#222222")
                fr.set_edgecolor("#444444")
                for txt in self._legend_artist.get_texts():
                    txt.set_color(self.DARK_FG)
            except Exception:
                pass
            return

        handles = [
            mlines.Line2D([], [], linewidth=1.4, label="Spectrum", color=self.SPEC_COLOR),
            mlines.Line2D([], [], linestyle=":", linewidth=1.2, label="Interharmonic"),
            mlines.Line2D([], [], marker="s", linestyle="None", label="Known line"),
            mpatches.Patch(alpha=0.10, label="Harmonic window (±tol)"),
        ]

        # Figure-level legend (not tied to an Axes), so ax.cla() won’t erase it.
        self._legend_artist = self.fig.legend(
            handles=handles,
            loc="upper right",
            bbox_to_anchor=(0.98, 0.98),   # tuck into the corner a bit
            fontsize="small",
            framealpha=0.45,
            borderpad=0.4,
        )
        # Dark theme styling
        fr = self._legend_artist.get_frame()
        fr.set_facecolor("#222222")
        fr.set_edgecolor("#444444")
        for txt in self._legend_artist.get_texts():
            txt.set_color(self.DARK_FG)

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

        cols = ("k","f_hz","f_pred","df_hz","mag_rms","dBr1","percent","cumTHD_pct","phase_deg")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)

        # widths tuned for your dark theme and screenshot layout
        widths = {
            "k": 50, "f_hz": 120, "f_pred": 120, "df_hz": 100,
            "mag_rms": 120, "dBr1": 90, "percent": 100, "cumTHD_pct": 110, "phase_deg": 100
        }
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths.get(c, 100), anchor="e")

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.extra_var = tk.StringVar(value="")
        self.extra_lbl = tk.Label(
            table_frame,
            textvariable=self.extra_var,
            bg="#1a1a1a", fg="#dddddd",
            anchor="w", justify="left"
        )
        self.extra_lbl.grid(row=1, column=0, sticky="ew", pady=(6, 0))
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
        self._ensure_static_legend()
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

    def _debug_analysis_summary(self, res, spec, inter_list, known_list, tol_hz):
        """Emit a concise analysis summary to the Debug Log (display-only)."""
        try:
            import math
            f_axis, mag_rms = spec if spec else (None, None)
            nbins = len(f_axis) if (f_axis is not None) else 0
            df = (float(f_axis[1] - f_axis[0]) if f_axis is not None and len(f_axis) > 1 else float("nan"))

            f1  = float(getattr(res, "f1_hz", float("nan")) or float("nan"))
            v1  = float(getattr(res, "v1_rms", float("nan")) or float("nan"))
            thd = float(getattr(res, "thd_pct", float("nan")) or float("nan"))

            msg = (
                f"📈 Analysis | ch={self.chan_var.get()} | window={self.window_var.get()} | "
                f"bins={nbins}, df={df:.3g} Hz | f1={f1:.6g} Hz, V1rms={v1:.6g} | THD={thd:.3f}% | "
                f"harmonic tol=±{tol_hz:.3g} Hz"
            )
            log_debug(msg)

            if inter_list:
                s = ", ".join(f"{f:.1f} Hz ({db:.1f} dBr₁)" for f, db in inter_list[:8])
                log_debug(f"🔶 Interharmonics: {s}")
            else:
                log_debug("🔶 Interharmonics: none ≥ threshold")

            if known_list:
                s = ", ".join(f"{f:.1f} Hz ({db:.1f} dBr₁)" for f, db in known_list)
                log_debug(f"🟩 Known/house lines: {s}")
            else:
                log_debug("🟩 Known/house lines: none")
        except Exception as e:
            log_debug(f"⚠️ Debug summary failed: {e}")

    def _draw_interharmonics_overlay(self, f_axis, mag_rms, *, f0_hz, inter_list, known_list, tol_hz):
        """
        Visual overlay to distinguish harmonics vs. interharmonics.
        - Shades ±tol around each k·f0 (harmonic windows)
        - Marks interharmonic peaks with dotted vlines + ▼ tip
        - Marks known/house lines with ■
        """
        import numpy as np

        # Safety: nothing to do without a plotted Axes or frequency axis
        if getattr(self, "ax", None) is None or f0_hz <= 0 or len(f_axis) < 2:
            return

        ax = self.ax

        # Remove previous overlay artists cleanly (but keep legend persistent!)
        for a in getattr(self, "_overlay_artists", []):
            try:
                a.remove()
            except Exception:
                pass
        self._overlay_artists = []

        f_min, f_max = self.ax.get_xlim()

        # --- 1) Shade harmonic acceptance windows (±tol_hz around k·f0)
        kmax = int(f_max // max(f0_hz, 1e-12))
        for k in range(1, kmax + 1):
            fk = k * f0_hz
            x0, x1 = fk - tol_hz, fk + tol_hz
            if x1 < f_min or x0 > f_max:
                continue
            span = ax.axvspan(max(x0, f_min), min(x1, f_max), alpha=0.06)
            self._overlay_artists.append(span)

        # --- 2) Interharmonic peaks: dotted vline + ▼ at actual amplitude
        for f_i, _dbr in inter_list:
            idx = int(np.argmin(np.abs(f_axis - f_i)))
            yi = float(mag_rms[idx])
            v = ax.axvline(f_i, linestyle=":", linewidth=1.2, alpha=0.7)
            m = ax.plot([f_i], [yi], marker="v", markersize=5, alpha=0.9)[0]
            self._overlay_artists += [v, m]

        # --- 3) Known/house lines: small ■ markers near the noise floor (or real level if visible)
        y0, y1 = ax.get_ylim()
        y_mark = y0 + 0.02 * (y1 - y0)
        for f_k, _dbr in known_list:
            idx = int(np.argmin(np.abs(f_axis - f_k)))
            yk = max(float(mag_rms[idx]), y_mark)
            m = ax.plot([f_k], [yk], marker="s", markersize=5, alpha=0.9)[0]
            self._overlay_artists.append(m)

        # --- 4) Static legend (no flicker) ---
        self._ensure_static_legend()
        # --- Selected harmonic marker (if any) ---
        try:
            sel_f = getattr(self, "_selected_freq", None)
            if sel_f is not None:
                idx = int(np.argmin(np.abs(f_axis - sel_f)))
                fx = float(f_axis[idx])
                yi = float(mag_rms[idx])
                # Bright vline + dot + small label
                v = ax.axvline(fx, color="#00eaff", linewidth=1.5, alpha=0.9, zorder=4)
                m = ax.plot([fx], [yi], marker="o", markersize=7, color="#00eaff", alpha=0.95, zorder=5)[0]
                lab = f"k={getattr(self, '_selected_k', '?')}"
                y0, y1 = ax.get_ylim()
                ty = min(y1, yi + 0.06 * (y1 - y0))
                t = ax.text(fx, ty, lab, color="#00eaff", fontsize=9, ha="center", va="bottom")
                self._overlay_artists += [v, m, t]
        except Exception:
            pass

        # Ask canvas to refresh just the overlay change
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def _on_tree_select(self, event=None):
        """
        When a table row is selected, store k and f and refresh the overlay so
        the plot shows a marker at that harmonic.
        """
        try:
            sel = self.tree.selection()
            if not sel:
                self._selected_k = None
                self._selected_freq = None
                # redraw to clear any previous marker
                self._refresh_selection_overlay()
                return
            iid = sel[0]
            vals = self.tree.item(iid, "values")
            # columns: ("k","f_hz","f_pred","df_hz","mag_rms","dBr1","percent","cumTHD_pct","phase_deg")
            k = int(float(vals[0]))
            # prefer measured f_hz; fall back to predicted if missing
            f_txt = vals[1]
            if f_txt in ("", "—"):
                f_txt = vals[2]
            f_sel = float(f_txt)
            self._selected_k = k
            self._selected_freq = f_sel
            # redraw overlays (shading, interharmonics, known lines, + our selection)
            self._refresh_selection_overlay()
        except Exception:
            # keep UI responsive even if parsing fails
            pass

    def _refresh_selection_overlay(self):
        """
        Re-draw the overlay layer using cached spectrum + last interharmonics.
        Safe no-op if we don't have required caches yet.
        """
        try:
            spec = getattr(self, "_last_spec", None)
            res  = getattr(self, "_last_result", None)
            if not spec or not res or getattr(res, "f1_hz", 0.0) <= 0.0:
                return
            f_axis, mag_rms = spec
            f0 = float(res.f1_hz)
            inter = getattr(self, "_last_interharmonics", []) or []
            known = getattr(self, "_last_known_lines", []) or []
            df = float(f_axis[1] - f_axis[0]) if len(f_axis) >= 2 else 0.0
            tol = max(0.015 * f0, 2 * df) if f0 > 0 and df > 0 else 0.0
            self._draw_interharmonics_overlay(
                f_axis, mag_rms,
                f0_hz=f0,
                inter_list=inter,
                known_list=[(fk, db) for fk, db in known],
                tol_hz=tol
            )
        except Exception:
            pass

    # --- Known lab lines you care about (edit this list as you like) ---
    KNOWN_LINES_HZ = [
        50.0, 100.0, 150.0, 200.0,      # mains (EU)
        16.67,                          # railway (EU)
        #20000.0, 25000.0, 30000.0, 40000.0, 45000.0  # common SMPS/driver bands
    ]

    def _find_interharmonics_from_spec(freqs_hz: np.ndarray,
                                       mag_rms: np.ndarray,
                                       f0_hz: float,
                                       *,
                                       topN=8,
                                       rel_exclusion=0.015,   # ±1.5% around k·f0 → harmonic
                                       abs_exclusion_bins=2,  # plus ±2 bins
                                       min_prom_db=20.0):     # only show ≥20 dB below fundamental
        if f0_hz <= 0 or len(freqs_hz) < 3:
            return []
        df = float(freqs_hz[1] - freqs_hz[0])
        tol_hz = max(rel_exclusion * f0_hz, abs_exclusion_bins * df)

        # Fundamental reference
        fund_idx = int(np.clip(round(f0_hz / df), 0, len(freqs_hz) - 1))
        fund_amp = float(max(mag_rms[fund_idx], 1e-20))
        rel_db = 20.0 * np.log10(np.maximum(mag_rms, 1e-20) / fund_amp)

        # Peak picking on relative spectrum
        peaks, _ = find_peaks(rel_db, prominence=min_prom_db)

        inter = []
        for p in peaks:
            f = freqs_hz[p]
            k = max(1, int(round(f / f0_hz)))
            f_harm = k * f0_hz
            if abs(f - f_harm) <= tol_hz:
                continue  # skip anything close to an integer harmonic
            inter.append((f, rel_db[p]))

        inter.sort(key=lambda x: x[1], reverse=True)
        return inter[:topN]

    def _match_known_lines_from_spec(freqs_hz: np.ndarray,
                                     mag_rms: np.ndarray,
                                     f0_hz: float,
                                     *,
                                     known_list=KNOWN_LINES_HZ,
                                     tol_bins=2,
                                     floor_db=-80.0):
        if f0_hz <= 0 or len(freqs_hz) < 2:
            return []
        df = float(freqs_hz[1] - freqs_hz[0])
        fund_idx = int(np.clip(round(f0_hz / df), 0, len(freqs_hz) - 1))
        fund_amp = float(max(mag_rms[fund_idx], 1e-20))
        rel_db = 20.0 * np.log10(np.maximum(mag_rms, 1e-20) / fund_amp)

        out = []
        tol_hz = tol_bins * df
        for fk in known_list:
            idx = int(np.argmin(np.abs(freqs_hz - fk)))
            if abs(freqs_hz[idx] - fk) <= tol_hz and rel_db[idx] > floor_db:
                out.append((fk, rel_db[idx]))
        return out

    def _update_interharmonics_readout(self, res, *, min_prom_db=10.0, topN=8):
        """
        Compute and show non-harmonic (interharmonic) peaks and known 'house' lines,
        referenced in dB relative to the fundamental (dBr₁). Safe: read-only, uses
        the last plotted spectrum cached by _render_plot().
        """
        lines = []
        spec = getattr(self, "_last_spec", None)
        
        def _fmt_hz(f):
            return f"{f/1000:.1f} kHz" if f >= 1000 else f"{f:.1f} Hz"

        try:
            # Need a valid spectrum and fundamental
            if not (spec and res and getattr(res, "f1_hz", 0.0) > 0):
                self.extra_var.set("")
                return

            f_axis, mag_rms = spec
            f0 = float(res.f1_hz)

            # Frequency resolution and guard rails
            if not hasattr(f_axis, "__len__") or len(f_axis) < 2:
                self.extra_var.set("")
                return
            df = float(f_axis[1] - f_axis[0])
            if df <= 0.0:
                self.extra_var.set("")
                return

            # Fundamental bin and relative dB spectrum (dBr to fundamental)
            fund_idx = int(np.clip(round(f0 / df), 0, len(f_axis) - 1))
            fund_amp = float(max(mag_rms[fund_idx], 1e-20))
            rel_db = 20.0 * np.log10(np.maximum(mag_rms, 1e-20) / fund_amp)

            # ---- Interharmonic peaks (exclude integer harmonics) ----
            # Tolerance for "is a harmonic" = max(±1.5% of f0, ±2 bins)
            tol_hz = max(0.015 * f0, 2 * df)

            # Peak picking on the relative spectrum
            peaks, _ = find_peaks(rel_db, prominence=min_prom_db)

            inter = []
            for p in peaks:
                fp = f_axis[p]
                k = max(1, int(round(fp / f0)))
                if abs(fp - k * f0) <= tol_hz:
                    continue  # reject actual harmonics
                inter.append((fp, rel_db[p]))

            inter.sort(key=lambda x: x[1], reverse=True)
            inter = inter[:topN]

            # ---- Known/house lines (from your class list) ----
            known = []
            tol_bins = 2
            floor_db = -80.0
            tol_hz_k = tol_bins * df
            for fk in getattr(self, "KNOWN_LINES_HZ", []):
                idx = int(np.argmin(np.abs(f_axis - fk)))
                if abs(f_axis[idx] - fk) <= tol_hz_k and rel_db[idx] > floor_db:
                    known.append((float(fk), rel_db[idx]))

            # ---- Build readout text ----
            if inter:
                lines.append(
                    "Non-harmonic lines (dBr₁): " +
                    ", ".join(f"{_fmt_hz(fi)} ({db:.1f} dBr₁)" for fi, db in inter)
                )
            else:
                lines.append(f"Non-harmonic lines (dBr₁): (none ≥ {min_prom_db:.0f} dB)")

            if known:
                lines.append(
                    "Known/house lines: " +
                    ", ".join(f"{_fmt_hz(fk)} ({db:.1f} dBr₁)" for fk, db in known)
                )
            elif getattr(self, "KNOWN_LINES_HZ", None):
                lines.append("Known/house lines: (none from list visible)")

            self._last_interharmonics = inter
            self._last_known_lines = known
            self._draw_interharmonics_overlay(
                f_axis, mag_rms,
                f0_hz=f0,
                inter_list=inter,
                known_list=[(fk, db) for fk, db in known],
                tol_hz=max(0.015 * f0, 2 * df)
            )
            self._debug_analysis_summary(
                res,
                (f_axis, mag_rms),
                inter_list=inter,
                known_list=known,
                tol_hz=tol_hz
            )            
            self.extra_var.set("\n".join(lines))

        except Exception:
            # Never break UI on analysis errors; just clear the line.
            self.extra_var.set("")

    def _build_harmonic_export_rows(self, res):
        import math
        # columns to export
        header = ["k","f_hz","f_pred","df_hz","mag_rms","dBr1","percent","cumTHD_pct","phase_deg"]

        # fundamentals
        f1 = float(getattr(res, "f1_hz", 0.0) or 0.0)
        v1 = float(getattr(res, "v1_rms", 0.0) or 0.0)

        rows = []
        sum_sq = 0.0  # for cumulative THD up to k
        for r in getattr(res, "rows", []):
            k      = int(r.k)
            f_meas = float(r.f_hz)
            v_k    = float(r.mag_rms)

            f_pred = (k * f1) if f1 > 0 else float("nan")
            df_hz  = (f_meas - f_pred) if f1 > 0 else float("nan")
            dbr1   = 20.0 * math.log10(v_k / max(v1, 1e-20)) if v1 > 0 else float("nan")

            if k >= 2:  # only harmonics contribute to THD
                sum_sq += v_k * v_k
            cum_thd_pct = (100.0 * math.sqrt(sum_sq) / v1) if (v1 > 0 and sum_sq > 0) else (0.0 if k < 2 else float("nan"))

            rows.append([k, f_meas, f_pred, df_hz, v_k, dbr1, float(r.percent), cum_thd_pct, float(r.phase_deg)])

        return header, rows

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
            self._last_result = res

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
        
        #self._update_interharmonics_readout(res)
        self._update_interharmonics_readout(res, min_prom_db=6.0)


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
        self._last_spec = (f.copy(), mag_rms.copy())
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
        #self.ax.plot(f, mag_rms, linewidth=1.4)
        self.ax.plot(f, mag_rms, linewidth=1.4, color=self.SPEC_COLOR, zorder=3)
        
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
        import math, tkinter as tk

        # Defensive
        if not res or not hasattr(res, "rows"):
            return

        # Fundamental (used for derived columns)
        try:
            f1 = float(res.f1_hz)
        except Exception:
            f1 = 0.0
        try:
            v1 = float(res.v1_rms)
        except Exception:
            v1 = 0.0

        # If no harmonics were resolvable: fall back to original single-row view.
        # This path is rare; a full rebuild is fine here.
        if not res.rows:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self._tree_rows.clear()
            self.tree.insert(
                "",
                "end",
                values=(
                    "1",
                    f"{f1:.3f}",
                    "—",
                    "—",
                    f"{v1:.6g}",
                    "—",
                    "100.000",
                    "—",
                    f"{0.0:.2f}",
                ),
            )
            return

        # --- Build the desired table state (as strings) ---
        new_rows = {}  # k -> tuple(values)
        order = []     # desired row order by k
        sum_sq = 0.0

        for r in res.rows:
            k = int(r.k)
            f_meas = float(r.f_hz)

            # sanitize harmonic magnitude
            try:
                v_k = float(r.mag_rms)
            except Exception:
                v_k = 0.0
            if not math.isfinite(v_k) or v_k < 0:
                v_k = 0.0

            f_pred = (k * f1) if f1 > 0 else float("nan")
            df_hz = (f_meas - f_pred) if (f1 > 0 and math.isfinite(f_pred)) else float("nan")

            # --- SAFE dBr1 ---
            if v1 > 0 and v_k > 0:
                dbr1 = 20.0 * math.log10(v_k / v1)
            elif v1 > 0 and v_k == 0:
                dbr1 = float("-inf")  # will render as "—"
            else:
                dbr1 = float("nan")

            if k >= 2:
                sum_sq += v_k * v_k
            cum_thd_pct = (
                (100.0 * math.sqrt(sum_sq) / v1)
                if (v1 > 0 and sum_sq > 0)
                else (0.0 if k < 2 else float("nan"))
            )

            # sanitize percent/phase
            try:
                pct = float(r.percent)
            except Exception:
                pct = float("nan")
            if not math.isfinite(pct):
                pct = float("nan")
            try:
                ph = float(r.phase_deg)
            except Exception:
                ph = float("nan")
            if not math.isfinite(ph):
                ph = float("nan")

            vals = (
                k,
                f"{f_meas:.3f}",
                (f"{f_pred:.3f}" if math.isfinite(f_pred) else "—"),
                (f"{df_hz:.3f}" if math.isfinite(df_hz) else "—"),
                f"{v_k:.6g}",
                (f"{dbr1:.1f}" if math.isfinite(dbr1) else "—"),
                (f"{pct:.3f}" if math.isfinite(pct) else "—"),
                (f"{cum_thd_pct:.3f}" if math.isfinite(cum_thd_pct) else "—"),
                (f"{ph:.2f}" if math.isfinite(ph) else "—"),
            )
            new_rows[k] = vals
            order.append(k)

        # --- Diff apply to Treeview (no flicker) ---
        # Preserve view + selection
        y0 = self.tree.yview()[0] if self.tree.get_children() else 0.0
        selected = set(self.tree.selection())

        # Remove rows that disappeared
        for k, iid in list(self._tree_rows.items()):
            if k not in new_rows:
                try:
                    self.tree.delete(iid)
                except Exception:
                    pass
                self._tree_rows.pop(k, None)

        # Insert/update rows that are present
        for k in order:
            vals = new_rows[k]
            iid = self._tree_rows.get(k)
            if iid is None:
                iid = self.tree.insert("", "end", values=vals)
                self._tree_rows[k] = iid
            else:
                # Only update when changed (prevents redraw)
                if tuple(self.tree.item(iid, "values")) != vals:
                    self.tree.item(iid, values=vals)

        # Ensure correct order (cheap; usually no-op)
        for idx, k in enumerate(order):
            iid = self._tree_rows[k]
            self.tree.move(iid, "", idx)

        # Restore selection (if still present) and scroll
        still_there = [iid for iid in selected if iid in self._tree_rows.values()]
        if still_there:
            self.tree.selection_set(still_there)
        if self.tree.get_children():
            self.tree.yview_moveto(y0)

        self._last_result = res



    # --------- Export ----------
    def save_csv(self):
        # No modal dialogs; write straight to oszi_csv/harmonics/
        if not self.last_capture:
            self.status_var.set("No data to export yet.")
            return

        t, y, fs, chan, scale = self.last_capture

        # Recompute from the latest capture (keeps behavior; no math changes)
        res = analyze_harmonics(
            y, fs,
            n_harmonics=int(self.nharm_var.get()),
            window=WINDOWS.get(self.window_var.get(), "hann"),
            include_dc=self.include_dc_var.get(),
            compute_thdn=True
        )

        # Ensure destination exists
        dest_dir = os.path.join("oszi_csv", "harmonics")
        os.makedirs(dest_dir, exist_ok=True)

        # UTC timestamp, consistent with your other logs
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
        fname = f"harmonics_{chan}_{ts}.csv"
        path = os.path.join(dest_dir, fname)

        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                # metadata (comment-style so downstream tools can skip easily)
                w.writerow(["# channel", chan])
                w.writerow(["# window", self.window_var.get()])
                w.writerow(["# f1_hz", f"{res.f1_hz:.9f}"])
                w.writerow(["# v1_rms", f"{res.v1_rms:.9g}"])
                w.writerow(["# THD_pct", f"{res.thd*100:.6f}"])
                if res.thdn is not None:
                    w.writerow(["# THDN_pct", f"{res.thdn*100:.6f}"])
                w.writerow([])

                # main harmonic table (kept identical to your current display)
                w.writerow(["k","f_hz","mag_rms","percent","phase_deg"])
                for r in res.rows:
                    w.writerow([r.k, r.f_hz, r.mag_rms, r.percent, r.phase_deg])

            self.status_var.set(f"Saved CSV → {path}")
            log_debug(f"💾 Saved Harmonics CSV → {path}")
        except Exception as e:
            self.status_var.set(f"CSV save failed: {e}")

    def save_png(self):
        # No modal dialogs; write straight to oszi_csv/harmonics/
        if self.canvas is None:
            self.status_var.set("No plot to save.")
            return

        dest_dir = os.path.join("oszi_csv", "harmonics")
        os.makedirs(dest_dir, exist_ok=True)

        # Use last capture for channel in filename (fallback if missing)
        chan = None
        try:
            _, _, _, chan, _ = self.last_capture
        except Exception:
            chan = str(self.chan_var.get())

        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
        fname = f"spectrum_{chan}_{ts}.png"
        path = os.path.join(dest_dir, fname)

        try:
            self.fig.savefig(path, dpi=150,
                             facecolor=self.fig.get_facecolor(),
                             edgecolor="none")
            self.status_var.set(f"Saved Spectrum PNG → {path}")
            log_debug(f"🖼️ Saved Spectrum PNG → {path}")
        except Exception as e:
            self.status_var.set(f"PNG save failed: {e}")

    def copy_md(self):
        import math

        res = getattr(self, "_last_result", None)
        if not res:
            self.status_var.set("No data to copy.")
            return

        header, rows = self._build_harmonic_export_rows(res)

        def fmt(v):
            if isinstance(v, float):
                return "—" if not math.isfinite(v) else f"{v:.6g}"
            return str(v)

        parts = []
        parts.append(f"**Harmonics summary**  ")
        parts.append(
            f"Channel: `{self.chan_var.get()}` | Window: `{self.window_var.get()}` | "
            f"f₁ = {float(getattr(res,'f1_hz', float('nan'))):.6g} Hz | "
            f"V₁,rms = {float(getattr(res,'v1_rms', float('nan'))):.6g} | "
            f"THD = {float(getattr(res,'thd_pct', float('nan'))):.3f}%"
        )
        parts.append("")
        parts.append("| " + " | ".join(header) + " |")
        parts.append("|" + "|".join(["---:"] * len(header)) + "|")
        for row in rows:
            parts.append("| " + " | ".join(fmt(v) for v in row) + " |")

        inter = getattr(self, "_last_interharmonics", [])
        if inter:
            parts.append("")
            parts.append("**Non-harmonic lines** (relative to fundamental):")
            parts.append("")
            parts.append("| frequency_hz | dBr1 |")
            parts.append("|---:|---:|")
            for fi, dbr in inter:
                parts.append(f"| {fi:.6g} | {dbr:.3f} |")

        known = getattr(self, "_last_known_lines", [])
        if known:
            parts.append("")
            parts.append("**Known/house lines:**")
            parts.append("")
            parts.append("| frequency_hz | dBr1 |")
            parts.append("|---:|---:|")
            for fk, dbr in known:
                parts.append(f"| {fk:.6g} | {dbr:.3f} |")

        text = "\n".join(parts)
        try:
            # prefer root if present; fallback to widget
            target = getattr(self, "root", None) or self.tree
            target.clipboard_clear()
            target.clipboard_append(text)
            self.status_var.set("Markdown summary copied to clipboard.")
        except Exception as e:
            self.status_var.set(f"Copy failed: {e}")


def setup_harmonics_tab(tab_frame, ip: str, root):
    """Entry point used by main.py to mount the tab."""
    return HarmonicsTab(tab_frame, ip, root)
