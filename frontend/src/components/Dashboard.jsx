import React, { useState } from 'react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import {
  Zap, Wind, Thermometer, Users, Activity, Leaf,
  Play, Square, Settings, AlertCircle, CheckCircle,
  TrendingDown, DollarSign, ChevronDown, ChevronUp,
  Cpu, Database, BarChart2, Radio
} from 'lucide-react'
import './Dashboard.css'

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, unit, color, trend, sub }) {
  return (
    <div className="stat-card" style={{ '--accent': color }}>
      <div className="stat-icon"><Icon size={18} /></div>
      <div className="stat-body">
        <div className="stat-label">{label}</div>
        <div className="stat-value">
          <span className="stat-num">{value}</span>
          <span className="stat-unit">{unit}</span>
        </div>
        {sub && <div className="stat-sub">{sub}</div>}
      </div>
      {trend !== undefined && (
        <div className={`stat-trend ${trend >= 0 ? 'up' : 'down'}`}>
          {trend >= 0 ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {Math.abs(trend).toFixed(1)}%
        </div>
      )}
    </div>
  )
}

function ZoneCard({ zone }) {
  const occupied = zone.occupancy > 0
  const comfortPct = Math.round(zone.comfort_score * 100)
  const pmvColor = Math.abs(zone.pmv) < 0.5 ? '#22c55e' : Math.abs(zone.pmv) < 1.5 ? '#f59e0b' : '#ef4444'

  return (
    <div className={`zone-card ${occupied ? 'occupied' : 'empty'}`}>
      <div className="zone-header">
        <span className="zone-name">{zone.name}</span>
        <span className={`zone-badge ${occupied ? 'active' : 'inactive'}`}>
          {occupied ? `${zone.occupancy}/${zone.max_occupancy} occ.` : 'Empty'}
        </span>
      </div>
      <div className="zone-metrics">
        <div className="zone-metric">
          <Thermometer size={12} />
          <span>{zone.temp_c}°C</span>
        </div>
        <div className="zone-metric">
          <Wind size={12} />
          <span>{zone.co2_ppm} ppm</span>
        </div>
        <div className="zone-metric">
          <Zap size={12} />
          <span>{(zone.hvac_power_kw + zone.lighting_power_kw).toFixed(2)} kW</span>
        </div>
      </div>
      <div className="zone-comfort-bar">
        <div className="zone-comfort-label">
          <span>Comfort</span>
          <span style={{ color: pmvColor }}>{comfortPct}%</span>
        </div>
        <div className="zone-comfort-track">
          <div className="zone-comfort-fill" style={{ width: `${comfortPct}%`, background: pmvColor }} />
        </div>
      </div>
      <div className="zone-setpoints">
        <span>🔥 {zone.setpoint_heating}°C</span>
        <span>❄️ {zone.setpoint_cooling}°C</span>
        <span>💡 {Math.round(zone.lighting_level * 100)}%</span>
      </div>
    </div>
  )
}

function AgentLogEntry({ log, expanded, onToggle }) {
  return (
    <div className="agent-log-entry fade-in" onClick={onToggle}>
      <div className="log-header">
        <div className="log-meta">
          <span className="log-cycle">#{log.cycle}</span>
          <span className="log-time mono">{log.timestamp}</span>
          <span className={`log-type ${log.agentType}`}>
            {log.agentType === 'llm' ? '🧠 LLM' : '⚡ OPTIM'}
          </span>
        </div>
        <div className="log-conf">
          <div className="conf-bar">
            <div className="conf-fill" style={{ width: `${Math.round(log.confidence * 100)}%` }} />
          </div>
          <span>{Math.round(log.confidence * 100)}%</span>
        </div>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </div>
      <div className="log-summary">{log.summary}</div>
      {expanded && (
        <div className="log-reasoning mono fade-in">
          {log.reasoning}
        </div>
      )}
    </div>
  )
}

function ToolCallRow({ call }) {
  const icon = call.status === 'success' ? '✓' : '✗'
  return (
    <div className={`tool-call ${call.status}`}>
      <span className="tc-icon">{icon}</span>
      <span className="tc-name mono">{call.tool}</span>
      <span className="tc-time mono">{call.timestamp}</span>
      {call.actions !== undefined && <span className="tc-detail">{call.actions} actions</span>}
      {call.anomalies !== undefined && <span className="tc-detail">{call.anomalies} anomalies</span>}
    </div>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="tt-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="tt-row" style={{ color: p.color }}>
          <span>{p.name}:</span>
          <span>{typeof p.value === 'number' ? p.value.toFixed(2) : p.value}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function Dashboard({
  state, history, agentLogs, toolCalls,
  running, cycle, comfortPriority,
  groqApiKey, llmStatus, llmError, llmTokensUsed,
  dataSource, wsConnected, backendAvailable,
  onStart, onStop, onComfortChange, onGroqKeyChange
}) {
  const [activeTab, setActiveTab] = useState('overview')
  const [expandedLog, setExpandedLog] = useState(null)
  const [showSettings, setShowSettings] = useState(false)

  const savingsPct = state?.energy_savings_pct ?? 0
  const comfort = state?.comfort_score ?? 0
  const totalKw = state?.total_power_kw ?? 0
  const carbonSaved = state?.carbon_saved_kg ?? 0
  const costSaved = state?.cost_saved_usd ?? 0

  const lastHistory = history[history.length - 1]
  const prevHistory = history[history.length - 3]
  const savingsTrend = lastHistory && prevHistory
    ? lastHistory.savings - prevHistory.savings : 0

  return (
    <div className="dashboard">
      {/* ── Header ── */}
      <header className="dash-header">
        <div className="header-brand">
          <div className="brand-icon">🌿</div>
          <div>
            <div className="brand-name">Eco-Loop</div>
            <div className="brand-sub">Autonomous Building Intelligence</div>
          </div>
        </div>

        <div className="header-status">
          <div className={`status-indicator ${running ? 'running' : 'stopped'}`}>
            <span className="status-dot" />
            <span>{running ? 'LOOP ACTIVE' : 'LOOP IDLE'}</span>
          </div>
          <div className="header-meta mono">
            <span>Cycle #{cycle}</span>
            <span>·</span>
            <span>{state?.sim_time ? new Date(state.sim_time).toLocaleTimeString() : '--'}</span>
            <span>·</span>
            <span>{state?.outdoor_temp_c?.toFixed(1)}°C outdoor</span>
          </div>
        </div>

        <div className="header-controls">
          <button
            id="btn-settings"
            className="btn-icon"
            onClick={() => setShowSettings(s => !s)}
          >
            <Settings size={16} />
          </button>
          {running ? (
            <button id="btn-stop" className="btn-stop" onClick={onStop}>
              <Square size={14} /> Stop Loop
            </button>
          ) : (
            <button id="btn-start" className="btn-start" onClick={onStart}>
              <Play size={14} /> Start Loop
            </button>
          )}
        </div>
      </header>

      {/* ── Settings Panel ── */}
      {showSettings && (
        <div className="settings-panel fade-in">
          {/* Groq API Key */}
          <div className="setting-row">
            <label>🧠 Groq API Key</label>
            <input
              id="groq-api-key"
              type="password"
              placeholder="Enter Groq API Key (free at console.groq.com)"
              value={groqApiKey}
              onChange={e => onGroqKeyChange(e.target.value)}
              style={{
                background: 'var(--bg-card)', border: '1px solid var(--border-bright)',
                borderRadius: '5px', padding: '5px 10px', color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)', fontSize: '11px', width: '340px'
              }}
            />
            <span style={{
              fontSize: 10,
              padding: '2px 8px',
              borderRadius: 4,
              fontWeight: 600,
              background: llmStatus === 'success' ? 'rgba(34,197,94,0.15)'
                : llmStatus === 'calling' ? 'rgba(6,182,212,0.15)'
                : llmStatus === 'error' ? 'rgba(239,68,68,0.15)'
                : 'rgba(74,85,104,0.2)',
              color: llmStatus === 'success' ? 'var(--green)'
                : llmStatus === 'calling' ? 'var(--cyan)'
                : llmStatus === 'error' ? 'var(--red)'
                : 'var(--text-muted)'
            }}>
              {llmStatus === 'success' ? '✓ LLM Active'
                : llmStatus === 'calling' ? '⟳ Calling Llama...'
                : llmStatus === 'error' ? `✗ ${llmError?.slice(0,30)}`
                : groqApiKey ? '◎ Key set — awaiting cycle'
                : '○ No key — using optimizer'}
            </span>
            {llmTokensUsed > 0 && (
              <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                {llmTokensUsed} tokens used
              </span>
            )}
          </div>
          {/* Comfort Priority */}
          <div className="setting-row">
            <label>Comfort Priority</label>
            <div className="slider-row">
              <span className="text-green">Energy</span>
              <input
                id="comfort-slider"
                type="range" min="0" max="1" step="0.05"
                value={comfortPriority}
                onChange={e => onComfortChange(parseFloat(e.target.value))}
              />
              <span className="text-amber">Comfort</span>
              <span className="mono">{Math.round(comfortPriority * 100)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* ── KPI Strip ── */}
      <div className="kpi-strip">
        <StatCard
          icon={TrendingDown}
          label="Energy Savings"
          value={savingsPct.toFixed(1)}
          unit="%"
          color="#22c55e"
          trend={savingsTrend}
          sub="vs baseline schedule"
        />
        <StatCard
          icon={Activity}
          label="Comfort Score"
          value={Math.round(comfort * 100)}
          unit="%"
          color="#06b6d4"
          sub="PMV-based thermal comfort"
        />
        <StatCard
          icon={Zap}
          label="Total Load"
          value={totalKw.toFixed(2)}
          unit="kW"
          color="#3b82f6"
          sub={`HVAC: ${state?.total_hvac_kw?.toFixed(2)} kW`}
        />
        <StatCard
          icon={Leaf}
          label="Carbon Saved"
          value={carbonSaved.toFixed(2)}
          unit="kg CO₂"
          color="#a855f7"
          sub="vs rule-based baseline"
        />
        <StatCard
          icon={DollarSign}
          label="Cost Saved"
          value={`$${costSaved.toFixed(3)}`}
          unit=""
          color="#f59e0b"
          sub="cumulative this session"
        />
        <StatCard
          icon={Radio}
          label="Agent Cycles"
          value={cycle}
          unit=""
          color="#ef4444"
          sub={`${agentLogs.length} reasoning entries`}
        />
      </div>

      {/* ── Tab Navigation ── */}
      <nav className="tab-nav">
        {[
          { id: 'overview', label: 'Overview', icon: BarChart2 },
          { id: 'zones', label: 'Zones', icon: Database },
          { id: 'agent', label: 'Agent', icon: Cpu },
          { id: 'energy', label: 'Energy Charts', icon: Zap },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            id={`tab-${id}`}
            className={`tab-btn ${activeTab === id ? 'active' : ''}`}
            onClick={() => setActiveTab(id)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>

      {/* ── Tab Content ── */}
      <div className="tab-content">

        {/* OVERVIEW */}
        {activeTab === 'overview' && (
          <div className="overview-grid fade-in">
            {/* Energy vs Baseline Chart */}
            <div className="chart-card wide">
              <div className="chart-title">Energy Savings vs Baseline (%)</div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gSavings" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: '#4a5568' }} domain={[0, 40]} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="savings" name="Savings %" stroke="#22c55e" fill="url(#gSavings)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Power Breakdown Chart */}
            <div className="chart-card">
              <div className="chart-title">Power Breakdown (kW)</div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={history.slice(-40)} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gHvac" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: '#4a5568' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="hvac" name="HVAC" stroke="#3b82f6" fill="url(#gHvac)" strokeWidth={2} dot={false} stackId="1" />
                  <Area type="monotone" dataKey="lighting" name="Lighting" stroke="#f59e0b" fill="rgba(245,158,11,0.2)" strokeWidth={2} dot={false} stackId="1" />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Comfort Chart */}
            <div className="chart-card">
              <div className="chart-title">Comfort Score (%)</div>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={history.slice(-40)} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: '#4a5568' }} domain={[60, 100]} />
                  <Tooltip content={<CustomTooltip />} />
                  <Line type="monotone" dataKey="comfort" name="Comfort %" stroke="#06b6d4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* MCP Architecture Display */}
            <div className="arch-card wide">
              <div className="chart-title">System Architecture — Live</div>
              <div className="arch-diagram">
                {[
                  { label: 'EnergyPlus\nSimulator', color: '#3b82f6', active: running },
                  { label: 'Sensor\nStream', color: '#06b6d4', active: running },
                  { label: 'MCP\nTools', color: '#a855f7', active: running },
                  { label: 'LLM\nAgent', color: '#22c55e', active: running },
                  { label: 'Action\nPlanner', color: '#f59e0b', active: running },
                  { label: 'Building\nControl', color: '#ef4444', active: running },
                ].map((node, i) => (
                  <React.Fragment key={node.label}>
                    <div className={`arch-node ${node.active ? 'active' : ''}`} style={{ '--nc': node.color }}>
                      <div className="arch-dot" />
                      <span>{node.label}</span>
                    </div>
                    {i < 5 && <div className={`arch-arrow ${node.active ? 'active' : ''}`}>→</div>}
                  </React.Fragment>
                ))}
                {running && <div className="arch-loop-label">↩ Closed Loop</div>}
              </div>
            </div>
          </div>
        )}

        {/* ZONES */}
        {activeTab === 'zones' && (
          <div className="zones-grid fade-in">
            {state?.zones?.map(zone => (
              <ZoneCard key={zone.id} zone={zone} />
            ))}
          </div>
        )}

        {/* AGENT */}
        {activeTab === 'agent' && (
          <div className="agent-layout fade-in">
            <div className="agent-logs-panel">
              <div className="panel-title">
                <Cpu size={14} />
                Agent Reasoning Log
                <span className="panel-count">{agentLogs.length}</span>
              </div>
              <div className="logs-scroll">
                {agentLogs.length === 0 ? (
                  <div className="empty-state">Start the control loop to see agent reasoning</div>
                ) : agentLogs.map(log => (
                  <AgentLogEntry
                    key={log.id}
                    log={log}
                    expanded={expandedLog === log.id}
                    onToggle={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                  />
                ))}
              </div>
            </div>
            <div className="tool-calls-panel">
              <div className="panel-title">
                <Database size={14} />
                MCP Tool Calls
                <span className="panel-count">{toolCalls.length}</span>
              </div>
              <div className="tools-scroll">
                {toolCalls.length === 0 ? (
                  <div className="empty-state">Tool calls appear here</div>
                ) : toolCalls.map(tc => (
                  <ToolCallRow key={tc.id} call={tc} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ENERGY CHARTS */}
        {activeTab === 'energy' && (
          <div className="energy-grid fade-in">
            <div className="chart-card wide">
              <div className="chart-title">Total Power vs Outdoor Temperature</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={history} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval="preserveStartEnd" />
                  <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#4a5568' }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#4a5568' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '11px', color: '#94a3b8' }} />
                  <Line yAxisId="left" type="monotone" dataKey="power" name="Total kW" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  <Line yAxisId="right" type="monotone" dataKey="outdoor" name="Outdoor °C" stroke="#f59e0b" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="chart-card">
              <div className="chart-title">Carbon Saved (kg CO₂ cumulative)</div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gCarbon" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#a855f7" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: '#4a5568' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="carbon" name="CO₂ Saved kg" stroke="#a855f7" fill="url(#gCarbon)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div className="chart-card">
              <div className="chart-title">Energy Savings % Trend</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={history.slice(-20)} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#4a5568' }} interval={4} />
                  <YAxis tick={{ fontSize: 10, fill: '#4a5568' }} domain={[0, 40]} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="savings" name="Savings %" fill="#22c55e" opacity={0.8} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>

      {/* ── Footer ── */}
      <footer className="dash-footer">
        <span>🏆 Honeywell Eco-Loop Hackathon 2026</span>
        <span className="mono">EnergyPlus + MCP + LLM Agents</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
            background: dataSource === 'backend' ? '#22c55e' : '#06b6d4'
          }}/>
          {dataSource === 'backend'
            ? '🔗 Backend WebSocket · Real EnergyPlus'
            : '⚡ Standalone · Physics Simulation'
          }
        </span>
      </footer>
    </div>
  )
}
