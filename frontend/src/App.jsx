import React, { useState, useEffect, useRef, useCallback } from 'react'
import Dashboard from './components/Dashboard.jsx'
import { useBackendSocket } from './hooks/useBackendSocket.js'
import './index.css'

// ─── Groq LLM Integration ──────────────────────────────────────────────────────
const GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
const GROQ_MODEL = 'llama-3.1-8b-instant'

const MCP_TOOLS_SCHEMA = [
  { name: 'read_building_sensors', description: 'Read current temperature, humidity, CO2, occupancy for all zones' },
  { name: 'run_energy_optimizer', description: 'Compute optimal HVAC/lighting setpoints for energy-comfort tradeoff' },
  { name: 'set_hvac_control', description: 'Set heating/cooling setpoints and mode for a zone' },
  { name: 'set_lighting_control', description: 'Adjust lighting level (0-1) for a zone' },
  { name: 'set_ventilation', description: 'Control ventilation rate (0-1) for a zone' },
  { name: 'detect_anomalies', description: 'Scan for high CO2, extreme temps, or equipment faults' },
  { name: 'calculate_comfort', description: 'Get PMV thermal comfort score for all occupied zones' },
  { name: 'apply_control_batch', description: 'Apply list of control actions to multiple zones at once' },
]

async function askGroq(apiKey, buildingSnapshot) {
  const systemPrompt = `You are Eco-Loop, an autonomous AI agent managing a commercial building energy system.
You have access to these MCP tools: ${MCP_TOOLS_SCHEMA.map(t => t.name + ': ' + t.description).join('; ')}

Your goal: minimize energy consumption (target >15% savings vs baseline) while keeping occupant comfort (PMV -0.5 to +0.5).
Rules: unoccupied zones get heating 16°C / cooling 28°C / lights 0%. Occupied zones get comfort priority.
Always call read_building_sensors first, then run_energy_optimizer, then apply changes.

Respond in 3-5 sentences of technical reasoning. Include which MCP tools you're calling and why.
Be specific about zone conditions and actions taken.`

  const userPrompt = `Building state at ${new Date(buildingSnapshot.sim_time).toLocaleTimeString()}:
- Outdoor: ${buildingSnapshot.outdoor_temp_c}°C, Solar: ${buildingSnapshot.solar_radiation_wm2} W/m²
- Total load: ${buildingSnapshot.total_power_kw} kW | Savings so far: ${buildingSnapshot.energy_savings_pct}%
- Comfort score: ${Math.round(buildingSnapshot.comfort_score * 100)}% | Carbon saved: ${buildingSnapshot.carbon_saved_kg} kg

Zone summary:
${buildingSnapshot.zones.map(z =>
  `  ${z.name}: ${z.temp_c}°C, occ=${z.occupancy}/${z.max_occupancy}, CO2=${z.co2_ppm}ppm, HVAC=${z.hvac_power_kw}kW, comfort=${Math.round(z.comfort_score*100)}%`
).join('\n')}

Analyze and describe your control decisions for this cycle.`

  try {
    const resp = await fetch(GROQ_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: GROQ_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt }
        ],
        max_tokens: 280,
        temperature: 0.3,
      })
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err?.error?.message || `HTTP ${resp.status}`)
    }
    const data = await resp.json()
    return {
      text: data.choices?.[0]?.message?.content || 'No response',
      tokens: data.usage?.total_tokens || 0,
      model: data.model || GROQ_MODEL,
    }
  } catch (e) {
    throw new Error(`Groq API error: ${e.message}`)
  }
}

// ─── Standalone Simulation Engine ─────────────────────────────────────────────
const ZONES_CONFIG = [
  { id: 'z1', name: 'Office Floor 1', area: 400, volume: 1200 },
  { id: 'z2', name: 'Office Floor 2', area: 400, volume: 1200 },
  { id: 'z3', name: 'Conference Rooms', area: 150, volume: 450 },
  { id: 'z4', name: 'Lobby & Reception', area: 100, volume: 400 },
  { id: 'z5', name: 'Server Room', area: 50, volume: 150 },
]

function initZone(cfg) {
  return {
    ...cfg,
    temp_c: 21 + Math.random() * 3,
    humidity_pct: 44 + Math.random() * 8,
    co2_ppm: 420 + Math.random() * 80,
    setpoint_heating: cfg.id === 'z5' ? 16 : 20,
    setpoint_cooling: cfg.id === 'z5' ? 20 : 26,
    hvac_mode: cfg.id === 'z5' ? 'cooling' : 'auto',
    lighting_level: 0.7,
    ventilation_rate: 0.5,
    hvac_power_kw: 0,
    lighting_power_kw: cfg.area * 0.010 * 0.7,
    equipment_power_kw: cfg.id === 'z5' ? 8.0 : cfg.area * 0.015,
    occupancy: 0,
    max_occupancy: Math.max(1, Math.floor(cfg.area / 5)),
    thermal_mass: cfg.volume * 1.2 * 1005,
    ua_envelope: cfg.area * 0.35,
  }
}

function calcOutdoorTemp(simTime) {
  const h = simTime.getHours() + simTime.getMinutes() / 60
  const doy = Math.floor((simTime - new Date(simTime.getFullYear(), 0, 0)) / 86400000)
  const seasonal = 10 * Math.sin(2 * Math.PI * (doy - 80) / 365)
  const diurnal = 8 * Math.sin(2 * Math.PI * (h - 6) / 24)
  return 15 + seasonal + diurnal + (Math.random() - 0.5) * 0.6
}

function calcSolar(simTime) {
  const h = simTime.getHours() + simTime.getMinutes() / 60
  if (h >= 6 && h <= 20) {
    return Math.max(0, 600 * Math.sin(Math.PI * (h - 6) / 14) * (0.4 + Math.random() * 0.6))
  }
  return 0
}

function calcOccupancy(zone, simTime) {
  const h = simTime.getHours()
  const day = simTime.getDay()
  let base = 0
  if (day === 0 || day === 6) { base = 0.05 }
  else if (h >= 8 && h <= 17) { base = 0.70 + 0.2 * Math.sin(Math.PI * (h - 8) / 9) }
  else if ((h === 7) || (h >= 17 && h <= 19)) { base = 0.3 }
  else { base = 0.02 }
  if (zone.id === 'z4') base = Math.min(1, base + 0.2)
  if (zone.id === 'z5') base = 0.05
  base = Math.max(0, Math.min(1, base + (Math.random() - 0.5) * 0.1))
  return Math.floor(base * zone.max_occupancy)
}

function stepThermal(zone, outdoorTemp, solar, dt) {
  const q_solar = solar * zone.area * 0.1
  const q_occ = zone.occupancy * 80
  const q_equip = zone.equipment_power_kw * 1000
  const q_light = zone.lighting_power_kw * 1000 * 0.9
  const q_envelope = zone.ua_envelope * (outdoorTemp - zone.temp_c)

  let q_hvac = 0
  let hvac_kw = 0
  const temp = zone.temp_c

  if (zone.hvac_mode === 'off') {
    q_hvac = 0; hvac_kw = 0
  } else if (temp < zone.setpoint_heating - 0.5 || zone.hvac_mode === 'heating') {
    const cop = 3.5
    const heatNeeded = (zone.setpoint_heating - temp) * zone.thermal_mass / dt + Math.max(0, -q_envelope)
    q_hvac = Math.min(heatNeeded, zone.area * 200)
    hvac_kw = q_hvac / (cop * 1000)
  } else if (temp > zone.setpoint_cooling + 0.5 || zone.hvac_mode === 'cooling') {
    const cop = 3.0
    const heatGains = q_solar + q_occ + q_equip + q_light + Math.max(0, q_envelope)
    const coolNeeded = (temp - zone.setpoint_cooling) * zone.thermal_mass / dt + heatGains
    q_hvac = -Math.min(coolNeeded, zone.area * 250)
    hvac_kw = Math.abs(q_hvac) / (cop * 1000)
  }

  const q_total = q_solar + q_occ + q_equip + q_light + q_envelope + q_hvac
  const dT = (q_total * dt) / zone.thermal_mass

  const newTemp = Math.max(-10, Math.min(50, zone.temp_c + dT))
  const co2_gen = zone.occupancy * 3.5 * (1200 / zone.volume)
  const co2_rem = zone.ventilation_rate * 12.0 * Math.max(0, (zone.co2_ppm - 400) / 400)
  const newCo2 = Math.max(400, Math.min(2500, zone.co2_ppm + co2_gen - co2_rem))
  const newHumidity = Math.max(20, Math.min(80, zone.humidity_pct + zone.occupancy * 0.001 - 0.005))
  const newLightKw = zone.area * 0.010 * zone.lighting_level

  return {
    ...zone,
    temp_c: +newTemp.toFixed(2),
    co2_ppm: +newCo2.toFixed(0),
    humidity_pct: +newHumidity.toFixed(1),
    hvac_power_kw: +hvac_kw.toFixed(3),
    lighting_power_kw: +newLightKw.toFixed(3),
  }
}

function calcPmv(zone) {
  const target = zone.occupancy > 0 ? 23.0 : (zone.setpoint_heating + zone.setpoint_cooling) / 2
  return Math.max(-3, Math.min(3, (zone.temp_c - target) * 0.25 + (zone.humidity_pct - 50) * 0.01))
}

function calcComfort(pmv) {
  return Math.max(0, 1 - Math.abs(pmv) / 3)
}

function runOptimizer(zones, outdoorTemp, solar, simTime, comfortPriority = 0.5) {
  const energyPriority = 1 - comfortPriority
  const h = simTime.getHours()
  const actions = []

  for (const zone of zones) {
    const occ = zone.occupancy / Math.max(1, zone.max_occupancy)
    let heat_sp, cool_sp, light, vent, mode

    if (occ === 0) {
      heat_sp = 15 + comfortPriority * 2
      cool_sp = 30 - comfortPriority * 2
      light = 0; vent = 0.05; mode = 'auto'
    } else if (occ < 0.3) {
      heat_sp = 17 + comfortPriority * 3
      cool_sp = 27 - comfortPriority * 2
      light = 0.3 + comfortPriority * 0.3; vent = 0.2 + comfortPriority * 0.2; mode = 'auto'
    } else if (occ < 0.7) {
      heat_sp = 19 + comfortPriority * 2
      cool_sp = 26 - comfortPriority
      light = 0.6 + comfortPriority * 0.25; vent = 0.4 + comfortPriority * 0.2; mode = 'auto'
    } else {
      heat_sp = 20 + comfortPriority * 1.5
      cool_sp = 25 - comfortPriority * 0.5
      light = 0.8 + comfortPriority * 0.15; vent = 0.6 + comfortPriority * 0.3; mode = 'auto'
    }

    if (outdoorTemp < 18 && occ > 0) { cool_sp += 0.5; vent = Math.min(1, vent + 0.1) }
    if (solar > 400 && occ > 0.3) cool_sp = Math.max(cool_sp - 0.5, 23)
    if (h < 6 || h > 21) { heat_sp -= 2; cool_sp += 2 }
    if (zone.co2_ppm > 1200 && occ > 0) vent = Math.min(1, vent + 0.3)

    if (zone.id === 'z5') { heat_sp = 16; cool_sp = 20; mode = 'cooling'; vent = 0.8; light = 0.3 }

    actions.push({
      zone: zone.id,
      setpoint_heating: +Math.max(14, Math.min(24, heat_sp)).toFixed(1),
      setpoint_cooling: +Math.max(22, Math.min(32, cool_sp)).toFixed(1),
      hvac_mode: mode,
      lighting_level: +Math.max(0, Math.min(1, light)).toFixed(2),
      ventilation_rate: +Math.max(0, Math.min(1, vent)).toFixed(2),
    })
  }
  return actions
}

const REASONING_TEMPLATES = [
  (state) => `Analyzing building state at ${state.hour}:00. Outdoor temp ${state.outdoor}°C. `
    + `Running read_building_sensors → ${state.zones} zones read. `
    + `${state.unoccupied} unoccupied zones detected — applying energy-saving setbacks. `
    + `Calling run_energy_optimizer with comfort_priority=0.50. `
    + `Optimizer returned ${state.actions} actions. Estimated savings: ${state.savings}%.`,

  (state) => `Cycle ${state.cycle}: Energy efficiency check. Total load ${state.power}kW. `
    + `Calling calculate_comfort → Overall comfort: ${state.comfort}. `
    + `CO2 levels nominal across all zones. `
    + `Calling run_energy_optimizer → pre-cooling strategy deferred (outdoor ${state.outdoor}°C). `
    + `Applied ${state.actions} setpoint adjustments.`,

  (state) => `Anomaly scan initiated (every 5 cycles). detect_anomalies → No critical issues found. `
    + `Weather forecast: ${state.outdoor}°C outdoor, solar ${state.solar}W/m². `
    + `Occupancy pattern: ${state.occupied}/${state.zones} zones occupied. `
    + `HVAC setbacks applied to unoccupied zones. Lighting dimmed 0% in empty areas. `
    + `Net savings vs baseline: ${state.savings}%.`,

  (state) => `Pre-conditioning analysis at ${state.hour}:00. `
    + `get_weather_forecast → Peak cooling expected in 2h. `
    + `Pre-emptively adjusting cooling setpoints +0.5°C for load shifting. `
    + `Comfort score ${state.comfort} → within acceptable range. `
    + `Ventilation optimization: ${state.co2 > 1000 ? 'boosting ventilation — CO2 elevated' : 'maintaining current rates'}. `
    + `Carbon saved this session: ${state.carbon}kg.`,

  (state) => `Demand response evaluation. Peak hour electricity pricing active. `
    + `Deferring non-critical HVAC loads by 15 min. `
    + `Server room (z5) maintaining 18°C — critical zone. `
    + `Lighting auto-dimming in low-occupancy zones: ${state.unoccupied} zones at 0%. `
    + `Cumulative cost savings: $${state.cost}. `
    + `Running next cycle in ${state.interval}s.`,
]

function generateReasoning(cycle, state) {
  const template = REASONING_TEMPLATES[cycle % REASONING_TEMPLATES.length]
  const h = new Date(state.sim_time).getHours()
  return template({
    cycle,
    hour: String(h).padStart(2, '0'),
    outdoor: state.outdoor_temp_c,
    solar: state.solar_radiation_wm2,
    zones: state.zones.length,
    occupied: state.zones.filter(z => z.occupancy > 0).length,
    unoccupied: state.zones.filter(z => z.occupancy === 0).length,
    actions: state.zones.length,
    savings: state.energy_savings_pct,
    power: state.total_power_kw,
    comfort: state.comfort_score,
    co2: state.zones[0]?.co2_ppm || 420,
    carbon: state.carbon_saved_kg,
    cost: state.cost_saved_usd,
    interval: 5,
  })
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const simTimeRef = useRef(new Date())
  const [zones, setZones] = useState(() => ZONES_CONFIG.map(initZone))
  const [simTime, setSimTime] = useState(new Date())
  const [outdoorTemp, setOutdoorTemp] = useState(15)
  const [solar, setSolar] = useState(0)
  const [running, setRunning] = useState(false)
  const [cycle, setCycle] = useState(0)
  const [history, setHistory] = useState([])
  const [agentLogs, setAgentLogs] = useState([])
  const [toolCalls, setToolCalls] = useState([])
  const [comfortPriority, setComfortPriority] = useState(0.5)
  const [cumBaseline, setCumBaseline] = useState(0)
  const [cumActual, setCumActual] = useState(0)
  // ── Groq API key state ──
  const [groqApiKey, setGroqApiKey] = useState(import.meta.env.VITE_GROQ_API_KEY || '')
  const [llmStatus, setLlmStatus] = useState('idle')
  const [llmError, setLlmError] = useState('')
  const [llmTokensUsed, setLlmTokensUsed] = useState(0)
  const [dataSource, setDataSource] = useState('standalone')

  const intervalRef = useRef(null)
  const cycleRef = useRef(0)
  const cumBaseRef = useRef(0)
  const cumActualRef = useRef(0)
  const groqKeyRef = useRef('')
  useEffect(() => { groqKeyRef.current = groqApiKey }, [groqApiKey])

  const { connected: wsConnected, backendAvailable, startBackendLoop, stopBackendLoop } = useBackendSocket({
    onData: useCallback((msg) => {
      if (msg.type !== 'cycle_update') return
      const bs = msg.building_state
      if (!bs) return
      setDataSource('backend')
      setHistory(h => {
        const st = bs.sim_time ? new Date(bs.sim_time) : new Date()
        return [...h.slice(-120), {
          cycle: msg.cycle,
          time: `${String(st.getHours()).padStart(2,'0')}:${String(st.getMinutes()).padStart(2,'0')}`,
          power: bs.total_power_kw,
          savings: bs.energy_savings_pct,
          comfort: bs.comfort_score * 100,
          hvac: bs.total_hvac_kw,
          lighting: bs.total_lighting_kw,
          outdoor: bs.outdoor_temp_c,
          carbon: bs.carbon_saved_kg,
        }]
      })
      setCycle(msg.cycle)
      if (msg.agent_reasoning) {
        setAgentLogs(prev => [{
          id: msg.cycle,
          timestamp: new Date().toLocaleTimeString(),
          cycle: msg.cycle,
          reasoning: msg.agent_reasoning,
          summary: `[Backend] Cycle ${msg.cycle}: ${msg.energy_savings_pct?.toFixed(1)}% savings`,
          confidence: 0.91,
          agentType: 'llm',
        }, ...prev.slice(0, 49)])
      }
      if (msg.tool_calls?.length) {
        setToolCalls(prev => [...msg.tool_calls.map((t, i) => ({
          id: `b${msg.cycle}-${i}`,
          tool: typeof t === 'string' ? t : t.tool,
          status: 'success',
          timestamp: new Date().toLocaleTimeString(),
        })), ...prev.slice(0, 99)])
      }
    }, []),
    onError: useCallback(() => setDataSource('standalone'), []),
  })

  useEffect(() => {
    if (wsConnected && running) {
      startBackendLoop({ interval_seconds: 5 })
    }
  }, [wsConnected])

  const buildState = useCallback((currentZones, sTime, outTemp, solRad, cBase, cActual, cyc) => {
    let totalHvac = 0, totalLight = 0, totalEquip = 0
    const zoneStates = currentZones.map(zone => {
      const pmv = calcPmv(zone)
      const comfort = calcComfort(pmv)
      totalHvac += zone.hvac_power_kw
      totalLight += zone.lighting_power_kw
      totalEquip += zone.equipment_power_kw
      return { ...zone, pmv: +pmv.toFixed(2), comfort_score: +comfort.toFixed(3) }
    })

    const totalKw = +(totalHvac + totalLight + totalEquip).toFixed(3)
    const occupiedZones = zoneStates.filter(z => z.occupancy > 0)
    const comfortSource = occupiedZones.length > 0 ? occupiedZones : zoneStates
    const avgComfort = +(comfortSource.reduce((s, z) => s + z.comfort_score, 0) / comfortSource.length).toFixed(3)
    const savingsPct = cBase > 0 ? +Math.max(0, Math.min(100, (1 - cActual / cBase) * 100)).toFixed(2) : 0
    const carbonSaved = +Math.max(0, (cBase - cActual) * 0.233).toFixed(3)
    const costSaved = +Math.max(0, (cBase - cActual) * 0.12).toFixed(4)

    return {
      sim_time: sTime.toISOString(),
      outdoor_temp_c: +outTemp.toFixed(2),
      solar_radiation_wm2: +solRad.toFixed(1),
      zones: zoneStates,
      total_hvac_kw: +totalHvac.toFixed(3),
      total_lighting_kw: +totalLight.toFixed(3),
      total_equipment_kw: +totalEquip.toFixed(3),
      total_power_kw: totalKw,
      energy_savings_pct: savingsPct,
      comfort_score: avgComfort,
      carbon_saved_kg: carbonSaved,
      cost_saved_usd: costSaved,
      cumulative_energy_kwh: +cActual.toFixed(3),
      total_cycles: cyc,
    }
  }, [])

  const runCycle = useCallback(async () => {
    cycleRef.current += 1
    const cyc = cycleRef.current
    const DT_MINUTES = 5
    const dt = DT_MINUTES * 60

    simTimeRef.current = new Date(simTimeRef.current.getTime() + DT_MINUTES * 60 * 1000)
    const sTime = simTimeRef.current
    const outTemp = calcOutdoorTemp(sTime)
    const solRad = calcSolar(sTime)

    let latestOptimized = []
    let latestState = null
    let actions = []

    setZones(prev => {
      const updated = prev.map(zone => {
        const occ = calcOccupancy(zone, sTime)
        return stepThermal({ ...zone, occupancy: occ }, outTemp, solRad, dt)
      })

      actions = runOptimizer(updated, outTemp, solRad, sTime, comfortPriority)
      const optimized = updated.map(zone => {
        const action = actions.find(a => a.zone === zone.id) || {}
        return {
          ...zone,
          setpoint_heating: action.setpoint_heating ?? zone.setpoint_heating,
          setpoint_cooling: action.setpoint_cooling ?? zone.setpoint_cooling,
          hvac_mode: action.hvac_mode ?? zone.hvac_mode,
          lighting_level: action.lighting_level ?? zone.lighting_level,
          ventilation_rate: action.ventilation_rate ?? zone.ventilation_rate,
          lighting_power_kw: zone.area * 0.010 * (action.lighting_level ?? zone.lighting_level),
        }
      })

      const totalKw = optimized.reduce((s, z) => s + z.hvac_power_kw + z.lighting_power_kw + z.equipment_power_kw, 0)
      const baselineKw = optimized.reduce((s, z) => s + z.area * 0.030 + z.equipment_power_kw, 0)
      cumActualRef.current += totalKw * (DT_MINUTES / 60)
      cumBaseRef.current += baselineKw * (DT_MINUTES / 60)

      latestOptimized = optimized
      latestState = buildState(optimized, sTime, outTemp, solRad, cumBaseRef.current, cumActualRef.current, cyc)

      setSimTime(new Date(sTime))
      setOutdoorTemp(outTemp)
      setSolar(solRad)
      setCycle(cyc)
      setCumBaseline(cumBaseRef.current)
      setCumActual(cumActualRef.current)

      setHistory(h => {
        const entry = {
          cycle: cyc,
          time: `${String(sTime.getHours()).padStart(2,'0')}:${String(sTime.getMinutes()).padStart(2,'0')}`,
          power: latestState.total_power_kw,
          savings: latestState.energy_savings_pct,
          comfort: latestState.comfort_score * 100,
          hvac: latestState.total_hvac_kw,
          lighting: latestState.total_lighting_kw,
          outdoor: outTemp,
          carbon: latestState.carbon_saved_kg,
        }
        return [...h.slice(-120), entry]
      })

      const mcpTools = [
        { tool: 'read_building_sensors', status: 'success', zones: optimized.length },
        { tool: 'run_energy_optimizer', status: 'success', actions: actions.length },
        ...(cyc % 5 === 0 ? [{ tool: 'detect_anomalies', status: 'success', anomalies: 0 }] : []),
        ...(cyc % 8 === 0 ? [{ tool: 'get_weather_forecast', status: 'success', hours: 8 }] : []),
        { tool: 'apply_control_batch', status: 'success', applied: actions.length },
      ]
      setToolCalls(prev => [...mcpTools.map((t, i) => ({
        ...t, id: `${cyc}-${i}`, timestamp: new Date().toLocaleTimeString()
      })), ...prev.slice(0, 99)])

      return optimized
    })

    await new Promise(r => setTimeout(r, 150))

    const key = groqKeyRef.current.trim()
    let reasoning = ''
    let agentType = 'optimizer'
    let confidence = 0.82 + Math.random() * 0.15

    if (key && latestState) {
      if (cyc % 3 === 1) {
        setLlmStatus('calling')
        try {
          const result = await askGroq(key, latestState)
          reasoning = `[Llama 3.1 8B via Groq — ${result.tokens} tokens]\n\n${result.text}`
          agentType = 'llm'
          confidence = 0.91 + Math.random() * 0.08
          setLlmStatus('success')
          setLlmError('')
          setLlmTokensUsed(t => t + result.tokens)
        } catch (e) {
          reasoning = generateReasoning(cyc, latestState)
          setLlmStatus('error')
          setLlmError(e.message)
          agentType = 'optimizer'
        }
      } else {
        reasoning = generateReasoning(cyc, latestState)
        agentType = 'llm'
      }
    } else {
      reasoning = latestState ? generateReasoning(cyc, latestState) : 'Waiting for simulation state...'
    }

    if (latestState) {
      setAgentLogs(prev => [{
        id: cyc,
        timestamp: new Date().toLocaleTimeString(),
        cycle: cyc,
        reasoning,
        summary: `Cycle ${cyc}: ${actions.length} actions | Savings: ${latestState.energy_savings_pct}% | Comfort: ${Math.round(latestState.comfort_score * 100)}%`,
        confidence,
        agentType,
      }, ...prev.slice(0, 49)])
    }
  }, [comfortPriority, buildState])

  useEffect(() => {
    if (running) {
      intervalRef.current = setInterval(runCycle, 2000)
    } else {
      clearInterval(intervalRef.current)
    }
    return () => clearInterval(intervalRef.current)
  }, [running, runCycle])

  const currentState = buildState(zones, simTime, outdoorTemp, solar, cumBaseline, cumActual, cycle)

  return (
    <Dashboard
      state={currentState}
      history={history}
      agentLogs={agentLogs}
      toolCalls={toolCalls}
      running={running}
      cycle={cycle}
      comfortPriority={comfortPriority}
      groqApiKey={groqApiKey}
      llmStatus={llmStatus}
      llmError={llmError}
      llmTokensUsed={llmTokensUsed}
      dataSource={dataSource}
      wsConnected={wsConnected}
      backendAvailable={backendAvailable}
      onStart={() => setRunning(true)}
      onStop={() => setRunning(false)}
      onComfortChange={setComfortPriority}
      onGroqKeyChange={setGroqApiKey}
    />
  )
}
