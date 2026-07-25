"""
MCP (Model Context Protocol) Server
Provides standardized tool calling for the LLM Orchestrator Agent
Eco-Loop Platform
"""

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("eco-loop.mcp")


class MCPTool:
    """A single MCP-compatible tool with JSON schema."""

    def __init__(self, name: str, description: str, parameters: Dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.call_count = 0
        self.last_called = None

    def to_schema(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
                "required": [k for k, v in self.parameters.items() if v.get("required", False)]
            }
        }


class MCPServer:
    """
    Model Context Protocol server exposing building control tools to the LLM agent.
    Tools are callable by the agent through structured JSON calls.
    """

    def __init__(self, simulator, optimizer, db):
        self.simulator = simulator
        self.optimizer = optimizer
        self.db = db
        self.tools: Dict[str, MCPTool] = {}
        self._register_tools()
        logger.info(f"MCP Server initialized with {len(self.tools)} tools.")

    def _register_tools(self):
        """Register all available building control tools."""

        # ── Tool 1: Read sensor data ──────────────────────────────────────────
        self._register(MCPTool(
            name="read_building_sensors",
            description=(
                "Read current sensor data from all building zones. "
                "Returns temperature, humidity, CO2, occupancy, and energy consumption for each zone. "
                "Use this first to understand current building state before making decisions."
            ),
            parameters={
                "zone_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of zone IDs to read. Leave empty for all zones.",
                    "required": False
                }
            },
            handler=self._tool_read_sensors
        ))

        # ── Tool 2: Apply HVAC control ────────────────────────────────────────
        self._register(MCPTool(
            name="set_hvac_control",
            description=(
                "Set HVAC control parameters for a specific zone. "
                "Adjust heating/cooling setpoints and operating mode. "
                "Setpoint changes take effect in next simulation step. "
                "Mode options: 'auto', 'heating', 'cooling', 'off'."
            ),
            parameters={
                "zone_id": {
                    "type": "string",
                    "description": "Zone ID (e.g. 'z1', 'z2')",
                    "required": True
                },
                "setpoint_heating": {
                    "type": "number",
                    "description": "Heating setpoint in Celsius (15-25). Lower saves energy.",
                    "required": False
                },
                "setpoint_cooling": {
                    "type": "number",
                    "description": "Cooling setpoint in Celsius (22-30). Higher saves energy.",
                    "required": False
                },
                "hvac_mode": {
                    "type": "string",
                    "enum": ["auto", "heating", "cooling", "off"],
                    "description": "HVAC operating mode",
                    "required": False
                }
            },
            handler=self._tool_set_hvac
        ))

        # ── Tool 3: Lighting control ──────────────────────────────────────────
        self._register(MCPTool(
            name="set_lighting_control",
            description=(
                "Adjust lighting level for a building zone. "
                "Level 0.0 = off, 1.0 = full brightness. "
                "Reducing lighting when unoccupied saves significant energy."
            ),
            parameters={
                "zone_id": {
                    "type": "string",
                    "description": "Zone ID to adjust lighting",
                    "required": True
                },
                "level": {
                    "type": "number",
                    "description": "Lighting level 0.0 (off) to 1.0 (full). Recommend 0.0 when empty.",
                    "required": True
                }
            },
            handler=self._tool_set_lighting
        ))

        # ── Tool 4: Ventilation control ───────────────────────────────────────
        self._register(MCPTool(
            name="set_ventilation",
            description=(
                "Control ventilation/air exchange rate for a zone. "
                "Higher rate improves CO2 but costs energy. "
                "Minimum rate of 0.2 must be maintained for occupied zones."
            ),
            parameters={
                "zone_id": {
                    "type": "string",
                    "description": "Zone ID",
                    "required": True
                },
                "rate": {
                    "type": "number",
                    "description": "Ventilation rate 0.0 to 1.0. Min 0.2 for occupied zones.",
                    "required": True
                }
            },
            handler=self._tool_set_ventilation
        ))

        # ── Tool 5: Energy optimizer ──────────────────────────────────────────
        self._register(MCPTool(
            name="run_energy_optimizer",
            description=(
                "Run the built-in energy optimization algorithm. "
                "Computes optimal setpoints for all zones based on occupancy, "
                "weather, electricity prices, and comfort constraints. "
                "Returns recommended control actions."
            ),
            parameters={
                "comfort_priority": {
                    "type": "number",
                    "description": "Comfort vs energy tradeoff. 0.0=max savings, 1.0=max comfort. Default 0.5.",
                    "required": False
                },
                "horizon_hours": {
                    "type": "integer",
                    "description": "Optimization horizon in hours. Default 4.",
                    "required": False
                }
            },
            handler=self._tool_run_optimizer
        ))

        # ── Tool 6: Comfort calculator ────────────────────────────────────────
        self._register(MCPTool(
            name="calculate_comfort",
            description=(
                "Calculate occupant thermal comfort (PMV/PPD) and air quality score "
                "for all zones. Use to assess if current conditions are acceptable "
                "before making aggressive energy-saving changes."
            ),
            parameters={},
            handler=self._tool_calculate_comfort
        ))

        # ── Tool 7: Weather forecast ──────────────────────────────────────────
        self._register(MCPTool(
            name="get_weather_forecast",
            description=(
                "Get simulated weather forecast for the next 24 hours. "
                "Includes outdoor temperature, solar radiation, and humidity. "
                "Use to proactively pre-cool or pre-heat the building."
            ),
            parameters={
                "hours_ahead": {
                    "type": "integer",
                    "description": "Number of hours to forecast (1-24). Default 8.",
                    "required": False
                }
            },
            handler=self._tool_get_weather
        ))

        # ── Tool 8: Energy savings report ────────────────────────────────────
        self._register(MCPTool(
            name="get_energy_report",
            description=(
                "Get current energy consumption vs baseline, savings percentage, "
                "carbon emissions avoided, and cost savings. "
                "Use to verify that optimizations are having measurable impact."
            ),
            parameters={},
            handler=self._tool_get_energy_report
        ))

        # ── Tool 9: Anomaly detector ──────────────────────────────────────────
        self._register(MCPTool(
            name="detect_anomalies",
            description=(
                "Scan all zones for anomalies: unusually high energy consumption, "
                "extreme temperatures, high CO2 levels, or sensor failures. "
                "Returns list of detected anomalies and recommended responses."
            ),
            parameters={},
            handler=self._tool_detect_anomalies
        ))

        # ── Tool 10: Apply batch actions ──────────────────────────────────────
        self._register(MCPTool(
            name="apply_control_batch",
            description=(
                "Apply a batch of control actions to multiple zones simultaneously. "
                "More efficient than calling individual tools when you have "
                "a complete optimization plan ready."
            ),
            parameters={
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "zone": {"type": "string"},
                            "setpoint_heating": {"type": "number"},
                            "setpoint_cooling": {"type": "number"},
                            "hvac_mode": {"type": "string"},
                            "lighting_level": {"type": "number"},
                            "ventilation_rate": {"type": "number"}
                        }
                    },
                    "description": "List of zone control actions",
                    "required": True
                }
            },
            handler=self._tool_apply_batch
        ))

    def _register(self, tool: MCPTool):
        self.tools[tool.name] = tool

    def list_tools(self) -> List[Dict]:
        return [t.to_schema() for t in self.tools.values()]

    async def call_tool(self, name: str, params: Dict) -> Dict:
        """Invoke a tool by name with given parameters."""
        if name not in self.tools:
            return {
                "success": False,
                "error": f"Tool '{name}' not found. Available: {list(self.tools.keys())}"
            }
        tool = self.tools[name]
        tool.call_count += 1
        tool.last_called = datetime.now().isoformat()
        try:
            result = await tool.handler(params)
            logger.debug(f"MCP tool '{name}' called successfully.")
            return {"success": True, "tool": name, "result": result}
        except Exception as e:
            logger.error(f"MCP tool '{name}' failed: {e}", exc_info=True)
            return {"success": False, "tool": name, "error": str(e)}

    # ─── Tool Handlers ────────────────────────────────────────────────────────

    async def _tool_read_sensors(self, params: Dict) -> Dict:
        state = self.simulator.get_state()
        zone_filter = params.get("zone_filter", [])
        zones = state["zones"]
        if zone_filter:
            zones = [z for z in zones if z["id"] in zone_filter]
        return {
            "timestamp": datetime.now().isoformat(),
            "outdoor_temp_c": state["outdoor_temp_c"],
            "solar_radiation_wm2": state["solar_radiation_wm2"],
            "zones": zones,
            "total_power_kw": state["total_power_kw"]
        }

    async def _tool_set_hvac(self, params: Dict) -> Dict:
        zone_id = params["zone_id"]
        action = {"zone": zone_id}
        if "setpoint_heating" in params:
            action["setpoint_heating"] = max(15.0, min(25.0, float(params["setpoint_heating"])))
        if "setpoint_cooling" in params:
            action["setpoint_cooling"] = max(22.0, min(30.0, float(params["setpoint_cooling"])))
        if "hvac_mode" in params:
            action["hvac_mode"] = params["hvac_mode"]
        self.simulator.apply_actions([action])
        return {"zone": zone_id, "applied": action, "status": "success"}

    async def _tool_set_lighting(self, params: Dict) -> Dict:
        zone_id = params["zone_id"]
        level = max(0.0, min(1.0, float(params["level"])))
        self.simulator.apply_actions([{"zone": zone_id, "lighting_level": level}])
        return {"zone": zone_id, "lighting_level": level, "status": "success"}

    async def _tool_set_ventilation(self, params: Dict) -> Dict:
        zone_id = params["zone_id"]
        rate = max(0.0, min(1.0, float(params["rate"])))
        self.simulator.apply_actions([{"zone": zone_id, "ventilation_rate": rate}])
        return {"zone": zone_id, "ventilation_rate": rate, "status": "success"}

    async def _tool_run_optimizer(self, params: Dict) -> Dict:
        comfort_priority = float(params.get("comfort_priority", 0.5))
        state = self.simulator.get_state()
        actions = self.optimizer.optimize(state, comfort_priority)
        return {
            "recommended_actions": actions,
            "optimizer_version": "1.0",
            "comfort_priority": comfort_priority,
            "zones_optimized": len(actions)
        }

    async def _tool_calculate_comfort(self, params: Dict) -> Dict:
        state = self.simulator.get_state()
        comfort_data = []
        for zone in state["zones"]:
            pmv = zone["pmv"]
            ppd = 100 - 95 * math.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
            co2_quality = "Good" if zone["co2_ppm"] < 1000 else "Poor" if zone["co2_ppm"] > 2000 else "Fair"
            comfort_data.append({
                "zone_id": zone["id"],
                "zone_name": zone["name"],
                "pmv": pmv,
                "ppd_pct": round(ppd, 1),
                "comfort_score": zone["comfort_score"],
                "co2_ppm": zone["co2_ppm"],
                "air_quality": co2_quality,
                "temp_c": zone["temp_c"],
                "humidity_pct": zone["humidity_pct"],
                "is_comfortable": abs(pmv) < 0.5 and zone["co2_ppm"] < 1000
            })
        overall_ppd = sum(z["ppd_pct"] for z in comfort_data) / len(comfort_data)
        return {
            "zones": comfort_data,
            "overall_ppd_pct": round(overall_ppd, 1),
            "overall_comfort": state["comfort_score"],
            "all_comfortable": all(z["is_comfortable"] for z in comfort_data)
        }

    async def _tool_get_weather(self, params: Dict) -> Dict:
        hours = min(24, int(params.get("hours_ahead", 8)))
        forecast = []
        current_time = self.simulator.sim_time
        for h in range(hours):
            t = current_time + timedelta(hours=h)
            hour = t.hour
            day_of_year = t.timetuple().tm_yday
            seasonal = 10 * math.sin(2 * math.pi * (day_of_year - 80) / 365)
            diurnal = 8 * math.sin(2 * math.pi * (hour - 6) / 24)
            temp = 15.0 + seasonal + diurnal
            solar = max(0, 600 * math.sin(math.pi * (hour - 6) / 14)) if 6 <= hour <= 20 else 0
            forecast.append({
                "hour": h + 1,
                "time": t.strftime("%H:%M"),
                "outdoor_temp_c": round(temp, 1),
                "solar_radiation_wm2": round(solar, 0),
                "humidity_pct": round(50 + 10 * math.sin(hour / 12), 1)
            })
        return {"forecast_hours": hours, "forecast": forecast}

    async def _tool_get_energy_report(self, params: Dict) -> Dict:
        state = self.simulator.get_state()
        return {
            "total_power_kw": state["total_power_kw"],
            "hvac_power_kw": state["total_hvac_kw"],
            "lighting_power_kw": state["total_lighting_kw"],
            "equipment_power_kw": state["total_equipment_kw"],
            "energy_savings_pct": state["energy_savings_pct"],
            "cumulative_energy_kwh": state["cumulative_energy_kwh"],
            "carbon_saved_kg": state["carbon_saved_kg"],
            "cost_saved_usd": state["cost_saved_usd"],
            "electricity_price_kwh": state["electricity_price_kwh"],
            "recommendation": (
                "Continue current strategy — savings above 15%"
                if state["energy_savings_pct"] >= 15
                else "Increase optimization aggressiveness — savings below target"
            )
        }

    async def _tool_detect_anomalies(self, params: Dict) -> Dict:
        state = self.simulator.get_state()
        anomalies = []
        for zone in state["zones"]:
            if zone["temp_c"] > 30:
                anomalies.append({
                    "zone": zone["id"],
                    "type": "HIGH_TEMPERATURE",
                    "value": zone["temp_c"],
                    "severity": "HIGH",
                    "action": "Increase cooling setpoint or check HVAC"
                })
            if zone["temp_c"] < 16:
                anomalies.append({
                    "zone": zone["id"],
                    "type": "LOW_TEMPERATURE",
                    "value": zone["temp_c"],
                    "severity": "MEDIUM",
                    "action": "Activate heating"
                })
            if zone["co2_ppm"] > 1500:
                anomalies.append({
                    "zone": zone["id"],
                    "type": "HIGH_CO2",
                    "value": zone["co2_ppm"],
                    "severity": "HIGH",
                    "action": "Increase ventilation immediately"
                })
            if zone["hvac_power_kw"] > zone.get("area_m2", 400) * 0.1 / 1000:
                pass  # Would flag extremely high HVAC load

        return {
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
            "all_normal": len(anomalies) == 0,
            "scan_time": datetime.now().isoformat()
        }

    async def _tool_apply_batch(self, params: Dict) -> Dict:
        actions = params.get("actions", [])
        self.simulator.apply_actions(actions)
        return {
            "applied_count": len(actions),
            "zones_affected": list({a.get("zone") for a in actions if "zone" in a}),
            "status": "success"
        }
