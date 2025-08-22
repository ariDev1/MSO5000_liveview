# Noise Inspector — Operator Guide

---

## 1) Purpose
Find **structure inside “white noise.”** The tab takes a local copy of the latest scope data and runs one of several detectors. Each run produces:
- a **plot** (spectrum, coherence, spectrogram, etc.)
- a **table** with detections
- optional **exports** (PNG/CSV)

**Methods currently available**
1. PSD+CFAR (lines/tones)
2. Spectrogram (persistence)
3. MSC (two‑channel coherence)
4. Multitaper (DPSS) + CFAR
5. Spectral Kurtosis (impulsiveness)
6. Cepstrum (comb/fundamental spacing)
7. Matched Filter (template correlation)
8. AR Spectrum (parametric)

Exports are written to `oszi_csv/noise_inspector/`.

---

## 2) Quick start
1. Open **Noise Inspector** tab.  
2. Pick **Channel(s)**: one channel for most methods, or a pair like `CHAN1&CHAN3` for **MSC**.  
3. Choose a **Method** and a **Preset** (e.g., *Fast scan*, *High resolution*).  
4. Select **Length [s]** (0.5 / 1 / 2 / 5) or **From CSV**.  
5. If **Matched Filter**, set **Template Path** (CSV with `y` or `t,y`).  
6. Press **Analyze**. The status shows: `method — <N> detections; <time>s, Δf≈<res>`  
7. Click table rows to drop a **red marker** on the plot. The main curve is **blue**, detections are **amber** dashed lines.  
8. **Save PNG** / **Save CSV** for reporting.

> If the scope is busy (“Timeout waiting for SCPI lock”), just press **Analyze** again.

---

## 3) Controls
- **Channel(s)** — `CHANx` or `CHANx&CHANy` (MSC needs a pair).  
- **Method** — detector to run (see §5).  
- **Preset** — per‑method defaults that set the relevant Advanced fields (see §4).  
- **Length [s]** — capture tail length from latest snapshot.  
  - **From CSV:** analyzes the newest `oszi_csv/CHAN*_*.csv` if path is blank.  
  - **Matched Filter:** the input row is relabeled **Template Path**.
- **Advanced ▾** (toggle at bottom):  
  - `NFFT` — FFT size (power of 2 recommended)  
  - `SegLen` / `Overlap` — Welch/MSC/Multitaper segmentation  
  - `Pfa` — CFAR false‑alarm probability (lower ⇒ stricter)  
  - `SmoothBins` — median filter width (odd) for baseline in dB  
  - `TopK` — list size for Spectrogram/Cepstrum  
  - `MSC_thr` — coherence threshold (0–1)  
  - `Hop` — STFT hop (samples) for Spectrogram/SK  
  - `K_tapers` — number of DPSS tapers (Multitaper)  
  - `SK_thr` — kurtosis threshold (higher ⇒ stricter)  
  - `qmin_ms` / `qmax_ms` — cepstrum window (quefrency)  
  - `AR_order` — Yule‑Walker model order (AR Spectrum)

---

## 4) Presets (what they change)
Presets only set fields that matter for the chosen method; everything else is left untouched.

- **PSD+CFAR** — *Fast scan* (smaller NFFT/SegLen), *High resolution* (larger NFFT/SegLen, more overlap), *Low false alarm* (Pfa 1e‑4).  
- **Spectrogram** — *Fast scan* (smaller NFFT/Hop), *High resolution* (bigger NFFT, more TopK).  
- **MSC** — *Deep* (larger NFFT/SegLen/Overlap, slightly higher threshold), *Fast scan* (smaller sizes).  
- **Multitaper** — *High resolution* (more tapers & larger N), *Fast scan* (fewer tapers & smaller N).  
- **Spectral Kurtosis** — *Transient hunt* (smaller hop, lower SK_thr), *Strict* (higher SK_thr).  
- **Cepstrum** — *Low rate* (wide quefrency for slow fundamentals), *Wide search* (bigger range, more peaks).  
- **AR Spectrum** — *Sharp peaks* (higher order & NFFT), *Fast scan* (smaller).  
- **Matched Filter** — no numeric params; supply a template.

---

## 5) Methods — full descriptions

### 5.1 PSD+CFAR — **Lines / tones in noise**
- **What it detects:** Narrowband components (spurs, carriers, clocks).  
- **How it works:** Welch PSD → robust baseline (median in log‑PSD) → **CFAR** on residual → group bins → **parabolic** peak refine.  
- **Plot:** PSD (dB) vs frequency; **amber dashed** lines at detections; **blue** main curve.  
- **Table columns:** `Type`, `f0_Hz`, `SNR_dB` (above baseline), `BW_Hz`, `Notes`.  
- **Good defaults:** `NFFT=4096`, `SegLen=4096`, `Overlap=0.5`, `Pfa=1e‑3`, `SmoothBins=31`.  
- **When to use:** Steady tones; faint spurs (increase NFFT/SegLen, or lower Pfa).  
- **Caveats:** Very close tones can merge; try **Multitaper** for separation.

### 5.2 Spectrogram (persistence) — **Time‑frequency occupancy**
- **What it detects:** Frequencies that are present **often** across frames.  
- **How it works:** STFT log‑PSD → CFAR threshold per frame → **occupancy** per bin → rank **TopK**.  
- **Plot:** Spectrogram image; **table** lists bins with highest `Occup_%`.  
- **Table columns:** `Type`, `f0_Hz`, `Occup_%`, `BW_Hz`, `Notes`.  
- **Good defaults:** `NFFT=4096`, `Hop=2048`, `Pfa=1e‑3`, `TopK=8`, `SmoothBins=31`.  
- **When to use:** Drifting/hopping carriers, intermittent lines.  
- **Caveats:** Occupancy depends on STFT window/hop; lower hop for faster dynamics.

### 5.3 MSC — **Two‑channel coherence**
- **Requires:** Select a **pair** (e.g., `CHAN2&CHAN3`) or two CSVs with same Fs.  
- **What it detects:** Frequencies with **high coherence** between channels.  
- **How it works:** Welch cross/auto spectra → magnitude‑squared coherence → threshold/group.  
- **Plot:** MSC 0…1 vs frequency; **amber dashed** detections above `MSC_thr`.  
- **Table columns:** `Type=coh`, `f0_Hz`, `MSC`, `BW_Hz`, `Notes`.  
- **Good defaults:** `NFFT=4096`, `SegLen=4096`, `Overlap=0.5`, `MSC_thr=0.5`.  
- **When to use:** Coupled/common interference; rejects uncorrelated noise.  
- **Caveats:** Mismatch in sampling or time alignment across CSVs will degrade MSC.

### 5.4 Multitaper (DPSS) + CFAR — **Variance‑reduced PSD**
- **What it detects:** Same targets as PSD+CFAR, but with **less variance**.  
- **How it works:** Average **K** DPSS‑tapered periodograms per segment → PSD → baseline + CFAR → peak refine.  
- **Plot:** Multitaper PSD (dB) with **amber dashed** detections.  
- **Table columns:** `Type=line`, `f0_Hz`, `SNR_dB`, `BW_Hz`, `Notes`.  
- **Good defaults:** `K_tapers=6`, `NFFT=4096`, `SegLen=4096`, `Overlap=0.5`, `Pfa=1e‑3`, `SmoothBins=31`.  
- **When to use:** **Weak/close tones** that vanish in Welch noise.  
- **Caveats:** More tapers increase compute; for rapid scans, lower `K_tapers`.

### 5.5 Spectral Kurtosis — **Impulsive / bursty bands**
- **What it detects:** **Impulsiveness** at certain frequencies (e.g., arcing, switching spikes).  
- **How it works:** STFT log‑magnitude → per‑frequency **excess kurtosis**; bins with `SK ≥ SK_thr` are flagged and grouped.  
- **Plot:** Image (same viewer as spectrogram); detections listed in table.  
- **Table columns:** `Type=sk`, `f0_Hz`, `SK`, `BW_Hz`, `Notes`.  
- **Good defaults:** `NFFT=4096`, `Hop=2048`, `SK_thr=2.5`.  
- **When to use:** Intermittent bursts; non‑Gaussian behavior.  
- **Caveats:** High SK can also occur from very strong stable tones plus windowing; corroborate with PSD view.

### 5.6 Cepstrum — **Comb/fundamental spacing**
- **What it detects:** The **spacing** between harmonic lines → estimates fundamental.  
- **How it works:** Power cepstrum from log‑magnitude → find top peaks in a **quefrency** window; report `f0 ≈ 1/q0`.  
- **Plot:** Cepstral “spectrum” vs **1/q**; peaks correspond to fundamental candidates.  
- **Table columns:** `Type=comb`, `f0_Hz`, `SNR_dB` (cepstral peak), `BW_Hz`, `Notes`.  
- **Good defaults:** `NFFT=4096`, `qmin_ms=0.02`, `qmax_ms=5`, `TopK=3`.  
- **When to use:** PWM/PSM carriers, gear/rotational tones, clock harmonics.  
- **Caveats:** Needs enough bandwidth and length; if fundamentals are very low (< 1 Hz), widen `qmax_ms`.

### 5.7 Matched Filter — **Template correlation**
- **Input:** **Template Path** to CSV with `y` (or `t,y`).  
- **What it detects:** Presence of a **known waveform** within the capture.  
- **How it works:** Normalize both signals → **correlate** → report the peak.  
- **Plot:** Correlation vs time index; max indicates best alignment.  
- **Table columns:** `Type=corr`, `f0_Hz=0`, `SNR_dB` (corr peak), `BW_Hz=0`, `Notes` includes peak index.  
- **Good practice:** Template shorter than capture; include a few periods; same Fs is best.  
- **Caveats:** Mismatched sampling rates or strong drift reduce correlation.

### 5.8 AR Spectrum — **Parametric peak emphasis**
- **What it detects:** Narrow peaks emphasized against a smooth background.  
- **How it works:** Yule‑Walker AR model (order `AR_order`) → spectrum → baseline removal → simple peak pick.  
- **Plot:** AR spectrum (dB) with **amber dashed** detections.  
- **Table columns:** `Type=ar`, `f0_Hz`, `SNR_dB` (residual), `BW_Hz`, `Notes`.  
- **Good defaults:** `AR_order=32`, `NFFT=4096`.  
- **When to use:** Short records; want very **sharp** spectral lines.  
- **Caveats:** Over‑high order can create spurious peaks; increase carefully.

---

## 6) Recipes
- **Faint spurs:** *Multitaper → High resolution* (raise `K_tapers`, NFFT; keep Pfa ~1e‑3).  
- **Shared interference across probes:** *MSC → Deep* (bigger N & Overlap, `MSC_thr≈0.6`).  
- **Bursty switching:** *Spectral Kurtosis → Transient hunt* (smaller hop, lower `SK_thr`).  
- **Comb/harmonic spacing:** *Cepstrum → Wide search* (increase `qmax_ms`, TopK).  
- **Known sync/chirp:** *Matched Filter* with a clean template.

---

## 7) Exports
- **PNG:** `oszi_csv/noise_inspector/NI_YYYYmmdd_HHMMSS_plot.png`  
- **CSV:** `oszi_csv/noise_inspector/NI_YYYYmmdd_HHMMSS_results.csv`  
  - Line 1: JSON header with `method, chan, Fs, N, params`  
  - Then the detection table columns and rows

---

## 8) Best practices (lab accuracy)
- Save raw captures along with findings.  
- Use longer **Length** for improved Δf & averaging; then use **High resolution** presets.  
- For ultra‑low SNR tones: lower **Pfa** (e.g., 1e‑4) or switch to **Multitaper**.  
- For drift/bursts: prefer **Spectrogram/SK**.  
- For cross‑channel coupling: use **MSC** with spatial separation.

---

## 9) Troubleshooting
- **Scope not connected** → connect on SCPI tab first.  
- **Timeout waiting for SCPI lock** → press **Analyze** again or shorten Length.  
- **Empty plot / no detections** → increase Length, reduce Pfa, check that the selected channel has a valid signal.  
- **MSC error** → you must select a **pair** (e.g., `CHAN2&CHAN3`) or supply two CSVs with the same Fs.  
- **Matched Filter error** → provide a valid **Template Path**; template should be shorter than capture and same Fs.

---

## 10) Change log (operator‑visible)
- **v1.3** — Expanded operator docs per method; color‑coded plot/markers; minor axis text overlap fix.  
- **v1.2** — Added presets + new methods (Multitaper, Spectral Kurtosis, Cepstrum, Matched Filter, AR Spectrum).  
- **v1.1** — Added Spectrogram & MSC; Advanced panel moved to bottom; dark table style; status shows Δf.  
- **v1.0** — PSD+CFAR only; read‑only snapshot; PNG/CSV export.

---

## 11) Safety statement
This tool is *read‑only*. It uses protected SCPI access and never writes persistent scope settings. All processing is performed on a **local copy** of the acquired data.
