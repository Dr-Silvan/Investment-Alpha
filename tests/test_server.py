import tempfile
import unittest
import sqlite3
import json
import io
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import secure_store


class DatabaseTests(unittest.TestCase):
    def test_cross_origin_mutation_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/settings",
                        method="POST",
                        data=b'{"accountValue":1}',
                        headers={"Content-Type": "application/json", "Origin": "https://attacker.example"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request)
                    self.assertEqual(caught.exception.code, 403)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=3)

    def test_local_responses_include_security_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/dashboard") as response:
                        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=3)

    def test_latest_close_uses_latest_alpaca_completed_bar(self):
        bars = [
            {"date": "2026-08-27", "price": 161.38},
            {"date": "2026-08-28", "price": 157.74},
        ]
        with patch.object(server, "alpaca_bars", return_value=bars):
            quote = server.latest_market_close("APH")
        self.assertEqual(quote["price"], 157.74)
        self.assertEqual(quote["asOf"], "2026-08-28")

    def test_market_provider_credentials_are_dpapi_encrypted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider.bin"
            secure_store.save_credentials(path, "PKTEST123", "secret-value-123456")
            raw = path.read_bytes()
            self.assertNotIn(b"PKTEST123", raw)
            self.assertNotIn(b"secret-value", raw)
            self.assertEqual(
                secure_store.load_credentials(path),
                {"apiKey": "PKTEST123", "apiSecret": "secret-value-123456"},
            )

    def test_initial_database_has_expected_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    settings = server.get_settings(db)
                    self.assertEqual(settings["accountValue"], 50_000)
                    self.assertEqual(settings["goalValue"], 1_000_000)
                    self.assertEqual(settings["currency"], "USD")
                    self.assertEqual(settings["maxTradeRiskPct"], 1.0)
                    self.assertEqual(server.dashboard(db)["metrics"]["activeCount"], 0)

    def test_positions_and_snapshots_feed_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute(
                        "INSERT INTO positions(ticker, average_price, quantity, current_price, opened_at, created_at) VALUES(?,?,?,?,?,?)",
                        ("NVDA", 100, 10, 115, "2026-01-01", server.now_iso()),
                    )
                    db.execute(
                        "INSERT INTO account_snapshots(value, note, recorded_at) VALUES(?,?,?)",
                        (52_000, "test", "2026-08-26"),
                    )
                with server.connect() as db:
                    data = server.dashboard(db)
                    self.assertEqual(data["metrics"]["positionValue"], 1_150)
                    self.assertEqual(data["metrics"]["unrealizedPnl"], 150)
                    self.assertEqual(data["metrics"]["activeCount"], 1)
                    self.assertEqual(data["metrics"]["importedActiveCount"], 1)
                    self.assertEqual(len(data["snapshots"]), 1)

    def test_goal_projection_excludes_cash_contributions(self):
        settings = {"accountValue": 50_000, "goalValue": 100_000}
        year = server.datetime.now().year
        timeline = [
            {"recordedAt": f"{year}-01-01", "kind": "snapshot", "amount": 50_000, "value": 50_000},
            {"recordedAt": f"{year}-02-01", "kind": "deposit", "amount": 10_000, "value": 60_000},
            {"recordedAt": f"{year}-08-01", "kind": "snapshot", "amount": 66_000, "value": 66_000},
        ]
        result = server.performance_projection(timeline, settings)
        self.assertEqual(result["ytdReturnPct"], 12.0)
        self.assertEqual(result["goalStatus"], "estimated")

    def test_portfolio_period_return_uses_common_start_and_excludes_deposit(self):
        timeline = [
            {"recordedAt": "2026-01-01", "kind": "snapshot", "amount": 50_000, "value": 50_000},
            {"recordedAt": "2026-03-01", "kind": "deposit", "amount": 10_000, "value": 60_000},
            {"recordedAt": "2026-06-01", "kind": "snapshot", "amount": 65_000, "value": 65_000},
        ]
        result = server.portfolio_period_return(timeline, "2026-02-01")
        self.assertEqual(result["startDate"], "2026-02-01")
        self.assertEqual(result["returnPct"], 10.0)

    def test_online_portfolio_return_marks_holdings_to_latest_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute("INSERT INTO account_snapshots(value,note,recorded_at) VALUES(?,?,?)", (10_000, "initial", "2026-08-26"))
                    db.execute("INSERT INTO positions(ticker,average_price,quantity,current_price,opened_at,created_at) VALUES(?,?,?,?,?,?)", ("APH", 100, 10, 100, "2026-08-26", server.now_iso()))
                quote = {"ticker": "APH", "startPrice": 100, "lastPrice": 110, "startDate": "2026-08-26", "lastDate": "2026-08-27", "returnPct": 10, "source": "test"}
                with server.connect() as db, patch.object(server, "market_return", return_value=quote):
                    result = server.online_portfolio_return(db, "2026-08-26")
                self.assertEqual(result["endDate"], "2026-08-27")
                self.assertEqual(result["endValue"], 10_100)
                self.assertEqual(result["returnPct"], 1.0)

    def test_sector_etf_uses_its_representative_leader(self):
        result = server.sector_leader_for("XLU")
        self.assertEqual(result["sector"], "Utilities")
        self.assertEqual(result["sectorEtf"], "XLU")
        self.assertEqual(result["leader"], "NEE")

    def test_scale_in_records_rule_and_recalculates_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    cur = db.execute(
                        "INSERT INTO positions(ticker,average_price,quantity,current_price,opened_at,created_at) VALUES(?,?,?,?,?,?)",
                        ("APH", 100, 10, 105, "2026-01-01", server.now_iso()),
                    )
                    position_id = cur.lastrowid
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    payload = {"actionType": "buy", "price": 110, "quantity": 5, "fee": 0,
                               "stopAfter": 95, "primaryReason": "Drop Test 통과", "occurredAt": "2026-08-26"}
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/positions/{position_id}/actions",
                        method="POST", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request) as response:
                        result = json.load(response)
                    self.assertEqual(result["position"]["quantity"], 15)
                    self.assertAlmostEqual(result["position"]["average_price"], 103.3333333333)
                    self.assertEqual(result["position"]["initial_r"], 50)
                    self.assertEqual(result["action"]["primary_reason"], "Drop Test 통과")
                finally:
                    httpd.shutdown();httpd.server_close()

    def test_online_close_refresh_updates_active_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute(
                        "INSERT INTO positions(ticker, average_price, quantity, current_price, opened_at, created_at) VALUES(?,?,?,?,?,?)",
                        ("NVDA", 100, 2, 101, "2026-01-01", server.now_iso()),
                    )
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/positions/refresh-prices",
                        method="POST", data=b"{}", headers={"Content-Type": "application/json"},
                    )
                    quote = {"ticker": "NVDA", "price": 123.4567, "asOf": "2026-08-25", "source": "test"}
                    with patch.object(server, "latest_market_close", return_value=quote):
                        with urllib.request.urlopen(request) as response:
                            result = json.load(response)
                    self.assertEqual(result["updated"], 1)
                    with server.connect() as db:
                        position = db.execute("SELECT current_price, price_as_of FROM positions").fetchone()
                    self.assertEqual(position["current_price"], 123.4567)
                    self.assertEqual(position["price_as_of"], "2026-08-25")
                finally:
                    httpd.shutdown()
                    httpd.server_close()

    def test_closed_position_builds_strategy_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute(
                        """INSERT INTO positions
                        (ticker, average_price, quantity, current_price, opened_at, created_at,
                         evidence_json, status, exit_price, result_pct, closed_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        ("TEST", 100, 1, 110, "2026-01-01", server.now_iso(),
                         '{"차트 구조":["핵심 전략"]}', "closed", 110, 10, "2026-02-01"),
                    )
                with server.connect() as db:
                    stats = server.dashboard(db)["strategyStats"]
                    self.assertEqual(stats[0]["strategy"], "핵심 전략")
                    self.assertEqual(stats[0]["winRate"], 100.0)
                    self.assertEqual(stats[0]["averageReturnPct"], 10.0)

    def test_cashflows_recalculate_equity_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute(
                        "INSERT INTO account_snapshots(value, note, recorded_at) VALUES(?,?,?)",
                        (50_000, "initial", "2026-01-01"),
                    )
                    db.execute(
                        "INSERT INTO cashflows(flow_type, amount, note, recorded_at, created_at) VALUES(?,?,?,?,?)",
                        ("deposit", 5_000, "deposit", "2026-02-01", server.now_iso()),
                    )
                    db.execute(
                        "INSERT INTO cashflows(flow_type, amount, note, recorded_at, created_at) VALUES(?,?,?,?,?)",
                        ("withdrawal", 2_000, "withdrawal", "2026-03-01", server.now_iso()),
                    )
                    server.sync_account_value(db)
                with server.connect() as db:
                    timeline = server.build_equity_timeline(db)
                    self.assertEqual([row["value"] for row in timeline], [50_000, 55_000, 53_000])
                    self.assertEqual(server.get_settings(db)["accountValue"], 53_000)

    def test_realized_trade_pnl_is_added_to_equity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    db.execute("INSERT INTO account_snapshots(value, note, recorded_at) VALUES(?,?,?)", (50_000, "initial", "2026-01-01"))
                    db.execute("INSERT INTO realized_events(source_kind, source_id, amount, note, recorded_at) VALUES(?,?,?,?,?)", ("trade", 1, 750, "profit", "2026-02-01"))
                    server.sync_account_value(db)
                with server.connect() as db:
                    timeline = server.build_equity_timeline(db)
                    self.assertEqual(timeline[-1]["kind"], "trade_pnl")
                    self.assertEqual(timeline[-1]["value"], 50_750)

    def test_trade_http_lifecycle_closes_into_asset_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_port}"
                def request(path, method, payload):
                    req = urllib.request.Request(
                        base + path, method=method,
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        return json.load(response)
                try:
                    trade = request("/api/trades", "POST", {
                        "ticker": "TEST", "entry": 100, "stop": 95, "target": 110,
                        "riskPct": 1, "accountValue": 50_000,
                    })
                    request(f"/api/trades/{trade['id']}", "PATCH", {"status": "active"})
                    closed = request(f"/api/trades/{trade['id']}", "PATCH", {
                        "status": "closed", "exitPrice": 110, "closedAt": server.datetime.now().date().isoformat(),
                        "exitReview": {"ruleBased": True, "계획된 청산": ["목표가 도달"]},
                    })
                    self.assertEqual(closed["status"], "closed")
                    self.assertEqual(closed["realized_pnl"], 1_000)
                    self.assertIn("목표가 도달", closed["exit_review_json"])
                    with server.connect() as db:
                        self.assertEqual(server.build_equity_timeline(db)[-1]["value"], 51_000)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=3)

    def test_exit_quality_classification_separates_process_from_outcome(self):
        chicken = server.classify_exit(
            {"ruleBased": False, "심리·재량": ["수익 반납 공포"]},
            {"availableDays": 10, "horizons": {"10": {"returnPct": 6.5}}},
        )
        defended = server.classify_exit(
            {"ruleBased": True, "가격 구조 훼손": ["주요 지지선 이탈"]},
            {"availableDays": 10, "horizons": {"10": {"returnPct": -4.0}}},
        )
        self.assertEqual(chicken, "Chicken-out 가능성")
        self.assertEqual(defended, "잘 방어한 매도")

    def test_old_trade_schema_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db = sqlite3.connect(db_path)
            try:
                db.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY)")
                db.commit()
            finally:
                db.close()
            with patch.object(server, "DB_PATH", db_path), patch.object(server, "DATA", Path(tmp)):
                server.init_db()
                with server.connect() as db:
                    columns = {row["name"] for row in db.execute("PRAGMA table_info(trades)")}
                    self.assertIn("evidence_json", columns)


if __name__ == "__main__":
    unittest.main()
