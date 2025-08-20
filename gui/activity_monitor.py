# gui/activity_monitor.py

import threading
import time
import app.app_state as app_state

def start_meter_thread(app_state, meter_state, meter_lock):
    N_LEDS = 16
    while True:
        level = 0.05
        if getattr(app_state, "is_logging_active", False):
            level += 0.4
        if getattr(app_state, "is_power_analysis_active", False):
            level += 0.4
        if getattr(app_state, "is_scpi_busy", False):
            level += 0.2
        # ...add more as needed...
        level = min(level, 1.0)
        with meter_lock:
            meter_state["level"] = level
            meter_state["phase"] = (meter_state["phase"] + 1) % N_LEDS
        time.sleep(0.08)

def draw_meter(canvas, level, phase, N_LEDS=16, DOT_SPACING=8, DOT_RADIUS=2, X_PAD=6):
    canvas.delete("all")
    h = canvas.winfo_height()
    base_y = h // 2
    n_lit = int(level * N_LEDS)
    for i in range(N_LEDS):
        x = X_PAD + i * DOT_SPACING
        if i < n_lit:
            # Red zone: rightmost 3, if we're that far
            if n_lit >= N_LEDS - 2 and i >= N_LEDS - 3:
                fill = "#e44"      # Red
            elif n_lit >= N_LEDS - 5 and i >= N_LEDS - 6:
                fill = "#fd0"      # Yellow
            else:
                fill = "#4f6"      # Green
        else:
            fill = "#222"
        # Animate yellow pulse when bar is maxed
        if n_lit == N_LEDS and (i + phase) % N_LEDS == 0:
            fill = "#ff0"
        canvas.create_oval(
            x - DOT_RADIUS, base_y - DOT_RADIUS, x + DOT_RADIUS, base_y + DOT_RADIUS,
            fill=fill, outline="#222"
        )
