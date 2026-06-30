# Trading Simulation — Key Definitions & Examples

> All examples use **live data from our portfolio as of June 30, 2026**.
> Portfolio start: $100,000 | Current value: ~$100,334

---

## 1. RSI — Relative Strength Index

**What it is:**
A momentum indicator that measures how fast a stock has been moving up or down over the last 14 trading days. It outputs a number between **0 and 100**.

**The scale:**
| RSI Value | Meaning | What we do |
|-----------|---------|------------|
| Below 30  | **Oversold** — stock fell too fast, likely to bounce | ✅ **BUY signal** |
| 30 – 50   | Weak / recovering | HOLD — watch |
| 50 – 70   | Healthy uptrend | HOLD |
| Above 70  | **Overbought** — stock rose too fast, likely to drop | ⚠️ Consider selling |

**How it is calculated (simplified):**
The formula compares average gains vs. average losses over 14 days.
```
RSI = 100 − (100 / (1 + avg_gain / avg_loss))
```
We use **Wilder smoothing** — each new day's gain/loss is blended with the previous 13 days,
so recent moves have more weight.

**Our portfolio — live RSI right now (June 30):**
```
ORCL  →  RSI 29.35  ← BELOW 30: this is why we auto-bought it today
CRM   →  RSI 41.09  ← recovering but not oversold yet
ADBE  →  RSI 40.08  ← similar to CRM
MSFT  →  RSI 38.98  ← approaching oversold zone
NOW   →  RSI 48.86  ← neutral / healthy
INTU  →  RSI 36.54  ← watch closely — approaching 30
SPY   →  RSI 52.22  ← broad market healthy, no signal
```

**Real example from our sim:**
ORCL dropped to RSI 29.35 → the auto-engine triggered a buy at $147.76 on June 30.
The bet: when a quality stock is this oversold, it tends to bounce.

---

## 2. MACD — Moving Average Convergence Divergence

**What it is:**
MACD tracks the *momentum trend* — not just whether the stock is going up or down,
but whether that move is **accelerating or decelerating**. It uses three numbers:

| Component | Meaning |
|-----------|---------|
| **MACD Line** | Difference between 12-day EMA and 26-day EMA |
| **Signal Line** | 9-day EMA smoothing of the MACD line |
| **Histogram** | MACD Line − Signal Line (the most important number) |

**Why the histogram matters:**
- **Histogram > 0** → MACD line is above signal line → momentum is **accelerating upward**
- **Histogram < 0** → MACD line is below signal line → momentum is **decelerating / falling**
- **Histogram crossing zero from below** → strongest buy signal (trend reversing up)

**Our portfolio — live MACD right now:**
```
ORCL  →  MACD line: -11.83 | Signal: -5.36  | Histogram: -6.47  ← still falling
CRM   →  MACD line:  -7.29 | Signal: -6.38  | Histogram: -0.91  ← barely negative, almost flat
ADBE  →  MACD line: -12.99 | Signal: -12.06 | Histogram: -0.93  ← similar to CRM
MSFT  →  MACD line: -13.71 | Signal: -10.52 | Histogram: -3.19  ← falling harder
NOW   →  MACD line:  -2.46 | Signal: -1.31  | Histogram: -1.15  ← negative but mild
INTU  →  MACD line: -23.31 | Signal: -25.16 | Histogram: +1.85  ← POSITIVE! momentum turning
SPY   →  MACD line:  +0.57 | Signal: +2.46  | Histogram: -1.89  ← negative, market weakening
```

**Key observation:** INTU has a **positive histogram (+1.85)** even though its MACD line is
still very negative. This means the selling momentum is *slowing down* — the stock is
preparing to turn around. This is what we call a **double-confirm signal** (see below).

---

## 3. EMA — Exponential Moving Average

**What it is:**
An average of past prices that gives **more weight to recent prices**.
Used internally to calculate MACD.

```
EMA = (Today's price × weight) + (Yesterday's EMA × (1 − weight))
where weight = 2 / (period + 1)
```

**In our system:**
- EMA(12) = 12-day EMA of closing prices → fast-moving average
- EMA(26) = 26-day EMA of closing prices → slow-moving average
- **MACD Line = EMA(12) − EMA(26)**

When the fast average (12) crosses above the slow average (26), trend is turning bullish.

---

## 4. Signal Types — How We Decide to Buy

We use **two tiers** of buy signal, with different funding sources:

### RSI-Only (Single Confirm)
```
Condition: RSI < 30
Action:    Buy with CASH only (up to $15,000)
Example:   ORCL on June 30 — RSI 29.35, MACD hist -6.47 → cash buy at $147.76
```

### Double-Confirm (High Conviction)
```
Condition: RSI < 30  AND  MACD histogram > 0
Action:    Buy with MARGIN (up to $25,000 borrowed money)
Example:   INTU at RSI 29 + MACD hist +1.85 would trigger this
           (INTU is currently RSI 36.54 — watch for it to drop below 30)
```

**Why require both signals for margin?**
RSI alone tells you a stock is oversold. MACD histogram positive tells you
the selling momentum is already reversing. Together = much higher probability of bounce.
Using borrowed money (margin) only on high-confidence signals limits risk.

---

## 5. Leverage

**What it is:**
A multiplier that lets you control more money than you actually have.

```
Buying power = Equity × Leverage
```

**Our leverage levels and when they apply:**

| Leverage | Buying Power | Condition |
|----------|-------------|-----------|
| **1.0×** | $100,000 | All positions MACD negative + RSI < 40 → protect capital |
| **1.25×** | $125,000 | All MACD negative but RSI recovering |
| **1.5×** | $150,000 | 1+ positions MACD turning positive |
| **2.0×** | $200,000 | Majority MACD positive + RSI > 50 |

**Current state (June 30):** Leverage = **1.0×**
All 5 positions have negative MACD histograms → the engine chose capital preservation mode.

**Real-world analogy:**
1.5× leverage is like putting $100k down on a house and borrowing $50k more to buy a second one.
If prices rise, you profit on both. If they fall, you still owe the borrowed $50k.

---

## 6. Stop-Loss

**What it is:**
A pre-set price level where we **automatically sell** to limit losses.
Prevents a bad position from destroying the whole portfolio.

**Our rule:** Stop-loss = entry price × (1 − stop%) = entry × 0.92 (8% below entry)

**Current stop-losses:**
```
CRM  →  Entry $158.37 | Stop $145.70 | Current $157.93 | Distance: 7.7%
ADBE →  Entry $202.73 | Stop $186.51 | Current $206.43 | Distance: 9.6%
MSFT →  Entry $372.97 | Stop $343.13 | Current $368.57 | Distance: 6.9%  ← closest to danger
NOW  →  Entry  $98.34 | Stop  $90.47 | Current  $99.97 | Distance: 9.5%
ORCL →  Entry $147.76 | Stop $135.94 | Current $147.76 | Distance: 8.0%
```

**Warning zone:** When a position is within **4% of its stop**, the system sends an alert.
MSFT at 6.9% away is the highest-risk position right now.

**Adaptive stop-loss:** The learning engine will widen the stop from 8% to 8.5%
if more than 40% of our closed trades were stop-loss exits (meaning stops are too tight).

---

## 7. Analyst Target

**What it is:**
The average price target set by Wall Street analysts who cover the stock.
Represents where professionals think the stock should be worth in ~12 months.

**Our positions and their analyst targets:**
```
CRM  →  Current $157.93 | Target $249.95 | Upside: +58%
ADBE →  Current $206.43 | Target $282.27 | Upside: +37%
MSFT →  Current $368.57 | Target $561.11 | Upside: +52%
NOW  →  Current  $99.97 | Target $141.48 | Upside: +41%
ORCL →  Current $147.76 | Target $252.64 | Upside: +71%
```

**How we use it:**
1. **As a take-profit trigger** — when a stock approaches its analyst target, RSI > 70 → sell
2. **As an AVOID filter** — if a stock is already AT or ABOVE its target, we don't buy it
   (e.g., AMD, PANW, FTNT are all above or near their targets → on our AVOID list)
3. **As a fallback target** — when no analyst data is available, we use entry × 1.40 (+40%)

---

## 8. Market Regime (SPY RSI)

**What it is:**
A classification of the overall stock market health, based on SPY's RSI.
SPY = S&P 500 ETF — tracks 500 biggest US companies.

| SPY RSI | Regime | What it means for us |
|---------|--------|----------------------|
| < 40 | **Bear** | Broad market falling — be cautious, reduce position sizes |
| 40 – 60 | **Neutral** | Normal market — standard rules apply |
| > 60 | **Bull** | Market rising strongly — can be more aggressive |

**Current (June 30):** SPY RSI = **52.22 → Neutral**

**Why we track it:**
All our individual tech stocks are RSI 29–49 while SPY is 52.
This means our stocks are more beaten-down than the market.
That's actually a **mean-reversion opportunity** — they should recover faster when sentiment turns.

The learning engine records the SPY regime at the time of every buy,
so over time we learn: "do RSI<30 entries work better in bear markets or neutral markets?"

---

## 9. Win Rate & Learning Stats

**Win rate:**
```
Win rate = Closed trades with positive P&L / Total closed trades
```

**Our adaptive thresholds (current defaults, will self-adjust):**
```
RSI buy threshold:  < 30   (tightens to 29/28 if win rate < 40%)
Stop-loss:          8.0%   (widens to 8.5% if >40% of exits are stops)
Cash per position:  $15,000 (grows to $17k if win rate > 70% on 10+ trades)
Margin per position:$25,000 (grows to $28k alongside cash)
```

**Confidence levels:**
- 🔴 **LOW** — fewer than 5 closed trades. Learning but not adapting yet.
- 🟡 **MEDIUM** — 5–14 closed trades. Thresholds start adjusting.
- 🟢 **HIGH** — 15+ closed trades. Statistically reliable. Full adaptation active.

**Current:** 0 closed trades → LOW confidence. System is building baseline.

---

## 10. P&L — Profit and Loss

**Unrealized P&L** (position still open):
```
Unrealized P&L = (Current price − Entry price) × Shares
Example: ADBE  →  ($206.43 − $202.73) × 108 shares = +$399.60
```

**Realized P&L** (position sold):
```
Realized P&L = (Sell price − Entry price) × Shares
Example: If ORCL sells at $161.50:
         ($161.50 − $147.76) × 69 = +$948.06
```

**Portfolio P&L:**
```
Total P&L = Portfolio value − Starting capital
           = $100,334 − $100,000 = +$334 (+0.33%)
```

---

## Quick Reference Card

```
RSI < 30          → Oversold → BUY (cash)
RSI < 30 + MACD hist > 0  → Double-confirm → BUY (margin)
RSI > 70          → Overbought → Consider SELL
Price ≤ Stop-loss  → AUTO-SELL immediately
Price near Target  → Review for take-profit

Leverage 1.0x → Defensive (all MACD negative, RSI weak)
Leverage 1.5x → Moderate  (some MACD positive)
Leverage 2.0x → Aggressive (majority MACD positive, RSI > 50)

SPY RSI < 40 → Bear market → reduce aggression
SPY RSI > 60 → Bull market → increase aggression
```

---

*Document generated June 30, 2026. Examples use live portfolio data.*
*Updated automatically by the simulation — check sim_ledger.json for current thresholds.*
