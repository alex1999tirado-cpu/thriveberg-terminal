# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files


datas = collect_data_files("textual")
datas += [("ajax_terminal/ui/themes/ajax.tcss", "ajax_terminal/ui/themes")]
datas += collect_data_files("ajax_terminal", includes=["charts/assets/*"])
datas += collect_data_files("ajax_terminal", includes=["assets/*"])
image_datas, image_binaries, image_hiddenimports = collect_all("textual_image")
datas += image_datas
version_file = os.environ.get("THRIVEBERG_VERSION_FILE", "installer/version_info.txt")

chart_hiddenimports = [
    "ajax_terminal.desktop_app",
    "ajax_terminal.macro_map_desktop",
    "ajax_terminal.country_registry",
    "ajax_terminal.models.macro",
    "ajax_terminal.services.macro_country_service",
    "ajax_terminal.providers.eurostat",
    "ajax_terminal.providers.world_bank",
    "ajax_terminal.providers.policy_rates",
    "ajax_terminal.providers.fred_yields",
    "ajax_terminal.charts.qt_app",
    "ajax_terminal.charts.qt_windows",
    "ajax_terminal.charts.ovdv_window",
    "ajax_terminal.charts.widgets.web_chart",
    "ajax_terminal.charts.renderers.three_globe.renderer",
    "ajax_terminal.charts.renderers.lightweight.renderer",
    "ajax_terminal.charts.renderers.echarts.renderer",
    "ajax_terminal.charts.renderers.pyvista.volatility_surface",
]

analysis = Analysis(
    ["ajax_terminal/__main__.py"],
    pathex=["."],
    binaries=image_binaries,
    datas=datas,
    hiddenimports=[*image_hiddenimports, *chart_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="THRIVEBERG_Terminal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_file,
    icon="ajax_terminal/assets/thriveberg.ico",
)

bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="THRIVEBERG_Terminal",
)
