# Bloomberg Visual Audit

This inventory keeps every THRIVEBERG command attached to an explicit Bloomberg-style
visual family. `tests/test_visual_command_inventory.py` fails when a new command
is introduced without a reviewed screen family.

## 2026-10-03 Global Overview Pass

- `WALL` creates one frameless 2 x 2 market wall on the selected display instead
  of scattering four independent operating-system windows across the desktop.
- The default desk combines an intraday `EURUSD` price chart, `WEI` world equity
  breadth, `GOVT` sovereign benchmarks and `NEWS MARKETS` world headlines. Each
  pane runs the existing production workspace and retains its provider and data-
  quality labels.
- Compact panes preserve the Bloomberg-style function and instrument bands while
  removing duplicated application chrome, command bars and footers.
- Double-clicking a pane header expands that function to the full wall; a second
  double-click restores all four quadrants without reloading the other views.
- The selected display, automatic startup and four commands are persisted per
  signed-in Windows profile. Invalid recursive commands are replaced with the
  reviewed defaults.
- Visual validation covered the complete 1920 x 1080 wall with live public data;
  all labels, controls and tables remained readable with no overlapping panels.

## 2026-10-03 Tabbed Workspace Pass

- `TERMINAL` now contains a compact document-tab strip. Every tab retains its
  own security context, command history, live widget, engine status and pop-out
  state instead of destroying the previous function when navigation changes.
- Tabs are movable and individually closable. The amber active state, gray
  inactive state and square controls follow the existing terminal grammar and
  were checked at 1920 x 1080 with three simultaneous equity workspaces.
- Slow asynchronous loads are bound to the tab that started them, so completing
  `OVDV`, `FA` or another data request cannot overwrite a different active tab.
- `Ctrl+T`, `Ctrl+W`, `Ctrl+PgUp`, `Ctrl+PgDown` and `Ctrl+Shift+D` cover the
  keyboard workflow. `TAB NEW`, `TAB CLOSE` and `TAB WINDOW` expose the same
  operations through the command line.
- A tab can open as a complete independent terminal window on the next available
  display. Secondary windows keep normal navigation and can create their own tabs.
- Open tab commands and the active tab are persisted for authenticated sessions.

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

## 2026-10-02 Background Alerts Pass

- `ALRT` is now a flat two-view workstation: active rules and a persistent
  trigger ledger. Both use fixed columns rather than space-aligned text.
- The rule editor changes signal, operator and threshold controls by domain for
  market, fundamental, filing, news, event and portfolio-risk alerts.
- Background status is visible in the system bar while the user works elsewhere;
  new triggers also use the native system notification channel when available.
- Source, data quality, last check, last trigger, hit count and control error are
  visible for every rule. Trigger history retains document links and requires a
  double click to leave the terminal.
- Visual validation covered six real-provider rules at 1920 x 1080, including
  Finnhub realtime prices, SEC filings, Yahoo fundamentals/events, RSS news and
  calculated portfolio risk.

## 2026-10-02 Trusted Update And Diagnostics Pass

- `UPD` is now a native trusted-release workstation with separate signed
  installer and legacy-build identities, explicit integrity states and no
  ambiguous `VERIFIED` label for unsigned local executables.
- Online update controls are disabled and relabelled when no newer signed beta
  exists. A valid release shows beta, size, signed SHA-256 and release notes.
- `DIAG` uses the same flat strip, section heading and fixed-column table as the
  rest of the terminal. PASS, WARN and FAIL retain terminal green, amber and red.
- Support export wording states exactly what leaves the machine; portfolios,
  database contents and credential values are excluded.
- Both workspaces were visually checked at 1920 x 1080 with no overlap,
  clipping or nested-card styling.

## 2026-10-02 Embedded DOOM Pass

- `DOOM` opens Freedoom Phase 1 in a native Chocolate Doom viewport inside the
  terminal workspace; it does not open a second terminal tab or an unmanaged
  game process.
- The game viewport preserves the terminal system bar, function strip,
  instrument strip and footer. Its own controls use the existing flat terminal
  treatment and amber/cyan/white hierarchy.
- `POP OUT` detaches the same running game window and `DOCK` returns it to its
  original viewport. Navigation, restart and application shutdown terminate the
  child process with a bounded fallback and leave no residual process.
- The 1920x1080 source-build capture was reviewed with 1,199 distinct sampled
  viewport colors; the native game frame is present, correctly scaled and not
  blank.
- Only Freedoom Phase 1 is bundled. No proprietary id Software IWAD is present;
  engine source, primary licenses, campaign credits and the Spanish manual ship
  with the application.

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
| ALERTS | ALRT | Event-driven monitoring | Reviewed; background rules and persistent trigger ledger |
| DATA_QUALITY | DQM / data diagnostics | Support | Reviewed; native four-view monitor |
| WORKSPACES | WSP | Workspace manager | Support | Reviewed |
| UPDATES | UPD | Release manager | Support | Reviewed; signed online channel and revalidated cache |
| DIAGNOSTICS | DIAG | System diagnostics | Support | Reviewed; sanitized support export |
| DOOM | DOOM | Embedded classic game | Support | Reviewed; native dock/pop-out and verified free-content runtime |
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
