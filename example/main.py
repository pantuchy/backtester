from __future__ import (absolute_import, division, print_function, unicode_literals)
import os
import sys

currentdir = os.path.dirname(os.path.realpath(__file__))
parentdir = os.path.dirname(currentdir)
sys.path.append(parentdir)
sys.dont_write_bytecode = True

from os.path import exists
import backtester as bt
import pandas as pd

def get_number(num: int) -> str:
	return f"0{num}" if num < 10 else f"{num}"

years = [2021, 2022, 2023]
files = []

for y in years:
	for x in range(12):
		file_path = f"/Users/maksimpol/Downloads/Market Data/binance/futures/BTCUSDT/ohlc/1m/{y}-{get_number(x+1)}.csv"

		if exists(file_path):
			files.append(file_path)

dfs = (pd.read_csv(f, sep=",", header=0, usecols=[0,1,2,3,4,5]) for f in files)
df_raw = pd.concat(dfs, ignore_index=False)
df_raw["datetime"] = pd.to_datetime(df_raw["open_time"], unit="ms", utc=True)
df_raw = df_raw.sort_values("datetime", ascending=True).set_index("datetime")
df_raw.drop(["open_time"], axis=1, inplace=True)

delta = pd.Timedelta(900, unit="sec")

df = df_raw.resample(delta).agg({
	"open": "first",
	"high": "max",
	"low": "min",
	"close": "last",
	"volume": "sum"
})

df.dropna(inplace=True)

class BuyAndHold24Hours(bt.Strategy):
	def __init__(self):
		super().__init__()

		self.min_trade_notional = 10
		self.max_balance_risk = 0.1

	def next(self):
		if self.data.datetime.hour == 0:
			notional = self.broker.cash * self.max_balance_risk

			if notional >= self.min_trade_notional:
				qty = notional / self.data.close
				self.open_long(price=self.data.close, quantity=qty)
		elif self.data.datetime.hour == 23:
			if self.has_long:
				self.close_long(price=self.data.close)

strategy = BuyAndHold24Hours()
strategy.set_fee_rate(0.04)
strategy.set_funding_rate(0.01)
strategy.set_base_precision(8)
strategy.set_quote_precision(2)
strategy.set_price_precision(2)
strategy.set_cash(10000)
strategy.set_data(df)

report = strategy.run()
report.plot()
