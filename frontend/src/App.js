import React, { useState, useEffect, useRef } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import LiveTab from './components/LiveTab';
import ChartTab from './components/ChartTab';
import SignalsTab from './components/SignalsTab';
import HistoryTab from './components/HistoryTab';
import SettingsTab from './components/SettingsTab';

const TABS = [
  { id: 'live',     label: 'Live',     icon: '⚡' },
  { id: 'chart',    label: 'Chart',    icon: '📈' },
  { id: 'signals',  label: 'Signals',  icon: '🎯' },
  { id: 'history',  label: 'History',  icon: '📋' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
];

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem('btc-advisor-settings') || 'null') || {};
  } catch {
    return {};
  }
}

function sendNotification(title, body) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    new Notification(title, { body, icon: '/favicon.ico' });
  } catch {}
}

const SIGNAL_STRONG = new Set(['STRONG_BUY', 'STRONG_SELL', 'MODERATE_BUY', 'MODERATE_SELL']);

export default function App() {
  const [activeTab, setActiveTab] = useState('live');
  const [signalBadge, setSignalBadge] = useState(false);
  const { data, wsConnected, priceDirection } = useWebSocket();

  // Notification state tracking
  const prevSignalLabel = useRef(null);
  const alertAboveFired = useRef(false);
  const alertBelowFired = useRef(false);

  // Clear badge when user navigates to live tab
  useEffect(() => {
    if (activeTab === 'live') setSignalBadge(false);
  }, [activeTab]);

  // Fire notifications on signal changes + price alerts
  useEffect(() => {
    const settings = loadSettings();
    if (!settings.notifications) return;

    const signal = data.signal || {};
    const price = data.price;

    // Signal notifications + badge
    if (signal.signal) {
      const label = signal.signal;
      if (label !== prevSignalLabel.current && SIGNAL_STRONG.has(label)) {
        // Set badge on Live tab if user is on another tab
        if (activeTab !== 'live') setSignalBadge(true);

        if (settings.notifySignals) {
          const isBuy = label.includes('BUY');
          const strength = label.startsWith('STRONG') ? 'Strong' : 'Moderate';
          sendNotification(
            `${strength} ${isBuy ? 'BUY' : 'SELL'} Signal`,
            `BTC/USD — Score ${signal.score ?? '?'}/100${price ? ` @ $${Math.round(price).toLocaleString()}` : ''}`
          );
        }
      }
      prevSignalLabel.current = label;
    }

    // Price alert notifications
    if (settings.notifyPriceAlerts && price) {
      const above = parseFloat(settings.priceAlertAbove);
      const below = parseFloat(settings.priceAlertBelow);

      if (above && price >= above && !alertAboveFired.current) {
        alertAboveFired.current = true;
        sendNotification(
          'Price Alert — Target Reached',
          `BTC crossed ABOVE $${above.toLocaleString()} — now at $${Math.round(price).toLocaleString()}`
        );
      }
      // Reset above alert if price drops back 0.5% below threshold
      if (above && price < above * 0.995) alertAboveFired.current = false;

      if (below && price <= below && !alertBelowFired.current) {
        alertBelowFired.current = true;
        sendNotification(
          'Price Alert — Level Breached',
          `BTC dropped BELOW $${below.toLocaleString()} — now at $${Math.round(price).toLocaleString()}`
        );
      }
      // Reset below alert if price rises back 0.5% above threshold
      if (below && price > below * 1.005) alertBelowFired.current = false;
    }
  }, [data.signal, data.price, activeTab]);

  const isExtreme = data.volatilityLevel === 'Extreme';

  return (
    <div className="min-h-screen bg-[#1a1a2e] text-white flex flex-col">
      {/* Extreme volatility banner */}
      {isExtreme && (
        <div className="volatility-extreme bg-red-900 border-b border-red-500 text-red-200 text-center py-2 px-4 text-sm font-semibold z-50">
          ⚠️ EXTREME VOLATILITY — ATR &gt; 2.5% — Reduce position size!
        </div>
      )}

      {/* Connection status bar */}
      <div className="flex items-center justify-between px-4 py-1 bg-[#0f0f1a] text-xs">
        <span className="text-gray-500">BTC Advisor</span>
        <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-semibold bg-[#F7931A]/10 text-[#F7931A] border border-[#F7931A]/30">
          Stratégie E · F5
        </span>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${
            wsConnected && data.price ? 'bg-green-400'
            : wsConnected ? 'bg-yellow-400'
            : 'bg-red-500'
          }`}></span>
          <span className="text-gray-400">
            {wsConnected && data.price ? 'Live'
             : wsConnected ? 'Loading...'
             : 'Offline'}
          </span>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto pb-20">
        {activeTab === 'live'     && <LiveTab data={data} priceDirection={priceDirection} />}
        {activeTab === 'chart'    && <ChartTab data={data} />}
        {activeTab === 'signals'  && <SignalsTab data={data} />}
        {activeTab === 'history'  && <HistoryTab data={data} />}
        {activeTab === 'settings' && <SettingsTab data={data} />}
      </div>

      {/* Bottom Tab Bar */}
      <nav className="tab-bar">
        <div className="flex">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex flex-col items-center py-2 text-xs transition-colors relative ${
                activeTab === tab.id
                  ? 'text-[#F7931A]'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <span className="relative text-lg leading-none mb-0.5">
                {tab.icon}
                {tab.id === 'live' && signalBadge && activeTab !== 'live' && (
                  <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-[#F7931A] animate-pulse" />
                )}
              </span>
              <span>{tab.label}</span>
              {activeTab === tab.id && (
                <span className="absolute bottom-[calc(env(safe-area-inset-bottom)+40px)] w-8 h-0.5 bg-[#F7931A] rounded-full" />
              )}
            </button>
          ))}
        </div>
      </nav>

      {/* Disclaimer */}
      <div className="fixed bottom-[calc(env(safe-area-inset-bottom)+56px)] left-0 right-0 text-center text-[10px] text-gray-600 pointer-events-none">
        Not financial advice — for informational purposes only
      </div>
    </div>
  );
}
