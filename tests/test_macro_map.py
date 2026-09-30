from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ajax_terminal.charts.renderers.echarts.renderer import EChartsRenderer
from ajax_terminal.charts.renderers.three_globe.renderer import ThreeGlobeRenderer
from ajax_terminal.country_registry import COUNTRY_REGISTRY
from ajax_terminal.macro_map_desktop import (
    build_globe_payload,
    build_map_option,
    build_visual_pieces,
    country_shortcuts,
    parse_macro_map_args,
)
from ajax_terminal.models.macro import (
    CountryMapValue,
    MacroMapDataset,
    MacroMapMetric,
    MacroObservation,
)
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.eurostat import normalize_eurostat_latest
from ajax_terminal.providers.world_bank import normalize_world_bank_latest
from ajax_terminal.services.macro_country_service import (
    MacroCountryService,
    _observation_to_dict,
    normalize_map_metric,
)
from ajax_terminal.storage.cache import SQLiteCache


def _observation(code: str, value: float) -> MacroObservation:
    return MacroObservation(
        code=code,
        value=value,
        unit="%",
        period="2025",
        source="Official Test Source",
        quality=DataQuality.DELAYED,
        status="LATEST OFFICIAL",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def test_country_registry_resolves_iso_names_aliases_and_market_mapping() -> None:
    spain = COUNTRY_REGISTRY.resolve("ESP")
    assert spain is not None
    assert COUNTRY_REGISTRY.resolve("es") is spain
    assert COUNTRY_REGISTRY.resolve("espana") is spain
    assert (spain.main_equity_index, spain.sovereign_10y, spain.fx_reference) == (
        "IBEX",
        "ES10Y",
        "EURUSD",
    )
    assert COUNTRY_REGISTRY.resolve("UK").iso3 == "GBR"
    assert COUNTRY_REGISTRY.resolve("Korea").iso3 == "KOR"


def test_country_search_and_region_filters() -> None:
    assert COUNTRY_REGISTRY.search("switz")[0].iso3 == "CHE"
    assert COUNTRY_REGISTRY.search("jap")[0].iso3 == "JPN"
    assert all(country.region == "EUROPE" for country in COUNTRY_REGISTRY.region("EUROPE"))
    assert all(country.development == "EM" for country in COUNTRY_REGISTRY.region("EM"))


def test_map_arguments_and_country_shortcuts() -> None:
    metric, region, profile = parse_macro_map_args(("CPI", "EUROPE", "SPAIN"))
    assert (metric, region, profile.iso3) == (MacroMapMetric.CPI, "EUROPE", "ESP")
    links = country_shortcuts(profile)
    assert links == {
        "ECO": "ECO ES",
        "RATES": "RATES ES",
        "INDEX": "INDEX IBEX",
        "FX": "FX EURUSD",
        "NEWS": "NEWS SPAIN",
        "CAL": "CAL ES",
    }


def test_world_bank_normalization_selects_latest_real_period() -> None:
    payload = [
        {"page": 1},
        [
            {"countryiso3code": "ESP", "date": "2023", "value": 2.1},
            {"countryiso3code": "ESP", "date": "2025", "value": 2.8},
            {"countryiso3code": "USA", "date": "2025", "value": None},
        ],
    ]
    values = normalize_world_bank_latest(payload, "GDP", "GDP Growth", "%")

    assert values["ESP"].value == 2.8
    assert values["ESP"].period == "2025"
    assert values["ESP"].source == "World Bank"
    assert "USA" not in values


def test_metric_selection_and_dynamic_color_scales() -> None:
    assert normalize_map_metric("inflation") == MacroMapMetric.CPI
    assert normalize_map_metric("unemployment") == MacroMapMetric.UNEMPLOYMENT
    assert normalize_map_metric("yield") == MacroMapMetric.SOVEREIGN_10Y
    growth = build_visual_pieces([-2.0, 0.0, 4.0], MacroMapMetric.GDP)
    inflation = build_visual_pieces([1.0, 3.0, 8.0], MacroMapMetric.CPI)
    assert len(growth) == len(inflation) == 5
    assert growth[0]["color"] != inflation[0]["color"]


def test_choropleth_preserves_missing_data_as_unavailable() -> None:
    spain = COUNTRY_REGISTRY.resolve("ESP")
    germany = COUNTRY_REGISTRY.resolve("DEU")
    dataset = MacroMapDataset(
        MacroMapMetric.GDP,
        [CountryMapValue(spain, _observation("GDP", 2.8)), CountryMapValue(germany, None)],
    )
    option = build_map_option(dataset)
    data = option["series"][0]["data"]
    by_name = {item["name"]: item for item in data}

    assert by_name["Spain"]["value"] == 2.8
    assert by_name["Germany"]["value"] is None
    assert by_name["Germany"]["status"] == "UNAVAILABLE"


class _FailingWorldBank:
    async def latest(self, _countries, _metric):
        raise ProviderError("offline")


def test_provider_failure_uses_stale_cache_and_marks_it(tmp_path) -> None:
    cache = SQLiteCache(tmp_path / "macro.sqlite3")
    cached = _observation("GDP", 1.7)
    cache.set_json("macro_country:v2:ESP:gdp", _observation_to_dict(cached), -1)
    service = MacroCountryService(cache=cache, world_bank=_FailingWorldBank())

    dataset = asyncio.run(service.world_dataset("GDP", "EUROPE"))
    spain = next(item for item in dataset.values if item.profile.iso3 == "ESP")

    assert spain.observation.value == 1.7
    assert spain.observation.quality == DataQuality.CACHED
    assert spain.observation.status == "CACHED"


def test_eurostat_json_stat_normalization_uses_latest_available_period() -> None:
    payload = {
        "id": ["unit", "geo", "time"],
        "size": [1, 2, 2],
        "dimension": {
            "unit": {"category": {"index": {"RCH_A": 0}}},
            "geo": {"category": {"index": {"FR": 0, "DE": 1}}},
            "time": {"category": {"index": {"2026-07": 0, "2026-08": 1}}},
        },
        "value": {"0": 1.8, "1": 1.9, "2": 2.1},
        "status": {"1": "p"},
    }

    observations = normalize_eurostat_latest(
        payload,
        "CPI",
        "% y/y",
        {"FR": "FRA", "DE": "DEU"},
    )

    assert observations["FRA"].value == 1.9
    assert observations["FRA"].period == "2026-08"
    assert observations["FRA"].status == "OFFICIAL PRELIMINARY"
    assert observations["DEU"].value == 2.1
    assert observations["DEU"].period == "2026-07"


def test_echarts_map_option_has_professional_interaction_contract() -> None:
    spain = COUNTRY_REGISTRY.resolve("ESP")
    dataset = MacroMapDataset(MacroMapMetric.CPI, [CountryMapValue(spain, _observation("CPI", 2.4))])
    option = build_map_option(dataset, "EUROPE")

    series = option["series"][0]
    assert series["type"] == "map"
    assert series["map"] == "world"
    assert series["roam"] is True
    assert series["selectedMode"] == "single"
    assert option["visualMap"]["type"] == "piecewise"


def test_echarts_renderer_registers_map_and_country_bridge(tmp_path) -> None:
    renderer = EChartsRenderer(tmp_path / "echarts.js")
    html = renderer.render(
        {"series": [{"type": "map", "map": "world"}]},
        map_geojson={"type": "FeatureCollection", "features": []},
        country_events=True,
    )

    assert "echarts.registerMap('world'" in html
    assert "qrc:///qtwebchannel/qwebchannel.js" in html
    assert "terminalBridge.selectCountry" in html


def test_three_globe_payload_and_renderer_are_interactive(tmp_path) -> None:
    spain = COUNTRY_REGISTRY.resolve("ESP")
    dataset = MacroMapDataset(MacroMapMetric.GDP, [CountryMapValue(spain, _observation("GDP", 2.8))])
    payload = build_globe_payload(dataset, "EUROPE", selected_name="Spain")
    module = tmp_path / "three.module.js"
    core = tmp_path / "three.core.js"
    module.write_text("export const REVISION='test';", encoding="utf-8")
    core.write_text("export const CORE=true;", encoding="utf-8")
    html = ThreeGlobeRenderer(module, core).render(
        payload,
        {"type": "FeatureCollection", "features": []},
    )

    assert payload["selectedName"] == "Spain"
    assert payload["view"] == {"longitude": 14, "latitude": 49, "distance": 3.15}
    assert "new THREE.SphereGeometry" in html
    assert "new THREE.Raycaster" in html
    assert "globe.worldToLocal(hit.point.clone())" in html
    assert "window.ajaxCountryAtCoordinates" in html
    assert "const points=unwrapRing(ring)" in html
    assert "pointerdown" in html
    assert "wheel" in html
    assert "terminalBridge.selectCountry" in html
    assert "https://" not in html
