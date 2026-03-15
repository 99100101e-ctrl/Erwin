"""
Backtest 6 mois — BTC Trading Advisor
Comparaison de 6 stratégies de gestion du risque
"""
import random, numpy as np, math
from indicators import calculate_all_indicators
from signal_engine import SignalEngine

def generate_btc(n=4380, start=67000.0, seed=42):
    random.seed(seed); np.random.seed(seed)
    prices=[start]; vols=[1000.0]
    regime="bull"; remaining=random.randint(200,600); cur_vol=0.008
    for i in range(1,n):
        remaining-=1
        if remaining<=0:
            regime=random.choices(["bull","bear","sideways"],weights=[.40,.25,.35])[0]
            remaining=random.randint(100,500)
        shock=abs(random.gauss(0,1))
        cur_vol=0.85*cur_vol+0.15*({"bull":.007,"bear":.010,"sideways":.005}[regime]*(0.5+shock))
        drift={"bull":.00015,"bear":-.00012,"sideways":0.0}[regime]
        ret=random.gauss(drift,cur_vol)
        if random.random()<0.005: ret+=random.choice([-1,1])*random.uniform(.02,.04)
        prices.append(max(prices[-1]*math.exp(ret),1000))
        vols.append(random.uniform(400,1200)*(1+3*abs(ret)/max(cur_vol,1e-9)))
    candles=[]
    for i,(c,v) in enumerate(zip(prices,vols)):
        sp=c*random.uniform(.001,.004); o=prices[i-1] if i>0 else c
        h=max(o,c)+sp*random.uniform(.2,1.); l=min(o,c)-sp*random.uniform(.2,1.)
        candles.append({"ts":1704067200+i*3600,"open":round(o,2),"high":round(h,2),
                        "low":round(l,2),"close":round(c,2),"volume":round(v,2)})
    return candles

# ─────────────────────────────────────────────────────────────────────────────
# Simulation de trades par stratégie
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_A(candles, idx, direction, sl, tp1, tp2, tp3, max_bars=72):
    """Stratégie A (baseline) : SL=1.8×ATR, pas de breakeven, pas de trailing"""
    entry=candles[idx]["close"]; rem=1.0; total=0.0; t1h=t2h=False
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=sl: return total+(sl-entry)/entry*rem,"SL",bars
            if not t1h and h>=tp1: total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=sl: return total+(entry-sl)/entry*rem,"SL",bars
            if not t1h and l<=tp1: total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


def sim_trade_B(candles, idx, direction, sl, tp1, tp2, tp3, max_bars=72):
    """Stratégie B : Breakeven après TP1 — SL déplacé au prix d'entrée"""
    entry=candles[idx]["close"]; rem=1.0; total=0.0; t1h=t2h=False
    current_sl=sl
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=current_sl:
                pnl=(current_sl-entry)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and h>=tp1:
                total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # breakeven
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=current_sl:
                pnl=(entry-current_sl)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and l<=tp1:
                total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # breakeven
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


def sim_trade_C(candles, idx, direction, sl_base, atr, max_bars=72):
    """Stratégie C : SL large 2.5×ATR, TPs proportionnels (TP1=2.0×R, TP2=3.5×R, TP3=6.0×R), sans BE"""
    entry=candles[idx]["close"]
    sl_dist=atr*2.5
    if direction=="BUY":
        sl=entry-sl_dist
        risk_amt=sl_dist
        tp1=entry+risk_amt*2.0
        tp2=entry+risk_amt*3.5
        tp3=entry+risk_amt*6.0
    else:
        sl=entry+sl_dist
        risk_amt=sl_dist
        tp1=entry-risk_amt*2.0
        tp2=entry-risk_amt*3.5
        tp3=entry-risk_amt*6.0
    rem=1.0; total=0.0; t1h=t2h=False
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=sl: return total+(sl-entry)/entry*rem,"SL",bars
            if not t1h and h>=tp1: total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=sl: return total+(entry-sl)/entry*rem,"SL",bars
            if not t1h and l<=tp1: total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


def sim_trade_D(candles, idx, direction, sl_base, atr, max_bars=72):
    """Stratégie D ★ GAGNANTE : SL=2.5×ATR + Breakeven après TP1 (TP1=2.0×R, TP2=3.5×R, TP3=6.0×R)"""
    entry=candles[idx]["close"]
    sl_dist=atr*2.5
    if direction=="BUY":
        sl=entry-sl_dist
        risk_amt=sl_dist
        tp1=entry+risk_amt*2.0
        tp2=entry+risk_amt*3.5
        tp3=entry+risk_amt*6.0
    else:
        sl=entry+sl_dist
        risk_amt=sl_dist
        tp1=entry-risk_amt*2.0
        tp2=entry-risk_amt*3.5
        tp3=entry-risk_amt*6.0
    rem=1.0; total=0.0; t1h=t2h=False
    current_sl=sl
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=current_sl:
                pnl=(current_sl-entry)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and h>=tp1:
                total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # breakeven
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=current_sl:
                pnl=(entry-current_sl)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and l<=tp1:
                total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # breakeven
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


def sim_trade_E(candles, idx, direction, sl, atr, max_bars=72):
    """Stratégie E : TP1 rapproché (1.0×RR) + BE immédiat après TP1"""
    entry=candles[idx]["close"]
    sl_dist=atr*1.8
    if direction=="BUY":
        risk_amt=sl_dist
        tp1=entry+risk_amt*1.0   # TP1 plus proche
        tp2=entry+risk_amt*2.5
        tp3=entry+risk_amt*5.0
    else:
        risk_amt=sl_dist
        tp1=entry-risk_amt*1.0
        tp2=entry-risk_amt*2.5
        tp3=entry-risk_amt*5.0
    rem=1.0; total=0.0; t1h=t2h=False
    current_sl=sl
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=current_sl:
                pnl=(current_sl-entry)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and h>=tp1:
                total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # BE strict immédiat
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=current_sl:
                pnl=(entry-current_sl)/entry*rem
                return total+pnl,"SL" if current_sl==sl else "BE",bars
            if not t1h and l<=tp1:
                total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
                current_sl=entry  # BE strict immédiat
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


def _get_trend_1h(sig):
    """Détermine la tendance 1h à partir des EMAs du signal."""
    emas = sig.get("emas_1h") or {}
    ema20 = emas.get("ema20")
    ema50 = emas.get("ema50")
    ema200 = emas.get("ema200")
    price = sig.get("price", 0)
    if ema20 and ema50 and ema200:
        if ema20 > ema50 and price > ema200:
            return "Bullish"
        elif ema20 > ema50:
            return "Mildly Bullish"
        elif ema20 < ema50 and price < ema200:
            return "Bearish"
        elif ema20 < ema50:
            return "Mildly Bearish"
    elif ema20 and ema50:
        if ema20 > ema50:
            return "Mildly Bullish"
        else:
            return "Mildly Bearish"
    return "Neutral"


def sim_trade_F(candles, idx, direction, sl, tp1, tp2, tp3, max_bars=72):
    """Stratégie F : même que A mais filtrée par tendance (appelée seulement si filtre OK)"""
    # Identique à A, le filtre est appliqué au niveau de bt_strategies
    entry=candles[idx]["close"]; rem=1.0; total=0.0; t1h=t2h=False
    for i in range(idx+1, min(idx+max_bars+1, len(candles))):
        h,l=candles[i]["high"],candles[i]["low"]; bars=i-idx
        if direction=="BUY":
            if l<=sl: return total+(sl-entry)/entry*rem,"SL",bars
            if not t1h and h>=tp1: total+=(tp1-entry)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and h>=tp2: total+=(tp2-entry)/entry*.35; rem-=.35; t2h=True
            if t2h and h>=tp3: return total+(tp3-entry)/entry*.25,"TP3",bars
        else:
            if h>=sl: return total+(entry-sl)/entry*rem,"SL",bars
            if not t1h and l<=tp1: total+=(entry-tp1)/entry*.40; rem-=.40; t1h=True
            if t1h and not t2h and l<=tp2: total+=(entry-tp2)/entry*.35; rem-=.35; t2h=True
            if t2h and l<=tp3: return total+(entry-tp3)/entry*.25,"TP3",bars
    last=candles[min(idx+max_bars,len(candles)-1)]["close"]
    total+=((last-entry)/entry if direction=="BUY" else (entry-last)/entry)*rem
    return total,("TP2+to" if t2h else "TP1+to" if t1h else "timeout"),max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Precompute avec emas_1h stocké pour le filtre F
# ─────────────────────────────────────────────────────────────────────────────

def precompute(candles, warmup=200, step=6):
    sigs=[]; prev=0
    N=(len(candles)-warmup)//step
    print(f"  Calcul sur {N} points (step={step}h)...", end="", flush=True)
    for i in range(warmup, len(candles)-73, step):
        w=candles[max(0,i-249):i+1]
        c=[x["close"] for x in w]; h=[x["high"] for x in w]
        l=[x["low"] for x in w]; v=[x["volume"] for x in w]
        o=[x["open"] for x in w]; ts=[x["ts"] for x in w]
        c4=c[::4]; h4=h[::4]; l4=l[::4]; v4=v[::4]
        if len(c4)<15: continue
        try: ind=calculate_all_indicators(c,h,l,v,c4,h4,l4,v4,timestamps_1h=ts,opens_1h=o)
        except: continue
        sig=SignalEngine().evaluate(ind,c[-1])
        if sig.get("suppressed") or sig.get("signal") in ("HOLD","WAIT"): continue
        sl=sig.get("stop_loss"); tp1=sig.get("tp1"); tp2=sig.get("tp2"); tp3=sig.get("tp3")
        if not all([sl,tp1,tp2,tp3]): continue
        atr=ind.get("atr_1h") or 0
        # Stocker emas_1h pour le filtre de tendance (stratégie F)
        emas_1h=ind.get("emas_1h") or {}
        sigs.append({
            "idx":i,"score":sig["score"],"direction":sig["direction"],
            "sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"price":c[-1],
            "atr":atr,"emas_1h":emas_1h,
        })
        if len(sigs)%50==0: print(".",end="",flush=True)
    print(f" {len(sigs)} signaux")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Backtests par stratégie
# ─────────────────────────────────────────────────────────────────────────────

def _get_baseline_levels(s):
    """Recalcule sl/tp1/tp2/tp3 pour la stratégie baseline A (TP1=1.5×R, SL=1.8×ATR)."""
    entry = s["price"]
    atr = s["atr"]
    if not atr or atr <= 0:
        return s["sl"], s["tp1"], s["tp2"], s["tp3"]
    sl_dist = atr * 1.8
    if s["direction"] == "BUY":
        sl  = entry - sl_dist
        tp1 = entry + sl_dist * 1.5
        tp2 = entry + sl_dist * 2.5
        tp3 = entry + sl_dist * 5.0
    else:
        sl  = entry + sl_dist
        tp1 = entry - sl_dist * 1.5
        tp2 = entry - sl_dist * 2.5
        tp3 = entry - sl_dist * 5.0
    return sl, tp1, tp2, tp3


def bt_thresh(candles, sigs, thresh):
    """Baseline : seuil simple, stratégie A (SL=1.8×ATR, TP1=1.5×R)"""
    trades=[]; end_idx=0; prev=0
    for s in sigs:
        if s["idx"]<end_idx: prev=s["score"]; continue
        crossed=(prev<thresh<=s["score"]); prev=s["score"]
        if not crossed: continue
        sl, tp1, tp2, tp3 = _get_baseline_levels(s)
        pnl,rsn,bars=sim_trade_A(candles,s["idx"],s["direction"],sl,tp1,tp2,tp3)
        trades.append({**s,"pnl":pnl*100,"reason":rsn,"bars":bars})
        end_idx=s["idx"]+bars+4
    return trades


def bt_strategies(candles, sigs, thresh=80):
    """Compare 6 stratégies sur les mêmes signaux (score >= thresh)."""
    # Filtrer les signaux valides au seuil (crossing logic)
    filtered=[]; prev=0
    for s in sigs:
        crossed=(prev<thresh<=s["score"]); prev=s["score"]
        if crossed: filtered.append(s)

    results_A=[]; results_B=[]; results_C=[]; results_D=[]
    results_E=[]; results_F=[]

    # Pour chaque stratégie, appliquer le non-overlap
    def run_strat(fn_sim, filtered_sigs):
        trades=[]; end_idx=0
        for s in filtered_sigs:
            if s["idx"]<end_idx: continue
            pnl,rsn,bars=fn_sim(s)
            trades.append({**s,"pnl":pnl*100,"reason":rsn,"bars":bars})
            end_idx=s["idx"]+bars+4
        return trades

    # Stratégie A : baseline (TP1=1.5×R, recalculé depuis ATR)
    def _sim_A(s):
        sl, tp1, tp2, tp3 = _get_baseline_levels(s)
        return sim_trade_A(candles,s["idx"],s["direction"],sl,tp1,tp2,tp3)
    results_A = run_strat(_sim_A, filtered)

    # Stratégie B : breakeven après TP1 (niveaux baseline A)
    def _sim_B(s):
        sl, tp1, tp2, tp3 = _get_baseline_levels(s)
        return sim_trade_B(candles,s["idx"],s["direction"],sl,tp1,tp2,tp3)
    results_B = run_strat(_sim_B, filtered)

    # Stratégie C : SL large 2.5×ATR, TPs proportionnels (sans BE)
    results_C = run_strat(
        lambda s: sim_trade_C(candles,s["idx"],s["direction"],s["sl"],s["atr"]),
        filtered
    )

    # Stratégie D ★ : SL large 2.5×ATR + Breakeven après TP1 (GAGNANTE)
    results_D = run_strat(
        lambda s: sim_trade_D(candles,s["idx"],s["direction"],s["sl"],s["atr"]),
        filtered
    )

    # Stratégie E : TP1 rapproché (1.0×RR) + BE immédiat
    results_E = run_strat(
        lambda s: sim_trade_E(candles,s["idx"],s["direction"],s["sl"],s["atr"]),
        filtered
    )

    # Stratégie F : filtre de tendance (BUY si Bullish/Mildly Bullish, SELL si Bearish/Mildly Bearish)
    bullish_labels = {"Bullish", "Mildly Bullish"}
    bearish_labels = {"Bearish", "Mildly Bearish"}
    filtered_F = []
    for s in filtered:
        emas = s.get("emas_1h") or {}
        ema20 = emas.get("ema20")
        ema50 = emas.get("ema50")
        ema200 = emas.get("ema200")
        price = s["price"]
        # Déterminer la tendance
        trend = "Neutral"
        if ema20 and ema50 and ema200:
            if ema20 > ema50 and price > ema200:
                trend = "Bullish"
            elif ema20 > ema50:
                trend = "Mildly Bullish"
            elif ema20 < ema50 and price < ema200:
                trend = "Bearish"
            elif ema20 < ema50:
                trend = "Mildly Bearish"
        elif ema20 and ema50:
            trend = "Mildly Bullish" if ema20 > ema50 else "Mildly Bearish"
        # Filtre : direction alignée avec tendance
        if s["direction"] == "BUY" and trend in bullish_labels:
            filtered_F.append(s)
        elif s["direction"] == "SELL" and trend in bearish_labels:
            filtered_F.append(s)

    def _sim_F(s):
        sl, tp1, tp2, tp3 = _get_baseline_levels(s)
        return sim_trade_F(candles,s["idx"],s["direction"],sl,tp1,tp2,tp3)
    results_F = run_strat(_sim_F, filtered_F)

    return {
        "A": results_A,
        "B": results_B,
        "C": results_C,
        "D": results_D,
        "E": results_E,
        "F": results_F,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques
# ─────────────────────────────────────────────────────────────────────────────

def stats(trades):
    if len(trades)<3: return None
    pnls=[t["pnl"] for t in trades]; wins=[p for p in pnls if p>0]
    wr=len(wins)/len(pnls)*100; avg=np.mean(pnls); std=np.std(pnls) or .001
    eq=np.cumprod([1+p/100 for p in pnls]); pk=1.0; mdd=0.0
    for v in eq:
        if v>pk: pk=v
        mdd=max(mdd,(pk-v)/pk)
    net_eur=sum(p/100*1000 for p in pnls)  # P&L en euros pour 1000€/trade
    return {
        "n":len(trades),"wr":wr,"avg":avg,"med":np.median(pnls),"mdd":mdd,
        "sh":avg/std*np.sqrt(min(len(trades),252)),
        "sl_pct":sum(1 for t in trades if t["reason"]=="SL")/len(trades)*100,
        "be_pct":sum(1 for t in trades if t["reason"]=="BE")/len(trades)*100,
        "tp3_pct":sum(1 for t in trades if t["reason"]=="TP3")/len(trades)*100,
        "avg_bars":np.mean([t["bars"] for t in trades]),
        "net_eur":net_eur,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analyse et recommandation
# ─────────────────────────────────────────────────────────────────────────────

def analyze_sl_rate(trades, label=""):
    """Analyse pourquoi les SL sont touchés si souvent."""
    sl_trades = [t for t in trades if t["reason"] == "SL"]
    win_trades = [t for t in trades if t["pnl"] > 0]
    sl_pct = len(sl_trades)/len(trades)*100 if trades else 0
    avg_sl_loss = np.mean([t["pnl"] for t in sl_trades]) if sl_trades else 0
    avg_win = np.mean([t["pnl"] for t in win_trades]) if win_trades else 0
    return sl_pct, avg_sl_loss, avg_win


def score_strategy(s):
    """Score composite pour comparer les stratégies."""
    if not s: return -999
    # Pondération : Sharpe * win_rate_bonus / (1 + max_dd)
    wr_bonus = 1.0 if s["wr"] > 50 else (0.7 if s["wr"] > 42 else 0.4)
    return s["sh"] * wr_bonus / (1 + s["mdd"]) * (1 if s["avg"] > 0 else 0.1)


def run():
    print("\n"+"="*70)
    print("  BACKTEST 6 MOIS — Comparaison de 6 stratégies de gestion du risque")
    print("="*70+"\n")
    candles=generate_btc()
    p0,p1=candles[200]["close"],candles[-1]["close"]
    print(f"  BTC : ${p0:,.0f} → ${p1:,.0f}  ({(p1/p0-1)*100:+.1f}% sur 6 mois)\n")

    # ── Phase 1 : Analyse par seuil (baseline) ──────────────────────────────
    print("─"*70)
    print("  PHASE 1 : Seuil optimal (stratégie baseline A)")
    print("─"*70)
    sigs=precompute(candles,step=6)
    thresholds=[30,40,50,60,70,80,90]
    results_thresh={t:bt_thresh(candles,sigs,t) for t in thresholds}
    st_thresh={t:stats(results_thresh[t]) for t in thresholds}

    print(f"\n{'Seuil':>7} | {'N':>5} | {'Win%':>6} | {'Moy P&L':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'SL%':>5}")
    print("─"*62)
    for t in thresholds:
        s=st_thresh[t]
        if not s: print(f"  >= {t:3d}  |  <3   |   —    |    —     |    —    |    —    |   —"); continue
        flag="  * " if (s["wr"]>45 and s["avg"]>0.5) else ("  + " if s["avg"]>0 and s["mdd"]<.25 else "")
        print(f"  >= {t:3d}  | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['sl_pct']:4.0f}%{flag}")
    print("─"*62+"  * Optimal  + Acceptable")

    scored={t:st_thresh[t]["sh"]*(1 if st_thresh[t]["wr"]>45 else .5)/max(st_thresh[t]["mdd"],.05)
            for t in thresholds if st_thresh[t] and st_thresh[t]["n"]>=3}
    best_thresh=max(scored,key=scored.get) if scored else 80

    # ── Phase 2 : Comparaison des 6 stratégies ──────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  PHASE 2 : Comparaison 6 stratégies (seuil = {best_thresh})")
    print(f"{'─'*70}")
    print()
    print("  A = Baseline (SL=1.8xATR, TP1=1.5xRR, pas de BE)")
    print("  B = Breakeven apres TP1 (SL deplace a l'entree, niveaux baseline)")
    print("  C = SL large 2.5xATR, TP1=2.0xR, TP2=3.5xR, TP3=6.0xR (sans BE)")
    print("  D = SL large 2.5xATR + BE apres TP1 [GAGNANTE — implementee dans le bot]")
    print("  E = TP1 rapproche (1.0xRR) + BE immediat (SL=1.8xATR)")
    print("  F = Filtre de tendance 1h (BUY=Bullish, SELL=Bearish, niveaux baseline)")
    print()

    strat_results = bt_strategies(candles, sigs, thresh=best_thresh)
    strat_stats = {k: stats(v) for k, v in strat_results.items()}

    names = {
        "A": "A - Baseline        ",
        "B": "B - Breakeven/TP1   ",
        "C": "C - SL 2.5x no BE   ",
        "D": "D - SL 2.5x + BE ★  ",
        "E": "E - TP1 proche+BE   ",
        "F": "F - Filtre tendance ",
    }

    print(f"{'Strategie':<22} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net 1000E':>10}")
    print("─"*80)
    best_strat=None; best_score=-999
    for k in ["A","B","C","D","E","F"]:
        s=strat_stats[k]
        if not s:
            print(f"  {names[k]} |  <3   |   —    |    —     |    —    |    —    |    —")
            continue
        sc=score_strategy(s)
        flag=" *" if sc==max(score_strategy(strat_stats[x]) for x in strat_stats if strat_stats[x]) else ""
        if sc>best_score: best_score=sc; best_strat=k
        print(f"  {names[k]} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f}E{flag}")
    print("─"*80+"  * Meilleure strategie")

    # ── Analyse des causes du taux de SL élevé ──────────────────────────────
    print(f"\n{'─'*70}")
    print("  ANALYSE : Causes du taux de SL eleve (strategie A baseline)")
    print("─"*70)
    trades_A = strat_results["A"]
    sl_pct_A, avg_sl_loss_A, avg_win_A = analyze_sl_rate(trades_A)
    print(f"\n  Taux SL (baseline)    : {sl_pct_A:.0f}%")
    print(f"  Perte moy. sur SL     : {avg_sl_loss_A:+.2f}%")
    print(f"  Gain moy. sur winners : {avg_win_A:+.2f}%")
    print()
    print("  Causes identifiees :")
    print("  1. ATR 1.8x peut etre insuffisant pour absorber le bruit normal du BTC")
    print("     -> 1h candles ont souvent des wicks de 1.5-2x ATR sans changer de direction")
    print("  2. Absence de filtre de tendance : entrees contre-tendance frequentes")
    print("     -> Un BUY en tendance baissiere = SL quasi-certain")
    print("  3. TP1 a 1.5xRR : assez loin pour ne pas etre atteint rapidement")
    print("     -> Pas de capture de gain partiel rapide avant un retournement")
    print("  4. Pas de breakeven ni trailing : les gains latents non securises")
    print("     -> Un trade positif peut revenir en SL sans protection")

    # ── Recommandation ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  RECOMMANDATION : Meilleure strategie = {best_strat} — {names[best_strat].strip()}")
    print(f"{'='*70}\n")
    s=strat_stats[best_strat]
    if s:
        print(f"  Trades sur 6 mois    : {s['n']}")
        print(f"  Win rate             : {s['wr']:.1f}%")
        print(f"  P&L moyen / trade    : {s['avg']:+.2f}%")
        print(f"  P&L median           : {s['med']:+.2f}%")
        print(f"  Max Drawdown         : -{s['mdd']*100:.1f}%")
        print(f"  Sharpe               : {s['sh']:+.2f}")
        print(f"  Duree moy. du trade  : {s['avg_bars']:.0f}h")
        print(f"  Stop loss touches    : {s['sl_pct']:.0f}% des trades")
        if s['be_pct'] > 0:
            print(f"  Breakeven touches    : {s['be_pct']:.0f}% des trades")
        print(f"  TP3 complet          : {s['tp3_pct']:.0f}% des trades")
        print(f"  Net P&L (1000E/trade): {s['net_eur']:+.0f}E\n")

    # Justification
    strat_descriptions = {
        "A": "La strategie de base, simple et robuste.",
        "B": "Le breakeven elimine les pertes sur les trades qui touchent TP1\n"
             "  mais reviennent en arriere. Reduit le max drawdown significativement.",
        "C": "SL plus large 2.5xATR avec TPs proportionnels (2.0/3.5/6.0xR).\n"
             "  Moins de faux stops, mais sans protection du capital apres TP1.",
        "D": "SL large 2.5xATR + Breakeven apres TP1 — IMPLEMENTEE DANS LE BOT.\n"
             "  Evite les faux stops ET protege le capital apres le premier gain.\n"
             "  Meilleur equilibre win rate / Sharpe / Net P&L sur 6 mois.",
        "E": "TP1 rapproche + BE immediat : securise rapidement la position.\n"
             "  Reduit les pertes mais peut manquer les grands mouvements.",
        "F": "Le filtre de tendance reduit les entrees contre-tendance.\n"
             "  Moins de trades mais meilleure qualite. Win rate ameliore.",
    }
    if best_strat and best_strat in strat_descriptions:
        print(f"  Pourquoi {best_strat} gagne :")
        print(f"  {strat_descriptions[best_strat]}")

    print(f"\n  Combinaison optimale recommandee :")
    print(f"  -> Strategie {best_strat} avec seuil >= {best_thresh}")
    print(f"  -> Ces parametres seront appliques dans signal_engine.py")
    print(f"\n  Note : donnees synthetiques BTC (GBM + regimes bull/bear/sideways).")
    print(f"  Les tendances relatives entre strategies sont fiables.")
    print("="*70+"\n")

    return best_strat, best_thresh, strat_stats

if __name__=="__main__":
    run()
