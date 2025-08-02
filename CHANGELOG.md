# 📖 Changelog

All notable changes to this project are documented here.

## v0.9.8e-stable (2025-08-02)

### 🐳 Docker & CI Workflow Overhaul
- ✅ GitHub Actions now build Docker containers **only for stable tags** (`v*stable*`)
- 🧪 Removed accidental builds from `testing` and `master` pushes
- 🐳 New Docker image: `aridev1/mso5000_liveview:v0.9.8e-stable` + `latest`

### 📈 Power Analysis & GUI Polishing
- ⚙️ Improved auto-calibration scaling with better feedback
- 🧮 More accurate signed PF angle (θ) and impedance tracking
- 📐 PQ plot logic now avoids label overlap based on quadrant prediction
- 🖼️ PNG plot footer now includes probe config and system metadata

### 🛠️ Developer UX & CLI Improvements
- 🛡️ Git tagging strategy improved (`vX.Y.Z-stable` only triggers builds)
- 🧹 Cleanup: branch protection clarified, and `release/` workflow standardized
- ✨ Added CLI-friendly fallback mode for raw waveform failures

### 📚 Docs & Project Maintenance
- 📝 `README.md` updated with correct badges, links, and visual refinements
- 📸 Screenshot refreshed for GUI overview
- ✅ Cleaned up outdated tags, stale branches, and clarified release process

---

## v0.9.8 (2025-07-30)

### 🧠 Power Factor Polarity Fix & PQ Accuracy
- ✅ Fixed: PF polarity and PF angle (θ) sign now correctly reflect real/reactive power direction
- 📐 Accurate quadrant labeling with signed PF and θ, based on FFT phase shift
- 🔼 Impedance `Z` and angle now shown in summary (Vrms / Irms with ∠θ)
- 🔃 Heatmap-style PQ plot enhanced with trailing fade and quadrant visuals

### 📈 Real-Time Analyzer Improvements
- 📝 PNG summary plots now include operator name, scope model/serial/firmware
- 🕒 Power logging timestamped with ISO-8601 format
- 🗜️ Optimized SCPI waveform fetch logic to reduce overhead and sync issues
- 🧪 Vrms/Irms/P/S/Q/PF/Z computations match Rigol results even for distorted waveforms

### ⚡ GUI Refinements & Usability
- 👁️ Power tab uses refined SI formatting for better readability
- 🧮 Auto-calibration now auto-corrects using entered expected power
- 🛑 Live power analysis disables conflicting long-time logging safely
- 📤 CSV export includes all energy metrics and PF angle history

### 🐞 Stability & Edge Case Handling
- Fixed: edge-case NaN values in PF angle
- Fixed: probe multiplier warning clarified to avoid confusion
- Improved error resilience during scope disconnect or empty waveform fetch
- Internal debug logs include phase trace and FFT-derived frequency

---

## v0.9.7 (2025-07-27)

### ⚙️ Core & Backend Updates
- Auto-generated `version.py` now uses UTC timestamps and supports Python <3.11
- Dynamic SCPI blacklist growth based on timeouts and malformed responses
- Improved IDN parsing and frequency reference handling at startup

### ⚡ Power Analysis Overhaul
- New PF angle (θ) calculation shown in output and PQ plot
- Displays real-time energy stats: `Wh`, `VAh`, `VARh`
- DC offset removal now visually marked in GUI
- Refined scaling logic for clamp/shunt probes, with GUI feedback
- Auto-calibration visibly updates correction factor with user feedback

### 📈 Long-Time Measurement Enhancements
- Channels now scaled using unit detection (Volt vs Amp)
- Supports Vpp/Vavg/Vrms logging for CHx and MATHx in one CSV
- Pause/resume logic improved and visually reflected in status area
- Accurate sample timing via scheduler correction

### 🧪 GUI Features
- Debug log now supports toggle between FULL and MINIMAL output
- System Info and Channel Info tabs support clipboard copy
- New button for copying full CSV snapshot from all channels
- License tab shows activated/trial options from Rigol scope (via HTTP)

### 🐞 Misc
- Clean separation between logging and power analysis modes
- Better SCPI error handling in console and debug log

---

## v0.9.6 (2025-07-24)

### 🐳 Docker Integration and GUI Access
- 🖥️ Full X11 GUI support inside Docker
- 🐚 Improved Docker CLI usability

+### ⚡ Power Analyzer Refinements
+- Unified power logging into a single CSV file with timestamps
+- Live PQ plot with heatmap-style trail (fading intensity)
+- Displays real-time PF angle (θ) as orange dashed vector
+- New quadrant-aware labeling (I–IV) with dynamic zoom
+- Pause/resume/stop capability for live power analysis
+- "Remove DC offset" setting toggled visually and in log

### ⚡ Power Analyzer Refinements
- 📡 Frequency reference (`Reference: VOLT` or `CURR`) shown live in GUI
- 🧠 Compact layout and right-aligned labels for better readability
- 🛑 Power analyzer is disabled while long-time logging is active
- 📊 Frequency reference printed only once to log at startup

+### 📈 Long-Time Measurement Enhancements
+- Session logs written to single file `session_log.csv`
+- Optional Vavg/Vrms logging per channel
+- Supports MATH channels and unit scaling
+- Robust delay tracking with scheduling correction
+- Status updates every 5 cycles or at end

### 🛠️ Versioning & Build Metadata
- `build_version.py` now auto-generates `version.py` with commit hash

+### 🐞 Debugging Improvements
+- Toggle between FULL and MINIMAL logging output
+- Debug text label now lighter and smaller
+- Debug buttons float right in GUI
+- SCPI errors logged with context and auto-blacklist for timeouts

### 📦 GitHub Actions CI/CD
- Docker image auto-built and pushed on push/tag

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
