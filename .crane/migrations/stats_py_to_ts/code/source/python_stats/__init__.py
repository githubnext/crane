"""A tiny statistics library used as the source for the stats_py_to_ts migration example.

The TypeScript+Go target should be drop-in compatible: same function names, same
argument shapes, same outputs (to within 1e-9 numerical tolerance) on the parity
corpus in ../../parity/.
"""

from math import sqrt
from typing import List, Tuple


def mean(xs: List[float]) -> float:
    if not xs:
        raise ValueError("mean requires at least one element")
    return sum(xs) / len(xs)


def variance(xs: List[float]) -> float:
    if len(xs) < 2:
        raise ValueError("variance requires at least two elements")
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def stddev(xs: List[float]) -> float:
    return sqrt(variance(xs))


def median(xs: List[float]) -> float:
    if not xs:
        raise ValueError("median requires at least one element")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def quantile(xs: List[float], q: float) -> float:
    """Linear-interpolation quantile (matches numpy's default `linear` method)."""
    if not xs:
        raise ValueError("quantile requires at least one element")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Ordinary least squares. Returns (slope, intercept)."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have the same length")
    if len(xs) < 2:
        raise ValueError("linear_regression requires at least two points")
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        raise ValueError("xs must have non-zero variance")
    slope = num / den
    intercept = my - slope * mx
    return slope, intercept
