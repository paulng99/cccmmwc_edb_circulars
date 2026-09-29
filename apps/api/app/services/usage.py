"""Record and summarise token spend.

Classification is by feature (what the product was doing), then provider and model.
Circular programme is not a billing dimension: one OpenRouter call is not tied to one document.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models.entities import ApiUsage, User

logger = logging.getLogger(__name__)

HK = ZoneInfo("Asia/Hong_Kong")

# Search Foundation list rate (embeddings, reader, search). New keys include
# 10M free tokens; this estimate does not subtract that grant.
JINA_USD_PER_MILLION = Decimal("0.05")

FEATURES = (
    "chat",
    "classify",
    "source_suggest",
    "embed_index",
    "embed_query",
    "web_search",
)

_feature: ContextVar[str] = ContextVar("api_usage_feature", default="other")
_user_id: ContextVar[uuid.UUID | None] = ContextVar("api_usage_user", default=None)


@contextmanager
def usage_scope(feature: str) -> Iterator[None]:
    token = _feature.set(feature)
    try:
        yield
    finally:
        _feature.reset(token)


@contextmanager
def usage_user(user_id: uuid.UUID | None) -> Iterator[None]:
    token = _user_id.set(user_id)
    try:
        yield
    finally:
        _user_id.reset(token)


@contextmanager
def usage_user_ref(user_id: str | uuid.UUID | None) -> Iterator[None]:
    """Bind a user id passed across a Celery task boundary. Empty means a scheduled job."""
    parsed: uuid.UUID | None
    if isinstance(user_id, uuid.UUID):
        parsed = user_id
    elif user_id:
        try:
            parsed = uuid.UUID(str(user_id))
        except ValueError:
            parsed = None
    else:
        parsed = None
    with usage_user(parsed):
        yield


def hk_today() -> date:
    return datetime.now(HK).date()


def resolve_range(
    *,
    days: int | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    today = hk_today()
    if date_from or date_to:
        start = date_from or date_to or today
        end = date_to or today
        if start > end:
            start, end = end, start
        if (end - start).days > 366:
            start = end - timedelta(days=366)
        return start, end
    span = days if days and days > 0 else 30
    span = min(span, 366)
    return today - timedelta(days=span - 1), today


def hk_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=HK)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=HK)
    return start, end


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _money(value: Any) -> float:
    dec = value if isinstance(value, Decimal) else _dec(value) or Decimal(0)
    return float(dec.quantize(Decimal("0.00000001")))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def jina_cost(tokens: int) -> tuple[Decimal, str]:
    if tokens <= 0:
        return Decimal("0"), "unknown"
    cost = (Decimal(tokens) * JINA_USD_PER_MILLION / Decimal(1_000_000)).quantize(Decimal("0.00000001"))
    return cost, "estimate"


def parse_openrouter_usage(data: dict[str, Any], *, fallback_model: str) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt = _int(usage.get("prompt_tokens"))
    completion = _int(usage.get("completion_tokens"))
    total = _int(usage.get("total_tokens")) or (prompt + completion)
    cost = _dec(usage.get("cost"))
    source = "provider" if cost is not None else "unknown"
    if cost is None:
        details = usage.get("cost_details") if isinstance(usage.get("cost_details"), dict) else {}
        cost = _dec(details.get("upstream_inference_cost"))
        if cost is not None:
            source = "provider"
    return {
        "provider": "openrouter",
        "model": str(data.get("model") or fallback_model or ""),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_usd": cost or Decimal(0),
        "cost_source": source,
        "request_id": str(data["id"])[:128] if data.get("id") else None,
    }


def parse_ollama_usage(data: dict[str, Any], *, model: str) -> dict[str, Any]:
    prompt = _int(data.get("prompt_eval_count"))
    completion = _int(data.get("eval_count"))
    return {
        "provider": "ollama",
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost_usd": Decimal(0),
        "cost_source": "local",
        "request_id": None,
    }


def parse_jina_embed_usage(data: dict[str, Any], *, model: str) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt = _int(usage.get("prompt_tokens") or usage.get("total_tokens"))
    total = _int(usage.get("total_tokens")) or prompt
    cost, source = jina_cost(total)
    return {
        "provider": "jina",
        "model": str(data.get("model") or model or ""),
        "prompt_tokens": prompt or total,
        "completion_tokens": 0,
        "total_tokens": total,
        "cost_usd": cost,
        "cost_source": source,
        "request_id": None,
    }


def _tokens_from_obj(payload: Any, depth: int = 0) -> int | None:
    if depth > 3 or not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        for key in ("total_tokens", "tokens", "prompt_tokens"):
            if usage.get(key) is not None:
                return _int(usage.get(key))
    for key in ("data", "meta"):
        found = _tokens_from_obj(payload.get(key), depth + 1)
        if found:
            return found
    return None


def parse_jina_reader_usage(body: str, headers: Any, *, model: str = "jina-search") -> dict[str, Any]:
    tokens: int | None = None
    try:
        tokens = _tokens_from_obj(json.loads(body))
    except Exception:
        tokens = None
    if not tokens and headers is not None:
        for key in ("x-usage-tokens", "x-tokens", "x-token-usage"):
            raw = headers.get(key) if hasattr(headers, "get") else None
            if raw:
                tokens = _int(raw)
                break
    total = tokens or 0
    cost, source = jina_cost(total)
    return {
        "provider": "jina",
        "model": model,
        "prompt_tokens": total,
        "completion_tokens": 0,
        "total_tokens": total,
        "cost_usd": cost,
        "cost_source": source,
        "request_id": None,
    }


async def record_usage(fields: dict[str, Any]) -> None:
    feature = _feature.get() or "other"
    if feature not in FEATURES and feature != "other":
        feature = "other"
    try:
        async with SessionLocal() as session:
            session.add(
                ApiUsage(
                    provider=str(fields.get("provider") or "unknown")[:32],
                    feature=feature[:32],
                    model=str(fields.get("model") or "")[:128],
                    prompt_tokens=_int(fields.get("prompt_tokens")),
                    completion_tokens=_int(fields.get("completion_tokens")),
                    total_tokens=_int(fields.get("total_tokens")),
                    cost_usd=fields.get("cost_usd") or 0,
                    cost_source=str(fields.get("cost_source") or "unknown")[:16],
                    user_id=_user_id.get(),
                    request_id=fields.get("request_id"),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("failed to record api usage")


def _bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def _row_bucket(row: Any, **extra: Any) -> dict[str, Any]:
    item = _bucket()
    item.update(extra)
    item["calls"] = _int(row.calls)
    item["prompt_tokens"] = _int(row.prompt_tokens)
    item["completion_tokens"] = _int(row.completion_tokens)
    item["total_tokens"] = _int(row.total_tokens)
    item["cost_usd"] = _money(row.cost_usd)
    return item


def _fill_days(date_from: date, date_to: date, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date = {row["date"]: row for row in rows}
    out: list[dict[str, Any]] = []
    cursor = date_from
    while cursor <= date_to:
        key = cursor.isoformat()
        out.append(by_date.get(key) or {"date": key, **_bucket()})
        cursor += timedelta(days=1)
    return out


async def usage_report(
    session: AsyncSession,
    *,
    days: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start_date, end_date = resolve_range(days=days, date_from=date_from, date_to=date_to)
    start, end = hk_bounds(start_date, end_date)
    filt = (ApiUsage.created_at >= start) & (ApiUsage.created_at < end)

    def sums():
        return (
            func.count().label("calls"),
            func.coalesce(func.sum(ApiUsage.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(ApiUsage.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(ApiUsage.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(ApiUsage.cost_usd), 0).label("cost_usd"),
        )
    estimate_sum = func.coalesce(
        func.sum(case((ApiUsage.cost_source == "estimate", ApiUsage.cost_usd), else_=0)),
        0,
    )
    provider_sum = func.coalesce(
        func.sum(case((ApiUsage.cost_source == "provider", ApiUsage.cost_usd), else_=0)),
        0,
    )

    totals_row = (
        await session.execute(
            select(*sums(), estimate_sum.label("estimated_cost_usd"), provider_sum.label("provider_cost_usd")).where(filt)
        )
    ).one()

    feature_rows = (await session.execute(select(ApiUsage.feature, *sums()).where(filt).group_by(ApiUsage.feature))).all()
    by_feature_map = {row.feature: _row_bucket(row, feature=row.feature) for row in feature_rows}
    by_feature = [by_feature_map.get(name) or {"feature": name, **_bucket()} for name in FEATURES]
    for name, row in by_feature_map.items():
        if name not in FEATURES:
            by_feature.append(row)

    provider_rows = (
        await session.execute(
            select(ApiUsage.provider, *sums())
            .where(filt)
            .group_by(ApiUsage.provider)
            .order_by(func.sum(ApiUsage.cost_usd).desc())
        )
    ).all()
    model_rows = (
        await session.execute(
            select(ApiUsage.provider, ApiUsage.model, *sums())
            .where(filt)
            .group_by(ApiUsage.provider, ApiUsage.model)
            .order_by(func.sum(ApiUsage.cost_usd).desc())
        )
    ).all()

    user_rows = (
        await session.execute(
            select(ApiUsage.user_id, User.username, *sums())
            .outerjoin(User, User.id == ApiUsage.user_id)
            .where(filt)
            .group_by(ApiUsage.user_id, User.username)
            .order_by(func.sum(ApiUsage.cost_usd).desc(), func.sum(ApiUsage.total_tokens).desc())
        )
    ).all()
    user_feature_rows = (
        await session.execute(
            select(ApiUsage.user_id, ApiUsage.feature, *sums())
            .where(filt)
            .group_by(ApiUsage.user_id, ApiUsage.feature)
        )
    ).all()
    features_by_user: dict[str | None, list[dict[str, Any]]] = {}
    for row in user_feature_rows:
        key = str(row.user_id) if row.user_id else None
        features_by_user.setdefault(key, []).append(_row_bucket(row, feature=row.feature))
    for items in features_by_user.values():
        items.sort(key=lambda item: (-item["cost_usd"], -item["total_tokens"]))
    by_user = [
        _row_bucket(
            row,
            user_id=str(row.user_id) if row.user_id else None,
            username=row.username,
            by_feature=features_by_user.get(str(row.user_id) if row.user_id else None, []),
        )
        for row in user_rows
    ]

    hk_day = cast(func.timezone("Asia/Hong_Kong", ApiUsage.created_at), Date)
    day_rows = (
        await session.execute(
            select(
                hk_day.label("day"),
                func.count().label("calls"),
                func.coalesce(func.sum(ApiUsage.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(ApiUsage.cost_usd), 0).label("cost_usd"),
                func.coalesce(func.sum(ApiUsage.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(ApiUsage.completion_tokens), 0).label("completion_tokens"),
            )
            .where(filt)
            .group_by(hk_day)
            .order_by(hk_day)
        )
    ).all()
    by_day = _fill_days(
        start_date,
        end_date,
        [
            {
                "date": row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day),
                "calls": _int(row.calls),
                "prompt_tokens": _int(row.prompt_tokens),
                "completion_tokens": _int(row.completion_tokens),
                "total_tokens": _int(row.total_tokens),
                "cost_usd": _money(row.cost_usd),
            }
            for row in day_rows
        ],
    )

    recent_rows = (
        await session.execute(
            select(ApiUsage, User.username)
            .outerjoin(User, User.id == ApiUsage.user_id)
            .where(filt)
            .order_by(ApiUsage.created_at.desc())
            .limit(40)
        )
    ).all()

    totals = _row_bucket(totals_row)
    totals["estimated_cost_usd"] = _money(totals_row.estimated_cost_usd)
    totals["provider_cost_usd"] = _money(totals_row.provider_cost_usd)

    return {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timezone": "Asia/Hong_Kong",
        "currency": "USD",
        "jina_usd_per_million": float(JINA_USD_PER_MILLION),
        "totals": totals,
        "by_feature": by_feature,
        "by_user": by_user,
        "by_provider": [_row_bucket(row, provider=row.provider) for row in provider_rows],
        "by_model": [_row_bucket(row, provider=row.provider, model=row.model) for row in model_rows],
        "by_day": by_day,
        "recent": [
            {
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "user_id": str(row.user_id) if row.user_id else None,
                "username": username,
                "provider": row.provider,
                "feature": row.feature,
                "model": row.model,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "cost_usd": _money(row.cost_usd),
                "cost_source": row.cost_source,
            }
            for row, username in recent_rows
        ],
    }
