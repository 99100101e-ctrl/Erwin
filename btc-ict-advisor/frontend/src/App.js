import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API = "http://localhost:8001";
const tabs = ["LIVE", "CHART", "SIGNAL", "SESSIONS", "BACKTEST", "SETTINGS"];

export default function App() {
  const [state, setState] = useState(null);
  const [history, setHistory] = useState({ items: [], all_data_ready: false, message: "Loading..." });
  const [activeTab, setActiveTab] = useState("LIVE");
  const [indicatorData, setIndicatorData] = useState(null);

  useEffect(() => {
    const fetchHistory = async () => {
      const { data } = await axios.get(`${API}/api/history/status`);
      setHistory(data);
    };
    fetchHistory();
    const id = setInterval(fetchHistory, 1500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!history.all_data_ready) {
      return;
    }
    const load = async () => {
      const [stateResp, indResp] = await Promise.all([
        axios.get(`${API}/api/state`),
        axios.get(`${API}/api/indicators`),
      ]);
      setState(stateResp.data);
      setIndicatorData(indResp.data);
    };
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [history.all_data_ready]);

  const scoreStyle = useMemo(() => ({ width: `${state?.score || 0}%` }), [state]);

  if (!history.all_data_ready) {
    return (
      <div className="app loading-wrap">
        <h1>BTC ICT Advisor</h1>
        {history.items.map((item) => (
          <p key={item.timeframe}>{item.message}</p>
        ))}
        <div className="bar"><div className="fill" style={{ width: `${(history.items.length / 5) * 100}%` }} /></div>
        <p>{history.message}</p>
        <Footer />
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <h1>BTC ICT Advisor — HugoFX SMC Method</h1>
      </header>
      {activeTab === "LIVE" && (
        <section className="card">
          <h2>${state?.price?.toLocaleString() || "-"}</h2>
          <p>Signal: <strong>{state?.signal}</strong></p>
          <p>HTF Bias: {state?.htf_bias_score}</p>
          <p>Daily Bias: {state?.daily_bias}</p>
          <p>Kill Zone: {state?.kill_zone}</p>
          <div className="bar"><div className="fill" style={scoreStyle} /></div>
          <p>{state?.score}% score ({state?.confirmed}/{state?.total} indicators confirming)</p>
        </section>
      )}
      {activeTab === "SETTINGS" && (
        <section className="card">
          <h3>Indicator Selector</h3>
          {Object.entries(indicatorData?.categories || {}).map(([group, items]) => (
            <div key={group} className="group">
              <h4>{group}</h4>
              <div className="chips">
                {items.map((name) => (
                  <span key={name} className={indicatorData.active_indicators.includes(name) ? "chip on" : "chip"}>{name}</span>
                ))}
              </div>
            </div>
          ))}
          <p>Minimum score threshold: {indicatorData?.min_score_threshold}%</p>
        </section>
      )}
      {activeTab !== "LIVE" && activeTab !== "SETTINGS" && <section className="card">{activeTab} tab scaffolded and ready for expansion.</section>}
      <nav className="bottom-nav">
        {tabs.map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} className={activeTab === tab ? "active" : ""}>{tab}</button>
        ))}
      </nav>
      <Footer />
    </div>
  );
}

function Footer() {
  return <footer>Not financial advice — for informational purposes only</footer>;
}
