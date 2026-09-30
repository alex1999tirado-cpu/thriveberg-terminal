from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
from pathlib import Path

import numpy as np

_matplotlib_cache = Path(tempfile.gettempdir()) / "ajax-financial-terminal" / "matplotlib"
_matplotlib_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_matplotlib_cache))

import pyvista as pv
from PySide6.QtCore import Signal
from pyvistaqt import QtInteractor

from ajax_terminal.analytics.volatility_surface import SurfaceGrid, build_surface_grid, clean_vol_points
from ajax_terminal.charts.models.volatility import VolPoint, VolSurface
from ajax_terminal.charts.renderers.pyvista.camera import (
    CameraPreset,
    default_camera,
    front_camera,
    side_camera,
    top_camera,
)
from ajax_terminal.charts.renderers.pyvista.theme import (
    GRID_COLOR,
    GRID_MINOR,
    LABEL_COLOR,
    MUTED_LABEL_COLOR,
    SCENE_BACKGROUND,
    SURFACE_COLORS,
    SURFACE_EDGE,
)


@dataclass(frozen=True, slots=True)
class SceneGeometry:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    real_tenors: np.ndarray
    display_tenors: np.ndarray
    bounds: tuple[float, float, float, float, float, float]


class VolatilitySurfaceView(QtInteractor):
    point_tracked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent, auto_update=5.0)
        self.surface: VolSurface | None = None
        self.grid: SurfaceGrid | None = None
        self.geometry: SceneGeometry | None = None
        self.legend_visible = False
        self.interpolation = "linear"
        self._observations: list[VolPoint] = []
        self._observation_xyz = np.empty((0, 3))
        self._selection_actor = None
        self.set_background(SCENE_BACKGROUND)
        if self.iren is not None:
            self.enable_trackball_style()

    def set_surface(self, surface: VolSurface, *, interpolation: str = "linear") -> None:
        self.surface = surface
        self.interpolation = interpolation
        self.grid = build_surface_grid(surface, method=interpolation, tenor_steps=25)
        self.geometry = _scene_geometry(self.grid)
        self._observations = clean_vol_points(surface.points)
        self._observation_xyz = _observation_coordinates(self._observations, self.geometry)
        self._render_scene()

    def _render_scene(self) -> None:
        if self.grid is None or self.geometry is None:
            return
        self.clear()
        _populate_scene(self, self.geometry, self._observation_xyz, self.legend_visible)
        self.set_view("default")
        self.render()

    def set_legend_visible(self, visible: bool) -> None:
        self.legend_visible = visible
        self._render_scene()

    def set_tracking(self, enabled: bool) -> None:
        if self.iren is None:
            return
        if enabled:
            self.enable_point_picking(
                callback=self._picked,
                show_message=False,
                show_point=False,
                pickable_window=True,
                left_clicking=True,
            )
        else:
            self.disable_picking()

    def set_view(self, name: str) -> None:
        if self.geometry is None:
            return
        presets = {
            "default": default_camera,
            "top": top_camera,
            "flat": top_camera,
            "front": front_camera,
            "side": side_camera,
        }
        preset = presets.get(name.lower(), default_camera)(self.geometry.bounds)
        _apply_camera(self, preset)
        if name.lower() == "flat":
            self.camera.parallel_scale *= 0.82
        self.render()

    def _picked(self, picked_point) -> None:
        if not len(self._observation_xyz):
            return
        point = np.asarray(picked_point, dtype=float)
        index = int(np.argmin(np.linalg.norm(self._observation_xyz - point, axis=1)))
        selected = self._observations[index]
        location = self._observation_xyz[index]
        if self._selection_actor is not None:
            self.remove_actor(self._selection_actor, render=False)
        self._selection_actor = self.add_mesh(
            pv.Sphere(radius=max((self.geometry.bounds[1] - self.geometry.bounds[0]) * 0.012, 0.3), center=location),
            color="#20d9f7",
            smooth_shading=True,
            render=False,
        )
        self.render()
        self.point_tracked.emit(selected)


def _scene_geometry(grid: SurfaceGrid) -> SceneGeometry:
    grid_tenors = grid.tenor_days[:, 0]
    real_tenors = grid.observed_tenors
    grid_display = np.linspace(0.0, 42.0, len(grid_tenors))
    display_tenors = np.interp(np.log(real_tenors), np.log(grid_tenors), grid_display)
    y = np.repeat(grid_display[:, None], grid.moneyness.shape[1], axis=1)
    x = grid.moneyness * 100.0
    z = np.asarray(grid.iv, dtype=float)
    finite = z[np.isfinite(z)]
    if not len(finite):
        raise ValueError("Interpolation produced no supported volatility cells")
    xmin, xmax = float(np.nanmin(x)), float(np.nanmax(x))
    ymin, ymax = float(np.nanmin(y)), float(np.nanmax(y))
    zmin, zmax = float(np.nanmin(finite)), float(np.nanmax(finite))
    if zmax - zmin < 2.0:
        zmin -= 1.0
        zmax += 1.0
    return SceneGeometry(x, y, z, real_tenors, display_tenors, (xmin, xmax, ymin, ymax, zmin, zmax))


def render_surface_snapshot(
    surface: VolSurface,
    filename: str,
    *,
    interpolation: str = "linear",
    window_size: tuple[int, int] = (1400, 780),
) -> None:
    grid = build_surface_grid(surface, method=interpolation, tenor_steps=25)
    geometry = _scene_geometry(grid)
    points = clean_vol_points(surface.points)
    observations = _observation_coordinates(points, geometry)
    plotter = pv.Plotter(off_screen=True, window_size=window_size)
    plotter.set_background(SCENE_BACKGROUND)
    _populate_scene(plotter, geometry, observations, False)
    plotter.show(interactive=False, auto_close=False)
    _apply_camera(plotter, default_camera(geometry.bounds))
    plotter.render()
    plotter.screenshot(filename)
    plotter.close()


def _populate_scene(plotter, geometry: SceneGeometry, observations: np.ndarray, legend_visible: bool) -> None:
    structured = pv.StructuredGrid(geometry.x, geometry.y, geometry.z)
    structured["IV"] = geometry.z.ravel(order="F")
    plotter.add_mesh(
        structured,
        scalars="IV",
        cmap=list(SURFACE_COLORS),
        clim=_finite_limits(geometry.z),
        show_edges=True,
        edge_color=SURFACE_EDGE,
        line_width=0.55,
        smooth_shading=False,
        nan_opacity=0.0,
        show_scalar_bar=legend_visible,
        scalar_bar_args={
            "title": "IV %",
            "title_font_size": 10,
            "label_font_size": 9,
            "color": LABEL_COLOR,
            "vertical": True,
            "position_x": 0.91,
            "position_y": 0.16,
            "height": 0.45,
            "width": 0.06,
        },
    )
    if len(observations):
        cloud = pv.PolyData(observations)
        plotter.add_mesh(
            cloud,
            color="#ffd12a",
            point_size=5,
            render_points_as_spheres=True,
            opacity=0.9,
        )
    _add_reference_planes(plotter, geometry)
    _add_scene_labels(plotter, geometry)


def _observation_coordinates(points: list[VolPoint], geometry: SceneGeometry) -> np.ndarray:
    if not points:
        return np.empty((0, 3))
    locations = []
    for point in points:
        y = float(np.interp(point.tenor_days, geometry.real_tenors, geometry.display_tenors))
        locations.append((point.moneyness * 100.0, y, point.iv * 100.0))
    return np.asarray(locations, dtype=float)


def _add_reference_planes(plotter: QtInteractor, geometry: SceneGeometry) -> None:
    xmin, xmax, ymin, ymax, zmin, zmax = geometry.bounds
    xr, yr, zr = xmax - xmin, max(ymax - ymin, 1.0), max(zmax - zmin, 2.0)
    floor_z = zmin - zr * 0.30
    back_y = ymax + yr * 0.28
    side_x = xmin - xr * 0.28

    floor_x, floor_y = np.meshgrid(np.linspace(xmin, xmax, 9), np.linspace(ymin, ymax, 9))
    floor = pv.StructuredGrid(floor_x, floor_y, np.full_like(floor_x, floor_z))
    plotter.add_mesh(floor, style="wireframe", color=GRID_COLOR, line_width=0.7, opacity=0.9)

    back_x, back_z = np.meshgrid(np.linspace(xmin, xmax, 10), np.linspace(zmin, zmax, 8))
    back = pv.StructuredGrid(back_x, np.full_like(back_x, back_y), back_z)
    plotter.add_mesh(back, style="wireframe", color=GRID_COLOR, line_width=0.7, opacity=0.9)

    side_y, side_z = np.meshgrid(np.linspace(ymin, ymax, 9), np.linspace(zmin, zmax, 8))
    side = pv.StructuredGrid(np.full_like(side_y, side_x), side_y, side_z)
    plotter.add_mesh(side, style="wireframe", color=GRID_COLOR, line_width=0.7, opacity=0.9)

    for mesh in (floor, back, side):
        plotter.add_mesh(mesh.extract_feature_edges(), color=GRID_MINOR, line_width=0.8)


def _add_scene_labels(plotter: QtInteractor, geometry: SceneGeometry) -> None:
    xmin, xmax, ymin, ymax, zmin, zmax = geometry.bounds
    xr, yr, zr = xmax - xmin, max(ymax - ymin, 1.0), max(zmax - zmin, 2.0)
    floor_z = zmin - zr * 0.30
    back_y = ymax + yr * 0.28
    side_x = xmin - xr * 0.28
    x_ticks = np.linspace(xmin, xmax, min(7, max(3, geometry.x.shape[1] // 5)))
    z_ticks = np.linspace(zmin, zmax, 6)

    _labels(plotter, [(value, ymin - yr * 0.06, floor_z) for value in x_ticks], [f"{value:.0f}%" for value in x_ticks])
    _labels(
        plotter,
        [(xmax + xr * 0.035, value, floor_z) for value in geometry.display_tenors],
        [_tenor_label(int(value)) for value in geometry.real_tenors],
    )
    _labels(plotter, [(side_x - xr * 0.035, ymin, value) for value in z_ticks], [f"{value:.1f}" for value in z_ticks])
    _labels(plotter, [(xmax + xr * 0.03, back_y, value) for value in z_ticks], [f"{value:.1f}" for value in z_ticks])
    _labels(plotter, [((xmin + xmax) / 2.0, ymin - yr * 0.24, floor_z - zr * 0.05)], ["MONEYNESS / STRIKE-SPOT"] , size=11)
    _labels(plotter, [(xmax + xr * 0.19, (ymin + ymax) / 2.0, floor_z - zr * 0.04)], ["TERM"], size=11)
    _labels(plotter, [(side_x - xr * 0.16, ymin, (zmin + zmax) / 2.0)], ["IV %"], size=11)


def _labels(plotter: QtInteractor, points, labels, *, size: int = 9) -> None:
    plotter.add_point_labels(
        np.asarray(points, dtype=float),
        labels,
        font_size=size,
        text_color=MUTED_LABEL_COLOR if size <= 9 else LABEL_COLOR,
        shape=None,
        show_points=False,
        always_visible=True,
    )


def _apply_camera(plotter: QtInteractor, preset: CameraPreset) -> None:
    plotter.camera_position = [preset.position, preset.focal_point, preset.view_up]
    if preset.parallel_projection:
        plotter.enable_parallel_projection()
    else:
        plotter.disable_parallel_projection()
    plotter.camera.zoom(1.16)


def _finite_limits(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    return float(np.min(finite)), float(np.max(finite))


def _tenor_label(days: int) -> str:
    if days < 28:
        return f"{days}D"
    if days < 365:
        months = max(1, round(days / 30.4375))
        return f"{months}M"
    years = days / 365.25
    return f"{years:.0f}Y" if abs(years - round(years)) < 0.16 else f"{years:.1f}Y"
