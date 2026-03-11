import { useState, useEffect, useRef } from 'react';

const WS_URL = 'ws://localhost:8000/ws';

export function useWebSocket() {
  const [data, setData] = useState({
    price: null,
    indicators: {},
    signal: {},
    fearGreed: null,
    marketPhase: 'Unknown',
    trend1h: 'Neutral',
    trend4h: 'Neutral',
    volatilityLevel: 'Low',
    signalHistory: [],
    candles1h: [],
    connected: false,
    lastUpdate: null,
  });
  const [wsConnected, setWsConnected] = useState(false);
  const [priceDirection, setPriceDirection] = useState(null);
  const prevPrice = useRef(null);
  const wsRef = useRef(null);

  // Single effect, empty deps — runs ONCE on mount, cleans up on unmount.
  // Everything lives inside the closure so there are no unstable dependency chains.
  useEffect(() => {
    let cancelled = false;
    let reconnectTimer = null;

    function connect() {
      if (cancelled) return;

      // Skip if a socket is already open or connecting
      if (
        wsRef.current &&
        (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING)
      ) return;

      let ws;
      try {
        ws = new WebSocket(WS_URL);
      } catch (err) {
        console.error('[WS] constructor error:', err);
        reconnectTimer = setTimeout(connect, 5000);
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        console.log('[WS] connected');
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        let msg;
        try { msg = JSON.parse(event.data); }
        catch (e) { console.warn('[WS] parse error', e); return; }

        const type = msg.type;

        if (type === 'init' || type === 'update') {
          setData(prev => {
            const newPrice = msg.price || prev.price;
            if (newPrice && prevPrice.current && newPrice !== prevPrice.current) {
              const dir = newPrice > prevPrice.current ? 'up' : 'down';
              setPriceDirection(dir);
              setTimeout(() => setPriceDirection(null), 1500);
            }
            prevPrice.current = newPrice;
            return {
              price: newPrice,
              indicators: msg.indicators || prev.indicators,
              signal: msg.signal || prev.signal,
              fearGreed: msg.fear_greed || prev.fearGreed,
              marketPhase: msg.market_phase || prev.marketPhase,
              trend1h: msg.trend_1h || prev.trend1h,
              trend4h: msg.trend_4h || prev.trend4h,
              volatilityLevel: msg.volatility_level || prev.volatilityLevel,
              signalHistory: msg.signal_history || prev.signalHistory,
              candles1h: msg.candles_1h || prev.candles1h,
              connected: msg.connected !== undefined ? msg.connected : prev.connected,
              lastUpdate: msg.ts ? new Date(msg.ts * 1000).toISOString() : prev.lastUpdate,
            };
          });
        } else if (type === 'price') {
          setData(prev => {
            const newPrice = msg.price;
            if (newPrice && prevPrice.current && newPrice !== prevPrice.current) {
              const dir = newPrice > prevPrice.current ? 'up' : 'down';
              setPriceDirection(dir);
              setTimeout(() => setPriceDirection(null), 1500);
            }
            prevPrice.current = newPrice;
            return { ...prev, price: newPrice };
          });
        } else if (type === 'fear_greed') {
          setData(prev => ({ ...prev, fearGreed: msg.data }));
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        console.log('[WS] closed — reconnecting in 5s...');
        setWsConnected(false);
        reconnectTimer = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        // onclose fires after onerror; reconnect is handled there
        console.warn('[WS] error');
      };
    }

    connect();

    // Fetch initial state via REST while WS is connecting
    fetch('/api/state')
      .then(r => r.json())
      .then(state => {
        if (cancelled) return;
        setData(prev => ({
          price: state.price || prev.price,
          indicators: state.indicators || prev.indicators,
          signal: state.signal || prev.signal,
          fearGreed: state.fear_greed || prev.fearGreed,
          marketPhase: state.market_phase || prev.marketPhase,
          trend1h: state.trend_1h || prev.trend1h,
          trend4h: state.trend_4h || prev.trend4h,
          volatilityLevel: state.volatility_level || prev.volatilityLevel,
          signalHistory: state.signal_history || prev.signalHistory,
          candles1h: state.candles_1h || prev.candles1h,
          connected: state.connected !== undefined ? state.connected : prev.connected,
          lastUpdate: state.last_update || prev.lastUpdate,
        }));
      })
      .catch(e => console.warn('[REST] init failed:', e));

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onmessage = null;
        wsRef.current.onerror = null;
        wsRef.current.onclose = null;  // must be null before close() to suppress reconnect
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []); // empty deps — intentional: connect logic is self-contained

  return { data, wsConnected, priceDirection };
}
