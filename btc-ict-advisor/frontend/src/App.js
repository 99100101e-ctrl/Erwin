import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API = "http://localhost:8001";
const tabs = ["LIVE", "CHART", "SIGNAL", "SESSIONS", "BACKTEST", "SETTINGS"];
const tfs = ["15m", "1h", "4h", "1d", "1w"];

export default function App() {
  const [state, setState] = useState(null);
  const [history, setHistory] = useState({ items: [], all_data_ready: false, message: "Loading..." });
  const [activeTab, setActiveTab] = useState("LIVE");
  const [indicatorData, setIndicatorData] = useState(null);
  const [chartTf, setChartTf] = useState("1h");
  const [chartData, setChartData] = useState({ candles: [], label: "Loading..." });
  const [apiOnline, setApiOnline] = useState(false);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const { data } = await axios.get(`${API}/api/history/status`);
        setHistory(data);
        setApiOnline(true);
      } catch {
        setApiOnline(false);
      }
    };
    fetchHistory();
    const id = setInterval(fetchHistory, 1500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const [stateResp, indResp] = await Promise.all([
          axios.get(`${API}/api/state`),
          axios.get(`${API}/api/indicators`),
        ]);
        setState(stateResp.data);
        setIndicatorData(indResp.data);
        setApiOnline(true);
      } catch {
        setApiOnline(false);
      }
    };
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const loadChart = async () => {
      try {
        const { data } = await axios.get(`${API}/api/chart/${chartTf}`);
        setChartData(data);
      } catch {
        setChartData({ candles: [], label: "Chart unavailable" });
      }
    };
    loadChart();
    const id = setInterval(loadChart, 5000);
    return () => clearInterval(id);
  }, [chartTf]);

  const scoreStyle = useMemo(() => ({ width: `${state?.score || 0}%` }), [state]);
  const closes = chartData.candles.map((c) => c.close);
  const path = buildLinePath(closes, 780, 260);

  return (
    <div className="app">
      <header>
        <h1>BTC ICT Advisor — HugoFX SMC Method</h1>
        <p className={apiOnline ? "status online" : "status offline"}>
          API: {apiOnline ? "ONLINE" : "OFFLINE"}
          {state?.connection_status ? ` • Feed: ${state.connection_status}` : ""}
        </p>
      </header>

      {!history.all_data_ready && (
        <section className="card loading-wrap">
          <h2>Loading historical data</h2>
          {history.items.map((item) => (
            <p key={item.timeframe}>{item.message}</p>
          ))}
          <div className="bar">
            <div className="fill" style={{ width: `${(history.items.length / 5) * 100}%` }} />
          </div>
          <p>{history.message}</p>
        </section>
      )}

      {activeTab === "LIVE" && (
        <section className="card">
          <h2>${state?.price?.toLocaleString() || "-"}</h2>
          <p>
            Signal: <strong>{state?.signal || "WAIT"}</strong>
          </p>
          <p>HTF Bias: {state?.htf_bias_score || "-"}</p>
          <p>Daily Bias: {state?.daily_bias || "-"}</p>
          <p>Kill Zone: {state?.kill_zone || "-"}</p>
          <div className="bar">
            <div className="fill" style={scoreStyle} />
          </div>
          <p>
            {state?.score || 0}% score ({state?.confirmed || 0}/{state?.total || 0} indicators confirming)
          </p>
        </section>
      )}

      {activeTab === "CHART" && (
        <section className="card">
          <div className="tf-row">
            {tfs.map((tf) => (
              <button key={tf} onClick={() => setChartTf(tf)} className={chartTf === tf ? "active" : ""}>
                {tf}
              </button>
            ))}
          </div>
          <div className="chart-wrap">
            {path ? (
              <svg viewBox="0 0 780 260" role="img" aria-label="BTC line chart">
                <path d={path} stroke="#58a6ff" strokeWidth="2" fill="none" />
              </svg>
            ) : (
              <p>No chart data</p>
            )}
          </div>
          <p>{chartData.label}</p>
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
                  <span key={name} className={indicatorData?.active_indicators?.includes(name) ? "chip on" : "chip"}>
                    {name}
                  </span>
                ))}
              </div>
            </div>
          ))}
          <p>Minimum score threshold: {indicatorData?.min_score_threshold || 70}%</p>
        </section>
      )}

      {activeTab !== "LIVE" && activeTab !== "SETTINGS" && activeTab !== "CHART" && (
        <section className="card">{activeTab} tab scaffolded and ready for expansion.</section>
      )}

      <nav className="bottom-nav">
        {tabs.map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} className={activeTab === tab ? "active" : ""}>
            {tab}
          </button>
        ))}
      </nav>
      <Footer />
    </div>
  );
}

function buildLinePath(values, width, height) {
  if (!values.length) {
    return "";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  return values
    .map((v, idx) => {
      const x = (idx / (values.length - 1 || 1)) * width;
      const y = height - ((v - min) / spread) * height;
      return `${idx === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function Footer() {
  return <footer>Not financial advice — for informational purposes only</footer>;
}
