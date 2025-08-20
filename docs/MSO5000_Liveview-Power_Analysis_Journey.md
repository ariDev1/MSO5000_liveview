# MSO5000 Liveview Power Analysis: A Journey Through SCPI, Waveforms, and Crashes

## Background

This document summarizes our deep dive into improving waveform acquisition for the Rigol MSO5000-based power analysis project. It serves as both a technical report and a cautionary tale for developers working with SCPI-controlled instruments in real-time environments.

## Original Stable Design

* Used `:WAV:FORM BYTE` for waveform transfer
* Queried one channel at a time (`CHAN1`, `CHAN2`)
* Used `query_binary_values(..., datatype='B')` safely
* Scaling was hardcoded or minimal
* GUI was responsive, scope never froze
* Real power and energy were calculated simply, reliably

## The Ambition

We aimed to add:

* Precision real-time power calculations (P, Q, PF, energy)
* FFT-based cycle lock
* Full dual-channel waveform sync
* SCPI probe factor auto-scaling (`:CHANnelX:PROBe?`)
* Support for `:WAV:FORM WORD` for better resolution
* Auto-decimation for performance

## What Went Wrong

1. **Scope freezes during `:WAV:DATA?` using `WORD`**

   * `query_binary_values(..., datatype='h')` caused timeout or connection loss
   * `read_raw()` + manual block decode also failed randomly

2. **SCPI command format inconsistencies**

   * `:CHAN1:PROB?` vs `:CHANnel1:PROBe?`
   * Some abbreviations worked; others caused SCPI errors or silent failures

3. **Connection instability over TCP/IP (VXI11)**

   * Rapid or large SCPI payloads (especially with multiple channels)
   * Scope firmware (possibly hacked) couldn’t handle aggressive queries

4. **No feedback from scope on partial failures**

   * When SCPI crashes mid-burst, responses silently time out
   * GUI hangs or fills log with `Broken pipe`, `VI_ERROR_IO`

## Observations

* Rigol MSO5000 scopes are sensitive to waveform block size
* BYTE mode is far more robust than WORD
* Sending `:WAV:DATA?` for both channels back-to-back often causes firmware failure
* Adding just a `time.sleep(0.1)` between queries reduces crash rate — but is not a fix
* SCPI probe queries (`:CHANnelX:PROBe?`) only work in long form, and fail silently otherwise

## Lessons Learned

* **Stability > features** — Always prioritize user experience and device integrity
* **Rigol SCPI quirks are undocumented** — test all variants
* **query\_binary\_values is safe** for small blocks — `read_raw()` is not unless bulletproofed
* **Cycle lock, FFT, and energy calc are best done offline** unless absolute real-time precision is needed

## Current Path Forward

We reverted to:

* Safe single-channel acquisition using BYTE mode
* Manual probe scaling by user in GUI
* Optional CSV export for post-processing

...and will slowly reintroduce advanced features **in isolation**.

## Why This Matters

This journey is valuable to:

* Engineers building SCPI tools
* Developers working with real-time measurement GUIs
* Anyone trying to extract high-resolution data over fragile TCP SCPI links

We share this not only as a technical log, but as **open engineering in practice**. Mistakes were made. Things broke. But it was real, and honest.

## Closing Thought

Not everything belongs in the real-time path. That’s what files, post-processing, and user control are for.

We thank the Rigol MSO5000 for surviving this long.

And we thank curiosity, because it pushed us here.
