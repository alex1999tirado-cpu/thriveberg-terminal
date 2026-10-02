# Bloomberg Visual Audit

This inventory keeps every THRIVEBERG command attached to an explicit Bloomberg-style
visual family. `tests/test_visual_command_inventory.py` fails when a new command
is introduced without a reviewed screen family.

## 2026-10-02 Data Quality Pass

- `DQM` adds a native four-view data-quality workstation for provider health,
  cache inventory, domain coverage and cross-source quote comparison.
- Provider probes run in parallel and retain latency plus success/failure history;
  disabled credentials remain distinct from provider failures.
- Cross-source values are marked `ALIGNED`, `DIVERGENT` or `SINGLE SOURCE`, and
  double-clicking a comparison drills into the existing `FLDS` provenance view.
- The screen follows the shared terminal grammar: flat numbered tabs, real table
  columns, amber actions and values, cyan section labels, and explicit status colors.

## 2026-10-02 Portfolio Accounting Pass

- `PORT` now uses five native views for holdings, attribution, transactions, the
  cash ledger and a broker-import preview. Every dataset uses real columns and
  preserves the dense full-width terminal layout.
- Holdings expose native and base-currency values, weighted cost, live price,
  FX conversion, P&L, weight, provider and data quality. NAV reconciles with net
  external flows and total P&L, including cash taxes and fees.
- Transaction and cash-entry controls reject invalid operations visibly. A
  ledger-managed position cannot be deleted outside its transaction history.
- Broker rows are color-coded `READY` or `ERROR` before any write occurs, and
  applying the same export twice does not duplicate transactions.
- Visual validation covered all five tabs at 1920 x 1080 with mixed USD/EUR
  positions, realized P&L, dividends, taxes and multiple data providers.

## 2026-10-02 Portfolio Risk Pass

- `PORT` adds four flat native views for risk contribution, factor exposure,
  pairwise correlation and stress scenarios, bringing the workspace to nine
  functional tabs without introducing a separate visual language.
- The risk summary uses two metric blocks per row so VaR, expected shortfall,
  drawdown, Sharpe, beta, alpha and model fit remain visible together at
  1920 x 1080.
- Coverage, observation count, period, provider and data quality remain visible.
  Missing or mock history is rejected rather than silently estimated.
- Scenario rows distinguish observed historical replay from `ESTIMATED*`
  factor, currency and concentration shocks and state the method beside each
  result.
- Visual validation covered all four views using three live-listed positions,
  including historical EUR/USD conversion for a European security.

## 2026-10-02 Corporate Actions Pass

- `PORT` adds a tenth flat native view for observed dividends and splits, with
  explicit entitlement, event terms, native/base values, position delta, source,
  quality, control status and methodology columns.
- `SYNC OBSERVED` never mutates the ledger. `APPLY ELIGIBLE` writes only reviewed
  candidates and disables itself when no eligible event remains.
- Dividend application is idempotent and uses an observed event-date FX close.
  Same-day manual dividends are held for review instead of being duplicated.
- Split application restates the dated transaction ledger, current quantity,
  average native/base cost and later realized P&L. Unreconciled positions remain
  in `REVIEW` and are not changed.
- Visual validation covered preview and applied states at 1920 x 1080 with real
  Yahoo Finance dividend events and an isolated portfolio database.

## 2026-09-28 Quality Pass

- `HOME` now opens the working multi-asset monitor after login instead of an
  instructional placeholder.
- `RV`, `EE`, `ANR`, `DVD`, `EVT`, `FILINGS`, `10K`, `10Q` and `EQS` now use native
  Qt tables with real columns, fixed headers, row selection and horizontal/vertical
  scrolling. They no longer rely on spaces inside an SVG text snapshot.
- `RV` exposes automatic/manual peer sets, company names, mean/median rows and
  drill-down to `DES`. Automatic candidates are validated against the target's
  provider sector and industry; the KRI.AT check excludes Motor Oil and returns
  packaged-food peers.
- `FX` and `FWD` without a ticker remain global functions. They no longer inherit
  the active equity and produce invalid commands such as `AAPL FX`.
- `EQUITY` routes to the native `DES` workspace; `COMP` routes to native `RV`.
- All remaining Rich tables use visible column rules, and the native DES/financial
  tables use the same subtle grid and cell padding.
- Visual captures covered HOME, WEI, FX, FWD, GOVT, ECO, NEWS, DES, RV, EE, ANR,
  DVD, FILINGS, EQS, OMON, HELP, GP and OVDV. The full automated suite passed.

## Shared Rules

- Red function bar, orange active security/editable fields, flat gray numbered tabs.
- Yellow section headings, cyan labels/links, white data, green/red market movement.
- Dense full-width layouts, square corners, minimal borders and no nested cards.
- Security-first workflow: select the instrument, then run the function.
- Price charts use Lightweight Charts, analytical charts use ECharts and OVDV uses
  PyVista/VTK.

## Command Loop

| THRIVEBERG command | Bloomberg analogue | Visual family | Status |
| --- | --- | --- | --- |
| HOME | MAIN / monitors | Market monitor | Reviewed |
| WEI | WEI | Market monitor | Reviewed |
| INSTRUMENTS | SECF | Market monitor | Reviewed |
| WATCH | WATC | Market monitor | Reviewed |
| EQUITY | Equity menu | Security | Reviewed |
| INSTRUMENT | DES | Security | Reviewed |
| INDEX | DES index | Security | Reviewed |
| COMMODITY | DES commodity | Security | Reviewed |
| FX | FXC | Fixed income / FX | Reviewed |
| FWD | FX forward matrix | Fixed income / FX | Reviewed |
| CURVE | GC / yield curve | Fixed income / FX | Reviewed |
| RATES | Curve alias | Fixed income / FX | Reviewed |
| GOVERNMENT | GOVT / BTMM | Fixed income / FX | Reviewed |
| CORPORATE | CORP | Fixed income / FX | Reviewed |
| BOND | DES bond | Fixed income / FX | Reviewed |
| ECO | ECST / economics | Macro / news | Reviewed |
| CAL | ECO calendar | Macro / news | Reviewed |
| NEWS | TOP / CN | Macro / news | Reviewed; selection colors normalized |
| SOCIAL | MSG-style collaboration | Collaboration | Reviewed |
| INCOME_STATEMENT | IS | Fundamentals | Reviewed |
| BALANCE_SHEET | BS | Fundamentals | Reviewed |
| CASH_FLOW | CF | Fundamentals | Reviewed |
| FINANCIAL_ANALYSIS | FA | Fundamentals | Reviewed |
| RELATIVE_VALUATION | RV | Fundamentals | Reviewed |
| COMP | RV comparison | Fundamentals | Fixed; now routes to RV |
| ESTIMATES | EE | Fundamentals | Reviewed |
| ANALYST | ANR | Fundamentals | Reviewed |
| DIVIDENDS | DVD | Fundamentals | Reviewed |
| EVENTS | EVT | Fundamentals | Reviewed |
| FILINGS | DSCO / filings | Fundamentals | Reviewed |
| TEN_K | 10-K filing | Fundamentals | Reviewed |
| TEN_Q | 10-Q filing | Fundamentals | Reviewed |
| EXPORT | XLS | Fundamentals | Reviewed |
| SCREENER | EQS | Fundamentals | Reviewed |
| PORTFOLIO | PORT | Portfolio accounting / risk / corporate actions | Reviewed; ten-view native ledger, risk and corporate-action workstation |
| DATA_QUALITY | DQM / data diagnostics | Support | Reviewed; native four-view monitor |
| CHART | GP | Price chart | Rebuilt with Lightweight Charts |
| RISK | GP analytics view | Price chart | Fixed; now routes to live chart |
| OPTIONS | OMON | Derivatives | Reviewed |
| OPTION_VALUATION | OVME | Derivatives | Reviewed |
| VOL | OVDV | Derivatives | Rebuilt with PyVista and ECharts |
| HELP | HELP | Support | Reviewed |
| SEARCH | SECF search | Support | Reviewed |
| UNKNOWN | Command feedback | Support | Reviewed |

## Reference Priority

1. User-supplied screenshots, especially OVDV.
2. Bloomberg newsroom quick-start guide.
3. Bloomberg Terminal Essentials and official student guide.
4. Bloomberg function and university terminal guides.

This is a behavioral and layout reference. THRIVEBERG keeps its own identity and does
not reproduce Bloomberg logos or protected branding.
