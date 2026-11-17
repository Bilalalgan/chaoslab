"""
ChaosLab - Ayrık zamanlı sistemler (haritalar)
==============================================
x_{n+1} = F(x_n; p),  boyut 1–4 (x, y, z, w)

Modüller: yörünge, örümcek ağı (cobweb), sabit noktalar + kararlılık (|λ| < 1),
Jacobian determinantı (alan/hacim daralması), Lyapunov spektrumu (Jacobian çarpımı + QR),
kelebek etkisi, yörünge (çatallaşma) diyagramı + λ_max(p), çekim havzası,
güç spektrumu ve fraktal boyut.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp
from scipy.optimize import root
from sympy.parsing.sympy_parser import parse_expr

from analysis_tools import cluster_attractors, fractal_analysis, power_spectrum
from chaos_engine import (
    ALLOWED_PATTERN, FUNCTIONS, MAX_DIM, MAX_PLOT_POINTS, SOLVE_TIMEOUT, TRANSFORMS, state_names, var_latex,
    ChaosError, clean, downsample_idx, fnum, kaplan_yorke, parse_params, run_with_timeout,
)

MAX_ITER = 500_000
MAX_BIF_WORK_MAP = 60_000_000
BOUND = 1e10


def classify_fixed_point(eigs: np.ndarray, tol: float = 1e-7) -> tuple[str, bool, int]:
    """Harita sabit noktası: |λ| < 1 kararlı yön, |λ| > 1 kararsız yön."""
    mod = np.abs(eigs)
    n_out = int(np.sum(mod > 1 + tol))
    n_in = int(np.sum(mod < 1 - tol))
    n_on = len(eigs) - n_out - n_in
    cplx = bool(np.any(np.abs(eigs.imag) > tol))
    if n_on > 0:
        on = eigs[np.abs(mod - 1) <= tol]
        if np.any(np.abs(on.imag) > tol):
            return "Hiperbolik Değil – Neimark–Sacker Adayı (|λ| = 1, karmaşık)", False, n_out
        if np.any(on.real < 0):
            return "Hiperbolik Değil – Periyot Katlanma (Flip) Adayı (λ = −1)", False, n_out
        return "Hiperbolik Değil – Eyer-Düğüm / Pitchfork Adayı (λ = +1)", False, n_out
    if n_out == 0:
        return ("Kararlı Odak (Stable Focus, çekici)" if cplx else "Kararlı Düğüm (Stable Node, çekici)"), True, 0
    if n_in == 0:
        return ("Kararsız Odak (Unstable Focus, itici)" if cplx else "Kararsız Düğüm (Unstable Node, itici)"), False, n_out
    return f"Kararsız Eyer (Saddle) index-{n_out}", False, n_out


def diagnose_map(lam: list[float], tol: float, diverged: bool = False) -> str:
    if diverged:
        return "Iraksak (Sınırsız Yörünge)"
    lam = sorted(lam, reverse=True)
    if len(lam) > 1 and lam[0] > tol and lam[1] > tol:
        return "Hiperkaotik"
    if lam[0] > tol:
        return "Kaotik"
    if abs(lam[0]) <= tol:
        return "Yarı-Periyodik / Marjinal (λ₁ ≈ 0)"
    return "Periyodik / Kararlı Sabit Nokta"


class DiscreteMap:
    def __init__(self, equations: list[str], params_text: str = "") -> None:
        eqs = [e.strip() for e in equations if e is not None and str(e).strip() != ""]
        if not 1 <= len(eqs) <= MAX_DIM:
            raise ChaosError(f"Harita 1–{MAX_DIM} denklemden oluşmalıdır (≤4: x, y, z, w; >4: x1 … xN).")
        self.dim = len(eqs)
        self.var_names = state_names(self.dim)
        self.vars = sp.symbols(" ".join(self.var_names), real=True, seq=True)
        self.params = parse_params(params_text)
        self.param_syms = {k: sp.Symbol(k, real=True) for k in self.params}
        local: dict[str, Any] = dict(FUNCTIONS)
        local.update({n: s for n, s in zip(self.var_names, self.vars)})
        local.update(self.param_syms)
        allowed = set(self.vars) | set(self.param_syms.values())
        self.exprs: list[sp.Expr] = []
        for name, eq in zip(self.var_names, eqs):
            if not ALLOWED_PATTERN.match(eq) or "__" in eq:
                raise ChaosError(f"{name}_(n+1) denkleminde geçersiz karakter var.")
            try:
                expr = sp.sympify(parse_expr(eq, local_dict=local, transformations=TRANSFORMS))
            except Exception as exc:  # noqa: BLE001
                raise ChaosError(f"{name}_(n+1) = '{eq}' ayrıştırılamadı: {exc}") from exc
            unknown = expr.free_symbols - allowed
            if unknown:
                names = ", ".join(sorted(str(s) for s in unknown))
                raise ChaosError(
                    f"{name}_(n+1) denkleminde tanımsız sembol(ler): {names}. "
                    f"Parametre olarak ekleyin veya yalnızca {', '.join(self.var_names)} kullanın."
                )
            self.exprs.append(expr)
        self.subs = {self.param_syms[k]: v for k, v in self.params.items()}
        self.exprs_num = [sp.sympify(e.subs(self.subs)) for e in self.exprs]
        self.J_sym = sp.Matrix(self.exprs).jacobian(self.vars)
        self.J_num = sp.Matrix(self.exprs_num).jacobian(self.vars)
        self._f = sp.lambdify(self.vars, self.exprs_num, modules="numpy", cse=True)
        self._J = sp.lambdify(self.vars, self.J_num, modules="numpy", cse=True)
        if self.dim <= 4:
            self.det_num = sp.simplify(self.J_num.det())
            self._det = sp.lambdify(self.vars, self.det_num, modules="numpy")
        else:  # yüksek boyutta sembolik determinant çok pahalı → sayısal
            self.det_num = None
            self._det = self._det_numeric

    def _det_numeric(self, *cols: np.ndarray) -> np.ndarray:
        P = np.stack([np.atleast_1d(np.asarray(c, dtype=float)) for c in cols], axis=-1)
        return np.array([np.linalg.det(self.jac(p)) for p in P])

    # ---------------------------------------------------------------- temel
    def F(self, s: np.ndarray) -> np.ndarray:
        return np.asarray(self._f(*s), dtype=float)

    def jac(self, s: np.ndarray) -> np.ndarray:
        return np.asarray(self._J(*s), dtype=float).reshape(self.dim, self.dim)

    def F_vec(self, X: np.ndarray, pfun: Any = None, pargs: list[Any] | None = None) -> np.ndarray:
        M = X.shape[1]
        out = (pfun(*X, *pargs) if pfun is not None else self._f(*X))
        return np.stack([np.broadcast_to(np.asarray(o, dtype=float), (M,)) for o in out])

    @property
    def polynomial(self) -> bool:
        return all(sp.sympify(e).is_polynomial(*self.vars) for e in self.exprs_num)

    def iterate(self, ic: list[float], n: int) -> tuple[np.ndarray, bool]:
        if n > MAX_ITER:
            raise ChaosError(f"İterasyon sayısı çok büyük (≤ {MAX_ITER}).")
        X = np.empty((n + 1, self.dim))
        X[0] = np.asarray(ic, dtype=float)
        diverged = False
        with np.errstate(all="ignore"):
            for i in range(n):
                X[i + 1] = self.F(X[i])
                if not np.all(np.isfinite(X[i + 1])) or np.max(np.abs(X[i + 1])) > BOUND:
                    X = X[: i + 2]
                    diverged = True
                    break
        return X, diverged

    # ---------------------------------------------------------------- sembolik
    def symbolic(self, orbit: np.ndarray | None) -> dict[str, Any]:
        eq_latex = [rf"{var_latex(v)}^{{(n+1)}} = {sp.latex(e)}" if len(v) > 1 else rf"{v}_{{n+1}} = {sp.latex(e)}" for v, e in zip(self.var_names, self.exprs)]
        if self.det_num is not None:
            det_latex = rf"\det J = {sp.latex(sp.simplify(self.J_sym.det()))}"
            num_latex = rf"\det J = {sp.latex(sp.N(self.det_num, 6))}"
            state_dep = bool(self.det_num.free_symbols & set(self.vars))
        else:
            det_latex = r"\det J\ \ (N > 4:\ \text{sayısal hesap})"
            num_latex = r"\langle |\det J| \rangle_{\text{geo}}\ \text{yörünge boyunca}"
            state_dep = True
        info: dict[str, Any] = {
            "symbolic_latex": det_latex,
            "numeric_latex": num_latex,
            "state_dependent": state_dep,
        }
        if self.dim == 1:
            val = None
            if orbit is not None and len(orbit):
                with np.errstate(all="ignore"):
                    d = np.abs(np.broadcast_to(np.asarray(self._det(*orbit.T), dtype=float), (len(orbit),)))
                d = d[np.isfinite(d) & (d > 0)]
                val = float(np.exp(np.mean(np.log(d)))) if d.size else None
            info["value"] = fnum(val) if val is not None else None
            info["class"] = "1B Harita"
            info["detail"] = "1B haritada |f'(x)| yerel genişleme oranıdır; ⟨ln|f'|⟩ = λ."
        elif not state_dep:
            val = float(self.det_num)
            info["value"] = fnum(val)
            if abs(abs(val) - 1) < 1e-12:
                info["class"] = "Alan/Hacim Koruyan (Conservative)"
                info["detail"] = "|det J| = 1 : faz hacmi korunur."
            elif abs(val) < 1:
                info["class"] = "Kayıplı (Dissipative)"
                info["detail"] = f"|det J| = {abs(val):.4g} < 1 : her iterasyonda hacim bu oranla daralır."
            else:
                info["class"] = "Hacim Genişleten (Expanding)"
                info["detail"] = f"|det J| = {abs(val):.4g} > 1 : hacim büyür."
        else:
            gm = None
            if orbit is not None and len(orbit):
                with np.errstate(all="ignore"):
                    d = np.abs(np.broadcast_to(np.asarray(self._det(*orbit.T), dtype=float), (len(orbit),)))
                d = d[np.isfinite(d) & (d > 0)]
                gm = float(np.exp(np.mean(np.log(d)))) if d.size else None
            info["value"] = fnum(gm) if gm is not None else None
            info["mean_along_trajectory"] = info["value"]
            if gm is None:
                info["class"] = "Durum Bağımlı"
                info["detail"] = "det J duruma bağlı; yörünge verisi yok."
            elif gm < 1:
                info["class"] = "Kayıplı (Dissipative, ortalama)"
                info["detail"] = f"Yörünge boyunca geometrik ortalama |det J| = {gm:.4g} < 1."
            else:
                info["class"] = "Hacim Genişleten (ortalama)"
                info["detail"] = f"Yörünge boyunca geometrik ortalama |det J| = {gm:.4g} ≥ 1."
        fps, method = self.fixed_points(orbit)
        return {
            "dimension": self.dim,
            "variables": self.var_names,
            "equations_latex": eq_latex,
            "params": {k: fnum(float(v), 8) for k, v in self.params.items()},
            "params_latex": ", ".join(rf"{sp.latex(self.param_syms[k])} = {sp.latex(v)}" for k, v in self.params.items()),
            "determinant": info,
            "jacobian_latex": "J = " + sp.latex(self.J_sym),
            "jacobian_numeric_latex": "J = " + sp.latex(self.J_num.applyfunc(lambda v: sp.N(v, 5))),
            "fixed_points": fps,
            "fixed_points_method": method,
        }

    def _analyze_fp(self, pt: np.ndarray, exact: list[sp.Expr] | None) -> dict[str, Any]:
        J = self.jac(pt)
        eigs = np.linalg.eigvals(J)
        eigs = eigs[np.argsort(-np.abs(eigs))]
        label, stable, index = classify_fixed_point(eigs)
        if exact is not None:
            parts = []
            for v, val in zip(self.var_names, exact):
                txt = sp.latex(val)
                if len(txt) > 60:
                    txt = sp.latex(sp.N(val, 8))
                parts.append(f"{var_latex(v)}^* = {txt}")
            latex = r"\left(" + r",\; ".join(parts) + r"\right)"
        else:
            latex = r"\left(" + r",\; ".join(f"{var_latex(v)}^* \\approx {p:.6g}" for v, p in zip(self.var_names, pt)) + r"\right)"
        eig_latex = r",\; ".join(
            (f"\\lambda_{{{i + 1}}} = {e.real:.5g}" + (f" {'+' if e.imag >= 0 else '-'} {abs(e.imag):.5g}i" if abs(e.imag) > 1e-9 else ""))
            + f"\\;(|\\lambda| = {abs(e):.4g})"
            for i, e in enumerate(eigs)
        )
        return {
            "point": [fnum(p, 8) for p in pt],
            "latex": latex,
            "eigenvalues": [{"re": fnum(e.real, 8), "im": fnum(e.imag, 8), "mod": fnum(abs(e), 8)} for e in eigs],
            "eigen_latex": eig_latex,
            "type": label,
            "stable": stable,
            "index": index,
            "jacobian_latex": sp.latex(sp.Matrix(np.round(J, 6)).applyfunc(lambda v: sp.N(v, 5))),
        }

    def fixed_points(self, orbit: np.ndarray | None) -> tuple[list[dict[str, Any]], str]:
        G = [e - v for e, v in zip(self.exprs_num, self.vars)]
        results: list[dict[str, Any]] = []
        method = ""
        if self.polynomial and self.dim <= 4:
            sol, err = run_with_timeout(lambda: sp.solve(G, list(self.vars), dict=True), SOLVE_TIMEOUT)
            if err is None and sol:
                seen: list[np.ndarray] = []
                for s in sol:
                    try:
                        vals = [sp.sympify(s.get(v, v)) for v in self.vars]
                        if any(val.free_symbols for val in vals):
                            continue
                        cv = [complex(sp.N(val, 20)) for val in vals]
                    except Exception:  # noqa: BLE001
                        continue
                    if not all(abs(c.imag) < 1e-9 for c in cv):
                        continue
                    p = np.array([c.real for c in cv])
                    if any(np.linalg.norm(p - q) < 1e-9 * max(1.0, np.linalg.norm(q)) for q in seen):
                        continue
                    seen.append(p)
                    results.append(self._analyze_fp(p, vals))
                if results:
                    return results, "Analitik çözüm (sympy.solve, F(x) = x)"
                method = "Analitik çözümde reel kök yok → sayısal arama"
            elif err == "timeout":
                method = f"Analitik çözüm {SOLVE_TIMEOUT:.0f} s'yi aştı → sayısal fallback"
            else:
                method = "Analitik çözüm bulunamadı → sayısal fallback"
        else:
            method = ("Transandantal / parçalı harita → sayısal çoklu başlangıç araması" if self.dim <= 4 or not self.polynomial else "Yüksek boyut (N > 4) → sayısal çoklu başlangıç araması")
        rng = np.random.default_rng(7)
        n = self.dim
        guesses = [np.zeros(n)]
        if orbit is not None and len(orbit) and np.all(np.isfinite(orbit)):
            idx = np.linspace(0, len(orbit) - 1, 60).astype(int)
            guesses += [orbit[i] for i in idx]
            lo, hi = orbit.min(axis=0), orbit.max(axis=0)
        else:
            lo, hi = -2 * np.ones(n), 2 * np.ones(n)
        span = np.maximum(hi - lo, 1.0)
        guesses += list(rng.uniform(lo - 0.25 * span, hi + 0.25 * span, size=(80, n)))
        cands: list[np.ndarray] = []
        with np.errstate(all="ignore"):
            for g in guesses:
                try:
                    s = root(lambda u: self.F(u) - u, g, jac=lambda u: self.jac(u) - np.eye(n), method="hybr")
                except Exception:  # noqa: BLE001
                    continue
                if s.success and np.all(np.isfinite(s.x)) and np.linalg.norm(self.F(s.x) - s.x) < 1e-9:
                    if not any(np.linalg.norm(s.x - q) < 1e-6 * max(1.0, np.linalg.norm(q)) for q in cands):
                        cands.append(s.x)
        cands.sort(key=lambda p: tuple(np.round(p, 6)))
        for p in cands:
            results.append(self._analyze_fp(p, None))
        if not results:
            method += " — incelenen bölgede reel sabit nokta bulunamadı."
        return results, method

    # ---------------------------------------------------------------- Lyapunov
    def lyapunov(self, ic: list[float], n: int, transient: int) -> dict[str, Any]:
        d = self.dim
        x = np.asarray(ic, dtype=float)
        with np.errstate(all="ignore"):
            for _ in range(transient):
                x = self.F(x)
                if not np.all(np.isfinite(x)) or np.max(np.abs(x)) > BOUND:
                    return self._lyap_div()
            Q = np.eye(d)
            sums = np.zeros(d)
            hist_n, hist = [], []
            every = max(1, n // 1500)
            for i in range(1, n + 1):
                J = self.jac(x)
                Q, R = np.linalg.qr(J @ Q)
                dg = np.diag(R)
                sums += np.log(np.abs(np.where(dg == 0, 1e-300, dg)))
                Q = Q * np.sign(np.where(dg == 0, 1.0, dg))
                x = self.F(x)
                if not np.all(np.isfinite(x)) or np.max(np.abs(x)) > BOUND:
                    return self._lyap_div()
                if i % every == 0 or i == n:
                    hist_n.append(i)
                    hist.append(sums / i)
        lam = hist[-1]
        H = np.array(hist)
        tail = H[int(len(H) * 0.75):]
        fluct = float(np.max(np.std(tail, axis=0))) if len(tail) > 2 else 0.0
        tol = max(0.002, 3.0 / math.sqrt(n), 3 * fluct) if d > 1 else max(0.001, 2 * fluct)
        ls = sorted(lam.tolist(), reverse=True)
        return {
            "exponents": [fnum(v, 6) for v in ls],
            "sum": fnum(float(np.sum(lam)), 6),
            "kaplan_yorke": fnum(kaplan_yorke(ls), 6),
            "classification": diagnose_map(ls, tol),
            "zero_tolerance": fnum(tol, 3),
            "time": hist_n,
            "history": [clean(H[:, i]) for i in range(d)],
            "diverged": False,
            "t_total": n,
            "dt": 1,
        }

    def _lyap_div(self) -> dict[str, Any]:
        return {
            "exponents": [None] * self.dim, "sum": None, "kaplan_yorke": None,
            "classification": diagnose_map([0.0] * self.dim, 0.01, diverged=True),
            "zero_tolerance": None, "time": [], "history": [[] for _ in range(self.dim)], "diverged": True,
        }

    # ---------------------------------------------------------------- kelebek
    def butterfly(self, ic: list[float], n: int, delta0: float, base: np.ndarray) -> dict[str, Any]:
        ic2 = np.asarray(ic, dtype=float).copy()
        ic2[0] += delta0
        pert, _ = self.iterate(list(ic2), n)
        m = min(len(base), len(pert))
        y1, y2 = base[:m], pert[:m]
        dist = np.linalg.norm(y1 - y2, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            ln_d = np.log(np.where(dist > 0, dist, np.nan))
        nn = np.arange(m, dtype=float)
        lam_est = None
        fin = np.isfinite(ln_d)
        if np.any(fin):
            sat = float(np.nanmax(ln_d))
            l0 = math.log(max(abs(delta0), 1e-300))
            thr = l0 + 0.6 * (sat - l0)
            cross = np.where(fin & (ln_d >= thr))[0]
            end = int(cross[0]) if cross.size else m - 1
            seg = fin[:end]
            if end > 5 and np.sum(seg) > 4:
                lam_est = float(np.polyfit(nn[:end][seg], ln_d[:end][seg], 1)[0])
        hz = np.where(dist > 0.1 * (1 + float(np.nanstd(y1))))[0]
        idx = downsample_idx(m, 4000)
        return {
            "t": clean(nn[idx]),
            "base": [clean(y1[idx, i]) for i in range(self.dim)],
            "perturbed": [clean(y2[idx, i]) for i in range(self.dim)],
            "distance": clean(dist[idx]),
            "ln_distance": clean(ln_d[idx]),
            "delta0": delta0,
            "lambda_estimate": fnum(lam_est) if lam_est is not None else None,
            "predictability_horizon": int(hz[0]) if hz.size else None,
        }

    # ---------------------------------------------------------------- çatallaşma
    def bifurcation(
        self, param: str, p_min: float, p_max: float, steps: int, var: str, ic: list[float],
        transient: int, keep: int, lyap: bool = True,
    ) -> dict[str, Any]:
        if param not in self.params:
            raise ChaosError(f"'{param}' parametresi sistemde tanımlı değil.")
        if var not in self.var_names:
            raise ChaosError(f"'{var}' durum değişkeni sistemde yok.")
        if not (2 <= steps <= 3000):
            raise ChaosError("Adım sayısı 2 ile 3000 arasında olmalı.")
        if p_max <= p_min:
            raise ChaosError("Parametre aralığı geçersiz (max > min olmalı).")
        if keep < 1 or keep > 2000:
            raise ChaosError("Kaydedilen iterasyon 1–2000 arasında olmalı.")
        if (transient + keep) * steps > MAX_BIF_WORK_MAP:
            raise ChaosError("Tarama çok büyük; adım, geçici rejim veya kayıt sayısını azaltın.")
        names = list(self.params.keys())
        psyms = [self.param_syms[k] for k in names]
        f = sp.lambdify((*self.vars, *psyms), self.exprs, modules="numpy", cse=True)
        Jsym = sp.Matrix(self.exprs).jacobian(self.vars)
        Jlist = [[Jsym[a, b] for b in range(self.dim)] for a in range(self.dim)]
        Jf = sp.lambdify((*self.vars, *psyms), Jlist, modules="numpy", cse=True)
        M = steps
        pv = np.linspace(p_min, p_max, M)
        pargs = [pv if k == param else float(self.params[k]) for k in names]
        X = np.tile(np.asarray(ic, dtype=float)[:, None], (1, M))
        vi = self.var_names.index(var)
        d = self.dim
        rec = np.full((keep, M), np.nan)
        Q = np.tile(np.eye(d), (M, 1, 1))
        sums = np.zeros((M, d))
        with np.errstate(all="ignore"):
            for i in range(transient + keep):
                if lyap and i >= transient:
                    Jr = Jf(*X, *pargs)
                    Jm = np.empty((M, d, d))
                    for a in range(d):
                        for b in range(d):
                            Jm[:, a, b] = np.broadcast_to(np.asarray(Jr[a][b], dtype=float), (M,))
                    Jm = np.nan_to_num(Jm, nan=0.0, posinf=0.0, neginf=0.0)
                    Qn, R = np.linalg.qr(Jm @ Q)
                    dg = np.diagonal(R, axis1=1, axis2=2)
                    sums += np.log(np.abs(np.where(dg == 0, 1e-300, dg)))
                    Q = Qn * np.sign(np.where(dg == 0, 1.0, dg))[:, None, :]
                X = self.F_vec(X, f, pargs)
                bad = ~np.all(np.isfinite(X), axis=0) | (np.max(np.abs(X), axis=0) > BOUND)
                if np.any(bad):
                    X[:, bad] = np.nan
                if i >= transient:
                    rec[i - transient] = X[vi]
        diverged = ~np.all(np.isfinite(X), axis=0)
        px = np.repeat(pv[None, :], keep, axis=0)
        ok = np.isfinite(rec)
        P, Yv = px[ok], rec[ok]
        # aynı parametredeki yinelenen değerleri (periyodik yörüngeler) seyrelt
        if P.size > 400_000:
            sel = np.unique(np.linspace(0, P.size - 1, 400_000).astype(int))
            P, Yv = P[sel], Yv[sel]
        lam_max = None
        if lyap:
            lm = np.max(sums / max(1, keep), axis=1)
            lm[diverged] = np.nan
            lam_max = clean(lm)
        return {
            "param": param, "var": var,
            "p": clean(P), "maxima": clean(Yv),
            "p_values": clean(pv),
            "lambda_max": lam_max,
            "diverged": [fnum(v) for v in pv[diverged]],
            "n_points": int(P.size),
            "max_per_param": keep,
        }

    # ---------------------------------------------------------------- havza
    def basin(
        self, ic: list[float], var_a: str, var_b: str, a_range: tuple[float, float],
        b_range: tuple[float, float], res: int, n_iter: int,
    ) -> dict[str, Any]:
        if self.dim < 2:
            # 1B: ikinci eksen yok; x ekseni boyunca tek satır
            var_b = var_a
        for v in (var_a, var_b):
            if v not in self.var_names:
                raise ChaosError(f"'{v}' durum değişkeni sistemde yok.")
        if self.dim >= 2 and var_a == var_b:
            raise ChaosError("Havza için iki farklı değişken seçin.")
        if not (10 <= res <= 600):
            raise ChaosError("Çözünürlük 10 ile 600 arasında olmalı.")
        if a_range[1] <= a_range[0] or (self.dim >= 2 and b_range[1] <= b_range[0]):
            raise ChaosError("Havza aralığı geçersiz (max > min olmalı).")
        rows = res if self.dim >= 2 else 1
        M = res * rows
        if n_iter * M > MAX_BIF_WORK_MAP * 2:
            raise ChaosError("Havza hesabı çok büyük; çözünürlüğü veya iterasyonu azaltın.")
        av = np.linspace(a_range[0], a_range[1], res)
        bv = np.linspace(b_range[0], b_range[1], rows) if self.dim >= 2 else np.array([0.0])
        A, B = np.meshgrid(av, bv)
        X = np.tile(np.asarray(ic, dtype=float)[:, None], (1, M))
        X[self.var_names.index(var_a)] = A.ravel()
        if self.dim >= 2:
            X[self.var_names.index(var_b)] = B.ravel()
        n_win = max(10, n_iter // 2)
        s1 = np.zeros((self.dim, M))
        s2 = np.zeros((self.dim, M))
        with np.errstate(all="ignore"):
            for i in range(n_iter):
                X = self.F_vec(X)
                bad = ~np.all(np.isfinite(X), axis=0) | (np.max(np.abs(X), axis=0) > 1e6)
                if np.any(bad):
                    X[:, bad] = np.nan
                if i >= n_iter - n_win:
                    s1 += X
                    s2 += X * X
        diverged = ~np.all(np.isfinite(X), axis=0)
        mean = (s1 / n_win).T
        std = np.sqrt(np.maximum((s2 / n_win).T - mean ** 2, 0.0))
        labels, info = cluster_attractors(mean, std, diverged)
        return {
            "var_a": var_a, "var_b": var_b if self.dim >= 2 else None,
            "a": clean(av), "b": clean(bv),
            "labels": labels.reshape(rows, res).tolist(),
            "attractors": info,
            "diverged_fraction": fnum(float(np.mean(diverged)), 4),
            "res": res, "n_iter": n_iter,
        }

    def function_curve(self, orbit: np.ndarray, n: int = 600) -> dict[str, Any] | None:
        """1B harita için y = f(x) eğrisi (örümcek ağı diyagramı)."""
        if self.dim != 1:
            return None
        fin = orbit[np.isfinite(orbit[:, 0]), 0]
        if fin.size == 0:
            lo, hi = -1.0, 1.0
        else:
            lo, hi = float(fin.min()), float(fin.max())
        span = max(hi - lo, 1e-3)
        xs = np.linspace(lo - 0.08 * span, hi + 0.08 * span, n)
        with np.errstate(all="ignore"):
            ys = np.broadcast_to(np.asarray(self._f(xs)[0], dtype=float), xs.shape)
        return {"x": clean(xs), "y": clean(ys)}


# ---------------------------------------------------------------------------
# Hazır haritalar
# ---------------------------------------------------------------------------
MAP_PRESETS: dict[str, dict[str, Any]] = {
    "logistic": {
        "name": "Lojistik Harita (1B)",
        "equations": ["r*x*(1 - x)"], "params": "r=3.9", "initial": [0.2],
        "n_iter": 5000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "r", "min": 2.5, "max": 4.0, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "x", "a_range": [-0.5, 1.5], "b_range": [0, 1], "res": 400, "n": 300, "override": ""},
    },
    "sine": {
        "name": "Sinüs Haritası (1B)",
        "equations": ["a*sin(pi*x)"], "params": "a=0.95", "initial": [0.3],
        "n_iter": 5000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 0.6, "max": 1.0, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "x", "a_range": [-1.5, 1.5], "b_range": [0, 1], "res": 400, "n": 300, "override": ""},
    },
    "tent": {
        "name": "Çadır (Tent) Haritası (1B)",
        "equations": ["mu*(1 - abs(2*x - 1))/2"], "params": "mu=1.99", "initial": [0.123],
        "n_iter": 5000, "transient": 100, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "mu", "min": 1.0, "max": 1.999, "steps": 800, "var": "x", "transient": 300, "keep": 200},
        "basin": {"a": "x", "b": "x", "a_range": [-0.5, 1.5], "b_range": [0, 1], "res": 400, "n": 200, "override": ""},
    },
    "gauss": {
        "name": "Gauss (Mouse) Haritası (1B)",
        "equations": ["exp(-alpha*x^2) + beta"], "params": "alpha=6.2, beta=-0.5", "initial": [0.1],
        "n_iter": 5000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "beta", "min": -1.0, "max": 1.0, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "x", "a_range": [-2, 2], "b_range": [0, 1], "res": 400, "n": 300, "override": "beta=-0.52"},
    },
    "henon": {
        "name": "Hénon Haritası (2B)",
        "equations": ["1 - a*x^2 + y", "b*x"], "params": "a=1.4, b=0.3", "initial": [0.0, 0.0],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 1.0, "max": 1.42, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-2.5, 2.5], "b_range": [-2.5, 2.5], "res": 250, "n": 200, "override": ""},
    },
    "lozi": {
        "name": "Lozi Haritası (2B, parçalı doğrusal)",
        "equations": ["1 - a*abs(x) + y", "b*x"], "params": "a=1.7, b=0.5", "initial": [0.1, 0.1],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 1.0, "max": 1.8, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-3, 3], "b_range": [-3, 3], "res": 250, "n": 200, "override": ""},
    },
    "ikeda": {
        "name": "Ikeda Haritası (2B)",
        "equations": [
            "1 + u*(x*cos(0.4 - 6/(1 + x^2 + y^2)) - y*sin(0.4 - 6/(1 + x^2 + y^2)))",
            "u*(x*sin(0.4 - 6/(1 + x^2 + y^2)) + y*cos(0.4 - 6/(1 + x^2 + y^2)))",
        ],
        "params": "u=0.9", "initial": [0.1, 0.1],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "u", "min": 0.5, "max": 0.95, "steps": 600, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-1, 3], "b_range": [-3, 2], "res": 200, "n": 300, "override": "u=0.75"},
    },
    "tinkerbell": {
        "name": "Tinkerbell Haritası (2B)",
        "equations": ["x^2 - y^2 + a*x + b*y", "2*x*y + c*x + d*y"],
        "params": "a=0.9, b=-0.6013, c=2.0, d=0.5", "initial": [-0.72, -0.64],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 0.7, "max": 0.9, "steps": 600, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-1.5, 0.8], "b_range": [-1.8, 0.8], "res": 220, "n": 300, "override": ""},
    },
    "duffing_map": {
        "name": "Duffing Haritası (2B)",
        "equations": ["y", "-b*x + a*y - y^3"], "params": "a=2.75, b=0.2", "initial": [0.1, 0.1],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 2.0, "max": 2.8, "steps": 800, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-2, 2], "b_range": [-2, 2], "res": 250, "n": 300, "override": "a=2.3"},
    },
    "henon3": {
        "name": "Genelleştirilmiş Hénon (3B Hiperkaotik)",
        "equations": ["a - y^2 - b*z", "x", "y"], "params": "a=1.76, b=0.1", "initial": [0.1, 0.1, 0.1],
        "n_iter": 20000, "transient": 200, "delta0": 1e-8, "lyap_n": 20000,
        "bif": {"param": "a", "min": 1.0, "max": 1.8, "steps": 600, "var": "x", "transient": 500, "keep": 200},
        "basin": {"a": "x", "b": "y", "a_range": [-2.5, 2.5], "b_range": [-2.5, 2.5], "res": 200, "n": 200, "override": ""},
    },
    "cml5": {
        "name": "Bağlaşık Lojistik Kafes (5B)",
        "equations": ['(1 - e)*r*x1*(1 - x1) + e/2*(r*x5*(1 - x5) + r*x2*(1 - x2))', '(1 - e)*r*x2*(1 - x2) + e/2*(r*x1*(1 - x1) + r*x3*(1 - x3))', '(1 - e)*r*x3*(1 - x3) + e/2*(r*x2*(1 - x2) + r*x4*(1 - x4))', '(1 - e)*r*x4*(1 - x4) + e/2*(r*x3*(1 - x3) + r*x5*(1 - x5))', '(1 - e)*r*x5*(1 - x5) + e/2*(r*x4*(1 - x4) + r*x1*(1 - x1))'],
        "params": "r=3.9, e=0.1", "initial": [0.1, 0.2, 0.3, 0.4, 0.5],
        "n_iter": 10000, "transient": 200, "delta0": 1e-8, "lyap_n": 10000,
        "bif": {"param": "e", "min": 0.0, "max": 0.6, "steps": 400, "var": "x1", "transient": 500, "keep": 150},
        "basin": {"a": "x1", "b": "x2", "a_range": [-0.2, 1.2], "b_range": [-0.2, 1.2], "res": 150, "n": 300, "override": ""},
        "axes": ["x1", "x2", "x3"],
    },
}


# ---------------------------------------------------------------------------
# Üst düzey API
# ---------------------------------------------------------------------------
def map_full_analysis(
    equations: list[str], params: str, initial: list[float], n_iter: int, transient: int,
    delta0: float, lyap_n: int, compute_lyapunov: bool = True,
) -> dict[str, Any]:
    m = DiscreteMap(equations, params)
    if len(initial) < m.dim:
        raise ChaosError(f"{m.dim} adet başlangıç koşulu gerekli.")
    ic = [float(v) for v in initial[: m.dim]]
    if n_iter < 20:
        raise ChaosError("İterasyon sayısı en az 20 olmalı.")
    if transient >= n_iter:
        raise ChaosError("Geçici iterasyon sayısı toplamdan küçük olmalı.")
    orbit, diverged = m.iterate(ic, n_iter)
    finite = orbit[np.all(np.isfinite(orbit), axis=1)]
    att = finite[transient:] if len(finite) > transient + 10 else finite
    sym = m.symbolic(att)
    idx = downsample_idx(len(orbit), MAX_PLOT_POINTS * 2)
    trajectory = {
        "t": clean(np.arange(len(orbit))[idx]),
        "states": [clean(orbit[idx, i]) for i in range(m.dim)],
        "diverged": diverged,
        "warning": "Yörünge ıraksadı (|x| > 1e10)." if diverged else None,
        "n_points": int(len(orbit)),
        "transient": transient,
    }
    bfly = m.butterfly(ic, min(n_iter, 2000), delta0, orbit)
    lyap = m.lyapunov(ic, lyap_n, transient) if compute_lyapunov else None
    spectrum = power_spectrum(finite, 1.0, m.var_names, discard_frac=min(0.5, transient / max(1, len(finite))))
    fractal = fractal_analysis(att) if not diverged else {
        "correlation": {"available": False, "reason": "diverged"},
        "box": {"available": False, "reason": "diverged"},
    }
    if lyap is not None:
        fractal["kaplan_yorke"] = lyap.get("kaplan_yorke")
    if len(att):
        ai = downsample_idx(len(att), 8000)
        fractal["points"] = [clean(att[ai, i]) for i in range(m.dim)]
    return {
        "kind": "map",
        "symbolic": sym,
        "trajectory": trajectory,
        "butterfly": bfly,
        "lyapunov": lyap,
        "spectrum": spectrum,
        "fractal": fractal,
        "curve": m.function_curve(att if len(att) else orbit),
        "variables": m.var_names,
        "dimension": m.dim,
    }


def _merge(params: str, override: str) -> str:
    override = (override or "").strip()
    if not override:
        return params
    return f"{params}, {override}" if params.strip() else override


def map_bifurcation(
    equations: list[str], params: str, initial: list[float], param: str, p_min: float, p_max: float,
    steps: int, var: str, transient: int, keep: int,
) -> dict[str, Any]:
    m = DiscreteMap(equations, params)
    ic = [float(v) for v in initial[: m.dim]]
    return m.bifurcation(param, p_min, p_max, steps, var, ic, transient, keep)


def map_basin(
    equations: list[str], params: str, initial: list[float], var_a: str, var_b: str,
    a_min: float, a_max: float, b_min: float, b_max: float, res: int, n_iter: int, override: str = "",
) -> dict[str, Any]:
    m = DiscreteMap(equations, _merge(params, override))
    ic = [float(v) for v in initial[: m.dim]]
    out = m.basin(ic, var_a, var_b, (a_min, a_max), (b_min, b_max), res, n_iter)
    fps, _ = m.fixed_points(None)
    from analysis_tools import match_equilibria

    match_equilibria(out["attractors"], fps)
    out["equilibria"] = [{"point": e["point"], "stable": e["stable"], "type": e["type"]} for e in fps]
    out["params_used"] = {k: fnum(float(v), 8) for k, v in m.params.items()}
    return out


def map_compare(keys: list[str]) -> dict[str, Any]:
    from analysis_tools import box_counting_dimension, correlation_dimension

    rows = []
    for key in keys:
        p = MAP_PRESETS.get(key)
        if p is None:
            continue
        row: dict[str, Any] = {"key": key, "name": p["name"], "dim": len(p["equations"])}
        try:
            m = DiscreteMap(p["equations"], p["params"])
            orbit, div = m.iterate(p["initial"], p["n_iter"])
            att = orbit[p["transient"]:]
            att = att[np.all(np.isfinite(att), axis=1)]
            ly = m.lyapunov(p["initial"], min(p["lyap_n"], 10000), p["transient"])
            spec = power_spectrum(att, 1.0, m.var_names, discard_frac=0.0)
            cd = correlation_dimension(att, n_max=1500, theiler=1)
            bd = box_counting_dimension(att)
            ents = [v["spectral_entropy"] for v in spec.get("vars", {}).values() if v.get("spectral_entropy") is not None]
            row.update({
                "exponents": ly["exponents"], "lambda_max": ly["exponents"][0], "sum": ly["sum"],
                "kaplan_yorke": ly["kaplan_yorke"], "classification": ly["classification"],
                "D2": cd.get("D2"), "D0": bd.get("D0"),
                "spectral_entropy": fnum(float(np.mean(ents)), 4) if ents else None,
                "dominant_freq": spec.get("vars", {}).get("x", {}).get("dominant_freq"),
                "ok": True,
            })
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": False, "error": str(exc)})
        rows.append(row)
    return {"rows": rows}
