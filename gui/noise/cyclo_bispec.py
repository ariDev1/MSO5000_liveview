# gui/noise/cyclo_bispec.py
"""
Bispectrum / Bicoherence for cyclostationary analysis.

Usage:
    acc = BicoherenceAccumulator(nfft=512, noverlap=256, window="hann", demean=True)
    acc.update(x, fs)            # call each time you have a new 1-D sample block
    f, B, b2 = acc.results()     # B: complex bispectrum, b2: bicoherence [0..1]

We only fill the principal region f1>=0, f2>=0, f1+f2<=fs/2.
"""

from __future__ import annotations
import numpy as np
try:
    from scipy.signal import get_window
except Exception:
    get_window = None

def _frame_signal(x, nfft, noverlap):
    step = nfft - noverlap
    if step <= 0:
        raise ValueError("noverlap must be < nfft")
    n = len(x)
    if n < nfft:
        return np.empty((0, nfft), dtype=float)
    nseg = 1 + (n - nfft) // step
    idx = np.arange(nfft)[None, :] + step * np.arange(nseg)[:, None]
    return x[idx]

class BicoherenceAccumulator:
    def __init__(self, nfft=512, noverlap=256, window="hann", demean=True):
        self.nfft = int(nfft)
        self.noverlap = int(noverlap)
        self.window = window
        self.demean = bool(demean)

        M = self.nfft // 2 + 1  # rfft size
        # Running sums (principal triangle). We store full square then mask at the end for simplicity.
        self.S1 = np.zeros((M, M), dtype=np.complex128)  # Σ X(f1) X(f2) X*(f1+f2)
        self.S2 = np.zeros((M, M), dtype=np.float64)     # Σ |X(f1) X(f2)|^2
        self.S3 = np.zeros(M, dtype=np.float64)          # Σ |X(f)|^2   (for f = f1+f2)
        self.K = 0

        # Pre-build window
        if isinstance(self.window, str) and get_window is not None:
            self.win = get_window(self.window, self.nfft, fftbins=True).astype(float)
        elif self.window is None:
            self.win = np.ones(self.nfft, float)
        else:
            # array-like provided
            w = np.asarray(self.window, float)
            if len(w) != self.nfft:
                raise ValueError("window length must match nfft")
            self.win = w
        # Normalize window RMS to avoid amplitude bias across nseg
        self.win = self.win / np.sqrt(np.mean(self.win**2))

    def update(self, x: np.ndarray, fs: float) -> None:
        """Accumulate statistics from one time-series block."""
        x = np.asarray(x, float)
        if self.demean:
            x = x - np.mean(x)

        frames = _frame_signal(x, self.nfft, self.noverlap)
        if frames.size == 0:
            return
        frames = frames * self.win[None, :]

        # FFT (real)
        X = np.fft.rfft(frames, n=self.nfft, axis=1)  # shape (K, M)
        Kseg, M = X.shape

        # Update S3 for all f bins using sum of |X|^2 over segments
        self.S3[:M] += np.sum(np.abs(X)**2, axis=0)

        # Vectorized triangular accumulation:
        # For each f1 index i, combine against all f2 in 0..M-1-i
        for i in range(M):
            max_j = M - i
            Xi = X[:, i][:, None]                 # shape (Kseg, 1)
            Xj = X[:, :max_j]                     # shape (Kseg, max_j)
            Xk = np.conj(X[:, i:(i+max_j)])       # f1+f2 index -> i+j

            prod = Xi * Xj * Xk                   # shape (Kseg, max_j)
            self.S1[i, :max_j] += np.sum(prod, axis=0)

            # Denominators
            self.S2[i, :max_j] += np.sum(np.abs(Xi * Xj)**2, axis=0)

        self.K += Kseg
        self._fs = float(fs)

    def results(self):
        """Return (freq_vector, bispectrum, bicoherence) masked to the principal triangle."""
        if self.K == 0:
            M = self.nfft // 2 + 1
            f = np.linspace(0, (M-1) * self._fs / self.nfft, M) if hasattr(self, "_fs") else np.linspace(0, 1, M)
            mask = _triangle_mask(M)
            return f, np.zeros((M, M), complex), np.zeros((M, M), float) * mask

        M = self.nfft // 2 + 1
        f = np.linspace(0, (M-1) * self._fs / self.nfft, M)

        # Bispectrum (averaged triple product)
        B = self.S1 / max(self.K, 1)

        # Bicoherence (squared magnitude normalization)
        b_num = np.abs(self.S1)**2
        # Build Σ|X(f1+f2)|^2 lookups as a 2D matrix via broadcasting
        S3_mat = self.S3[None, :]   # shape (1, M)
        # For each (i,j), denom = S2[i,j] * S3[i+j]
        denom = np.zeros_like(self.S2)
        for i in range(M):
            max_j = M - i
            denom[i, :max_j] = self.S2[i, :max_j] * S3_mat[0, i:(i+max_j)]
        with np.errstate(divide="ignore", invalid="ignore"):
            b2 = np.where(denom > 0, b_num / denom, 0.0)
            b2 = np.clip(b2, 0.0, 1.0)

        mask = _triangle_mask(M)
        return f, B * mask, b2 * mask

def _triangle_mask(M):
    """Upper-left right triangle (including diagonal) for indices i+j<M."""
    mask = np.zeros((M, M), float)
    for i in range(M):
        mask[i, :M-i] = 1.0
    return mask

def plot_bicoherence(ax, f, b2, vmin=0.0, vmax=1.0):
    """Convenience plot: triangular bicoherence heatmap with axes in Hz."""
    import matplotlib.pyplot as plt
    M = len(f)
    # Build masked array to hide i+j>=M region
    tri = np.ma.array(b2, mask=(b2 == 0))
    im = ax.imshow(
        np.flipud(tri), extent=[f[0], f[-1], f[0], f[-1]],
        vmin=vmin, vmax=vmax, aspect="equal", interpolation="nearest"
    )
    ax.set_xlabel("f1 [Hz]")
    ax.set_ylabel("f2 [Hz]")
    ax.set_title("Bicoherence")
    cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("bicoherence")
    # Diagonal f1+f2=fs/2 line (visual cue)
    ax.plot([0, f[-1]], [f[-1], 0], color="#666", linewidth=0.8, linestyle="--")
    return im
