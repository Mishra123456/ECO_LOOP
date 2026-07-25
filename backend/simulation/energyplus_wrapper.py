"""
EnergyPlus Real Integration Wrapper
Connects to actual EnergyPlus via pyenergyplus API (EnergyPlus 23.2+)
Falls back gracefully to physics simulation if EnergyPlus not installed.
Eco-Loop Platform — Honeywell Hackathon 2026
"""

import os
import logging
import subprocess
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("eco-loop.energyplus")

# EnergyPlus output variable names we care about
EP_VARS = {
    "zone_temp": "Zone Mean Air Temperature",
    "zone_humidity": "Zone Air Relative Humidity",
    "zone_co2": "Zone CO2 Concentration",
    "zone_occupancy": "Zone People Occupant Count",
    "zone_lights": "Zone Lights Electric Power",
    "zone_equipment": "Zone Electric Equipment Electric Power",
    "outdoor_temp": "Site Outdoor Air Drybulb Temperature",
    "solar": "Site Direct Solar Radiation Rate per Area",
    "hvac_power": "Facility Total HVAC Electric Demand Power",
    "htg_setpoint": "Zone Thermostat Heating Setpoint Temperature",
    "clg_setpoint": "Zone Thermostat Cooling Setpoint Temperature",
}

ZONE_NAMES = [
    "OFFICE_FLOOR_1",
    "OFFICE_FLOOR_2",
    "CONFERENCE_ROOMS",
    "LOBBY_RECEPTION",
    "SERVER_ROOM",
]


class EnergyPlusWrapper:
    """
    Wraps EnergyPlus via the pyenergyplus Python API (EnergyPlus 23.2+).
    
    Usage:
        wrapper = EnergyPlusWrapper()
        if wrapper.available:
            wrapper.start()
            state = wrapper.get_state()
            wrapper.apply_actions([...])
    """

    def __init__(self):
        self.available = False
        self.api = None
        self.state_handle = None
        self.running = False
        self.current_state: Dict = {}
        self.idf_path = Path(__file__).parent / "models" / "office_building.idf"
        self.epw_path = self._find_epw()
        self._zone_handles: Dict[str, Dict[str, int]] = {}
        self._actuator_handles: Dict[str, Dict[str, int]] = {}
        self._detect_energyplus()

    def _detect_energyplus(self):
        """Detect EnergyPlus installation."""
        ep_paths = [
            os.environ.get("ENERGYPLUS_PATH", ""),
            "C:/EnergyPlusV23-2-0/",
            "C:/EnergyPlus-23-2-0/",
            "/usr/local/EnergyPlus-23-2-0/",
            "/Applications/EnergyPlus-23-2-0/",
        ]
        for path in ep_paths:
            if path and Path(path).exists():
                try:
                    import sys
                    sys.path.insert(0, path)
                    from pyenergyplus.api import EnergyPlusAPI
                    self.api = EnergyPlusAPI()
                    self.available = True
                    logger.info(f"EnergyPlus found at: {path}")
                    return
                except ImportError:
                    continue

        logger.info("EnergyPlus not found — physics simulation mode active.")

    def _find_epw(self) -> Optional[Path]:
        """Find a weather file."""
        candidates = [
            Path(__file__).parent / "weather" / "weather.epw",
            Path("C:/EnergyPlusV23-2-0/WeatherData/USA_CA_San.Francisco.724940_TMY3.epw"),
            Path("/usr/local/EnergyPlus-23-2-0/WeatherData/USA_CA_San.Francisco.724940_TMY3.epw"),
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def start(self):
        """Start EnergyPlus co-simulation."""
        if not self.available or not self.api:
            logger.warning("EnergyPlus not available — using physics sim.")
            return False

        try:
            self.state_handle = self.api.state_manager.new_state()

            # Register callbacks
            self.api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
                self.state_handle, self._on_timestep
            )
            self.api.runtime.callback_end_zone_timestep_after_zone_reporting(
                self.state_handle, self._on_after_timestep
            )

            # Run EnergyPlus in background
            ep_args = [
                "-w", str(self.epw_path) if self.epw_path else "",
                "-d", "./energyplus_output",
                str(self.idf_path)
            ]
            self.api.runtime.run_energyplus(self.state_handle, ep_args)
            self.running = True
            logger.info("EnergyPlus co-simulation started.")
            return True

        except Exception as e:
            logger.error(f"EnergyPlus start failed: {e}")
            return False

    def _get_zone_handle(self, zone_name: str, var_name: str) -> Optional[int]:
        """Get or cache a zone variable handle."""
        if zone_name not in self._zone_handles:
            self._zone_handles[zone_name] = {}
        if var_name not in self._zone_handles[zone_name]:
            try:
                handle = self.api.exchange.get_variable_handle(
                    self.state_handle, var_name, zone_name
                )
                self._zone_handles[zone_name][var_name] = handle
            except Exception:
                return None
        return self._zone_handles[zone_name].get(var_name)

    def _on_timestep(self, state):
        """Called by EnergyPlus at each timestep start."""
        try:
            zones_data = []
            for zone_name in ZONE_NAMES:
                zone_data = {"name": zone_name}
                for key, ep_var in EP_VARS.items():
                    if "Site" in ep_var or "Facility" in ep_var:
                        continue
                    handle = self._get_zone_handle(zone_name, ep_var)
                    if handle and handle != -1:
                        zone_data[key] = self.api.exchange.get_variable_value(state, handle)
                zones_data.append(zone_data)

            # Global variables
            outdoor_h = self.api.exchange.get_variable_handle(
                state, EP_VARS["outdoor_temp"], "Environment"
            )
            solar_h = self.api.exchange.get_variable_handle(
                state, EP_VARS["solar"], "Environment"
            )

            self.current_state = {
                "zones": zones_data,
                "outdoor_temp_c": self.api.exchange.get_variable_value(state, outdoor_h) if outdoor_h != -1 else 15.0,
                "solar_radiation_wm2": self.api.exchange.get_variable_value(state, solar_h) if solar_h != -1 else 0.0,
                "sim_time": datetime.now().isoformat(),
                "source": "energyplus",
            }
        except Exception as e:
            logger.error(f"EnergyPlus timestep read error: {e}")

    def _on_after_timestep(self, state):
        """Called after zone timestep — apply any pending actuator changes."""
        pass

    def get_state(self) -> Dict:
        """Return current EnergyPlus state."""
        return self.current_state

    def set_zone_setpoints(self, zone_name: str, heating_sp: float, cooling_sp: float):
        """Apply setpoint override via EnergyPlus actuator."""
        if not self.available or not self.state_handle:
            return
        try:
            htg_handle = self.api.exchange.get_actuator_handle(
                self.state_handle,
                "Zone Temperature Control",
                "Heating Setpoint",
                zone_name
            )
            clg_handle = self.api.exchange.get_actuator_handle(
                self.state_handle,
                "Zone Temperature Control",
                "Cooling Setpoint",
                zone_name
            )
            if htg_handle != -1:
                self.api.exchange.set_actuator_value(self.state_handle, htg_handle, heating_sp)
            if clg_handle != -1:
                self.api.exchange.set_actuator_value(self.state_handle, clg_handle, cooling_sp)
        except Exception as e:
            logger.error(f"EnergyPlus actuator error: {e}")

    def stop(self):
        """Stop EnergyPlus."""
        if self.state_handle and self.api:
            try:
                self.api.state_manager.delete_state(self.state_handle)
            except Exception:
                pass
        self.running = False
        logger.info("EnergyPlus stopped.")
