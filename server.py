from __future__ import annotations

import json
import ipaddress
import math
import mimetypes
import csv
import io
import re
import sqlite3
import os
import shutil
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
WEB = RESOURCE_ROOT / "web"
if getattr(sys, "frozen", False):
    DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "투자" / "data"
else:
    DATA = ROOT / "data"
DB_PATH = DATA / "workstation.db"
LAST_HEARTBEAT = 0.0
SECTOR_CACHE: dict[str, dict] = {}
SECTOR_LEADERS = {
    "Technology": ("XLK", "NVDA"),
    "Financial Services": ("XLF", "BRK-B"),
    "Financial": ("XLF", "BRK-B"),
    "Healthcare": ("XLV", "LLY"),
    "Industrials": ("XLI", "GE"),
    "Consumer Cyclical": ("XLY", "AMZN"),
    "Consumer Defensive": ("XLP", "WMT"),
    "Communication Services": ("XLC", "META"),
    "Energy": ("XLE", "XOM"),
    "Utilities": ("XLU", "NEE"),
    "Basic Materials": ("XLB", "LIN"),
    "Real Estate": ("XLRE", "PLD"),
}
SECTOR_ETFS = {etf: sector for sector, (etf, _) in SECTOR_LEADERS.items()}
SWING_STRATEGIES = {
    "차트 구조": ["핵심: LL 이후 상승 Swing AVWAP 교점","평행 패턴 저점","평행 패턴 돌파 후 Test·재상승","대칭삼각","상승삼각","하강삼각","하모닉 패턴","상승 패턴","지지·저항 전환 후 Retest","박스권 저항 돌파","HH·HL 상승 구조"],
    "모멘텀": ["RSI 지지","스토캐스틱 골든크로스","스토캐스틱 상승"],
    "자금 흐름": ["CMF 상승","CMF 0선 상향 돌파","가격 LL·CMF HL 양의 다이버전스","Accumulation/Distribution 상승"],
    "추세·변동성": ["상승 이동평균선 Pullback 지지","거래량 동반 Breakout","ATR 변동성 Breakout","52주 신고가 Breakout"],
    "상대강도": ["QQQ 대비 상대강도 상승","SPY 대비 상대강도 상승","섹터 ETF 대비 상대강도 상승"],
    "진입 확인": ["저점 반전 확인","직전 고점 돌파","거래량 증가","지지선 재확인","Bullish Engulfing 확인"],
}
DAY_STRATEGIES = {"가격 행동": ["Opening Range Breakout","VWAP Reclaim","Premarket High Breakout","First Pullback","Gap and Go"], "모멘텀": ["Relative Volume Surge","Tape Acceleration","Momentum Continuation"], "반전": ["Failed Breakout Reversal","VWAP Rejection","Exhaustion Reversal"]}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False) and not DB_PATH.exists():
        legacy = Path.home() / "Desktop" / "Investment-beta" / "data" / "workstation.db"
        if legacy.is_file():
            shutil.copy2(legacy, DB_PATH)
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '',
                setup TEXT NOT NULL DEFAULT 'Pullback',
                status TEXT NOT NULL DEFAULT 'planned',
                entry REAL NOT NULL,
                stop REAL NOT NULL,
                target REAL NOT NULL,
                quantity INTEGER NOT NULL,
                risk_amount REAL NOT NULL,
                risk_pct REAL NOT NULL,
                rr REAL NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                closed_at TEXT,
                exit_price REAL,
                result_r REAL
            );
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                mood TEXT NOT NULL DEFAULT 'Neutral',
                created_at TEXT NOT NULL,
                FOREIGN KEY(trade_id) REFERENCES trades(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                average_price REAL NOT NULL,
                quantity REAL NOT NULL,
                current_price REAL NOT NULL,
                opened_at TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                closed_at TEXT,
                exit_price REAL,
                result_pct REAL
            );
            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                value REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cashflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flow_type TEXT NOT NULL CHECK(flow_type IN ('deposit', 'withdrawal')),
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS realized_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_kind TEXT NOT NULL CHECK(source_kind IN ('trade', 'position')),
                source_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                UNIQUE(source_kind, source_id)
            );
            CREATE TABLE IF NOT EXISTS position_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                action_type TEXT NOT NULL CHECK(action_type IN ('buy','sell','stop_update')),
                price REAL,
                quantity REAL NOT NULL DEFAULT 0,
                fee REAL NOT NULL DEFAULT 0,
                occurred_at TEXT NOT NULL,
                primary_reason TEXT NOT NULL,
                supporting_json TEXT NOT NULL DEFAULT '[]',
                warning_json TEXT NOT NULL DEFAULT '[]',
                stop_after REAL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(position_id) REFERENCES positions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS strategy_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL CHECK(mode IN ('swing','day')),
                group_name TEXT NOT NULL,
                label TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(mode, group_name, label)
            );
            CREATE TABLE IF NOT EXISTS day_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_quantity REAL NOT NULL,
                exit_price REAL NOT NULL,
                exit_quantity REAL NOT NULL,
                fees REAL NOT NULL DEFAULT 0,
                pnl REAL NOT NULL,
                strategies_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS day_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_trade_id INTEGER,
                ticker TEXT NOT NULL,
                body TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(day_trade_id) REFERENCES day_trades(id) ON DELETE SET NULL
            );
            """
        )
        trade_columns = {row["name"] for row in db.execute("PRAGMA table_info(trades)")}
        if "evidence_json" not in trade_columns:
            db.execute("ALTER TABLE trades ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")
        if "realized_pnl" not in trade_columns:
            db.execute("ALTER TABLE trades ADD COLUMN realized_pnl REAL")
        for name, definition in {
            "exit_review_json": "TEXT NOT NULL DEFAULT '{}'",
            "post_exit_json": "TEXT NOT NULL DEFAULT '{}'",
            "post_exit_updated_at": "TEXT",
        }.items():
            if name not in trade_columns:
                db.execute(f"ALTER TABLE trades ADD COLUMN {name} {definition}")
        position_columns = {row["name"] for row in db.execute("PRAGMA table_info(positions)")}
        for name, definition in {
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "closed_at": "TEXT",
            "exit_price": "REAL",
            "result_pct": "REAL",
            "exit_review_json": "TEXT NOT NULL DEFAULT '{}'",
            "post_exit_json": "TEXT NOT NULL DEFAULT '{}'",
            "post_exit_updated_at": "TEXT",
            "price_as_of": "TEXT",
            "price_updated_at": "TEXT",
            "initial_r": "REAL",
            "current_stop": "REAL",
            "peak_live_risk": "REAL NOT NULL DEFAULT 0",
            "realized_pnl": "REAL NOT NULL DEFAULT 0",
        }.items():
            if name not in position_columns:
                db.execute(f"ALTER TABLE positions ADD COLUMN {name} {definition}")
        defaults = {
            "account_value": "50000",
            "goal_value": "1000000",
            "currency": "USD",
            "max_trade_risk_pct": "1.0",
            "max_portfolio_heat_pct": "5.0",
            "max_position_pct": "50.0",
        }
        db.executemany(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", defaults.items()
        )
        if not db.execute("SELECT 1 FROM settings WHERE key='program_start_date'").fetchone():
            candidates = []
            queries = [
                "SELECT MIN(recorded_at) AS day FROM account_snapshots",
                "SELECT MIN(opened_at) AS day FROM positions",
            ]
            if "created_at" in trade_columns:
                queries.append("SELECT MIN(SUBSTR(created_at,1,10)) AS day FROM trades")
            for query in queries:
                value = db.execute(query).fetchone()["day"]
                if value:
                    candidates.append(value)
            db.execute("INSERT INTO settings(key,value) VALUES('program_start_date',?)", (min(candidates) if candidates else datetime.now().date().isoformat(),))
        for row in db.execute("SELECT id, average_price, quantity, opened_at, created_at FROM positions"):
            if not db.execute("SELECT 1 FROM position_actions WHERE position_id=? LIMIT 1", (row["id"],)).fetchone():
                db.execute(
                    """INSERT INTO position_actions(position_id, action_type, price, quantity, occurred_at, primary_reason, notes, created_at)
                    VALUES(?, 'buy', ?, ?, ?, '최초 포지션 등록', '기존 포지션 자동 이관', ?)""",
                    (row["id"], row["average_price"], row["quantity"], row["opened_at"], row["created_at"]),
                )
        for mode, catalog in (("swing", SWING_STRATEGIES), ("day", DAY_STRATEGIES)):
            for group, labels in catalog.items():
                db.executemany("INSERT OR IGNORE INTO strategy_catalog(mode,group_name,label,created_at) VALUES(?,?,?,?)", [(mode, group, label, now_iso()) for label in labels])


def as_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def get_settings(db: sqlite3.Connection) -> dict:
    values = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}
    return {
        "accountValue": float(values.get("account_value", 50_000)),
        "goalValue": float(values.get("goal_value", 1_000_000)),
        "currency": values.get("currency", "USD"),
        "maxTradeRiskPct": float(values.get("max_trade_risk_pct", 1.0)),
        "maxPortfolioHeatPct": float(values.get("max_portfolio_heat_pct", 5.0)),
        "maxPositionPct": float(values.get("max_position_pct", 50.0)),
        "programStartDate": values.get("program_start_date", datetime.now().date().isoformat()),
    }


def dashboard(db: sqlite3.Connection) -> dict:
    settings = get_settings(db)
    trades = [as_dict(r) for r in db.execute("SELECT * FROM trades ORDER BY id DESC")]
    active = [t for t in trades if t["status"] == "active"]
    closed = [t for t in trades if t["status"] == "closed"]
    heat = sum(float(t["risk_pct"]) for t in active)
    wins = [t for t in closed if (t["result_r"] or 0) > 0]
    expectancy = (
        sum(float(t["result_r"] or 0) for t in closed) / len(closed) if closed else 0
    )
    all_positions = [as_dict(r) for r in db.execute("SELECT * FROM positions ORDER BY id DESC")]
    positions = [p for p in all_positions if p.get("status", "active") == "active"]
    closed_positions = [p for p in all_positions if p.get("status") == "closed"]
    snapshots = [as_dict(r) for r in db.execute("SELECT * FROM account_snapshots ORDER BY recorded_at")]
    cashflows = [as_dict(r) for r in db.execute("SELECT * FROM cashflows ORDER BY recorded_at, id")]
    equity_timeline = build_equity_timeline(db)
    performance = performance_projection(equity_timeline, settings)
    position_cost = sum(float(p["average_price"]) * float(p["quantity"]) for p in positions)
    position_value = sum(float(p["current_price"]) * float(p["quantity"]) for p in positions)
    active_trade_value = sum(float(t["entry"]) * float(t["quantity"]) for t in active)
    invested_assets = position_value + active_trade_value
    actions = [as_dict(row) for row in db.execute("SELECT pa.*, p.ticker FROM position_actions pa JOIN positions p ON p.id=pa.position_id ORDER BY pa.occurred_at DESC, pa.id DESC")]
    action_buckets = {}
    for action in actions:
        if action["primary_reason"] == "최초 포지션 등록":
            continue
        key = (action["action_type"], action["primary_reason"])
        bucket = action_buckets.setdefault(key, {"actionType": action["action_type"], "reason": action["primary_reason"], "count": 0, "realizedPnl": 0.0})
        bucket["count"] += 1
        bucket["realizedPnl"] += float(action["realized_pnl"] or 0)
    management_stats = [{**value, "realizedPnl": round(value["realizedPnl"], 2)} for value in action_buckets.values()]
    management_stats.sort(key=lambda row: (-row["count"], row["reason"]))
    strategies = [as_dict(row) for row in db.execute("SELECT * FROM strategy_catalog ORDER BY mode, group_name, id")]
    day_trades = [as_dict(row) for row in db.execute("SELECT * FROM day_trades ORDER BY trade_date DESC, id DESC")]
    day_journals = [as_dict(row) for row in db.execute("SELECT * FROM day_journal ORDER BY trade_date DESC, id DESC")]
    local_today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    today_day_trades = [row for row in day_trades if row["trade_date"] == local_today]
    day_pnl = sum(float(row["pnl"]) for row in today_day_trades)
    day_capital = sum(float(row["entry_price"]) * float(row["entry_quantity"]) for row in today_day_trades)
    day_buckets = {}
    for trade in day_trades:
        try: selected = json.loads(trade["strategies_json"] or "[]")
        except json.JSONDecodeError: selected = []
        for strategy in selected:
            bucket = day_buckets.setdefault(strategy, {"strategy": strategy, "trades": 0, "wins": 0, "pnl": 0.0, "grossProfit": 0.0, "grossLoss": 0.0})
            pnl = float(trade["pnl"]);bucket["trades"] += 1;bucket["wins"] += int(pnl > 0);bucket["pnl"] += pnl
            if pnl > 0: bucket["grossProfit"] += pnl
            elif pnl < 0: bucket["grossLoss"] += abs(pnl)
    day_strategy_stats = []
    for bucket in day_buckets.values():
        bucket["winRate"] = round(bucket["wins"] / bucket["trades"] * 100, 1)
        bucket["averagePnl"] = round(bucket["pnl"] / bucket["trades"], 2)
        bucket["profitFactor"] = round(bucket["grossProfit"] / bucket["grossLoss"], 2) if bucket["grossLoss"] else None
        day_strategy_stats.append(bucket)
    live_risk_total = sum(max((float(p["average_price"]) - float(p["current_stop"])) * float(p["quantity"]), 0) for p in positions if p.get("current_stop"))
    risk_expansions = [float(p["peak_live_risk"]) / float(p["initial_r"]) for p in all_positions if p.get("initial_r") and float(p["initial_r"]) > 0]
    strategy_buckets = {}
    for position in closed_positions:
        try:
            evidence = json.loads(position.get("evidence_json") or "{}")
        except json.JSONDecodeError:
            evidence = {}
        for group, items in evidence.items():
            for item in items:
                bucket = strategy_buckets.setdefault(item, {"strategy": item, "group": group, "trades": 0, "wins": 0, "totalReturnPct": 0.0})
                bucket["trades"] += 1
                result = float(position.get("result_pct") or 0)
                bucket["wins"] += int(result > 0)
                bucket["totalReturnPct"] += result
    strategy_stats = []
    for bucket in strategy_buckets.values():
        bucket["winRate"] = round(bucket["wins"] / bucket["trades"] * 100, 1)
        bucket["averageReturnPct"] = round(bucket.pop("totalReturnPct") / bucket["trades"], 2)
        strategy_stats.append(bucket)
    strategy_stats.sort(key=lambda row: (-row["trades"], -row["averageReturnPct"]))
    return {
        "settings": settings,
        "active": active,
        "planned": [t for t in trades if t["status"] == "planned"],
        "recent": trades[:8],
        "positions": positions,
        "closedPositions": closed_positions,
        "strategyStats": strategy_stats,
        "snapshots": snapshots,
        "cashflows": cashflows,
        "equityTimeline": equity_timeline,
        "positionActions": actions,
        "managementStats": management_stats,
        "strategies": strategies,
        "dayTrades": day_trades,
        "dayJournals": day_journals,
        "dayStrategyStats": day_strategy_stats,
        "metrics": {
            "portfolioHeat": round(heat + (live_risk_total / performance["currentAssets"] * 100 if performance["currentAssets"] else 0), 2),
            "activeCount": len(active) + len(positions),
            "plannerActiveCount": len(active),
            "importedActiveCount": len(positions),
            "closedCount": len(closed),
            "winRate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "expectancy": round(expectancy, 2),
            "positionCost": round(position_cost, 2),
            "positionValue": round(position_value, 2),
            "unrealizedPnl": round(position_value - position_cost, 2),
            "investedAssets": round(invested_assets, 2),
            "availableAssets": round(max(performance["currentAssets"] - invested_assets, 0), 2),
            "investedPct": round(invested_assets / performance["currentAssets"] * 100, 2) if performance["currentAssets"] else 0,
            "riskExpansionRatio": round(sum(risk_expansions) / len(risk_expansions), 2) if risk_expansions else None,
            "dayAvailableCapital": round(max(performance["currentAssets"] - invested_assets, 0), 2),
            "todayDayPnl": round(day_pnl, 2),
            "todayDayCapital": round(day_capital, 2),
            "todayDayReturnOnTotalPct": round(day_pnl / performance["currentAssets"] * 100, 3) if performance["currentAssets"] else 0.0,
            "todayDayReturnOnCapitalPct": round(day_pnl / day_capital * 100, 3) if day_capital else 0.0,
            **performance,
        },
        "sync": {
            "online": False,
            "label": "Local mode",
            "lastUpdated": now_iso(),
        },
    }


def performance_projection(timeline: list[dict], settings: dict) -> dict:
    """Cash-flow-adjusted YTD estimate and a conservative goal projection."""
    current = float(timeline[-1]["value"] if timeline else settings["accountValue"])
    goal = float(settings["goalValue"])
    year_start = datetime.now().date().replace(month=1, day=1).isoformat()
    ytd = [row for row in timeline if row["recordedAt"] >= year_start]
    base = {"currentAssets": round(current, 2), "ytdReturnPct": None, "annualizedReturnPct": None,
            "goalYears": None, "goalStatus": "insufficient_data"}
    if current >= goal:
        return {**base, "goalYears": 0, "goalStatus": "reached"}
    if len(ytd) < 2 or ytd[0]["recordedAt"] == ytd[-1]["recordedAt"]:
        return base
    start, end = float(ytd[0]["value"]), float(ytd[-1]["value"])
    if start <= 0:
        return base
    net_flow = sum(
        float(row["amount"]) * (1 if row["kind"] == "deposit" else -1)
        for row in ytd[1:] if row["kind"] in {"deposit", "withdrawal"}
    )
    ytd_return = (end - start - net_flow) / start
    days = (datetime.fromisoformat(ytd[-1]["recordedAt"]).date() - datetime.fromisoformat(ytd[0]["recordedAt"]).date()).days
    result = {**base, "ytdReturnPct": round(ytd_return * 100, 2)}
    if days < 30 or ytd_return <= -1:
        return result
    annualized = (1 + ytd_return) ** (365 / days) - 1
    result["annualizedReturnPct"] = round(annualized * 100, 2)
    if annualized <= 0 or current <= 0:
        result["goalStatus"] = "non_positive_return"
        return result
    years = math.log(goal / current) / math.log(1 + annualized)
    result["goalYears"] = round(years, 1)
    result["goalStatus"] = "estimated"
    return result


def portfolio_period_return(timeline: list[dict], requested_start: str) -> dict | None:
    if not timeline:
        return None
    before = [row for row in timeline if row["recordedAt"] <= requested_start]
    if before:
        start_value = float(before[-1]["value"])
        start_date = requested_start
    else:
        start_value = float(timeline[0]["value"])
        start_date = timeline[0]["recordedAt"]
    end_row = timeline[-1]
    if end_row["recordedAt"] < start_date or start_value <= 0:
        return None
    flows = [row for row in timeline if start_date < row["recordedAt"] <= end_row["recordedAt"]]
    net_flow = sum(
        float(row["amount"]) * (1 if row["kind"] == "deposit" else -1)
        for row in flows if row["kind"] in {"deposit", "withdrawal"}
    )
    end_value = float(end_row["value"])
    return {
        "startDate": start_date, "endDate": end_row["recordedAt"],
        "startValue": round(start_value, 2), "endValue": round(end_value, 2),
        "returnPct": round((end_value - start_value - net_flow) / start_value * 100, 2),
    }


def online_portfolio_return(db: sqlite3.Connection, start_date: str) -> dict | None:
    timeline = build_equity_timeline(db)
    if not timeline:
        return None
    before = [row for row in timeline if row["recordedAt"] <= start_date]
    start_value = float(before[-1]["value"] if before else timeline[0]["value"])
    effective_start = start_date if before else timeline[0]["recordedAt"]
    if start_value <= 0:
        return None
    market_pnl = 0.0
    latest_dates = []
    errors = []
    for table, entry_column, quantity_column in (("positions", "average_price", "quantity"), ("trades", "entry", "quantity")):
        date_column = "opened_at" if table == "positions" else "created_at"
        rows = db.execute(f"SELECT ticker,{entry_column} AS entry_price,{quantity_column} AS quantity,{date_column} AS opened FROM {table} WHERE status='active'")
        for row in rows:
            opened = str(row["opened"])[:10]
            quote_row = market_return(row["ticker"], max(effective_start, opened))
            if "error" in quote_row:
                errors.append({"ticker": row["ticker"], "error": quote_row["error"]})
                continue
            market_pnl += (float(quote_row["lastPrice"]) - float(quote_row["startPrice"])) * float(row["quantity"])
            latest_dates.append(quote_row["lastDate"])
    realized = db.execute("SELECT COALESCE(SUM(amount),0) AS pnl FROM realized_events WHERE recorded_at>=?", (effective_start,)).fetchone()["pnl"]
    end_value = start_value + market_pnl + float(realized)
    return {"startDate": effective_start, "endDate": max(latest_dates) if latest_dates else effective_start,
            "startValue": round(start_value, 2), "endValue": round(end_value, 2),
            "returnPct": round((end_value / start_value - 1) * 100, 2), "errors": errors}


def build_equity_timeline(db: sqlite3.Connection) -> list[dict]:
    events = []
    for row in db.execute("SELECT id, value, note, recorded_at FROM account_snapshots"):
        events.append({"id": row["id"], "kind": "snapshot", "amount": float(row["value"]), "note": row["note"], "recordedAt": row["recorded_at"], "order": 0})
    for row in db.execute("SELECT id, flow_type, amount, note, recorded_at FROM cashflows"):
        events.append({"id": row["id"], "kind": row["flow_type"], "amount": float(row["amount"]), "note": row["note"], "recordedAt": row["recorded_at"], "order": 1})
    for row in db.execute("SELECT id, source_kind, source_id, amount, note, recorded_at FROM realized_events"):
        events.append({"id": row["id"], "kind": f"{row['source_kind']}_pnl", "sourceId": row["source_id"], "amount": float(row["amount"]), "note": row["note"], "recordedAt": row["recorded_at"], "order": 2})
    events.sort(key=lambda row: (row["recordedAt"], row["order"], row["id"]))
    current = None
    timeline = []
    for event in events:
        if event["kind"] == "snapshot":
            current = event["amount"]
        elif current is not None:
            current += event["amount"] if event["kind"] in {"deposit", "trade_pnl", "position_pnl"} else -event["amount"]
        else:
            continue
        timeline.append({**event, "value": round(current, 2)})
    return timeline


def sync_account_value(db: sqlite3.Connection) -> None:
    timeline = build_equity_timeline(db)
    if timeline:
        db.execute(
            "INSERT INTO settings(key, value) VALUES('account_value', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(timeline[-1]["value"]),),
        )


def market_return(ticker: str, start_date: str, end_date: str | None = None) -> dict:
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    period1 = int(start.timestamp())
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) if end_date else datetime.now(timezone.utc)
    period2 = int(end.timestamp()) + 172_800
    symbol = quote(ticker.strip().upper(), safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = Request(url, headers={"User-Agent": "Investment-Beta/0.1"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.load(response)
        result = payload["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        rows = [(datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(), float(value)) for stamp, value in zip(timestamps, closes) if value is not None]
        meta = result.get("meta", {})
        meta_stamp = int(meta.get("regularMarketTime") or 0)
        meta_price = meta.get("regularMarketPrice")
        period = meta.get("currentTradingPeriod", {}).get("regular", {})
        period_start, period_end = int(period.get("start") or 0), int(period.get("end") or 0)
        last_stamp = max((stamp for stamp, value in zip(timestamps, closes) if value is not None), default=0)
        if meta_stamp and meta_price is not None and period_start and period_end and (meta_stamp < period_start or meta_stamp >= period_end) and meta_stamp > last_stamp:
            zone = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")
            rows.append((datetime.fromtimestamp(meta_stamp, timezone.utc).astimezone(zone).date().isoformat(), float(meta_price)))
        if not rows:
            raise ValueError("가격 데이터가 없습니다.")
        first_date, first = rows[0]
        last_date, last = rows[-1]
        return {
            "ticker": ticker.upper(), "startPrice": first, "lastPrice": last,
            "startDate": first_date, "lastDate": last_date,
            "returnPct": round((last / first - 1) * 100, 2), "source": "Yahoo Finance daily close",
        }
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
        return {"ticker": ticker.upper(), "error": str(exc), "source": "Yahoo Finance"}


def latest_market_close(ticker: str) -> dict:
    """Return the latest completed daily close without requiring yfinance."""
    symbol = quote(ticker.strip().upper(), safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=10d&interval=1d&events=history&includeAdjustedClose=false"
    )
    request = Request(url, headers={"User-Agent": "Investment-Beta/0.1"})
    try:
        with urlopen(request, timeout=8) as response:
            result = json.load(response)["chart"]["result"][0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        completed = [(stamp, value) for stamp, value in zip(timestamps, closes) if value is not None]
        meta_stamp = int(meta.get("regularMarketTime") or 0)
        meta_price = meta.get("regularMarketPrice")
        regular_period = meta.get("currentTradingPeriod", {}).get("regular", {})
        current_start = int(regular_period.get("start") or 0)
        current_end = int(regular_period.get("end") or 0)
        meta_is_completed = bool(
            meta_stamp and meta_price is not None and current_start and current_end
            and (meta_stamp < current_start or meta_stamp >= current_end)
        )
        # Yahoo occasionally publishes the completed session in regularMarketPrice
        # before filling that day's daily close candle. Prefer the newer completed
        # market timestamp instead of silently falling back to the prior session.
        if meta_is_completed and (not completed or meta_stamp > completed[-1][0]):
            stamp, value = meta_stamp, meta_price
        elif completed:
            stamp, value = completed[-1]
        else:
            raise ValueError("완료된 종가 데이터가 없습니다.")
        zone = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")
        return {
            "ticker": ticker.upper(), "price": round(float(value), 4),
            "asOf": datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date().isoformat(),
            "source": "Yahoo Finance daily close",
        }
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        return {"ticker": ticker.upper(), "error": str(exc), "source": "Yahoo Finance daily close"}


def sector_leader_for(ticker: str) -> dict:
    symbol = ticker.strip().upper()
    if symbol in SECTOR_CACHE:
        return dict(SECTOR_CACHE[symbol])
    sector = SECTOR_ETFS.get(symbol)
    if not sector:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={quote(symbol)}&quotesCount=1&newsCount=0"
        request = Request(url, headers={"User-Agent": "Investment-Beta/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                quotes = json.load(response).get("quotes", [])
            match = next((row for row in quotes if row.get("symbol", "").upper() == symbol), quotes[0] if quotes else {})
            sector = match.get("sector") or match.get("sectorDisp")
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
            return {"ticker": symbol, "error": f"섹터 조회 실패: {exc}"}
    mapping = SECTOR_LEADERS.get(sector)
    if not mapping:
        return {"ticker": symbol, "sector": sector, "error": "지원되는 핵심 섹터로 분류되지 않았습니다."}
    etf, leader = mapping
    result = {"ticker": symbol, "sector": sector, "sectorEtf": etf, "leader": leader}
    SECTOR_CACHE[symbol] = result
    return dict(result)


def market_series(ticker: str, start_date: str, end_date: str) -> list[dict]:
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    symbol = quote(ticker.strip().upper(), safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}"
        "&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = Request(url, headers={"User-Agent": "Investment-Beta/0.1"})
    with urlopen(request, timeout=8) as response:
        result = json.load(response)["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    adjusted = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    rows = []
    for stamp, value in zip(timestamps, adjusted):
        if value is not None:
            rows.append({"date": datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(), "price": float(value)})
    return rows


def classify_exit(review: dict, post: dict) -> str:
    if not post or int(post.get("availableDays", 0)) < 5:
        return "데이터 부족"
    horizons = post.get("horizons", {})
    reference = horizons.get("10") or horizons.get("5") or {}
    after_return = float(reference.get("returnPct", 0))
    psychology = set(review.get("심리·재량", []))
    structure = set(review.get("가격 구조 훼손", []))
    rule_based = bool(review.get("ruleBased"))
    if psychology and not rule_based and not structure and after_return >= 3:
        return "Chicken-out 가능성"
    if not rule_based and after_return >= 3:
        return "이른 매도 가능성"
    if rule_based and after_return <= 0:
        return "잘 방어한 매도"
    if rule_based:
        return "계획대로 매도"
    return "추가 관찰 필요"


MACRO_CACHE = DATA / "macro-cache.json"
FRED_SERIES = [
    ("CPI", "CPIAUCSL", "Consumer Price Index", "YoY", "inflation", 12),
    ("PPI", "PPIACO", "Producer Price Index", "YoY", "inflation", 12),
    ("UNRATE", "UNRATE", "Unemployment Rate", "%", "labor", 1),
    ("PAYEMS", "PAYEMS", "Nonfarm Payrolls", "K MoM", "labor_change", 1),
    ("ICSA", "ICSA", "Initial Jobless Claims", "claims", "claims", 1),
    ("RETAIL", "RSAFS", "Retail Sales", "MoM", "growth", 1),
]

def fetch_fred_rows(series_id: str) -> list[tuple[str, float]]:
    start=(datetime.now().date()-timedelta(days=500)).isoformat()
    request=Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}",headers={"User-Agent":"Tuja/0.9"})
    with urlopen(request,timeout=10) as response: text=response.read().decode("utf-8-sig")
    rows=[]
    for row in csv.DictReader(io.StringIO(text)):
        raw=row.get(series_id)
        if raw and raw != ".": rows.append((row.get("DATE") or row.get("observation_date"),float(raw)))
    return rows

def macro_indicator(code: str, series_id: str, title: str, unit: str, kind: str, lag: int) -> dict:
    rows=fetch_fred_rows(series_id)
    if len(rows)<=lag: raise ValueError(f"{title} 데이터 부족")
    date,value=rows[-1];previous=rows[-1-lag][1]
    if kind in {"inflation","growth"}: display=(value/previous-1)*100
    elif kind in {"labor_change"}: display=value-previous
    else: display=value
    prior_display=((rows[-2][1]/rows[-2-lag][1]-1)*100 if kind in {"inflation","growth"} and len(rows)>lag+1 else (rows[-2][1]-rows[-3][1] if kind=="labor_change" and len(rows)>2 else rows[-2][1]))
    delta=display-prior_display
    if kind in {"inflation","growth"} and len(rows)>lag+2:
        earlier_display=(rows[-3][1]/rows[-3-lag][1]-1)*100
    elif kind=="labor_change" and len(rows)>3:
        earlier_display=rows[-3][1]-rows[-4][1]
    elif len(rows)>2:
        earlier_display=rows[-3][1]
    else:
        earlier_display=prior_display
    previous_delta=prior_display-earlier_display
    trend_direction="up" if delta>0 else "down" if delta<0 else "flat"
    trend_count=2 if trend_direction!="flat" and ((delta>0 and previous_delta>0) or (delta<0 and previous_delta<0)) else 1
    direction="상승" if delta>0 else "하락" if delta<0 else "변화 없음"
    if kind=="inflation": implication=f"이전 발표 대비 {abs(delta):.2f}%p {direction}했습니다. 물가 압력이 높아지면 금리 인하 기대에는 부담이 될 수 있습니다. 연준의 2% 목표는 공식적으로 PCE 물가 기준이므로 CPI·PPI와 직접 동일시하지 않습니다."
    elif kind=="labor": implication=f"이전 발표 대비 {abs(delta):.2f}%p {direction}했습니다. 실업률 상승은 노동시장 둔화, 하락은 고용 여건의 견조함을 시사할 수 있습니다."
    elif kind=="claims": implication=f"이전 주 대비 {abs(delta):,.0f}건 {direction}했습니다. 신청 증가가 이어지면 노동시장 냉각 신호로 해석될 수 있습니다."
    elif kind=="labor_change": implication=f"이전 발표보다 고용 증가폭이 {abs(delta):,.0f}천 명 {direction}했습니다. 추세적인 둔화 여부를 실업률과 함께 확인해야 합니다."
    else: implication=f"이전 발표 대비 {abs(delta):.2f}%p {direction}했습니다. 소비 변화는 경기 성장과 기업 매출 환경을 판단하는 참고 지표입니다."
    return {"code":code,"title":title,"date":date,"value":round(display,2),"previous":round(prior_display,2),"delta":round(delta,2),"previousDelta":round(previous_delta,2),"trendDirection":trend_direction,"trendCount":trend_count,"unit":unit,"implication":implication,"source":"FRED","sourceUrl":f"https://fred.stlouisfed.org/series/{series_id}"}

def parse_bls_calendar() -> list[dict]:
    request=Request("https://www.bls.gov/schedule/news_release/bls.ics",headers={"User-Agent":"Investment-Beta/0.3 contact local-user"})
    with urlopen(request,timeout=10) as response: raw=response.read().decode("utf-8",errors="replace")
    raw=re.sub(r"\r?\n[ \t]", "", raw);events=[];now=datetime.now(timezone.utc)
    allow=("Consumer Price Index","Producer Price Index","Employment Situation","Job Openings","Employment Cost Index")
    for block in raw.split("BEGIN:VEVENT")[1:]:
        summary_match=re.search(r"\nSUMMARY:(.+)","\n"+block);date_match=re.search(r"\nDTSTART(?:;TZID=([^:]+))?:(\d{8}T\d{6})","\n"+block)
        if not summary_match or not date_match: continue
        summary=summary_match.group(1).replace("\\,",",").strip()
        if not any(name in summary for name in allow): continue
        zone=ZoneInfo(date_match.group(1) or "America/New_York");local=datetime.strptime(date_match.group(2),"%Y%m%dT%H%M%S").replace(tzinfo=zone);utc=local.astimezone(timezone.utc)
        if utc>=now-timedelta(days=1): events.append({"title":summary,"startsAt":utc.isoformat(),"et":local.strftime("%Y-%m-%d %H:%M ET"),"kst":utc.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),"importance":"high","agency":"BLS","sourceUrl":"https://www.bls.gov/schedule/"})
    return events

def fomc_events() -> list[dict]:
    dates=["2026-09-16","2026-10-28","2026-12-09","2027-01-27","2027-03-17","2027-04-28","2027-06-09","2027-07-28","2027-09-15","2027-10-27","2027-12-08"]
    now=datetime.now(timezone.utc);events=[]
    for day in dates:
        local=datetime.fromisoformat(day+"T14:00:00").replace(tzinfo=ZoneInfo("America/New_York"));utc=local.astimezone(timezone.utc)
        if utc>=now-timedelta(days=1): events.append({"title":"FOMC Policy Decision","startsAt":utc.isoformat(),"et":local.strftime("%Y-%m-%d %H:%M ET"),"kst":utc.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),"importance":"high","agency":"Federal Reserve","sourceUrl":"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"})
    return events

def fallback_bls_events() -> list[dict]:
    """Official 2026 BLS dates used when bls.gov blocks its calendar download."""
    rows=[
        ("2026-09-01T10:00:00","Job Openings and Labor Turnover Survey"),("2026-09-04T08:30:00","Employment Situation"),
        ("2026-09-10T08:30:00","Producer Price Index"),("2026-09-11T08:30:00","Consumer Price Index"),
        ("2026-09-29T10:00:00","Job Openings and Labor Turnover Survey"),("2026-10-02T08:30:00","Employment Situation"),
        ("2026-10-14T08:30:00","Consumer Price Index"),("2026-10-15T08:30:00","Producer Price Index"),
        ("2026-10-30T08:30:00","Employment Cost Index"),("2026-11-03T10:00:00","Job Openings and Labor Turnover Survey"),
        ("2026-11-06T08:30:00","Employment Situation"),("2026-11-10T08:30:00","Consumer Price Index"),
        ("2026-11-13T08:30:00","Producer Price Index"),
    ];now=datetime.now(timezone.utc);events=[]
    for stamp,title in rows:
        local=datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("America/New_York"));utc=local.astimezone(timezone.utc)
        if utc>=now-timedelta(days=1): events.append({"title":title,"startsAt":utc.isoformat(),"et":local.strftime("%Y-%m-%d %H:%M ET"),"kst":utc.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),"importance":"high","agency":"BLS","sourceUrl":"https://www.bls.gov/schedule/2026/home.htm"})
    return events

def load_macro_snapshot(force: bool=False) -> dict:
    if not force and MACRO_CACHE.exists():
        try:
            cached=json.loads(MACRO_CACHE.read_text(encoding="utf-8"));age=datetime.now(timezone.utc)-datetime.fromisoformat(cached["fetchedAt"])
            if age<timedelta(hours=6): return cached
        except (ValueError,KeyError,json.JSONDecodeError): pass
    try:
        indicators=[];errors=[]
        for args in FRED_SERIES:
            try: indicators.append(macro_indicator(*args))
            except Exception as exc: errors.append(str(exc))
        try: events=parse_bls_calendar()+fomc_events()
        except Exception as exc: events=fallback_bls_events()+fomc_events();errors.append(f"BLS calendar live feed: {exc}")
        events.sort(key=lambda row:row["startsAt"]);result={"indicators":indicators,"events":events[:18],"fetchedAt":now_iso(),"stale":False,"errors":errors}
        DATA.mkdir(exist_ok=True);MACRO_CACHE.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8");return result
    except Exception as exc:
        if MACRO_CACHE.exists():
            cached=json.loads(MACRO_CACHE.read_text(encoding="utf-8"));cached["stale"]=True;cached.setdefault("errors",[]).append(str(exc));return cached
        return {"indicators":[],"events":fomc_events(),"fetchedAt":None,"stale":True,"errors":[str(exc)]}


class Handler(SimpleHTTPRequestHandler):
    server_version = "Tuja/0.9"

    def request_is_allowed(self, *, mutating: bool = False) -> bool:
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if self.headers.get("Host", "") not in allowed_hosts:
            return False
        if mutating:
            origin = self.headers.get("Origin")
            allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if origin and origin not in allowed_origins:
                return False
            if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
                return False
        return True

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, value, status=HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 1_048_576:
            raise ValueError("Request body is too large.")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self) -> None:
        if not self.request_is_allowed():
            self.send_json({"error": "Local access only"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/dashboard":
            with connect() as db:
                self.send_json(dashboard(db))
            return
        if path == "/api/trades":
            with connect() as db:
                rows = [as_dict(r) for r in db.execute("SELECT * FROM trades ORDER BY id DESC")]
                self.send_json(rows)
            return
        if path == "/api/journal":
            with connect() as db:
                rows = [as_dict(r) for r in db.execute("SELECT * FROM journal ORDER BY id DESC")]
                self.send_json(rows)
            return
        if path == "/api/positions":
            with connect() as db:
                rows = [as_dict(r) for r in db.execute("SELECT * FROM positions ORDER BY id DESC")]
                self.send_json(rows)
            return
        if path == "/api/snapshots":
            with connect() as db:
                rows = [as_dict(r) for r in db.execute("SELECT * FROM account_snapshots ORDER BY recorded_at")]
                self.send_json(rows)
            return
        if path == "/api/cashflows":
            with connect() as db:
                rows = [as_dict(r) for r in db.execute("SELECT * FROM cashflows ORDER BY recorded_at, id")]
                self.send_json(rows)
            return
        if path == "/api/macro":
            self.send_json(load_macro_snapshot())
            return
        if path == "/api/relative-performance":
            requested = parse_qs(parsed.query).get("benchmarks", ["QQQ,SPY"])[0]
            benchmarks = [x.strip().upper() for x in requested.split(",") if x.strip()][:5]
            with connect() as db:
                positions = [as_dict(r) for r in db.execute("SELECT * FROM positions ORDER BY id DESC")]
            cache = {}
            comparisons = []
            for position in positions:
                position_return = (float(position["current_price"]) / float(position["average_price"]) - 1) * 100
                benchmark_rows = []
                for benchmark in benchmarks:
                    key = (benchmark, position["opened_at"], position.get("closed_at"))
                    if key not in cache:
                        cache[key] = market_return(*key)
                    row = dict(cache[key])
                    if "returnPct" in row:
                        row["alphaPct"] = round(position_return - row["returnPct"], 2)
                    benchmark_rows.append(row)
                comparisons.append({
                    "positionId": position["id"], "ticker": position["ticker"],
                    "openedAt": position["opened_at"], "positionReturnPct": round(position_return, 2),
                    "benchmarks": benchmark_rows,
                })
            self.send_json({"comparisons": comparisons, "benchmarks": benchmarks})
            return
        if path == "/api/portfolio-relative-performance":
            with connect() as db:
                settings = get_settings(db)
                program_start = settings["programStartDate"]
                portfolio = online_portfolio_return(db, program_start)
            if not portfolio:
                self.send_json({"error": "비교할 자산 원장 기록이 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            benchmarks = [market_return(ticker, program_start) for ticker in ("SPY", "QQQ")]
            for row in benchmarks:
                if "returnPct" in row:
                    row["alphaPct"] = round(portfolio["returnPct"] - row["returnPct"], 2)
            self.send_json({"requestedStartDate": program_start, "portfolio": portfolio, "benchmarks": benchmarks})
            return
        if path == "/api/sector-relative-performance":
            with connect() as db:
                positions = [as_dict(row) for row in db.execute(
                    "SELECT id, ticker, average_price, current_price, opened_at FROM positions WHERE status='active' ORDER BY id DESC"
                )]
            market_cache = {}
            comparisons = []
            for position in positions:
                profile = sector_leader_for(position["ticker"])
                position_return = (float(position["current_price"]) / float(position["average_price"]) - 1) * 100
                row = {"positionId": position["id"], "ticker": position["ticker"], "openedAt": position["opened_at"],
                       "positionReturnPct": round(position_return, 2), "profile": profile, "benchmarks": []}
                symbols = [profile.get("leader"), "SPY"] if not profile.get("error") else ["SPY"]
                for symbol in symbols:
                    key = (symbol, position["opened_at"])
                    if key not in market_cache:
                        market_cache[key] = market_return(symbol, position["opened_at"])
                    benchmark = dict(market_cache[key])
                    if "returnPct" in benchmark:
                        benchmark["alphaPct"] = round(position_return - benchmark["returnPct"], 2)
                    row["benchmarks"].append(benchmark)
                comparisons.append(row)
            self.send_json({"comparisons": comparisons})
            return
        if path == "/api/exit-quality":
            with connect() as db:
                rows = []
                for kind, table in (("trade", "trades"), ("position", "positions")):
                    for row in db.execute(
                        f"SELECT id, ticker, closed_at, exit_price, exit_review_json, post_exit_json, post_exit_updated_at FROM {table} WHERE status='closed' ORDER BY closed_at DESC"
                    ):
                        review = json.loads(row["exit_review_json"] or "{}")
                        post = json.loads(row["post_exit_json"] or "{}")
                        rows.append({
                            "kind": kind, "id": row["id"], "ticker": row["ticker"],
                            "closedAt": row["closed_at"], "exitPrice": row["exit_price"],
                            "review": review, "postExit": post,
                            "classification": classify_exit(review, post),
                            "updatedAt": row["post_exit_updated_at"],
                        })
                rows.sort(key=lambda item: item["closedAt"] or "", reverse=True)
                self.send_json(rows)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        if not self.request_is_allowed(mutating=True):
            self.send_json({"error": "Cross-origin request blocked"}, HTTPStatus.FORBIDDEN)
            return
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            parts = path.strip("/").split("/")
            if path == "/api/heartbeat":
                global LAST_HEARTBEAT
                LAST_HEARTBEAT = time.monotonic()
                self.send_json({"ok": True})
                return
            if path == "/api/exit-observations/refresh":
                self.refresh_exit_observations()
                return
            if path == "/api/positions/refresh-prices":
                self.refresh_position_prices()
                return
            if len(parts) == 4 and parts[:2] == ["api", "positions"] and parts[3] == "actions":
                self.create_position_action(int(parts[2]), payload)
                return
            if path == "/api/trades":
                self.create_trade(payload)
                return
            if path == "/api/journal":
                self.create_journal(payload)
                return
            if path == "/api/settings":
                self.update_settings(payload)
                return
            if path == "/api/positions":
                self.create_position(payload)
                return
            if path == "/api/snapshots":
                self.create_snapshot(payload)
                return
            if path == "/api/cashflows":
                self.create_cashflow(payload)
                return
            if path == "/api/strategies":
                self.create_strategy(payload)
                return
            if path == "/api/day-trades":
                self.create_day_trade(payload)
                return
            if path == "/api/day-journal":
                self.create_day_journal(payload)
                return
            if path == "/api/macro/refresh":
                self.send_json(load_macro_snapshot(force=True))
                return
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, TypeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def refresh_position_prices(self) -> None:
        with connect() as db:
            positions = [as_dict(row) for row in db.execute(
                "SELECT id, ticker FROM positions WHERE status='active' ORDER BY id"
            )]
        quotes = {}
        results = []
        updated_at = now_iso()
        with connect() as db:
            for position in positions:
                ticker = position["ticker"].strip().upper()
                if ticker not in quotes:
                    quotes[ticker] = latest_market_close(ticker)
                quote_row = dict(quotes[ticker])
                quote_row["positionId"] = position["id"]
                if "price" in quote_row:
                    db.execute(
                        "UPDATE positions SET current_price=?, price_as_of=?, price_updated_at=? WHERE id=?",
                        (quote_row["price"], quote_row["asOf"], updated_at, position["id"]),
                    )
                results.append(quote_row)
        succeeded = sum("price" in row for row in results)
        self.send_json({"updated": succeeded, "failed": len(results) - succeeded, "results": results})

    def do_PATCH(self) -> None:
        if not self.request_is_allowed(mutating=True):
            self.send_json({"error": "Cross-origin request blocked"}, HTTPStatus.FORBIDDEN)
            return
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "trades"]:
            try:
                self.update_trade(int(parts[2]), self.read_json())
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if len(parts) == 3 and parts[:2] == ["api", "positions"]:
            try:
                self.update_position(int(parts[2]), self.read_json())
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if len(parts) == 3 and parts[:2] == ["api", "cashflows"]:
            try:
                self.update_cashflow(int(parts[2]), self.read_json())
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if len(parts) == 3 and parts[:2] == ["api", "snapshots"]:
            try:
                self.update_snapshot(int(parts[2]), self.read_json())
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if len(parts) == 3 and parts[:2] == ["api", "strategies"]:
            try:
                self.update_strategy(int(parts[2]), self.read_json())
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        if not self.request_is_allowed(mutating=True):
            self.send_json({"error": "Cross-origin request blocked"}, HTTPStatus.FORBIDDEN)
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] in {"cashflows", "snapshots"}:
            table = "cashflows" if parts[1] == "cashflows" else "account_snapshots"
            try:
                record_id = int(parts[2])
            except ValueError:
                self.send_json({"error": "Invalid record id"}, HTTPStatus.BAD_REQUEST)
                return
            with connect() as db:
                cur = db.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
                if cur.rowcount == 0:
                    self.send_json({"error": "Record not found"}, HTTPStatus.NOT_FOUND)
                    return
                sync_account_value(db)
                self.send_json({"deleted": True, "id": record_id})
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def create_trade(self, p: dict) -> None:
        ticker = str(p["ticker"]).strip().upper()
        entry, stop, target = (float(p[k]) for k in ("entry", "stop", "target"))
        risk_pct = float(p["riskPct"])
        account = float(p["accountValue"])
        if not ticker or min(entry, stop, target, account, risk_pct) <= 0:
            raise ValueError("모든 가격과 계좌 값은 0보다 커야 합니다.")
        distance = entry - stop
        if distance <= 0 or target <= entry:
            raise ValueError("Long 거래는 Stop < Entry < Target이어야 합니다.")
        risk_amount = account * risk_pct / 100
        rr = (target - entry) / distance
        with connect() as db:
            settings = get_settings(db)
            timeline = build_equity_timeline(db)
            total_assets = float(timeline[-1]["value"] if timeline else account)
            imported_value = db.execute("SELECT COALESCE(SUM(current_price*quantity),0) AS value FROM positions WHERE status='active'").fetchone()["value"]
            active_value = db.execute("SELECT COALESCE(SUM(entry*quantity),0) AS value FROM trades WHERE status='active'").fetchone()["value"]
            ticker_value = db.execute("SELECT COALESCE(SUM(current_price*quantity),0) AS value FROM positions WHERE status='active' AND ticker=?", (ticker,)).fetchone()["value"]
            ticker_value += db.execute("SELECT COALESCE(SUM(entry*quantity),0) AS value FROM trades WHERE status='active' AND ticker=?", (ticker,)).fetchone()["value"]
            risk_qty = math.floor(risk_amount / distance)
            cash_qty = math.floor(max(total_assets - float(imported_value) - float(active_value), 0) / entry)
            concentration_room = max(total_assets * settings["maxPositionPct"] / 100 - float(ticker_value), 0)
            concentration_qty = math.floor(concentration_room / entry)
            quantity = min(risk_qty, cash_qty, concentration_qty)
            if quantity < 1:
                raise ValueError("가용 자산 또는 단일 종목 50% 한도로 매수 가능한 수량이 없습니다.")
            risk_amount = quantity * distance
            risk_pct = risk_amount / account * 100
            if not db.execute("SELECT 1 FROM account_snapshots LIMIT 1").fetchone():
                db.execute(
                    "INSERT INTO account_snapshots(value, note, recorded_at) VALUES(?,?,?)",
                    (account, "Trade planner initial balance", datetime.now().date().isoformat()),
                )
            cur = db.execute(
                """INSERT INTO trades
                (ticker, thesis, setup, status, entry, stop, target, quantity,
                 risk_amount, risk_pct, rr, notes, created_at, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker, str(p.get("thesis", "")), str(p.get("setup", "Pullback")),
                    str(p.get("status", "planned")), entry, stop, target, quantity,
                    risk_amount, risk_pct, rr, str(p.get("notes", "")), now_iso(),
                    json.dumps(p.get("evidence", {}), ensure_ascii=False),
                ),
            )
            row = db.execute("SELECT * FROM trades WHERE id = ?", (cur.lastrowid,)).fetchone()
            self.send_json(as_dict(row), HTTPStatus.CREATED)

    def create_position_action(self, position_id: int, p: dict) -> None:
        action_type = str(p["actionType"])
        if action_type not in {"buy", "sell", "stop_update"}:
            raise ValueError("지원하지 않는 포지션 관리 행동입니다.")
        reason = str(p.get("primaryReason", "")).strip()
        if not reason:
            raise ValueError("핵심 실행 근거를 선택하세요.")
        occurred_at = str(p.get("occurredAt") or datetime.now().date().isoformat())
        with connect() as db:
            row = db.execute("SELECT * FROM positions WHERE id=? AND status='active'", (position_id,)).fetchone()
            if not row:
                self.send_json({"error": "Active position not found"}, HTTPStatus.NOT_FOUND)
                return
            old_qty, old_avg = float(row["quantity"]), float(row["average_price"])
            stop_after = float(p["stopAfter"]) if p.get("stopAfter") not in (None, "") else row["current_stop"]
            price = float(p["price"]) if p.get("price") not in (None, "") else None
            quantity = float(p.get("quantity") or 0)
            fee = float(p.get("fee") or 0)
            changes = {}
            realized = 0.0
            if action_type == "buy":
                if not price or min(price, quantity) <= 0:
                    raise ValueError("추가 매수 가격과 수량은 0보다 커야 합니다.")
                timeline = build_equity_timeline(db)
                settings = get_settings(db)
                total_assets = float(timeline[-1]["value"] if timeline else settings["accountValue"])
                invested = db.execute("SELECT COALESCE(SUM(current_price*quantity),0) AS value FROM positions WHERE status='active'").fetchone()["value"]
                invested += db.execute("SELECT COALESCE(SUM(entry*quantity),0) AS value FROM trades WHERE status='active'").fetchone()["value"]
                new_cost = price * quantity + fee
                ticker_after = float(row["current_price"]) * old_qty + new_cost
                if float(invested) + new_cost > total_assets + 0.01:
                    raise ValueError("가용 자산을 초과하는 추가 매수입니다.")
                if ticker_after > total_assets * settings["maxPositionPct"] / 100 + 0.01:
                    raise ValueError("단일 종목 최대 투자 비중 50%를 초과합니다.")
                new_qty = old_qty + quantity
                new_avg = (old_avg * old_qty + new_cost) / new_qty
                changes.update({"quantity": new_qty, "average_price": new_avg, "current_price": price})
                if row["initial_r"] is None and stop_after:
                    changes["initial_r"] = max((old_avg - float(stop_after)) * old_qty, 0)
            elif action_type == "sell":
                if not price or min(price, quantity) <= 0 or quantity >= old_qty:
                    raise ValueError("일부 매도 수량은 0보다 크고 현재 수량보다 작아야 합니다. 전량은 전체 종료를 사용하세요.")
                realized = (price - old_avg) * quantity - fee
                changes.update({"quantity": old_qty - quantity, "current_price": price,
                                "realized_pnl": float(row["realized_pnl"] or 0) + realized})
            else:
                if not stop_after or float(stop_after) <= 0:
                    raise ValueError("변경할 손절가를 입력하세요.")
                if row["initial_r"] is None:
                    changes["initial_r"] = max((old_avg - float(stop_after)) * old_qty, 0)
            if stop_after:
                changes["current_stop"] = float(stop_after)
            final_qty = float(changes.get("quantity", old_qty))
            final_avg = float(changes.get("average_price", old_avg))
            live_risk = max((final_avg - float(stop_after)) * final_qty, 0) if stop_after else 0
            changes["peak_live_risk"] = max(float(row["peak_live_risk"] or 0), live_risk)
            sql = ", ".join(f"{key}=?" for key in changes)
            db.execute(f"UPDATE positions SET {sql} WHERE id=?", (*changes.values(), position_id))
            cur = db.execute(
                """INSERT INTO position_actions(position_id, action_type, price, quantity, fee, occurred_at, primary_reason,
                supporting_json, warning_json, stop_after, realized_pnl, notes, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (position_id, action_type, price, quantity, fee, occurred_at, reason,
                 json.dumps(p.get("supporting", []), ensure_ascii=False), json.dumps(p.get("warnings", []), ensure_ascii=False),
                 stop_after, realized, str(p.get("notes", "")), now_iso()),
            )
            action = db.execute("SELECT * FROM position_actions WHERE id=?", (cur.lastrowid,)).fetchone()
            self.send_json({"action": as_dict(action), "position": as_dict(db.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone())}, HTTPStatus.CREATED)

    def create_position(self, p: dict) -> None:
        ticker = str(p["ticker"]).strip().upper()
        average_price = float(p["averagePrice"])
        quantity = float(p["quantity"])
        if not ticker or min(average_price, quantity) <= 0:
            raise ValueError("티커, 평균 매수가와 수량은 0보다 커야 합니다.")
        quote_row = latest_market_close(ticker)
        current_price = float(quote_row.get("price", average_price))
        opened_at = str(p.get("openedAt") or datetime.now().date().isoformat())
        with connect() as db:
            cur = db.execute(
                """INSERT INTO positions
                (ticker, average_price, quantity, current_price, opened_at, notes, evidence_json, created_at, price_as_of, price_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker, average_price, quantity, current_price, opened_at,
                    str(p.get("notes", "")),
                    json.dumps(p.get("evidence", {}), ensure_ascii=False), now_iso(),
                    quote_row.get("asOf"), now_iso() if "price" in quote_row else None,
                ),
            )
            row = db.execute("SELECT * FROM positions WHERE id = ?", (cur.lastrowid,)).fetchone()
            db.execute(
                """INSERT INTO position_actions(position_id, action_type, price, quantity, occurred_at, primary_reason, notes, created_at)
                VALUES(?, 'buy', ?, ?, ?, '최초 포지션 등록', 'Import position', ?)""",
                (cur.lastrowid, average_price, quantity, opened_at, now_iso()),
            )
            self.send_json(as_dict(row), HTTPStatus.CREATED)

    def create_snapshot(self, p: dict) -> None:
        value = float(p["value"])
        if value <= 0:
            raise ValueError("자산은 0보다 커야 합니다.")
        recorded_at = str(p.get("recordedAt") or datetime.now().date().isoformat())
        with connect() as db:
            cur = db.execute(
                "INSERT INTO account_snapshots(value, note, recorded_at) VALUES(?, ?, ?)",
                (value, str(p.get("note", "")), recorded_at),
            )
            sync_account_value(db)
            row = db.execute("SELECT * FROM account_snapshots WHERE id = ?", (cur.lastrowid,)).fetchone()
            self.send_json(as_dict(row), HTTPStatus.CREATED)

    def create_cashflow(self, p: dict) -> None:
        flow_type = str(p["flowType"])
        amount = float(p["amount"])
        if flow_type not in {"deposit", "withdrawal"}:
            raise ValueError("입금 또는 출금을 선택하세요.")
        if amount <= 0:
            raise ValueError("금액은 0보다 커야 합니다.")
        recorded_at = str(p.get("recordedAt") or datetime.now().date().isoformat())
        with connect() as db:
            if not db.execute("SELECT 1 FROM account_snapshots LIMIT 1").fetchone():
                raise ValueError("먼저 초기 총자산을 기록하세요.")
            cur = db.execute(
                "INSERT INTO cashflows(flow_type, amount, note, recorded_at, created_at) VALUES(?,?,?,?,?)",
                (flow_type, amount, str(p.get("note", "")), recorded_at, now_iso()),
            )
            sync_account_value(db)
            row = db.execute("SELECT * FROM cashflows WHERE id = ?", (cur.lastrowid,)).fetchone()
            self.send_json(as_dict(row), HTTPStatus.CREATED)

    def create_strategy(self, p: dict) -> None:
        mode, group, label = str(p.get("mode", "swing")), str(p["group"]).strip(), str(p["label"]).strip()
        if mode not in {"swing", "day"} or not group or not label:
            raise ValueError("모드, 섹션과 전략 이름을 입력하세요.")
        with connect() as db:
            try:
                cur = db.execute("INSERT INTO strategy_catalog(mode,group_name,label,created_at) VALUES(?,?,?,?)", (mode, group, label, now_iso()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 섹션에 동일한 전략이 이미 있습니다.") from exc
            self.send_json(as_dict(db.execute("SELECT * FROM strategy_catalog WHERE id=?", (cur.lastrowid,)).fetchone()), HTTPStatus.CREATED)

    def update_strategy(self, strategy_id: int, p: dict) -> None:
        active = 1 if bool(p["active"]) else 0
        with connect() as db:
            row = db.execute("SELECT * FROM strategy_catalog WHERE id=?", (strategy_id,)).fetchone()
            if not row:
                self.send_json({"error": "Strategy not found"}, HTTPStatus.NOT_FOUND);return
            db.execute("UPDATE strategy_catalog SET active=? WHERE id=?", (active, strategy_id))
            self.send_json(as_dict(db.execute("SELECT * FROM strategy_catalog WHERE id=?", (strategy_id,)).fetchone()))

    def create_day_trade(self, p: dict) -> None:
        ticker = str(p["ticker"]).strip().upper();entry=float(p["entryPrice"]);entry_qty=float(p["entryQuantity"]);exit_price=float(p["exitPrice"]);exit_qty=float(p["exitQuantity"]);fees=float(p.get("fees") or 0)
        if not ticker or min(entry, entry_qty, exit_price, exit_qty) <= 0 or abs(entry_qty-exit_qty) > 1e-8:
            raise ValueError("완료된 데이 거래는 매수·매도 수량이 같고 모든 값이 0보다 커야 합니다.")
        pnl=(exit_price-entry)*exit_qty-fees;trade_date=str(p.get("tradeDate") or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat())
        strategies=[str(item) for item in p.get("strategies", [])]
        with connect() as db:
            cur=db.execute("""INSERT INTO day_trades(ticker,trade_date,entry_price,entry_quantity,exit_price,exit_quantity,fees,pnl,strategies_json,notes,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(ticker,trade_date,entry,entry_qty,exit_price,exit_qty,fees,pnl,json.dumps(strategies,ensure_ascii=False),str(p.get("notes","")),now_iso()))
            self.send_json(as_dict(db.execute("SELECT * FROM day_trades WHERE id=?",(cur.lastrowid,)).fetchone()),HTTPStatus.CREATED)

    def create_day_journal(self, p: dict) -> None:
        body=str(p["body"]).strip();day_trade_id=p.get("dayTradeId")
        if not body: raise ValueError("저널 내용을 입력하세요.")
        with connect() as db:
            trade=db.execute("SELECT ticker,trade_date FROM day_trades WHERE id=?",(day_trade_id,)).fetchone()
            if not trade: raise ValueError("연결할 데이 거래를 찾을 수 없습니다.")
            ticker=str(p.get("ticker") or trade["ticker"]).strip().upper();trade_date=str(p.get("tradeDate") or trade["trade_date"])
            cur=db.execute("INSERT INTO day_journal(day_trade_id,ticker,body,trade_date,created_at) VALUES(?,?,?,?,?)",(day_trade_id,ticker,body,trade_date,now_iso()))
            self.send_json(as_dict(db.execute("SELECT * FROM day_journal WHERE id=?",(cur.lastrowid,)).fetchone()),HTTPStatus.CREATED)

    def update_cashflow(self, record_id: int, p: dict) -> None:
        flow_type = str(p["flowType"])
        amount = float(p["amount"])
        if flow_type not in {"deposit", "withdrawal"} or amount <= 0:
            raise ValueError("종류와 금액을 확인하세요.")
        with connect() as db:
            cur = db.execute(
                "UPDATE cashflows SET flow_type=?, amount=?, note=?, recorded_at=? WHERE id=?",
                (flow_type, amount, str(p.get("note", "")), str(p["recordedAt"]), record_id),
            )
            if cur.rowcount == 0:
                self.send_json({"error": "Record not found"}, HTTPStatus.NOT_FOUND)
                return
            sync_account_value(db)
            row = db.execute("SELECT * FROM cashflows WHERE id=?", (record_id,)).fetchone()
            self.send_json(as_dict(row))

    def update_snapshot(self, record_id: int, p: dict) -> None:
        value = float(p["value"])
        if value <= 0:
            raise ValueError("총자산은 0보다 커야 합니다.")
        with connect() as db:
            cur = db.execute(
                "UPDATE account_snapshots SET value=?, note=?, recorded_at=? WHERE id=?",
                (value, str(p.get("note", "")), str(p["recordedAt"]), record_id),
            )
            if cur.rowcount == 0:
                self.send_json({"error": "Record not found"}, HTTPStatus.NOT_FOUND)
                return
            sync_account_value(db)
            row = db.execute("SELECT * FROM account_snapshots WHERE id=?", (record_id,)).fetchone()
            self.send_json(as_dict(row))

    def update_position(self, position_id: int, p: dict) -> None:
        with connect() as db:
            row = db.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
            if not row:
                self.send_json({"error": "Position not found"}, HTTPStatus.NOT_FOUND)
                return
            changes = {}
            if "currentPrice" in p:
                current_price = float(p["currentPrice"])
                if current_price <= 0:
                    raise ValueError("현재가는 0보다 커야 합니다.")
                changes["current_price"] = current_price
            if p.get("status") == "closed":
                exit_price = float(p["exitPrice"])
                if exit_price <= 0:
                    raise ValueError("청산가는 0보다 커야 합니다.")
                changes.update({
                    "status": "closed", "exit_price": exit_price,
                    "closed_at": str(p.get("closedAt") or datetime.now().date().isoformat()),
                    "result_pct": round((exit_price / float(row["average_price"]) - 1) * 100, 4),
                    "current_price": exit_price,
                    "exit_review_json": json.dumps(p.get("exitReview", {}), ensure_ascii=False),
                })
            if not changes:
                raise ValueError("변경할 값이 없습니다.")
            sql = ", ".join(f"{key} = ?" for key in changes)
            db.execute(f"UPDATE positions SET {sql} WHERE id = ?", (*changes.values(), position_id))
            if changes.get("status") == "closed":
                pnl = float(row["realized_pnl"] or 0) + (float(changes["exit_price"]) - float(row["average_price"])) * float(row["quantity"])
                db.execute(
                    """INSERT INTO realized_events(source_kind, source_id, amount, note, recorded_at)
                    VALUES('position', ?, ?, ?, ?)
                    ON CONFLICT(source_kind, source_id) DO UPDATE SET amount=excluded.amount, note=excluded.note, recorded_at=excluded.recorded_at""",
                    (position_id, pnl, f"{row['ticker']} imported position P&L", changes["closed_at"]),
                )
                sync_account_value(db)
            updated = db.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
            self.send_json(as_dict(updated))

    def update_trade(self, trade_id: int, p: dict) -> None:
        with connect() as db:
            trade = db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not trade:
                self.send_json({"error": "Trade not found"}, HTTPStatus.NOT_FOUND)
                return
            changes = {}
            if p.get("status") == "active":
                changes["status"] = "active"
            if p.get("status") == "closed":
                exit_price = float(p["exitPrice"])
                if exit_price <= 0:
                    raise ValueError("종료가는 0보다 커야 합니다.")
                closed_at = str(p.get("closedAt") or datetime.now().date().isoformat())
                pnl = (exit_price - float(trade["entry"])) * int(trade["quantity"])
                result_r = (exit_price - float(trade["entry"])) / (float(trade["entry"]) - float(trade["stop"]))
                changes.update({"status": "closed", "exit_price": exit_price, "closed_at": closed_at, "result_r": result_r, "realized_pnl": pnl, "exit_review_json": json.dumps(p.get("exitReview", {}), ensure_ascii=False)})
                db.execute(
                    """INSERT INTO realized_events(source_kind, source_id, amount, note, recorded_at)
                    VALUES('trade', ?, ?, ?, ?)
                    ON CONFLICT(source_kind, source_id) DO UPDATE SET amount=excluded.amount, note=excluded.note, recorded_at=excluded.recorded_at""",
                    (trade_id, pnl, f"{trade['ticker']} trade P&L", closed_at),
                )
            if "notes" in p:
                changes["notes"] = str(p["notes"])
            if not changes:
                raise ValueError("변경할 값이 없습니다.")
            sql = ", ".join(f"{key} = ?" for key in changes)
            db.execute(f"UPDATE trades SET {sql} WHERE id = ?", (*changes.values(), trade_id))
            if changes.get("status") == "closed":
                sync_account_value(db)
            row = db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            self.send_json(as_dict(row))

    def refresh_exit_observations(self) -> None:
        updated = 0
        errors = []
        today = datetime.now().date()
        with connect() as db:
            items = []
            for kind, table in (("trade", "trades"), ("position", "positions")):
                for row in db.execute(f"SELECT id, ticker, closed_at, exit_price FROM {table} WHERE status='closed'"):
                    items.append((kind, table, as_dict(row)))
            for kind, table, item in items:
                try:
                    closed_date = datetime.fromisoformat(item["closed_at"]).date()
                    end_date = min(today, closed_date + timedelta(days=45))
                    series = market_series(item["ticker"], item["closed_at"], end_date.isoformat())
                    after = [row for row in series if row["date"] > closed_date.isoformat()]
                    exit_price = float(item["exit_price"])
                    horizons = {}
                    for horizon in (1, 5, 10, 20):
                        if len(after) >= horizon:
                            point = after[horizon - 1]
                            horizons[str(horizon)] = {
                                "date": point["date"], "price": round(point["price"], 4),
                                "returnPct": round((point["price"] / exit_price - 1) * 100, 2),
                            }
                    observed = after[:20]
                    returns = [(row["price"] / exit_price - 1) * 100 for row in observed]
                    post = {
                        "horizons": horizons, "availableDays": len(after),
                        "mfePct": round(max(returns), 2) if returns else None,
                        "maePct": round(min(returns), 2) if returns else None,
                    }
                    db.execute(
                        f"UPDATE {table} SET post_exit_json=?, post_exit_updated_at=? WHERE id=?",
                        (json.dumps(post, ensure_ascii=False), now_iso(), item["id"]),
                    )
                    updated += 1
                except Exception as exc:
                    errors.append({"ticker": item["ticker"], "error": str(exc)})
        self.send_json({"updated": updated, "errors": errors})

    def create_journal(self, p: dict) -> None:
        title = str(p["title"]).strip()
        if not title:
            raise ValueError("제목을 입력하세요.")
        with connect() as db:
            cur = db.execute(
                "INSERT INTO journal(trade_id, title, body, mood, created_at) VALUES(?, ?, ?, ?, ?)",
                (p.get("tradeId"), title, str(p.get("body", "")), str(p.get("mood", "Neutral")), now_iso()),
            )
            row = db.execute("SELECT * FROM journal WHERE id = ?", (cur.lastrowid,)).fetchone()
            self.send_json(as_dict(row), HTTPStatus.CREATED)

    def update_settings(self, p: dict) -> None:
        mapping = {
            "accountValue": "account_value",
            "goalValue": "goal_value",
            "currency": "currency",
            "maxTradeRiskPct": "max_trade_risk_pct",
            "maxPortfolioHeatPct": "max_portfolio_heat_pct",
            "maxPositionPct": "max_position_pct",
        }
        with connect() as db:
            for source, target in mapping.items():
                if source in p:
                    db.execute(
                        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (target, str(p[source])),
                    )
            self.send_json(get_settings(db))

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (WEB / relative).resolve()
        if WEB.resolve() not in file.parents and file != WEB.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file.is_file():
            file = WEB / "index.html"
        body = file.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    init_db()
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"Investment Beta could not start: port {port} is already in use.")
        print("Close the previous Investment Beta window and run start.cmd again.")
        raise SystemExit(1) from exc
    print(f"Investment Beta is running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.8, webbrowser.open, args=(f"http://{host}:{port}",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Investment Beta...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
