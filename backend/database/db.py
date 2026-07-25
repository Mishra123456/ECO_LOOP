"""
SQLite Database Manager — Async operations for Eco-Loop
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger("eco-loop.db")


class DatabaseManager:
    def __init__(self, db_path: str = "eco_loop.db"):
        self.db_path = db_path

    async def initialize(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_number INTEGER,
                    timestamp TEXT,
                    building_state TEXT,
                    agent_reasoning TEXT,
                    actions_taken TEXT,
                    energy_savings_pct REAL,
                    comfort_score REAL,
                    carbon_saved_kg REAL,
                    cost_saved_usd REAL,
                    total_power_kw REAL,
                    cycle_duration_ms REAL,
                    agent_type TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    zone_id TEXT,
                    anomaly_type TEXT,
                    severity TEXT,
                    value REAL,
                    resolved INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_cycles_timestamp ON cycles(timestamp)
            """)
            await db.commit()
        logger.info(f"Database initialized: {self.db_path}")

    async def log_cycle(self, metrics: Dict):
        try:
            async with aiosqlite.connect(self.db_path) as db:
                state = metrics.get("building_state", {})
                await db.execute("""
                    INSERT INTO cycles
                    (cycle_number, timestamp, building_state, agent_reasoning,
                     actions_taken, energy_savings_pct, comfort_score,
                     carbon_saved_kg, cost_saved_usd, total_power_kw, cycle_duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metrics.get("cycle"),
                    metrics.get("timestamp"),
                    json.dumps(state),
                    metrics.get("agent_reasoning", ""),
                    json.dumps(metrics.get("actions_taken", [])),
                    state.get("energy_savings_pct", 0),
                    state.get("comfort_score", 0),
                    state.get("carbon_saved_kg", 0),
                    state.get("cost_saved_usd", 0),
                    state.get("total_power_kw", 0),
                    metrics.get("cycle_duration_ms", 0)
                ))
                await db.commit()
        except Exception as e:
            logger.error(f"DB log_cycle error: {e}")

    async def get_recent_cycles(self, limit: int = 100) -> List[Dict]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (limit,)
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"DB get_recent_cycles error: {e}")
            return []

    async def get_analytics_summary(self) -> Dict:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as total_cycles,
                        AVG(energy_savings_pct) as avg_savings_pct,
                        MAX(energy_savings_pct) as max_savings_pct,
                        AVG(comfort_score) as avg_comfort,
                        SUM(carbon_saved_kg) as total_carbon_saved,
                        SUM(cost_saved_usd) as total_cost_saved,
                        AVG(total_power_kw) as avg_power_kw,
                        AVG(cycle_duration_ms) as avg_cycle_ms
                    FROM cycles
                """)
                row = await cursor.fetchone()
                if row:
                    return {
                        "total_cycles": row[0] or 0,
                        "avg_savings_pct": round(row[1] or 0, 2),
                        "max_savings_pct": round(row[2] or 0, 2),
                        "avg_comfort": round(row[3] or 0, 3),
                        "total_carbon_saved_kg": round(row[4] or 0, 3),
                        "total_cost_saved_usd": round(row[5] or 0, 4),
                        "avg_power_kw": round(row[6] or 0, 3),
                        "avg_cycle_ms": round(row[7] or 0, 1)
                    }
        except Exception as e:
            logger.error(f"DB analytics error: {e}")
        return {}
