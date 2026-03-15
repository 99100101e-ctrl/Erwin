import React, { useMemo } from 'react';
import SignalGauge from './SignalGauge';
import FearGreedGauge from './FearGreedGauge';

function fmt(n, decimals = 0) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function pct(n) {
  if (n == null) return '—';
  const v = Number(n) * 100;
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function IndicatorPill({ label, value, color = 'text-gray-300' }) {
  return (
    <div className="glass-card px-3 py-2 flex flex-col items-center gap-0.5">
      <span className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</span>
      <span className={`text-sm font-bold ${color}`}>{value}</span>
    </div>
  );
}

function TrendDot({ label, trend }) {
  const isBull = trend === 'Bullish' || trend === 'Mildly Bullish';
  const isBear = trend === 'Bearish' || trend === 'Mildly Bearish';
  const dot = isBull ? '🟢' : isBear ? '🔴' : '⚪';
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[10px] text-gray-500 uppercase">{label}</span>
      <span className="text-lg leading-none">{dot}</span>
    </div>
  );
}

function TrendBadge({ label, trend }) {
  const color =
    trend === 'Bullish' || trend === 'Mildly Bullish'
      ? 'bg-green-900 text-green-400 border-green-800'
      : trend === 'Bearish' || trend === 'Mildly Bearish'
      ? 'bg-red-900 text-red-400 border-red-800'
      : 'bg-gray-800 text-gray-400 border-gray-700';
  return (
    <div className={`rounded-full px-3 py-1 text-xs font-semibold border ${color}`}>
      {label}: {trend || 'Neutral'}
    </div>
  );
}

export default function LiveTab({ data, priceDirection }) {
  const { price, change24h, indicators, signal, fearGreed, marketPhase,
          trend15m, trend1h, trend4h, trend1d, volatilityLevel } = data;

  const ind = indicators || {};
  const rsi1h = ind.rsi_1h;
  const rsi4h = ind.rsi_4h;
  const macd1h = ind.macd_1h;
  const bb1h = ind.bb_1h;
  const emas1h = ind.emas_1h || {};
  const stoch = ind.stoch_rsi_1h;
  const atrPct = ind.atr_pct;
  const volRatio = ind.volume_ratio_1h;
  const adx = ind.adx_1h;
  const sweep = ind.sweep_1h;
  const poc = ind.poc_1h;
  const liqZone = ind.liq_zone_1h;

  const priceClass = priceDirection === 'up' ? 'price-up' : priceDirection === 'down' ? 'price-down' : 'text-white';

  const signalLabel = useMemo(() => {
    const s = signal?.signal;
    if (!s || s === 'HOLD') return { text: 'HOLD', cls: 'signal-hold', emoji: '⏸' };
    if (!s || s === 'WAIT') return { text: 'WAIT', cls: 'signal-wait', emoji: '⏳' };
    if (s === 'STRONG_BUY') return { text: 'STRONG BUY', cls: 'signal-strong-buy', emoji: '🚀' };
    if (s === 'STRONG_SELL') return { text: 'STRONG SELL', cls: 'signal-strong-sell', emoji: '🔴' };
    if (s === 'MODERATE_BUY') return { text: 'MODERATE BUY', cls: 'signal-moderate-buy', emoji: '📈' };
    if (s === 'MODERATE_SELL') return { text: 'MODERATE SELL', cls: 'signal-moderate-sell', emoji: '📉' };
    return { text: s, cls: 'signal-hold', emoji: '⏸' };
  }, [signal?.signal]);

  const volatilityColor =
    volatilityLevel === 'Extreme' ? 'text-red-400' :
    volatilityLevel === 'High' ? 'text-orange-400' :
    volatilityLevel === 'Medium' ? 'text-yellow-400' :
    'text-green-400';

  return (
    <div className="px-4 pt-4 pb-6 max-w-lg mx-auto space-y-4">
      {/* Price display */}
      <div className="glass-card p-5 text-center">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-1">BTC / USD</div>
        <div className={`text-5xl font-black tabular-nums transition-colors ${priceClass}`}>
          {price ? `$${fmt(price)}` : '—'}
        </div>
        {change24h != null && (
          <div className={`text-sm font-semibold mt-1 ${change24h >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {change24h >= 0 ? '▲' : '▼'} {pct(change24h)} (24h)
          </div>
        )}
        <div className="flex items-center justify-center gap-4 mt-2">
          <span className="text-xs text-gray-500">Market: <span className="text-white">{marketPhase}</span></span>
          <span className={`text-xs font-semibold ${volatilityColor}`}>
            ⚡ {volatilityLevel} volatility
          </span>
        </div>
      </div>

      {/* MTF Scanner */}
      <div className="glass-card p-3">
        <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-2">Multi-Timeframe Scanner</div>
        <div className="grid grid-cols-4 gap-2">
          <TrendDot label="15M" trend={trend15m} />
          <TrendDot label="1H"  trend={trend1h} />
          <TrendDot label="4H"  trend={trend4h} />
          <TrendDot label="1D"  trend={trend1d} />
        </div>
      </div>

      {/* Liquidity sweep alert */}
      {sweep?.detected && (
        <div className={`glass-card p-3 flex items-center gap-3 ${
          sweep.direction === 'bullish'
            ? 'border border-green-700 bg-green-900/20'
            : 'border border-red-700 bg-red-900/20'
        }`}>
          <span className="text-2xl">{sweep.direction === 'bullish' ? '💎' : '🔻'}</span>
          <div>
            <div className={`text-sm font-bold ${sweep.direction === 'bullish' ? 'text-green-400' : 'text-red-400'}`}>
              Liquidity Sweep Detected!
            </div>
            <div className="text-xs text-gray-400">
              {sweep.direction === 'bullish' ? 'Sell-side liquidity taken' : 'Buy-side liquidity taken'} at ${fmt(sweep.level)}
            </div>
          </div>
        </div>
      )}

      {/* POC & Liquidation zone quick info */}
      {(poc || liqZone) && (
        <div className="flex gap-2">
          {poc && (
            <div className="glass-card px-3 py-2 flex-1 text-center">
              <div className="text-[10px] text-yellow-400 uppercase tracking-wide">POC</div>
              <div className="text-sm font-bold text-yellow-300">${fmt(poc)}</div>
            </div>
          )}
          {liqZone && (
            <div className={`glass-card px-3 py-2 flex-1 text-center ${liqZone.near ? 'border border-red-700' : ''}`}>
              <div className="text-[10px] text-red-400 uppercase tracking-wide">
                {liqZone.near ? '⚠️ Liq Zone' : 'Liq Zone'}
              </div>
              <div className="text-sm font-bold text-red-300">${fmt(liqZone.zone)}</div>
              <div className="text-[10px] text-gray-500">{liqZone.proximity_pct?.toFixed(1)}% away</div>
            </div>
          )}
        </div>
      )}

      {/* Trend badges (detailed) */}
      <div className="flex gap-2 flex-wrap">
        <TrendBadge label="1H" trend={trend1h} />
        <TrendBadge label="4H" trend={trend4h} />
      </div>

      {/* Signal panel */}
      <div className={`glass-card p-4 ${signalLabel.cls}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{signalLabel.emoji}</span>
            <div>
              <div className="text-lg font-black">{signalLabel.text}</div>
              <div className="flex gap-2 items-center mt-0.5">
                <span className="text-xs text-gray-400">
                  Conf: <span className="text-white font-semibold">{signal?.confidence || 'Low'}</span>
                </span>
                {signal?.approach && signal.approach !== 'weak' && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                    signal.approach === 'strong'      ? 'bg-green-900 text-green-300' :
                    signal.approach === 'approaching' ? 'bg-yellow-900 text-yellow-300' :
                                                        'bg-gray-800 text-gray-400'
                  }`}>
                    {signal.approach === 'strong' ? '🔥 STRONG' :
                     signal.approach === 'approaching' ? '⚡ APPROACHING' : '📈 BUILDING'}
                  </span>
                )}
              </div>
            </div>
          </div>
          <SignalGauge score={signal?.score || 0} />
        </div>

        {/* Score bar — always visible */}
        <div className="mb-3">
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>
              {signal?.conditions_met?.length > 0
                ? `${signal.conditions_met.length}/${signal.conditions_total || 10} conditions`
                : 'Signal Score'}
            </span>
            <span className="font-bold text-white">{signal?.score || 0}/100</span>
          </div>
          <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full score-bar ${
                (signal?.score || 0) >= 80 ? 'bg-gradient-to-r from-green-600 to-green-400' :
                (signal?.score || 0) >= 60 ? 'bg-gradient-to-r from-yellow-600 to-yellow-400' :
                (signal?.score || 0) >= 40 ? 'bg-gradient-to-r from-orange-700 to-orange-500' :
                'bg-gradient-to-r from-gray-700 to-gray-500'
              }`}
              style={{ width: `${signal?.score || 0}%` }}
            />
          </div>
          {/* Thresholds markers */}
          <div className="relative h-1 mt-0.5">
            <div className="absolute left-[60%] top-0 w-px h-2 bg-yellow-600/50" />
            <div className="absolute left-[80%] top-0 w-px h-2 bg-green-600/50" />
          </div>
        </div>

        {/* Suppression reasons */}
        {signal?.suppressed && signal?.suppress_reasons?.length > 0 && (
          <div className="bg-gray-900 rounded p-2 mb-2 space-y-0.5">
            {signal.suppress_reasons.map((r, i) => (
              <div key={i} className="text-xs text-yellow-400">⏸ {r}</div>
            ))}
          </div>
        )}

        {/* Conditions met */}
        {signal?.conditions_met?.length > 0 && (
          <div className="mt-2">
            <div className="text-xs text-gray-500 mb-1">Conditions triggered:</div>
            {signal.conditions_met.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-1 text-xs text-green-400 py-0.5">
                <span>✓</span>
                <span>{c}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* TP/SL cards */}
      {signal?.tp1 && (
        <div className="grid grid-cols-2 gap-2">
          <div className="glass-card p-3">
            <div className="text-[10px] text-red-400 uppercase tracking-wide mb-1">Stop Loss</div>
            <div className="font-bold text-red-400">${fmt(signal.stop_loss)}</div>
            <div className="text-xs text-gray-500">-{signal.sl_pct}%</div>
          </div>
          <div className="glass-card p-3">
            <div className="text-[10px] text-yellow-400 uppercase tracking-wide mb-1">R/R Ratio</div>
            <div className="font-bold text-yellow-400">{signal.risk_reward}:1</div>
            <div className="text-xs text-gray-500">Min 1.5:1</div>
          </div>
          <div className="glass-card p-3">
            <div className="text-[10px] text-green-400 uppercase tracking-wide mb-1">TP1 — 40%</div>
            <div className="font-bold text-green-400">${fmt(signal.tp1)}</div>
            <div className="text-xs text-gray-500">+{signal.tp1_pct}%</div>
            {signal.breakeven_after_tp1 && (
              <div className="text-[9px] text-yellow-400 mt-1">⚡ Déplacer SL au BE dès TP1</div>
            )}
          </div>
          <div className="glass-card p-3">
            <div className="text-[10px] text-green-300 uppercase tracking-wide mb-1">TP2 — 35%</div>
            <div className="font-bold text-green-300">${fmt(signal.tp2)}</div>
            <div className="text-xs text-gray-500">+{signal.tp2_pct}%</div>
          </div>
          <div className="glass-card p-3 col-span-2">
            <div className="text-[10px] text-blue-400 uppercase tracking-wide mb-1">TP3 — 25%</div>
            <div className="font-bold text-blue-400">${fmt(signal.tp3)}</div>
            <div className="text-xs text-gray-500">+{signal.tp3_pct}%</div>
          </div>
        </div>
      )}

      {/* Indicators grid */}
      <div className="grid grid-cols-3 gap-2">
        <IndicatorPill
          label="RSI 1H"
          value={rsi1h != null ? rsi1h.toFixed(1) : '—'}
          color={rsi1h < 32 ? 'text-green-400' : rsi1h > 68 ? 'text-red-400' : 'text-gray-200'}
        />
        <IndicatorPill
          label="RSI 4H"
          value={rsi4h != null ? rsi4h.toFixed(1) : '—'}
          color={rsi4h < 38 ? 'text-green-400' : rsi4h > 62 ? 'text-red-400' : 'text-gray-200'}
        />
        <IndicatorPill
          label="StochRSI"
          value={stoch ? stoch.k.toFixed(1) : '—'}
          color={stoch?.k < 25 ? 'text-green-400' : stoch?.k > 75 ? 'text-red-400' : 'text-gray-200'}
        />
        <IndicatorPill
          label="MACD"
          value={macd1h ? macd1h.histogram.toFixed(0) : '—'}
          color={macd1h?.histogram > 0 ? 'text-green-400' : 'text-red-400'}
        />
        <IndicatorPill
          label="ATR%"
          value={atrPct != null ? atrPct.toFixed(2) + '%' : '—'}
          color={atrPct > 2.5 ? 'text-red-400' : atrPct > 1.5 ? 'text-yellow-400' : 'text-green-400'}
        />
        <IndicatorPill
          label="Volume"
          value={volRatio != null ? (volRatio * 100).toFixed(0) + '%' : '—'}
          color={volRatio >= 1.3 ? 'text-green-400' : 'text-gray-300'}
        />
        <IndicatorPill label="EMA20" value={emas1h.ema20 ? fmt(emas1h.ema20) : '—'} />
        <IndicatorPill label="EMA50" value={emas1h.ema50 ? fmt(emas1h.ema50) : '—'} />
        <IndicatorPill label="EMA200" value={emas1h.ema200 ? fmt(emas1h.ema200) : '—'} />
        <IndicatorPill
          label="ADX"
          value={adx?.adx != null ? adx.adx.toFixed(1) : '—'}
          color={adx?.trending ? 'text-green-400' : 'text-gray-300'}
        />
        <IndicatorPill
          label="DI+"
          value={adx?.plus_di != null ? adx.plus_di.toFixed(1) : '—'}
          color="text-green-300"
        />
        <IndicatorPill
          label="DI-"
          value={adx?.minus_di != null ? adx.minus_di.toFixed(1) : '—'}
          color="text-red-300"
        />
        {bb1h && (
          <>
            <IndicatorPill label="BB Upper" value={fmt(bb1h.upper)} color="text-red-300" />
            <IndicatorPill label="BB Mid" value={fmt(bb1h.middle)} />
            <IndicatorPill label="BB Lower" value={fmt(bb1h.lower)} color="text-green-300" />
          </>
        )}
      </div>

      {/* Fear & Greed */}
      {fearGreed && <FearGreedGauge data={fearGreed} />}

      {/* Disclaimer */}
      <div className="text-center text-[11px] text-gray-600 pb-2 italic">
        ⚠️ Not financial advice — for informational purposes only
      </div>
    </div>
  );
}
