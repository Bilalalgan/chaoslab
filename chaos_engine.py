"""
ChaosLab - Kaotik Sistem Analiz Motoru
======================================
Sürekli zamanlı 3B / 4B doğrusal olmayan dinamik sistemler için
sembolik (SymPy) ve sayısal (NumPy / SciPy) analiz algoritmaları.

Modüller
--------
1. Yapısal & sembolik analiz : boyut, otonomluk, diverjans, Jacobian, denge noktaları
2. Yörünge / faz portresi     : solve_ivp (DOP853 / RK45)
3. Kelebek etkisi             : iki yakın yörüngenin ayrışması, ln||Δx(t)||
4. Lyapunov spektrumu         : varyasyonel denklemler + QR (Gram-Schmidt) yeniden ortonormalizasyon
5. Çatallaşma diyagramı       : vektörize RK4 parametre taraması + argrelextrema yerel maksimumlar
"""
from __future__ import annotations

import math
import re
import threading
from typing import Any, Callable

import numpy as np
import sympy as sp
from scipy.integrate import solve_ivp
from scipy.optimize import root
from scipy.signal import argrelextrema
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
STATE_NAMES = ["x", "y", "z", "w"]
MAX_DIM = 10


def state_names(n: int) -> list[str]:
    """n ≤ 4: x, y, z, w; n > 4: x1 … xn."""
    return STATE_NAMES[:n] if n <= 4 else [f"x{i}" for i in range(1, n + 1)]


def var_latex(v: str) -> str:
    return v if len(v) == 1 else f"{v[0]}_{{{v[1:]}}}"


ALL_STATE_NAMES = set(STATE_NAMES) | {f"x{i}" for i in range(1, MAX_DIM + 1)}
T_SYM = sp.Symbol("t")
TRANSFORMS = standard_transformations + (convert_xor,)
ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9_+\-*/^().,\s]*$")
RESERVED = ALL_STATE_NAMES | {"t", "pi", "e_const"}
PY_KEYWORDS = {
    "lambda", "and", "or", "not", "if", "else", "for", "while", "in", "is",
    "def", "class", "return", "import", "from", "as", "with", "pass", "del",
    "global", "nonlocal", "try", "except", "finally", "raise", "yield", "assert",
    "break", "continue", "None", "True", "False", "async", "await", "elif",
}
FUNCTIONS: dict[str, Any] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "exp": sp.exp, "log": sp.log, "ln": sp.log, "sqrt": sp.sqrt,
    "abs": sp.Abs, "Abs": sp.Abs, "sign": sp.sign, "pi": sp.pi,
}
SOLVE_TIMEOUT = 3.0
MAX_SIM_POINTS = 200_000
MAX_PLOT_POINTS = 15_000
MAX_BIF_WORK = 200_000_000  # (toplam adım) × (parametre sayısı) üst sınırı


class ChaosError(ValueError):
    """Kullanıcıya gösterilecek analiz hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def clean(arr: Any) -> Any:
    """NumPy dizilerini JSON uyumlu listeye çevirir (NaN / Inf -> None)."""
    a = np.asarray(arr, dtype=float)
    if a.ndim == 0:
        v = float(a)
        return v if math.isfinite(v) else None
    out = a.astype(object)
    out[~np.isfinite(a)] = None
    return out.tolist()


def fnum(v: float, digits: int = 6) -> float | None:
    v = float(v)
    if not math.isfinite(v):
        return None
    return float(f"{v:.{digits}g}")


def downsample_idx(n: int, limit: int = MAX_PLOT_POINTS) -> np.ndarray:
    if n <= limit:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, limit).astype(int))


def run_with_timeout(fn: Callable[[], Any], timeout: float) -> tuple[Any, str | None]:
    """fn'i ayrı bir daemon iş parçacığında çalıştırır; süre aşımında (None, 'timeout')."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return None, "timeout"
    if "error" in box:
        return None, f"error: {box['error']}"
    return box.get("value"), None


def parse_params(text: str) -> dict[str, sp.Expr]:
    """'sigma=10, rho=28, beta=8/3' -> {'sigma': 10, 'rho': 28, 'beta': 8/3} (SymPy sayıları)."""
    params: dict[str, sp.Expr] = {}
    if not text:
        return params
    for raw in re.split(r"[,;\n]+", text):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise ChaosError(f"Parametre biçimi hatalı: '{item}' (örnek: sigma=10)")
        name, value = (s.strip() for s in item.split("=", 1))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ChaosError(f"Geçersiz parametre adı: '{name}'")
        if name in RESERVED or name in FUNCTIONS or name in PY_KEYWORDS:
            raise ChaosError(f"'{name}' ayrılmış bir isimdir, parametre adı olarak kullanılamaz")
        if not ALLOWED_PATTERN.match(value) or "__" in value:
            raise ChaosError(f"Parametre değeri geçersiz: '{value}'")
        try:
            val = parse_expr(value, local_dict=dict(FUNCTIONS), transformations=TRANSFORMS)
            val = sp.nsimplify(val, rational=True) if val.is_Float else val
            float(val)
        except Exception as exc:  # noqa: BLE001
            raise ChaosError(f"Parametre değeri sayıya çevrilemedi: {name}={value}") from exc
        params[name] = val
    return params


def classify_equilibrium(eigs: np.ndarray, tol: float = 1e-7) -> tuple[str, bool, int]:
    """Özdeğerlerden topolojik tip, kararlılık ve indeks (kararsız boyut)."""
    re_ = eigs.real
    im_ = eigs.imag
    scale = max(1.0, float(np.max(np.abs(eigs))))
    ztol = tol * scale
    n_pos = int(np.sum(re_ > ztol))
    n_neg = int(np.sum(re_ < -ztol))
    n_zero = len(eigs) - n_pos - n_neg
    complex_mask = np.abs(im_) > ztol
    has_complex = bool(np.any(complex_mask))
    complex_unstable = bool(np.any(complex_mask & (re_ > ztol)))
    complex_stable = bool(np.any(complex_mask & (re_ < -ztol)))

    if n_zero > 0:
        pure_imag = bool(np.any((np.abs(re_) <= ztol) & complex_mask))
        if pure_imag:
            label = "Hiperbolik Değil – Hopf Adayı (saf sanal çift ±iω)"
        else:
            label = "Hiperbolik Değil – Sıfır Özdeğer (Eyer-Düğüm / Pitchfork adayı)"
        return label, False, n_pos
    if n_pos == 0:
        label = "Kararlı Odak-Düğüm (Stable Focus-Node)" if has_complex else "Kararlı Düğüm (Stable Node)"
        return label, True, 0
    if n_neg == 0:
        label = "Kararsız Odak-Düğüm (Unstable Focus-Node)" if has_complex else "Kararsız Düğüm (Unstable Node)"
        return label, False, n_pos
    if has_complex:
        if complex_unstable and not complex_stable:
            kind = "kararsız spiral düzlem"
        elif complex_stable and not complex_unstable:
            kind = "kararlı spiral düzlem"
        else:
            kind = "karma spiral"
        label = f"Kararsız Eyer-Odak (Saddle-Focus) index-{n_pos} [{kind}]"
    else:
        label = f"Kararsız Eyer (Saddle) index-{n_pos}"
    return label, False, n_pos


def kaplan_yorke(lyap: list[float]) -> float:
    lam = sorted(lyap, reverse=True)
    cum = np.cumsum(lam)
    if cum[0] < 0:
        return 0.0
    j = int(np.max(np.where(cum >= 0)[0])) + 1  # en büyük j: sum_{i<=j} >= 0
    if j >= len(lam):
        return float(len(lam))
    return float(j + cum[j - 1] / abs(lam[j]))


def diagnose(lyap: list[float], tol: float, diverged: bool = False) -> str:
    if diverged:
        return "Iraksak (Sınırsız Yörünge)"
    lam = sorted(lyap, reverse=True)
    l1 = lam[0]
    l2 = lam[1] if len(lam) > 1 else -math.inf
    total = float(np.sum(lam))
    if l1 > tol and l2 > tol:
        return "Hiperkaotik"
    if l1 > tol:
        if total < 0:
            return "Kaotik"
        return "Kararsız / Hacim Genişleten (Σλ ≥ 0)"
    if abs(l1) <= tol:
        if abs(l2) <= tol:
            return "Yarı-Periyodik (Tor, T²)"
        return "Periyodik (Limit Çevrimi)"
    return "Kararlı Denge Noktası"


# ---------------------------------------------------------------------------
# Sistem
# ---------------------------------------------------------------------------
class ChaosSystem:
    """Kullanıcı tanımlı / hazır ODE sistemi: dx/dt = F(x, t; p)."""

    def __init__(self, equations: list[str], params_text: str = "") -> None:
        eqs = [e.strip() for e in equations if e is not None and str(e).strip() != ""]
        if not 1 <= len(eqs) <= MAX_DIM:
            raise ChaosError(f"Sistem 1–{MAX_DIM} denklemden oluşmalıdır (≤4: x, y, z, w; >4: x1 … xN).")
        self.dim = len(eqs)
        self.var_names = state_names(self.dim)
        self.vars = sp.symbols(" ".join(self.var_names), real=True, seq=True)
        self.params = parse_params(params_text)
        self.param_syms = {name: sp.Symbol(name, real=True) for name in self.params}

        local: dict[str, Any] = dict(FUNCTIONS)
        local.update({n: s for n, s in zip(self.var_names, self.vars)})
        local["t"] = T_SYM
        local.update(self.param_syms)
        allowed = set(self.vars) | set(self.param_syms.values()) | {T_SYM}

        self.exprs: list[sp.Expr] = []
        for name, eq in zip(self.var_names, eqs):
            if not ALLOWED_PATTERN.match(eq) or "__" in eq:
                raise ChaosError(f"d{name}/dt denkleminde geçersiz karakter var.")
            try:
                expr = parse_expr(eq, local_dict=local, transformations=TRANSFORMS)
            except Exception as exc:  # noqa: BLE001
                raise ChaosError(f"d{name}/dt = '{eq}' ayrıştırılamadı: {exc}") from exc
            expr = sp.sympify(expr)
            unknown = expr.free_symbols - allowed
            if unknown:
                names = ", ".join(sorted(str(s) for s in unknown))
                raise ChaosError(
                    f"d{name}/dt denkleminde tanımsız sembol(ler): {names}. "
                    f"Parametre olarak ekleyin veya {self.dim}B sistem için yalnızca {', '.join(self.var_names)}, t kullanın."
                )
            self.exprs.append(expr)

        self.subs = {self.param_syms[k]: v for k, v in self.params.items()}
        self.exprs_num = [sp.sympify(e.subs(self.subs)) for e in self.exprs]
        self.J_sym = sp.Matrix(self.exprs).jacobian(self.vars)
        self.J_num = sp.Matrix(self.exprs_num).jacobian(self.vars)

        args = (T_SYM, *self.vars)
        self._f = sp.lambdify(args, self.exprs_num, modules="numpy", cse=True)
        self._J = sp.lambdify(args, self.J_num, modules="numpy", cse=True)
        div_num = sp.simplify(self.J_num.trace())
        self._div = sp.lambdify(args, div_num, modules="numpy")
        self.div_num_expr = div_num

        # Varyasyonel sistem: [F(x); J(x)·Φ] (Φ satır-öncelikli düzleştirilmiş)
        n = self.dim
        self.phi_syms = sp.symbols(f"phi_0:{n * n}")
        Phi = sp.Matrix(n, n, self.phi_syms)
        JPhi = self.J_num * Phi
        aug = list(self.exprs_num) + [JPhi[i, j] for i in range(n) for j in range(n)]
        self._aug = sp.lambdify((T_SYM, *self.vars, *self.phi_syms), aug, modules="numpy", cse=True)

    # ------------------------------------------------------------------ sayısal
    def rhs(self, t: float, s: np.ndarray) -> np.ndarray:
        return np.asarray(self._f(t, *s), dtype=float)

    def jac(self, t: float, s: np.ndarray) -> np.ndarray:
        return np.asarray(self._J(t, *s), dtype=float).reshape(self.dim, self.dim)

    def aug_rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        return np.asarray(self._aug(t, *y), dtype=float)

    @property
    def autonomous(self) -> bool:
        return all(T_SYM not in e.free_symbols for e in self.exprs)

    @property
    def polynomial(self) -> bool:
        return all(sp.sympify(e).is_polynomial(*self.vars) for e in self.exprs_num)

    # ------------------------------------------------------------- MODÜL 1
    def symbolic_analysis(self, traj: np.ndarray | None = None) -> dict[str, Any]:
        eq_latex = [
            rf"\dot{{{var_latex(v)}}} = {sp.latex(e)}" for v, e in zip(self.var_names, self.exprs)
        ]
        div_sym = sp.simplify(self.J_sym.trace())
        div_num = self.div_num_expr
        state_dep = bool(div_num.free_symbols & (set(self.vars) | {T_SYM}))

        div_info: dict[str, Any] = {
            "symbolic_latex": rf"\nabla \cdot \mathbf{{F}} = {sp.latex(div_sym)}",
            "numeric_latex": rf"\nabla \cdot \mathbf{{F}} = {sp.latex(sp.N(div_num, 6))}",
            "state_dependent": state_dep,
        }
        if not state_dep:
            val = float(div_num)
            div_info["value"] = fnum(val)
            if abs(val) < 1e-12:
                div_info["class"] = "Korunumlu (Conservative)"
                div_info["detail"] = "∇·F = 0 : faz hacmi korunur (Liouville)."
            elif val < 0:
                div_info["class"] = "Kayıplı (Dissipative)"
                div_info["detail"] = (
                    f"∇·F = {val:.4g} < 0 : faz hacmi V(t) = V₀·e^({val:.4g}·t) ile üstel daralır; garip çekici oluşabilir."
                )
            else:
                div_info["class"] = "Hacim Genişleten (Expanding)"
                div_info["detail"] = f"∇·F = {val:.4g} > 0 : faz hacmi üstel büyür."
        else:
            mean_val = None
            if traj is not None and traj.size:
                with np.errstate(all="ignore"):
                    vals = np.asarray(self._div(0.0, *traj.T), dtype=float)
                    vals = np.broadcast_to(vals, (traj.shape[0],))
                    vals = vals[np.isfinite(vals)]
                if vals.size:
                    mean_val = float(np.mean(vals))
            div_info["value"] = fnum(mean_val) if mean_val is not None else None
            div_info["mean_along_trajectory"] = div_info["value"]
            if mean_val is None:
                div_info["class"] = "Durum Bağımlı"
                div_info["detail"] = "Diverjans duruma bağlı; yörünge verisi yok."
            elif abs(mean_val) < 1e-6:
                div_info["class"] = "Ortalama Korunumlu"
                div_info["detail"] = f"⟨∇·F⟩ ≈ {mean_val:.4g} (yörünge boyunca ortalama)."
            elif mean_val < 0:
                div_info["class"] = "Kayıplı (Dissipative, ortalama)"
                div_info["detail"] = (
                    f"Diverjans duruma bağlı; yörünge boyunca ⟨∇·F⟩ = {mean_val:.4g} < 0 → ortalamada hacim daralır."
                )
            else:
                div_info["class"] = "Hacim Genişleten (ortalama)"
                div_info["detail"] = f"Yörünge boyunca ⟨∇·F⟩ = {mean_val:.4g} > 0."

        jac_latex = r"J = " + sp.latex(self.J_sym)
        jac_num_latex = r"J = " + sp.latex(self.J_num.applyfunc(lambda v: sp.N(v, 5)))

        if self.autonomous:
            equilibria, eq_method = self.equilibria(traj)
        else:
            equilibria, eq_method = [], "Otonom olmayan sistem: F(x, t) = 0 zamandan bağımsız denge tanımlamaz."

        return {
            "dimension": self.dim,
            "variables": self.var_names,
            "autonomous": self.autonomous,
            "autonomy_label": "Otonom" if self.autonomous else "Otonom Değil",
            "equations_latex": eq_latex,
            "params": {k: fnum(float(v), 8) for k, v in self.params.items()},
            "params_latex": ", ".join(
                rf"{sp.latex(self.param_syms[k])} = {sp.latex(v)}" for k, v in self.params.items()
            ),
            "divergence": div_info,
            "jacobian_latex": jac_latex,
            "jacobian_numeric_latex": jac_num_latex,
            "equilibria": equilibria,
            "equilibria_method": eq_method,
        }

    def _analyze_point(self, pt: np.ndarray, exact: list[sp.Expr] | None) -> dict[str, Any]:
        J = self.jac(0.0, pt)
        eigs = np.linalg.eigvals(J)
        order = np.argsort(-eigs.real)
        eigs = eigs[order]
        label, stable, index = classify_equilibrium(eigs)
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
            for i, e in enumerate(eigs)
        )
        return {
            "point": [fnum(p, 8) for p in pt],
            "latex": latex,
            "eigenvalues": [{"re": fnum(e.real, 8), "im": fnum(e.imag, 8)} for e in eigs],
            "eigen_latex": eig_latex,
            "type": label,
            "stable": stable,
            "index": index,
            "jacobian_latex": sp.latex(sp.Matrix(np.round(J, 6)).applyfunc(lambda v: sp.N(v, 5))),
        }

    def _dedupe(self, pts: list[np.ndarray]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for p in pts:
            if not np.all(np.isfinite(p)):
                continue
            if any(np.linalg.norm(p - q) < 1e-6 * max(1.0, np.linalg.norm(q)) for q in out):
                continue
            out.append(p)
        return out

    def equilibria(self, traj: np.ndarray | None = None) -> tuple[list[dict[str, Any]], str]:
        """F(x)=0: önce analitik (sympy.solve, 3 s zaman aşımı), olmazsa sayısal çoklu başlangıç + nsolve."""
        results: list[dict[str, Any]] = []
        method = ""
        if self.polynomial and self.dim <= 4:
            sol, err = run_with_timeout(
                lambda: sp.solve(self.exprs_num, self.vars, dict=True), SOLVE_TIMEOUT
            )
            if err is None and sol:
                pts, exacts = [], []
                for s in sol:
                    try:
                        vals = [sp.sympify(s.get(v, v)) for v in self.vars]
                        if any(val.free_symbols for val in vals):
                            continue  # sürekli denge kümesi (serbest değişken) - atla
                        cvals = [complex(sp.N(val, 20)) for val in vals]
                    except Exception:  # noqa: BLE001
                        continue
                    if all(abs(c.imag) < 1e-9 for c in cvals):
                        pts.append(np.array([c.real for c in cvals]))
                        exacts.append(vals)
                seen: list[np.ndarray] = []
                for p, ex in zip(pts, exacts):
                    if any(np.linalg.norm(p - q) < 1e-9 * max(1.0, np.linalg.norm(q)) for q in seen):
                        continue
                    seen.append(p)
                    results.append(self._analyze_point(p, ex))
                if results:
                    return results, "Analitik çözüm (sympy.solve)"
                method = "Analitik çözümde reel kök yok → sayısal arama"
            elif err == "timeout":
                method = f"Analitik çözüm {SOLVE_TIMEOUT:.0f} s'yi aştı → sayısal (root + nsolve) fallback"
            else:
                method = "Analitik çözüm bulunamadı → sayısal (root + nsolve) fallback"
        else:
            method = ("Transandantal sistem → sayısal (root + nsolve) çoklu başlangıç araması" if self.dim <= 4 or not self.polynomial else "Yüksek boyut (N > 4) → sayısal (root + nsolve) çoklu başlangıç araması")

        pts = self._numeric_equilibria(traj)
        for p in pts:
            results.append(self._analyze_point(p, None))
        if not results:
            method += " — incelenen bölgede reel denge noktası bulunamadı."
        return results, method

    def _numeric_equilibria(self, traj: np.ndarray | None) -> list[np.ndarray]:
        rng = np.random.default_rng(12345)
        n = self.dim
        guesses: list[np.ndarray] = [np.zeros(n)]
        if traj is not None and traj.size and np.all(np.isfinite(traj)):
            idx = np.linspace(0, traj.shape[0] - 1, 60).astype(int)
            guesses += [traj[i] for i in idx]
            lo, hi = traj.min(axis=0), traj.max(axis=0)
        else:
            lo, hi = -10 * np.ones(n), 10 * np.ones(n)
        span = np.maximum(hi - lo, 1.0)
        lo, hi = lo - 0.25 * span, hi + 0.25 * span
        guesses += list(rng.uniform(lo, hi, size=(80, n)))

        def f(s: np.ndarray) -> np.ndarray:
            return self.rhs(0.0, s)

        def jf(s: np.ndarray) -> np.ndarray:
            return self.jac(0.0, s)

        cands: list[np.ndarray] = []
        with np.errstate(all="ignore"):
            for g in guesses:
                try:
                    sol = root(f, g, jac=jf, method="hybr")
                except Exception:  # noqa: BLE001
                    continue
                if sol.success and np.all(np.isfinite(sol.x)) and np.linalg.norm(f(sol.x)) < 1e-8:
                    cands.append(sol.x)
        cands = self._dedupe(cands)

        polished: list[np.ndarray] = []
        for c in cands:
            try:
                ns = sp.nsolve(self.exprs_num, self.vars, [float(v) for v in c], tol=1e-25, prec=30)
                p = np.array([float(v) for v in ns])
                if np.linalg.norm(p - c) < 1e-4 * max(1.0, np.linalg.norm(c)):
                    polished.append(p)
                    continue
            except Exception:  # noqa: BLE001
                pass
            polished.append(c)
        polished = self._dedupe(polished)
        polished.sort(key=lambda p: (round(float(p[0]), 6), round(float(p[1]), 6)))
        return polished

    # ------------------------------------------------------------- MODÜL 2
    def integrate(
        self, ic: list[float], t_max: float, dt: float, method: str = "DOP853", t0: float = 0.0
    ) -> dict[str, Any]:
        ic_arr = np.asarray(ic, dtype=float)
        if ic_arr.shape != (self.dim,):
            raise ChaosError(f"{self.dim} adet başlangıç koşulu gerekli.")
        n_pts = int(round((t_max - t0) / dt)) + 1
        if n_pts < 10:
            raise ChaosError("t_max / Δt çok küçük: en az 10 zaman adımı gerekli.")
        if n_pts > MAX_SIM_POINTS:
            raise ChaosError(f"Çok fazla nokta ({n_pts}). Δt'yi büyütün veya t_max'ı küçültün (≤ {MAX_SIM_POINTS}).")
        t_eval = np.linspace(t0, t_max, n_pts)

        def bound_event(t: float, s: np.ndarray) -> float:
            return 1e8 - float(np.max(np.abs(s)))

        bound_event.terminal = True  # type: ignore[attr-defined]
        with np.errstate(all="ignore"):
            sol = solve_ivp(
                self.rhs, (t0, t_max), ic_arr, method=method, t_eval=t_eval,
                rtol=1e-9, atol=1e-11, events=bound_event,
            )
        diverged = sol.status == 1 or (sol.status == -1)
        warn = None
        if sol.status == 1:
            warn = f"Yörünge t ≈ {sol.t[-1]:.3g} anında |x| > 1e8 oldu (ıraksak)."
        elif sol.status == -1:
            warn = f"Entegrasyon başarısız: {sol.message}"
        return {"t": sol.t, "y": sol.y.T, "diverged": bool(diverged), "warning": warn}

    # ------------------------------------------------------------- MODÜL 3
    def butterfly(self, ic: list[float], t_max: float, dt: float, delta0: float, base: dict[str, Any]) -> dict[str, Any]:
        ic2 = np.asarray(ic, dtype=float).copy()
        ic2[0] += delta0
        pert = self.integrate(list(ic2), t_max, dt)
        n = min(len(base["t"]), len(pert["t"]))
        t = base["t"][:n]
        y1, y2 = base["y"][:n], pert["y"][:n]
        dist = np.linalg.norm(y1 - y2, axis=1)
        with np.errstate(divide="ignore"):
            ln_d = np.log(np.where(dist > 0, dist, np.nan))

        # Doğrusal büyüme bölgesinden λ_max tahmini (doyma öncesi)
        lam_est = None
        sat = np.nanmax(ln_d) if np.any(np.isfinite(ln_d)) else None
        if sat is not None:
            thr = math.log(max(abs(delta0), 1e-300)) + 0.6 * (sat - math.log(max(abs(delta0), 1e-300)))
            cross = np.where(np.isfinite(ln_d) & (ln_d >= thr))[0]
            end = int(cross[0]) if cross.size else n - 1
            seg = np.isfinite(ln_d[:end])
            if end > 20 and np.sum(seg) > 10:
                lam_est = float(np.polyfit(t[:end][seg], ln_d[:end][seg], 1)[0])
        horizon_idx = np.where(dist > 1.0)[0]
        horizon = float(t[horizon_idx[0]]) if horizon_idx.size else None

        idx = downsample_idx(n)
        return {
            "t": clean(t[idx]),
            "base": [clean(y1[idx, i]) for i in range(self.dim)],
            "perturbed": [clean(y2[idx, i]) for i in range(self.dim)],
            "distance": clean(dist[idx]),
            "ln_distance": clean(ln_d[idx]),
            "delta0": delta0,
            "lambda_estimate": fnum(lam_est) if lam_est is not None else None,
            "predictability_horizon": fnum(horizon) if horizon is not None else None,
        }

    # ------------------------------------------------------------- MODÜL 4
    def lyapunov_spectrum(
        self, ic: list[float], t_total: float, dt: float, transient: float = 0.0, renorm_time: float = 0.1
    ) -> dict[str, Any]:
        """Varyasyonel denklemler Φ' = J(x)Φ, sabit adımlı RK4 + periyodik QR yeniden ortonormalizasyon."""
        n = self.dim
        if dt <= 0 or t_total <= 0:
            raise ChaosError("Lyapunov için T ve Δt pozitif olmalı.")
        steps = int(round(t_total / dt))
        if steps > 400_000:
            raise ChaosError("Lyapunov adım sayısı çok büyük (> 400000). Δt'yi büyütün veya T'yi küçültün.")
        x = np.asarray(ic, dtype=float)
        t = 0.0
        if transient > 0:
            tr = self.integrate(list(x), transient, min(dt * 10, transient / 10))
            if tr["diverged"]:
                return self._lyap_diverged()
            x = tr["y"][-1]
            t = transient
        y = np.concatenate([x, np.eye(n).ravel()])
        renorm = max(1, int(round(renorm_time / dt)))
        sums = np.zeros(n)
        t_start = t
        hist_t: list[float] = []
        hist_l: list[np.ndarray] = []
        h = dt
        f = self.aug_rhs
        diverged = False
        with np.errstate(all="ignore"):
            for i in range(1, steps + 1):
                k1 = f(t, y)
                k2 = f(t + 0.5 * h, y + 0.5 * h * k1)
                k3 = f(t + 0.5 * h, y + 0.5 * h * k2)
                k4 = f(t + h, y + h * k3)
                y = y + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                t += h
                if i % renorm == 0 or i == steps:
                    if not np.all(np.isfinite(y)) or np.max(np.abs(y[:n])) > 1e8:
                        diverged = True
                        break
                    Q, R = np.linalg.qr(y[n:].reshape(n, n))
                    d = np.diag(R)
                    sums += np.log(np.abs(d))
                    Q = Q * np.sign(np.where(d == 0, 1.0, d))
                    y[n:] = Q.ravel()
                    hist_t.append(t)
                    hist_l.append(sums / (t - t_start))
        if diverged or not hist_l:
            return self._lyap_diverged()

        lyap = hist_l[-1]
        H = np.array(hist_l)
        # Sıfır toleransı: sabit taban + son %25 bölümdeki yakınsama dalgalanması
        tail = H[int(len(H) * 0.75):]
        fluct = float(np.max(np.std(tail, axis=0))) if len(tail) > 2 else 0.0
        tol = max(0.002, 1.0 / t_total, 3.0 * fluct)
        lam_sorted = sorted(lyap.tolist(), reverse=True)
        dky = kaplan_yorke(lam_sorted)
        cls = diagnose(lam_sorted, tol)

        idx = downsample_idx(len(hist_t), 1500)
        return {
            "exponents": [fnum(v, 6) for v in lam_sorted],
            "sum": fnum(float(np.sum(lyap)), 6),
            "kaplan_yorke": fnum(dky, 6),
            "classification": cls,
            "zero_tolerance": fnum(tol, 3),
            "time": clean(np.array(hist_t)[idx]),
            "history": [clean(H[idx, i]) for i in range(n)],
            "diverged": False,
            "t_total": t_total,
            "dt": dt,
        }

    def _lyap_diverged(self) -> dict[str, Any]:
        return {
            "exponents": [None] * self.dim,
            "sum": None,
            "kaplan_yorke": None,
            "classification": diagnose([0.0] * self.dim, 0.01, diverged=True),
            "zero_tolerance": None,
            "time": [],
            "history": [[] for _ in range(self.dim)],
            "diverged": True,
        }

    # ------------------------------------------------------------- MODÜL 5
    def bifurcation(
        self,
        param: str,
        p_min: float,
        p_max: float,
        steps: int,
        var: str,
        ic: list[float],
        t_transient: float,
        t_total: float,
        dt: float,
        max_per_param: int = 600,
    ) -> dict[str, Any]:
        """Tüm parametre değerleri tek bir vektörize RK4 entegrasyonunda (N × M durum matrisi) çözülür."""
        if param not in self.params:
            raise ChaosError(f"'{param}' parametresi sistemde tanımlı değil.")
        if var not in self.var_names:
            raise ChaosError(f"'{var}' durum değişkeni sistemde yok.")
        if not (2 <= steps <= 2000):
            raise ChaosError("Adım sayısı 2 ile 2000 arasında olmalı.")
        if t_total <= t_transient:
            raise ChaosError("Toplam süre geçici rejim süresinden büyük olmalı.")
        if p_max <= p_min:
            raise ChaosError("Parametre aralığı geçersiz (max > min olmalı).")
        n_steps = int(round(t_total / dt))
        n_tr = int(round(t_transient / dt))
        n_rec = n_steps - n_tr
        if n_rec < 10:
            raise ChaosError("Kayıt penceresi çok kısa: toplam t, geçici rejimden en az 10·Δt büyük olmalı.")
        work = n_steps * steps
        if work > MAX_BIF_WORK:
            raise ChaosError(
                f"Tarama çok büyük: (toplam t / Δt) × adım = {n_steps:,} × {steps} = {work:,} "
                f"> {MAX_BIF_WORK:,}. Adım sayısını veya toplam t'yi azaltın ya da Δt'yi büyütün."
            )

        p_names = list(self.params.keys())
        p_syms = [self.param_syms[k] for k in p_names]
        f = sp.lambdify((T_SYM, *self.vars, *p_syms), self.exprs, modules="numpy", cse=True)

        M = steps
        p_vals = np.linspace(p_min, p_max, M)
        pargs = [p_vals if k == param else float(self.params[k]) for k in p_names]
        X = np.tile(np.asarray(ic, dtype=float)[:, None], (1, M))
        vi = self.var_names.index(var)
        shape = (M,)
        K = max_per_param

        # Parça parça (chunk) kayıt: bellek kullanımı t_total'dan bağımsız.
        # Tampon CH+2 satır; argrelextrema iç satırlar (1..CH) için çalışır,
        # son 2 satır bir sonraki tamponun başına taşınır (boşluk / tekrar yok).
        CH = int(max(1000, min(20000, 8_000_000 // M)))
        buf = np.empty((CH + 2, M))
        k = 0
        pk_cols = np.empty(0, dtype=np.int64)
        pk_vals = np.empty(0)
        vmin = np.full(M, np.inf)
        vmax = np.full(M, -np.inf)
        diverged = np.zeros(M, dtype=bool)
        last = np.full(M, np.nan)

        def keep_last(cols: np.ndarray, vals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            """Her sütun için zaman sırasındaki son K tepe değerini tutar."""
            if cols.size == 0:
                return cols, vals
            rc, rv = cols[::-1], vals[::-1]
            order = np.argsort(rc, kind="stable")
            sc = rc[order]
            starts = np.searchsorted(sc, sc, side="left")
            rank = np.arange(sc.size) - starts
            keep = np.zeros(sc.size, dtype=bool)
            keep[order] = rank < K
            return rc[keep][::-1], rv[keep][::-1]

        def process(block: np.ndarray) -> None:
            nonlocal pk_cols, pk_vals
            if block.shape[0] < 3:
                return
            fin = np.isfinite(block)
            diverged[:] |= ~np.all(fin, axis=0)
            bc = np.where(fin, block, 0.0)
            vmin[:] = np.minimum(vmin, bc.min(axis=0))
            vmax[:] = np.maximum(vmax, bc.max(axis=0))
            rows, cols = argrelextrema(bc, np.greater, axis=0, order=1)
            if rows.size == 0:
                return
            y0 = bc[rows - 1, cols]
            y1 = bc[rows, cols]
            y2 = bc[rows + 1, cols]
            denom = y0 - 2.0 * y1 + y2
            peak = np.where(np.abs(denom) > 1e-14, y1 - (y2 - y0) ** 2 / (8.0 * denom), y1)
            order = np.argsort(rows, kind="stable")  # zaman sırası
            pk_cols = np.concatenate([pk_cols, cols[order].astype(np.int64)])
            pk_vals = np.concatenate([pk_vals, peak[order]])
            pk_cols, pk_vals = keep_last(pk_cols, pk_vals)

        h = dt
        t = 0.0
        with np.errstate(all="ignore"):
            for i in range(n_steps):
                k1 = F_vec(f, t, X, pargs, shape)
                k2 = F_vec(f, t + 0.5 * h, X + 0.5 * h * k1, pargs, shape)
                k3 = F_vec(f, t + 0.5 * h, X + 0.5 * h * k2, pargs, shape)
                k4 = F_vec(f, t + h, X + h * k3, pargs, shape)
                X = X + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                t += h
                if i % 50 == 0:
                    bad = ~np.all(np.isfinite(X), axis=0) | (np.max(np.abs(X), axis=0) > 1e8)
                    if np.any(bad):
                        X[:, bad] = np.nan
                if i >= n_tr:
                    buf[k] = X[vi]
                    k += 1
                    if k == CH + 2:
                        process(buf)
                        buf[0:2] = buf[CH:CH + 2]
                        k = 2
            process(buf[:k])
            last[:] = buf[k - 1] if k > 0 else np.nan

        px: list[np.ndarray] = []
        py: list[np.ndarray] = []
        n_per = np.zeros(M, dtype=int)
        order = np.argsort(pk_cols, kind="stable")
        cols_s, peak_s = pk_cols[order], pk_vals[order]
        bounds = np.searchsorted(cols_s, np.arange(M + 1))
        for c in range(M):
            if diverged[c]:
                continue
            pk = peak_s[bounds[c]:bounds[c + 1]]
            amp = float(vmax[c] - vmin[c])
            if pk.size == 0 or amp < 1e-6 * max(1.0, abs(float(last[c]))):
                pk = np.array([last[c]])  # sabit nokta dalı
            n_per[c] = pk.size
            px.append(np.full(pk.size, p_vals[c]))
            py.append(pk)
        px_a = np.concatenate(px) if px else np.array([])
        py_a = np.concatenate(py) if py else np.array([])
        return {
            "param": param,
            "var": var,
            "p": clean(px_a),
            "maxima": clean(py_a),
            "p_values": clean(p_vals),
            "n_maxima": n_per.tolist(),
            "diverged": [fnum(v) for v in p_vals[diverged]],
            "n_points": int(px_a.size),
            "max_per_param": K,
        }


    # ------------------------------------------------------------- MODÜL 6: Poincaré kesiti
    def poincare(
        self,
        ic: list[float],
        plane_var: str,
        plane_value: float,
        direction: int,
        t_transient: float,
        t_max: float,
        max_points: int = 20000,
    ) -> dict[str, Any]:
        """Σ = {x_k = c} hiper-düzlemi; solve_ivp olay (event) kök bulma ile kesişimler."""
        if self.dim < 2:
            raise ChaosError("Poincaré kesiti için en az 2 boyutlu sistem gerekli.")
        if plane_var not in self.var_names:
            raise ChaosError(f"'{plane_var}' durum değişkeni sistemde yok.")
        if t_max <= t_transient:
            raise ChaosError("Toplam süre geçici rejim süresinden büyük olmalı.")
        if t_max - t_transient > 1_000_000:
            raise ChaosError("Kesit süresi çok uzun (≤ 1e6).")
        k = self.var_names.index(plane_var)
        x0 = np.asarray(ic, dtype=float)
        with np.errstate(all="ignore"):
            if t_transient > 0:
                tr = solve_ivp(self.rhs, (0.0, t_transient), x0, method="DOP853", rtol=1e-8, atol=1e-10)
                if not np.all(np.isfinite(tr.y[:, -1])) or np.max(np.abs(tr.y[:, -1])) > 1e8:
                    raise ChaosError("Geçici rejimde yörünge ıraksadı.")
                x0 = tr.y[:, -1]

            def sec(t: float, s: np.ndarray) -> float:
                return float(s[k] - plane_value)

            sec.direction = float(np.sign(direction)) if direction else 0.0  # type: ignore[attr-defined]

            def bound(t: float, s: np.ndarray) -> float:
                return 1e8 - float(np.max(np.abs(s)))

            bound.terminal = True  # type: ignore[attr-defined]
            sol = solve_ivp(
                self.rhs, (t_transient, t_max), x0, method="DOP853",
                rtol=1e-9, atol=1e-11, events=[sec, bound], dense_output=False,
            )
        pts = sol.y_events[0] if sol.y_events and len(sol.y_events[0]) else np.empty((0, self.dim))
        tev = sol.t_events[0] if sol.t_events and len(sol.t_events[0]) else np.empty(0)
        pts = pts[:max_points]
        tev = tev[:max_points]
        others = [v for v in self.var_names if v != plane_var]
        ret_times = np.diff(tev) if len(tev) > 1 else np.empty(0)
        return {
            "plane_var": plane_var,
            "plane_value": plane_value,
            "direction": int(np.sign(direction)) if direction else 0,
            "n_points": int(len(pts)),
            "points": {v: clean(pts[:, self.var_names.index(v)]) for v in self.var_names},
            "t": clean(tev),
            "others": others,
            "mean_return_time": fnum(float(np.mean(ret_times))) if ret_times.size else None,
            "diverged": bool(sol.status == 1),
        }

    # ------------------------------------------------------------- MODÜL 7: Çekim havzası
    def basin(
        self,
        ic: list[float],
        var_a: str,
        var_b: str,
        a_range: tuple[float, float],
        b_range: tuple[float, float],
        res: int,
        t_total: float,
        dt: float,
        window_frac: float = 0.2,
    ) -> dict[str, Any]:
        """Başlangıç koşulu ızgarası; vektörize RK4; son pencere ortalamasıyla çekici kümeleme."""
        from analysis_tools import cluster_attractors

        for v in (var_a, var_b):
            if v not in self.var_names:
                raise ChaosError(f"'{v}' durum değişkeni sistemde yok.")
        if self.dim >= 2 and var_a == var_b:
            raise ChaosError("Havza için iki farklı değişken seçin.")
        if not (10 <= res <= 400):
            raise ChaosError("Çözünürlük 10 ile 400 arasında olmalı.")
        if a_range[1] <= a_range[0] or (self.dim >= 2 and b_range[1] <= b_range[0]):
            raise ChaosError("Havza aralığı geçersiz (max > min olmalı).")
        n_steps = int(round(t_total / dt))
        if n_steps < 20:
            raise ChaosError("t / Δt çok küçük.")
        rows = res if self.dim >= 2 else 1
        M = res * rows
        if n_steps * M > MAX_BIF_WORK:
            raise ChaosError(
                f"Havza hesabı çok büyük: {n_steps:,} adım × {M:,} nokta > {MAX_BIF_WORK:,}. "
                "Çözünürlüğü / süreyi azaltın veya Δt'yi büyütün."
            )
        f = sp.lambdify((T_SYM, *self.vars), self.exprs_num, modules="numpy", cse=True)
        av = np.linspace(a_range[0], a_range[1], res)
        bv = np.linspace(b_range[0], b_range[1], rows) if self.dim >= 2 else np.array([0.0])
        A, B = np.meshgrid(av, bv)  # satır: b, sütun: a
        X = np.tile(np.asarray(ic, dtype=float)[:, None], (1, M))
        ia, ib = self.var_names.index(var_a), self.var_names.index(var_b)
        X[ia] = A.ravel()
        if self.dim >= 2:
            X[ib] = B.ravel()
        shape = (M,)
        n_win = max(5, int(n_steps * window_frac))
        s1 = np.zeros((self.dim, M))
        s2 = np.zeros((self.dim, M))
        h = dt
        t = 0.0
        with np.errstate(all="ignore"):
            for i in range(n_steps):
                k1 = F_vec(f, t, X, [], shape)
                k2 = F_vec(f, t + 0.5 * h, X + 0.5 * h * k1, [], shape)
                k3 = F_vec(f, t + 0.5 * h, X + 0.5 * h * k2, [], shape)
                k4 = F_vec(f, t + h, X + h * k3, [], shape)
                X = X + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                t += h
                if i % 25 == 0:
                    bad = ~np.all(np.isfinite(X), axis=0) | (np.max(np.abs(X), axis=0) > 1e6)
                    if np.any(bad):
                        X[:, bad] = np.nan
                if i >= n_steps - n_win:
                    s1 += X
                    s2 += X * X
        diverged = ~np.all(np.isfinite(X), axis=0) | (np.max(np.abs(np.nan_to_num(X, nan=1e9)), axis=0) > 1e6)
        mean = (s1 / n_win).T
        var = np.maximum((s2 / n_win).T - mean ** 2, 0.0)
        labels, info = cluster_attractors(mean, np.sqrt(var), diverged)
        return {
            "var_a": var_a, "var_b": var_b if self.dim >= 2 else None,
            "a": clean(av), "b": clean(bv),
            "labels": labels.reshape(rows, res).tolist(),
            "attractors": info,
            "diverged_fraction": fnum(float(np.mean(diverged)), 4),
            "res": res,
            "t_total": t_total, "dt": dt,
        }


def F_vec(f: Callable[..., Any], t: float, S: np.ndarray, pargs: list[Any], shape: tuple[int]) -> np.ndarray:
    """Vektörize sağ taraf: S (N × M) durum matrisi, her sütun bir parametre değeri."""
    out = f(t, *S, *pargs)
    return np.stack([np.broadcast_to(np.asarray(o, dtype=float), shape) for o in out])


# ---------------------------------------------------------------------------
# Hazır sistemler
# ---------------------------------------------------------------------------
PRESETS: dict[str, dict[str, Any]] = {
    "lorenz": {
        "name": "Lorenz Sistemi (3B)",
        "equations": ["sigma*(y - x)", "x*(rho - z) - y", "x*y - beta*z"],
        "params": "sigma=10, rho=28, beta=8/3",
        "initial": [1.0, 1.0, 1.0],
        "t_max": 100.0, "dt": 0.01, "delta0": 1e-5,
        "lyap_t": 300.0, "lyap_dt": 0.01, "lyap_transient": 20.0,
        "bif": {"param": "rho", "min": 10.0, "max": 40.0, "steps": 200, "var": "z",
                "t_transient": 60.0, "t_total": 160.0, "dt": 0.01},
        "axes": ["x", "y", "z"],
    },
    "rossler": {
        "name": "Rössler Sistemi (3B)",
        "equations": ["-y - z", "x + a*y", "b + z*(x - c)"],
        "params": "a=0.2, b=0.2, c=5.7",
        "initial": [1.0, 1.0, 0.0],
        "t_max": 300.0, "dt": 0.02, "delta0": 1e-5,
        "lyap_t": 1000.0, "lyap_dt": 0.02, "lyap_transient": 50.0,
        "bif": {"param": "c", "min": 2.0, "max": 18.0, "steps": 200, "var": "x",
                "t_transient": 200.0, "t_total": 500.0, "dt": 0.02},
        "axes": ["x", "y", "z"],
    },
    "chen": {
        "name": "Chen Sistemi (3B)",
        "equations": ["a*(y - x)", "(c - a)*x - x*z + c*y", "x*y - b*z"],
        "params": "a=35, b=3, c=28",
        "initial": [-10.0, 0.0, 37.0],
        "t_max": 60.0, "dt": 0.005, "delta0": 1e-5,
        "lyap_t": 200.0, "lyap_dt": 0.002, "lyap_transient": 10.0,
        "bif": {"param": "c", "min": 18.0, "max": 30.0, "steps": 200, "var": "z",
                "t_transient": 40.0, "t_total": 100.0, "dt": 0.004},
        "axes": ["x", "y", "z"],
    },
    "dadras3": {
        "name": "Dadras-Momeni Sistemi (3B)",
        "equations": ["y - a*x + b*y*z", "c*y - x*z + z", "d*x*y - e*z"],
        "params": "a=3, b=2.7, c=1.7, d=2, e=9",
        "initial": [1.1, 2.1, -2.0],
        "t_max": 200.0, "dt": 0.01, "delta0": 1e-5,
        "lyap_t": 600.0, "lyap_dt": 0.01, "lyap_transient": 30.0,
        "bif": {"param": "c", "min": 0.5, "max": 2.5, "steps": 200, "var": "x",
                "t_transient": 100.0, "t_total": 300.0, "dt": 0.01},
        "axes": ["x", "y", "z"],
    },
    "dadras4": {
        "name": "Dadras-Momeni Sistemi (4B Hiperkaotik)",
        "equations": ["a*x - y*z + w", "x*z - b*y", "x*y - c*z + x*w", "-y"],
        "params": "a=8, b=40, c=14.9",
        "initial": [10.0, 1.0, 10.0, 1.0],
        "t_max": 50.0, "dt": 0.002, "delta0": 1e-5,
        "lyap_t": 200.0, "lyap_dt": 0.002, "lyap_transient": 10.0,
        "bif": {"param": "a", "min": 4.0, "max": 10.0, "steps": 150, "var": "x",
                "t_transient": 20.0, "t_total": 50.0, "dt": 0.002},
        "axes": ["x", "y", "w"],
    },
    "thomas": {
        "name": "Thomas Döngüsel Simetrik Çekicisi (3B)",
        "equations": ["sin(y) - b*x", "sin(z) - b*y", "sin(x) - b*z"],
        "params": "b=0.208186",
        "initial": [0.1, 0.0, 0.0],
        "t_max": 1000.0, "dt": 0.05, "delta0": 1e-5,
        "lyap_t": 3000.0, "lyap_dt": 0.05, "lyap_transient": 100.0,
        "bif": {"param": "b", "min": 0.15, "max": 0.33, "steps": 180, "var": "x",
                "t_transient": 500.0, "t_total": 1500.0, "dt": 0.1},
        "axes": ["x", "y", "z"],
    },
    "lu": {
        "name": "Lü Sistemi (3B)",
        "equations": ["a*(y - x)", "-x*z + c*y", "x*y - b*z"],
        "params": "a=36, b=3, c=20",
        "initial": [1.0, 1.0, 1.0],
        "t_max": 60.0, "dt": 0.005, "delta0": 1e-5,
        "lyap_t": 200.0, "lyap_dt": 0.005, "lyap_transient": 10.0,
        "bif": {"param": "c", "min": 12.0, "max": 28.0, "steps": 200, "var": "z",
                "t_transient": 40.0, "t_total": 100.0, "dt": 0.005},
        "axes": ["x", "y", "z"],
    },
    "chua": {
        "name": "Chua Devresi (3B, parçalı doğrusal)",
        "equations": [
            "alpha*(y - x - (m1*x + (m0 - m1)/2*(abs(x + 1) - abs(x - 1))))",
            "x - y + z",
            "-beta*y",
        ],
        "params": "alpha=15.6, beta=28, m0=-8/7, m1=-5/7",
        "initial": [0.7, 0.0, 0.0],
        "t_max": 200.0, "dt": 0.01, "delta0": 1e-5,
        "lyap_t": 500.0, "lyap_dt": 0.005, "lyap_transient": 50.0,
        "bif": {"param": "alpha", "min": 8.0, "max": 16.0, "steps": 200, "var": "x",
                "t_transient": 100.0, "t_total": 250.0, "dt": 0.01},
        "axes": ["x", "y", "z"],
    },
    "halvorsen": {
        "name": "Halvorsen Döngüsel Çekicisi (3B)",
        "equations": ["-a*x - 4*y - 4*z - y^2", "-a*y - 4*z - 4*x - z^2", "-a*z - 4*x - 4*y - x^2"],
        "params": "a=1.4",
        "initial": [-1.48, -1.51, 2.04],
        "t_max": 150.0, "dt": 0.005, "delta0": 1e-5,
        "lyap_t": 300.0, "lyap_dt": 0.005, "lyap_transient": 20.0,
        "bif": {"param": "a", "min": 1.3, "max": 2.4, "steps": 150, "var": "x",
                "t_transient": 60.0, "t_total": 150.0, "dt": 0.005},
        "axes": ["x", "y", "z"],
    },
    "aizawa": {
        "name": "Aizawa Çekicisi (3B)",
        "equations": [
            "(z - b)*x - d*y",
            "d*x + (z - b)*y",
            "c + a*z - z^3/3 - (x^2 + y^2)*(1 + e*z) + f*z*x^3",
        ],
        "params": "a=0.95, b=0.7, c=0.6, d=3.5, e=0.25, f=0.1",
        "initial": [0.1, 0.0, 0.0],
        "t_max": 200.0, "dt": 0.01, "delta0": 1e-5,
        "lyap_t": 500.0, "lyap_dt": 0.01, "lyap_transient": 50.0,
        "bif": {"param": "a", "min": 0.6, "max": 1.0, "steps": 150, "var": "z",
                "t_transient": 100.0, "t_total": 250.0, "dt": 0.01},
        "axes": ["x", "y", "z"],
    },
    "rossler4": {
        "name": "Hiperkaotik Rössler (4B)",
        "equations": ["-y - z", "x + a*y + w", "b + x*z", "-c*z + d*w"],
        "params": "a=0.25, b=3, c=0.5, d=0.05",
        "initial": [-10.0, -6.0, 0.0, 10.0],
        "t_max": 300.0, "dt": 0.01, "delta0": 1e-5,
        "lyap_t": 1000.0, "lyap_dt": 0.01, "lyap_transient": 50.0,
        "bif": {"param": "d", "min": 0.0, "max": 0.06, "steps": 120, "var": "x",
                "t_transient": 150.0, "t_total": 350.0, "dt": 0.01},
        "axes": ["x", "y", "w"],
    },
}

PRESETS["hyper5"] = {
    "name": "Hiperkaotik Lorenz Türevi (5B)",
    "equations": ["a*(x2 - x1) + x4", "c*x1 - x2 - x1*x3 + x5", "x1*x2 - b*x3", "-x2*x3 + r*x4", "-k*x2"],
    "params": "a=10, b=8/3, c=28, r=-1, k=3",
    "initial": [1.0, 1.0, 1.0, 1.0, 1.0],
    "t_max": 60.0, "dt": 0.005, "delta0": 1e-5,
    "lyap_t": 200.0, "lyap_dt": 0.005, "lyap_transient": 10.0,
    "bif": {"param": "k", "min": 1.0, "max": 6.0, "steps": 120, "var": "x1",
            "t_transient": 30.0, "t_total": 80.0, "dt": 0.005},
    "axes": ["x1", "x2", "x3"],
}
PRESETS["rossler6"] = {
    "name": "Bağlaşık Rössler Çifti (6B)",
    "equations": ["-x2 - x3 + eps*(x4 - x1)", "x1 + a*x2", "b + x3*(x1 - c)",
                  "-x5 - x6 + eps*(x1 - x4)", "x4 + a*x5", "b + x6*(x4 - c)"],
    "params": "a=0.2, b=0.2, c=5.7, eps=0.05",
    "initial": [1.0, 1.0, 0.0, 2.0, 0.0, 0.0],
    "t_max": 300.0, "dt": 0.02, "delta0": 1e-5,
    "lyap_t": 1000.0, "lyap_dt": 0.02, "lyap_transient": 50.0,
    "bif": {"param": "eps", "min": 0.0, "max": 0.3, "steps": 100, "var": "x1",
            "t_transient": 150.0, "t_total": 350.0, "dt": 0.02},
    "axes": ["x1", "x2", "x4"],
}

# Poincaré kesiti ve çekim havzası varsayılanları
PRESET_EXTRAS: dict[str, dict[str, Any]] = {
    "lorenz": {"poincare": {"var": "z", "value": 27.0, "dir": 1, "t_transient": 20.0, "t_max": 1000.0},
               "basin": {"a": "x", "b": "y", "a_range": [-20, 20], "b_range": [-20, 20], "res": 120,
                         "t": 40.0, "dt": 0.01, "override": "rho=20"}},
    "rossler": {"poincare": {"var": "x", "value": 0.0, "dir": -1, "t_transient": 100.0, "t_max": 3000.0},
                "basin": {"a": "x", "b": "y", "a_range": [-15, 15], "b_range": [-15, 15], "res": 80,
                          "t": 60.0, "dt": 0.02, "override": ""}},
    "chen": {"poincare": {"var": "z", "value": 20.0, "dir": 1, "t_transient": 10.0, "t_max": 300.0},
             "basin": {"a": "x", "b": "y", "a_range": [-30, 30], "b_range": [-30, 30], "res": 70,
                       "t": 15.0, "dt": 0.004, "override": ""}},
    "dadras3": {"poincare": {"var": "z", "value": 0.0, "dir": 1, "t_transient": 30.0, "t_max": 1500.0},
                "basin": {"a": "x", "b": "y", "a_range": [-10, 10], "b_range": [-10, 10], "res": 80,
                          "t": 40.0, "dt": 0.01, "override": ""}},
    "dadras4": {"poincare": {"var": "z", "value": 0.0, "dir": 1, "t_transient": 10.0, "t_max": 400.0},
                "basin": {"a": "x", "b": "y", "a_range": [-30, 30], "b_range": [-30, 30], "res": 60,
                          "t": 10.0, "dt": 0.002, "override": ""}},
    "thomas": {"poincare": {"var": "z", "value": 0.0, "dir": 1, "t_transient": 200.0, "t_max": 8000.0},
               "basin": {"a": "x", "b": "y", "a_range": [-6, 6], "b_range": [-6, 6], "res": 80,
                         "t": 300.0, "dt": 0.1, "override": "b=0.32"}},
    "lu": {"poincare": {"var": "z", "value": 20.0, "dir": 1, "t_transient": 10.0, "t_max": 300.0},
           "basin": {"a": "x", "b": "y", "a_range": [-25, 25], "b_range": [-25, 25], "res": 70,
                     "t": 15.0, "dt": 0.005, "override": "c=12"}},
    "chua": {"poincare": {"var": "y", "value": 0.0, "dir": 1, "t_transient": 50.0, "t_max": 3000.0},
             "basin": {"a": "x", "b": "z", "a_range": [-3, 3], "b_range": [-4, 4], "res": 80,
                       "t": 80.0, "dt": 0.01, "override": ""}},
    "halvorsen": {"poincare": {"var": "z", "value": 0.0, "dir": 1, "t_transient": 20.0, "t_max": 1500.0},
                  "basin": {"a": "x", "b": "y", "a_range": [-10, 10], "b_range": [-10, 10], "res": 70,
                            "t": 30.0, "dt": 0.005, "override": ""}},
    "aizawa": {"poincare": {"var": "x", "value": 0.0, "dir": 1, "t_transient": 50.0, "t_max": 2000.0},
               "basin": {"a": "x", "b": "z", "a_range": [-1.5, 1.5], "b_range": [-1.5, 2], "res": 70,
                         "t": 60.0, "dt": 0.01, "override": ""}},
    "hyper5": {"poincare": {"var": "x3", "value": 25.0, "dir": 1, "t_transient": 10.0, "t_max": 300.0},
               "basin": {"a": "x1", "b": "x2", "a_range": [-20, 20], "b_range": [-20, 20], "res": 60,
                         "t": 15.0, "dt": 0.005, "override": ""}},
    "rossler6": {"poincare": {"var": "x1", "value": 0.0, "dir": -1, "t_transient": 100.0, "t_max": 3000.0},
                 "basin": {"a": "x1", "b": "x4", "a_range": [-12, 12], "b_range": [-12, 12], "res": 60,
                           "t": 60.0, "dt": 0.02, "override": ""}},
    "rossler4": {"poincare": {"var": "x", "value": 0.0, "dir": -1, "t_transient": 100.0, "t_max": 3000.0},
                 "basin": {"a": "x", "b": "y", "a_range": [-20, 20], "b_range": [-20, 20], "res": 60,
                           "t": 60.0, "dt": 0.01, "override": ""}},
}
for _k, _v in PRESET_EXTRAS.items():
    PRESETS[_k].update(_v)


# ---------------------------------------------------------------------------
# Üst düzey API fonksiyonları
# ---------------------------------------------------------------------------
def full_analysis(
    equations: list[str],
    params: str,
    initial: list[float],
    t_max: float,
    dt: float,
    delta0: float,
    lyap_t: float,
    lyap_dt: float,
    lyap_transient: float,
    compute_lyapunov: bool = True,
    method: str = "DOP853",
) -> dict[str, Any]:
    system = ChaosSystem(equations, params)
    if len(initial) < system.dim:
        raise ChaosError(f"{system.dim} adet başlangıç koşulu gerekli.")
    ic = [float(v) for v in initial[: system.dim]]
    if dt <= 0 or t_max <= 0:
        raise ChaosError("t_max ve Δt pozitif olmalı.")

    base = system.integrate(ic, t_max, dt, method=method)
    traj = base["y"]
    finite = traj[np.all(np.isfinite(traj), axis=1)]
    sym = system.symbolic_analysis(finite[len(finite) // 5:] if len(finite) > 50 else finite)

    idx = downsample_idx(len(base["t"]))
    trajectory = {
        "t": clean(base["t"][idx]),
        "states": [clean(traj[idx, i]) for i in range(system.dim)],
        "diverged": base["diverged"],
        "warning": base["warning"],
        "n_points": int(len(base["t"])),
    }
    bfly = system.butterfly(ic, t_max, dt, delta0, base)
    lyap = (
        system.lyapunov_spectrum(ic, lyap_t, lyap_dt, lyap_transient)
        if compute_lyapunov
        else None
    )
    if lyap is not None and base["diverged"] and not lyap["diverged"]:
        lyap["classification"] = diagnose([0.0] * system.dim, 0.01, diverged=True)

    if lyap is not None and lyap.get("sum") is not None:
        mean_div = sym["divergence"].get("value")
        lyap["divergence_check"] = mean_div

    from analysis_tools import fractal_analysis, power_spectrum

    att = finite[len(finite) // 5:] if len(finite) > 50 else finite
    spectrum = power_spectrum(finite, dt, system.var_names, discard_frac=0.2)
    fractal = fractal_analysis(att) if not base["diverged"] else {
        "correlation": {"available": False, "reason": "diverged"},
        "box": {"available": False, "reason": "diverged"},
    }
    if lyap is not None:
        fractal["kaplan_yorke"] = lyap.get("kaplan_yorke")
    # 3B gösterim için çekici noktaları (alt örneklenmiş)
    if len(att):
        ai = downsample_idx(len(att), 6000)
        fractal["points"] = [clean(att[ai, i]) for i in range(system.dim)]

    return {
        "symbolic": sym,
        "trajectory": trajectory,
        "butterfly": bfly,
        "lyapunov": lyap,
        "spectrum": spectrum,
        "fractal": fractal,
        "variables": system.var_names,
        "dimension": system.dim,
    }


def _merge_params(params: str, override: str) -> str:
    override = (override or "").strip()
    if not override:
        return params
    return f"{params}, {override}" if params.strip() else override


def poincare_analysis(
    equations: list[str], params: str, initial: list[float], plane_var: str, plane_value: float,
    direction: int, t_transient: float, t_max: float,
) -> dict[str, Any]:
    system = ChaosSystem(equations, params)
    ic = [float(v) for v in initial[: system.dim]]
    if len(ic) != system.dim:
        raise ChaosError(f"{system.dim} adet başlangıç koşulu gerekli.")
    return system.poincare(ic, plane_var, plane_value, direction, t_transient, t_max)


def basin_analysis(
    equations: list[str], params: str, initial: list[float], var_a: str, var_b: str,
    a_min: float, a_max: float, b_min: float, b_max: float, res: int, t_total: float, dt: float,
    override: str = "",
) -> dict[str, Any]:
    system = ChaosSystem(equations, _merge_params(params, override))
    ic = [float(v) for v in initial[: system.dim]]
    if len(ic) != system.dim:
        raise ChaosError(f"{system.dim} adet başlangıç koşulu gerekli.")
    out = system.basin(ic, var_a, var_b, (a_min, a_max), (b_min, b_max), res, t_total, dt)
    # Kararlı denge noktalarıyla eşleştirme
    eqs: list[dict[str, Any]] = []
    if system.autonomous:
        try:
            eqs, _ = system.equilibria(None)
        except Exception:  # noqa: BLE001
            eqs = []
    from analysis_tools import match_equilibria

    match_equilibria(out["attractors"], eqs)
    out["equilibria"] = [{"point": e["point"], "stable": e["stable"], "type": e["type"]} for e in eqs]
    out["params_used"] = {k: fnum(float(v), 8) for k, v in system.params.items()}
    return out


def compare_systems(keys: list[str], quick: bool = True) -> dict[str, Any]:
    """Seçilen hazır sistemler için özet metrikler: λ spektrumu, D_KY, D2, D0, spektral entropi."""
    from analysis_tools import correlation_dimension, box_counting_dimension, power_spectrum

    rows = []
    for key in keys:
        p = PRESETS.get(key)
        if p is None:
            continue
        row: dict[str, Any] = {"key": key, "name": p["name"], "dim": len(p["equations"])}
        try:
            system = ChaosSystem(p["equations"], p["params"])
            ic = list(map(float, p["initial"]))
            base = system.integrate(ic, p["t_max"], p["dt"])
            traj = base["y"]
            finite = traj[np.all(np.isfinite(traj), axis=1)]
            att = finite[len(finite) // 5:]
            lyT = min(p["lyap_t"], 1000.0) if quick else p["lyap_t"]
            lyap = system.lyapunov_spectrum(ic, lyT, p["lyap_dt"], p["lyap_transient"])
            spec = power_spectrum(finite, p["dt"], system.var_names)
            cd = correlation_dimension(att, n_max=1500)
            bd = box_counting_dimension(att)
            ents = [v["spectral_entropy"] for v in spec.get("vars", {}).values() if v.get("spectral_entropy") is not None]
            row.update({
                "exponents": lyap["exponents"],
                "lambda_max": lyap["exponents"][0],
                "sum": lyap["sum"],
                "kaplan_yorke": lyap["kaplan_yorke"],
                "classification": lyap["classification"],
                "D2": cd.get("D2"),
                "D0": bd.get("D0"),
                "spectral_entropy": fnum(float(np.mean(ents)), 4) if ents else None,
                "dominant_freq": spec.get("vars", {}).get(system.var_names[0], {}).get("dominant_freq"),
                "ok": True,
            })
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": False, "error": str(exc)})
        rows.append(row)
    return {"rows": rows}


def bifurcation_analysis(
    equations: list[str],
    params: str,
    initial: list[float],
    param: str,
    p_min: float,
    p_max: float,
    steps: int,
    var: str,
    t_transient: float,
    t_total: float,
    dt: float,
) -> dict[str, Any]:
    system = ChaosSystem(equations, params)
    ic = [float(v) for v in initial[: system.dim]]
    if len(ic) != system.dim:
        raise ChaosError(f"{system.dim} adet başlangıç koşulu gerekli.")
    return system.bifurcation(param, p_min, p_max, steps, var, ic, t_transient, t_total, dt)
