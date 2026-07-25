/**
 * useBackendSocket.js
 * WebSocket hook — connects to Eco-Loop FastAPI backend.
 * Falls back to standalone simulation if backend unavailable.
 * Eco-Loop Platform — Honeywell Hackathon 2026
 */

import { useEffect, useRef, useState, useCallback } from 'react'

const WS_URL = 'ws://localhost:8000/ws'
const API_URL = 'http://localhost:8000'
const RECONNECT_MS = 3000
const MAX_RETRIES = 3

/**
 * useBackendSocket
 * Returns { connected, backendData, backendAvailable, startBackendLoop, stopBackendLoop }
 * When connected=true, backendData has live data from FastAPI.
 * When connected=false, caller should use standalone simulation.
 */
export function useBackendSocket({ onData, onError } = {}) {
  const ws = useRef(null)
  const retries = useRef(0)
  const reconnectTimer = useRef(null)
  const [connected, setConnected] = useState(false)
  const [backendAvailable, setBackendAvailable] = useState(null) // null=checking, true, false
  const [lastMessage, setLastMessage] = useState(null)

  const checkBackend = useCallback(async () => {
    try {
      const resp = await fetch(`${API_URL}/api/status`, { signal: AbortSignal.timeout(2000) })
      if (resp.ok) {
        setBackendAvailable(true)
        return true
      }
    } catch {
      // backend not running
    }
    setBackendAvailable(false)
    return false
  }, [])

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return

    try {
      const socket = new WebSocket(WS_URL)

      socket.onopen = () => {
        setConnected(true)
        retries.current = 0
        clearTimeout(reconnectTimer.current)
        console.log('[Eco-Loop] Backend WebSocket connected')
      }

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          setLastMessage(data)
          onData?.(data)
        } catch (e) {
          console.warn('[Eco-Loop] WS parse error:', e)
        }
      }

      socket.onerror = () => {
        setConnected(false)
        onError?.('WebSocket error — using standalone simulation')
      }

      socket.onclose = () => {
        setConnected(false)
        if (retries.current < MAX_RETRIES) {
          retries.current++
          reconnectTimer.current = setTimeout(connect, RECONNECT_MS)
        } else {
          console.log('[Eco-Loop] Backend unavailable — standalone mode active')
          setBackendAvailable(false)
        }
      }

      ws.current = socket
    } catch {
      setConnected(false)
      setBackendAvailable(false)
    }
  }, [onData, onError])

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimer.current)
    ws.current?.close()
    setConnected(false)
  }, [])

  const startBackendLoop = useCallback(async (config = {}) => {
    try {
      const resp = await fetch(`${API_URL}/api/loop/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_seconds: 5, auto_mode: true, ...config }),
      })
      return resp.ok
    } catch {
      return false
    }
  }, [])

  const stopBackendLoop = useCallback(async () => {
    try {
      await fetch(`${API_URL}/api/loop/stop`, { method: 'POST' })
    } catch {}
  }, [])

  const manualControl = useCallback(async (command) => {
    try {
      const resp = await fetch(`${API_URL}/api/building/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(command),
      })
      return resp.ok ? await resp.json() : null
    } catch {
      return null
    }
  }, [])

  // On mount: check if backend is available then attempt WS connection
  useEffect(() => {
    checkBackend().then((available) => {
      if (available) connect()
    })
    return () => disconnect()
  }, [])

  return {
    connected,
    backendAvailable,
    lastMessage,
    connect,
    disconnect,
    startBackendLoop,
    stopBackendLoop,
    manualControl,
    checkBackend,
  }
}
