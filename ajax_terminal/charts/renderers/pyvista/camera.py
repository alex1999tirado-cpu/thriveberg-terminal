from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CameraPreset:
    position: tuple[float, float, float]
    focal_point: tuple[float, float, float]
    view_up: tuple[float, float, float]
    parallel_projection: bool = False


def default_camera(bounds: tuple[float, float, float, float, float, float]) -> CameraPreset:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    xr = max(xmax - xmin, 1.0)
    yr = max(ymax - ymin, 1.0)
    zr = max(zmax - zmin, 1.0)
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)
    return CameraPreset(
        position=(center[0] - xr * 0.24, ymin - yr * 2.65, zmax + max(zr * 1.15, xr * 0.32)),
        focal_point=(center[0] + xr * 0.04, center[1] + yr * 0.08, center[2] - zr * 0.08),
        view_up=(0.0, 0.0, 1.0),
    )


def top_camera(bounds: tuple[float, float, float, float, float, float]) -> CameraPreset:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)
    span = max(xmax - xmin, ymax - ymin, 1.0)
    return CameraPreset((center[0], center[1], zmax + span * 2.4), center, (0.0, 1.0, 0.0), True)


def front_camera(bounds: tuple[float, float, float, float, float, float]) -> CameraPreset:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)
    span = max(xmax - xmin, zmax - zmin, 1.0)
    return CameraPreset((center[0], ymin - span * 2.6, center[2]), center, (0.0, 0.0, 1.0), True)


def side_camera(bounds: tuple[float, float, float, float, float, float]) -> CameraPreset:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)
    span = max(ymax - ymin, zmax - zmin, 1.0)
    return CameraPreset((xmin - span * 2.6, center[1], center[2]), center, (0.0, 0.0, 1.0), True)
