from __future__ import annotations

import re
import unicodedata

from ajax_terminal.models.macro import CountryProfile


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(re.findall(r"[A-Z0-9]+", ascii_text.upper()))


COUNTRIES: tuple[CountryProfile, ...] = (
    CountryProfile("US", "USA", "United States", "United States", "AMERICAS", "DM", "USD", "Federal Reserve", "SPX", "US10Y", "EURUSD", "FEDFUNDS", ("US", "USA", "AMERICA")),
    CountryProfile("CA", "CAN", "Canada", "Canada", "AMERICAS", "DM", "CAD", "Bank of Canada", "TSX", "CA10Y", "USDCAD", "IRSTCB01CAM156N"),
    CountryProfile("MX", "MEX", "Mexico", "Mexico", "AMERICAS", "EM", "MXN", "Banco de Mexico", "MEXBOL", "MX10Y"),
    CountryProfile("BR", "BRA", "Brazil", "Brazil", "AMERICAS", "EM", "BRL", "Banco Central do Brasil", "IBOV", "", "", "IRSTCB01BRM156N"),
    CountryProfile("GB", "GBR", "United Kingdom", "United Kingdom", "EUROPE", "DM", "GBP", "Bank of England", "FTSE", "GB10Y", "GBPUSD", "", ("UK", "BRITAIN", "GREAT BRITAIN")),
    CountryProfile("DE", "DEU", "Germany", "Germany", "EUROPE", "DM", "EUR", "European Central Bank", "DAX", "DE10Y", "EURUSD", "ECBDFR"),
    CountryProfile("FR", "FRA", "France", "France", "EUROPE", "DM", "EUR", "European Central Bank", "CAC", "FR10Y", "EURUSD", "ECBDFR"),
    CountryProfile("ES", "ESP", "Spain", "Spain", "EUROPE", "DM", "EUR", "European Central Bank", "IBEX", "ES10Y", "EURUSD", "ECBDFR", ("ESPANA",)),
    CountryProfile("IT", "ITA", "Italy", "Italy", "EUROPE", "DM", "EUR", "European Central Bank", "FTSEMIB", "IT10Y", "EURUSD", "ECBDFR"),
    CountryProfile("CH", "CHE", "Switzerland", "Switzerland", "EUROPE", "DM", "CHF", "Swiss National Bank", "SMI", "CH10Y", "USDCHF"),
    CountryProfile("SE", "SWE", "Sweden", "Sweden", "EUROPE", "DM", "SEK", "Riksbank", "OMXS30", "SE10Y", "USDSEK"),
    CountryProfile("NO", "NOR", "Norway", "Norway", "EUROPE", "DM", "NOK", "Norges Bank", "", "NO10Y", "USDNOK"),
    CountryProfile("PL", "POL", "Poland", "Poland", "EUROPE", "EM", "PLN", "National Bank of Poland", "", "PL10Y", "", "IRSTCB01PLM156N"),
    CountryProfile("NL", "NLD", "Netherlands", "Netherlands", "EUROPE", "DM", "EUR", "European Central Bank", "AEX", "", "EURUSD", "ECBDFR"),
    CountryProfile("PT", "PRT", "Portugal", "Portugal", "EUROPE", "DM", "EUR", "European Central Bank", "", "", "EURUSD", "ECBDFR"),
    CountryProfile("GR", "GRC", "Greece", "Greece", "EUROPE", "DM", "EUR", "European Central Bank", "", "", "EURUSD", "ECBDFR"),
    CountryProfile("EZ", "EMU", "Euro Area", "", "EUROPE", "DM", "EUR", "European Central Bank", "SX5E", "DE10Y", "EURUSD", "ECBDFR", ("EUROZONE", "EURO AREA", "EA")),
    CountryProfile("JP", "JPN", "Japan", "Japan", "ASIA", "DM", "JPY", "Bank of Japan", "NIKKEI", "JP10Y", "USDJPY", "IRSTCB01JPM156N"),
    CountryProfile("CN", "CHN", "China", "China", "ASIA", "EM", "CNY", "People's Bank of China", "CSI300", "", "", "IRSTCB01CNM156N"),
    CountryProfile("HK", "HKG", "Hong Kong", "", "ASIA", "DM", "HKD", "Hong Kong Monetary Authority", "HSI"),
    CountryProfile("KR", "KOR", "South Korea", "Korea", "ASIA", "DM", "KRW", "Bank of Korea", "KOSPI", "KR10Y", "", "", ("KOREA", "REPUBLIC OF KOREA")),
    CountryProfile("IN", "IND", "India", "India", "ASIA", "EM", "INR", "Reserve Bank of India", "NIFTY", "", "", "IRSTCB01INM156N"),
    CountryProfile("AU", "AUS", "Australia", "Australia", "ASIA", "DM", "AUD", "Reserve Bank of Australia", "ASX200", "AU10Y", "AUDUSD"),
    CountryProfile("NZ", "NZL", "New Zealand", "New Zealand", "ASIA", "DM", "NZD", "Reserve Bank of New Zealand", "", "NZ10Y", "NZDUSD"),
    CountryProfile("SG", "SGP", "Singapore", "Singapore", "ASIA", "DM", "SGD", "Monetary Authority of Singapore", "STI"),
    CountryProfile("ID", "IDN", "Indonesia", "Indonesia", "ASIA", "EM", "IDR", "Bank Indonesia"),
    CountryProfile("ZA", "ZAF", "South Africa", "South Africa", "AFRICA", "EM", "ZAR", "South African Reserve Bank", "", "ZA10Y", "", "IRSTCB01ZAM156N"),
    CountryProfile("TR", "TUR", "Turkey", "Turkey", "EUROPE", "EM", "TRY", "Central Bank of Turkey"),
)


class CountryRegistry:
    def __init__(self, countries: tuple[CountryProfile, ...] = COUNTRIES) -> None:
        self._countries = countries
        self._lookup: dict[str, CountryProfile] = {}
        for country in countries:
            values = (country.iso2, country.iso3, country.name, country.map_name, *country.aliases)
            for value in values:
                if value:
                    self._lookup[_key(value)] = country

    def all(self) -> tuple[CountryProfile, ...]:
        return self._countries

    def mapped(self) -> tuple[CountryProfile, ...]:
        return tuple(country for country in self._countries if country.map_name)

    def resolve(self, value: str | None) -> CountryProfile | None:
        return self._lookup.get(_key(value or ""))

    def search(self, value: str, limit: int = 8) -> list[CountryProfile]:
        needle = _key(value)
        if not needle:
            return list(self._countries[:limit])
        exact = self.resolve(value)
        if exact is not None:
            return [exact]
        matches = []
        for country in self._countries:
            haystack = [_key(country.name), _key(country.iso2), _key(country.iso3), *(_key(alias) for alias in country.aliases)]
            if any(candidate.startswith(needle) or needle in candidate for candidate in haystack):
                matches.append(country)
        return matches[:limit]

    def region(self, name: str) -> tuple[CountryProfile, ...]:
        selected = name.upper()
        if selected == "WORLD":
            return self.mapped()
        if selected in {"DM", "EM"}:
            return tuple(country for country in self.mapped() if country.development == selected)
        return tuple(country for country in self.mapped() if country.region == selected)


COUNTRY_REGISTRY = CountryRegistry()
