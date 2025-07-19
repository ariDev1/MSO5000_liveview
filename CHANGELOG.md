# 📖 Changelog

All notable changes to this project are documented here.

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
