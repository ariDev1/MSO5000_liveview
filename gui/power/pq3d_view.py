# gui/power/pq3d_view.py
# 3D PQ viewer (UI-only). Fixed external viewpoints (no fly mode).
# Keys: 1..6 switch view, V/B cycle, Z toggle proj, H help.

from collections import deque
import numpy as np
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import matplotlib.cm as cm

# -------------------- Configure your preset viewpoints here --------------------
# Edit, remove, or add entries. 'proj' is "persp" or "ortho".
VIEWS = [
    {"name": "Top PQ (2D-like)", "elev": 90, "azim": -90, "roll": 0,  "proj": "ortho"},  # P vs Q
    {"name": "Iso 1",            "elev": 20, "azim": -35, "roll": 0,  "proj": "persp"},
    {"name": "Iso 2",            "elev": 35, "azim":  30, "roll": 0,  "proj": "persp"},
    {"name": "Iso 3",            "elev": 12, "azim":-120, "roll": 0,  "proj": "persp"},
    {"name": "Front (P–t)",      "elev":  0, "azim": -90, "roll": 0,  "proj": "ortho"},  # X–Z
    {"name": "Side  (Q–t)",      "elev":  0, "azim":   0, "roll": 0,  "proj": "ortho"},  # Y–Z
]
DEFAULT_VIEW_INDEX = 1  # which entry in VIEWS to start with (0-based)
# -----------------------------------------------------------------------------

DEFAULT_ROLL_SUPPORTED = True  # Matplotlib >= 3.7 supports roll in view_init

class PQ3DView:
    def __init__(self, max_age_s: float = 60.0, max_points: int = 4000):
        # Figure / Axes
        self.fig = Figure(figsize=(5, 3), dpi=100, facecolor="#000000")
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Data buffer
        self.buf = deque()
        self.max_age_s = float(max_age_s)
        self.max_points = int(max_points)

        # Spline
        self.use_spline = True
        self.spline_samples = 8  # Catmull–Rom per segment

        # Trail + head
        self.cmap = cm.get_cmap("plasma")
        self._trail = Line3DCollection([], linewidths=1.6, antialiased=True)
        self._trail.set_segments([np.zeros((2, 3))])  # seed
        self._trail.set_alpha(0.0)
        self.ax.add_collection3d(self._trail)
        self._head = self.ax.scatter([], [], [], s=30)

        # View state
        self._initialized_view = False
        self._proj_applied = False
        self._manual_limits = False
        self._xlim = self._ylim = self._zlim = None

        # Events
        self._event_bound = False

        # Preset views
        self._views = list(VIEWS)
        self._view_idx = int(DEFAULT_VIEW_INDEX) % max(1, len(self._views))
        self._temp_proj_override = None  # set by 'Z' key

        # Overlay (help) — visible by default, toggled with 'H'
        self.overlay_visible = True
        self._overlay_artist = None

        self._apply_dark_theme()

    # --------------------------- Appearance --------------------------- #

    def _apply_dark_theme(self):
        ax = self.ax
        self.fig.patch.set_facecolor("#000000")
        ax.set_facecolor("#000000")
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        try:
            ax.set_position([0, 0, 1, 1])
        except Exception:
            pass

        try:
            for a in (ax.xaxis, ax.yaxis, ax.zaxis):
                a.pane.fill = False
                a.pane.set_facecolor((0, 0, 0, 0))
                a.pane.set_edgecolor((1, 1, 1, 0.35))
            ax.grid(True)
            for a in (ax.xaxis, ax.yaxis, ax.zaxis):
                a._axinfo["grid"]["color"] = (1, 1, 1, 0.18)
                a._axinfo["grid"]["linewidth"] = 0.6
        except Exception:
            # Older mpl fallbacks
            for a in (getattr(ax, "w_xaxis", None),
                      getattr(ax, "w_yaxis", None),
                      getattr(ax, "w_zaxis", None)):
                if not a:
                    continue
                try: a.set_pane_color((0, 0, 0, 0))
                except Exception: pass
                try: a.pane_fill = False
                except Exception: pass

        ax.set_xlabel("P [W]", color="#DDDDDD", labelpad=6)
        ax.set_ylabel("Q [VAR]", color="#DDDDDD", labelpad=6)
        ax.set_zlabel("time [s]", color="#DDDDDD", labelpad=6)
        ax.tick_params(colors="#AAAAAA", which="both", labelsize=8)
        try:
            ax.set_box_aspect((1, 1, 0.6))
        except Exception:
            pass

    # ------------------------------ Views ----------------------------- #

    def set_views(self, views_list):
        """Optional external API to replace the preset list at runtime."""
        self._views = list(views_list) if views_list else [{"name":"Default","elev":20,"azim":-35,"roll":0,"proj":"persp"}]
        self._view_idx = 0
        self._apply_current_view()

    def _apply_projection(self, proj):
        ax = self.ax
        try:
            FOCAL_LEN = 0.45  # try 0.35 … 0.6 for stronger perspective
            ax.set_proj_type(proj, focal_length=FOCAL_LEN if proj == "persp" else None)

        except TypeError:
            try:
                ax.set_proj_type(proj)
            except Exception:
                pass
            try:
                if proj == "persp":
                    ax.dist = 4.5  # legacy fallback 3.5 .. 6.0
            except Exception:
                pass
        self._proj_applied = True

    def _apply_current_view(self):
        if not self._views:
            return
        v = self._views[self._view_idx]
        proj = self._temp_proj_override or v.get("proj", "persp")
        self._apply_projection(proj)

        elev = float(v.get("elev", 20))
        azim = float(v.get("azim", -35))
        roll = float(v.get("roll", 0))
        try:
            if DEFAULT_ROLL_SUPPORTED:
                self.ax.view_init(elev=elev, azim=azim, roll=roll)
            else:
                self.ax.view_init(elev=elev, azim=azim)
        except TypeError:
            # older Matplotlib without roll
            self.ax.view_init(elev=elev, azim=azim)

        if self.fig.canvas:
            self.fig.canvas.draw_idle()
        self._update_overlay()

    # --------------------------- Data path --------------------------- #

    def push(self, t_s: float, P: float, Q: float):
        self.buf.append((float(t_s), float(P), float(Q)))
        # prune by age
        tmin = t_s - self.max_age_s
        while self.buf and self.buf[0][0] < tmin:
            self.buf.popleft()
        # prune by count
        while len(self.buf) > self.max_points:
            self.buf.popleft()

    def _arrays(self):
        arr = np.asarray(self.buf, dtype=float)
        x = arr[:, 1]                       # P
        y = arr[:, 2]                       # Q
        z = arr[:, 0] - arr[-1, 0]          # relative time (s)
        step = max(1, len(x) // 1200)
        if step > 1:
            x, y, z = x[::step], y[::step], z[::step]
        return x, y, z

    # ----------------------------- Spline ---------------------------- #

    def _smooth3d(self, x, y, z, samples=None, alpha=0.5):
        if samples is None:
            samples = self.spline_samples
        P = np.column_stack([x, y, z])
        n = len(P)
        if n < 4 or samples < 2:
            return x, y, z

        eps = 1e-12
        out = [P[0]]

        def tj(ti, pi, pj):
            return ti + (np.linalg.norm(pj - pi) ** alpha)

        for i in range(n - 3):
            P0, P1, P2, P3 = P[i], P[i + 1], P[i + 2], P[i + 3]
            t0 = 0.0
            t1 = tj(t0, P0, P1)
            t2 = tj(t1, P1, P2)
            t3 = tj(t2, P2, P3)

            ts = np.linspace(t1, t2, samples, endpoint=False)
            for t in ts:
                t10 = (t1 - t0) or eps
                t21 = (t2 - t1) or eps
                t32 = (t3 - t2) or eps
                t20 = (t2 - t0) or eps
                t31 = (t3 - t1) or eps

                A1 = (t1 - t) / t10 * P0 + (t - t0) / t10 * P1
                A2 = (t2 - t) / t21 * P1 + (t - t1) / t21 * P2
                A3 = (t3 - t) / t32 * P2 + (t - t2) / t32 * P3
                B1 = (t2 - t) / t20 * A1 + (t - t0) / t20 * A2
                B2 = (t3 - t) / t31 * A2 + (t - t1) / t31 * A3
                C  = (t2 - t) / (t2 - t1 + eps) * B1 + (t - t1) / (t2 - t1 + eps) * B2
                out.append(C)

        out.append(P[-1])
        out = np.asarray(out)
        return out[:, 0], out[:, 1], out[:, 2]

    # ----------------------------- Events ---------------------------- #

    def _ensure_events(self):
        if not self._event_bound and self.fig.canvas is not None:
            self.fig.canvas.mpl_connect("scroll_event", self._on_scroll)
            self.fig.canvas.mpl_connect("key_press_event", self._on_key)
            self.fig.canvas.mpl_connect("figure_enter_event", self._on_enter)
            self._event_bound = True

    def _on_enter(self, _event):
        # ensure keyboard focus inside Tk
        try:
            w = self.fig.canvas.get_tk_widget()
            w.focus_set()
        except Exception:
            pass
        if self.overlay_visible:
            self._update_overlay()

    def _on_scroll(self, event):
        if not self.buf:
            return
        step = getattr(event, "step", None)
        zoom_in = (step > 0) if step is not None else (getattr(event, "button", "") == "up")
        factor = 0.9 if zoom_in else 1.1

        # Anchor at newest point (P, Q, z=0)
        _, P, Q = self.buf[-1]
        xc, yc, zc = float(P), float(Q), 0.0

        if self._manual_limits and self._xlim and self._ylim and self._zlim:
            xmin, xmax = self._xlim
            ymin, ymax = self._ylim
            zmin, zmax = self._zlim
        else:
            xmin, xmax = self.ax.get_xlim()
            ymin, ymax = self.ax.get_ylim()
            zmin, zmax = self.ax.get_zlim()

        def zoom_axis(lo, hi, c, f, min_span=1e-9):
            half = max((hi - lo) * 0.5, min_span)
            half *= f
            return c - half, c + half

        xmin, xmax = zoom_axis(xmin, xmax, xc, factor)
        ymin, ymax = zoom_axis(ymin, ymax, yc, factor)
        zmin, zmax = zoom_axis(zmin, zmax, zc, factor)

        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        self.ax.set_zlim(zmin, zmax)
        self._xlim, self._ylim, self._zlim = (xmin, xmax), (ymin, ymax), (zmin, zmax)
        self._manual_limits = True

        if self.fig.canvas is not None:
            self.fig.canvas.draw_idle()

    def _on_key(self, event):
        if not event.key:
            return
        k = event.key.lower()

        if k == "h":
            self.overlay_visible = not self.overlay_visible
            self._update_overlay()
            return

        if k == "z":
            # temporary projection override (persp <-> ortho) for current view
            cur = self._views[self._view_idx]
            base = cur.get("proj", "persp")
            self._temp_proj_override = "ortho" if (self._temp_proj_override or base) == "persp" else "persp"
            self._apply_current_view()
            return

        if k == "v":  # next view
            self._view_idx = (self._view_idx + 1) % len(self._views)
            self._temp_proj_override = None
            self._apply_current_view()
            return

        if k == "b":  # previous view
            self._view_idx = (self._view_idx - 1) % len(self._views)
            self._temp_proj_override = None
            self._apply_current_view()
            return

        # numeric direct-select (1..9)
        if k.isdigit():
            idx = int(k) - 1
            if 0 <= idx < len(self._views):
                self._view_idx = idx
                self._temp_proj_override = None
                self._apply_current_view()
            return

    # --------------------------- Overlay (help) ------------------------ #

    def _overlay_text(self):
        v = self._views[self._view_idx] if self._views else {"name":"N/A","proj":"persp"}
        proj = self._temp_proj_override or v.get("proj", "persp")
        lines = [
            f"View: {v.get('name','N/A')}   Proj: {proj}",
            "1..6: set view   V/B: next/prev   Z: toggle proj   H: help",
            "Wheel: zoom (anchored at newest point)",
        ]
        return "\n".join(lines)

    def _update_overlay(self):
        if not self.overlay_visible:
            if self._overlay_artist is not None:
                try:
                    self._overlay_artist.remove()
                except Exception:
                    pass
                self._overlay_artist = None
            if self.fig.canvas:
                self.fig.canvas.draw_idle()
            return

        txt = self._overlay_text()
        if self._overlay_artist is None:
            self._overlay_artist = self.fig.text(
                0.015, 0.985, txt,
                ha="left", va="top",
                color="#EEEEEE",
                fontsize=9,
                family="monospace",
                linespacing=1.25,
                bbox=dict(
                    facecolor=(0, 0, 0, 0.55),
                    edgecolor=(1, 1, 1, 0.18),
                    boxstyle="round,pad=0.35"
                )
            )
        else:
            self._overlay_artist.set_text(txt)
        if self.fig.canvas:
            self.fig.canvas.draw_idle()

    # ------------------------------ Draw ------------------------------ #

    def draw(self):
        # Ensure events & current view applied
        self._ensure_events()
        if not self._proj_applied:
            self._apply_current_view()

        if not self.buf:
            if self.overlay_visible:
                self._update_overlay()
            return

        x, y, z = self._arrays()
        if self.use_spline and len(x) >= 4:
            x, y, z = self._smooth3d(x, y, z)

        if len(x) > 1:
            pts = np.column_stack([x, y, z])
            segs = np.stack([pts[:-1], pts[1:]], axis=1)

            zc = 0.5 * (z[:-1] + z[1:])
            w = (zc + self.max_age_s) / max(self.max_age_s, 1e-9)
            w = np.clip(w, 0.0, 1.0)

            rgba = self.cmap(w)
            rgba[:, 3] = 0.20 + 0.80 * w
            lws = 0.6 + 2.0 * w

            self._trail.set_segments(segs)
            self._trail.set_color(rgba)
            self._trail.set_linewidths(lws)
            self._trail.set_alpha(1.0)
        else:
            self._trail.set_segments([])
            self._trail.set_alpha(0.0)

        try:
            self._head._offsets3d = ([x[-1]], [y[-1]], [z[-1]])
        except Exception:
            self._head.remove()
            self._head = self.ax.scatter([x[-1]], [y[-1]], [z[-1]], s=30)

        # Axis limits
        if self._manual_limits and self._xlim and self._ylim and self._zlim:
            self.ax.set_xlim(*self._xlim)
            self.ax.set_ylim(*self._ylim)
            self.ax.set_zlim(*self._zlim)
        else:
            px = (x.max() - x.min()) or 1.0
            qx = (y.max() - y.min()) or 1.0
            m = 0.12
            self.ax.set_xlim(x.min() - m * px, x.max() + m * px)
            self.ax.set_ylim(y.min() - m * qx, y.max() + m * qx)
            self.ax.set_zlim(-self.max_age_s, 0)

        # Fill window and keep overlay current
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        try:
            self.ax.set_position([0, 0, 1, 1])
        except Exception:
            pass

        if self.overlay_visible:
            self._update_overlay()

        if self.fig.canvas is not None:
            self.fig.canvas.draw_idle()
