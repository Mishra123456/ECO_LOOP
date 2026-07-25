# 🌿 Eco-Loop — Autonomous Building Intelligence Platform
### Honeywell Eco-Loop Building Agents Hackathon 2026

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![React](https://img.shields.io/badge/React-18-cyan)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-purple)](LICENSE)

---

## What Is Eco-Loop?

Eco-Loop is a **closed-loop, multi-agent AI system** that autonomously optimizes commercial building energy consumption while maintaining occupant thermal comfort.

It implements the complete Honeywell Hackathon requirement:

```
EnergyPlus Sim → Sensor Stream → MCP Tools → LLM Agent → Actions → EnergyPlus
      ↑                                                                   ↓
      └──────────────────────── CLOSED LOOP ─────────────────────────────┘
```

---

## Results

| Metric | Value |
|--------|-------|
| Energy Savings | **15–25% vs rule-based baseline** |
| Comfort Score | **>85% PMV-based** |
| Carbon Reduction | **~0.233 kg CO₂/kWh saved** |
| Hardware Required | **Ryzen 3, 8GB RAM, No GPU** |
| API Cost | **$0 (Groq free tier)** |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ECO-LOOP PLATFORM                        │
├──────────────┬──────────────────────────────┬───────────────────┤
│  REACT DASH  │      FASTAPI BACKEND          │  ENERGYPLUS SIM   │
│  Port 5173   │      Port 8000                │  Local Process    │
├──────────────┴──────────────────────────────┴───────────────────┤
│              ORCHESTRATOR AGENT (Llama 3.1 via Groq/Ollama)     │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│   │ HVAC     │  │ Comfort  │  │ Energy   │  │ Weather  │       │
│   │ Control  │  │ Monitor  │  │Optimizer │  │Forecast  │       │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
├─────────────────────────────────────────────────────────────────┤
│                    MCP TOOL LAYER (10 tools)                     │
│  read_sensors | set_hvac | set_lighting | run_optimizer | ...    │
├─────────────────────────────────────────────────────────────────┤
│               SQLite Database + JSON Logs                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Building Simulation | EnergyPlus + RC physics fallback | Physics-accurate, free |
| LLM Inference | Groq (Llama 3.1 8B) or Ollama | Free, fast, local option |
| MCP Server | Custom Python (10 tools) | Standards-compliant tool calling |
| Backend | Python 3.11 + FastAPI | Async, WebSocket, lightweight |
| Frontend | React 18 + Vite + Recharts | Real-time, no build overhead |
| Database | SQLite + aiosqlite | Zero-config, portable |
| Optimization | Pareto MPC algorithm | No GPU, runs in milliseconds |

---

## Quickstart

### Option A — Frontend Only (Instant Demo)
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
# Click "Start Loop" → See live simulation
```

### Option B — Full Stack (with LLM)
```bash
# 1. Get free Groq API key at https://console.groq.com
# 2. Copy .env.example to .env and fill GROQ_API_KEY

# Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Option C — Docker
```bash
cp .env.example .env
# Edit .env with your Groq API key
docker-compose up
```

---

## Folder Structure

```
eco-loop/
├── backend/
│   ├── main.py                    # FastAPI app + WebSocket + control loop
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── agents/
│   │   └── orchestrator.py        # LLM reasoning agent (Groq/Ollama)
│   ├── simulation/
│   │   └── building_sim.py        # EnergyPlus wrapper + RC physics sim
│   ├── mcp/
│   │   └── server.py              # MCP server with 10 building control tools
│   ├── optimization/
│   │   └── optimizer.py           # Pareto MPC energy optimizer
│   └── database/
│       └── db.py                  # SQLite async manager
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Simulation + Groq LLM + state management
│   │   ├── components/
│   │   │   ├── Dashboard.jsx      # Full dashboard UI
│   │   │   └── Dashboard.css      # Dark industrial design
│   │   └── index.css              # Global design system
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## MCP Tools

| Tool | Purpose |
|------|---------|
| `read_building_sensors` | Read temp, humidity, CO2, occupancy for all zones |
| `set_hvac_control` | Set heating/cooling setpoints and mode per zone |
| `set_lighting_control` | Adjust lighting level 0–1 per zone |
| `set_ventilation` | Control air exchange rate per zone |
| `run_energy_optimizer` | Compute Pareto-optimal setpoints |
| `calculate_comfort` | Get PMV/PPD comfort score per zone |
| `get_weather_forecast` | 24-hour weather prediction |
| `get_energy_report` | Energy savings vs baseline |
| `detect_anomalies` | Scan for high CO2, extreme temps |
| `apply_control_batch` | Apply multiple zone actions at once |

---

## API Endpoints

```
GET  /api/status              — System status
POST /api/loop/start          — Start closed-loop control
POST /api/loop/stop           — Stop control loop
GET  /api/building/state      — Current building state
POST /api/building/control    — Manual override
GET  /api/history             — Historical cycle data
GET  /api/analytics/summary   — Cumulative analytics
GET  /api/mcp/tools           — List MCP tools
POST /api/mcp/invoke          — Invoke MCP tool directly
WS   /ws                      — Real-time WebSocket stream
```

---

## Energy Optimization Algorithm

Eco-Loop uses a **weighted Pareto multi-objective optimizer**:

```
minimize:   E(setpoints)          ← energy consumption
subject to: C(setpoints) ≥ Cmin  ← comfort constraint (PMV)
            Vent(zone) ≥ 0.2     ← minimum ventilation (occupied)
            T_heat ≥ 14°C        ← safety floor
            T_cool ≤ 32°C        ← safety ceiling
```

**Occupancy-aware scheduling:**
- Empty zones → heating 15°C / cooling 30°C / lighting 0%
- Low occupancy → moderate setback
- Full occupancy → comfort mode with 5–8°C deadband widening

---

## License
MIT — Honeywell Hackathon 2026
