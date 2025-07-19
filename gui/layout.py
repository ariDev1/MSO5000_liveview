import tkinter as tk
from tkinter import ttk

DARK_BG = "#1a1a1a"
DARK_FG = "#ffffff"
DARK_SELECT = "#333333"
DARK_TAB_BG = "#2d2d2d"

def setup_styles():
    style = ttk.Style()
    style.theme_use('clam')
    style.layout("TButton", [('Button.focus', {'children': [('Button.padding', {'children': [('Button.label', {'sticky': 'nswe'})]})]})])
    style.configure('TNotebook', background=DARK_BG, borderwidth=0, relief='flat')
    style.configure('TNotebook.Tab', background=DARK_TAB_BG, foreground=DARK_FG,
                    padding=[10, 5], borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', DARK_SELECT)])
    style.configure('TFrame', background=DARK_BG)
    
    # New: Consistent dark styling
    style.configure('TLabel', background=DARK_BG, foreground=DARK_FG)
    style.configure('TButton', background=DARK_TAB_BG, foreground=DARK_FG, focuscolor=DARK_TAB_BG)
    style.map('TButton',
              background=[('active', DARK_SELECT)],
              foreground=[('active', '#ffffff')])
    style.configure('TLabelframe', background=DARK_BG, foreground=DARK_FG)
    style.configure('TLabelframe.Label', background=DARK_BG, foreground=DARK_FG)

def create_main_gui(container, ip):
    root = container.winfo_toplevel()  # ✅ define root from container
    root.title(f"MSO5000 Live Monitor - {ip}")
    root.geometry("1200x800")
    root.minsize(800, 600)
    root.configure(bg=DARK_BG)

    setup_styles()

    # Tabs
    notebook = ttk.Notebook(container)
    notebook.pack(fill="both", expand=True, padx=10, pady=5)

    tabs = {}

    for tab_name in ["System Info", "Channel Data", "Debug Log", "Licenses", "Long-Time Measurement", "SCPI"]:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        tabs[tab_name] = frame

    return tabs, notebook
