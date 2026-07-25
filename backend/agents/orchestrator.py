"""
Orchestrator Agent — Multi-step LLM reasoning with MCP tool calling
Uses Ollama (local CPU inference) with structured tool call parsing.
Eco-Loop Platform
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("eco-loop.agent")


SYSTEM_PROMPT = """You are Eco-Loop, an autonomous building energy management AI agent.
Your mission is to continuously optimize a commercial building's energy consumption
while maintaining occupant thermal comfort and air quality.

You have access to the following tools:
{tool_descriptions}

OPERATING PRINCIPLES:
1. Always READ sensors first before making decisions
2. Check comfort levels before aggressive energy reduction
3. Use the optimizer for complex multi-zone decisions
4. Monitor anomalies every few cycles
5. Target >15% energy savings vs baseline without discomfort
6. Unoccupied zones: reduce setpoints, dim lights, lower ventilation
7. Occupied zones: maintain comfort (PMV between -0.5 and +0.5)
8. Pre-cool/pre-heat during off-peak electricity hours when possible

RESPONSE FORMAT:
You must respond with valid JSON in this exact format:
{{
  "reasoning": "Your step-by-step analysis of the building state",
  "tool_calls": [
    {{
      "tool": "tool_name",
      "params": {{...}}
    }}
  ],
  "summary": "One sentence summary of your decision",
  "confidence": 0.0-1.0
}}

If no action is needed, return empty tool_calls array with reasoning."""

TOOL_CALL_PATTERN = re.compile(
    r'\{[^{}]*"tool"\s*:\s*"([^"]+)"[^{}]*"params"\s*:\s*(\{[^{}]*\})[^{}]*\}',
    re.DOTALL
)


class OrchestratorAgent:
    """
    Master LLM agent that orchestrates all building optimization.
    Uses Ollama for local CPU inference. Falls back to rule-based
    optimization if Ollama is unavailable.
    """

    def __init__(self, mcp_server, model_name: str = "phi3:mini"):
        self.mcp = mcp_server
        self.model_name = model_name
        self.ollama_url = "http://localhost:11434/api/generate"
        self.ollama_available = False
        self.cycle_history: List[Dict] = []
        self.memory: Dict[str, Any] = {
            "total_cycles": 0,
            "successful_llm_calls": 0,
            "rule_based_cycles": 0,
            "total_actions": 0,
            "anomalies_resolved": 0,
        }
        self._check_ollama()

    def _check_ollama(self):
        """Check if Ollama is running locally."""
        try:
            resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                available = [m["name"] for m in models]
                logger.info(f"Ollama available. Models: {available}")
                # Pick best available model
                preferred = ["phi3:mini", "phi3", "qwen2.5:3b", "qwen2.5", "llama3.2:3b",
                             "llama3.2", "tinyllama", "mistral:7b-instruct-q4_0"]
                for p in preferred:
                    if any(p in a for a in available):
                        self.model_name = p
                        logger.info(f"Selected model: {self.model_name}")
                        break
                self.ollama_available = True
        except Exception:
            logger.warning("Ollama not available — using rule-based fallback agent.")
            self.ollama_available = False

    def _format_tool_descriptions(self) -> str:
        tools = self.mcp.list_tools()
        lines = []
        for t in tools:
            params = list(t["inputSchema"]["properties"].keys())
            lines.append(f"- {t['name']}: {t['description'][:80]}... Params: {params}")
        return "\n".join(lines)

    def _build_prompt(self, building_state: Dict) -> str:
        """Build LLM prompt with current building context."""
        hour = datetime.now().hour
        time_context = (
            "morning rush" if 7 <= hour < 9
            else "business hours" if 9 <= hour < 17
            else "evening wind-down" if 17 <= hour < 20
            else "night/unoccupied"
        )

        zones_summary = []
        for z in building_state.get("zones", []):
            zones_summary.append(
                f"  {z['name']}: {z['temp_c']}°C, "
                f"occupancy={z['occupancy']}/{z['max_occupancy']}, "
                f"CO2={z['co2_ppm']}ppm, "
                f"comfort={z['comfort_score']:.2f}, "
                f"HVAC={z['hvac_power_kw']:.2f}kW"
            )

        prompt = f"""Current building state at {building_state.get('sim_time', 'unknown')} [{time_context}]:

OUTDOOR: {building_state.get('outdoor_temp_c')}°C, Solar: {building_state.get('solar_radiation_wm2')} W/m²
OVERALL: Power={building_state.get('total_power_kw')}kW, Savings={building_state.get('energy_savings_pct')}%, Comfort={building_state.get('comfort_score'):.2f}

ZONES:
{chr(10).join(zones_summary)}

CYCLE #{self.memory['total_cycles'] + 1} | Prev LLM calls: {self.memory['successful_llm_calls']} | Rule-based: {self.memory['rule_based_cycles']}

Analyze the building state and take optimal actions to reduce energy consumption while maintaining comfort.
Remember to call read_building_sensors first for fresh data, then run_energy_optimizer if needed."""

        return prompt

    async def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama local LLM API."""
        system = SYSTEM_PROMPT.format(
            tool_descriptions=self._format_tool_descriptions()
        )
        payload = {
            "model": self.model_name,
            "prompt": f"{system}\n\nUSER: {prompt}\nASSISTANT:",
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 800,
                "stop": ["USER:", "\n\n\n"]
            }
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.ollama_url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("response", "")
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}")
        return None

    def _parse_llm_response(self, response: str) -> Dict:
        """Parse LLM JSON response, with fallback for malformed output."""
        # Try direct JSON parse
        try:
            cleaned = response.strip()
            # Find JSON block
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start != -1 and end > start:
                json_str = cleaned[start:end]
                parsed = json.loads(json_str)
                return parsed
        except Exception:
            pass

        # Fallback: extract tool calls with regex
        tool_calls = []
        for match in TOOL_CALL_PATTERN.finditer(response):
            try:
                tool_name = match.group(1)
                params = json.loads(match.group(2))
                tool_calls.append({"tool": tool_name, "params": params})
            except Exception:
                pass

        return {
            "reasoning": response[:500] if response else "Unable to parse LLM response",
            "tool_calls": tool_calls,
            "summary": "LLM response parsed with fallback",
            "confidence": 0.5
        }

    def _rule_based_agent(self, building_state: Dict) -> Dict:
        """
        Deterministic rule-based fallback agent.
        Runs when Ollama is unavailable. Still uses MCP tools indirectly.
        """
        actions = []
        logs = []
        hour = datetime.now().hour
        is_business_hours = 8 <= hour <= 18
        is_weekend = datetime.now().weekday() >= 5

        for zone in building_state.get("zones", []):
            zid = zone["id"]
            occupancy_ratio = zone["occupancy"] / max(1, zone["max_occupancy"])
            temp = zone["temp_c"]
            comfort = zone["comfort_score"]

            # Unoccupied zone optimization
            if occupancy_ratio < 0.1:
                actions.append({
                    "zone": zid,
                    "setpoint_heating": 17.0,
                    "setpoint_cooling": 28.0,
                    "lighting_level": 0.0,
                    "ventilation_rate": 0.1
                })
                logs.append(f"[RULE] {zone['name']}: unoccupied — energy-saving mode")

            # Low occupancy
            elif occupancy_ratio < 0.4:
                actions.append({
                    "zone": zid,
                    "setpoint_heating": 19.0,
                    "setpoint_cooling": 27.0,
                    "lighting_level": 0.5,
                    "ventilation_rate": 0.3
                })
                logs.append(f"[RULE] {zone['name']}: low occupancy — reduced mode")

            # Fully occupied — comfort mode
            else:
                target_cool = 26.0
                target_heat = 20.0
                # High CO2 — boost ventilation
                vent = 0.7 if zone["co2_ppm"] > 1000 else 0.5
                actions.append({
                    "zone": zid,
                    "setpoint_heating": target_heat,
                    "setpoint_cooling": target_cool,
                    "lighting_level": 0.9,
                    "ventilation_rate": vent
                })
                logs.append(f"[RULE] {zone['name']}: occupied — comfort mode")

        return {
            "reasoning": f"Rule-based agent: {'Business hours' if is_business_hours else 'After hours'}, {hour:02d}:00",
            "actions": actions,
            "logs": logs,
            "tool_calls": [],
            "summary": f"Applied {len(actions)} rule-based actions",
            "confidence": 0.75,
            "agent_type": "rule_based"
        }

    async def run_cycle(self, building_state: Dict) -> Dict:
        """
        Run one complete reasoning-action cycle.
        Returns actions and reasoning for the control loop.
        """
        self.memory["total_cycles"] += 1
        cycle_start = time.time()
        logs = []
        all_tool_calls = []
        all_actions = []

        if self.ollama_available:
            # ── LLM Reasoning Path ────────────────────────────────────────────
            prompt = self._build_prompt(building_state)
            llm_response = await self._call_ollama(prompt)

            if llm_response:
                parsed = self._parse_llm_response(llm_response)
                self.memory["successful_llm_calls"] += 1
                logs.append(f"[LLM] {self.model_name} responded in {time.time()-cycle_start:.1f}s")

                # Execute tool calls
                for tc in parsed.get("tool_calls", []):
                    tool_name = tc.get("tool")
                    params = tc.get("params", {})
                    if tool_name:
                        logs.append(f"[TOOL] Calling: {tool_name}")
                        result = await self.mcp.call_tool(tool_name, params)
                        all_tool_calls.append({
                            "tool": tool_name,
                            "params": params,
                            "result": result
                        })

                        # Extract actions from optimizer calls
                        if tool_name == "run_energy_optimizer" and result.get("success"):
                            reco = result["result"].get("recommended_actions", [])
                            all_actions.extend(reco)
                            logs.append(f"[OPTIMIZER] {len(reco)} actions recommended")

                        elif tool_name == "apply_control_batch" and result.get("success"):
                            count = result["result"].get("applied_count", 0)
                            logs.append(f"[BATCH] Applied {count} actions")

                        elif tool_name in ["set_hvac_control", "set_lighting_control", "set_ventilation"]:
                            if result.get("success"):
                                logs.append(f"[CONTROL] {tool_name} applied to {params.get('zone_id')}")

                # Apply optimizer actions if any
                if all_actions:
                    self.simulator_apply(all_actions)
                    self.memory["total_actions"] += len(all_actions)

                return {
                    "reasoning": parsed.get("reasoning", ""),
                    "actions": all_actions,
                    "tool_calls": all_tool_calls,
                    "logs": logs,
                    "summary": parsed.get("summary", ""),
                    "confidence": parsed.get("confidence", 0.7),
                    "agent_type": "llm",
                    "model": self.model_name,
                    "cycle_time_s": round(time.time() - cycle_start, 2)
                }

        # ── Rule-Based Fallback ───────────────────────────────────────────────
        self.memory["rule_based_cycles"] += 1

        # Always run optimizer regardless of LLM availability
        optimizer_result = await self.mcp.call_tool("run_energy_optimizer", {
            "comfort_priority": 0.5,
            "horizon_hours": 4
        })
        if optimizer_result.get("success"):
            all_actions = optimizer_result["result"].get("recommended_actions", [])

        # Also run anomaly detection every 5 cycles
        if self.memory["total_cycles"] % 5 == 0:
            anomaly_result = await self.mcp.call_tool("detect_anomalies", {})
            if anomaly_result.get("success"):
                anomalies = anomaly_result["result"].get("anomalies", [])
                if anomalies:
                    logs.append(f"[ANOMALY] {len(anomalies)} anomalies detected!")
                    self.memory["anomalies_resolved"] += len(anomalies)

        if not all_actions:
            # Full rule-based fallback
            result = self._rule_based_agent(building_state)
            all_actions = result["actions"]
            logs.extend(result["logs"])

        if all_actions:
            self.simulator_apply(all_actions)
            self.memory["total_actions"] += len(all_actions)

        return {
            "reasoning": f"Cycle {self.memory['total_cycles']}: Optimizer + rule-based control. "
                         f"LLM offline — using deterministic optimization.",
            "actions": all_actions,
            "tool_calls": all_tool_calls,
            "logs": logs,
            "summary": f"Applied {len(all_actions)} optimized actions (rule-based mode)",
            "confidence": 0.8,
            "agent_type": "rule_based_optimizer",
            "cycle_time_s": round(time.time() - cycle_start, 2)
        }

    def simulator_apply(self, actions: List[Dict]):
        """Apply actions to the simulator (accessed via MCP server)."""
        try:
            self.mcp.simulator.apply_actions(actions)
        except Exception as e:
            logger.error(f"Failed to apply actions: {e}")
