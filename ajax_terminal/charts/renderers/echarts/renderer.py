from __future__ import annotations

import json
from pathlib import Path

from ajax_terminal.charts.theme import AJAX_BACKGROUND


ASSET_NAME = "echarts-6.1.0.min.js"


class EChartsRenderer:
    name = "Apache ECharts"

    def __init__(self, asset_path: Path | None = None) -> None:
        self.asset_path = asset_path or Path(__file__).resolve().parents[2] / "assets" / ASSET_NAME

    def render(
        self,
        option: dict[str, object],
        *,
        map_geojson: dict[str, object] | None = None,
        country_events: bool = False,
    ) -> str:
        map_payload = json.dumps(map_geojson, separators=(",", ":")) if map_geojson else "null"
        channel_script = '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>' if country_events else ""
        return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body,#chart{{width:100%;height:100%;margin:0;overflow:hidden;background:{AJAX_BACKGROUND}}}
</style></head><body><div id="chart"></div>{channel_script}
<script src="{self.asset_path.as_uri()}"></script><script>
const worldGeoJSON={map_payload};
if(worldGeoJSON){{echarts.registerMap('world',worldGeoJSON);}}
const chart=echarts.init(document.getElementById('chart'),null,{{renderer:'canvas',useDirtyRect:true}});
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,ch=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
const prepareOption=value=>{{
  if(worldGeoJSON && value.tooltip){{
    value.tooltip.formatter=params=>{{
      const item=params.data||{{}};
      if(item.value===null || item.value===undefined || item.value==='-'){{
        return `<b>${{escapeHtml(params.name)}}</b><br><span style="color:#8f99a3">DATA UNAVAILABLE</span>`;
      }}
      return `<b>${{escapeHtml(item.country||params.name)}}</b> &nbsp; ${{escapeHtml(item.iso3||'')}}<br>`+
        `<span style="color:#4f9ebb">${{escapeHtml(item.metricLabel||'VALUE')}}</span> &nbsp; <b>${{escapeHtml(item.displayValue||item.value)}}</b><br>`+
        `${{escapeHtml(item.period||'')}}<br><span style="color:#8f99a3">${{escapeHtml(item.source||'UNKNOWN')}} | ${{escapeHtml(item.status||'')}}</span>`;
    }};
  }}
  return value;
}};
let option=prepareOption({json.dumps(option, separators=(',', ':'))});
chart.setOption(option,true);
window.ajaxSetOption=value=>{{option=prepareOption(value);chart.setOption(option,true);}};
window.ajaxResize=()=>chart.resize();
window.ajaxSelectCountry=name=>{{
  chart.dispatchAction({{type:'unselect',seriesIndex:0}});
  if(name){{chart.dispatchAction({{type:'select',seriesIndex:0,name:name}});}}
}};
let terminalBridge=null;
if(window.qt && window.QWebChannel){{
  new QWebChannel(qt.webChannelTransport,channel=>{{terminalBridge=channel.objects.terminalBridge;}});
}}
chart.on('click',params=>{{
  if(terminalBridge && params.componentType==='series' && params.name){{terminalBridge.selectCountry(String(params.name));}}
}});
window.addEventListener('resize',()=>chart.resize());
</script></body></html>"""
