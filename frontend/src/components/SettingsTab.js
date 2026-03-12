import React, { useState, useEffect } from 'react';

const DEFAULT_SETTINGS = {
  portfolioSize: 10000,
  riskPct: 2,
  currency: 'USD',
  notifications: false,
  notifySignals: true,
  notifyPriceAlerts: true,
  priceAlertAbove: '',
  priceAlertBelow: '',
  btcAmount: '',
  avgBuyPrice: '',
  theme: 'dark',
};

function fmt(n, d = 0) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

export default function SettingsTab({ data }) {
  const [settings, setSettings] = useState(() => {
    try {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem('btc-advisor-settings') || 'null') };
    } catch {
      return DEFAULT_SETTINGS;
    }
  });
  const [pnl, setPnl] = useState({ trades: [], total: 0 });
  const [notifPermission, setNotifPermission] = useState(
    typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'
  );

  // Load P&L from localStorage
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('btc-advisor-pnl') || '[]');
      const total = saved.reduce((s, t) => s + (t.pnl || 0), 0);
      setPnl({ trades: saved, total });
    } catch {}
  }, []);

  const save = (newSettings) => {
    setSettings(newSettings);
    localStorage.setItem('btc-advisor-settings', JSON.stringify(newSettings));
  };

  const handleNotifToggle = async () => {
    if (typeof Notification === 'undefined') return;
    if (!settings.notifications) {
      // Enabling — request permission
      const perm = await Notification.requestPermission();
      setNotifPermission(perm);
      if (perm === 'granted') {
        save({ ...settings, notifications: true });
        new Notification('BTC Advisor', {
          body: 'Notifications enabled! You will be alerted on strong signals and price alerts.',
          icon: '/favicon.ico',
        });
      }
    } else {
      save({ ...settings, notifications: false });
    }
  };

  const positionSize = (settings.portfolioSize * (settings.riskPct / 100)).toFixed(2);
  const signal = data.signal || {};

  // Unrealized P&L
  const btcAmt = parseFloat(settings.btcAmount) || 0;
  const avgBuy = parseFloat(settings.avgBuyPrice) || 0;
  const currentPrice = data.price || 0;
  const unrealizedPnl = btcAmt && avgBuy && currentPrice
    ? (currentPrice - avgBuy) * btcAmt
    : null;
  const unrealizedPct = btcAmt && avgBuy && currentPrice
    ? ((currentPrice - avgBuy) / avgBuy) * 100
    : null;
  const costBasis = btcAmt && avgBuy ? btcAmt * avgBuy : null;

  const riskAmt = signal.stop_loss && data.price
    ? Math.abs(data.price - signal.stop_loss)
    : null;
  const contracts = riskAmt
    ? Math.floor(parseFloat(positionSize) / riskAmt)
    : null;

  const notifSupported = typeof Notification !== 'undefined' && notifPermission !== 'unsupported';
  const notifBlocked = notifPermission === 'denied';

  return (
    <div className="px-4 pt-4 pb-6 max-w-lg mx-auto space-y-4">
      <h2 className="text-lg font-bold">Settings & Portfolio</h2>

      {/* Notifications */}
      <div className="glass-card p-4 space-y-3">
        <div className="text-sm font-semibold text-gray-300 mb-1">Notifications</div>

        {!notifSupported && (
          <div className="text-xs text-red-400 bg-red-900/30 rounded p-2">
            Browser notifications are not supported on this device/browser.
          </div>
        )}
        {notifBlocked && (
          <div className="text-xs text-yellow-400 bg-yellow-900/30 rounded p-2">
            Notifications are blocked. Enable them in your browser settings, then toggle again.
          </div>
        )}

        {notifSupported && (
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-gray-300">Enable Notifications</div>
              <div className="text-xs text-gray-500">
                {settings.notifications ? 'Active — alerts will fire' : 'Off'}
              </div>
            </div>
            <button
              onClick={handleNotifToggle}
              disabled={notifBlocked}
              className={`relative w-11 h-6 rounded-full transition-colors ${
                settings.notifications ? 'bg-[#F7931A]' : 'bg-gray-700'
              } ${notifBlocked ? 'opacity-40 cursor-not-allowed' : ''}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                settings.notifications ? 'translate-x-5' : 'translate-x-0.5'
              }`} />
            </button>
          </div>
        )}

        {settings.notifications && (
          <>
            <div className="border-t border-gray-700 pt-3 space-y-2">
              <div className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-2">Alert Types</div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.notifySignals}
                  onChange={e => save({ ...settings, notifySignals: e.target.checked })}
                  className="accent-[#F7931A]"
                />
                <span className="text-sm text-gray-300">Strong signals (BUY / SELL)</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.notifyPriceAlerts}
                  onChange={e => save({ ...settings, notifyPriceAlerts: e.target.checked })}
                  className="accent-[#F7931A]"
                />
                <span className="text-sm text-gray-300">Price level alerts</span>
              </label>
            </div>

            {settings.notifyPriceAlerts && (
              <div className="border-t border-gray-700 pt-3 space-y-3">
                <div className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-1">Price Alerts</div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Alert when price goes ABOVE ($)</label>
                  <input
                    type="number"
                    placeholder="e.g. 105000"
                    value={settings.priceAlertAbove}
                    onChange={e => save({ ...settings, priceAlertAbove: e.target.value })}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Alert when price goes BELOW ($)</label>
                  <input
                    type="number"
                    placeholder="e.g. 90000"
                    value={settings.priceAlertBelow}
                    onChange={e => save({ ...settings, priceAlertBelow: e.target.value })}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
                  />
                </div>
                {(settings.priceAlertAbove || settings.priceAlertBelow) && data.price && (
                  <div className="text-xs text-gray-500">
                    Current price: ${fmt(data.price)}
                    {settings.priceAlertAbove && (
                      <span className={parseFloat(settings.priceAlertAbove) <= data.price ? ' text-red-400' : ' text-gray-500'}>
                        {' '}• Above ${fmt(parseFloat(settings.priceAlertAbove))}
                        {parseFloat(settings.priceAlertAbove) <= data.price ? ' ⚠️ Already triggered' : ''}
                      </span>
                    )}
                    {settings.priceAlertBelow && (
                      <span className={parseFloat(settings.priceAlertBelow) >= data.price ? ' text-red-400' : ' text-gray-500'}>
                        {' '}• Below ${fmt(parseFloat(settings.priceAlertBelow))}
                        {parseFloat(settings.priceAlertBelow) >= data.price ? ' ⚠️ Already triggered' : ''}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Portfolio settings */}
      <div className="glass-card p-4 space-y-4">
        <div className="text-sm font-semibold text-gray-300 mb-1">Portfolio Settings</div>

        <div>
          <label className="text-xs text-gray-400 mb-1 block">Portfolio Size (USD)</label>
          <input
            type="number"
            value={settings.portfolioSize}
            onChange={e => save({ ...settings, portfolioSize: parseFloat(e.target.value) || 0 })}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400 mb-1 block">Risk per Trade (%)</label>
          <input
            type="number"
            min="0.1"
            max="10"
            step="0.1"
            value={settings.riskPct}
            onChange={e => save({ ...settings, riskPct: parseFloat(e.target.value) || 2 })}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
          />
          <div className="text-xs text-yellow-400 mt-1">Max recommended: 2%</div>
        </div>
      </div>

      {/* BTC Holdings & Unrealized P&L */}
      <div className="glass-card p-4 space-y-3">
        <div className="text-sm font-semibold text-gray-300 mb-1">BTC Holdings</div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Amount (BTC)</label>
            <input
              type="number"
              min="0"
              step="0.001"
              placeholder="e.g. 0.5"
              value={settings.btcAmount}
              onChange={e => save({ ...settings, btcAmount: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Avg Buy Price ($)</label>
            <input
              type="number"
              min="0"
              step="1"
              placeholder="e.g. 95000"
              value={settings.avgBuyPrice}
              onChange={e => save({ ...settings, avgBuyPrice: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
            />
          </div>
        </div>

        {unrealizedPnl !== null ? (
          <div className="mt-2 bg-gray-900 rounded-lg p-3 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">Unrealized P&L</span>
              <span className={`text-base font-black ${unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {unrealizedPnl >= 0 ? '+' : ''}${fmt(unrealizedPnl, 2)}
                <span className="text-xs font-normal ml-1">
                  ({unrealizedPct >= 0 ? '+' : ''}{unrealizedPct.toFixed(2)}%)
                </span>
              </span>
            </div>
            <div className="flex justify-between text-xs text-gray-500">
              <span>Cost basis</span>
              <span>${fmt(costBasis, 2)}</span>
            </div>
            <div className="flex justify-between text-xs text-gray-500">
              <span>Current value</span>
              <span className="text-white">${fmt(btcAmt * currentPrice, 2)}</span>
            </div>
            <div className="flex justify-between text-xs text-gray-500">
              <span>Break-even price</span>
              <span className="text-yellow-400">${fmt(avgBuy)}</span>
            </div>
          </div>
        ) : (
          <div className="text-xs text-gray-600 text-center py-2">
            Enter your BTC amount and average buy price to see unrealized P&L
          </div>
        )}
      </div>

      {/* Position calculator */}
      <div className="glass-card p-4">
        <div className="text-sm font-semibold text-gray-300 mb-3">Position Calculator</div>
        <div className="grid grid-cols-2 gap-3">
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-1">Risk Amount</div>
            <div className="text-xl font-bold text-yellow-400">${fmt(parseFloat(positionSize), 2)}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-1">Portfolio</div>
            <div className="text-xl font-bold text-white">${fmt(settings.portfolioSize)}</div>
          </div>
        </div>
        {contracts && (
          <div className="mt-3 text-center">
            <div className="text-xs text-gray-500 mb-1">Estimated Contracts (based on current signal)</div>
            <div className="text-2xl font-black text-[#F7931A]">{contracts}</div>
          </div>
        )}
        {!contracts && (
          <div className="text-xs text-gray-600 text-center mt-2">
            Generate a signal to see position size
          </div>
        )}
      </div>

      {/* P&L tracker */}
      <div className="glass-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold text-gray-300">P&L Tracker</div>
          <div className={`text-lg font-black ${pnl.total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {pnl.total >= 0 ? '+' : ''}${fmt(pnl.total, 2)}
          </div>
        </div>
        {pnl.trades.length === 0 ? (
          <div className="text-xs text-gray-600 text-center py-4">
            No trades recorded yet.<br/>
            Trades are tracked automatically when signals are generated.
          </div>
        ) : (
          <div className="space-y-2">
            {pnl.trades.slice(0, 10).map((t, i) => (
              <div key={i} className="flex justify-between text-xs">
                <span className="text-gray-400">{t.signal}</span>
                <span className={t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {t.pnl >= 0 ? '+' : ''}${fmt(t.pnl, 2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Network info */}
      <div className="glass-card p-4">
        <div className="text-sm font-semibold text-gray-300 mb-3">iPhone Access</div>
        <div className="text-xs text-gray-400 space-y-1">
          <div>To access on iPhone, connect to the same WiFi network and visit:</div>
          <div className="bg-gray-900 rounded p-2 font-mono text-[#F7931A] break-all">
            http://YOUR_PC_IP:3000
          </div>
          <div className="text-gray-600">
            Find your PC's local IP in the backend startup message.
          </div>
        </div>
      </div>

      {/* Connection status */}
      <div className="glass-card p-4">
        <div className="text-sm font-semibold text-gray-300 mb-3">Connection Status</div>
        <div className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-400">Binance data feed</span>
            <span className={data.connected ? 'text-green-400' : 'text-yellow-400'}>
              {data.connected ? '● Live' : '● Seeded / Offline'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Last update</span>
            <span className="text-gray-300">
              {data.lastUpdate ? new Date(data.lastUpdate).toLocaleTimeString() : '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Current price</span>
            <span className="text-white font-bold">
              {data.price ? `$${fmt(data.price)}` : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="glass-card p-4 border border-yellow-900/50">
        <div className="text-xs font-semibold text-yellow-400 uppercase mb-2">⚠️ Disclaimer</div>
        <div className="text-xs text-gray-400">
          This application is for <strong className="text-white">informational purposes only</strong> and
          does not constitute financial advice. Trading cryptocurrencies involves significant risk of loss.
          Always do your own research and never invest more than you can afford to lose.
        </div>
      </div>
    </div>
  );
}
