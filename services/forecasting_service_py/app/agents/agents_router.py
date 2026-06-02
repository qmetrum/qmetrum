"""FastAPI router exposing agent endpoints under /agents."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import Portfolio, Position, AlertRule, AlertEvent
from app.agents import (
    portfolio_commentary,
    scenario_translator,
    scenario_summary,
    news_synthesizer,
    alert_explainer,
    client_qa,
)


agents_router = APIRouter()


def _require_user_like(session: Session, user_id: Optional[int], x_user_id: Optional[int]):
    # Thin shim that mirrors main._require_user without importing main (avoid
    # circular imports). In production (Cognito configured) we accept only the
    # X-User-Id that CognitoAuthMiddleware injected from a verified JWT claim.
    from app.auth.cognito import is_cognito_configured
    from app.db.models import User

    if is_cognito_configured():
        if x_user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        uid = int(x_user_id)
    else:
        uid = user_id if user_id is not None else x_user_id
        if uid is None:
            uid = 1
    user = session.exec(select(User).where(User.id == uid)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


class CommentaryRequest(BaseModel):
    metrics: dict[str, Any] = {}
    regime: str = "Normal"
    horizon_days: int = 90
    snapshot_hash: Optional[str] = None


class CommentaryResponse(BaseModel):
    commentary: str
    cached: bool
    model: str
    prompt_tokens: int
    output_tokens: int
    latency_ms: int
    source_data: dict[str, Any]


@agents_router.post("/commentary/{portfolio_id}", response_model=CommentaryResponse)
def portfolio_commentary_endpoint(
    portfolio_id: int,
    payload: CommentaryRequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user_like(session, user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio)
            .where(Portfolio.id == portfolio_id)
            .where(Portfolio.user_id == user.id)
        ).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        positions = session.exec(
            select(Position).where(Position.portfolio_id == portfolio_id)
        ).all()
        holdings = [
            {"ticker": p.ticker, "weight": p.weight, "quantity": p.quantity}
            for p in positions
        ]

    try:
        text, result = portfolio_commentary.run(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.name or f"Portfolio #{portfolio_id}",
            holdings=holdings,
            metrics=payload.metrics,
            regime=payload.regime,
            horizon_days=payload.horizon_days,
            snapshot_hash=payload.snapshot_hash,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"commentary agent failed: {exc}")

    return CommentaryResponse(
        commentary=text,
        cached=result.cached,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        source_data={
            "portfolio": portfolio.name or f"Portfolio #{portfolio_id}",
            "holdings": holdings,
            "metrics": payload.metrics,
            "regime": payload.regime,
            "horizon_days": payload.horizon_days,
        },
    )


class ScenarioTranslateRequest(BaseModel):
    description: str


class ScenarioTranslateResponse(BaseModel):
    name: str
    shock_pct: float
    vol_scale: float
    drift_shift: float
    cached: bool
    latency_ms: int


@agents_router.post("/scenario-translate", response_model=ScenarioTranslateResponse)
def scenario_translate_endpoint(payload: ScenarioTranslateRequest):
    desc = (payload.description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")
    if len(desc) > 1000:
        raise HTTPException(status_code=400, detail="description is too long (max 1000 chars)")
    try:
        params, result = scenario_translator.run(desc)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scenario translator failed: {exc}")
    return ScenarioTranslateResponse(
        name=params.name,
        shock_pct=params.shock_pct,
        vol_scale=params.vol_scale,
        drift_shift=params.drift_shift,
        cached=result.cached,
        latency_ms=result.latency_ms,
    )


class ScenarioRunItem(BaseModel):
    name: str
    shock_pct: float = 0.0
    vol_scale: float = 1.0
    drift_shift: float = 0.0
    return_pct: float
    dollar_impact: float


class ScenarioSummaryRequest(BaseModel):
    portfolio_name: str
    portfolio_value: float
    scenarios: list[ScenarioRunItem]


class ScenarioSummaryResponse(BaseModel):
    summary: str
    cached: bool
    latency_ms: int
    source_data: dict[str, Any]


@agents_router.post("/scenario-summary", response_model=ScenarioSummaryResponse)
def scenario_summary_endpoint(payload: ScenarioSummaryRequest):
    if not payload.scenarios:
        raise HTTPException(status_code=400, detail="at least one scenario is required")
    scenarios_data = [s.model_dump() for s in payload.scenarios]
    try:
        text, result = scenario_summary.run(
            portfolio_name=payload.portfolio_name,
            portfolio_value=payload.portfolio_value,
            scenarios=scenarios_data,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scenario summary failed: {exc}")
    return ScenarioSummaryResponse(
        summary=text,
        cached=result.cached,
        latency_ms=result.latency_ms,
        source_data={
            "portfolio_name": payload.portfolio_name,
            "portfolio_value": payload.portfolio_value,
            "scenarios": scenarios_data,
        },
    )


class ClientQARequest(BaseModel):
    question: str
    metrics: dict[str, Any] = {}
    regime: str = "Normal"
    snapshot_hash: Optional[str] = None


class ClientQAResponse(BaseModel):
    answer: str
    cached: bool
    latency_ms: int
    source_data: dict[str, Any]


@agents_router.post("/qa/{portfolio_id}", response_model=ClientQAResponse)
def client_qa_endpoint(
    portfolio_id: int,
    payload: ClientQARequest,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="question is too long (max 2000 chars)")

    with Session(engine) as session:
        user = _require_user_like(session, user_id, x_user_id)
        portfolio = session.exec(
            select(Portfolio)
            .where(Portfolio.id == portfolio_id)
            .where(Portfolio.user_id == user.id)
        ).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        positions = session.exec(
            select(Position).where(Position.portfolio_id == portfolio_id)
        ).all()
        holdings = [
            {"ticker": p.ticker, "weight": p.weight, "quantity": p.quantity}
            for p in positions
        ]
        held_tickers = [p.ticker.upper() for p in positions]

        alerts: list[dict[str, Any]] = []
        if held_tickers:
            rules = session.exec(
                select(AlertRule)
                .where(AlertRule.user_id == user.id)
                .where(AlertRule.is_active == True)  # noqa: E712
                .where(AlertRule.ticker.in_(held_tickers))  # type: ignore[attr-defined]
            ).all()
            for r in rules:
                latest = session.exec(
                    select(AlertEvent)
                    .where(AlertEvent.alert_id == r.id)
                    .order_by(AlertEvent.evaluated_at.desc())
                ).first()
                alerts.append({
                    "id": r.id,
                    "name": r.name,
                    "ticker": r.ticker.upper(),
                    "alert_type": r.alert_type,
                    "direction": r.direction,
                    "threshold_value": r.threshold_value,
                    "latest_event": (
                        {
                            "triggered": bool(latest.triggered),
                            "evaluated_at": latest.evaluated_at.isoformat()
                            if latest.evaluated_at else "",
                            "payload": latest.payload or {},
                        }
                        if latest else None
                    ),
                })

    try:
        text, result = client_qa.run(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.name or f"Portfolio #{portfolio_id}",
            holdings=holdings,
            metrics=payload.metrics,
            regime=payload.regime,
            alerts=alerts,
            question=question,
            snapshot_hash=payload.snapshot_hash,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Q&A agent failed: {exc}")

    return ClientQAResponse(
        answer=text,
        cached=result.cached,
        latency_ms=result.latency_ms,
        source_data={
            "portfolio": portfolio.name or f"Portfolio #{portfolio_id}",
            "holdings": holdings,
            "metrics": payload.metrics,
            "regime": payload.regime,
            "alerts": alerts,
            "question": question,
        },
    )


class NewsItem(BaseModel):
    title: str
    publisher: Optional[str] = None
    timestamp: Optional[str] = None
    type: Optional[str] = None


class NewsSynthesizeRequest(BaseModel):
    items: list[NewsItem]


class NewsHighlightOut(BaseModel):
    index: int
    note: str


class NewsSynthesisResponse(BaseModel):
    summary: str
    sentiment: str
    highlights: list[NewsHighlightOut]
    cached: bool
    latency_ms: int
    source_data: dict[str, Any]


@agents_router.post("/news-synthesize/{ticker}", response_model=NewsSynthesisResponse)
def news_synthesize_endpoint(ticker: str, payload: NewsSynthesizeRequest):
    if not payload.items:
        raise HTTPException(status_code=400, detail="items is required")
    if len(payload.items) > 40:
        # Cap at 40 so prompts stay cheap; caller should pre-trim.
        payload.items = payload.items[:40]
    items = [it.model_dump() for it in payload.items]
    try:
        synthesis, result = news_synthesizer.run(ticker, items)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"news synthesizer failed: {exc}")
    timestamps = [it.get("timestamp") for it in items if it.get("timestamp")]
    return NewsSynthesisResponse(
        summary=synthesis.summary,
        sentiment=synthesis.sentiment,
        highlights=[NewsHighlightOut(index=h.index, note=h.note) for h in synthesis.highlights],
        cached=result.cached,
        latency_ms=result.latency_ms,
        source_data={
            "ticker": ticker.upper(),
            "item_count": len(items),
            "oldest_timestamp": min(timestamps) if timestamps else None,
            "newest_timestamp": max(timestamps) if timestamps else None,
            "publishers": sorted({str(it.get("publisher") or "unknown") for it in items}),
        },
    )


class AlertExplainResponse(BaseModel):
    explanation: str
    cached: bool
    latency_ms: int
    source_data: dict[str, Any]


@agents_router.post("/alert-explain/{alert_id}", response_model=AlertExplainResponse)
def alert_explain_endpoint(
    alert_id: int,
    user_id: Optional[int] = None,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    with Session(engine) as session:
        user = _require_user_like(session, user_id, x_user_id)
        rule = session.exec(
            select(AlertRule)
            .where(AlertRule.id == alert_id)
            .where(AlertRule.user_id == user.id)
        ).first()
        if not rule:
            raise HTTPException(status_code=404, detail="Alert not found")

        latest_event_row = session.exec(
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.evaluated_at.desc())
        ).first()
        latest_event = None
        if latest_event_row:
            latest_event = {
                "id": latest_event_row.id,
                "triggered": bool(latest_event_row.triggered),
                "evaluated_at": latest_event_row.evaluated_at.isoformat()
                if latest_event_row.evaluated_at else "",
                "payload": latest_event_row.payload or {},
            }

        # Exposures: portfolios owned by this user that hold the ticker.
        positions = session.exec(
            select(Portfolio, Position)
            .join(Position, Position.portfolio_id == Portfolio.id)
            .where(Portfolio.user_id == user.id)
            .where(Position.ticker == rule.ticker.upper())
        ).all()
        exposures = [
            {
                "portfolio_id": p.id,
                "portfolio_name": p.name or f"Portfolio #{p.id}",
                "weight": pos.weight,
            }
            for (p, pos) in positions
        ]

    try:
        text, result = alert_explainer.run(
            alert_id=alert_id,
            rule_name=rule.name,
            ticker=rule.ticker.upper(),
            alert_type=rule.alert_type,
            direction=rule.direction,
            threshold=rule.threshold_value,
            latest_event=latest_event,
            exposures=exposures,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"alert explainer failed: {exc}")

    return AlertExplainResponse(
        explanation=text,
        cached=result.cached,
        latency_ms=result.latency_ms,
        source_data={
            "rule": {
                "name": rule.name,
                "ticker": rule.ticker.upper(),
                "alert_type": rule.alert_type,
                "direction": rule.direction,
                "threshold_value": rule.threshold_value,
                "is_active": rule.is_active,
            },
            "latest_event": latest_event,
            "exposures": exposures,
        },
    )
