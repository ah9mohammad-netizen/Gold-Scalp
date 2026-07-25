"""SQLite persistence for the XAU-USDT paper-trading service.

The database lives on the Railway Volume at ``/data/history.db``.  Every setup
that becomes a paper order is retained with its indicator snapshot, and every
closed order adds one immutable account-history row.  The schema is migrated in
place so an existing Railway volume remains usable after deployments.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import config

logger = logging.getLogger("DatabaseEngine")


class DatabaseEngine:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            if config.DATABASE_URL.startswith("sqlite:///"):
                self.db_path = config.DATABASE_URL.replace("sqlite:///", "", 1)
            else:
                self.db_path = config.DB_PATH
        else:
            self.db_path = db_path
        self._ensure_directory()
        self._init_db()

    def _ensure_directory(self) -> None:
        """Create the target directory; locally fall back if /data is unavailable."""
        abs_path = os.path.abspath(self.db_path)
        directory = os.path.dirname(abs_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                logger.info("Created database directory: %s", directory)
            except PermissionError:
                fallback = os.path.abspath("history.db")
                logger.warning("Cannot create %s; using %s", directory, fallback)
                self.db_path = fallback

    def _get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        connection.execute("PRAGMA busy_timeout=30000;")
        return connection

    @staticmethod
    def _add_missing_columns(
        cursor: sqlite3.Cursor, table: str, columns: Dict[str, str]
    ) -> None:
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _init_db(self) -> None:
        """Create or safely upgrade the persistent schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    bar_timestamp_ms INTEGER,
                    source TEXT,
                    strategy_version TEXT,
                    setup_name TEXT,
                    reference_price REAL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    sl_price REAL NOT NULL,
                    tp1_price REAL NOT NULL,
                    tp2_price REAL NOT NULL,
                    size_oz REAL,
                    leverage INTEGER,
                    dollar_risk REAL,
                    zscore REAL,
                    adx REAL,
                    atr_usd REAL,
                    spread_usd REAL,
                    layer1_regime TEXT,
                    layer2_structure TEXT,
                    layer3_momentum TEXT,
                    status TEXT NOT NULL,
                    reason TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    source TEXT,
                    candle_timestamp_ms INTEGER,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    reference_price REAL,
                    entry_price REAL NOT NULL,
                    sl_price REAL NOT NULL,
                    tp1_price REAL NOT NULL,
                    tp2_price REAL NOT NULL,
                    size_oz REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    required_margin_usd REAL NOT NULL,
                    entry_fee_usd REAL NOT NULL DEFAULT 0.0,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    exit_fee_usd REAL NOT NULL DEFAULT 0.0,
                    gross_pnl_usd REAL,
                    pnl_usd REAL DEFAULT 0.0,
                    pnl_pct REAL DEFAULT 0.0,
                    exit_reason TEXT,
                    status TEXT NOT NULL,
                    FOREIGN KEY (signal_id) REFERENCES signals (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS account_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    balance_before REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    change_usd REAL NOT NULL,
                    change_reason TEXT NOT NULL,
                    trade_id INTEGER,
                    FOREIGN KEY (trade_id) REFERENCES trades (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Upgrade databases made by earlier versions without data loss.
            self._add_missing_columns(
                cursor,
                "signals",
                {
                    "bar_timestamp_ms": "INTEGER",
                    "source": "TEXT",
                    "strategy_version": "TEXT",
                    "setup_name": "TEXT",
                    "reference_price": "REAL",
                    "zscore": "REAL",
                    "adx": "REAL",
                    "atr_usd": "REAL",
                    "spread_usd": "REAL",
                },
            )
            self._add_missing_columns(
                cursor,
                "trades",
                {
                    "source": "TEXT",
                    "candle_timestamp_ms": "INTEGER",
                    "reference_price": "REAL",
                    "entry_fee_usd": "REAL NOT NULL DEFAULT 0.0",
                    "exit_fee_usd": "REAL NOT NULL DEFAULT 0.0",
                    "gross_pnl_usd": "REAL",
                },
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_bar ON signals(bar_timestamp_ms)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status, opened_at)"
            )

            cursor.execute("SELECT COUNT(*) FROM account_history")
            if int(cursor.fetchone()[0]) == 0:
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO account_history
                    (timestamp, balance_before, balance_after, change_usd, change_reason, trade_id)
                    VALUES (?, ?, ?, ?, 'INITIAL_DEPOSIT', NULL)
                    """,
                    (now, 0.0, config.INITIAL_BALANCE_USDT, config.INITIAL_BALANCE_USDT),
                )
                logger.info(
                    "Initialized paper account with $%.2f USDT in %s",
                    config.INITIAL_BALANCE_USDT,
                    self.db_path,
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Account and risk views
    # ------------------------------------------------------------------
    def get_current_balance(self) -> float:
        """Realized cash balance. Open PnL is intentionally kept separate."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT balance_after FROM account_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return float(row["balance_after"]) if row else config.INITIAL_BALANCE_USDT

    def get_initial_balance(self) -> float:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT balance_after FROM account_history
                WHERE change_reason = 'INITIAL_DEPOSIT' ORDER BY id ASC LIMIT 1
                """
            ).fetchone()
            return float(row["balance_after"]) if row else config.INITIAL_BALANCE_USDT

    def get_daily_realized_pnl(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(pnl_usd), 0.0) AS day_pnl FROM trades
                WHERE status = 'CLOSED' AND closed_at LIKE ?
                """,
                (f"{today}%",),
            ).fetchone()
            return float(row["day_pnl"] or 0.0)

    def count_trades_opened_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM trades WHERE opened_at LIKE ?", (f"{today}%",)
            ).fetchone()
            return int(row["count"] or 0)

    def get_account_snapshot(self, mark_price: float = 0.0) -> Dict[str, float]:
        """Return realized balance, marked equity and margin usage for Telegram."""
        balance = self.get_current_balance()
        used_margin = 0.0
        unrealized = 0.0
        for trade in self.get_open_trades():
            entry = float(trade["entry_price"])
            size = float(trade["size_oz"])
            mark = float(mark_price) if mark_price > 0 else entry
            gross = (mark - entry) * size if trade["direction"] == "LONG" else (entry - mark) * size
            entry_fee = float(trade.get("entry_fee_usd") or 0.0)
            estimated_exit_fee = mark * size * config.PAPER_TAKER_FEE_RATE
            unrealized += gross - entry_fee - estimated_exit_fee
            used_margin += float(trade["required_margin_usd"])
        equity = balance + unrealized
        return {
            "balance": round(balance, 2),
            "unrealized_pnl_usd": round(unrealized, 2),
            "equity": round(equity, 2),
            "used_margin_usd": round(used_margin, 2),
            "free_margin_usd": round(max(0.0, equity - used_margin), 2),
        }

    # ------------------------------------------------------------------
    # Signals and trades
    # ------------------------------------------------------------------
    def has_signal_for_bar(self, bar_timestamp_ms: Optional[int]) -> bool:
        """Idempotency guard for a restart during a completed candle."""
        if not bar_timestamp_ms:
            return False
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM signals WHERE bar_timestamp_ms = ?
                AND status IN ('NEW', 'EXECUTED') LIMIT 1
                """,
                (int(bar_timestamp_ms),),
            ).fetchone()
            return row is not None

    def save_signal(self, signal_data: Dict[str, Any]) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    timestamp, bar_timestamp_ms, source, strategy_version, setup_name, reference_price,
                    symbol, direction, entry_price, sl_price, tp1_price, tp2_price,
                    size_oz, leverage, dollar_risk, zscore, adx, atr_usd, spread_usd,
                    layer1_regime, layer2_structure, layer3_momentum, status, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_data["timestamp"],
                    signal_data.get("bar_timestamp_ms"),
                    signal_data.get("source"),
                    signal_data.get("strategy_version"),
                    signal_data.get("setup_name"),
                    signal_data.get("reference_price"),
                    signal_data["symbol"],
                    signal_data["direction"],
                    signal_data["entry_price"],
                    signal_data["sl_price"],
                    signal_data["tp1_price"],
                    signal_data["tp2_price"],
                    signal_data.get("size_oz"),
                    signal_data.get("leverage"),
                    signal_data.get("dollar_risk"),
                    signal_data.get("zscore"),
                    signal_data.get("adx"),
                    signal_data.get("atr_at_entry"),
                    signal_data.get("spread"),
                    signal_data.get("layer1_regime", "PASSED"),
                    signal_data.get("layer2_structure", "STRUCTURAL_BREAK"),
                    signal_data.get("layer3_momentum", "MOMENTUM_OK"),
                    signal_data.get("status", "NEW"),
                    signal_data.get("reason", signal_data.get("layer2_structure", "")),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_signal_status(self, signal_id: int, status: str) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE signals SET status = ? WHERE id = ?", (status, signal_id))
            conn.commit()

    def open_trade(self, trade_data: Dict[str, Any]) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades (
                    signal_id, source, candle_timestamp_ms, symbol, direction, reference_price,
                    entry_price, sl_price, tp1_price, tp2_price, size_oz, leverage,
                    required_margin_usd, entry_fee_usd, opened_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (
                    trade_data.get("signal_id"),
                    trade_data.get("source"),
                    trade_data.get("bar_timestamp_ms"),
                    trade_data["symbol"],
                    trade_data["direction"],
                    trade_data.get("reference_price"),
                    trade_data["entry_price"],
                    trade_data["sl_price"],
                    trade_data["tp1_price"],
                    trade_data["tp2_price"],
                    trade_data["size_oz"],
                    trade_data["leverage"],
                    trade_data["required_margin_usd"],
                    trade_data.get("entry_fee_usd", 0.0),
                    trade_data["opened_at"],
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_trade_sl(self, trade_id: int, new_sl: float) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE trades SET sl_price = ? WHERE id = ? AND status = 'OPEN'",
                (new_sl, trade_id),
            )
            conn.commit()

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl_usd: float,
        pnl_pct: float,
        exit_reason: str,
        *,
        gross_pnl_usd: Optional[float] = None,
        exit_fee_usd: float = 0.0,
    ) -> bool:
        """Close once and atomically append the resulting realized balance."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "SELECT entry_fee_usd FROM trades WHERE id = ? AND status = 'OPEN'", (trade_id,)
            )
            existing = cursor.fetchone()
            if existing is None:
                conn.rollback()
                return False
            balance_row = conn.execute(
                "SELECT balance_after FROM account_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            balance_before = float(balance_row["balance_after"]) if balance_row else config.INITIAL_BALANCE_USDT
            balance_after = max(0.0, balance_before + pnl_usd)
            conn.execute(
                """
                UPDATE trades SET closed_at = ?, exit_price = ?, exit_fee_usd = ?, gross_pnl_usd = ?,
                    pnl_usd = ?, pnl_pct = ?, exit_reason = ?, status = 'CLOSED'
                WHERE id = ? AND status = 'OPEN'
                """,
                (
                    now,
                    round(exit_price, 4),
                    round(exit_fee_usd, 6),
                    gross_pnl_usd,
                    round(pnl_usd, 6),
                    round(pnl_pct, 4),
                    exit_reason,
                    trade_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO account_history
                (timestamp, balance_before, balance_after, change_usd, change_reason, trade_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, balance_before, balance_after, round(pnl_usd, 6), exit_reason, trade_id),
            )
            conn.commit()
        logger.info(
            "Trade #%s closed [%s] | net $%.2f | balance $%.2f",
            trade_id,
            exit_reason,
            pnl_usd,
            balance_after,
        )
        return True

    def get_open_trades(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def get_recent_signals(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_statistics(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            summary = conn.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(SUM(pnl_usd), 0.0) AS total_pnl,
                       COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd ELSE 0 END), 0.0) AS gross_profit,
                       COALESCE(SUM(CASE WHEN pnl_usd < 0 THEN ABS(pnl_usd) ELSE 0 END), 0.0) AS gross_loss,
                       COALESCE(SUM(entry_fee_usd + exit_fee_usd), 0.0) AS total_fees,
                       MAX(pnl_usd) AS best, MIN(pnl_usd) AS worst
                FROM trades WHERE status = 'CLOSED'
                """
            ).fetchone()
            total = int(summary["total"] or 0)
            wins = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM trades WHERE status = 'CLOSED' AND pnl_usd > 0"
                ).fetchone()["count"]
                or 0
            )
            losses = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM trades WHERE status = 'CLOSED' AND pnl_usd < 0"
                ).fetchone()["count"]
                or 0
            )
            reasons = {
                row["exit_reason"]: int(row["count"])
                for row in conn.execute(
                    "SELECT exit_reason, COUNT(*) AS count FROM trades WHERE status='CLOSED' GROUP BY exit_reason"
                ).fetchall()
            }

        balance = self.get_current_balance()
        initial = self.get_initial_balance()
        gross_loss = float(summary["gross_loss"] or 0.0)
        gross_profit = float(summary["gross_profit"] or 0.0)
        profit_factor = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0)
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100.0, 2) if total else 0.0,
            "total_pnl_usd": round(float(summary["total_pnl"] or 0.0), 2),
            "total_return_pct": round((balance - initial) / initial * 100.0, 2) if initial else 0.0,
            "profit_factor": round(profit_factor, 2),
            "best_trade_usd": round(float(summary["best"] or 0.0), 2),
            "worst_trade_usd": round(float(summary["worst"] or 0.0), 2),
            "total_fees_usd": round(float(summary["total_fees"] or 0.0), 2),
            "current_balance": round(balance, 2),
            "initial_balance": round(initial, 2),
            "exit_breakdown": reasons,
            "db_path": self.db_path,
        }

    # ------------------------------------------------------------------
    # Bot state and safe Telegram export
    # ------------------------------------------------------------------
    def set_state(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO bot_state(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
            conn.commit()

    def get_state(self, key: str, default: str = "") -> str:
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def create_export_snapshot(self) -> str:
        """Make a transactionally consistent DB copy for Telegram.

        Uploading only ``history.db`` while SQLite is in WAL mode can omit recent
        trades held in ``history.db-wal``. ``backup`` produces a standalone file
        that includes all committed pages without pausing the service.
        """
        export_dir = tempfile.mkdtemp(prefix="xau_history_")
        path = os.path.join(export_dir, "history.db")
        try:
            with self._get_connection() as source, sqlite3.connect(path) as target:
                source.backup(target)
                target.commit()
            return path
        except Exception:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            try:
                os.rmdir(export_dir)
            except OSError:
                pass
            raise


# Global database used by the Railway worker.
db = DatabaseEngine()
