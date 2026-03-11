import { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = process.env.REACT_APP_WS_URL ||
  (window.location.hostname === 'localhost'
    ? 'ws://localhost:8000/ws'
    : `ws://${window.location.hostname}:8000/ws`);

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
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const prevPrice = useRef(null);
  const [priceDirection, setPriceDirection] = useState(null);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        console.log('WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          handleMessage(msg);
        } catch (e) {
          console.warn('WS parse error:', e);
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        console.log('WebSocket disconnected, reconnecting...');
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.warn('WebSocket error:', err);
      };
    } catch (e) {
      console.error('WebSocket connect error:', e);
      reconnectTimer.current = setTimeout(connect, 5000);
    }
  }, []);

  const handleMessage = useCallback((msg) => {
    const type = msg.type;

    if (type === 'init' || type === 'update') {
      setData(prev => {
        const newPrice = msg.price || prev.price;
        if (newPrice && prevPrice.current && newPrice !== prevPrice.current) {
          setPriceDirection(newPrice > prevPrice.current ? 'up' : 'down');
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
          setPriceDirection(newPrice > prevPrice.current ? 'up' : 'down');
          setTimeout(() => setPriceDirection(null), 1500);
        }
        prevPrice.current = newPrice;
        return { ...prev, price: newPrice };
      });
    } else if (type === 'fear_greed') {
      setData(prev => ({ ...prev, fearGreed: msg.data }));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  // Also fetch initial state via REST
  useEffect(() => {
    fetch('/api/state')
      .then(r => r.json())
      .then(state => {
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
      .catch(e => console.warn('REST init failed:', e));
  }, []);

  return { data, wsConnected, priceDirection };
}
