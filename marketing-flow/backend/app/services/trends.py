# backend/app/services/trends.py
import os, time, random
from typing import Dict, List
from pytrends.request import TrendReq
from pytrends import exceptions as pt_exc
import logging
# ---------- Tuning knobs (env-overridable) ----------
MFA_TRENDS_TTL = int(os.getenv("MFA_TRENDS_TTL", "600"))        # cache 10 min
MFA_TRENDS_MAX_RETRIES = int(os.getenv("MFA_TRENDS_MAX_RETRIES", "3"))
MFA_TRENDS_BACKOFF_BASE = float(os.getenv("MFA_TRENDS_BACKOFF_BASE", "2.0"))
MFA_TRENDS_ENABLED = os.getenv("MFA_TRENDS_OFF", "0") != "1"    # set MFA_TRENDS_OFF=1 to disable

# Simple in-process cache: {(keyword_lower, geo): {"ts": time.time(), "data": {...}}}
_cache: Dict = {}

def _ok_cached(key) -> bool:
    item = _cache.get(key)
    return bool(item and (time.time() - item["ts"] < MFA_TRENDS_TTL))

def _save_cache(key, data):
    _cache[key] = {"ts": time.time(), "data": data}

def _empty(suffix_note: str = ""):
    data = {"interest_last_12m": [], "top_queries": [], "rising_queries": []}
    if suffix_note:
        data["_note"] = suffix_note
    return data

def keyword_snapshot(keyword: str, geo: str = "VN") -> Dict:
    """
    Returns:
      {
        "interest_last_12m": [{"date":"YYYY-MM-DD", "<kw>": int}, ...],
        "top_queries": [{"query": str, "value": int}, ...],
        "rising_queries": [{"query": str, "value": int}, ...],
        "_note": "optional info"
      }
    Never raises; returns empty structure on errors/rate limits.
    """
    kw = (keyword or "").strip()
    if not kw or not MFA_TRENDS_ENABLED:
        return _empty("trends_disabled")

    key = (kw.lower(), geo or "")
    if _ok_cached(key):
        return _cache[key]["data"]

    # Configure pytrends with retries/backoff at HTTP level as well
    pytrends = TrendReq(
    hl="vi-VN",
    tz=420,                         # GMT+7
    timeout=(10, 30),
    requests_args={"headers": {"User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}}
    )


    attempts = 0
    while True:
        try:
            attempts += 1
            pytrends.build_payload([kw], cat=0, timeframe="today 12-m", geo=geo, gprop="")
            df = pytrends.interest_over_time()

            # Convert interest_over_time to list of {date, <kw>: value}
            interest: List[Dict] = []
            if df is not None and not df.empty:
                # some builds include 'isPartial' column
                if "isPartial" in df.columns:
                    df = df.drop(columns=["isPartial"])
                for idx, row in df.iterrows():
                    try:
                        val = int(row[kw])
                    except Exception:
                        try:
                            # sometimes the column is kw.lower()
                            val = int(row.get(kw.lower(), 0))
                        except Exception:
                            val = 0
                    interest.append({"date": idx.strftime("%Y-%m-%d"), kw: val})

            # Related queries (best-effort; may be None)
            rqs = pytrends.related_queries()
            top, rising = [], []
            bucket = rqs.get(kw) if isinstance(rqs, dict) else None
            if bucket and bucket.get("top") is not None:
                for _, r in bucket["top"].iterrows():
                    top.append({"query": str(r["query"]), "value": int(r["value"])})
            if bucket and bucket.get("rising") is not None:
                for _, r in bucket["rising"].iterrows():
                    rising.append({"query": str(r["query"]), "value": int(r["value"])})

            data = {"interest_last_12m": interest, "top_queries": top, "rising_queries": rising}
            _save_cache(key, data)
            return data

        except pt_exc.TooManyRequestsError:
            if attempts >= MFA_TRENDS_MAX_RETRIES:
                data = _empty("trends_rate_limited")
                _save_cache(key, data)
                return data
            # exponential backoff with jitter
            sleep_s = min(60, (MFA_TRENDS_BACKOFF_BASE ** attempts) + random.uniform(0, 1.0))
            time.sleep(sleep_s)

        except Exception as e:
            # Any other error → graceful empty with error note
            data = _empty(f"trends_error: {e}")
            _save_cache(key, data)
            return data
