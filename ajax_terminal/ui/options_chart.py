from __future__ import annotations

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image as PILImage

from ajax_terminal.models.options import VolatilitySurface


FIGURE_BG = "#000000"
PANEL_BG = "#181a1c"
PLOT_BG = "#121416"
HEADER_BG = "#34383c"
GRID = "#65717a"
TEXT = "#e3e5e7"
MUTED = "#a6adb5"
YELLOW = "#f2c94c"
ORANGE = "#d99116"
RED = "#ff3b38"
COLORS = ("#f2c94c", "#38bdf8", "#30d979", "#ff5a5f", "#d7dce2", "#ff9f1c")
SURFACE_CMAP = LinearSegmentedColormap.from_list(
    "ajax_bloomberg_surface",
    (
        (0.00, "#00a83b"),
        (0.26, "#39d12f"),
        (0.48, "#d7e128"),
        (0.66, "#ffd11a"),
        (0.82, "#ff850d"),
        (1.00, "#e32620"),
    ),
)


def build_volatility_image(
    surface: VolatilitySurface,
    mode: str = "SKEW",
    *,
    elevation: float = 14.0,
    azimuth: float = -48.0,
    zoom: float = 1.0,
    selected_slice: int = 0,
    moneyness_range: tuple[float, float] = (0.75, 1.25),
    tracked_moneyness: float = 1.0,
) -> PILImage.Image:
    if not surface.slices:
        raise ValueError("No valid implied-volatility observations are available")
    figure = Figure(figsize=(16, 7.4), dpi=100, facecolor=FIGURE_BG)
    selected_index = max(0, min(selected_slice, len(surface.slices) - 1))
    selected = surface.slices[selected_index]
    normalized_mode = mode.upper()

    main_bounds = (0.018, 0.050, 0.59, 0.85)
    term_bounds = (0.655, 0.535, 0.335, 0.365)
    skew_bounds = (0.655, 0.035, 0.335, 0.365)
    _panel_background(figure, main_bounds, facecolor=PANEL_BG, show_border=False)
    _panel_background(figure, term_bounds, facecolor=FIGURE_BG)
    _panel_background(figure, skew_bounds, facecolor=FIGURE_BG)
    figure.add_artist(
        Rectangle((0.629, 0.025), 0.0015, 0.91, transform=figure.transFigure, facecolor="#767b80", edgecolor="none")
    )

    if normalized_mode == "SURFACE":
        main_axis = figure.add_axes(main_bounds, projection="3d")
        _draw_surface(
            main_axis,
            surface,
            elevation=elevation,
            azimuth=azimuth,
            zoom=zoom,
            moneyness_range=moneyness_range,
        )
        main_title = "3D VOLATILITY SURFACE"
        main_selector = f"{surface.symbol} / LISTED"
    elif normalized_mode == "TERM":
        main_axis = figure.add_axes(main_bounds)
        _draw_terms(main_axis, surface)
        main_title = "VOLATILITY VS. TERM"
        main_selector = "MULTI-MONEYNESS"
    else:
        main_axis = figure.add_axes(main_bounds)
        _draw_skews(
            main_axis,
            surface,
            moneyness_range=moneyness_range,
            tracked_moneyness=tracked_moneyness,
        )
        main_title = "SKEW / EXPIRY COMPARISON"
        main_selector = "LISTED EXPIRIES"

    term_axis = figure.add_axes(term_bounds)
    skew_axis = figure.add_axes(skew_bounds)
    _draw_term_cut(term_axis, surface, tracked_moneyness)
    _draw_skew_cut(skew_axis, surface, selected_index, moneyness_range, tracked_moneyness)
    matched_limits = _matched_iv_limits(surface)
    term_axis.set_ylim(*matched_limits)
    skew_axis.set_ylim(*matched_limits)
    if normalized_mode in {"SKEW", "TERM"}:
        main_axis.set_ylim(*matched_limits)

    _panel_header(figure, main_bounds, main_title, main_selector)
    _panel_header(
        figure,
        term_bounds,
        "VOLATILITY VS. TERM",
        f"MONEYNESS {tracked_moneyness * 100:.1f}%",
    )
    _panel_header(
        figure,
        skew_bounds,
        "MONEYNESS",
        f"TERM {selected.days_to_expiry}D / {selected.expiry:%d %b %y}",
    )
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    width, height = canvas.get_width_height()
    return PILImage.frombuffer(
        "RGBA",
        (width, height),
        canvas.buffer_rgba(),
        "raw",
        "RGBA",
        0,
        1,
    ).convert("RGB")


def _panel_background(
    figure: Figure,
    bounds: tuple[float, float, float, float],
    *,
    facecolor: str,
    show_border: bool = True,
) -> None:
    x, y, width, height = bounds
    figure.add_artist(
        Rectangle(
            (x - 0.006, y - 0.012),
            width + 0.012,
            height + 0.012,
            transform=figure.transFigure,
            facecolor=facecolor,
            edgecolor="#5f666c" if show_border else facecolor,
            linewidth=0.7 if show_border else 0.0,
            zorder=-10,
        )
    )


def _panel_header(
    figure: Figure,
    bounds: tuple[float, float, float, float],
    title: str,
    selector: str,
) -> None:
    x, y, width, height = bounds
    header_y = y + height + 0.008
    header_height = 0.035
    figure.add_artist(
        Rectangle(
            (x - 0.006, header_y),
            width + 0.012,
            header_height,
            transform=figure.transFigure,
            facecolor=HEADER_BG,
            edgecolor="#777b80",
            linewidth=0.6,
        )
    )
    figure.text(x, header_y + header_height / 2, title, color=TEXT, fontsize=10.5, va="center", ha="left")
    figure.text(
        x + width,
        header_y + header_height / 2,
        selector,
        color="#050607",
        fontsize=8.5,
        va="center",
        ha="right",
        weight="bold",
        bbox={"facecolor": ORANGE, "edgecolor": "none", "pad": 2.5},
    )


def _draw_skews(
    axis,
    surface: VolatilitySurface,
    *,
    moneyness_range: tuple[float, float],
    tracked_moneyness: float,
) -> None:
    _style_axis(axis)
    for index, slice_ in enumerate(surface.slices):
        points = sorted(slice_.points, key=lambda item: item.moneyness)
        axis.plot(
            [point.moneyness * 100.0 for point in points],
            [point.implied_volatility * 100.0 for point in points],
            color=COLORS[index % len(COLORS)],
            linewidth=1.35,
            marker="D",
            markersize=2.3,
            label=f"{slice_.expiry:%d %b %y} / {slice_.days_to_expiry}D",
        )
    axis.axvline(100.0, color="#d8dde2", linewidth=0.7, linestyle=":")
    axis.axvline(tracked_moneyness * 100.0, color=ORANGE, linewidth=0.9)
    axis.set_xlim(moneyness_range[0] * 100.0, moneyness_range[1] * 100.0)
    axis.set_xlabel("Moneyness / Spot (%)")
    axis.set_ylabel("Implied Volatility (%)")
    legend = axis.legend(
        loc="upper right",
        fontsize=7.2,
        ncols=2,
        facecolor="#101214",
        edgecolor="#70757a",
        framealpha=0.95,
    )
    for text in legend.get_texts():
        text.set_color(TEXT)


def _draw_terms(axis, surface: VolatilitySurface) -> None:
    _style_axis(axis)
    for index, moneyness in enumerate(surface.moneyness_grid):
        terms: list[int] = []
        values: list[float] = []
        for slice_ in surface.slices:
            value = _interpolated_iv(slice_, moneyness)
            if value is not None:
                terms.append(slice_.days_to_expiry)
                values.append(value * 100.0)
        if terms:
            axis.plot(
                terms,
                values,
                color=COLORS[index % len(COLORS)],
                linewidth=1.35,
                marker="D",
                markersize=2.5,
                label=f"{moneyness * 100:.0f}% MNY",
            )
    _set_term_ticks(axis, surface)
    axis.set_xlabel("Listed Expiry")
    axis.set_ylabel("Implied Volatility (%)")
    legend = axis.legend(loc="upper right", fontsize=7.2, ncols=2, facecolor="#101214", edgecolor="#70757a")
    for text in legend.get_texts():
        text.set_color(TEXT)


def _draw_surface(
    axis,
    surface: VolatilitySurface,
    *,
    elevation: float,
    azimuth: float,
    zoom: float,
    moneyness_range: tuple[float, float],
) -> None:
    observed_x: list[float] = []
    observed_y: list[float] = []
    observed_z: list[float] = []
    for slice_ in surface.slices:
        for point in slice_.points:
            observed_x.append(point.moneyness * 100.0)
            observed_y.append(_term_coordinate(slice_.days_to_expiry))
            observed_z.append(point.implied_volatility * 100.0)

    x_mesh, y_mesh, grid = _dense_surface(surface, moneyness_range)
    if grid.size and np.isfinite(grid).sum() >= 4:
        finite_grid = grid[np.isfinite(grid)]
        color_minimum = float(finite_grid.min())
        color_maximum = float(finite_grid.max())
        if color_maximum <= color_minimum:
            color_maximum = color_minimum + 1e-6
        color_norm = PowerNorm(
            gamma=1.35,
            vmin=color_minimum,
            vmax=color_maximum,
        )
        axis.plot_surface(
            x_mesh,
            y_mesh,
            np.ma.masked_invalid(grid),
            cmap=SURFACE_CMAP,
            norm=color_norm,
            edgecolor="#151715",
            linewidth=0.24,
            antialiased=True,
            alpha=1.0,
            shade=False,
            rcount=min(grid.shape[0], 50),
            ccount=min(grid.shape[1], 70),
        )
    axis.set_facecolor(PANEL_BG)
    axis.set_xlabel("Moneyness (%)", color=TEXT, labelpad=7)
    axis.set_ylabel("Term", color=TEXT, labelpad=7)
    axis.set_zlabel("IV (%)", color=TEXT, labelpad=6)
    terms = sorted({slice_.days_to_expiry for slice_ in surface.slices})
    axis.set_yticks([_term_coordinate(days) for days in terms])
    axis.set_yticklabels([_tenor_label(days) for days in terms])
    axis.tick_params(colors="#e1e3e5", labelsize=7.2, pad=0)
    for pane in (axis.xaxis.pane, axis.yaxis.pane):
        pane.set_facecolor("#202326")
        pane.set_edgecolor("#a6aaad")
        pane.set_alpha(0.0)
    axis.zaxis.pane.set_facecolor("#181a1c")
    axis.zaxis.pane.set_edgecolor("#555b60")
    axis.zaxis.pane.set_alpha(0.0)
    axis.grid(False)
    for axis_part in (axis.xaxis, axis.yaxis, axis.zaxis):
        axis_part._axinfo["grid"].update(color=(0.0, 0.0, 0.0, 0.0), linewidth=0.0)
        axis_part._axinfo["axisline"].update(color=(0.0, 0.0, 0.0, 0.0), linewidth=0.0)
        axis_part.line.set_color((0.0, 0.0, 0.0, 0.0))
    axis.view_init(elev=elevation, azim=azimuth)
    axis.set_proj_type("persp", focal_length=0.95)
    axis.set_box_aspect((1.85, 1.30, 0.30), zoom=2.08)
    axis.set_zlim(*_matched_iv_limits(surface))
    _apply_zoom(axis, observed_x, observed_y, observed_z, zoom, moneyness_range)
    _draw_floating_axis_grids(axis)


def _dense_surface(
    surface: VolatilitySurface,
    moneyness_range: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    low = max(moneyness_range[0], min(surface.moneyness_grid))
    high = min(moneyness_range[1], max(surface.moneyness_grid))
    x_dense = np.linspace(low * 100.0, high * 100.0, 44)
    slices = sorted(surface.slices, key=lambda item: item.days_to_expiry)
    source_days = np.array([max(slice_.days_to_expiry, 1) for slice_ in slices], dtype=float)
    source_rows = np.full((len(slices), len(x_dense)), np.nan, dtype=float)
    for row, slice_ in enumerate(slices):
        points = sorted(slice_.points, key=lambda item: item.moneyness)
        if len(points) < 2:
            continue
        xs = np.array([point.moneyness * 100.0 for point in points], dtype=float)
        zs = np.array([point.implied_volatility * 100.0 for point in points], dtype=float)
        source_rows[row, :] = _fit_display_smile(xs, zs, x_dense)
    if len(source_days) == 1:
        y_dense = np.array([_term_coordinate(source_days[0])], dtype=float)
        dense = source_rows.copy()
    else:
        display_days = np.geomspace(float(source_days.min()), float(source_days.max()), 24)
        y_dense = np.log(display_days)
        dense = np.full((len(display_days), len(x_dense)), np.nan, dtype=float)
        for column in range(len(x_dense)):
            valid = np.isfinite(source_rows[:, column])
            if valid.sum() < 2:
                continue
            terms = source_days[valid]
            values = source_rows[valid, column] / 100.0
            total_variance = values**2 * (terms / 365.0)
            interpolated_variance = np.interp(display_days, terms, total_variance)
            dense[:, column] = np.sqrt(interpolated_variance / (display_days / 365.0)) * 100.0
    x_mesh, y_mesh = np.meshgrid(x_dense, y_dense)
    return x_mesh, y_mesh, dense


def _draw_term_cut(axis, surface: VolatilitySurface, tracked_moneyness: float) -> None:
    _style_axis(axis)
    terms: list[int] = []
    volatilities: list[float] = []
    for slice_ in surface.slices:
        value = _interpolated_iv(slice_, tracked_moneyness)
        if value is not None:
            terms.append(slice_.days_to_expiry)
            volatilities.append(value * 100.0)
    axis.plot(terms, volatilities, color=RED, marker="D", markersize=3.3, linewidth=1.35)
    _set_term_ticks(axis, surface)
    axis.set_xlabel("Listed Expiry")
    axis.set_ylabel("IV %")


def _draw_skew_cut(
    axis,
    surface: VolatilitySurface,
    selected_index: int,
    moneyness_range: tuple[float, float],
    tracked_moneyness: float,
) -> None:
    _style_axis(axis)
    slice_ = surface.slices[selected_index]
    points = sorted(slice_.points, key=lambda item: item.moneyness)
    xs = [point.moneyness * 100.0 for point in points]
    ys = [point.implied_volatility * 100.0 for point in points]
    axis.plot(xs, ys, color=RED, marker="D", markersize=2.8, linewidth=1.35)
    tracked_iv = _interpolated_iv(slice_, tracked_moneyness)
    if tracked_iv is not None:
        axis.scatter(
            [tracked_moneyness * 100.0],
            [tracked_iv * 100.0],
            color=YELLOW,
            edgecolor="#050607",
            s=30,
            zorder=5,
        )
    axis.axvline(100.0, color="#d8dde2", linewidth=0.7, linestyle=":")
    axis.set_xlim(moneyness_range[0] * 100.0, moneyness_range[1] * 100.0)
    axis.set_xlabel("Strike / Spot %")
    axis.set_ylabel("IV %")


def _set_term_ticks(axis, surface: VolatilitySurface) -> None:
    terms = [slice_.days_to_expiry for slice_ in surface.slices]
    if len(terms) > 1 and min(terms) > 0:
        axis.set_xscale("log")
    axis.set_xticks(terms)
    axis.set_xticklabels([_tenor_label(days) for days in terms], rotation=0)


def _tenor_label(days: int) -> str:
    if days < 45:
        return f"{days}D"
    if days < 730:
        return f"{max(round(days / 30), 1)}M"
    return f"{days / 365:.1f}Y".replace(".0Y", "Y")


def _term_coordinate(days: float) -> float:
    return float(np.log(max(float(days), 1.0)))


def _fit_display_smile(xs: np.ndarray, zs: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Fit a smooth display smile while keeping values anchored to observed IVs."""
    if len(xs) < 3:
        return np.interp(targets, xs, zs, left=zs[0], right=zs[-1])
    coordinates = np.log(np.maximum(xs, 1e-6) / 100.0)
    target_coordinates = np.log(np.maximum(targets, 1e-6) / 100.0)
    degree = min(3, len(xs) - 1)
    coefficients = np.polyfit(coordinates, zs, degree)
    fitted_observations = np.polyval(coefficients, coordinates)
    residuals = np.abs(zs - fitted_observations)
    median_residual = float(np.median(residuals))
    if median_residual > 0 and len(xs) >= degree + 3:
        keep = residuals <= max(median_residual * 3.5, 0.35)
        if int(keep.sum()) >= degree + 1:
            coefficients = np.polyfit(coordinates[keep], zs[keep], degree)
    fitted = np.polyval(coefficients, target_coordinates)
    observed_span = max(float(zs.max() - zs.min()), 1.0)
    lower = max(0.01, float(zs.min()) - observed_span * 0.20)
    upper = float(zs.max()) + observed_span * 0.20
    return np.clip(fitted, lower, upper)


def _matched_iv_limits(surface: VolatilitySurface) -> tuple[float, float]:
    values = [
        point.implied_volatility * 100.0
        for slice_ in surface.slices
        for point in slice_.points
        if np.isfinite(point.implied_volatility)
    ]
    if not values:
        return 0.0, 100.0
    minimum = min(values)
    maximum = max(values)
    span = max(maximum - minimum, 4.0)
    return max(0.0, minimum - span * 0.12), maximum + span * 0.12


def _interpolated_iv(slice_, target: float) -> float | None:
    grid_value = slice_.grid.get(target)
    if grid_value is not None:
        return grid_value
    points = sorted(slice_.points, key=lambda point: point.moneyness)
    if len(points) < 2 or target < points[0].moneyness or target > points[-1].moneyness:
        return None
    return float(
        np.interp(
            target,
            [point.moneyness for point in points],
            [point.implied_volatility for point in points],
        )
    )


def _apply_zoom(
    axis,
    xs: list[float],
    ys: list[float],
    zs: list[float],
    zoom: float,
    moneyness_range: tuple[float, float],
) -> None:
    if not xs or not ys or not zs:
        return
    factor = max(0.65, min(zoom, 2.5))
    x_low = max(min(xs), moneyness_range[0] * 100.0)
    x_high = min(max(xs), moneyness_range[1] * 100.0)
    _set_zoomed_limit(axis.set_xlim, x_low, x_high, factor, minimum_span=10.0)
    y_span = max(max(ys) - min(ys), 0.7)
    _set_zoomed_limit(axis.set_ylim, min(ys), max(ys), factor, minimum_span=y_span)


def _set_zoomed_limit(setter, minimum: float, maximum: float, zoom: float, minimum_span: float) -> None:
    center = (minimum + maximum) / 2.0
    span = max(maximum - minimum, minimum_span) * 1.18 / zoom
    setter(center - span / 2.0, center + span / 2.0)


def _draw_floating_axis_grids(axis) -> None:
    x_low, x_high = axis.get_xlim3d()
    y_low, y_high = axis.get_ylim3d()
    z_low, z_high = axis.get_zlim3d()
    x_span = x_high - x_low
    y_span = y_high - y_low
    z_span = z_high - z_low
    original_x_ticks = [tick for tick in axis.get_xticks() if x_low <= tick <= x_high]
    original_y_ticks = list(axis.get_yticks())
    original_y_labels = [label.get_text() for label in axis.get_yticklabels()]
    original_z_ticks = [tick for tick in axis.get_zticks() if z_low <= tick <= z_high]

    side_x = x_low - x_span * 0.62
    rear_y = y_high + y_span * 0.32
    floor_z = z_low - z_span * 0.28
    floor_x_low = x_low + x_span * 0.06
    floor_x_high = x_high - x_span * 0.06
    panel_y_low = y_low + y_span * 0.06
    panel_y_high = y_high - y_span * 0.06
    wall_z_low = z_low + z_span * 0.06

    axis.set_xlim3d(side_x - x_span * 0.06, x_high + x_span * 0.12)
    axis.set_ylim3d(y_low - y_span * 0.16, rear_y + y_span * 0.05)
    axis.set_zlim3d(floor_z - z_span * 0.07, z_high + z_span * 0.03)
    side_y_ticks = np.linspace(panel_y_low, panel_y_high, 8)
    rear_x_ticks = np.linspace(floor_x_low, floor_x_high, 10)
    wall_z_ticks = np.linspace(wall_z_low, z_high, 7)
    floor_x_ticks = np.linspace(floor_x_low, floor_x_high, 10)
    floor_y_ticks = np.linspace(panel_y_low, panel_y_high, 8)
    style = {"color": "#9aa2a8", "linewidth": 0.56, "alpha": 0.88}

    # Three separate grids: side wall, floor and rear wall.
    for value in side_y_ticks:
        axis.plot([side_x, side_x], [value, value], [wall_z_low, z_high], **style)
    for value in wall_z_ticks:
        axis.plot([side_x, side_x], [panel_y_low, panel_y_high], [value, value], **style)

    for value in rear_x_ticks:
        axis.plot([value, value], [rear_y, rear_y], [wall_z_low, z_high], **style)
    for value in wall_z_ticks:
        axis.plot([floor_x_low, floor_x_high], [rear_y, rear_y], [value, value], **style)

    for value in floor_x_ticks:
        axis.plot([value, value], [panel_y_low, panel_y_high], [floor_z, floor_z], **style)
    for value in floor_y_ticks:
        axis.plot([floor_x_low, floor_x_high], [value, value], [floor_z, floor_z], **style)

    tick_style = {"color": "#e1e3e5", "fontsize": 8.0}
    for value in original_x_ticks:
        axis.text(
            value,
            panel_y_low - y_span * 0.025,
            floor_z - z_span * 0.012,
            f"{value:.0f}",
            ha="center",
            va="top",
            **tick_style,
        )
    for value, label in zip(original_y_ticks, original_y_labels):
        axis.text(
            floor_x_high + x_span * 0.025,
            value,
            floor_z - z_span * 0.012,
            label,
            ha="left",
            va="center",
            **tick_style,
        )
    for value in original_z_ticks:
        label = f"{value:.1f}" if not np.isclose(value, round(value)) else f"{value:.0f}"
        axis.text(
            side_x + x_span * 0.40,
            panel_y_low,
            value,
            label,
            ha="right",
            va="center",
            **tick_style,
        )

    label_style = {"color": TEXT, "fontsize": 8.8}
    axis.text(
        (floor_x_low + floor_x_high) / 2.0,
        panel_y_low - y_span * 0.18,
        floor_z - z_span * 0.025,
        "Moneyness (%)",
        ha="center",
        va="top",
        **label_style,
    )
    axis.text(
        floor_x_high - x_span * 0.02,
        panel_y_high + y_span * 0.08,
        floor_z - z_span * 0.02,
        "Term",
        ha="left",
        va="center",
        **label_style,
    )
    axis.set_xticks([])
    axis.set_yticks([])
    axis.set_zticks([])
    axis.set_xlabel("")
    axis.set_ylabel("")
    axis.set_zlabel("")


def _style_axis(axis) -> None:
    axis.set_facecolor(PLOT_BG)
    axis.figure.patch.set_facecolor(FIGURE_BG)
    axis.tick_params(colors="#d2d6da", labelsize=8)
    axis.xaxis.label.set_color(TEXT)
    axis.yaxis.label.set_color(TEXT)
    for spine in axis.spines.values():
        spine.set_color("#8a9096")
        spine.set_linewidth(0.8)
    axis.grid(True, color=GRID, linestyle="--", linewidth=0.55, alpha=0.58)
