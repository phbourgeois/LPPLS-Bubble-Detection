"""Single canonical LPPLS fit for both snapshot and historical backtests.

Always use the legacy 7 x 7 x 7 grid (343 candidates). Cached design
matrices and pseudoinverses improve speed without reducing the search grid.
Only prices observed as of the requested date are passed to the fitter.
"""
from __future__ import annotations

from functools import lru_cache
import numpy as np

GRID_VERSION = "legacy_full_7x7x7_v1"
GRID_SIZE = 343


@lru_cache(maxsize=32)
def _designs(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return immutable (design, pseudoinverse, grid) for a window length."""
    if n < 5:
        raise ValueError("At least five weekly observations are required")
    t = np.arange(n, dtype=float)
    ahead_max = min(1.5 * n, max(6, n))
    candidates = []
    matrices = []
    for m in np.linspace(0.1, 0.9, 7):
        for omega in np.linspace(6.0, 13.0, 7):
            for ahead in np.linspace(1.0, ahead_max, 7):
                tc = (n - 1) + ahead
                tau = tc - t
                x1 = tau ** m
                angle = omega * np.log(tau)
                matrices.append(np.column_stack(
                    (np.ones(n), x1, x1*np.cos(angle), x1*np.sin(angle))
                ))
                candidates.append((m, omega, tc))
    design = np.stack(matrices)
    pseudo = np.linalg.pinv(design)
    grid = np.asarray(candidates, dtype=float)
    design.setflags(write=False)
    pseudo.setflags(write=False)
    grid.setflags(write=False)
    return design, pseudo, grid


def fit_lppls(log_prices: np.ndarray) -> dict:
    """Full-grid SSE minimization with the original snapshot phase convention.

    Explicit candidate residuals avoid subtractive cancellation in
    expressions based on y'y - beta'X'y.
    """
    y = np.asarray(log_prices, dtype=float)
    n = len(y)
    if n < 5 or y.ndim != 1 or not np.isfinite(y).all():
        return {"success": False, "n": n}
    design, pseudo, grid = _designs(n)
    beta = np.einsum("kpn,n->kp", pseudo, y, optimize=True)
    residuals = np.einsum("knp,kp->kn", design, beta, optimize=True) - y
    sses = np.einsum("kn,kn->k", residuals, residuals, optimize=True)
    j = int(np.argmin(sses))
    a, b, c1, c2 = beta[j]
    m, omega, tc = grid[j]
    sse = float(sses[j])
    sst = float(np.sum((y - y.mean())**2))
    return {
        "success": True, "A": float(a), "B": float(b),
        "C": float(np.hypot(c1, c2)), "m": float(m),
        "omega": float(omega), "phi": float(np.arctan2(c2, c1) % (2*np.pi)),
        "tc": float(tc), "r2": (1 - sse / sst) if sst > 0 else np.nan,
        "rmse": float(np.sqrt(sse / n)), "sse": sse, "n": n,
    }


def classify_lppls(fit: dict) -> tuple[bool, str]:
    """Common heuristic validity and UP/DOWN convention (not a statistical test)."""
    if not fit.get("success", False):
        return False, "NONE"
    n = fit["n"]
    valid = bool(
        0.1 <= fit["m"] <= 0.9
        and 6.0 <= fit["omega"] <= 13.0
        and n - 1 < fit["tc"] <= n - 1 + 1.5*n
        and np.isfinite(fit["r2"]) and fit["r2"] >= 0.2
    )
    if not valid:
        return False, "NONE"
    return True, "UP" if fit["B"] < 0 else "DOWN"
