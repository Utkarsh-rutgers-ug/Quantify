"""Quantitator's separate research ledger. Every fill uses a later observation."""
import json
import re
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, render_template
from research.replay_archive import NY, connection

panel = Blueprint("paper_replay", __name__)
ALIASES = {"A":"Agilent", "AA":"Alcoa", "AAP":"Advance Auto Parts","AAPL":"Apple","GOOGL":"Alphabet|Google",
           "MSFT":"Microsoft","QBTS":"D-Wave","QUBT":"Quantum Computing Inc","S":"SentinelOne","PTC":"PTC Inc"}
STARTING_CASH = 100000
ORDER_BUDGET = 5000
FEE = 0.0005

def ledger(c):
    c.execute("""create table if not exists decision(mode text,ticker text,stamp integer,action text,
        reason text,held integer,cash real,fill text,price real,headline text, primary key(mode,ticker,stamp))""")
    columns = {row[1] for row in c.execute("pragma table_info(decision)")}
    if "order_qty" not in columns:
        c.execute("alter table decision add column order_qty integer not null default 0")
        c.execute("update decision set order_qty=1 where action in ('BUY','SELL')")
    if "fill_qty" not in columns:
        c.execute("alter table decision add column fill_qty integer not null default 0")
        c.execute("update decision set fill_qty=1 where fill is not null")

def relevant(ticker, news):
    pattern = r"\$"+re.escape(ticker)+r"\b"
    if ticker in ALIASES:
        pattern += r"|\b(?:"+ALIASES[ticker]+r")\b"
    return next((title for title in news if re.search(pattern,title,re.I)),None)

def regular(stamp):
    clock=datetime.fromtimestamp(stamp,NY)
    return clock.weekday()<5 and 570<=clock.hour*60+clock.minute<960

def step(c,mode,ticker,stamp,quote_time,price,opening,momentum,headline,fresh,execution_time):
    previous=c.execute("select action,stamp,held,cash,order_qty from decision where mode=? and ticker=? order by stamp desc limit 1",(mode,ticker)).fetchone()
    old,then,held,cash,pending=previous or ("HOLD",0,0,STARTING_CASH,0)
    if stamp<=then: return
    fill=None
    fill_qty = 0
    expiry=7200 if mode=="replay" else 600
    eligible_time = then < execution_time if mode == "live" else then <= execution_time
    if fresh and eligible_time and stamp-then<=expiry and regular(execution_time):
        if old == "BUY":
            unit_cost = opening * (1 + FEE)
            fill_qty = min(pending, int(min(cash, ORDER_BUDGET) / unit_cost))
            if fill_qty:
                held += fill_qty
                cash -= fill_qty * unit_cost
                fill = "BUY"
        elif old == "SELL":
            fill_qty = min(pending, held)
            if fill_qty:
                held -= fill_qty
                cash += fill_qty * opening * (1 - FEE)
                fill = "SELL"
    quantity = 0
    action, reason = "HOLD", "No qualifying news and price signal"
    if not fresh:
        reason = "Missing, stale or outside-session price"
    elif held and momentum is not None and momentum <= -0.005:
        quantity = min(held, max(1, int(ORDER_BUDGET / price)))
        action, reason = "SELL", "Price decline of at least 0.5%"
    elif headline and momentum is not None and momentum >= 0.005:
        quantity = int(min(cash, ORDER_BUDGET) / (price * (1 + FEE)))
        if quantity:
            action, reason = "BUY", "Recent company headline and price rise of at least 0.5%"
        else:
            reason = "Available order budget cannot cover one share"
    c.execute("""insert into decision
        (mode,ticker,stamp,action,reason,held,cash,fill,price,headline,order_qty,fill_qty)
        values(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mode,ticker,stamp,action,reason,held,cash,fill,price,headline,quantity,fill_qty))

def replay():
    with connection() as c:
        ledger(c)
        c.execute("delete from decision where mode='replay'")
        prior={}
        for ticker,start,end,opening,close in c.execute("select ticker,start,end,o,c from bar order by end,ticker"):
            # Only completed bars and previously available headlines inform the decision.
            news=(r[0] for r in c.execute("select title from headline where available between ? and ? order by available desc,url",(end-86400,end)))
            previous=prior.get(ticker)
            move=close/previous-1 if previous else None
            step(c,"replay",ticker,end,end,close,opening,move,relevant(ticker,news),True,start)
            prior[ticker]=close

def live(evidence, stamp):
    with connection() as c:
        ledger(c)
        for q in evidence["quotes"]:
            ticker=q["ticker"]
            time=q.get("market_timestamp")
            observed=int(datetime.fromisoformat(time.replace("Z","+00:00")).timestamp()) if time else 0
            fresh=0<=stamp-observed<=300 and regular(observed) and regular(stamp)
            previous=c.execute("select stamp,price from decision where mode='live' and ticker=? order by stamp desc limit 1",(ticker,)).fetchone()
            price=q.get("price") if fresh else None
            move=price/previous[1]-1 if price and previous and previous[1] and 0<stamp-previous[0]<=600 else None
            titles=[n["title"] for n in evidence["news"] if n.get("published_at") and
                0<=stamp-int(datetime.fromisoformat(n["published_at"].replace("Z","+00:00")).timestamp())<=86400]
            step(c,"live",ticker,stamp,observed,price,price,move,relevant(ticker,titles),fresh,observed)

@panel.get("/quantitator")
def monitor():
    with connection() as c:
        ledger(c)
        c.row_factory=sqlite3.Row
        rows=c.execute("select * from decision where mode='live' and stamp=(select max(stamp) from decision where mode='live') order by ticker").fetchall()
        totals=c.execute("select mode,count(*) as decisions,count(fill) as fills from decision group by mode").fetchall()
        fills=c.execute("select * from decision where fill is not null order by stamp desc limit 30").fetchall()
        coverage=c.execute("select count(*) as n,count(distinct publisher) as publishers from headline").fetchone()
        bars=c.execute("select count(*),count(distinct ticker) from bar").fetchone()
    return render_template("monitor.html",rows=rows,totals=totals,fills=fills,coverage=coverage,bars=bars,
        utc=lambda t:datetime.fromtimestamp(t,timezone.utc).strftime("%b %d %H:%M UTC"))
