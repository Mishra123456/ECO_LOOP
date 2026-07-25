"""
Eco-Loop Building Intelligence Platform
Main FastAPI Application
Honeywell Hackathon 2026
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.orchestrator import OrchestratorAgent
from simulation.building_sim import BuildingSimulator
from database.db import DatabaseManager
from mcp.server import MCPServer
from optimization.optimizer import EnergyOptimizer

# ─── Logging Setup ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("eco-loop")


# ─── Global State ────────────────────────────────────────────────────────────
class AppState:
    simulator: Optional[BuildingSimulator] = None
    orchestrator: Optional[OrchestratorAgent] = None
    db: Optional[DatabaseManager] = None
    mcp: Optional[MCPServer] = None
    optimizer: Optional[EnergyOptimizer] = None
    loop_running: bool = False
    connected_clients: List[WebSocket] = []
    loop_interval: int = 10  # seconds between control cycles
    current_metrics: Dict[str, Any] = {}


app_state = AppState()


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌱 Eco-Loop starting up...")
    app_state.db = DatabaseManager("eco_loop.db")
    await app_state.db.initialize()

    app_state.simulator = BuildingSimulator()
    app_state.simulator.initialize()

    app_state.optimizer = EnergyOptimizer()
    app_state.mcp = MCPServer(app_state.simulator, app_state.optimizer, app_state.db)

    app_state.orchestrator = OrchestratorAgent(
        mcp_server=app_state.mcp,
        model_name="phi3:mini"
    )

    logger.info("✅ All systems initialized. Ready for closed-loop control.")
    yield

    logger.info("🛑 Eco-Loop shutting down...")
    app_state.loop_running = False


app = FastAPI(
    title="Eco-Loop Building Intelligence API",
    description="Autonomous closed-loop building energy optimization platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Models ─────────────────────────────────────────────────────────
class ControlCommand(BaseModel):
    zone: str
    setpoint_heating: Optional[float] = None
    setpoint_cooling: Optional[float] = None
    hvac_mode: Optional[str] = None
    lighting_level: Optional[float] = None
    ventilation_rate: Optional[float] = None


class LoopConfig(BaseModel):
    interval_seconds: int = 10
    auto_mode: bool = True
    comfort_priority: float = 0.5  # 0=max energy savings, 1=max comfort


# ─── WebSocket Manager ────────────────────────────────────────────────────────
async def broadcast(message: Dict[str, Any]):
    """Broadcast message to all connected WebSocket clients."""
    if not app_state.connected_clients:
        return
    disconnected = []
    payload = json.dumps(message, default=str)
    for ws in app_state.connected_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        app_state.connected_clients.remove(ws)


# ─── Control Loop ─────────────────────────────────────────────────────────────
async def run_control_loop():
    """
    The closed-loop control cycle:
    1. Read EnergyPlus simulation state
    2. Send to LLM Orchestrator via MCP tools
    3. Agent reasons and selects actions
    4. Apply actions back to simulator
    5. Broadcast results to dashboard
    6. Log everything to DB
    7. Repeat
    """
    logger.info("🔄 Closed-loop control started.")
    cycle = 0

    while app_state.loop_running:
        cycle_start = time.time()
        cycle += 1

        try:
            # Step 1: Read building state from simulator
            building_state = app_state.simulator.get_state()
            building_state["cycle"] = cycle
            building_state["timestamp"] = datetime.now().isoformat()

            # Step 2: Run orchestrator agent (LLM reasoning + MCP tools)
            agent_result = await app_state.orchestrator.run_cycle(building_state)

            # Step 3: Apply agent decisions to simulator
            if agent_result.get("actions"):
                app_state.simulator.apply_actions(agent_result["actions"])

            # Step 4: Collect updated metrics
            updated_state = app_state.simulator.get_state()
            metrics = {
                "type": "cycle_update",
                "cycle": cycle,
                "timestamp": datetime.now().isoformat(),
                "building_state": updated_state,
                "agent_reasoning": agent_result.get("reasoning", ""),
                "actions_taken": agent_result.get("actions", []),
                "energy_savings_pct": updated_state.get("energy_savings_pct", 0),
                "comfort_score": updated_state.get("comfort_score", 0),
                "carbon_saved_kg": updated_state.get("carbon_saved_kg", 0),
                "cost_saved_usd": updated_state.get("cost_saved_usd", 0),
                "agent_logs": agent_result.get("logs", []),
                "tool_calls": agent_result.get("tool_calls", []),
                "cycle_duration_ms": round((time.time() - cycle_start) * 1000, 1)
            }

            app_state.current_metrics = metrics

            # Step 5: Save to database
            await app_state.db.log_cycle(metrics)

            # Step 6: Broadcast to dashboard
            await broadcast(metrics)

            logger.info(
                f"Cycle {cycle:04d} | "
                f"Energy saved: {updated_state.get('energy_savings_pct', 0):.1f}% | "
                f"Comfort: {updated_state.get('comfort_score', 0):.2f} | "
                f"Duration: {metrics['cycle_duration_ms']}ms"
            )

        except Exception as e:
            logger.error(f"Cycle {cycle} error: {e}", exc_info=True)
            await broadcast({
                "type": "error",
                "cycle": cycle,
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })

        # Wait for next cycle
        elapsed = time.time() - cycle_start
        sleep_time = max(0, app_state.loop_interval - elapsed)
        await asyncio.sleep(sleep_time)

    logger.info("🛑 Closed-loop control stopped.")


# ─── REST Endpoints ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "system": "Eco-Loop Building Intelligence Platform",
        "version": "1.0.0",
        "status": "operational",
        "loop_running": app_state.loop_running
    }


@app.get("/api/status")
async def get_status():
    return {
        "loop_running": app_state.loop_running,
        "loop_interval": app_state.loop_interval,
        "connected_clients": len(app_state.connected_clients),
        "current_metrics": app_state.current_metrics,
        "simulator_mode": app_state.simulator.mode if app_state.simulator else "unknown",
        "llm_model": app_state.orchestrator.model_name if app_state.orchestrator else "unknown",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/loop/start")
async def start_loop(background_tasks: BackgroundTasks, config: LoopConfig = LoopConfig()):
    if app_state.loop_running:
        return {"status": "already_running", "message": "Control loop is already active"}
    app_state.loop_running = True
    app_state.loop_interval = config.interval_seconds
    background_tasks.add_task(run_control_loop)
    return {"status": "started", "interval_seconds": app_state.loop_interval}


@app.post("/api/loop/stop")
async def stop_loop():
    app_state.loop_running = False
    await broadcast({"type": "loop_stopped", "timestamp": datetime.now().isoformat()})
    return {"status": "stopped"}


@app.get("/api/building/state")
async def get_building_state():
    if not app_state.simulator:
        raise HTTPException(status_code=503, detail="Simulator not initialized")
    return app_state.simulator.get_state()


@app.post("/api/building/control")
async def manual_control(command: ControlCommand):
    """Manual override endpoint — bypasses LLM agent."""
    if not app_state.simulator:
        raise HTTPException(status_code=503, detail="Simulator not initialized")
    actions = [command.model_dump(exclude_none=True)]
    app_state.simulator.apply_actions(actions)
    new_state = app_state.simulator.get_state()
    await broadcast({"type": "manual_override", "actions": actions, "state": new_state})
    return {"status": "applied", "new_state": new_state}


@app.get("/api/history")
async def get_history(limit: int = 100):
    if not app_state.db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    records = await app_state.db.get_recent_cycles(limit)
    return {"records": records, "count": len(records)}


@app.get("/api/analytics/summary")
async def get_analytics():
    if not app_state.db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    summary = await app_state.db.get_analytics_summary()
    return summary


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    """List all registered MCP tools."""
    if not app_state.mcp:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    return {"tools": app_state.mcp.list_tools()}


@app.post("/api/mcp/invoke")
async def invoke_mcp_tool(tool_name: str, parameters: Dict[str, Any] = {}):
    """Directly invoke an MCP tool (for debugging/testing)."""
    if not app_state.mcp:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    result = await app_state.mcp.call_tool(tool_name, parameters)
    return result


# ─── WebSocket ───────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    app_state.connected_clients.append(ws)
    logger.info(f"WebSocket client connected. Total: {len(app_state.connected_clients)}")

    # Send current state immediately on connect
    try:
        await ws.send_text(json.dumps({
            "type": "connected",
            "loop_running": app_state.loop_running,
            "current_metrics": app_state.current_metrics,
            "timestamp": datetime.now().isoformat()
        }, default=str))

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        app_state.connected_clients.remove(ws)
        logger.info(f"WebSocket client disconnected. Remaining: {len(app_state.connected_clients)}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if ws in app_state.connected_clients:
            app_state.connected_clients.remove(ws)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
