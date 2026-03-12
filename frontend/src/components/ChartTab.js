import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';

export default function ChartTab({ data }) {
  const mainRef = useRef(null);
  const deltaRef = useRef(null);
  const mainChart = useRef(null);
  const deltaChart = useRef(null);
  const candleSeries = useRef(null);
  const ema20Series = useRef(null);
  const ema50Series = useRef(null);
  const ema200Series = useRef(null);
  const bbUpperSeries = useRef(null);
  const bbLowerSeries = useRef(null);
  const bbMidSeries = useRef(null);
  const deltaSeries = useRef(null);
  const pocLine = useRef(null);
  const liqLine = useRef(null);
  // FVG primitives stored as an array (cleared and re-added each update)
  const fvgPrimitives = useRef([]);

  // ── Chart initialisation ──────────────────────────────────────────────────
  useEffect(() => {
    if (!mainRef.current || !deltaRef.current) return;

    const baseOpts = {
      layout: { background: { type: ColorType.Solid, color: '#0f0f1a' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true },
    };

    // Main chart
    const mc = createChart(mainRef.current, {
      ...baseOpts,
      crosshair: { mode: CrosshairMode.Normal },
      width: mainRef.current.clientWidth,
      height: mainRef.current.clientHeight,
    });
    mainChart.current = mc;

    candleSeries.current = mc.addCandlestickSeries({
      upColor: '#4ade80', downColor: '#f87171',
      borderUpColor: '#4ade80', borderDownColor: '#f87171',
      wickUpColor: '#4ade80', wickDownColor: '#f87171',
    });
    ema20Series.current  = mc.addLineSeries({ color: '#F7931A', lineWidth: 1, title: 'EMA20' });
    ema50Series.current  = mc.addLineSeries({ color: '#a78bfa', lineWidth: 1, title: 'EMA50' });
    ema200Series.current = mc.addLineSeries({ color: '#60a5fa', lineWidth: 1, title: 'EMA200' });
    bbUpperSeries.current = mc.addLineSeries({ color: 'rgba(248,113,113,0.4)', lineWidth: 1, title: 'BB↑' });
    bbMidSeries.current   = mc.addLineSeries({ color: 'rgba(250,204,21,0.3)',  lineWidth: 1, title: 'BB' });
    bbLowerSeries.current = mc.addLineSeries({ color: 'rgba(74,222,128,0.4)', lineWidth: 1, title: 'BB↓' });
    // POC line
    pocLine.current  = mc.addLineSeries({ color: 'rgba(250,204,21,0.8)', lineWidth: 1, lineStyle: 2, title: 'POC' });
    // Liquidation zone
    liqLine.current  = mc.addLineSeries({ color: 'rgba(239,68,68,0.5)',  lineWidth: 1, lineStyle: 3, title: 'LiqZone' });

    // Delta volume chart (synced timescale)
    const dc = createChart(deltaRef.current, {
      ...baseOpts,
      crosshair: { mode: CrosshairMode.Normal },
      width: deltaRef.current.clientWidth,
      height: deltaRef.current.clientHeight,
      timeScale: { ...baseOpts.timeScale, visible: false },
    });
    deltaChart.current = dc;
    deltaSeries.current = dc.addHistogramSeries({ priceFormat: { type: 'volume' } });

    // Sync timescales
    mc.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (range) dc.timeScale().setVisibleRange(range);
    });
    dc.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (range) mc.timeScale().setVisibleRange(range);
    });

    const handleResize = () => {
      if (mainRef.current) mc.applyOptions({ width: mainRef.current.clientWidth });
      if (deltaRef.current) dc.applyOptions({ width: deltaRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      mc.remove(); dc.remove();
      mainChart.current = null; deltaChart.current = null;
    };
  }, []);

  // ── Data updates ──────────────────────────────────────────────────────────
  useEffect(() => {
    const candles = data.candles1h;
    if (!candles || !candles.length || !candleSeries.current) return;

    const sorted = [...candles].sort((a, b) => a.ts - b.ts);

    // Candlestick
    try {
      candleSeries.current.setData(sorted.map(c => ({
        time: c.ts, open: c.open, high: c.high, low: c.low, close: c.close,
      })));
    } catch (e) {}

    // EMAs
    const ema20d = computeEMA(sorted, 20);
    const ema50d = computeEMA(sorted, 50);
    const ema200d = computeEMA(sorted, 200);
    try {
      if (ema20d.length)  ema20Series.current.setData(ema20d);
      if (ema50d.length)  ema50Series.current.setData(ema50d);
      if (ema200d.length) ema200Series.current.setData(ema200d);
    } catch (e) {}

    // Bollinger Bands (20,2)
    const bbPeriod = 20;
    const bbU = [], bbM = [], bbL = [];
    for (let i = bbPeriod - 1; i < sorted.length; i++) {
      const win = sorted.slice(i - bbPeriod + 1, i + 1).map(c => c.close);
      const mean = win.reduce((s, v) => s + v, 0) / bbPeriod;
      const std  = Math.sqrt(win.reduce((s, v) => s + (v - mean) ** 2, 0) / bbPeriod);
      bbU.push({ time: sorted[i].ts, value: mean + 2 * std });
      bbM.push({ time: sorted[i].ts, value: mean });
      bbL.push({ time: sorted[i].ts, value: mean - 2 * std });
    }
    try {
      if (bbU.length) bbUpperSeries.current.setData(bbU);
      if (bbM.length) bbMidSeries.current.setData(bbM);
      if (bbL.length) bbLowerSeries.current.setData(bbL);
    } catch (e) {}

    // Delta volume bars
    const deltaData = sorted.map(c => ({
      time: c.ts,
      value: c.close >= c.open ? c.volume : -c.volume,
      color: c.close >= c.open ? 'rgba(74,222,128,0.7)' : 'rgba(248,113,113,0.7)',
    }));
    try { deltaSeries.current.setData(deltaData); } catch (e) {}

    // POC line — flat line across full time range at POC price
    const poc = (data.indicators?.poc_1h) ?? null;
    if (poc && sorted.length >= 2) {
      try {
        pocLine.current.setData([
          { time: sorted[0].ts, value: poc },
          { time: sorted[sorted.length - 1].ts, value: poc },
        ]);
      } catch (e) {}
    }

    // Liquidation zone line
    const liq = data.indicators?.liq_zone_1h?.zone ?? null;
    if (liq && sorted.length >= 2) {
      try {
        liqLine.current.setData([
          { time: sorted[0].ts, value: liq },
          { time: sorted[sorted.length - 1].ts, value: liq },
        ]);
      } catch (e) {}
    }

    // FVG zones — rendered as coloured horizontal band primitives
    // lightweight-charts v4 supports IPrimitive via series.attachPrimitive
    // Simple approach: draw FVGs as extra line pairs (upper + lower bounding the gap)
    // We clear old FVG lines and re-draw
    try {
      fvgPrimitives.current.forEach(s => mainChart.current?.removeSeries(s));
      fvgPrimitives.current = [];
      const fvgs = data.indicators?.fvgs_1h ?? [];
      fvgs.forEach(fvg => {
        const color = fvg.type === 'BISI'
          ? 'rgba(74,222,128,0.12)'
          : 'rgba(248,113,113,0.12)';
        const borderColor = fvg.type === 'BISI'
          ? 'rgba(74,222,128,0.5)'
          : 'rgba(248,113,113,0.5)';

        // Find the candle ts at fvg.ts and extend to end
        const startTs = fvg.ts;
        const endTs = sorted[sorted.length - 1].ts;
        if (startTs >= endTs) return;

        // Top boundary
        const topSeries = mainChart.current.addLineSeries({
          color: borderColor, lineWidth: 1, lineStyle: 3,
          lastValueVisible: false, priceLineVisible: false,
        });
        topSeries.setData([{ time: startTs, value: fvg.top }, { time: endTs, value: fvg.top }]);

        // Bottom boundary
        const botSeries = mainChart.current.addLineSeries({
          color: borderColor, lineWidth: 1, lineStyle: 3,
          lastValueVisible: false, priceLineVisible: false,
        });
        botSeries.setData([{ time: startTs, value: fvg.bottom }, { time: endTs, value: fvg.bottom }]);

        fvgPrimitives.current.push(topSeries, botSeries);
      });
    } catch (e) {}

  
  }, [data.candles1h, data.indicators]);

  const ind = data.indicators || {};
  const poc  = ind.poc_1h;
  const liq  = ind.liq_zone_1h;
  const adx  = ind.adx_1h;
  const fvgCount = (ind.fvgs_1h || []).length;

  return (
    <div className="flex flex-col h-screen pb-20">
      {/* Header */}
      <div className="px-3 pt-2 pb-1 flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-300">BTC/USD — 1H</h2>
        <div className="flex gap-2 text-[10px] flex-wrap">
          <span className="flex items-center gap-1 text-[#F7931A]">
            <span className="w-3 h-0.5 bg-[#F7931A] inline-block"/>EMA20
          </span>
          <span className="flex items-center gap-1 text-purple-400">
            <span className="w-3 h-0.5 bg-purple-400 inline-block"/>EMA50
          </span>
          <span className="flex items-center gap-1 text-blue-400">
            <span className="w-3 h-0.5 bg-blue-400 inline-block"/>EMA200
          </span>
          <span className="flex items-center gap-1 text-red-400/70">
            <span className="w-3 h-0.5 bg-red-400/50 inline-block"/>BB
          </span>
          {poc && (
            <span className="text-yellow-400/80">
              POC ${poc.toLocaleString()}
            </span>
          )}
          {liq?.near && (
            <span className="text-red-400 font-semibold animate-pulse">
              ⚠️ LiqZone ${liq.zone?.toLocaleString()}
            </span>
          )}
          {adx?.adx && (
            <span className={adx.trending ? 'text-green-400' : 'text-gray-500'}>
              ADX {adx.adx}
            </span>
          )}
          {fvgCount > 0 && (
            <span className="text-teal-400/70">{fvgCount} FVGs</span>
          )}
        </div>
      </div>

      {/* Main chart — 70% height */}
      <div ref={mainRef} className="chart-container" style={{ flex: '7 1 0' }} />

      {/* Delta volume chart — 30% height */}
      <div className="px-3 pt-0.5 pb-0">
        <span className="text-[10px] text-gray-500 uppercase tracking-wide">Delta Volume</span>
      </div>
      <div ref={deltaRef} className="chart-container" style={{ flex: '3 1 0' }} />

      {data.candles1h.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm">
          Waiting for candle data...
        </div>
      )}
    </div>
  );
}

function computeEMA(candles, period) {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const result = [];
  let ema = candles.slice(0, period).reduce((s, c) => s + c.close, 0) / period;
  result.push({ time: candles[period - 1].ts, value: ema });
  for (let i = period; i < candles.length; i++) {
    ema = candles[i].close * k + ema * (1 - k);
    result.push({ time: candles[i].ts, value: ema });
  }
  return result;
}
