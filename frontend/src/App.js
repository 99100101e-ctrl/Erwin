import React, { useState } from 'react';
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

export default function App() {
  const [activeTab, setActiveTab] = useState('live');
  const { data, wsConnected, priceDirection } = useWebSocket();

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
              className={`flex-1 flex flex-col items-center py-2 text-xs transition-colors ${
                activeTab === tab.id
                  ? 'text-[#F7931A]'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <span className="text-lg leading-none mb-0.5">{tab.icon}</span>
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
