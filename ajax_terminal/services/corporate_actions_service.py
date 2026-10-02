from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from ajax_terminal.models.equity import CorporateAction, CorporateActionType
from ajax_terminal.models.quote import DataQuality, PriceHistory
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.workstation import (
    PortfolioCashFlow,
    PortfolioCorporateAction,
    PortfolioPosition,
    PortfolioStore,
    PortfolioTransaction,
)


@dataclass(frozen=True, slots=True)
class CorporateActionCandidate:
    action: CorporateAction
    eligible_quantity: float
    status: str
    cash_amount: float = 0.0
    fx_rate: float | None = None
    base_value: float | None = None
    position_delta: float = 0.0
    notes: str = ""

    @property
    def eligible(self) -> bool:
        return self.status == "ELIGIBLE"


@dataclass(frozen=True, slots=True)
class PortfolioCorporateActionsLoad:
    portfolio: str
    base_currency: str
    candidates: tuple[CorporateActionCandidate, ...]
    discovered: int
    eligible: int
    applied: int
    review: int
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorporateActionApplyResult:
    applied: int
    skipped: int
    failed: int
    messages: tuple[str, ...] = ()


def load_portfolio_corporate_actions(
    store: PortfolioStore,
    name: str = "MAIN",
    *,
    market: MarketService | None = None,
    refresh: bool = False,
) -> PortfolioCorporateActionsLoad:
    portfolio = store.create(name)
    base_currency = store.base_currency(portfolio)
    positions = store.positions(portfolio)
    transactions = store.transactions(portfolio, limit=10_000)
    cash_flows = store.cash_flows(portfolio, limit=10_000)
    applied = store.corporate_actions(portfolio, limit=10_000)
    symbols = tuple(sorted(
        {item.symbol for item in positions}
        | {item.symbol for item in transactions if item.symbol}
    ))
    if not symbols:
        return PortfolioCorporateActionsLoad(
            portfolio, base_currency, (), 0, 0, len(applied), 0, ()
        )

    service = market or MarketService()

    async def load_market() -> tuple[dict[str, list[CorporateAction]], dict[str, tuple[PriceHistory | None, bool]]]:
        results = await asyncio.gather(
            *(service.corporate_actions(symbol, refresh=refresh) for symbol in symbols)
        )
        actions_by_symbol = {
            symbol: [item for item in actions if item.quality != DataQuality.MOCK]
            for symbol, actions in zip(symbols, results)
        }
        foreign_currencies = sorted({
            action.currency.upper()
            for actions in actions_by_symbol.values()
            for action in actions
            if action.action_type == CorporateActionType.DIVIDEND
            and action.currency
            and action.currency.upper() != base_currency.upper()
        })
        fx_results = await asyncio.gather(
            *(
                _load_fx_history(service, currency, base_currency)
                for currency in foreign_currencies
            )
        )
        return actions_by_symbol, dict(zip(foreign_currencies, fx_results))

    actions_by_symbol, fx_by_currency = asyncio.run(load_market())
    transactions_by_symbol = {
        symbol: tuple(item for item in transactions if item.symbol == symbol)
        for symbol in symbols
    }
    positions_by_symbol = {item.symbol: item for item in positions}
    applied_by_id = {item.action_id: item for item in applied}
    applied_ids = set(applied_by_id)
    candidates: list[CorporateActionCandidate] = []
    observed_ids: set[str] = set()
    relevant_observed_ids: set[str] = set()

    for symbol in symbols:
        symbol_actions = sorted(
            actions_by_symbol.get(symbol, []),
            key=lambda item: (item.effective_date, item.action_type, item.action_id),
        )
        symbol_transactions = transactions_by_symbol[symbol]
        first_trade = min(
            (date.fromisoformat(item.trade_date) for item in symbol_transactions),
            default=None,
        )
        position = positions_by_symbol.get(symbol)
        recorded_from = first_trade
        if recorded_from is None and position is not None and position.updated_at:
            try:
                recorded_from = date.fromisoformat(position.updated_at[:10])
            except ValueError:
                recorded_from = None
        position_matches = _position_matches_applied_history(
            position,
            symbol_transactions,
            tuple(item for item in applied if item.symbol == symbol and item.action_type == "SPLIT"),
        )
        for action in symbol_actions:
            observed_ids.add(action.action_id)
            existing = applied_by_id.get(action.action_id)
            if existing is not None:
                relevant_observed_ids.add(action.action_id)
                candidates.append(_applied_candidate(action, existing))
                continue
            if recorded_from is not None and action.effective_date < recorded_from:
                continue
            relevant_observed_ids.add(action.action_id)
            if first_trade is None:
                candidates.append(
                    CorporateActionCandidate(
                        action, 0.0, "REVIEW", notes="NO TRANSACTION HISTORY; ENTITLEMENT CANNOT BE VERIFIED"
                    )
                )
                continue
            if action.effective_date < first_trade:
                continue
            if action.effective_date > date.today():
                candidates.append(
                    CorporateActionCandidate(action, 0.0, "FUTURE", notes="NOT YET EFFECTIVE")
                )
                continue
            eligible_quantity = _quantity_before_action(
                symbol_transactions,
                symbol_actions,
                action.effective_date,
                action.action_id,
            )
            if eligible_quantity <= 1e-9:
                candidates.append(
                    CorporateActionCandidate(
                        action, 0.0, "NO ENTITLEMENT", notes="NO SHARES HELD BEFORE EFFECTIVE DATE"
                    )
                )
                continue
            if action.action_type == CorporateActionType.SPLIT:
                ratio = action.split_ratio
                if ratio is None or ratio <= 0 or math.isclose(ratio, 1.0, abs_tol=1e-12):
                    candidates.append(
                        CorporateActionCandidate(action, eligible_quantity, "REVIEW", notes="INVALID OR 1:1 SPLIT RATIO")
                    )
                    continue
                if not position_matches:
                    candidates.append(
                        CorporateActionCandidate(
                            action,
                            eligible_quantity,
                            "REVIEW",
                            position_delta=eligible_quantity * (ratio - 1.0),
                            notes="CURRENT POSITION DOES NOT RECONCILE TO LEDGER AND APPLIED SPLITS",
                        )
                    )
                    continue
                candidates.append(
                    CorporateActionCandidate(
                        action,
                        eligible_quantity,
                        "ELIGIBLE",
                        position_delta=eligible_quantity * (ratio - 1.0),
                        notes="LEDGER RESTATED; SPLIT PRESERVES BOOK VALUE AT EFFECTIVE DATE",
                    )
                )
                continue

            amount = float(action.amount or 0.0)
            cash_amount = eligible_quantity * amount
            if amount <= 0:
                candidates.append(
                    CorporateActionCandidate(action, eligible_quantity, "REVIEW", notes="INVALID DIVIDEND AMOUNT")
                )
                continue
            if _possible_dividend_duplicate(action, cash_flows):
                candidates.append(
                    CorporateActionCandidate(
                        action,
                        eligible_quantity,
                        "REVIEW",
                        cash_amount=cash_amount,
                        notes="POSSIBLE MANUAL DIVIDEND ON THE SAME SYMBOL AND DATE",
                    )
                )
                continue
            fx_rate = _action_fx_rate(action, base_currency, fx_by_currency)
            if fx_rate is None:
                candidates.append(
                    CorporateActionCandidate(
                        action,
                        eligible_quantity,
                        "REVIEW",
                        cash_amount=cash_amount,
                        notes=f"NO OBSERVED {action.currency}/{base_currency} FX CLOSE NEAR EX-DATE",
                    )
                )
                continue
            candidates.append(
                CorporateActionCandidate(
                    action,
                    eligible_quantity,
                    "ELIGIBLE",
                    cash_amount=cash_amount,
                    fx_rate=fx_rate,
                    base_value=cash_amount * fx_rate,
                    notes="OBSERVED DIVIDEND; BOOKED ON EX-DATE BECAUSE PAYMENT DATE IS UNAVAILABLE",
                )
            )

    for record in applied:
        if record.action_id in observed_ids:
            continue
        candidates.append(_ledger_only_candidate(record))

    candidates.sort(
        key=lambda item: (item.action.effective_date, item.action.symbol, item.action.action_id),
        reverse=True,
    )
    return PortfolioCorporateActionsLoad(
        portfolio=portfolio,
        base_currency=base_currency,
        candidates=tuple(candidates),
        discovered=len(relevant_observed_ids),
        eligible=sum(item.eligible for item in candidates),
        applied=sum(item.status == "APPLIED" for item in candidates),
        review=sum(item.status == "REVIEW" for item in candidates),
        symbols=symbols,
    )


def apply_eligible_corporate_actions(
    store: PortfolioStore,
    load: PortfolioCorporateActionsLoad,
) -> CorporateActionApplyResult:
    applied = 0
    skipped = 0
    messages: list[str] = []
    for candidate in sorted(
        load.candidates,
        key=lambda item: (item.action.effective_date, item.action.action_type, item.action.action_id),
    ):
        if not candidate.eligible:
            skipped += 1
            continue
        action = candidate.action
        try:
            store.apply_corporate_action(
                action_id=action.action_id,
                symbol=action.symbol,
                action_type=str(action.action_type),
                effective_date=action.effective_date,
                eligible_quantity=candidate.eligible_quantity,
                amount=action.amount,
                currency=action.currency,
                numerator=action.numerator,
                denominator=action.denominator,
                fx_rate=candidate.fx_rate or 1.0,
                provider=action.provider,
                quality=str(action.quality),
                name=load.portfolio,
                notes=candidate.notes,
            )
            applied += 1
        except (ValueError, RuntimeError) as exc:
            messages.append(f"{action.symbol} {action.effective_date}: {' '.join(str(exc).split())[:160]}")
    return CorporateActionApplyResult(
        applied=applied,
        skipped=skipped,
        failed=len(messages),
        messages=tuple(messages),
    )


def _quantity_before_action(
    transactions: Sequence[PortfolioTransaction],
    actions: Sequence[CorporateAction],
    effective_date: date,
    target_id: str,
) -> float:
    events: list[tuple[date, int, float]] = []
    for transaction in transactions:
        observed = date.fromisoformat(transaction.trade_date)
        if observed >= effective_date:
            continue
        signed = transaction.quantity if transaction.side == "BUY" else -transaction.quantity
        events.append((observed, 1, signed))
    for action in actions:
        ratio = action.split_ratio
        if (
            action.action_type == CorporateActionType.SPLIT
            and action.action_id != target_id
            and action.effective_date < effective_date
            and ratio is not None
            and ratio > 0
        ):
            events.append((action.effective_date, 0, ratio))
    quantity = 0.0
    for _observed, kind, value in sorted(events, key=lambda item: (item[0], item[1])):
        if kind == 0:
            quantity *= value
        else:
            quantity += value
    return max(quantity, 0.0)


def _position_matches_applied_history(
    position: PortfolioPosition | None,
    transactions: Sequence[PortfolioTransaction],
    splits: Sequence[PortfolioCorporateAction],
) -> bool:
    events: list[tuple[date, int, float]] = []
    for transaction in transactions:
        signed = transaction.quantity if transaction.side == "BUY" else -transaction.quantity
        events.append((date.fromisoformat(transaction.trade_date), 1, signed))
    for split in splits:
        if split.numerator is None or split.denominator in {None, 0}:
            continue
        events.append(
            (date.fromisoformat(split.effective_date), 0, split.numerator / split.denominator)
        )
    expected = 0.0
    for _observed, kind, value in sorted(events, key=lambda item: (item[0], item[1])):
        expected = expected * value if kind == 0 else expected + value
    actual = position.quantity if position is not None else 0.0
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7)


def _possible_dividend_duplicate(
    action: CorporateAction,
    cash_flows: Sequence[PortfolioCashFlow],
) -> bool:
    return any(
        item.kind == "DIVIDEND"
        and item.symbol == action.symbol
        and item.flow_date == action.effective_date.isoformat()
        and item.source != "CORPORATE ACTION"
        for item in cash_flows
    )


async def _load_fx_history(
    market: MarketService,
    currency: str,
    base_currency: str,
) -> tuple[PriceHistory | None, bool]:
    direct = await market.history(f"{currency}{base_currency}", "5Y", "1d", allow_mock=False)
    if direct.bars and direct.quality != DataQuality.MOCK:
        return direct, False
    inverse = await market.history(f"{base_currency}{currency}", "5Y", "1d", allow_mock=False)
    if inverse.bars and inverse.quality != DataQuality.MOCK:
        return inverse, True
    return None, False


def _action_fx_rate(
    action: CorporateAction,
    base_currency: str,
    fx_by_currency: dict[str, tuple[PriceHistory | None, bool]],
) -> float | None:
    currency = action.currency.upper()
    if not currency or currency == base_currency.upper():
        return 1.0
    history, inverse = fx_by_currency.get(currency, (None, False))
    if history is None:
        return None
    available = [
        (bar.timestamp.date(), float(bar.adjusted_close or bar.close))
        for bar in history.bars
        if bar.timestamp.date() <= action.effective_date and (bar.adjusted_close or bar.close) > 0
    ]
    if not available:
        return None
    observed, value = max(available, key=lambda item: item[0])
    if (action.effective_date - observed).days > 7:
        return None
    return 1.0 / value if inverse else value


def _applied_candidate(
    action: CorporateAction,
    record: PortfolioCorporateAction,
) -> CorporateActionCandidate:
    return CorporateActionCandidate(
        action=action,
        eligible_quantity=record.eligible_quantity,
        status="APPLIED",
        cash_amount=record.cash_amount,
        fx_rate=record.fx_rate,
        base_value=record.cash_amount * record.fx_rate if record.cash_amount else None,
        position_delta=record.position_delta,
        notes=f"APPLIED {record.applied_at}",
    )


def _ledger_only_candidate(record: PortfolioCorporateAction) -> CorporateActionCandidate:
    action = CorporateAction(
        action_id=record.action_id,
        symbol=record.symbol,
        action_type=CorporateActionType(record.action_type),
        effective_date=date.fromisoformat(record.effective_date),
        amount=record.amount,
        currency=record.currency,
        numerator=record.numerator,
        denominator=record.denominator,
        provider=record.provider,
        quality=DataQuality(record.quality),
    )
    return _applied_candidate(action, record)
