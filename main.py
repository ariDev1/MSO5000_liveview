#main.py

import matplotlib
# Must be set BEFORE importing pyplot or any module that imports pyplot.
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: F401
from matplotlib import pyplot as plt  # noqa: F401

import os
import sys
import argparse
import threading
import tkinter as tk
from tkinter import ttk

# Ensure version.py exists
try:
    os.system("python3 build_version.py")
except Exception:
    # Non-fatal; version.py may be pre-generated
    pass

# --- Lightweight imports that don't trigger side effects ---
import version as V
from utils.debug import attach_debug_widget, start_debug_updater, log_debug, set_debug_level
from gui.layout import create_main_gui
from gui.image_display import attach_image_label, update_image, set_ip, start_screenshot_thread
from gui.activity_monitor import start_meter_thread, draw_meter
from scpi.interface import connect_scope, safe_query
from scpi.loop import start_scpi_loop
from scpi.data import scpi_data
import app.app_state as app_state

# NOTE: Tab setup functions are imported lazily inside build_tabs() to keep import order clean.

# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true", help="Show version number")
    parser.add_argument("--ip", type=str, help="Scope IP (overrides interactive prompt)")
    parser.add_argument("--samples", type=int, help="Override number of waveform points (default: project config)")
    parser.add_argument("--noMarquee", action="store_true", help="Disable the marquee text at the top")
    return parser.parse_args(argv)


# ----------------------------------------------------------------------------
# Scope connection + initial data capture
# ----------------------------------------------------------------------------

def connect_and_prepare(ip: str):
    """Connect to scope, stash globals, and probe a few info fields."""
    scope = connect_scope(ip)
    set_ip(ip)
    scpi_data["ip"] = ip

    if not scope:
        print("❌ Could not connect to scope — exiting.")
        return None

    # Expose scope globally for modules that rely on app_state
    app_state.scope = scope
    app_state.scope_ip = ip

    # Save IDN + get frequency reference (best-effort)
    try:
        idn = safe_query(scope, "*IDN?")
        os.makedirs("utils", exist_ok=True)
        with open("utils/idn.txt", "w") as f:
            f.write(idn.strip())
        log_debug(f"📝 IDN saved to utils/idn.txt: {idn.strip()}")
    except Exception as e:
        log_debug(f"⚠️ Could not save IDN info to utils/idn.txt: {e}")

    try:
        freq_ref = safe_query(scope, ":POWer:QUALity:FREQreference?", "N/A")
        log_debug(f"📡 Frequency Reference: {freq_ref}")
        scpi_data["freq_ref"] = freq_ref
    except Exception as e:
        log_debug(f"⚠️ Could not get frequency reference: {e}")

    return scope


# ----------------------------------------------------------------------------
# GUI wiring helpers
# ----------------------------------------------------------------------------

def build_root(ip: str):
    root = tk.Tk()
    root.title(f"{V.APP_NAME} {V.VERSION} [{V.GIT_COMMIT}] 🢒 {ip}")
    root.geometry("1200x800")
    root.minsize(800, 600)

    main_frame = tk.Frame(root, bg="#1a1a1a")
    main_frame.pack(fill="both", expand=True)
    return root, main_frame


def build_topbar(parent, no_marquee: bool):
    """Top row with marquee and action buttons. Returns (toggle_btn, marquee_widget)."""
    button_row = tk.Frame(parent, bg="#1a1a1a")
    button_row.pack(fill="x", padx=10, pady=(5, 0))
    button_row.columnconfigure(0, weight=1)
    button_row.columnconfigure(1, weight=0)

    marquee_frame = tk.Frame(button_row, bg="#1a1a1a")
    marquee_frame.grid(row=0, column=0, sticky="ew")

    button_frame = tk.Frame(button_row, bg="#1a1a1a")
    button_frame.grid(row=0, column=1, sticky="e")

    # Optional marquee
    marquee_widget = None
    if not no_marquee:
        from gui.marquee import attach_marquee
        marquee_widget = attach_marquee(
            marquee_frame,
            file_path="marquee.txt",
            url="https://aether-research.institute/MSO5000/marquee.txt",
        )

    toggle_btn = ttk.Button(button_frame, text="🗗 Hide", style="TButton")
    toggle_btn.pack(side="left", padx=(10, 5))

    return toggle_btn, marquee_widget, button_row


def build_screenshot_strip(parent, notebook):
    """Screenshot image area above tabs; returns (image_frame, img_label, visible_flag)."""
    image_frame = tk.Frame(parent, bg="#1a1a1a")
    img_label = tk.Label(image_frame, bg="#1a1a1a")
    img_label.pack()

    # Place above tabs
    image_frame.pack(before=notebook, fill="x", pady=5)

    attach_image_label(img_label)
    # Periodic update; thread captures file while Tk loop swaps image
    update_image(parent.winfo_toplevel())
    start_screenshot_thread()

    return image_frame, img_label, [True]


def start_activity_meter(main_frame):
    """Create and start the animated activity meter."""
    activity_meter = tk.Canvas(main_frame, height=10, bg="#181818", highlightthickness=0)
    activity_meter.pack(fill="x", padx=10, pady=(4, 0))

    meter_state = {"level": 0.0, "phase": 0}
    meter_lock = threading.Lock()
    threading.Thread(target=start_meter_thread, args=(app_state, meter_state, meter_lock), daemon=True).start()

    update_id = [None]

    def update_meter():
        # Guard for shutdown/teardown
        try:
            if getattr(app_state, "is_shutting_down", False):
                return
            if not activity_meter.winfo_exists():
                return
            with meter_lock:
                level = meter_state["level"]
                phase = meter_state["phase"]
            draw_meter(activity_meter, level, phase)
        except tk.TclError:
            return
        try:
            if activity_meter.winfo_exists() and not getattr(app_state, "is_shutting_down", False):
                update_id[0] = activity_meter.after(50, update_meter)
        except tk.TclError:
            return

    update_meter()
    return activity_meter, update_id


# ----------------------------------------------------------------------------
# Tabs and Debug pane
# ----------------------------------------------------------------------------

def build_tabs(main_frame, ip, root):
    """Create tabs and wire their setup functions; returns (tabs, notebook, power_shutdown, extras)."""
    tabs, notebook = create_main_gui(main_frame, ip)

    # Lazy imports to avoid heavy imports before Tk exists
    from gui.licenses import setup_licenses_tab
    from gui.system_info import setup_system_info_tab
    from gui.channel_info import setup_channel_tab
    from gui.logging_controls import setup_logging_tab
    from gui.scpi_console import setup_scpi_tab
    from gui.power_analysis import setup_power_analysis_tab
    from gui.bh_curve import setup_bh_curve_tab
    # Harmonics/THD tab is project-specific and may not exist in older builds
    try:
        from gui.harmonics_tab import setup_harmonics_tab
    except Exception:
        setup_harmonics_tab = None  # noqa: F401

    # Wire tabs
    setup_licenses_tab(tabs["Licenses"], ip, root)
    setup_system_info_tab(tabs["System Info"], root)
    setup_channel_tab(tabs["Channel Data"], ip, root)
    setup_logging_tab(tabs["Long-Time Measurement"], ip, root)
    setup_scpi_tab(tabs["SCPI"], ip)

    setup_power_analysis_tab(tabs["Power Analysis"], ip, root)
    power_tab = tabs["Power Analysis"]
    power_shutdown = getattr(power_tab, "_shutdown", lambda: None)

    setup_bh_curve_tab(tabs["BH Curve"], ip, root)

    if setup_harmonics_tab and "Harmonics/THD" in tabs:
        setup_harmonics_tab(tabs["Harmonics/THD"], ip, root)

    # Debug tab widgets
    debug_frame = tabs["Debug Log"]
    _build_debug_pane(debug_frame, root)

    return tabs, notebook, power_shutdown


def _build_debug_pane(debug_frame, root):
    debug_level_frame = tk.Frame(debug_frame, bg="#2d2d2d")
    debug_level_frame.pack(fill="x", padx=5, pady=(5, 0))

    tk.Label(debug_level_frame, text="Debug Output Level:",
             bg="#2d2d2d", fg="#bbbbbb", font=("TkDefaultFont", 9)).pack(side="left", padx=(10, 10))

    tk.Frame(debug_level_frame, bg="#2d2d2d").pack(side="left", expand=True, fill="x")

    debug_var = tk.StringVar(value="FULL")

    def on_debug_level_change():
        set_debug_level(debug_var.get())

    for level, label in [("FULL", "🛠 Full"), ("MINIMAL", "⚠️ Minimal")]:
        tk.Radiobutton(
            debug_level_frame, text=label, variable=debug_var, value=level,
            command=on_debug_level_change,
            bg="#2d2d2d", fg="#ffffff", selectcolor="#555555",
            activebackground="#333333", indicatoron=False,
            relief="raised", width=10
        ).pack(side="left", padx=5)

    text_widget = tk.Text(
        debug_frame, font=("Courier", 9), height=100,
        bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
        selectbackground="#333333", state=tk.DISABLED
    )
    text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar = ttk.Scrollbar(debug_frame, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")

    attach_debug_widget(text_widget)
    start_debug_updater(root)
    log_debug("🔧 Debug log ready.")


# ----------------------------------------------------------------------------
# Shutdown plumbing
# ----------------------------------------------------------------------------

def make_shutdown(root, activity_after_id_ref, activity_canvas, power_shutdown, tabs, toggle_btn_ref, marquee_widget):
    """Build a robust shutdown handler that avoids Tcl errors."""

    def shutdown():
        log_debug("🛑 Shutdown requested")

        # Prevent double entry
        if getattr(app_state, "is_shutting_down", False):
            return
        app_state.is_shutting_down = True

        # Component-specific cleanup (wrap to avoid cascade failures)
        try:
            power_shutdown()
        except Exception:
            pass

        # BH tab (best-effort)
        try:
            bh_tab = tabs.get("BH Curve")
            if bh_tab and hasattr(bh_tab, "_shutdown"):
                bh_tab._shutdown()
        except Exception:
            pass

        # Long-time logger
        try:
            from logger.longtime import stop_logging
            stop_logging()
        except Exception:
            pass

        # Cancel our local repeating after() for the activity meter
        try:
            if activity_after_id_ref[0] is not None and activity_canvas.winfo_exists():
                activity_canvas.after_cancel(activity_after_id_ref[0])
                activity_after_id_ref[0] = None
        except Exception:
            pass

        # Attempt to cancel screenshot updates (only if helper exists)
        try:
            from gui.image_display import cancel_image_updates  # optional helper
            try:
                cancel_image_updates(root)  # type: ignore
            except Exception:
                pass
        except Exception:
            pass

        # Cancel marquee timers if widget exposes _shutdown()
        try:
            if marquee_widget and hasattr(marquee_widget, "_shutdown"):
                marquee_widget._shutdown()
        except Exception:
            pass

        # Stop Tk's internal repeaters (prevents "...scroll" errors during teardown)
        try:
            root.tk.call("tk", "cancelrepeat")
        except Exception:
            pass

        # Leave VISA closing to the finally block after mainloop exits
        try:
            root.quit()
        except Exception:
            pass

    return shutdown


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv)

    if args.version:
        print(f"{V.APP_NAME} {V.VERSION}")
        print(f"Git Commit: {V.GIT_COMMIT}")
        print(f"Build Date: {V.BUILD_DATE}")
        sys.exit(0)

    # Optional override of WAV_POINTS (keeps existing behavior)
    if args.samples is not None:
        try:
            import config
            config.WAV_POINTS = args.samples
            print(f"🔧 Overridden WAV_POINTS to {args.samples}")
        except Exception as e:
            print(f"⚠️ Could not override WAV_POINTS: {e}")

    # Scope IP: CLI has priority; otherwise prompt (preserves current UX)
    ip = args.ip
    if not ip:
        ip = input("Enter RIGOL MSO5000 IP address: ").strip()
    if not ip:
        print("🔌 No IP provided")
        return

    # Connect & stash
    scope = connect_and_prepare(ip)
    if scope is None:
        return

    # Start SCPI poll loop (it uses its own connection internally)
    start_scpi_loop(ip if ip else "USB")

    # GUI
    root, main_frame = build_root(ip)

    # Activity meter
    activity_canvas, activity_after_id = start_activity_meter(main_frame)

    # Top bar (marquee + buttons)
    toggle_btn, marquee_widget, _ = build_topbar(main_frame, no_marquee=args.noMarquee)

    # Tabs (and debug pane)
    tabs, notebook, power_shutdown = build_tabs(main_frame, ip, root)

    # Screenshot strip above tabs
    image_frame, img_label, img_visible = build_screenshot_strip(main_frame, notebook)

    # Toggle button wiring for screenshot area
    def toggle_image():
        if img_visible[0]:
            image_frame.pack_forget()
            toggle_btn.config(text="🗖 Show")
        else:
            image_frame.pack(before=notebook, fill="x", pady=5)
            toggle_btn.config(text="🗗 Hide")
        img_visible[0] = not img_visible[0]

    toggle_btn.config(command=toggle_image)

    # Add Exit button on the right of top bar
    # (Placed here to access shutdown closure)
    btn_row_children = toggle_btn.master  # the button_frame
    shutdown_btn = ttk.Button(btn_row_children, text="⏻ Exit", style="TButton")

    shutdown = make_shutdown(
        root=root,
        activity_after_id_ref=activity_after_id,
        activity_canvas=activity_canvas,
        power_shutdown=power_shutdown,
        tabs=tabs,
        toggle_btn_ref=toggle_btn,
        marquee_widget=marquee_widget,
    )
    shutdown_btn.config(command=shutdown)
    shutdown_btn.pack(side="left", padx=(0, 5))

    # WM close button should run our shutdown
    root.protocol("WM_DELETE_WINDOW", shutdown)

    # Mainloop + robust teardown
    try:
        root.mainloop()
    finally:
        # Close primary VISA session last (avoid leaving socket open)
        try:
            from scpi.interface import scpi_lock
            with scpi_lock:
                if app_state.scope:
                    try:
                        app_state.scope.close()
                    except Exception:
                        pass
                    app_state.scope = None
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
