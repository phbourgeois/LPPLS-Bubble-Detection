"""Causal, bootstrap-calibrated exploratory LPPLS oscillation test.

This is NOT a probability of a financial bubble. Refit the entire model/grid
under both circular-block and Gaussian random-walk nulls constructed solely
from pre-decision returns. The statistic measures improvement over an
optimized smooth power-law, with multiplicity handled separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from math import pi
from typing import Any

import numpy as np


@dataclass(frozen=True)
class StatisticalConfig:
    windows: tuple[int, ...] = (52, 104)
    bootstrap_draws: int = 199
    block_weeks: int = 4
    alpha: float = 0.10
    min_cycles: float = 1.5
    seed: int = 20261104

    def validate(self) -> None:
        if not self.windows or min(self.windows) < 26:
            raise ValueError('Fenêtres de calibration : minimum 26 semaines.')
        if self.bootstrap_draws < 19:
            raise ValueError('Au moins 19 répétitions bootstrap requises.')
        if not 1 <= self.block_weeks < min(self.windows):
            raise ValueError('Longueur de blocs incompatible avec les fenêtres.')
        if not 0 < self.alpha < 1:
            raise ValueError('alpha doit être dans (0,1).')


@lru_cache(maxsize=32)
def _designs(n: int):
    """Orthonormal projection bases for a precommitted fixed grid."""
    t = np.arange(n, dtype=float)
    full, smooth, params, inverses = [], [], [], []
    for m in (0.2, 0.5, 0.8):
        for ahead in (1., 0.25 * n, 0.75 * n):
            tau = n - 1 + ahead - t
            power = tau ** m
            base = np.column_stack((np.ones(n), power))
            qb, _ = np.linalg.qr(base, mode='reduced')
            smooth.append(qb)
            for omega in (7., 9.5, 12.):
                phase = omega * np.log(tau)
                x = np.column_stack((base, power*np.cos(phase), power*np.sin(phase)))
                q, _ = np.linalg.qr(x, mode='reduced')
                full.append(q)
                inverses.append(np.linalg.pinv(x))
                params.append((m, omega, ahead))
    return np.stack(full), np.stack(smooth), tuple(params), np.stack(inverses)


def _score_batch(paths: np.ndarray) -> dict[str, np.ndarray]:
    """Apply the *same full model selection* to observed and null series."""
    paths = np.asarray(paths, dtype=float)
    if paths.ndim != 2 or paths.shape[1] < 26 or not np.isfinite(paths).all():
        raise ValueError('Series must be complete finite log-price windows >= 26.')
    n = paths.shape[1]
    full, smooth, params, inverses = _designs(n)
    y = paths - paths[:, :1]
    energy = np.sum(y*y, axis=1)
    a = np.einsum('bn,cnf->bcf', y, full, optimize=True)
    b = np.einsum('bn,cnf->bcf', y, smooth, optimize=True)
    sse1 = np.maximum(0., energy[:, None] - np.sum(a*a, axis=2))
    sse0 = np.maximum(0., energy[:, None] - np.sum(b*b, axis=2))
    idx = np.argmin(sse1, axis=1)
    best1 = sse1[np.arange(len(y)), idx]
    best0 = sse0.min(axis=1)
    gain = np.clip((best0 - best1) / np.maximum(best0, 1e-12), 0, 1)
    beta = np.einsum('bfn,bn->bf', inverses[idx], y, optimize=True)
    omega = np.array([params[k][1] for k in idx])
    ahead = np.array([params[k][2] for k in idx])
    cycles = omega * np.log((n - 1 + ahead) / ahead) / (2*pi)
    return dict(gain=gain, B=beta[:,1], omega=omega, ahead=ahead,
                cycles=cycles, sse_full=best1, sse_smooth=best0)


def _bootstrap_returns(returns: np.ndarray, draws: int, block: int,
                       rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = len(returns)
    starts = rng.integers(0, n, size=(draws, (n+block-1)//block))
    index = ((starts[:, :, None]+np.arange(block)[None, None, :]) % n)
    indices = index.reshape(draws, -1)[:, :n]
    return (returns[indices],
            rng.normal(returns.mean(), returns.std(ddof=1), size=(draws,n)))


def calibrated_window(log_prices: np.ndarray, config: StatisticalConfig,
                      asof: str, asset: str) -> dict[str, Any]:
    """P-value of oscillatory improvement under two refitted null families."""
    config.validate()
    y = np.asarray(log_prices, dtype=float)
    if y.ndim != 1 or len(y) not in config.windows or not np.isfinite(y).all():
        raise ValueError('Fenêtre incomplète ou horizon non sélectionné.')
    if y.std() < 1e-9:
        return dict(asset=asset, asof=asof, window_weeks=len(y),
                    p_block=1., p_gaussian=1., p_joint=1., oscillation_gain=0.,
                    signal='NONE', cycles=0., B=0., eligible=False)
    seed_bytes = f'{config.seed}|{asof}|{asset}|{len(y)}'.encode()
    seed = int.from_bytes(hashlib.sha256(seed_bytes).digest()[:8], 'big')
    rng = np.random.default_rng(seed)
    block, gaussian = _bootstrap_returns(np.diff(y), config.bootstrap_draws,
                                        config.block_weeks, rng)
    r = np.vstack([block, gaussian])
    null_paths = np.concatenate((np.zeros((len(r),1)), np.cumsum(r,axis=1)), axis=1)
    fit = _score_batch(np.vstack((y, null_paths)))
    gain = float(fit['gain'][0])
    b = config.bootstrap_draws
    p_block = (1+int(np.count_nonzero(fit['gain'][1:1+b] >= gain-1e-12))) / (b+1)
    p_gaussian = (1+int(np.count_nonzero(fit['gain'][1+b:] >= gain-1e-12))) / (b+1)
    cycles, B = float(fit['cycles'][0]), float(fit['B'][0])
    eligible = cycles >= config.min_cycles and np.isfinite(B) and abs(B) > 1e-9
    return dict(asset=asset, asof=asof, window_weeks=len(y),
                p_block=p_block, p_gaussian=p_gaussian,
                p_joint=max(p_block,p_gaussian), oscillation_gain=gain,
                signal=('UP' if B < 0 else 'DOWN') if eligible else 'NONE',
                cycles=cycles, B=B, eligible=bool(eligible))


def benjamini_hochberg(pvalues: np.ndarray, alpha: float) -> tuple[np.ndarray,np.ndarray]:
    """BH adjusted p-values across a prespecified family at the SAME date."""
    p = np.asarray(pvalues, dtype=float)
    if not np.isfinite(p).all() or np.any((p < 0)|(p > 1)):
        raise ValueError('p-values must lie in [0,1].')
    n = len(p)
    if n == 0:
        return np.array([], dtype=bool), np.array([])
    order = np.argsort(p, kind='stable')
    q_sorted = np.minimum.accumulate((p[order] * n / np.arange(1,n+1))[::-1])[::-1]
    q = np.empty(n); q[order] = np.clip(q_sorted, 0, 1)
    return q <= alpha, q


def decide_asof(prices_by_asset: dict[str, dict[int, np.ndarray]],
                config: StatisticalConfig, asof: str) -> list[dict[str,Any]]:
    """BH includes *all* eligible asset/window tests, including weak fits."""
    rows=[]
    for asset, windows in sorted(prices_by_asset.items()):
        for w in config.windows:
            if w in windows:
                rows.append(calibrated_window(windows[w],config,asof,asset))
    if rows:
        reject,q=benjamini_hochberg(np.array([r['p_joint'] for r in rows]),config.alpha)
        for i,row in enumerate(rows):
            row['q_bh']=float(q[i]);row['significant']=bool(reject[i] and row['eligible'])
    return rows
