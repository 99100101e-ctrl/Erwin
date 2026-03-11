import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';

export default function ChartTab({ data }) {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const candleSeries = useRef(null);
  const ema20Series = useRef(null);
  const ema50Series = useRef(null);
  const ema200Series = useRef(null);
  const bbUpperSeries = useRef(null);
  const bbLowerSeries = useRef(null);
  const bbMidSeries = useRef(null);

  useEffect(() => {
    if (!chartRef.current) return;

    const chart = createChart(chartRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f0f1a' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1e1e2e' },
        horzLines: { color: '#1e1e2e' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true },
      width: chartRef.current.clientWidth,
      height: chartRef.current.clientHeight,
    });

    chartInstance.current = chart;

    // Candlestick series
    candleSeries.current = chart.addCandlestickSeries({
      upColor: '#4ade80',
      downColor: '#f87171',
      borderUpColor: '#4ade80',
      borderDownColor: '#f87171',
      wickUpColor: '#4ade80',
      wickDownColor: '#f87171',
    });

    // EMA lines
    ema20Series.current = chart.addLineSeries({ color: '#F7931A', lineWidth: 1, title: 'EMA20' });
    ema50Series.current = chart.addLineSeries({ color: '#a78bfa', lineWidth: 1, title: 'EMA50' });
    ema200Series.current = chart.addLineSeries({ color: '#60a5fa', lineWidth: 1, title: 'EMA200' });

    // Bollinger Bands
    bbUpperSeries.current = chart.addLineSeries({ color: 'rgba(248,113,113,0.4)', lineWidth: 1, title: 'BB Upper' });
    bbMidSeries.current = chart.addLineSeries({ color: 'rgba(250,204,21,0.3)', lineWidth: 1, title: 'BB Mid' });
    bbLowerSeries.current = chart.addLineSeries({ color: 'rgba(74,222,128,0.4)', lineWidth: 1, title: 'BB Lower' });

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartInstance.current = null;
    };
  }, []);

  // Update chart data when candles change
  useEffect(() => {
    const candles = data.candles1h;
    if (!candles || !candles.length || !candleSeries.current) return;

    const sorted = [...candles].sort((a, b) => a.ts - b.ts);

    const candleData = sorted.map(c => ({
      time: c.ts,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    try {
      candleSeries.current.setData(candleData);
    } catch (e) {
      console.warn('Chart update error:', e);
    }

    // EMA lines (approximate from close prices)
    const closes = sorted.map(c => c.close);
    if (closes.length >= 20) {
      const ema20Data = computeEMA(sorted, 20);
      const ema50Data = computeEMA(sorted, 50);
      const ema200Data = computeEMA(sorted, 200);
      try {
        if (ema20Data.length) ema20Series.current.setData(ema20Data);
        if (ema50Data.length) ema50Series.current.setData(ema50Data);
        if (ema200Data.length) ema200Series.current.setData(ema200Data);
      } catch (e) {}
    }

    // Bollinger Bands (20, 2) — computed from full candle history
    const bbUpper = [];
    const bbMid = [];
    const bbLower = [];
    const bbPeriod = 20;
    for (let i = bbPeriod - 1; i < sorted.length; i++) {
      const window = sorted.slice(i - bbPeriod + 1, i + 1).map(c => c.close);
      const mean = window.reduce((s, v) => s + v, 0) / bbPeriod;
      const variance = window.reduce((s, v) => s + (v - mean) ** 2, 0) / bbPeriod;
      const std = Math.sqrt(variance);
      bbUpper.push({ time: sorted[i].ts, value: mean + 2 * std });
      bbMid.push({  time: sorted[i].ts, value: mean });
      bbLower.push({ time: sorted[i].ts, value: mean - 2 * std });
    }
    try {
      if (bbUpper.length) bbUpperSeries.current.setData(bbUpper);
      if (bbMid.length)   bbMidSeries.current.setData(bbMid);
      if (bbLower.length) bbLowerSeries.current.setData(bbLower);
    } catch (e) {}
  }, [data.candles1h]);

  return (
    <div className="flex flex-col h-screen pb-20">
      <div className="px-4 pt-3 pb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-300">BTC/USD — 1H Chart</h2>
        <div className="flex gap-2 text-xs flex-wrap justify-end">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#F7931A] inline-block"/>EMA20</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-purple-400 inline-block"/>EMA50</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-400 inline-block"/>EMA200</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-400/50 inline-block"/>BB</span>
        </div>
      </div>
      <div ref={chartRef} className="flex-1 chart-container" />
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
