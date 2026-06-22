/**
 * useSocket.js
 * ============
 * Shared React hook for the Flask-SocketIO WebSocket connection.
 *
 * One socket instance is created for the whole app (module-level singleton).
 * Components subscribe via the hook and get cleaned up automatically.
 *
 * Events pushed by the backend:
 *   "prediction"        — new prediction ready (after every completed round)
 *   "round_complete"    — a round just finished (raw round data)
 *   "state"             — live game phase/multiplier at 100 ms intervals
 *   "decisions_updated" — backfill complete, Actual column now has real data
 *
 * Usage:
 *   const { connected, lastPrediction, lastRound, liveState, updatedDecisions } = useSocket();
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';

// ── Singleton socket ──────────────────────────────────────────────────────

let _socket = null;
let _refCount = 0;

function getSocket() {
  if (!_socket) {
    // Same origin — Vite dev proxy forwards /socket.io to Flask on :5000
    _socket = io({
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      reconnectionDelay: 1000,
      reconnectionAttempts: Infinity,
      timeout: 5000,
      autoConnect: true,
    });
  }
  return _socket;
}

// ── Hook ──────────────────────────────────────────────────────────────────

export default function useSocket() {
  const [connected, setConnected]             = useState(false);
  const [lastPrediction, setLastPred]         = useState(null);
  const [lastRound, setLastRound]             = useState(null);
  const [liveState, setLiveState]             = useState(null);
  const [updatedDecisions, setUpdatedDecisions] = useState(null);

  const socketRef = useRef(null);

  const on  = useCallback((event, handler) => { socketRef.current?.on(event, handler); },  []);
  const off = useCallback((event, handler) => { socketRef.current?.off(event, handler); }, []);

  useEffect(() => {
    const s = getSocket();
    socketRef.current = s;
    _refCount++;

    const onConnect           = () => setConnected(true);
    const onDisconnect        = () => setConnected(false);
    const onPrediction        = (data) => setLastPred(data);
    const onRound             = (data) => setLastRound(data);
    const onState             = (data) => setLiveState(data);
    const onDecisionsUpdated  = (data) => setUpdatedDecisions(data?.decisions ?? null);

    s.on('connect',           onConnect);
    s.on('disconnect',        onDisconnect);
    s.on('prediction',        onPrediction);
    s.on('round_complete',    onRound);
    s.on('state',             onState);
    s.on('decisions_updated', onDecisionsUpdated);

    setConnected(s.connected);

    return () => {
      s.off('connect',           onConnect);
      s.off('disconnect',        onDisconnect);
      s.off('prediction',        onPrediction);
      s.off('round_complete',    onRound);
      s.off('state',             onState);
      s.off('decisions_updated', onDecisionsUpdated);

      _refCount--;
    };
  }, []);

  return { connected, lastPrediction, lastRound, liveState, updatedDecisions, on, off };
}
