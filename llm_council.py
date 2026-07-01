#!/usr/bin/env python3
"""
llm_council.py — Multi-LLM trading decision council (free-tier first)

All judges receive identical market data → return BUY/SELL/HOLD.
All judges run in parallel threads. Weighted majority vote decides.
After each trade closes, outcome is logged → accuracy scores update automatically.

FREE judges (no cost, just sign up):
  rules      : deterministic rule engine — always active, no key needed
  groq_70b   : Llama 3.3 70B via Groq   — console.groq.com     (6000 req/day free)
  groq_8b    : Llama 3.1 8B  via Groq   — same key, ultra fast  (30 req/min free)
  cerebras   : Llama 3.1 70B via Cerebras — cloud.cerebras.ai   (generous free tier)
  gemini     : Gemini 2.0 Flash — aistudio.google.com           (1500 req/day free)
  openrouter : Llama/Mistral/Gemma free models — openrouter.ai  (truly free models)
  mistral    : Mistral 7B — console.mistral.ai                   (free experimental)

PAID judges (add only if you want):
  haiku      : Claude Haiku 4.5  — console.anthropic.com
  gpt4mini   : GPT-4o-mini       — platform.openai.com

Keys go in .sim_config — see bottom of this file or .sim_config for format.
"""

from __future__ import annotations
import json, os, threading, warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────

_CFG_PATH   = Path(__file__).parent / ".sim_config"
_LOG_PATH   = Path(__file__).parent / "llm_council_log.jsonl"
_SCORE_PATH = Path(__file__).parent / "llm_scores.json"

JUDGE_TIMEOUT  = 15     # seconds (all judges run in parallel, so wall-time = slowest)
ROLLING_WINDOW = 30     # trades window for accuracy weight


# ── Config reader ─────────────────────────────────────────────────────────────

def _get_key(section: str, key: str) -> str:
    """Read from .sim_config, ignoring comment lines."""
    try:
        in_section = False
        for line in _CFG_PATH.read_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if s.lower() == f"[{section.lower()}]":
                in_section = True
                continue
            if in_section and s.startswith("["):
                break
            if in_section and key.lower() in s.lower() and "=" in s:
                val = s.split("=", 1)[1].strip()
                # reject placeholder values
                if val and "your-key" not in val and "..." not in val:
                    return val
    except Exception:
        pass
    return ""


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(sym, price, rsi, macd_h, gap_pct, news,
                  in_pos, pnl_pct, target_pct, stop_pct) -> str:
    pos_line = f"Held — P&L {pnl_pct:+.2f}%" if in_pos else "No position"
    task     = "SELL decision" if in_pos else "ENTRY decision"
    return f"""Intraday day trading sim. Fast-cycle: target +{target_pct:.1f}%, stop -{stop_pct:.1f}%.
Goal: 6-8 round trips/day in volatile tech. Capital preservation first.

{sym} | ${price:.2f} | RSI {rsi:.1f} | MACD_hist {macd_h:+.4f} | gap {gap_pct:+.1f}%
News: {news or 'none'} | {pos_line} | Task: {task}

Entry rules: BUY if (RSI 38-58 AND MACD_h>0) OR (RSI<35 AND MACD_h>0). Never buy RSI>70.
Exit rules : SELL if P&L>+{target_pct}% OR P&L<-{stop_pct}% OR RSI>75 OR MACD flips negative with profit.

Reply with ONE LINE only:
DECISION - brief reason
(DECISION = BUY, SELL, or HOLD — nothing else)"""


def _parse(text: str, fallback: str = "HOLD") -> tuple[str, str]:
    text = text.strip()
    # handle "**BUY**" or "BUY:" formats from some models
    for token in ("BUY", "SELL", "HOLD"):
        if text.upper().startswith(token):
            parts = text[len(token):].lstrip(" -:").strip()
            return token, parts[:80] or token
    return fallback, text[:80]


# ── Judges ────────────────────────────────────────────────────────────────────

def _judge_rules(sym, price, rsi, macd_h, gap_pct, news,
                 in_pos, pnl_pct, target_pct, stop_pct) -> tuple[str, str, str]:
    if in_pos:
        if pnl_pct >= target_pct:   return "SELL", f"target +{target_pct}% hit", "rules"
        if pnl_pct <= -stop_pct:    return "SELL", f"stop -{stop_pct}% hit",     "rules"
        if pnl_pct > 0.3 and macd_h < 0:
                                    return "SELL", "protect gain: MACD flipped",  "rules"
        if rsi > 75:                return "SELL", f"RSI overbought {rsi:.0f}",   "rules"
        return "HOLD", "within bounds", "rules"
    if rsi > 70:    return "HOLD", f"RSI overbought {rsi:.0f}", "rules"
    if 38 <= rsi <= 58 and macd_h > 0:
                    return "BUY",  "momentum: RSI mid + MACD+",    "rules"
    if rsi < 35 and macd_h > 0:
                    return "BUY",  "reversal: RSI oversold + MACD+", "rules"
    return "HOLD", "no signal", "rules"


def _judge_groq(api_key: str, model: str, name: str,
                prompt: str) -> tuple[str, str, str]:
    try:
        from groq import Groq
        r = Groq(api_key=api_key).chat.completions.create(
            model=model, max_tokens=80, temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        dec, reason = _parse(r.choices[0].message.content)
        return dec, reason, name
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", name


def _judge_gemini(api_key: str, prompt: str) -> tuple[str, str, str]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        r = genai.GenerativeModel(
            "gemini-2.0-flash-exp",
            generation_config={"temperature": 0.1, "max_output_tokens": 80},
        ).generate_content(prompt)
        dec, reason = _parse(r.text)
        return dec, reason, "gemini"
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", "gemini"


def _judge_cerebras(api_key: str, prompt: str) -> tuple[str, str, str]:
    try:
        from cerebras.cloud.sdk import Cerebras
        r = Cerebras(api_key=api_key).chat.completions.create(
            model="llama3.1-70b",
            max_tokens=80, temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        dec, reason = _parse(r.choices[0].message.content)
        return dec, reason, "cerebras"
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", "cerebras"


def _judge_openrouter(api_key: str, prompt: str) -> tuple[str, str, str]:
    """Uses OpenRouter's free-tier models (Llama 3.1 8B free)."""
    try:
        import urllib.request, json as _json
        body = _json.dumps({
            "model": "meta-llama/llama-3.1-8b-instruct:free",
            "max_tokens": 80,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/sim-trader",
                "X-Title": "sim-trader",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = _json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        dec, reason = _parse(text)
        return dec, reason, "openrouter"
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", "openrouter"


def _judge_mistral(api_key: str, prompt: str) -> tuple[str, str, str]:
    try:
        from mistralai import Mistral
        r = Mistral(api_key=api_key).chat.complete(
            model="open-mistral-7b",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        dec, reason = _parse(r.choices[0].message.content)
        return dec, reason, "mistral"
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", "mistral"


def _judge_claude(api_key: str, model: str, name: str,
                  prompt: str) -> tuple[str, str, str]:
    try:
        import anthropic
        r = anthropic.Anthropic(api_key=api_key).messages.create(
            model=model, max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        dec, reason = _parse(r.content[0].text)
        return dec, reason, name
    except Exception as e:
        tag = "auth" if "401" in str(e) else "err"
        return "HOLD", f"{tag}({str(e)[:20]})", name


def _judge_openai(api_key: str, prompt: str) -> tuple[str, str, str]:
    try:
        from openai import OpenAI
        r = OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini", max_tokens=80, temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        dec, reason = _parse(r.choices[0].message.content)
        return dec, reason, "gpt4mini"
    except Exception as e:
        return "HOLD", f"err({str(e)[:25]})", "gpt4mini"


# ── Score tracker ─────────────────────────────────────────────────────────────

def load_scores() -> dict:
    if _SCORE_PATH.exists():
        try:
            return json.loads(_SCORE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_scores(scores: dict) -> None:
    _SCORE_PATH.write_text(json.dumps(scores, indent=2))


def _weight(judge: str, scores: dict) -> float:
    rec = scores.get(judge, {})
    total   = rec.get("total_rolling", 0)
    correct = rec.get("correct_rolling", 0)
    if total < 5:
        return 1.0                      # equal weight until enough data
    acc = correct / total
    return max(0.2, acc * 2)            # 0.2 – 2.0 range


def record_decision(trade_id, sym, judge_votes, decision, reason) -> None:
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "trade_id": trade_id, "sym": sym,
        "votes": judge_votes,
        "council_decision": decision, "council_reason": reason,
        "outcome": None, "profitable": None,
    }
    with open(_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def record_outcome(trade_id: str, pnl: float, judge_votes: dict) -> None:
    profitable = pnl > 0
    lines = []
    if _LOG_PATH.exists():
        for line in _LOG_PATH.read_text().splitlines():
            try:
                obj = json.loads(line)
                if obj.get("trade_id") == trade_id and obj.get("outcome") is None:
                    obj["outcome"] = round(pnl, 2)
                    obj["profitable"] = profitable
                    line = json.dumps(obj)
            except Exception:
                pass
            lines.append(line)
        _LOG_PATH.write_text("\n".join(lines) + "\n")

    scores = load_scores()
    for judge, vote in judge_votes.items():
        rec = scores.setdefault(judge, {
            "correct_rolling": 0, "total_rolling": 0,
            "correct_all": 0, "total_all": 0, "pnl_when_correct": 0.0,
        })
        was_right = (vote == "BUY" and profitable) or (vote != "BUY" and not profitable)
        rec["total_rolling"]   = min(rec["total_rolling"]   + 1, ROLLING_WINDOW)
        rec["correct_rolling"] = min(rec["correct_rolling"] + int(was_right), rec["total_rolling"])
        rec["total_all"]      += 1
        rec["correct_all"]    += int(was_right)
        if was_right:
            rec["pnl_when_correct"] = round(rec.get("pnl_when_correct", 0) + pnl, 2)
    save_scores(scores)


# ── Council main ──────────────────────────────────────────────────────────────

def council_decide(
    sym: str, price: float, rsi: float, macd_h: float,
    gap_pct: float = 0.0, news: str = "",
    in_pos: bool = False, pnl_pct: float = 0.0,
    target_pct: float = 1.0, stop_pct: float = 0.5,
    trade_id: str = "",
) -> tuple[str, str, dict]:
    """
    Run all available judges in parallel.
    Returns (decision, reason, votes_dict).
    """
    prompt = _build_prompt(sym, price, rsi, macd_h, gap_pct, news,
                           in_pos, pnl_pct, target_pct, stop_pct)

    groq_key      = _get_key("groq",      "groq_api_key")
    google_key    = _get_key("google",    "google_api_key")
    cerebras_key  = _get_key("cerebras",  "cerebras_api_key")
    openrouter_key= _get_key("openrouter","openrouter_api_key")
    mistral_key   = _get_key("mistral",   "mistral_api_key")
    anthropic_key = _get_key("anthropic", "anthropic_api_key")
    openai_key    = _get_key("openai",    "openai_api_key")

    # Build task list — rules always first
    tasks: list[tuple] = [
        ("rules", _judge_rules,
         (sym, price, rsi, macd_h, gap_pct, news, in_pos, pnl_pct, target_pct, stop_pct)),
    ]

    # Free tier judges
    if groq_key:
        tasks.append(("groq_70b",  _judge_groq,
                      (groq_key, "llama-3.3-70b-versatile", "groq_70b", prompt)))
        tasks.append(("groq_8b",   _judge_groq,
                      (groq_key, "llama-3.1-8b-instant",    "groq_8b",  prompt)))
    if google_key:
        tasks.append(("gemini",    _judge_gemini,    (google_key, prompt)))
    if cerebras_key:
        tasks.append(("cerebras",  _judge_cerebras,  (cerebras_key, prompt)))
    if openrouter_key:
        tasks.append(("openrouter",_judge_openrouter,(openrouter_key, prompt)))
    if mistral_key:
        tasks.append(("mistral",   _judge_mistral,   (mistral_key, prompt)))

    # Paid judges (only if key present)
    if anthropic_key:
        tasks.append(("haiku",  _judge_claude,
                      (anthropic_key, "claude-haiku-4-5-20251001", "haiku", prompt)))
    if openai_key:
        tasks.append(("gpt4mini", _judge_openai, (openai_key, prompt)))

    # Run all in parallel
    results: dict[str, tuple[str, str, str]] = {}
    lock = threading.Lock()

    def run(name, fn, args):
        try:
            res = fn(*args)
        except Exception as e:
            res = ("HOLD", f"crash:{str(e)[:30]}", name)
        with lock:
            results[name] = res

    threads = [threading.Thread(target=run, args=(n, fn, a), daemon=True)
               for n, fn, a in tasks]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=JUDGE_TIMEOUT)

    # Weighted majority vote
    scores = load_scores()
    tally: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    votes_dict: dict[str, str] = {}
    reasons: dict[str, str]    = {}

    for name, (dec, reason, _) in results.items():
        w = _weight(name, scores)
        tally[dec]    += w
        votes_dict[name] = dec
        reasons[name]    = reason

    winner = max(tally, key=tally.get)

    vote_str = " | ".join(f"{n}:{v}" for n, v in sorted(votes_dict.items()))
    winning_judge = next((n for n, v in votes_dict.items() if v == winner), "")
    primary_reason = reasons.get(winning_judge, winner)
    council_reason = f"{primary_reason}  [{vote_str}]"

    if trade_id:
        record_decision(trade_id, sym, votes_dict, winner, council_reason)

    return winner, council_reason, votes_dict


# ── Scoreboard ────────────────────────────────────────────────────────────────

def scoreboard() -> str:
    scores = load_scores()
    if not scores:
        return "No council data yet — scores build up after first trades."
    lines = ["LLM Council — Judge Accuracy (rolling {ROLLING_WINDOW} trades):"]
    lines.append(f"  {'Judge':<12} {'Acc':>6}  {'Trades':>7}  {'P&L correct':>12}")
    for judge, rec in sorted(
        scores.items(),
        key=lambda x: x[1].get("correct_rolling", 0) / max(x[1].get("total_rolling", 1), 1),
        reverse=True,
    ):
        total   = rec.get("total_rolling", 0)
        correct = rec.get("correct_rolling", 0)
        acc     = correct / total if total else 0
        pnl     = rec.get("pnl_when_correct", 0)
        lines.append(f"  {judge:<12} {acc:>5.0%}   {total:>7}   ${pnl:>+10.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing council with NVDA (RSI=44, MACD+, no position)...")
    dec, reason, votes = council_decide(
        sym="NVDA", price=132.00, rsi=44.0, macd_h=0.15,
        gap_pct=1.2, news="NVDA AI demand surge reported",
        in_pos=False, pnl_pct=0.0,
    )
    print(f"\nDecision : {dec}")
    print(f"Reason   : {reason}")
    print(f"Votes    : {votes}")
    print(f"\n{scoreboard()}")
