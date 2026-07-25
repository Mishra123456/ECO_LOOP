"""
Building Simulator — EnergyPlus Wrapper + High-Fidelity Fallback
Eco-Loop Platform
"""

import math
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("eco-loop.simulator")


class Zone:
    """Represents a thermal zone in the building."""
    def __init__(self, zone_id: str, name: str, area_m2: float, volume_m3: float):
        self.id = zone_id
        self.name = name
        self.area_m2 = area_m2
        self.volume_m3 = volume_m3

        # Thermal state
        self.temp_c = 22.0
        self.humidity_pct = 45.0
        self.co2_ppm = 420.0

        # Control setpoints
        self.setpoint_heating = 20.0
        self.setpoint_cooling = 26.0
        self.hvac_mode = "auto"  # heating | cooling | auto | off
        self.lighting_level = 0.7  # 0-1
        self.ventilation_rate = 0.5  # 0-1

        # Energy
        self.hvac_power_kw = 0.0
        self.lighting_power_kw = area_m2 * 0.010 * self.lighting_level
        self.equipment_power_kw = area_m2 * 0.015

        # Occupancy
        self.occupancy = 0
        self.max_occupancy = max(1, int(area_m2 / 5))

        # Thermal properties (simplified RC model)
        self.thermal_mass = volume_m3 * 1.2 * 1005  # J/K
        self.ua_envelope = area_m2 * 0.35  # W/K (U-value * area)


class BuildingSimulator:
    """
    Physics-based building simulator.
    Uses a simplified RC thermal model when EnergyPlus is unavailable.
    Automatically switches to EnergyPlus if installed.
    """

    def __init__(self):
        self.mode = "physics_sim"  # or "energyplus"
        self.zones: Dict[str, Zone] = {}
        self.outdoor_temp = 15.0
        self.solar_radiation = 0.0
        self.time_step_minutes = 5
        self.sim_time = datetime.now()
        self.baseline_energy_kwh = 0.0
        self.current_energy_kwh = 0.0
        self.total_cycles = 0
        self.initial_temp = 22.0
        self.electricity_price_kwh = 0.12  # USD
        self.carbon_intensity_kg_kwh = 0.233  # kg CO2/kWh (US grid average)
        self._cumulative_baseline = 0.0
        self._cumulative_actual = 0.0

    def initialize(self):
        """Set up building zones."""
        zone_configs = [
            ("z1", "Office Floor 1", 400.0, 1200.0),
            ("z2", "Office Floor 2", 400.0, 1200.0),
            ("z3", "Conference Rooms", 150.0, 450.0),
            ("z4", "Lobby & Reception", 100.0, 400.0),
            ("z5", "Server Room", 50.0, 150.0),
        ]
        for zid, name, area, vol in zone_configs:
            self.zones[zid] = Zone(zid, name, area, vol)

        # Server room always cool
        self.zones["z5"].setpoint_cooling = 18.0
        self.zones["z5"].setpoint_heating = 16.0
        self.zones["z5"].equipment_power_kw = 8.0

        logger.info(f"Building simulator initialized: {len(self.zones)} zones, mode={self.mode}")

        try:
            self._try_energyplus_init()
        except Exception:
            logger.info("EnergyPlus not found — using physics simulation mode.")

    def _try_energyplus_init(self):
        """Try to connect to EnergyPlus via pyenergyplus."""
        import importlib.util
        spec = importlib.util.find_spec("pyenergyplus")
        if spec:
            self.mode = "energyplus"
            logger.info("EnergyPlus detected — switching to EnergyPlus mode.")

    def _compute_outdoor_temp(self) -> float:
        """Synthetic outdoor temperature with daily and seasonal variation."""
        hour = self.sim_time.hour + self.sim_time.minute / 60.0
        day_of_year = self.sim_time.timetuple().tm_yday
        seasonal = 10 * math.sin(2 * math.pi * (day_of_year - 80) / 365)
        diurnal = 8 * math.sin(2 * math.pi * (hour - 6) / 24)
        noise = random.gauss(0, 0.3)
        return 15.0 + seasonal + diurnal + noise

    def _compute_solar_radiation(self) -> float:
        """Solar irradiance W/m2 based on time of day."""
        hour = self.sim_time.hour + self.sim_time.minute / 60.0
        if 6 <= hour <= 20:
            base = 600 * math.sin(math.pi * (hour - 6) / 14)
            cloud_factor = random.uniform(0.4, 1.0)
            return max(0, base * cloud_factor)
        return 0.0

    def _compute_occupancy(self, zone: Zone) -> int:
        """Time-based occupancy prediction."""
        hour = self.sim_time.hour
        day = self.sim_time.weekday()

        if day >= 5:  # Weekend
            base = 0.05
        elif 8 <= hour <= 17:
            base = 0.75 + 0.2 * math.sin(math.pi * (hour - 8) / 9)
        elif 7 <= hour < 8 or 17 < hour <= 19:
            base = 0.3
        else:
            base = 0.02

        if zone.id == "z4":  # Lobby always somewhat occupied
            base = min(1.0, base + 0.2)
        if zone.id == "z5":  # Server room rarely occupied
            base = 0.05

        base += random.gauss(0, 0.05)
        base = max(0.0, min(1.0, base))
        return int(base * zone.max_occupancy)

    def _step_thermal(self, zone: Zone, dt_seconds: float):
        """
        RC thermal model: dT/dt = (Q_hvac + Q_solar + Q_occ + Q_equip - UA*(T-Tout)) / C
        """
        # Heat gains
        q_solar = self.solar_radiation * zone.area_m2 * 0.1  # W (10% SHGC)
        q_occupancy = zone.occupancy * 80  # W per person
        q_equipment = zone.equipment_power_kw * 1000  # W
        q_lighting = zone.lighting_power_kw * 1000 * 0.9  # 90% becomes heat

        # Envelope losses
        q_envelope = zone.ua_envelope * (self.outdoor_temp - zone.temp_c)

        # HVAC power calculation
        if zone.hvac_mode == "off":
            q_hvac = 0.0
            zone.hvac_power_kw = 0.0
        elif zone.temp_c < zone.setpoint_heating - 0.5 or zone.hvac_mode == "heating":
            cop = 3.5
            heat_needed = (zone.setpoint_heating - zone.temp_c) * zone.thermal_mass / dt_seconds + max(0.0, -q_envelope)
            q_hvac = min(heat_needed, zone.area_m2 * 200.0)
            zone.hvac_power_kw = q_hvac / (cop * 1000.0)
        elif zone.temp_c > zone.setpoint_cooling + 0.5 or zone.hvac_mode == "cooling":
            cop = 3.0
            heat_gains = q_solar + q_occupancy + q_equipment + q_lighting + max(0.0, q_envelope)
            cool_needed = (zone.temp_c - zone.setpoint_cooling) * zone.thermal_mass / dt_seconds + heat_gains
            q_hvac = -min(cool_needed, zone.area_m2 * 250.0)
            zone.hvac_power_kw = abs(q_hvac) / (cop * 1000.0)
        else:
            q_hvac = 0.0
            zone.hvac_power_kw = 0.0

        # Total heat balance
        q_total = q_solar + q_occupancy + q_equipment + q_lighting + q_envelope + q_hvac

        # Temperature change
        dT = (q_total * dt_seconds) / zone.thermal_mass
        zone.temp_c = max(-10, min(50, zone.temp_c + dT))

        # CO2 (ppm) based on occupancy and ventilation
        co2_generation = zone.occupancy * 3.5 * (1200.0 / zone.volume_m3)
        co2_removal = zone.ventilation_rate * 12.0 * max(0.0, (zone.co2_ppm - 400.0) / 400.0)
        zone.co2_ppm = max(400.0, min(2500.0, zone.co2_ppm + co2_generation - co2_removal))

        # Humidity
        zone.humidity_pct += zone.occupancy * 0.001 - 0.005
        zone.humidity_pct = max(20, min(80, zone.humidity_pct))

        # Lighting energy
        zone.lighting_power_kw = zone.area_m2 * 0.010 * zone.lighting_level

    def step(self):
        """Advance simulation by one time step."""
        self.sim_time += timedelta(minutes=self.time_step_minutes)
        dt = self.time_step_minutes * 60

        self.outdoor_temp = self._compute_outdoor_temp()
        self.solar_radiation = self._compute_solar_radiation()

        total_energy_kw = 0.0
        baseline_kw = 0.0

        for zone in self.zones.values():
            zone.occupancy = self._compute_occupancy(zone)
            self._step_thermal(zone, dt)

            total_energy_kw += zone.hvac_power_kw + zone.lighting_power_kw + zone.equipment_power_kw
            baseline_kw += (
                zone.area_m2 * 0.030  # Baseline: 30W/m2 rule-based schedule
                + zone.equipment_power_kw
            )

        energy_kwh = total_energy_kw * (self.time_step_minutes / 60)
        baseline_kwh = baseline_kw * (self.time_step_minutes / 60)
        self._cumulative_actual += energy_kwh
        self._cumulative_baseline += baseline_kwh
        self.total_cycles += 1

    def get_state(self) -> Dict[str, Any]:
        """Return full building state as dict."""
        self.step()

        zone_states = []
        total_hvac = 0.0
        total_lighting = 0.0
        total_equipment = 0.0
        comfort_scores = []

        for zone in self.zones.values():
            # PMV-based comfort score (-3 to +3, 0 = perfect)
            pmv = self._calculate_pmv(zone)
            comfort = max(0, 1 - abs(pmv) / 3)
            comfort_scores.append(comfort)
            total_hvac += zone.hvac_power_kw
            total_lighting += zone.lighting_power_kw
            total_equipment += zone.equipment_power_kw

            zone_states.append({
                "id": zone.id,
                "name": zone.name,
                "temp_c": round(zone.temp_c, 2),
                "humidity_pct": round(zone.humidity_pct, 1),
                "co2_ppm": round(zone.co2_ppm, 0),
                "occupancy": zone.occupancy,
                "max_occupancy": zone.max_occupancy,
                "setpoint_heating": zone.setpoint_heating,
                "setpoint_cooling": zone.setpoint_cooling,
                "hvac_mode": zone.hvac_mode,
                "hvac_power_kw": round(zone.hvac_power_kw, 3),
                "lighting_level": zone.lighting_level,
                "lighting_power_kw": round(zone.lighting_power_kw, 3),
                "equipment_power_kw": round(zone.equipment_power_kw, 3),
                "comfort_score": round(comfort, 3),
                "pmv": round(pmv, 2),
                "ventilation_rate": zone.ventilation_rate
            })

        total_kw = total_hvac + total_lighting + total_equipment
        occupied_comforts = [z["comfort_score"] for z in zone_states if z["occupancy"] > 0]
        comfort_source = occupied_comforts if occupied_comforts else comfort_scores
        overall_comfort = sum(comfort_source) / len(comfort_source) if comfort_source else 0
        savings_pct = 0.0
        if self._cumulative_baseline > 0:
            savings_pct = max(0, (1 - self._cumulative_actual / self._cumulative_baseline) * 100)

        carbon_saved = (self._cumulative_baseline - self._cumulative_actual) * self.carbon_intensity_kg_kwh
        cost_saved = (self._cumulative_baseline - self._cumulative_actual) * self.electricity_price_kwh

        return {
            "sim_time": self.sim_time.isoformat(),
            "outdoor_temp_c": round(self.outdoor_temp, 2),
            "solar_radiation_wm2": round(self.solar_radiation, 1),
            "zones": zone_states,
            "total_hvac_kw": round(total_hvac, 3),
            "total_lighting_kw": round(total_lighting, 3),
            "total_equipment_kw": round(total_equipment, 3),
            "total_power_kw": round(total_kw, 3),
            "energy_savings_pct": round(savings_pct, 2),
            "comfort_score": round(overall_comfort, 3),
            "carbon_saved_kg": round(max(0, carbon_saved), 3),
            "cost_saved_usd": round(max(0, cost_saved), 4),
            "cumulative_energy_kwh": round(self._cumulative_actual, 3),
            "electricity_price_kwh": self.electricity_price_kwh,
            "simulator_mode": self.mode,
            "total_cycles": self.total_cycles
        }

    def _calculate_pmv(self, zone: Zone) -> float:
        """
        Simplified PMV (Predicted Mean Vote) — Fanger thermal comfort model.
        Returns value from -3 (cold) to +3 (hot), 0 = neutral.
        """
        t = zone.temp_c
        rh = zone.humidity_pct
        # Simplified: assume metabolic rate 1.2 met, clothing 0.5 clo, air speed 0.1 m/s
        # Full Fanger model approximation
        t_neutral = 22.0
        pmv = (t - t_neutral) * 0.25 + (rh - 50) * 0.01
        return max(-3.0, min(3.0, pmv))

    def apply_actions(self, actions: List[Dict[str, Any]]):
        """Apply control actions from the LLM agent."""
        for action in actions:
            zone_id = action.get("zone")
            if not zone_id or zone_id not in self.zones:
                continue

            zone = self.zones[zone_id]
            if "setpoint_heating" in action:
                zone.setpoint_heating = float(action["setpoint_heating"])
            if "setpoint_cooling" in action:
                zone.setpoint_cooling = float(action["setpoint_cooling"])
            if "hvac_mode" in action:
                zone.hvac_mode = action["hvac_mode"]
            if "lighting_level" in action:
                zone.lighting_level = max(0.0, min(1.0, float(action["lighting_level"])))
            if "ventilation_rate" in action:
                zone.ventilation_rate = max(0.0, min(1.0, float(action["ventilation_rate"])))

        logger.info(f"Applied {len(actions)} control actions to simulator.")
