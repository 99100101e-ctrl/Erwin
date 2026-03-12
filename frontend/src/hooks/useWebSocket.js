/**
 * useWebSocket — replaced with HTTP polling.
 * Fetches /api/state every 3 seconds. No WebSocket anywhere.
 * Keeps the same return interface {data, wsConnected, priceDirection}
 * so all existing components work without changes.
 */
import { useState, useEffect, useRef } from 'react';

const API_URL = 'http://localhost:8000/api/state';
const POLL_MS  = 3000;

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
    candles4h: [],
    candles1d: [],
    connected: false,
    lastUpdate: null,
  });
  // wsConnected: true = last poll succeeded, false = error / not yet fetched
  const [wsConnected, setWsConnected] = useState(false);
  const [priceDirection, setPriceDirection] = useState(null);
  const prevPrice = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const fetchData = () => {
      fetch(API_URL)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(s => {
          if (cancelled) return;

          // Detect price direction for flash animation
          const newPrice = s.price;
          if (newPrice && prevPrice.current && newPrice !== prevPrice.current) {
            const dir = newPrice > prevPrice.current ? 'up' : 'down';
            setPriceDirection(dir);
            setTimeout(() => setPriceDirection(null), 1500);
          }
          prevPrice.current = newPrice;

          setData({
            price: newPrice,
            change24h: s.price_change_24h ?? null,
            volume24h: s.volume_24h ?? null,
            indicators: s.indicators || {},
            signal: s.signal || {},
            fearGreed: s.fear_greed || null,
            marketPhase: s.market_phase || 'Unknown',
            trend15m: s.trend_15m || 'Neutral',
            trend1h: s.trend_1h || 'Neutral',
            trend4h: s.trend_4h || 'Neutral',
            trend1d: s.trend_1d || 'Neutral',
            volatilityLevel: s.volatility_level || 'Low',
            signalHistory: s.signal_history || [],
            candles1h: s.candles_1h || [],
            candles4h: s.candles_4h || [],
            candles1d: s.candles_1d || [],
            connected: s.connected || false,
            lastUpdate: s.last_update || null,
          });
          setWsConnected(true);
        })
        .catch(err => {
          if (cancelled) return;
          console.warn('[Poll] fetch error:', err.message);
          setWsConnected(false);
        });
    };

    fetchData();                              // immediate on mount
    const id = setInterval(fetchData, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []); // runs exactly once

  return { data, wsConnected, priceDirection };
}
