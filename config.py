"""
===============================================================================
 MSO5000 Liveview — Configuration File
===============================================================================

This file contains user-tunable settings for timing, waveform resolution,
and SCPI command handling. Adjust values here to control performance,
responsiveness, and compatibility with your oscilloscope.

SETTINGS YOU MAY EDIT:
- INTERVALL_BILD  : Interval (seconds) between VNC screenshot captures.
                    Lower = smoother live screen, but higher CPU/network load.
- INTERVALL_SCPI  : Interval (seconds) between SCPI queries for status/data.
                    Lower = more frequent updates, but heavier load on scope.
- WAV_POINTS      : Number of waveform points to request from the scope.
                    1000 is safe for all models; higher values may improve
                    resolution but can slow transfers or fail on older scopes.

DO NOT CHANGE UNLESS YOU KNOW WHAT YOU ARE DOING:
- BLACKLISTED_COMMANDS : List of SCPI queries known to cause instability,
                         hangs, or unsupported responses on Rigol MSO5000.
                         Only edit if you are adding new verified problem
                         commands. This list protects the stability of the app.

General Guidance:
- If you want smoother updates, reduce INTERVALL_BILD / INTERVALL_SCPI, but
  monitor CPU and scope load.
- If you need more detailed waveform analysis, try increasing WAV_POINTS.
- Avoid editing the blacklist unless debugging SCPI behavior.

===============================================================================
"""

# === User-adjustable refresh intervals ===
INTERVALL_BILD = 2   # seconds between VNC screenshot updates
INTERVALL_SCPI = 4   # seconds between SCPI queries

# === Waveform resolution ===
WAV_POINTS = 1000    # safe default; higher = more resolution, but slower

# === SCPI blacklist ===
# These commands are either unsupported, redundant, or known to cause hangs.
BLACKLISTED_COMMANDS = [
    ":SYSTem:UPTime?",
    ":SYSTem:TEMPerature?",
    ":SYSTem:OPTions?",
    ":TIMebase:HREFerence?",
    ":ACQuire:MODE?",
    # ":ACQuire:TYPE?",   # optional
    # ":TRIGger:HOLDoff?",

    ":WAVeform:YINCrement?",
    ":WAVeform:YORigin?",
    ":WAVeform:YREFerence?",

    # MATH probe queries are unsupported on MSO5000 → block explicitly
    ":MATH1:PROB?",
    ":MATH2:PROB?",
    ":MATH3:PROB?",
    ":MATH4:PROB?",
    # (optional variants if Rigol firmware ever changes spelling)
    # ":MATH1:PROBe?", ":MATH2:PROBe?", ":MATH3:PROBe?", ":MATH4:PROBe?",
]