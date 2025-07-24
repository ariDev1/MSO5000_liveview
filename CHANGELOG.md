# 📖 Changelog

All notable changes to this project are documented here.

---

## v0.9.6 (2025-07-24)

### 🐳 Docker Integration and GUI Access
- 🖥️ Full X11 GUI support inside Docker
  - `entrypoint.sh` detects `$DISPLAY` and `/tmp/.X11-unix`
  - Friendly error message if X11 access is blocked (e.g., missing `xhost`)
  - Works on X11 and XWayland setups (GNOME, KDE, etc.)
- 🐚 Improved Docker CLI usability
  - Mount `oszi_csv/` folder easily from host
  - Performance improvements from clean runtime

### ⚡ Power Analyzer Refinements
- 📡 Frequency reference (`Reference: VOLT` or `CURR`) shown live in GUI
- 🧠 Compact layout and right-aligned labels for better readability
- 🛑 Power analyzer is disabled while long-time logging is active (conflict-safe)
- 📊 Frequency reference printed only once to log at startup

### 🛠️ Versioning & Build Metadata
- `build_version.py` now auto-generates `version.py` with:
  - Git tag (e.g. `v0.9.6`)
  - Commit hash
  - Build timestamp (UTC)
- `--version` CLI shows exact release identity

### 📦 GitHub Actions CI/CD
- Docker image auto-built and pushed on:
  - Push to `master`
  - Any `v*` tag (e.g., `v0.9.6`)
- Produces both `:latest` and `:v0.9.6` Docker tags

---

## v0.9.5 (2025-07-21)

- ⚡ **Power Analyzer Upgrade**
  - Now displays `Reference: CURR` or `Reference: VOLT` based on SCPI readout
  - Reference source appears live in GUI beside channel selection
  - Clean handling of `:POWer:QUALity:FREQreference?` with fallback if unavailable

- 🖥️ **GUI Enhancements**
  - Compact layout for Voltage/Current/Reference fields to support smaller screen widths
  - Input fields now scale with cleaner spacing and shorter labels
  - Adaptive GUI padding and right-aligned labels to maximize clarity

- 📉 **Improved Plot Behavior**
  - Live PQ plot now tracks trailing values cleanly even in auto-refresh mode
  - Enhanced visibility of PF Angle vector

- 🐞 **Fixes and Logging**
  - Avoids SCPI spam and I/O errors from repeated FREQreference queries
  - Debug log now shows Freq.Ref status clearly and only once at connect time
  - Minor improvements to waveform data error handling

---

## v0.9.4 (2025-07-19)

- 🧪 **New SCPI Tab**
  - Added a dedicated SCPI tab with manual command input
  - Response output area with scrollback and timestamped logs
  - Optional right-side command list (`scpi_command_list.txt`) lets users select known SCPI commands
  - Double-click or “➡ Insert into Input” button to load from list
  - Handles I/O errors safely and logs all SCPI activity

- 🧱 **UI Improvements**
  - Fixed vertical overflow in SCPI tab — output box no longer hides buttons
  - Sidebar list resizes correctly with window

- 🐞 **Debug Log Integration**
  - All SCPI commands and errors now appear in the Debug tab
  - Uses `log_debug()` for traceability

- 🧼 Minor cleanup:
  - Removed layout duplication from button handlers
  - Improved resilience against missing files (e.g., `scpi_command_list.txt`)

---

## v0.9.3 (2025-07-17)

- 🎨 **UI Consistency Improvements**
  - Unified layout across all tabs (System Info, Channel Data, Long-Time Measurement)
  - Equal-width layout for Measurement Settings and Logging Status frames
  - Vertically stacked buttons for consistent interaction layout

- 📋 **New Features**
  - System Info tab: "📋 Copy System Info" button
  - Channel Data tab: "📋 Copy Settings" and "📋 Copy CSV Data" buttons
  - Long-Time tab: scrollable logging output replaces previous static label

- 🧠 **Improved Logic & Interactivity**
  - Smart button state handling (Start, Pause/Resume, Stop) based on session status
  - Status log updated live and auto-scrolls
  - Clipboard-safe formatting across tabs

- 🐞 **Fixes**
  - Resolved `NameError` from obsolete `log_status`
  - Scroll jumps eliminated during auto-updates
  - Clipboard actions and CSV export no longer conflict

---

## v0.9.2 (2025-07-16)

- ➕ Long-time measurement tab:
  - Pause/resume logging
  - Manual stop button
  - All measurements saved in a **single CSV** file
  - Timestamp added per row
- 📏 Added performance tip section to UI
- 🐞 Improved stability of SCPI query loop
- 🔒 Added lock for waveform exports
