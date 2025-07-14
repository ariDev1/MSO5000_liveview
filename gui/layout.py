import tkinter as tk
from tkinter import ttk

DARK_BG = "#1a1a1a"
DARK_FG = "#ffffff"
DARK_SELECT = "#333333"
DARK_TAB_BG = "#2d2d2d"

def setup_styles():
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('TNotebook', background=DARK_BG, borderwidth=0, relief='flat')
    style.configure('TNotebook.Tab', background=DARK_TAB_BG, foreground=DARK_FG,
                    padding=[10, 5], borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', DARK_SELECT)])
    style.configure('TFrame', background=DARK_BG, borderwidth=0)

def create_main_gui(root):
    root.title("RIGOL MSO5000 Live Monitor")
    root.geometry("1200x800")
    root.minsize(800, 600)
    root.configure(bg=DARK_BG)

    setup_styles()

    # Tabs
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=5)

    tabs = {}

    for tab_name in ["System Info", "Channel Data", "Debug Log", "Licenses", "Long-Time Measurement"]:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        tabs[tab_name] = frame

    return tabs
