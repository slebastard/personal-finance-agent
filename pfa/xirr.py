from __future__ import annotations

import datetime as dt


def xnpv(rate: float, flows: list[tuple[dt.date, float]]) -> float:
    t0 = flows[0][0]
    return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in flows)


def xirr(flows: list[tuple[dt.date, float]], lo: float = -0.99, hi: float = 10.0) -> float | None:
    """Money-weighted annualized return. Investor convention: deposits negative, value/withdrawals positive."""
    flows = sorted(flows)
    if len(flows) < 2 or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    if (flows[-1][0] - flows[0][0]).days < 1:
        return None
    try:
        f_lo, f_hi = xnpv(lo, flows), xnpv(hi, flows)
    except (OverflowError, ZeroDivisionError):
        return None
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = xnpv(mid, flows)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2
