from __future__ import annotations

from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass, Instrument


def normalize_symbol(symbol: str) -> str:
    return INSTRUMENT_REGISTRY.provider_symbol(symbol)


def canonical_symbol(symbol: str) -> str:
    return INSTRUMENT_REGISTRY.resolve(symbol).symbol


def is_fx_pair(symbol: str) -> bool:
    instrument = INSTRUMENT_REGISTRY.get(symbol)
    return instrument is not None and instrument.asset_class == AssetClass.FX


def split_fx_pair(pair: str) -> tuple[str, str]:
    clean = INSTRUMENT_REGISTRY.normalize(pair)
    instrument = INSTRUMENT_REGISTRY.get(clean)
    if instrument is None or instrument.asset_class != AssetClass.FX:
        raise ValueError(f"Invalid G10 FX pair: {pair}")
    return instrument.symbol[:3], instrument.symbol[3:]


def display_fx_pair(pair: str) -> str:
    base, quote = split_fx_pair(pair)
    return f"{base}/{quote}"


def infer_instrument(query: str) -> Instrument:
    return INSTRUMENT_REGISTRY.resolve(query)
