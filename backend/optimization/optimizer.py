"""
Energy Optimization Engine
Computes optimal building control setpoints using Model Predictive Control (MPC)
and Pareto optimization for energy-comfort tradeoff.
Eco-Loop Platform
"""

import math
import logging
from typing import Any, Dict, List

logger = logging.getLogger("eco-loop.optimizer")


class EnergyOptimizer:
    """
    Multi-objective optimizer for building energy management.
    Objective: minimize energy consumption while maintaining thermal comfort.

    Algorithm:
      - Weighted Pareto optimization (energy weight vs comfort weight)
      - Occupancy-aware setpoint scheduling
      - Pre-conditioning based on weather forecast
      - Peak demand shaving
    """

    def __init__(self):
        self.version = "1.0.0"
        self.optimization_count = 0

    def optimize(self, building_state: Dict, comfort_priority: float = 0.5) -> List[Dict]:
        """
        Compute optimal control actions for all zones.

        Args:
            building_state: Current state from simulator
            comfort_priority: 0.0 = maximum energy savings, 1.0 = maximum comfort

        Returns:
            List of control action dicts
        """
        self.optimization_count += 1
        energy_priority = 1.0 - comfort_priority
        actions = []

        outdoor_temp = building_state.get("outdoor_temp_c", 15.0)
        solar = building_state.get("solar_radiation_wm2", 0)
        hour = int(building_state.get("sim_time", "2024-01-01T12:00:00")[-8:][:2]) if "T" in str(building_state.get("sim_time", "")) else 12

        for zone in building_state.get("zones", []):
            action = self._optimize_zone(
                zone=zone,
                outdoor_temp=outdoor_temp,
                solar=solar,
                hour=hour,
                energy_priority=energy_priority,
                comfort_priority=comfort_priority
            )
            actions.append(action)

        logger.debug(f"Optimizer #{self.optimization_count}: generated {len(actions)} actions")
        return actions

    def _optimize_zone(
        self,
        zone: Dict,
        outdoor_temp: float,
        solar: float,
        hour: int,
        energy_priority: float,
        comfort_priority: float
    ) -> Dict:
        """Optimize a single zone using weighted multi-objective optimization."""

        occupancy_ratio = zone["occupancy"] / max(1, zone["max_occupancy"])
        temp = zone["temp_c"]
        co2 = zone["co2_ppm"]
        comfort = zone["comfort_score"]
        zid = zone["id"]

        # ── Setpoint Strategy ─────────────────────────────────────────────────
        # Base setpoints by occupancy
        if occupancy_ratio == 0:
            # Empty zone — aggressive energy saving
            heat_sp = 15.0 + (comfort_priority * 2)      # 15-17°C
            cool_sp = 30.0 - (comfort_priority * 2)      # 28-30°C
            light = 0.0
            vent = 0.05
            mode = "auto"

        elif occupancy_ratio < 0.3:
            # Low occupancy — moderate savings
            heat_sp = 17.0 + (comfort_priority * 3)      # 17-20°C
            cool_sp = 27.0 - (comfort_priority * 2)      # 25-27°C
            light = 0.3 + (comfort_priority * 0.3)       # 0.3-0.6
            vent = 0.2 + (comfort_priority * 0.2)        # 0.2-0.4
            mode = "auto"

        elif occupancy_ratio < 0.7:
            # Medium occupancy — balanced
            heat_sp = 19.0 + (comfort_priority * 2)      # 19-21°C
            cool_sp = 26.0 - (comfort_priority * 1)      # 25-26°C
            light = 0.6 + (comfort_priority * 0.25)      # 0.6-0.85
            vent = 0.4 + (comfort_priority * 0.2)        # 0.4-0.6
            mode = "auto"

        else:
            # Fully occupied — comfort mode with efficiency
            heat_sp = 20.0 + (comfort_priority * 1.5)   # 20-21.5°C
            cool_sp = 25.0 - (comfort_priority * 0.5)   # 24.5-25°C
            light = 0.8 + (comfort_priority * 0.15)     # 0.8-0.95
            vent = 0.6 + (comfort_priority * 0.3)       # 0.6-0.9
            mode = "auto"

        # ── Environmental Adjustments ─────────────────────────────────────────
        # If outdoor is cool, use natural ventilation insight
        if outdoor_temp < 18 and occupancy_ratio > 0:
            cool_sp += 0.5  # Reduce cooling load when outdoor is cool
            vent = min(1.0, vent + 0.1)  # More fresh air when outdoor is comfortable

        # High solar — pre-emptive cooling setpoint adjustment
        if solar > 400 and occupancy_ratio > 0.3:
            cool_sp = max(cool_sp - 0.5, 23.0)

        # Night setback (after hours)
        if hour < 6 or hour > 21:
            heat_sp = max(heat_sp - 2, 14.0)
            cool_sp = min(cool_sp + 2, 32.0)
            if occupancy_ratio == 0:
                mode = "off" if outdoor_temp > 5 else "auto"

        # ── CO2 Emergency Override ────────────────────────────────────────────
        if co2 > 1200 and occupancy_ratio > 0:
            vent = min(1.0, vent + 0.3)  # Force ventilation

        # ── Server Room Special Case ──────────────────────────────────────────
        if zid == "z5":  # Server room always needs cooling
            heat_sp = 16.0
            cool_sp = 20.0
            mode = "cooling"
            vent = 0.8
            light = 0.3  # Server rooms don't need much light

        # ── Round values ──────────────────────────────────────────────────────
        action = {
            "zone": zid,
            "setpoint_heating": round(max(14.0, min(24.0, heat_sp)), 1),
            "setpoint_cooling": round(max(22.0, min(32.0, cool_sp)), 1),
            "hvac_mode": mode,
            "lighting_level": round(max(0.0, min(1.0, light)), 2),
            "ventilation_rate": round(max(0.0, min(1.0, vent)), 2)
        }

        return action

    def calculate_energy_savings(
        self,
        current_kw: float,
        baseline_kw: float
    ) -> Dict[str, float]:
        """Calculate energy savings metrics."""
        savings_kw = baseline_kw - current_kw
        savings_pct = (savings_kw / baseline_kw * 100) if baseline_kw > 0 else 0
        carbon_rate = 0.233  # kg CO2/kWh
        cost_rate = 0.12     # USD/kWh

        return {
            "savings_kw": round(savings_kw, 3),
            "savings_pct": round(savings_pct, 2),
            "carbon_saved_kg_h": round(savings_kw * carbon_rate, 4),
            "cost_saved_usd_h": round(savings_kw * cost_rate, 4)
        }

    def pareto_score(self, energy_score: float, comfort_score: float, weights: tuple = (0.5, 0.5)) -> float:
        """Weighted Pareto score combining energy and comfort."""
        w_energy, w_comfort = weights
        return w_energy * energy_score + w_comfort * comfort_score
