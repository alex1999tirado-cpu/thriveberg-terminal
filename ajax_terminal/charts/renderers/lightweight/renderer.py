from __future__ import annotations

import html
import json
from pathlib import Path

from ajax_terminal.charts.models.ohlcv import OHLCVChart
from ajax_terminal.charts.renderers.lightweight.indicators import attach_default_indicators
from ajax_terminal.charts.renderers.lightweight.theme import SERIES_COLORS, chart_options
from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_BACKGROUND, AJAX_MUTED, AJAX_TEXT


ASSET_NAME = "lightweight-charts-5.2.1.min.js"


class LightweightChartsRenderer:
    name = "TradingView Lightweight Charts"

    def __init__(self, asset_path: Path | None = None) -> None:
        self.asset_path = asset_path or Path(__file__).resolve().parents[2] / "assets" / ASSET_NAME

    def render(
        self,
        chart: OHLCVChart,
        *,
        chart_type: str = "candle",
        studies: set[str] | None = None,
        horizontal_lines: list[float] | None = None,
        trend_lines: list[tuple[int, float, int, float]] | None = None,
    ) -> str:
        if not chart.points:
            raise ValueError(f"No real history is available for {chart.symbol}")
        attach_default_indicators(chart)
        selected_studies = studies if studies is not None else {"volume", "sma20", "ema50"}
        price_data = [
            {
                "time": point.epoch,
                "open": point.open,
                "high": point.high,
                "low": point.low,
                "close": point.close,
            }
            for point in chart.points
        ]
        line_data = [{"time": point.epoch, "value": point.close} for point in chart.points]
        volume_data = [
            {
                "time": point.epoch,
                "value": point.volume or 0.0,
                "color": "#18753b" if point.close >= point.open else "#9b2439",
            }
            for point in chart.points
        ]
        payload = {
            "price": price_data,
            "line": line_data,
            "volume": volume_data,
            "indicators": {
                key: [{"time": time, "value": value} for time, value in values]
                for key, values in chart.indicators.items()
            },
            "events": chart.events,
            "hLines": horizontal_lines or [],
            "trendLines": trend_lines or [],
        }
        return _document(
            asset_uri=self.asset_path.as_uri(),
            title=f"{chart.symbol} {chart.period} / {chart.interval}",
            subtitle=f"{chart.provider} | {chart.quality} | {len(chart.points)} BARS",
            payload=payload,
            options=chart_options(),
            chart_type=chart_type.lower(),
            studies=selected_studies,
        )


def _document(
    *,
    asset_uri: str,
    title: str,
    subtitle: str,
    payload: dict[str, object],
    options: dict[str, object],
    chart_type: str,
    studies: set[str],
) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body,#chart{{width:100%;height:100%;margin:0;overflow:hidden;background:{AJAX_BACKGROUND};font-family:Consolas,monospace}}
#chart{{position:absolute;inset:0 0 18px 0}}
#legend{{position:absolute;left:10px;top:7px;z-index:4;color:{AJAX_TEXT};font-size:13px;pointer-events:none}}
#legend b{{color:{AJAX_AMBER}}} #legend small{{color:{AJAX_MUTED}}}
#ohlc{{display:block;margin-top:3px;color:{AJAX_TEXT}}}
#attribution{{position:absolute;right:8px;bottom:2px;z-index:6;color:{AJAX_MUTED};font-size:10px}}
#attribution a{{color:{AJAX_MUTED};text-decoration:none}}
</style></head><body>
<div id="chart"></div>
<div id="legend"><b>{html.escape(title)}</b><small> &nbsp; {html.escape(subtitle)}</small><span id="ohlc"></span></div>
<div id="attribution">Charts by <a href="https://www.tradingview.com/" target="_blank">TradingView</a></div>
<script src="{asset_uri}"></script><script>
const DATA={json.dumps(payload, separators=(',', ':'))};
const OPTIONS={json.dumps(options, separators=(',', ':'))};
const chart=LightweightCharts.createChart(document.getElementById('chart'),OPTIONS);
const addSeries=(definition,legacy,options)=>chart.addSeries?chart.addSeries(definition,options):chart[legacy](options);
const type={json.dumps(chart_type)};
let priceSeries;
if(type==='line'){{
 priceSeries=addSeries(LightweightCharts.LineSeries,'addLineSeries',{{color:'{AJAX_AMBER}',lineWidth:2,priceLineVisible:true}});
 priceSeries.setData(DATA.line);
}} else if(type==='ohlc'||type==='bar'){{
 priceSeries=addSeries(LightweightCharts.BarSeries,'addBarSeries',{{upColor:'{SERIES_COLORS['up']}',downColor:'{SERIES_COLORS['down']}',thinBars:true}});
 priceSeries.setData(DATA.price);
}} else {{
 priceSeries=addSeries(LightweightCharts.CandlestickSeries,'addCandlestickSeries',{{upColor:'{SERIES_COLORS['up']}',downColor:'{SERIES_COLORS['down']}',borderVisible:false,wickUpColor:'{SERIES_COLORS['up']}',wickDownColor:'{SERIES_COLORS['down']}'}});
 priceSeries.setData(DATA.price);
}}
const activeStudies={json.dumps(sorted(studies))};
let volumeSeries=null; const indicatorSeries={{}};
if(activeStudies.includes('volume')){{
 volumeSeries=addSeries(LightweightCharts.HistogramSeries,'addHistogramSeries',{{priceFormat:{{type:'volume'}},priceScaleId:'volume'}});
 volumeSeries.priceScale().applyOptions({{scaleMargins:{{top:0.78,bottom:0.0}}}}); volumeSeries.setData(DATA.volume);
}}
const indicatorColors={json.dumps(SERIES_COLORS)};
for(const [key,values] of Object.entries(DATA.indicators)){{
 if(!activeStudies.includes(key)||!values.length)continue;
 const series=addSeries(LightweightCharts.LineSeries,'addLineSeries',{{color:indicatorColors[key],lineWidth:2,lastValueVisible:false,priceLineVisible:false}});
 series.setData(values); indicatorSeries[key]=series;
}}
for(const price of DATA.hLines) priceSeries.createPriceLine({{price,color:'{AJAX_AMBER}',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'H-LINE'}});
for(const line of DATA.trendLines){{
 const series=addSeries(LightweightCharts.LineSeries,'addLineSeries',{{color:'{AJAX_AMBER}',lineWidth:2,lastValueVisible:false,priceLineVisible:false}});
 series.setData([{{time:line[0],value:line[1]}},{{time:line[2],value:line[3]}}]);
}}
if(DATA.events.length){{
 if(LightweightCharts.createSeriesMarkers) LightweightCharts.createSeriesMarkers(priceSeries,DATA.events);
 else if(priceSeries.setMarkers) priceSeries.setMarkers(DATA.events);
}}
chart.subscribeCrosshairMove(param=>{{
 if(!param.time){{document.getElementById('ohlc').textContent='';return;}}
 const value=param.seriesData.get(priceSeries); if(!value)return;
 const text=value.open===undefined?`PX ${{value.value.toFixed(4)}}`:`O ${{value.open.toFixed(4)}}  H ${{value.high.toFixed(4)}}  L ${{value.low.toFixed(4)}}  C ${{value.close.toFixed(4)}}`;
 document.getElementById('ohlc').textContent=text;
}});
chart.timeScale().fitContent();
window.ajaxFit=()=>chart.timeScale().fitContent();
window.ajaxUpdateBars=payloads=>{{for(const payload of payloads){{
 const bar=payload.bar;
 priceSeries.update(type==='line'?{{time:bar.time,value:bar.close}}:bar);
 if(volumeSeries&&payload.volume)volumeSeries.update(payload.volume);
 for(const [key,value] of Object.entries(payload.indicators||{{}}))if(indicatorSeries[key])indicatorSeries[key].update(value);
}}}};
window.addEventListener('resize',()=>chart.resize(document.body.clientWidth,document.body.clientHeight-18));
</script></body></html>"""
