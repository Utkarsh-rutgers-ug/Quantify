import sqlite3
import unittest
from datetime import datetime
from paper_replay import ledger, step, relevant

class DecisionTest(unittest.TestCase):
    def test_fill_requires_later_market_observation(self):
        c=sqlite3.connect(":memory:")
        ledger(c)
        stamp=int(datetime.fromisoformat("2026-11-19T15:00:00+00:00").timestamp())
        for t,observed,price,fresh in [(stamp,stamp,100,True),(stamp+300,stamp-1,101,True),
                                       (stamp+600,stamp+600,102,True),(stamp+600,stamp+600,102,True)]:
            step(c,"live","AAPL",t,observed,price,price,.01,"Apple headline",fresh,observed)
        self.assertEqual(c.execute("select action,fill,held from decision order by stamp").fetchall(),
                         [("BUY",None,0),("BUY",None,0),("BUY","BUY",48)])
        self.assertAlmostEqual(c.execute("select min(cash) from decision").fetchone()[0],100000-48*102*1.0005)

    def test_same_day_add_trim_and_exit(self):
        c = sqlite3.connect(":memory:")
        ledger(c)
        start = int(datetime.fromisoformat("2026-11-19T15:00:00+00:00").timestamp())
        for i, move in enumerate([.01, .01, -.01, -.01, 0]):
            t = start + 300*i
            step(c,"live","AAPL",t,t,100,100,move,"Apple headline",True,t)
        self.assertEqual(c.execute("select fill_qty,held from decision order by stamp").fetchall(),
                         [(0,0),(49,49),(49,98),(50,48),(48,0)])
        self.assertAlmostEqual(c.execute("select cash from decision order by stamp desc limit 1").fetchone()[0],
                               100000 - 98*100*.001)

    def test_stale_data_and_unrelated_news(self):
        c=sqlite3.connect(":memory:")
        ledger(c)
        self.assertIsNone(relevant("A",["A busy earnings week"]))
        step(c,"live","AAPL",1000,0,None,None,.03,"Apple earnings",False,0)
        self.assertEqual(c.execute("select action,fill from decision").fetchone(),("HOLD",None))
