# gui/power/pq3d_view.py
# UI-only 3D PQ viewer: plots (P(t), Q(t), t) as a smooth, time-colored trail.

from collections import deque
import numpy as np
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import matplotlib.cm as cm

# ---- Default camera tuned for the look in your screenshot ----
# If you want to nudge it, just tweak these 3 numbers.
DEFAULT_ELEV = 12     # vertical tilt
DEFAULT_AZIM = -30    # rotation around vertical axis
DEFAULT_ROLL = None   # requires matplotlib >= 3.7; otherwise ignored


class PQ3DView:
    def __init__(self, max_age_s: float = 60.0, max_points: int = 4000):
        # Figure/axes
        self.fig = Figure(figsize=(5, 3), dpi=100, facecolor="#000000")
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Data buffer & limits
        self.buf = deque()
        self.max_age_s = float(max_age_s)
        self.max_points = int(max_points)

        # Spline options
        self.use_spline = True
        self.spline_samples = 8  # points per Catmull–Rom segment

        # Gradient trail collection
        self.cmap = cm.get_cmap("plasma")
        self._trail = Line3DCollection([], linewidths=1.6, antialiased=True)
        self._trail.set_segments([np.zeros((2, 3))])  # seed; avoids autoscale crash
        self._trail.set_alpha(0.0)  # hidden until data arrives
        self.ax.add_collection3d(self._trail)

        # Head marker
        self._head = self.ax.scatter([], [], [], s=30)

        # Camera / projection init flags
        self._initialized_view = False
        self._proj_applied = False

        # Manual zoom state (preserve user zoom across draws)
        self._manual_limits = False
        self._xlim = self._ylim = self._zlim = None

        # Event binding state
        self._event_bound = False

        # Projection preferences
        self.proj_type = "persp"     # 'persp' or 'ortho'
        self.focal_length = 0.9

        # Apply dark, pane-less theme
        self._apply_dark_theme()

    # ---------------------------- Appearance ---------------------------- #

    def _apply_dark_theme(self):
        ax = self.ax
        self.fig.patch.set_facecolor("#000000")
        ax.set_facecolor("#000000")
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        try:
            ax.set_position([0, 0, 1, 1])
        except Exception:
            pass

        # Remove pane fill (keep only lines)
        removed = False
        try:
            for a in (ax.xaxis, ax.yaxis, ax.zaxis):
                a.pane.fill = False
                a.pane.set_facecolor((0, 0, 0, 0))
                a.pane.set_edgecolor((1, 1, 1, 0.35))
            removed = True
        except Exception:
            pass
        if not removed:
            for a in (getattr(ax, "w_xaxis", None),
                      getattr(ax, "w_yaxis", None),
                      getattr(ax, "w_zaxis", None)):
                if a is None:
                    continue
                try: a.set_pane_color((0, 0, 0, 0))
                except Exception: pass
                try: a.pane_fill = False
                except Exception: pass
                try:
                    info = a._axinfo
                    info["pane_color"] = (0, 0, 0, 0)
                    info["pane_fill"] = False
                except Exception:
                    pass

        # Labels/ticks
        ax.set_xlabel("P [W]", color="#DDDDDD", labelpad=6)
        ax.set_ylabel("Q [VAR]", color="#DDDDDD", labelpad=6)
        ax.set_zlabel("time [s]", color="#DDDDDD", labelpad=6)
        ax.tick_params(colors="#AAAAAA", which="both", labelsize=8)

        # Subtle grid
        try:
            ax.grid(True)
            for a in (ax.xaxis, ax.yaxis, ax.zaxis):
                a._axinfo["grid"]["color"] = (1, 1, 1, 0.18)
                a._axinfo["grid"]["linewidth"] = 0.6
        except Exception:
            pass

        # Pleasant shape
        try:
            ax.set_box_aspect((1, 1, 0.6))
        except Exception:
            pass

    def _apply_projection(self):
        """Apply perspective/orthographic projection once, with fallbacks."""
        ax = self.ax
        try:
            ax.set_proj_type(self.proj_type, focal_length=self.focal_length)
        except TypeError:
            try:
                ax.set_proj_type(self.proj_type)
            except Exception:
                pass
            try:
                if self.proj_type == "persp":
                    ax.dist = 7  # fallback for older MPL
            except Exception:
                pass
        self._proj_applied = True

    def _apply_default_camera(self):
        """Set the default camera to match the screenshot-like view."""
        try:
            # Newer Matplotlib supports roll
            self.ax.view_init(elev=DEFAULT_ELEV, azim=DEFAULT_AZIM, roll=DEFAULT_ROLL)
        except TypeError:
            # Older versions: no roll
            self.ax.view_init(elev=DEFAULT_ELEV, azim=DEFAULT_AZIM)

    # ---------------------------- Data path ---------------------------- #

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

        step = max(1, len(x) // 1200)       # decimate
        if step > 1:
            x, y, z = x[::step], y[::step], z[::step]
        return x, y, z

    # ---------------------------- Spline ---------------------------- #

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
                C = (t2 - t) / (t2 - t1 + eps) * B1 + (t - t1) / (t2 - t1 + eps) * B2
                out.append(C)

        out.append(P[-1])
        out = np.asarray(out)
        return out[:, 0], out[:, 1], out[:, 2]

    # ---------------------------- Events ---------------------------- #

    def _ensure_events(self):
        if not self._event_bound and self.fig.canvas is not None:
            self.fig.canvas.mpl_connect("scroll_event", self._on_scroll)
            self._event_bound = True

    def _on_scroll(self, event):
        if not self.buf:
            return

        step = getattr(event, "step", None)
        if step is not None:
            zoom_in = step > 0
        else:
            zoom_in = (getattr(event, "button", "") == "up")

        factor = 0.9 if zoom_in else 1.1

        # Anchor at newest point (P, Q, z=0)
        t, P, Q = self.buf[-1]
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

        if zmax > 0:  # keep "now" at 0
            dz = zmax - 0.0
            zmax -= dz
            zmin -= dz

        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        self.ax.set_zlim(zmin, zmax)
        self._xlim, self._ylim, self._zlim = (xmin, xmax), (ymin, ymax), (zmin, zmax)
        self._manual_limits = True

        if self.fig.canvas is not None:
            self.fig.canvas.draw_idle()

    # ---------------------------- Draw ---------------------------- #

    def draw(self):
        if not self.buf:
            return

        self._ensure_events()
        if not self._proj_applied:
            self._apply_projection()

        # Apply your screenshot-like default exactly once; user rotations persist
        if not self._initialized_view:
            self._apply_default_camera()
            self._initialized_view = True

        x, y, z = self._arrays()
        if self.use_spline and len(x) >= 4:
            x, y, z = self._smooth3d(x, y, z)

        # Gradient trail
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

        # Head
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

        # Keep plot filling the window
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        try:
            self.ax.set_position([0, 0, 1, 1])
        except Exception:
            pass

        if self.fig.canvas is not None:
            self.fig.canvas.draw_idle()
