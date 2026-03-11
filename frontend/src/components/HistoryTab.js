import React from 'react';

function fmt(n, d = 0) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function signalBadge(signal) {
  if (signal?.includes('STRONG_BUY'))    return { bg: 'bg-green-900 text-green-300 border border-green-700', label: '🚀 STRONG BUY' };
  if (signal?.includes('MODERATE_BUY')) return { bg: 'bg-green-900/50 text-green-400 border border-green-800', label: '📈 MOD BUY' };
  if (signal?.includes('STRONG_SELL'))   return { bg: 'bg-red-900 text-red-300 border border-red-700', label: '🔴 STRONG SELL' };
  if (signal?.includes('MODERATE_SELL'))return { bg: 'bg-red-900/50 text-red-400 border border-red-800', label: '📉 MOD SELL' };
  return { bg: 'bg-gray-800 text-gray-400 border border-gray-700', label: signal || 'HOLD' };
}

export default function HistoryTab({ data }) {
  const history = data.signalHistory || [];

  return (
    <div className="px-4 pt-4 pb-6 max-w-lg mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Signal History</h2>
        <span className="text-xs text-gray-500">{history.length} signals</span>
      </div>

      {history.length === 0 ? (
        <div className="glass-card p-8 text-center">
          <div className="text-4xl mb-3">📋</div>
          <div className="text-gray-400 text-sm">No signals generated yet.</div>
          <div className="text-gray-600 text-xs mt-2">
            Ultra-precise signal logic means less frequent, higher quality signals.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {history.map((item, i) => {
            const badge = signalBadge(item.signal);
            const dt = new Date(item.timestamp);
            const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const dateStr = dt.toLocaleDateString([], { month: 'short', day: 'numeric' });

            return (
              <div key={i} className="glass-card p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="text-center text-xs text-gray-500 w-12">
                    <div>{dateStr}</div>
                    <div className="text-white">{timeStr}</div>
                  </div>
                  <div>
                    <span className={`text-xs font-semibold px-2 py-1 rounded-full ${badge.bg}`}>
                      {badge.label}
                    </span>
                    <div className="text-xs text-gray-500 mt-1">
                      {item.conditions_count}/10 conditions
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-white">${fmt(item.price)}</div>
                  <div className="text-xs text-gray-500">Score: {item.score}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Signal quality note */}
      <div className="glass-card p-4 border border-blue-900/50">
        <div className="text-xs font-semibold text-blue-400 uppercase mb-2">Signal Quality</div>
        <div className="space-y-1 text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-green-400 rounded-full" />
            <span>Score 80-100 = Strong signal (all conditions)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-yellow-400 rounded-full" />
            <span>Score 60-79 = Moderate signal (6+ conditions)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-gray-500 rounded-full" />
            <span>Score &lt;60 = HOLD (no trade recommended)</span>
          </div>
        </div>
      </div>
    </div>
  );
}
