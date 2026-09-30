from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ajax_terminal.charts.models.volatility import VolPoint, VolSurface


@dataclass(frozen=True, slots=True)
class SurfaceGrid:
    moneyness: np.ndarray
    tenor_days: np.ndarray
    iv: np.ndarray
    method: str
    observed_tenors: np.ndarray


@dataclass(frozen=True, slots=True)
class VolSnapshot:
    atm_iv: float | None
    put_25d_iv: float | None
    call_25d_iv: float | None
    risk_reversal: float | None
    butterfly: float | None
    skew_slope: float | None


def clean_vol_points(points: list[VolPoint]) -> list[VolPoint]:
    """Keep credible observed points without flattening genuine wing volatility.

    Inputs are already liquidity-filtered by ``OptionsService``. This second pass
    rejects impossible IV/moneyness values, duplicate contracts and isolated IV
    observations farther than six median absolute deviations within a tenor.
    """
    unique: dict[tuple[int, float, str], VolPoint] = {}
    for point in points:
        if not 0.02 <= point.iv <= 3.0:
            continue
        if not 0.5 <= point.moneyness <= 1.5:
            continue
        unique[(point.tenor_days, round(point.strike, 8), point.option_type)] = point

    grouped: dict[int, list[VolPoint]] = {}
    for point in unique.values():
        grouped.setdefault(point.tenor_days, []).append(point)
    cleaned: list[VolPoint] = []
    for tenor_points in grouped.values():
        tenor_points.sort(key=lambda item: item.moneyness)
        if len(tenor_points) < 8:
            cleaned.extend(tenor_points)
            continue
        values = np.asarray([point.iv for point in tenor_points], dtype=float)
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        limit = max(6.0 * 1.4826 * mad, 0.35)
        cleaned.extend(point for point in tenor_points if abs(point.iv - median) <= limit)
    return sorted(cleaned, key=lambda item: (item.tenor_days, item.moneyness))


def build_surface_grid(
    surface: VolSurface,
    *,
    method: str = "linear",
    moneyness_steps: int = 41,
    tenor_steps: int | None = None,
) -> SurfaceGrid:
    method = method.lower()
    if method not in {"nearest", "linear", "cubic"}:
        raise ValueError("Interpolation must be nearest, linear or cubic")
    points = clean_vol_points(surface.points)
    tenors = np.asarray(sorted({point.tenor_days for point in points}), dtype=float)
    if len(points) < 4 or len(tenors) < 2:
        raise ValueError("At least four observations across two expiries are required")
    lower = max(min(point.moneyness for point in points), 0.5)
    upper = min(max(point.moneyness for point in points), 1.5)
    if upper <= lower:
        raise ValueError("Observed strikes do not span a usable moneyness range")
    x_values = np.linspace(lower, upper, max(5, moneyness_steps))
    y_values = (
        np.geomspace(float(tenors[0]), float(tenors[-1]), max(len(tenors), tenor_steps))
        if tenor_steps is not None and len(tenors) > 1
        else tenors
    )
    x_grid, y_grid = np.meshgrid(x_values, y_values)
    observations = np.asarray([(point.moneyness, point.tenor_days) for point in points], dtype=float)
    values = np.asarray([point.iv * 100.0 for point in points], dtype=float)

    try:
        from scipy.interpolate import griddata
        from scipy.spatial import Delaunay
    except ImportError as exc:
        raise RuntimeError("SciPy is required to interpolate volatility surfaces") from exc

    interpolation_method = method
    if method == "linear":
        iv_grid = _linear_smile_term_grid(points, tenors, x_values, y_values)
    else:
        if method == "cubic" and len(points) < 16:
            interpolation_method = "linear"
            iv_grid = _linear_smile_term_grid(points, tenors, x_values, y_values)
        else:
            iv_grid = griddata(
                observations,
                values,
                (x_grid, y_grid),
                method=interpolation_method,
                fill_value=np.nan,
            )
    if interpolation_method == "nearest":
        hull = Delaunay(observations)
        outside = hull.find_simplex(np.column_stack((x_grid.ravel(), y_grid.ravel()))) < 0
        iv_grid.ravel()[outside] = np.nan
    return SurfaceGrid(x_grid, y_grid, iv_grid, interpolation_method, tenors)


def _linear_smile_term_grid(
    points: list[VolPoint],
    observed_tenors: np.ndarray,
    x_values: np.ndarray,
    y_values: np.ndarray,
) -> np.ndarray:
    observed_rows = np.full((len(observed_tenors), len(x_values)), np.nan, dtype=float)
    for row, tenor in enumerate(observed_tenors):
        smile = sorted(
            (point for point in points if point.tenor_days == int(tenor)),
            key=lambda point: point.moneyness,
        )
        if len(smile) < 2:
            continue
        x = np.asarray([point.moneyness for point in smile], dtype=float)
        iv = np.asarray([point.iv * 100.0 for point in smile], dtype=float)
        supported = (x_values >= x[0]) & (x_values <= x[-1])
        observed_rows[row, supported] = np.interp(x_values[supported], x, iv)

    result = np.full((len(y_values), len(x_values)), np.nan, dtype=float)
    for column in range(len(x_values)):
        supported = np.isfinite(observed_rows[:, column])
        if np.count_nonzero(supported) < 2:
            continue
        y = observed_tenors[supported]
        iv = observed_rows[supported, column]
        target_supported = (y_values >= y[0]) & (y_values <= y[-1])
        result[target_supported, column] = np.interp(y_values[target_supported], y, iv)
    return result


def term_structure(surface: VolSurface) -> list[tuple[int, float]]:
    result: list[tuple[int, float]] = []
    for tenor in sorted({point.tenor_days for point in surface.points}):
        candidates = [point for point in surface.points if point.tenor_days == tenor]
        if not candidates:
            continue
        atm = min(candidates, key=lambda point: abs(point.moneyness - 1.0))
        if abs(atm.moneyness - 1.0) <= 0.08:
            result.append((tenor, atm.iv * 100.0))
    return result


def skew_for_tenor(surface: VolSurface, tenor_days: int) -> list[VolPoint]:
    return sorted(
        (point for point in clean_vol_points(surface.points) if point.tenor_days == tenor_days),
        key=lambda point: point.moneyness,
    )


def volatility_snapshot(surface: VolSurface, tenor_days: int | None = None) -> VolSnapshot:
    tenors = surface.tenors
    if not tenors:
        return VolSnapshot(None, None, None, None, None, None)
    tenor = tenor_days if tenor_days in tenors else tenors[0]
    points = skew_for_tenor(surface, tenor)
    if not points:
        return VolSnapshot(None, None, None, None, None, None)
    atm = min(points, key=lambda point: abs(point.moneyness - 1.0))
    calls = [point for point in points if point.option_type == "call" and point.delta is not None]
    puts = [point for point in points if point.option_type == "put" and point.delta is not None]
    call = min(calls, key=lambda point: abs(float(point.delta) - 0.25)) if calls else None
    put = min(puts, key=lambda point: abs(float(point.delta) + 0.25)) if puts else None
    call_iv = call.iv if call is not None and abs(float(call.delta) - 0.25) <= 0.15 else None
    put_iv = put.iv if put is not None and abs(float(put.delta) + 0.25) <= 0.15 else None
    rr = call_iv - put_iv if call_iv is not None and put_iv is not None else None
    fly = (call_iv + put_iv) / 2.0 - atm.iv if call_iv is not None and put_iv is not None else None
    slope = _linear_skew_slope(points)
    return VolSnapshot(
        atm_iv=atm.iv,
        put_25d_iv=put_iv,
        call_25d_iv=call_iv,
        risk_reversal=rr,
        butterfly=fly,
        skew_slope=slope,
    )


def black_scholes_delta(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
    option_type: str,
) -> float | None:
    if min(spot, strike, time_years, volatility) <= 0:
        return None
    denominator = volatility * math.sqrt(time_years)
    d1 = (
        math.log(spot / strike)
        + (rate - dividend_yield + 0.5 * volatility * volatility) * time_years
    ) / denominator
    normal_cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    discounted = math.exp(-dividend_yield * time_years)
    if option_type.lower() == "call":
        return discounted * normal_cdf
    if option_type.lower() == "put":
        return discounted * (normal_cdf - 1.0)
    raise ValueError("Option type must be call or put")


def _linear_skew_slope(points: list[VolPoint]) -> float | None:
    near = [point for point in points if 0.85 <= point.moneyness <= 1.15]
    if len(near) < 2:
        return None
    x = np.asarray([point.moneyness for point in near], dtype=float)
    y = np.asarray([point.iv for point in near], dtype=float)
    return float(np.polyfit(x, y, 1)[0])
