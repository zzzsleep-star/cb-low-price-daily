#!/usr/bin/env python3
"""Self-contained daily low-price convertible-bond selector using AKShare."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import random
import time
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import requests

RATING = {"AAA": 9, "AA+": 8, "AA": 7, "AA-": 6, "A+": 5,
          "A": 4, "A-": 3, "BBB+": 2, "BBB": 1}


def parse_args():
    p = argparse.ArgumentParser(description="Build local cache and output the daily low-price top ten")
    p.add_argument("--data-dir", type=Path, default=Path.home()/".cb-low-price-daily")
    p.add_argument("--run-date", help="YYYY-MM-DD; defaults to local today")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--refresh-master", action="store_true")
    p.add_argument("--max-bonds", type=int, help="Smoke-test limit; never use for an official list")
    return p.parse_args()


def install_timeout():
    original = requests.sessions.Session.request
    def request(self, *a, **kw):
        kw.setdefault("timeout", 30)
        return original(self, *a, **kw)
    requests.sessions.Session.request = request


def retry(fn, attempts=3):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(i + 1 + random.random())
    raise last


def get_calendar(run_date: pd.Timestamp, state: Path):
    cache = state/"trade_calendar.parquet"
    source = "AKShare.tool_trade_date_hist_sina"
    try:
        raw = retry(ak.tool_trade_date_hist_sina)
        cal = pd.DataFrame({"trade_date": pd.to_datetime(raw["trade_date"], errors="coerce")})
        cal = cal.dropna().drop_duplicates().sort_values("trade_date")
        cal.to_parquet(cache, index=False)
    except Exception as exc:
        if not cache.exists():
            raise RuntimeError(f"Trading calendar unavailable and no cache exists: {exc}") from exc
        cal = pd.read_parquet(cache)
        cal["trade_date"] = pd.to_datetime(cal.trade_date)
        source = f"cached_calendar_after_{type(exc).__name__}"
    prior = cal.loc[cal.trade_date.lt(run_date), "trade_date"]
    if prior.empty:
        raise RuntimeError("No completed exchange trading day before run date")
    return pd.Timestamp(prior.max()).normalize(), cal, source


def current_universe(target: pd.Timestamp):
    spot = retry(ak.bond_zh_hs_cov_spot)
    spot["symbol"] = spot["symbol"].astype(str).str.lower()
    spot = spot[spot.symbol.str.match(r"^(sh|sz)\d{6}$")].copy()
    spot["bond_code"] = spot["symbol"].str[-6:]
    spot["exchange"] = spot.symbol.str[:2].str.upper()
    issue = retry(ak.bond_zh_cov)
    if issue.shape[1] < 19:
        raise RuntimeError(f"Unexpected bond_zh_cov schema: {issue.shape[1]} columns")
    # Positional extraction is intentional: AKShare has duplicate localized column names.
    basic = pd.DataFrame({
        "bond_code": issue.iloc[:, 0].astype(str).str.zfill(6),
        "bond_name_issue": issue.iloc[:, 1],
        "stock_code_issue": issue.iloc[:, 5].astype(str).str.zfill(6),
        "stock_name_issue": issue.iloc[:, 6],
        "listing_date_issue": pd.to_datetime(issue.iloc[:, 17], errors="coerce"),
        "rating_issue": issue.iloc[:, 18].astype("string").str.upper().str.strip(),
    })
    u = spot[["bond_code","exchange","name"]].merge(basic, on="bond_code", how="left")
    u = u[u.listing_date_issue.isna() | u.listing_date_issue.le(target)]
    return u.drop_duplicates("bond_code").sort_values("bond_code").reset_index(drop=True)


def fetch_info(code: str):
    def call():
        d = ak.bond_zh_cov_info(symbol=code, indicator="基本信息")
        if d is None or d.empty:
            raise ValueError("empty basic info")
        r = d.iloc[0]
        return {
            "bond_code": code,
            "bond_name_info": r.get("SECURITY_NAME_ABBR"),
            "stock_code_info": r.get("CONVERT_STOCK_CODE"),
            "stock_name_info": r.get("SECURITY_SHORT_NAME"),
            "listing_date_info": r.get("LISTING_DATE"),
            "maturity_date": r.get("EXPIRE_DATE"),
            "last_trade_date": r.get("CEASE_DATE"),
            "delisting_date": r.get("DELIST_DATE"),
            "rating_info": r.get("RATING"),
            "info_source": "AKShare.bond_zh_cov_info/Eastmoney",
            "info_retrieved_at": dt.datetime.now().astimezone().isoformat(),
        }
    return retry(call)


def build_master(universe: pd.DataFrame, state: Path, workers: int, refresh: bool):
    path = state/"master.parquet"
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if not old.empty:
        old["bond_code"] = old.bond_code.astype(str).str.zfill(6)
        old = old.rename(columns={"bond_name":"bond_name_info","stock_code":"stock_code_info",
                                  "stock_name":"stock_name_info","listing_date":"listing_date_info",
                                  "rating_raw":"rating_info"})
        old = old.drop(columns=["exchange"], errors="ignore")
    known = set(old.bond_code) if not old.empty and not refresh else set()
    need = [c for c in universe.bond_code if c not in known]
    rows=[]; failures=[]
    with cf.ThreadPoolExecutor(max_workers=max(1,min(workers,6))) as pool:
        futures={pool.submit(fetch_info,c):c for c in need}
        for fut in cf.as_completed(futures):
            code=futures[fut]
            try: rows.append(fut.result())
            except Exception as exc: failures.append({"bond_code":code,"stage":"basic_info","error":f"{type(exc).__name__}: {str(exc)[:300]}"})
    fresh=pd.DataFrame(rows)
    if refresh: master=fresh
    else: master=pd.concat([old,fresh],ignore_index=True) if not old.empty else fresh
    master=universe.merge(master,on="bond_code",how="left")
    master["bond_name"]=master.get("bond_name_info").fillna(master.bond_name_issue).fillna(master.name)
    master["stock_code"]=master.get("stock_code_info").fillna(master.stock_code_issue).astype("string").str.zfill(6)
    master["stock_name"]=master.get("stock_name_info").fillna(master.stock_name_issue)
    master["rating_raw"]=master.get("rating_info").fillna(master.rating_issue).astype("string").str.upper().str.strip()
    master["listing_date"]=pd.to_datetime(master.get("listing_date_info").fillna(master.listing_date_issue),errors="coerce")
    for c in ["maturity_date","last_trade_date","delisting_date"]:
        master[c]=pd.to_datetime(master.get(c),errors="coerce")
    keep=["bond_code","exchange","bond_name","stock_code","stock_name","listing_date","maturity_date",
          "last_trade_date","delisting_date","rating_raw","info_source","info_retrieved_at"]
    master=master[keep].drop_duplicates("bond_code")
    master.to_parquet(path,index=False)
    return master,failures


def fetch_history(rec: dict, wanted: pd.DatetimeIndex):
    code=rec["bond_code"]; symbol=rec["exchange"].lower()+code
    def call():
        d=ak.bond_zh_hs_cov_daily(symbol=symbol)
        if d is None or d.empty: raise ValueError("empty daily history")
        d=d.rename(columns={"date":"trade_date","volume":"volume_raw"})
        d["trade_date"]=pd.to_datetime(d.trade_date,errors="coerce")
        return d[d.trade_date.isin(wanted)].copy()
    return retry(call)


def update_history(master: pd.DataFrame, dates: pd.DatetimeIndex, state: Path, workers: int):
    path=state/"daily_history.parquet"
    old=pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if not old.empty:
        old["bond_code"]=old.bond_code.astype(str).str.zfill(6); old["trade_date"]=pd.to_datetime(old.trade_date)
    rows=[]; failures=[]
    with cf.ThreadPoolExecutor(max_workers=max(1,min(workers,6))) as pool:
        futures={pool.submit(fetch_history,r,dates):r for r in master.to_dict("records")}
        for fut in cf.as_completed(futures):
            rec=futures[fut]; code=rec["bond_code"]
            try: d=fut.result()
            except Exception as exc:
                d=pd.DataFrame(); failures.append({"bond_code":code,"stage":"daily_history","error":f"{type(exc).__name__}: {str(exc)[:300]}"})
            if not d.empty:
                for c in ["open","high","low","close","volume_raw"]: d[c]=pd.to_numeric(d[c],errors="coerce")
                d["bond_code"]=code; d["exchange"]=rec["exchange"]
                d["volume_bonds"]=d.volume_raw
                d["amount_for_screening"]=d.close*d.volume_bonds
                d["amount_for_screening_source"]="estimated_close_x_volume_bonds"
                d["data_source"]="AKShare.bond_zh_hs_cov_daily/Sina"
                d["retrieved_at"]=dt.datetime.now().astimezone().isoformat()
                rows.append(d[["bond_code","exchange","trade_date","open","high","low","close","volume_raw",
                               "volume_bonds","amount_for_screening","amount_for_screening_source","data_source","retrieved_at"]])
    new=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=old.columns)
    hist=pd.concat([old,new],ignore_index=True) if not old.empty else new
    hist=hist.sort_values(["bond_code","trade_date"]).drop_duplicates(["bond_code","trade_date"],keep="last")
    hist=hist.groupby("bond_code",group_keys=False).tail(40).reset_index(drop=True)
    hist.to_parquet(path,index=False)
    return hist,failures


def redemption_snapshot():
    try:
        red=retry(ak.bond_cb_redeem_jsl)
        code_col=next(c for c in red.columns if str(c) in {"代码","转债代码","债券代码"})
        status_cols=[c for c in red.columns if "强赎" in str(c) or "状态" in str(c)]
        text=red[status_cols].fillna("").astype(str).agg(lambda r:"|".join(r.tolist()),axis=1) if status_cols else pd.Series("",index=red.index)
        out=pd.DataFrame({"bond_code":red[code_col].astype(str).str.zfill(6),"redemption_status_text":text})
        out["decided_redeem"]=text.str.contains(r"已公告|公告强赎|强赎实施|赎回登记",regex=True,na=False)
        return out,"success"
    except Exception as exc:
        return pd.DataFrame(columns=["bond_code","redemption_status_text","decided_redeem"]),f"failed:{type(exc).__name__}:{str(exc)[:200]}"


def screen(master, hist, dates, target, redemption):
    target_rows=hist[hist.trade_date.eq(target)].copy()
    x=master.merge(target_rows,on=["bond_code","exchange"],how="left")
    sums=[]; complete=[]
    for code in x.bond_code:
        g=hist[(hist.bond_code.eq(code)) & hist.trade_date.isin(dates)]
        ok=len(g)==len(dates) and g.amount_for_screening.notna().all()
        complete.append(ok); sums.append(g.amount_for_screening.sum() if ok else np.nan)
    x["amount_5d"]=sums; x["window_5d_complete"]=complete
    x["days_to_maturity"]=(x.maturity_date-target).dt.days
    x["rating_score"]=x.rating_raw.map(RATING)
    names=x.stock_name.astype("string").str.upper()
    x["stock_risk_status"]=np.where(names.str.match(r"^\*?ST",na=False)|names.str.contains("退",na=False),"risk",
                                     np.where(names.notna(),"normal","unknown"))
    x=x.merge(redemption,on="bond_code",how="left")
    x["decided_redeem"]=x.decided_redeem.fillna(False).astype(bool)
    masks={
      "not_normal_trade":x.open.isna()|x.close.isna()|x.volume_bonds.isna(),
      "stock_risk":x.stock_risk_status.eq("risk"),
      "rating_below_A_plus":x.rating_score.lt(RATING["A+"])|x.rating_score.isna(),
      "maturity_under_90d_or_unknown":x.days_to_maturity.lt(90)|x.days_to_maturity.isna(),
      "amount_5d_under_50m_or_unknown":x.amount_5d.lt(50_000_000)|x.amount_5d.isna(),
      "close_under_90":x.close.lt(90)|x.close.isna(),
      "redeem_decision_effective":x.decided_redeem,
      "after_last_trade_date":x.last_trade_date.notna()&x.last_trade_date.le(target),
    }
    passed=pd.Series(True,index=x.index); counts={"before":len(x)}
    x["exclude_reasons"]=""
    for name,mask in masks.items():
        counts[name]=int((passed&mask).sum()); passed &= ~mask; x.loc[mask,"exclude_reasons"]+=name+";"
    x["pool_pass"]=passed; counts["after"]=int(passed.sum())
    eligible=x[x.pool_pass].sort_values(["close","bond_code"]).copy(); eligible["rank"]=range(1,len(eligible)+1)
    return x,eligible.head(10),counts


def main():
    a=parse_args(); install_timeout(); data=a.data_dir.expanduser().resolve(); state=data/"state"; state.mkdir(parents=True,exist_ok=True)
    run_date=pd.Timestamp(a.run_date or dt.date.today()).normalize()
    target,calendar,calendar_source=get_calendar(run_date,state)
    universe=current_universe(target)
    official=not bool(a.max_bonds)
    if a.max_bonds: universe=universe.head(a.max_bonds)
    master,fail_info=build_master(universe,state,a.workers,a.refresh_master)
    master=master[master.delisting_date.isna()|master.delisting_date.gt(target)].copy()
    last5=pd.DatetimeIndex(calendar.loc[calendar.trade_date.le(target),"trade_date"].tail(5))
    if len(last5)<5: raise RuntimeError("Trading calendar has fewer than five prior sessions")
    hist,fail_daily=update_history(master,last5,state,a.workers)
    redemption,red_status=redemption_snapshot()
    detail,top,counts=screen(master,hist,last5,target,redemption)
    out=data/"runs"/target.strftime("%Y-%m-%d"); out.mkdir(parents=True,exist_ok=True)
    top_cols=["rank","bond_code","bond_name","stock_code","stock_name","close","rating_raw","days_to_maturity",
              "amount_5d","stock_risk_status","redemption_status_text","amount_for_screening_source"]
    top[top_cols].to_csv(out/"low_price_top10.csv",index=False,encoding="utf-8-sig")
    detail.to_csv(out/"screening_detail.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame([counts]).to_csv(out/"screening_summary.csv",index=False,encoding="utf-8-sig")
    failures=pd.DataFrame(fail_info+fail_daily); failures.to_csv(out/"failures.csv",index=False,encoding="utf-8-sig")
    meta={"run_date":str(run_date.date()),"target_trade_date":str(target.date()),"calendar_source":calendar_source,
          "official_full_universe_run":official,"universe_count":len(master),"eligible_count":counts["after"],
          "selected_count":len(top),"redemption_snapshot_status":red_status,"failure_count":len(failures),
          "stock_risk_unknown_count":int(detail.stock_risk_status.eq("unknown").sum()),
          "five_trade_dates":[str(d.date()) for d in last5],"rules":{"min_rating":"A+","min_days_to_maturity":90,
          "min_amount_5d_yuan":50_000_000,"min_close":90,"top_k":10,"sort":"close asc, bond_code asc"},
          "generated_at":dt.datetime.now().astimezone().isoformat()}
    (out/"run_metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(meta,ensure_ascii=False,indent=2)); print(top[top_cols].to_string(index=False)); print(f"OUTPUT_DIR={out}")
    return 0


if __name__=="__main__": raise SystemExit(main())
