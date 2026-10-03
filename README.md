# THRIVEBERG Terminal

**THRIVEBERG** - Markets. Data. Analytics.

![THRIVEBERG OVDV implied-volatility workstation](screenshots/ovdv-aapl-surface.png)

THRIVEBERG Terminal is a local Python market workstation inspired by the density and speed of professional financial terminals. It uses a black, compact, keyboard-first interface with modular panels, watchlists, command navigation, analytics, and a provider layer designed for public data first and private APIs later.

For SEC EDGAR access, set `AJAX_SEC_USER_AGENT` to an identifying application/contact string for sustained use, for example `My Research Terminal name@example.com`. THRIVEBERG caches filing indexes for six hours and stays well below the SEC fair-access limit during normal use.

It does not use Bloomberg branding, logos, proprietary typefaces, or protected UI assets.

## Product tour

### Automatic global market wall

![THRIVEBERG Global Overview market wall](screenshots/global-overview-wall.png)

`WALL` turns the selected display into a dense four-pane global overview. The
default layout combines an intraday `EURUSD` chart, world equities, global
sovereign rates and the market-news wire, so price action, rates and headlines
remain visible together. Each pane is a real THRIVEBERG workspace rather than a
static dashboard: double-click its header to expand it across the display and
double-click again to restore the 2 x 2 grid.

### Tabbed and multi-monitor workspaces

![THRIVEBERG independent workspace tabs](screenshots/workspace-tabs.png)

Each tab retains its own security, command history and live view. Tabs can be
reordered, closed, restored at the next sign-in, or opened as complete
independent terminal windows for two- and three-monitor desks.

### Cross-asset market monitor

![THRIVEBERG native cross-asset market monitor](screenshots/terminal-markets.png)

`MARKETS` is a native cross-asset dashboard for equities, FX, sovereign rates,
credit and commodities. Its interactive matrix, daily-movers chart, selected-
security detail, verified headline preview and asset-class breadth panel share a
single dense workspace. Double-clicking a security opens `GP`; a single news
click previews the story and a double-click opens its source. The layout reduces
to the essential market columns when used inside the Global Overview wall.

### Fundamentals and listed options

| Detailed balance sheet | Listed-option chain |
| --- | --- |
| ![AAPL detailed balance sheet](screenshots/aapl-balance-sheet.png) | ![AAPL listed-option monitor](screenshots/aapl-option-monitor.png) |

### Price discovery and market structure

| Interactive price chart | Official USD yield curve |
| --- | --- |
| ![AAPL interactive price chart](screenshots/equity-price-chart.png) | ![Official USD Treasury yield curve](screenshots/usd-yield-curve.png) |

### World bond markets

| Global sovereign matrix | Spain government curve |
| --- | --- |
| ![Global 10-year sovereign yield matrix and comparison](screenshots/government-bonds-global.png) | ![Spain government yield curve by tenor](screenshots/government-bonds-spain.png) |

`GOVT` and `WB` open a native sovereign-rates workspace grouped into Americas,
EMEA and Asia-Pacific. The matrix aligns current yield, latest observed change
in basis points, spread to the US 10-year benchmark, one-year range, observation
frequency and data quality with a graphical cross-market comparison. Regional
commands such as `GOVT EMEA` narrow the universe; country commands such as
`GOVT ES` switch to the complete registered term structure. Double-click any
benchmark or chart point to open its one-year history in `GP`.

### Research workflow

| Security description | Global corporate calendar |
| --- | --- |
| ![AAPL security description](screenshots/equity-description.png) | ![Global corporate event calendar](screenshots/global-event-calendar.png) |

| Relative valuation | Live news wire |
| --- | --- |
| ![AAPL relative valuation](screenshots/aapl-relative-valuation.png) | ![Live financial news wire](screenshots/live-news-wire.png) |

### Listed-options volatility

OVDV turns real listed-option observations into an interactive implied-volatility surface. The native VTK viewport supports drag rotation, pan and zoom, while the same workspace tracks the term structure, smile/skew and market snapshot.

![AAPL implied-volatility surface rendered with VTK](screenshots/ovdv-aapl-surface-vtk.png)

### Global macro map

![Interactive global macro map with Spain selected](screenshots/global-macro-map.png)

### DOOM command

![Freedoom Phase 1 embedded in THRIVEBERG Terminal](screenshots/doom-freedoom.png)

`DOOM` launches the complete Freedoom Phase 1 campaign through Chocolate Doom
inside the terminal workspace. The native game window can be detached and
docked again with `POP OUT`; configuration and savegames stay under the current
Windows user's local application data. No proprietary DOOM IWAD is distributed.

### Data integrity and provider health

![THRIVEBERG provider health and cache diagnostics](screenshots/data-quality-monitor.png)

![THRIVEBERG cross-source quote comparison](screenshots/data-quality-comparison.png)

`DQM` audits the configured provider stack without storing credentials or raw
provider responses. It persists the latest availability and latency plus cumulative success/failure history, inventories
fresh and stale cache entries, documents domain coverage, and compares an
instrument across every applicable quote source. Double-clicking a comparison
opens the existing `FLDS` field-level provenance view.

### Portfolio accounting and attribution

| Multi-currency holdings and P&L | Security-level attribution |
| --- | --- |
| ![THRIVEBERG portfolio accounting](screenshots/portfolio-accounting.png) | ![THRIVEBERG portfolio performance attribution](screenshots/portfolio-attribution.png) |

`PORT` maintains a persistent transaction and cash ledger, weighted native and
base-currency costs, realized and unrealized P&L, income, fees, cash expenses,
NAV and security-level contribution. Broker CSV files are always previewed
before application; IBKR, DEGIRO, Trading 212 and generic exports are normalized
with duplicate protection and explicit FX validation.

### Portfolio risk and stress testing

![THRIVEBERG current-weight portfolio risk](screenshots/portfolio-risk.png)

`PORT <portfolio> RISK <benchmark> <period>` calculates base-currency daily
returns from observed price and FX histories. The four risk views report
coverage, annualized return and volatility, historical VaR/expected shortfall,
drawdown, Sharpe, benchmark beta, marginal contribution, pairwise correlation,
factor exposures and stress P&L. Factor loadings use observed liquid proxies
(`SPY`, `IWM`, `IWD`, `IWF`, `MTUM` and `QUAL` by default). Historical replays
are labelled `OBSERVED`; linear factor, FX and concentration shocks carry an
`ESTIMATED*` marker and display their methodology.

### Corporate actions and ledger adjustments

![THRIVEBERG observed portfolio corporate actions](screenshots/portfolio-corporate-actions.png)

`PORT <portfolio> ACTIONS` reconciles observed Yahoo Finance dividends and
splits against dated portfolio transactions. The preview shows entitlement,
native cash, event-date FX, base-currency value, position delta, provider,
quality and control status before any write. `APPLY ELIGIBLE` is idempotent:
dividends enter the cash ledger once, while splits restate quantities, average
cost and any later realized P&L without changing the book value at the split
date. Existing same-day manual dividends and unreconciled positions are held for
review. Yahoo chart events do not reliably provide payment dates, so eligible
dividends are explicitly booked on ex-date; unsupported spin-offs, rights issues
and cash-in-lieu terms are never inferred.

### Background alert engine

![THRIVEBERG background alert engine](screenshots/background-alert-engine.png)

`ALRT` monitors enabled rules throughout an authenticated desktop session, even
when another terminal function is open. It supports market prices and volume,
fundamental ratios, new regulatory filings, verified news, upcoming corporate
events and portfolio-risk thresholds. Numeric rules fire only when the condition
crosses from false to true and then rearm; feed rules prime their existing items
and record only newly observed fingerprints. Every trigger is persisted with its
source, quality, value, detail and document URL, can be acknowledged, and is
deduplicated transactionally if manual and background refreshes overlap. Checks
run every 30 seconds for market rules, two minutes for news, 15 minutes for
fundamentals/filings/events and 30 minutes for portfolio risk. The engine runs
locally while THRIVEBERG is open; it is not a cloud alert service when the PC or
application is off.

THRIVEBERG is a research and market-monitoring workstation. It does not route
orders, hold client money, or provide investment advice. Every data view carries
its provider and quality state; unavailable observations remain unavailable.

## Features

- Textual/Rich terminal interface with dense market panels.
- Universal command palette.
- Configurable `WALL` global overview with four independent live workspaces, automatic secondary-display startup and single-pane expansion.
- Live workspace tabs with independent instrument context, history and retained views; any tab can open as a complete second terminal window for multi-monitor desks.
- Native cross-asset market monitor with a structured quote matrix, daily-movers chart, security drill-down, verified news preview, breadth analytics and responsive Global Overview mode.
- Central instrument registry: 27 global indices, 45 G10 FX crosses, 28 sovereign yields, 6 credit benchmarks, 8 corporate cash bonds, and 17 major commodities.
- `WEI` world indices monitor grouped into Americas, Europe, and Asia-Pacific with YTD performance and market status.
- Filterable instrument discovery screens and a full G10 FX matrix.
- FX spot monitor and theoretical FX forwards.
- Government-bond monitor with global 10Y benchmarks and country drill-down, plus an official daily US Treasury curve.
- Corporate-credit monitor with daily ICE BofA/FRED effective yields and OAS by IG, HY, and rating.
- SEC-sourced corporate cash-bond directory with description and user-price YTM, duration, convexity, accrued-interest, and DV01 analytics.
- Macro monitor and indicator views.
- Interactive Three.js `MAP` globe with country drill-down, regional filters, official-period labels, sovereign rates and market shortcuts.
- Bloomberg-style interactive news wire with multi-source RSS aggregation, topic/ticker filters, categories, story detail, source links, deduplication, and cached fallback.
- Dense equity overview pages with company identity, valuation, growth, margins, returns, earnings dates, consensus targets, and related news.
- Dynamic equity resolution with detailed annual and quarterly income statements, balance sheets, and cash-flow statements. US issuers use official SEC 10-K/10-Q XBRL facts first, with provider fallback elsewhere.
- Jurisdiction-aware filing discovery: SEC EDGAR for US listings, LEI-resolved ESEF annual reports across the EEA, Companies House for UK accounts when `COMPANIES_HOUSE_API_KEY` is configured, and official disclosure portals for Canada, Japan, Korea, China, India, Brazil, Australia, Hong Kong, Switzerland and other mapped exchanges. Unknown foreign suffixes never fall back to SEC.
- Equity research functions for financial analysis, estimates, recommendations, relative valuation, dividends, corporate events, and screening.
- Native PySide6 chart workstations: TradingView Lightweight Charts for `GP`, Apache ECharts for analytical 2D views, and PyVista/VTK for the interactive `OVDV` volatility surface.
- Embedded `DOOM` workspace powered by Chocolate Doom 3.1.1 and the freely redistributable Freedoom Phase 1 0.13.0 campaign, with native docking, pop-out and local savegames.
- Persistent SQLite cache and watchlist storage.
- Native workstation tools: editable named watchlists (`WATC`); multi-currency portfolio accounting, performance attribution, broker CSV import, historical risk, factor exposure, correlation, stress testing and audited corporate-action adjustments (`PORT`); market alerts (`ALRT`); saved multi-factor screens (`EQS`); and a paged corporate calendar (`EVT ALL`) with watchlist, portfolio, market-cap, industry and geographic filters. Global provider and cache diagnostics (`DQM`), field-level source audit (`FLDS`), persistent workspaces (`WSP`), crash recovery, system diagnostics with sanitized support export (`DIAG`), and an Ed25519-signed online beta manager (`UPD`) are also included.
- Decoupled provider interfaces with cached fallback and explicit unavailable or estimated labels; fictitious market observations are not presented as real data.
- Analytics for FX forwards, fixed income, Black-Scholes options, volatility, and risk.
- Supabase-backed user accounts, friend requests, private messages, clickable THRIVEBERG command links, and self-contained friend ZIP export.
- Pytest coverage for command parsing, forwards, bonds, options, and provider normalization.

## Install

Python 3.12+ is recommended. The project is kept compatible with Python 3.11+ so it can run in common local environments.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

For the heavier data science stack, use:

```bash
python -m pip install -e ".[dev,full]"
```

Install the x64 chart runtime on Windows once with:

```powershell
.\setup_charts.ps1
```

It detects Python 3.11+ x64 and creates `.venv_gui`. The web chart engines and
their licenses are bundled locally, so rendering does not require a CDN.

Run:

```bash
python -m ajax_terminal
```

or:

```bash
thriveberg
```

## Windows Installer

The current beta is distributed as a per-user Windows installer:

```text
releases\BETA\THRIVEBERG-Terminal-BETA-022-Setup.exe
```

It installs THRIVEBERG Terminal under `%LOCALAPPDATA%\Programs`, creates the
normal shortcuts and can upgrade the same installation in place. A later setup
replaces the application files automatically while preserving the current
user's encrypted settings.

Build the next installer after changing the source with:

```powershell
.\build_installer.ps1
```

The default build number is `023`, so the preserved Beta 022 installer is never
overwritten accidentally. Pass `-BetaVersion` explicitly for later releases.

The build uses PyInstaller's one-directory layout internally and Inno Setup for
installation and upgrades. See [`installer/README.md`](installer/README.md).
Release executables, checksums and signed manifests are intentionally excluded
from source history. [Beta 022](https://github.com/alex1999tirado-cpu/thriveberg-terminal-releases/releases/tag/v0.5.0-beta.22)
uses a binary-only public update channel:
`UPD` verifies an Ed25519-signed manifest, signed size and SHA-256 before launching
an installer, supports interrupted-download resumption, and revalidates cached
installers before rollback. Windows Authenticode is still pending, so recipients
may continue to see a Microsoft SmartScreen warning.

## Security and integrity

- Private API keys are excluded from source and installers and are stored in a
  versioned per-user Windows DPAPI envelope with atomic V1-to-V2 migration.
- Provider downloads and external browser links require HTTPS; fixed providers
  also enforce hostname allowlists. Online updates accept only the public
  distribution repository and reject unsigned, altered, oversized or downgraded
  release metadata.
- Supabase access is constrained by Auth and row-level security. The bundled
  key is publishable and has no administrative privileges.
- CI runs 311 tests, `pip-audit`, `detect-secrets`, and Bandit for every change.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and
[the latest audit](docs/SECURITY_AUDIT.md) for verified results and residual
risks. The in-app Ed25519 signature authenticates THRIVEBERG update artifacts;
Authenticode publisher reputation remains a separate future hardening step.

## API Configuration

In the desktop terminal, open `TOOLS > DATA CONNECTIONS` to configure or remove
provider credentials. Sensitive settings are encrypted with Windows DPAPI and
stored in `%LOCALAPPDATA%\THRIVEBERG Terminal\secure-settings.bin`, bound to the
current Windows user. Recognized values left in a legacy `.env` file are migrated,
verified and removed from the plaintext file at startup. Existing V1 encrypted
stores are backed up in encrypted form and migrated transactionally.

`.env.example` remains available only as a source-development fallback. Never
embed personal or privileged API keys in an installer or release archive.
Private provider credentials are optional enhancements that each user may add
later; they are not required to install, create an account, or open the terminal.

The terminal works without private keys by using public endpoints when available and by falling back to cached data or mock data clearly labeled as `MOCK`. Mock data is never presented as live market data.

THRIVEBERG Social uses the shared Supabase project bundled as public client
configuration. A clean installation can create an account and sign in without
entering API keys. The bundled publishable key has no elevated privileges and
is restricted by Auth and the row-level security policies in
[`supabase/social_schema.sql`](supabase/social_schema.sql). Environment or
DPAPI-backed overrides remain available for development and self-hosted builds;
secret and `service_role` keys are always rejected. See
[`supabase/README.md`](supabase/README.md).

## Commands

```text
HELP
MARKETS
WEI
INSTRUMENTS
INSTRUMENTS FX
INSTRUMENTS INDEX
INSTRUMENTS RATES
INSTRUMENTS GOVT
INSTRUMENTS CORP
INSTRUMENTS BOND
INSTRUMENTS CMDTY
FX
FXC
FX EURUSD
FX EURJPY
FX GBPJPY
EURUSD
FX:EURUSD
FWD EURUSD
FWD EURUSD 3M
CURVE USD
CURVE EUR
GOVT
BTMM US
WB
GOVT US
GOVT DE
GOVT US10Y
CORP
CORP AAPL
CORP USCORPIG
BOND AAPL44
BOND AAPL44 PRICE 98.50
BOND 4.25 2034-05-15 98.50
GP USCORPIG 1Y 1D
ECO US
ECO CPI US
MAP
MAP GDP
MAP CPI EUROPE
MAP UNEMP SPAIN
MAP RATE DM
MAP 10Y AMERICAS
MAP EQUITY ASIA
WORLD CPI
CAL
NEWS
NEWS FED
NEWS ECONOMY
NEWS CENTRAL BANKS
NEWS AAPL
EQ AAPL
EQ AAPL 3M
EQ SAN.MC 1Y
FA AAPL
EE NVDA
ANR AAPL
DVD MSFT
EVT AAPL
EVT
EVT ALL 30
EVT ALL 30 2
EVT ALL 30 1 MCAP:MEGA IND:SEMICONDUCTORS GEO:US_LISTED
EVT WATC:DEFAULT 30 1
EVT PORT:MAIN 90 1
RV AAPL
RV AAPL MSFT GOOG META
EQS COUNTRY=US MARKETCAP>10B PE<25 ROIC>15
IS AAPL
BS MSFT
CF SAN.MC
FILINGS AAPL
10K AAPL
10Q AAPL
XLS AAPL
DES NVDA 5Y
CHART MSFT 1Y 1D
CHART EURJPY 5D 15M
GP SPX 6M 1D
INDEX SPX 1Y
CMDTY BRENT 6M
COMP AAPL MSFT
OMON AAPL
OMON AAPL 2026-12-18
OVME AAPL C 350 2026-12-18
OVDV AAPL
VS MSFT
VOL3D NVDA
RISK AAPL
WATCH
WATCH ADD EURUSD
WATCH REMOVE AAPL
WATC
WATC NEW EUROPE
WATC ADD SAN.MC EUROPE
PORT
PORT ADD AAPL 10 185 USD
PORT MAIN RISK SPY 1Y
PORT MAIN ACTIONS
ALRT
ALRT ADD AAPL PRICE > 250
ALRT ADD FUNDAMENTAL AAPL PE < 20
ALRT ADD FILING AAPL FILING_ANY
ALRT ADD NEWS AAPL NEWS
ALRT ADD EVENT AAPL EVENT_EARNINGS <= 14
ALRT ADD RISK MAIN VAR_95_PCT > 3%
AAPL FLDS REVENUE
DQM
DQM PROBE
DQM AAPL
WSP
UPD
DIAG
DOOM
TAB NEW
TAB NEW AAPL DES
TAB CLOSE
TAB WINDOW
WALL
WALL CONFIG
WALL ON
WALL OFF
WALL RESET
```

Workspace tabs are also available from the `+` control. `Ctrl+T` opens a tab,
`Ctrl+W` closes it, `Ctrl+PgUp` / `Ctrl+PgDown` cycle tabs and `Ctrl+Shift+D`
opens the active workspace as an independent terminal window on the next display.
Double-clicking a tab performs the same multi-window action. Open tab commands
and the active tab are restored with the next signed-in session.

`WALL` opens the global market overview. On a multi-monitor desk it automatically
uses the selected secondary display at sign-in; a one-monitor setup keeps the
overview closed until it is opened manually. `WALL CONFIG` or `TOOLS > WALL
CONFIG` selects the display and assigns any valid THRIVEBERG command to each
quadrant. `WALL ON` and `WALL OFF` control automatic startup, while `WALL RESET`
restores the `EURUSD`, `WEI`, `GOVT` and `NEWS MARKETS` default composition.

`NEWS` opens the top-stories wire. Use `NEWS <ticker>` for instrument headlines or
`NEWS MARKETS`, `NEWS ECONOMY`, `NEWS CENTRAL BANKS`, `NEWS COMPANIES`, `NEWS TECH`
and `NEWS POLITICS` for sections. Arrow keys or `J`/`K` move through stories,
`Enter` or `O` opens the original source, `R` refreshes and `/` focuses the command
line. Every story remains labeled `DELAYED`, `CACHED`, `MOCK` or `UNAVAILABLE`.

`FILINGS <ticker>` loads the official/regulatory filing index for the listing jurisdiction. `10K <ticker>`
and `10Q <ticker>` filter US filings, while `OPEN SEC`, `OPEN REPORT` or `OPEN PORTAL`
opens the corresponding primary source. Non-US local listings retain the annual,
interim or quarterly terminology used by their jurisdiction and are never mislabeled
as SEC 10-K/10-Q forms.

`MAP` opens the native 3D global economic globe. Drag to rotate, use the wheel to
zoom and click a country to load its detail panel. Its modes are `GDP`, `CPI`, `UNEMP`,
`RATE`, `10Y` and `EQUITY`; filters are `WORLD`, `AMERICAS`, `EUROPE`, `ASIA`,
`EM` and `DM`. Search by country name, ISO2 or ISO3, or click a country on the
map. The country panel preserves each observation's real period and source and
uses `N/A` when a provider has no verified value. Macro series come from the
World Bank and FRED/central-bank series; sovereign data uses US Treasury or
FRED/OECD mappings, and market returns use Yahoo Finance with their delayed
status retained. Keys `G`, `C`, `U`, `R`, `Y` and `E` switch map metric while the
map has focus. Panel shortcuts open `ECO`, `RATES`, `INDEX`, `FX`, `NEWS` and
`CAL` for the selected country.

`XLS <ticker>` exports annual and quarterly income statements, balance sheets and
cash-flow statements to `Downloads/THRIVEBERG Exports/`. The workbook contains numeric cells, source
metadata and separate sheets for each statement/frequency. For US issuers, every
period includes its SEC form, filing date and accession number. Standalone cash-flow
quarters derived from reported YTD/FY totals are explicitly marked `DERIVED`.
Currency and share values are scaled to millions while EPS remains unscaled. Mock
or unavailable statements are never exported.

`GOVT` shows 17 provider-backed global 10-year benchmarks without substituting mock
yields. It identifies daily and monthly observations explicitly, calculates
latest-available UST spreads, and retains source, timestamp and methodology in
each row's detail. `CORP` combines delayed ICE BofA index data distributed by FRED with a
reference directory of SEC-filed cash-bond terms. Individual cash-bond prices are
shown as `--` until a TRACE-capable market-data feed is configured; enter a clean
price explicitly with `BOND <symbol> PRICE <price>` to calculate yield and risk.

`GP` and `CHART` open the native price workstation. With `AUTO 30S` enabled it polls
the configured provider every 30 seconds and updates the latest candle,
volume and studies incrementally. This is automatic market-data refresh, not a
guaranteed exchange tick stream: Yahoo-backed views remain explicitly labeled
`DELAYED`. A licensed streaming/WebSocket provider can later use the same update
path without replacing the chart renderer.

For free US-equity streaming, create a personal Finnhub key at
`https://finnhub.io/register`, then run `.\configure_live_feed.ps1`. The assistant
validates the key and stores it with Windows DPAPI; `TOOLS > DATA CONNECTIONS`
provides the same configuration from the application. THRIVEBERG then keeps
Yahoo as the historical source, subscribes to Finnhub's official trade WebSocket
and folds incoming trades into the active candle at a maximum UI rate of 2 Hz.
The free key permits one simultaneous WebSocket connection; unsupported symbols
and entitlement errors fall back automatically to the 30-second delayed refresh.

`OVDV`, `VS`, `VOLSURF` and `VOL3D` open the PyVista/VTK options workstation.
The surface uses real listed option-chain observations, cleans unusable IVs and
interpolates only inside supported strike and expiry regions. Rotation, pan,
zoom, tracking, camera presets, skew, term structure and the surface table remain
interactive while the terminal stays open.

The interface follows Bloomberg's dense screen grammar: a persistent security
line, contextual function tabs, yellow table headings, regional market sections
and compact value columns. `FXC` aliases the G10 matrix, while `BTMM` and `WB`
route to the sovereign-rates workspace. Existing THRIVEBERG commands remain valid.

Hotkeys:

```text
/ command palette
ESC back
CTRL+R refresh
CTRL+K search
ALT+LEFT previous screen
ALT+RIGHT next screen
PGUP / PGDN scroll instrument details
F2 markets
F3 FX
F4 government bonds
F5 equity
F6 macro
F7 news
F8 chart for the current instrument
F9 social
F10 options for the current equity
ALT+1 equity overview
ALT+2 financial analysis
ALT+3 income statement
ALT+4 balance sheet
ALT+5 cash flow
ALT+6 estimates
ALT+7 relative valuation
ALT+8 equity news
```

`GP` and `CHART` render a complete chart workstation inside the terminal's center
panel. It includes candles, line and OHLC modes; volume, SMA, EMA and VWAP overlays;
asset-specific quick analytics; instrument events and headlines; eight ranges from
`1D` to `5Y`; and intervals from `1m` to `1W`. Windows Terminal 1.22+ uses Sixel for
a full-resolution image; other terminals use a compatible in-terminal renderer.

Chart keyboard controls are `1`-`8` for ranges, `C`/`L`/`O` for chart type,
`V`/`S`/`E`/`W` for volume, SMA, EMA and VWAP, `T`/`H` for trend and horizontal
lines, `X` to clear drawings, `N` for news, `R` to refresh and `0` to reset the
view. Trend lines use two chart clicks; horizontal lines use one.

`OMON <ticker>` opens the listed call/put chain with expiry navigation, bid/ask,
last, volume, open interest, calculated Black-Scholes IV and delta. `OVME` is an
editable European Black-Scholes pricer with market-price IV solving and first- and
second-order Greeks. `OVDV` uses a Bloomberg-style three-panel volatility view:
the selected skew or 3D surface on the left, volatility-versus-term at top right,
and the selected expiry's moneyness cut below it. Numbered Bloomberg-style tabs
switch between the volatility table, interactive 3D surface, term structure and
skew comparison. In `SKEW`, click to track a
moneyness, drag horizontally to pan, use the wheel to zoom and move between terms
with the term controls. In `3D SURFACE`, drag to rotate and use the wheel to zoom;
`R` resets the active view. Option quotes come from Yahoo Finance and retain
their delayed/cached/unavailable label; failed requests may use the last real cache
entry, never a generated chain. Surface grids interpolate only between observed
strikes and are labeled as derived.

## Architecture

```text
ajax_terminal/
  ui/          Textual screens, widgets, theme, command parser
  providers/   Public/API provider implementations and fallback contracts
  analytics/   Forwards, fixed income, options, volatility, risk
  models/      Typed market, macro, news, instrument models
  services/    Application services that combine providers, cache, and normalization
  storage/     SQLite database, TTL cache, watchlists
  utils/       Dates, symbols, formatting helpers
tests/         Focused analytics and parser tests
```

## Provider Strategy

The terminal is provider-neutral:

```text
Primary provider
  -> secondary provider
  -> cached data
  -> unavailable (research functions)
  -> clearly labeled mock data (general market shell only)
```

Each displayed data block includes provider, timestamp, and quality (`REALTIME`, `DELAYED`, `CACHED`, `MOCK`, or `UNAVAILABLE`) where relevant.
Yahoo research requests use an authenticated public session. Sovereign 10-year
benchmarks outside the US fall back to delayed FRED/OECD monthly series when Yahoo
does not carry the symbol. Research functions never substitute generated mock values.

Registered market instruments are defined only in `ajax_terminal/instruments/registry.py`. Equities intentionally use dynamic provider resolution instead of a closed symbol list.

## Roadmap

Development advances one validated beta milestone at a time:

1. Data quality, provider health, cache coverage, source comparison and field provenance. Completed in the Beta 013 development cycle.
2. Professional portfolio accounting, performance attribution and broker CSV imports. Completed in the Beta 014 development cycle.
3. Portfolio risk, factor exposure, correlation and stress scenarios. Completed in the Beta 015 development cycle.
4. Corporate actions and automatic position/history adjustments. Completed in the Beta 016 development cycle.
5. Background alerts for prices, fundamentals, filings, news, events and portfolio risk. Completed in the Beta 017 development cycle.
6. Signed incremental updates, diagnostics and encrypted configuration migration. Completed in the Beta 018 development cycle.
7. Estimate revisions, earnings surprises, guidance and filing comparison.
8. Multi-leg options, American/binomial valuation and aggregate Greeks.
9. Fixed-income cash flows, spread analytics and bootstrapped curves.
10. Ranked screening, synchronized chart workspaces, research notes and backtesting.
11. Paper trading, macOS packaging and optional broker connectivity after the security boundary is reviewed.

## Financial Data Disclaimer

THRIVEBERG Terminal is for research and software development. Data may be delayed, incomplete, cached, mocked, or unavailable. It is not investment advice, not a trading system, and not a substitute for licensed market data.

## License

[MIT](LICENSE)
