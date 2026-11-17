"""
ChaosLab - Ortak analiz araçları (sürekli ve ayrık sistemler için)
==================================================================
- Güç spektrumu        : Welch yöntemi (scipy.signal.welch), baskın frekans, spektral entropi
- Korelasyon boyutu    : Grassberger–Procaccia C(r) eğrisi, Theiler penceresi
- Kutu sayma boyutu    : N(ε) ~ ε^(-D0)
- Çekici kümeleme      : çekim havzası için son pencere ortalamalarına göre çekici etiketleme
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.signal import welch
from scipy.spatial.distance import cdist


def _clean(arr: Any) -> Any:
    a = np.asarray(arr, dtype=float)
    if a.ndim == 0:
        v = float(a)
        return v if math.isfinite(v) else None
    out = a.astype(object)
    out[~np.isfinite(a)] = None
    return out.tolist()


def _f(v: float | None, digits: int = 6) -> float | None:
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        return None
    return float(f"{v:.{digits}g}")


# ---------------------------------------------------------------------------
# Güç spektrumu
# ---------------------------------------------------------------------------
def power_spectrum(Y: np.ndarray, dt: float, var_names: list[str], discard_frac: float = 0.2) -> dict[str, Any]:
    """Y: (n, d) eşit aralıklı örnekler. Her değişken için Welch PSD (dB)."""
    Y = np.asarray(Y, dtype=float)
    Y = Y[np.all(np.isfinite(Y), axis=1)]
    n0 = int(len(Y) * discard_frac)
    Y = Y[n0:]
    n = len(Y)
    if n < 64:
        return {"available": False, "reason": "too_short"}
    fs = 1.0 / dt
    nperseg = int(2 ** min(13, max(6, int(math.log2(max(64, n // 4))))))
    nperseg = min(nperseg, n)
    out: dict[str, Any] = {"available": True, "fs": _f(fs), "dt": dt, "n_samples": n, "nperseg": nperseg, "vars": {}}
    freqs = None
    for i, v in enumerate(var_names):
        x = Y[:, i] - np.mean(Y[:, i])
        if np.allclose(x, 0.0, atol=1e-12):
            f, P = welch(np.zeros(n), fs=fs, nperseg=nperseg)
            P = np.full_like(f, 1e-30)
        else:
            f, P = welch(x, fs=fs, nperseg=nperseg, window="hann", detrend="constant", scaling="density")
        freqs = f
        P = np.maximum(P, 1e-30)
        db = 10.0 * np.log10(P)
        # baskın frekans (f = 0 hariç)
        k = int(np.argmax(P[1:]) + 1) if len(P) > 1 else 0
        # normalize spektral entropi (0: tek çizgi / periyodik, 1: beyaz gürültü / geniş bant)
        p = P[1:] / np.sum(P[1:]) if np.sum(P[1:]) > 0 else np.ones(len(P) - 1) / max(1, len(P) - 1)
        H = float(-np.sum(p * np.log(p + 1e-300)) / math.log(len(p))) if len(p) > 1 else 0.0
        # baskın tepeler (en yüksek 5)
        order = np.argsort(P[1:])[::-1][:5] + 1
        out["vars"][v] = {
            "psd_db": _clean(db),
            "dominant_freq": _f(f[k]),
            "dominant_period": _f(1.0 / f[k]) if f[k] > 0 else None,
            "spectral_entropy": _f(H, 4),
            "peaks": [{"f": _f(f[j]), "db": _f(db[j], 4)} for j in sorted(order)],
        }
    out["freq"] = _clean(freqs)
    return out


# ---------------------------------------------------------------------------
# Fraktal boyutlar
# ---------------------------------------------------------------------------
def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2)) or 1e-300
    return float(coef[0]), float(coef[1]), 1.0 - ss_res / ss_tot


def correlation_dimension(P: np.ndarray, n_max: int = 2000, theiler: int = 5, n_r: int = 36) -> dict[str, Any]:
    """Grassberger–Procaccia: C(r) = (2 / N(N-1)) Σ Θ(r - ||x_i - x_j||), D2 = d ln C / d ln r."""
    P = np.asarray(P, dtype=float)
    P = P[np.all(np.isfinite(P), axis=1)]
    if len(P) < 200:
        return {"available": False, "reason": "too_short"}
    idx = np.unique(np.linspace(0, len(P) - 1, min(n_max, len(P))).astype(int))
    X = P[idx]
    N = len(X)
    D = cdist(X, X)
    ii, jj = np.triu_indices(N, k=max(1, theiler))
    d = np.sort(D[ii, jj])
    d = d[d > 0]
    if d.size < 100:
        return {"available": False, "reason": "degenerate"}
    r_lo = max(d[int(0.0005 * d.size)], 1e-12)
    r_hi = d[int(0.5 * d.size)]
    if not (r_hi > r_lo):
        return {"available": False, "reason": "degenerate"}
    r = np.logspace(math.log10(r_lo), math.log10(r_hi), n_r)
    C = np.searchsorted(d, r, side="right") / d.size
    m = C > 0
    lr, lc = np.log(r[m]), np.log(C[m])
    # Ölçekleme bölgesi: 1e-3 ≤ C ≤ 1e-1 (yeterli nokta yoksa orta %60)
    sel = (C[m] >= 1e-3) & (C[m] <= 0.1)
    if np.sum(sel) < 5:
        k0, k1 = int(0.2 * len(lr)), int(0.8 * len(lr))
        sel = np.zeros(len(lr), dtype=bool)
        sel[k0:k1] = True
    slope, icpt, r2 = _linear_fit(lr[sel], lc[sel])
    local = np.gradient(lc, lr) if len(lr) > 2 else np.array([])
    return {
        "available": True,
        "D2": _f(slope, 5),
        "r2": _f(r2, 5),
        "log_r": _clean(lr),
        "log_C": _clean(lc),
        "local_slope": _clean(local),
        "fit_mask": sel.tolist(),
        "fit_intercept": _f(icpt, 6),
        "n_points": N,
        "theiler": theiler,
    }


def box_counting_dimension(P: np.ndarray, n_max: int = 60000) -> dict[str, Any]:
    """Kutu sayma: tüm noktalar ortak (izotrop) ölçekle [0,1]^d küpüne normalize edilir."""
    P = np.asarray(P, dtype=float)
    P = P[np.all(np.isfinite(P), axis=1)]
    if len(P) < 200:
        return {"available": False, "reason": "too_short"}
    if len(P) > n_max:
        P = P[np.unique(np.linspace(0, len(P) - 1, n_max).astype(int))]
    lo = P.min(axis=0)
    span = float(np.max(P.max(axis=0) - lo))
    if span <= 0:
        return {"available": False, "reason": "degenerate"}
    U = (P - lo) / span * (1 - 1e-12)
    Np = len(U)
    ks = list(range(1, 13))
    eps, counts = [], []
    for k in ks:
        m = 2 ** k
        cells = np.floor(U * m).astype(np.int64)
        # tek tamsayı anahtarı
        key = np.zeros(Np, dtype=np.int64)
        for c in range(cells.shape[1]):
            key = key * (m + 1) + cells[:, c]
        cnt = int(np.unique(key).size)
        eps.append(1.0 / m)
        counts.append(cnt)
        if cnt > Np / 3:
            break
    eps_a = np.array(eps)
    cnt_a = np.array(counts, dtype=float)
    x = np.log(1.0 / eps_a)
    y = np.log(cnt_a)
    # doyma öncesi orta bölge
    sel = (cnt_a < Np / 10) & (np.arange(len(eps_a)) >= 1)
    if np.sum(sel) < 3:
        sel = np.ones(len(eps_a), dtype=bool)
        sel[0] = False if len(sel) > 3 else True
    slope, icpt, r2 = _linear_fit(x[sel], y[sel])
    return {
        "available": True,
        "D0": _f(slope, 5),
        "r2": _f(r2, 5),
        "log_inv_eps": _clean(x),
        "log_N": _clean(y),
        "fit_mask": sel.tolist(),
        "fit_intercept": _f(icpt, 6),
        "n_points": Np,
    }


def fractal_analysis(P: np.ndarray) -> dict[str, Any]:
    return {"correlation": correlation_dimension(P), "box": box_counting_dimension(P)}


# ---------------------------------------------------------------------------
# Çekim havzası kümeleme
# ---------------------------------------------------------------------------
def cluster_attractors(
    mean: np.ndarray, std: np.ndarray, diverged: np.ndarray, max_clusters: int = 10
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """mean, std: (M, d) son pencere istatistikleri. Etiket -1: ıraksak, -2: diğer (küme sınırı aşıldı)."""
    M = mean.shape[0]
    labels = np.full(M, -1, dtype=int)
    ok = ~diverged & np.all(np.isfinite(mean), axis=1)
    if not np.any(ok):
        return labels, []
    sn = np.linalg.norm(std[ok], axis=1)
    scale = float(np.max(np.abs(mean[ok]))) + 1.0
    tol = max(0.25 * float(np.median(sn)), 1e-3 * scale)
    centers: list[np.ndarray] = []
    members: list[list[int]] = []
    for i in np.where(ok)[0]:
        m = mean[i]
        best, bd = -1, np.inf
        for c, ctr in enumerate(centers):
            dd = float(np.linalg.norm(m - ctr))
            if dd < bd:
                best, bd = c, dd
        if best >= 0 and bd <= tol + 0.25 * float(np.linalg.norm(std[i])):
            labels[i] = best
            members[best].append(i)
        elif len(centers) < max_clusters:
            centers.append(m.copy())
            members.append([i])
            labels[i] = len(centers) - 1
        else:
            labels[i] = -2
    # çok küçük kümeler (yakınsamamış sınır noktaları) → "çözümlenemedi" (-2)
    min_count = max(2, int(0.002 * M))
    for c in range(len(centers)):
        if len(members[c]) < min_count and len(centers) > 1:
            labels[labels == c] = -2
            members[c] = []
    # büyükten küçüğe yeniden numaralandır
    order = sorted([c for c in range(len(centers)) if members[c]], key=lambda c: -len(members[c]))
    remap = {old: new for new, old in enumerate(order)}
    new_labels = labels.copy()
    for old, new in remap.items():
        new_labels[labels == old] = new
    info = []
    for old in order:
        mem = np.array(members[old])
        mu = mean[mem].mean(axis=0)
        sd = float(np.median(np.linalg.norm(std[mem], axis=1)))
        info.append({
            "center": [_f(v, 6) for v in mu],
            "spread": _f(sd, 4),
            "kind": "fixed" if sd < 1e-3 * (1.0 + float(np.linalg.norm(mu))) else "oscillating",
            "fraction": _f(len(mem) / M, 4),
            "count": int(len(mem)),
        })
    return new_labels, info


def match_equilibria(attractors: list[dict[str, Any]], eqs: list[dict[str, Any]]) -> None:
    """Çekici merkezlerini kararlı denge/sabit noktalarla eşleştirir (yavaş yakınsamaya toleranslı)."""
    for a in attractors:
        a["equilibrium"] = None
        c = np.array([v if v is not None else np.nan for v in a["center"]], dtype=float)
        spread = float(a.get("spread") or 0.0)
        for k, e in enumerate(eqs):
            if not e.get("stable"):
                continue
            p = np.array(e["point"], dtype=float)
            if np.linalg.norm(c - p) < max(3.0 * spread, 1e-2 * (1 + np.linalg.norm(p))) and spread < 0.05 * (1 + np.linalg.norm(p)):
                a["equilibrium"] = k
                a["kind"] = "fixed"
                break
