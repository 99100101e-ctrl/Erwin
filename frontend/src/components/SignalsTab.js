import React from 'react';

function fmt(n, d = 0) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function TpSlCard({ label, value, pct, color }) {
  return (
    <div className="glass-card p-4">
      <div className={`text-[10px] uppercase tracking-widest mb-1 font-semibold ${color}`}>{label}</div>
      <div className={`text-xl font-black ${color}`}>${fmt(value)}</div>
      <div className="text-xs text-gray-400 mt-1">
        {pct != null ? `${pct > 0 ? '+' : ''}${pct}%` : ''}
      </div>
    </div>
  );
}

export default function SignalsTab({ data }) {
  const { signal, indicators } = data;
  const s = signal || {};
  const ind = indicators || {};

  const signalColor =
    s.signal === 'STRONG_BUY' || s.signal === 'MODERATE_BUY' ? 'text-green-400' :
    s.signal === 'STRONG_SELL' || s.signal === 'MODERATE_SELL' ? 'text-red-400' :
    'text-gray-400';

  const sr = ind.sr_1h || {};

  return (
    <div className="px-4 pt-4 pb-6 max-w-lg mx-auto space-y-4">
      <h2 className="text-lg font-bold">Signal Details</h2>

      {/* Current signal summary */}
      <div className="glass-card p-4">
        <div className={`text-2xl font-black mb-1 ${signalColor}`}>
          {s.signal || 'HOLD'}
        </div>
        <div className="flex gap-4 text-sm text-gray-400">
          <span>Score: <strong className="text-white">{s.score || 0}/100</strong></span>
          <span>Confidence: <strong className="text-white">{s.confidence || 'Low'}</strong></span>
        </div>
        {s.atr_pct && (
          <div className="text-xs text-gray-500 mt-1">
            ATR: <span className={s.atr_pct > 2.5 ? 'text-red-400' : 'text-gray-300'}>{s.atr_pct.toFixed(2)}%</span>
          </div>
        )}
      </div>

      {/* Full condition breakdown */}
      <div className="glass-card p-4">
        <div className="text-sm font-semibold text-gray-300 mb-3">Condition Breakdown</div>
        {s.conditions_met?.length > 0 && (
          <div className="mb-3">
            <div className="text-xs text-green-400 font-semibold mb-2">✅ Met ({s.conditions_met.length})</div>
            {s.conditions_met.map((c, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-green-300 py-1 border-b border-green-900/30">
                <span className="text-green-500 mt-0.5">✓</span>
                <span>{c}</span>
              </div>
            ))}
          </div>
        )}
        {s.conditions_failed?.length > 0 && (
          <div>
            <div className="text-xs text-red-400 font-semibold mb-2">✗ Not met ({s.conditions_failed.length})</div>
            {s.conditions_failed.map((c, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-red-300/70 py-1 border-b border-red-900/20">
                <span className="text-red-600 mt-0.5">✗</span>
                <span>{c}</span>
              </div>
            ))}
          </div>
        )}
        {!s.conditions_met?.length && !s.conditions_failed?.length && (
          <div className="text-xs text-gray-500">Waiting for indicator data...</div>
        )}
      </div>

      {/* TP/SL Cards */}
      {s.tp1 && (
        <>
          <div className="text-sm font-semibold text-gray-300">Risk Management</div>
          <div className="grid grid-cols-2 gap-3">
            <TpSlCard
              label="Stop Loss"
              value={s.stop_loss}
              pct={s.sl_pct ? -s.sl_pct : null}
              color="text-red-400"
            />
            <TpSlCard
              label={`R/R Ratio`}
              value={null}
              pct={null}
              color="text-yellow-400"
            />
          </div>
          <div className="glass-card p-4">
            <div className="text-xs text-yellow-400 font-semibold mb-2 uppercase tracking-wide">Risk/Reward</div>
            <div className="text-3xl font-black text-yellow-400">{s.risk_reward}:1</div>
            <div className="text-xs text-gray-500 mt-1">Minimum required: 1.5:1</div>
          </div>
          <div className="grid grid-cols-1 gap-3">
            <div className="glass-card p-4 border-l-4 border-green-500">
              <div className="text-xs text-green-400 uppercase tracking-wide font-semibold">TP1 — Take 40%</div>
              <div className="text-2xl font-black text-green-400 mt-1">${fmt(s.tp1)}</div>
              <div className="text-xs text-gray-400 mt-1">+{s.tp1_pct}% from entry</div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mt-2">
                <div className="h-1.5 rounded-full bg-green-500" style={{ width: `${Math.min(100, s.tp1_pct * 10)}%` }} />
              </div>
            </div>
            <div className="glass-card p-4 border-l-4 border-green-400">
              <div className="text-xs text-green-300 uppercase tracking-wide font-semibold">TP2 — Take 35%</div>
              <div className="text-2xl font-black text-green-300 mt-1">${fmt(s.tp2)}</div>
              <div className="text-xs text-gray-400 mt-1">+{s.tp2_pct}% from entry</div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mt-2">
                <div className="h-1.5 rounded-full bg-green-400" style={{ width: `${Math.min(100, s.tp2_pct * 10)}%` }} />
              </div>
            </div>
            <div className="glass-card p-4 border-l-4 border-blue-400">
              <div className="text-xs text-blue-400 uppercase tracking-wide font-semibold">TP3 — Final 25%</div>
              <div className="text-2xl font-black text-blue-400 mt-1">${fmt(s.tp3)}</div>
              <div className="text-xs text-gray-400 mt-1">+{s.tp3_pct}% from entry</div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mt-2">
                <div className="h-1.5 rounded-full bg-blue-400" style={{ width: `${Math.min(100, s.tp3_pct * 6)}%` }} />
              </div>
            </div>
          </div>
        </>
      )}

      {/* Support & Resistance */}
      {(sr.support || sr.resistance) && (
        <div className="glass-card p-4">
          <div className="text-sm font-semibold text-gray-300 mb-3">Support & Resistance (Auto-detected)</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-green-400 uppercase tracking-wide">Support</div>
              <div className="text-lg font-bold text-green-400">${fmt(sr.support)}</div>
              {sr.near_support && (
                <div className="text-xs text-green-300 mt-1">⚡ Price near support!</div>
              )}
            </div>
            <div>
              <div className="text-xs text-red-400 uppercase tracking-wide">Resistance</div>
              <div className="text-lg font-bold text-red-400">${fmt(sr.resistance)}</div>
              {sr.near_resistance && (
                <div className="text-xs text-red-300 mt-1">⚡ Price near resistance!</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Position sizing tip */}
      <div className="glass-card p-4 border border-yellow-900/50">
        <div className="text-xs text-yellow-400 font-semibold uppercase mb-2">Position Sizing</div>
        <div className="text-xs text-gray-300">
          Maximum recommended: <strong className="text-yellow-400">2% of portfolio</strong> per trade
        </div>
        {s.volatility_extreme && (
          <div className="text-xs text-red-400 mt-2 font-semibold">
            ⚠️ Extreme volatility — consider 0.5-1% max
          </div>
        )}
      </div>
    </div>
  );
}
