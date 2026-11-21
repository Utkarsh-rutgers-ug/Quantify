"""Build local Quantitator archive. Store UTC seconds and explicit availability."""
import argparse
import concurrent.futures
import json
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "instance" / "quantitator.sqlite"
NY = ZoneInfo("America/New_York")
START = date(2026, 9, 1)
QUERIES = ["stocks OR earnings OR acquisition", "economy OR inflation OR Federal Reserve",
           "markets OR commodities OR geopolitics", "Apple OR Microsoft OR Alphabet OR quantum computing"]

def connection():
    c = sqlite3.connect(DB, timeout=30)
    c.executescript("""
    create table if not exists headline(url text primary key,title text,publisher text,published integer,available integer,clock text);
    create index if not exists headline_time on headline(available);
    create table if not exists bar(ticker text,start integer,end integer,o real,h real,l real,c real,v integer,primary key(ticker,start));
    create table if not exists retrieval(task text primary key, records integer, error text);
    """)
    return c

def epoch(day):
    return int(datetime.combine(day, datetime.min.time(),NY).timestamp())

def fetch(url):
    return subprocess.check_output(["curl","-fsSL","--retry","2","--max-time","25","-A","Mozilla/5.0",url],stderr=subprocess.DEVNULL)

def archive(job):
    kind, key, arg, cutoff = job
    if kind == "news":
        day, query = arg
        url = "https://news.google.com/rss/search?" + urlencode(dict(q=f"({query}) after:{day} before:{day+timedelta(days=1)}",hl="en-US",gl="US",ceid="US:en"))
        rows = []
        for item in ET.fromstring(fetch(url)).findall("./channel/item"):
            title, link = item.findtext("title"), item.findtext("link")
            published = int(parsedate_to_datetime(item.findtext("pubDate")).timestamp())
            localday = datetime.fromtimestamp(published,NY).date()
            if title and link and epoch(START)<=published<=cutoff:
                rows.append((link,title,item.findtext("source"),published,epoch(localday+timedelta(days=1)),"archive assumed next NY midnight"))
        return "headline", rows
    start = epoch(START)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{arg}?" + urlencode(dict(interval="1h",period1=start,period2=cutoff))
    r=json.loads(fetch(url))["chart"]["result"][0]
    if r["meta"]["symbol"]!=arg: raise ValueError("Symbol mismatch")
    q=r["indicators"]["quote"][0]
    rows=[]
    for i,t in enumerate(r.get("timestamp",[])):
        prices=[q[k][i] for k in ("open","high","low","close")]
        local=datetime.fromtimestamp(t,NY)
        # Conservatively wait a full hour for each provider bar, even at early closes.
        if local.minute!=30 or not 9<=local.hour<=15 or any(v is None or v<=0 for v in prices) or t+3600>cutoff: continue
        rows.append((arg,t,t+3600,*prices,q["volume"][i]))
    return "bar",rows

def build(end):
    cutoff=min(epoch(end+timedelta(days=1))-1,int(time.time()))
    c=connection()
    local=sqlite3.connect((ROOT/"instance/trading.db").as_uri()+"?mode=ro",uri=True)
    tickers=sorted({r[0] for r in local.execute("select ticker from watched_tickers")}|{"SPY","PTC"})
    for url,title,publisher,pub,received in local.execute("select url,title,source_name,published_at,retrieved_at from news_articles where retrieved_at is not null"):
        parse=lambda stamp:int(datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp())
        if epoch(START)<=parse(received)<=cutoff:
            c.execute("insert or replace into headline values(?,?,?,?,?,?)",(url,title,publisher,parse(pub) if pub else None,parse(received),"recorded receipt"))
    jobs=[("bars",f"bars:{t}:{cutoff}",t,cutoff) for t in tickers]
    for i in range((end-START).days+1):
        day=START+timedelta(days=i)
        jobs.extend(("news",f"{day}:{q}",(day,q),cutoff) for q in QUERIES)
    c.commit()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(archive,j):j[1] for j in jobs}
        for f in concurrent.futures.as_completed(tasks):
            key=tasks[f]
            try:
                table,rows=f.result()
                c.executemany("insert or ignore into headline values(?,?,?,?,?,?)" if table=="headline" else "insert or replace into bar values(?,?,?,?,?,?,?,?)",rows)
                c.execute("insert or replace into retrieval values(?,?,null)",(key,len(rows)))
            except Exception as exc:
                c.execute("insert or replace into retrieval values(?,0,?)",(key,type(exc).__name__))
            c.commit()
    print("headlines, publishers:",c.execute("select count(*),count(distinct publisher) from headline").fetchone(),"bars:",c.execute("select count(*) from bar").fetchone(),"failed:",c.execute("select count(*) from retrieval where error is not null").fetchone())
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--through",type=date.fromisoformat,default=datetime.now(NY).date())
    build(parser.parse_args().through)
