# Qt viewer — Tk parity handover (branch `feature/qt-ui`)

The Qt viewer (`qt_app/`, launched via `python -m qt_app.main`) is an
alternative front-end next to the lab-tested Tk application (`python main.py`).
It reuses the established SCPI, calculation, logger, and CSV modules
unchanged. Tk behavior is frozen; every deliberate Qt difference is noted
inline in `qt_app/` as a `GAP` comment and consolidated below.

## Frozen constraints (never touched from this branch)

- `scpi/`, `logger/`, `gui/` (Tk code), `main.py`, calculation functions,
  CSV schemas/paths, Docker, releases.
- Qt-only changes live in `qt_app/`, plus test fixtures and this document.

## Parity status per tab

| Area | Matched with Tk | Diverges (reason) |
|---|---|---|
| Power setup/measure | Channels, probe, correction, formula, DC removal, 25 Mpts, auto + duration, auto-calibration, SI results, PQ triangle + trail | CSV header lacks `# Created` / FrequencyRef rows (schema frozen; shown in UI instead) |
| Power plot | Triangle, quadrants, S/θ/PF/Z box, dwell heat layer, trail, summary PNG on auto-stop | QPainter rendering instead of Matplotlib; "3D view" is a button opening the same `PQ3DView` backend (Tk uses a checkbox-owned window) |
| Harmonics | 9-column table incl. derived columns, overlays, legend, dBr₁ readout, known lines, selection marker, presets, exports | 15-spectra persistence heat-map and shared `surface3d` streaming → own 3D-history dialog; fetch-mode status (own exclusive reader in Tk); auto-path CSV/PNG names (Qt paths frozen) |
| Noise | All 10 methods, per-method presets, advanced fields, markers, hints, trail, 3D history with controls | Length trim, daily auto-log, bicoherence accumulation/vmax, cyclo α/dB extras, single-window MSC fetch (all need shared-code changes) |
| B-H | Geometry, probe, deskew, I/V/Auto cycle ref, averaging, trail, aspect/tight, warnings, samples | NORM/RAW sampler + point count (own exclusive reader in Tk); session run-log + detailed CSV (schema frozen); THD(I/V) (needs raw waves the shared adapter doesn't surface) |
| Core tabs | Order, titles, licenses format, system detail, debug verbosity, activity lamp, channel export/copy | Channels shows full snapshot (superset of Tk one-liners); self-test is read-only by design (Tk stops acquisition and probes); no marquee ticker (promo chrome) |
| Shell | Reconnect, hide/enlarge display, aspect-preserving VNC, upscale config | — |

## Deliberate Qt improvements (beyond Tk, operator-approved)

- Calibration accepts any nonzero sign combination (Tk: positive only).
- Expected-power deviation (`Δ %`) shown on every Power shot.
- Embedded plot dialogs instead of external-script subprocesses.
- UI zoom (`Ctrl +` / `Ctrl -` / `Ctrl 0`), setup fold toggles, per-user
  persistence of zoom/folds/workspace/tab setups, `F5` measure,
  `Ctrl+1…9` tab jumps, channel colors, big-digit headlines.

## Automated verification

- `pytest tests/`: 59 passed, 1 xfailed (pre-existing FFT-bin expectation).
- Qt tests run offscreen with an isolated `XDG_CONFIG_HOME` (see fixture in
  `tests/test_qt_viewer.py`) so they never touch real user settings.
- Each parity step was additionally smoke-tested offscreen (rendering,
  persistence round-trips, export files).

## Hardware-in-the-loop checklist (scope required)

- [ ] VNC screenshot cadence and enlarge/hide behavior under load.
- [ ] 25 Mpts fetches on Power and B-H RAW paths; duration-stop timing.
- [ ] Auto-measure loops (Power/Harmonics/Noise/B-H) for 10+ min: no
      growth in memory, no summary-PNG pileup beyond one per session.
- [ ] Reconnect storm: pull network mid-measure, confirm recover + relink lamp.
- [ ] Cross-sign calibration on a real regen/inverter rig (−P both sides,
      then mixed-sign refusal message).
- [ ] License tab against real `/cgi-bin/options.cgi`.
- [ ] Long-time logging + Power mutual exclusion from the Qt side.
- [ ] 3D-history dialogs with live spectra (lines/wire/surface, Log Z).
