# gui/layout.py

import tkinter as tk
from tkinter import ttk
import version as V

DARK_BG = "#1a1a1a"
DARK_FG = "#ffffff"
DARK_SELECT = "#333333"
DARK_TAB_BG = "#2d2d2d"
DARK_TAB_ACTIVE = "#444444"
DARK_TAB_SELECTED = "#1a1a1a"

def setup_styles():
    style = ttk.Style()
    style.theme_use('clam')
    style.layout("TButton", [('Button.focus', {'children': [('Button.padding', {'children': [('Button.label', {'sticky': 'nswe'})]})]})])
    style.configure('TNotebook', background=DARK_BG, borderwidth=0, relief='flat')
    style.configure('TNotebook.Tab', background=DARK_TAB_BG, foreground=DARK_FG,
                    padding=[10, 5], borderwidth=0)
    
    style.configure('TFrame', background=DARK_BG)
    style.map('TNotebook.Tab',
        background=[
            ('selected', DARK_TAB_SELECTED),
            ('active', DARK_TAB_ACTIVE),
            ('!selected', DARK_TAB_BG)
        ],
        foreground=[
            ('selected', '#ffffff'),
            ('active', '#ffffff'),
            ('!selected', DARK_FG)
        ]
    )
    # New: Consistent dark styling
    style.configure('TLabel', background=DARK_BG, foreground=DARK_FG)
    style.configure('TButton', background=DARK_TAB_BG, foreground=DARK_FG, focuscolor=DARK_TAB_BG)
    style.map('TButton',
              background=[('active', DARK_SELECT)],
              foreground=[('active', '#ffffff')])
    style.configure('TLabelframe', background=DARK_BG, foreground=DARK_FG)
    style.configure('TLabelframe.Label', background=DARK_BG, foreground=DARK_FG)

    # Custom style for refresh indicator
    style.configure("Refresh.TCheckbutton",
        background=DARK_TAB_BG,
        foreground=DARK_FG,
        font=("TkDefaultFont", 10),
        padding=6
    )

    style.map("Refresh.TCheckbutton",
        background=[
            ("selected", "#882222"),
            ("active", "#aa3333"),
            ("!selected", DARK_TAB_BG)
        ],
        foreground=[
            ("selected", "#ffffff"),
            ("active", "#ffffff"),
            ("!selected", DARK_FG)
        ]
    )
    # Custom style for DC Check indicator
    style.configure("DC.TCheckbutton",
        background=DARK_TAB_BG,
        foreground=DARK_FG,
        font=("TkDefaultFont", 10),
        padding=6
    )

    style.map("DC.TCheckbutton",
        background=[
            ("selected", "#226688"),
            ("active", "#3388aa"),
            ("!selected", DARK_TAB_BG)
        ],
        foreground=[
            ("selected", "#ffffff"),
            ("active", "#ffffff"),
            ("!selected", DARK_FG)
        ]
    )
    # Custom style for Action indicator
    style.configure("Action.TButton",
        background=DARK_TAB_BG,
        foreground=DARK_FG,
        padding=6,
        font=("TkDefaultFont", 10)
    )

    style.map("Action.TButton",
        background=[
            ("active", DARK_SELECT)
        ],
        foreground=[
            ("active", "#ffffff")
        ]
    )

    style.configure("SCPI.TButton",
        background=DARK_TAB_BG,
        foreground=DARK_FG,
        padding=6,
        font=("TkDefaultFont", 10)
    )
    style.map("SCPI.TButton",
        background=[("active", "#aa333")],
        foreground=[("active", "#ffffff")]
    )

    # Grouped sections for BH inputs
    style.configure("Group.TLabelframe",
        background=DARK_BG,
        foreground=DARK_FG)
    style.configure("Group.TLabelframe.Label",
        background=DARK_BG,
        foreground="#dddddd",
        font=("TkDefaultFont", 10, "bold"))

    # Subtle card container (used under some frames)
    style.configure("Card.TFrame",
        background="#202020")
    style.configure("TEntry",
        fieldbackground="#111111",
        foreground="#ffffff")
    style.configure("TCombobox",
        fieldbackground="#111111",
        background=DARK_TAB_BG,
        foreground=DARK_FG)
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", "#222222")  # your desired dark background
        ],
        foreground=[
            ("readonly", "#ffffff")  # your desired visible text color
        ]
    )
    style.configure(
        "Dark.Treeview",
        background=DARK_BG, fieldbackground=DARK_BG,
        foreground=DARK_FG, bordercolor="#333333",
        rowheight=22
    )
    style.map(
        "Dark.Treeview",
        background=[("selected", "#2a72b5")],
        foreground=[("selected", "#ffffff")]
    )
    style.configure(
        "Dark.Treeview.Heading",
        background="#222222", foreground=DARK_FG,
        relief="flat"
    )
    style.configure(
        "Dark.TSpinbox",
        fieldbackground="#111111", background=DARK_BG, foreground=DARK_FG
    )
    style.configure(
        "Dark.TCheckbutton",
        background=DARK_BG, foreground=DARK_FG
    )

def create_main_gui(container, ip):
    root = container.winfo_toplevel()
    root.configure(bg=DARK_BG)

    setup_styles()

    # Tabs
    notebook = ttk.Notebook(container)
    notebook.pack(fill="both", expand=True, padx=10, pady=5)

    tabs = {}

    for tab_name in ["System Info", "Licenses", "Debug Log", "Channel Data", "Long-Time Measurement", "Power Analysis", "BH Curve", "Harmonics/THD", "Noise Inspector", "SCPI"]:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        tabs[tab_name] = frame

    return tabs, notebook
