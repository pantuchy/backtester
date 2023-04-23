from __future__ import (absolute_import, division, print_function, unicode_literals)
import pandas as pd
from . import store
from . import config
from .reference import *
from .broker import *

class Report(object):
	def __init__(self, strategy: str, broker: Broker, cfg: config.Config, store: store.Store):
		self.__strategy = strategy
		self.__start_datetime = store.data.iloc[0].datetime
		self.__end_datetime = store.data.iloc[-1].datetime
		self.__broker = broker

		self.__trades = pd.DataFrame(
			store.trades,
			columns=["datetime", "side", "quantity", "price", "notional", "fee", "realized_pnl"]
		).round({
			"quantity": cfg.base_precision,
			"price": cfg.price_precision,
			"notional": cfg.quote_precision,
			"fee": cfg.quote_precision,
			"realized_pnl": cfg.quote_precision
		})

		self.__transactions = pd.DataFrame(
			store.transactions,
			columns=["datetime", "type", "amount"]
		).round({"amount": cfg.quote_precision})

	@property
	def strategy(self) -> str:
		return self.__strategy

	@property
	def start_datetime(self) -> pd.Timestamp:
		return self.__start_datetime

	@property
	def end_datetime(self) -> pd.Timestamp:
		return self.__end_datetime

	@property
	def start_cash(self) -> float:
		return self.__broker.start_cash

	@property
	def trades(self) -> pd.DataFrame:
		return self.__trades

	@property
	def transactions(self) -> pd.DataFrame:
		return self.__transactions

	@property
	def returns(self) -> pd.DataFrame:
		start_datetime = self.__start_datetime - pd.DateOffset(days=1)
		data = self.__transactions[["datetime", "amount"]].copy()
		data.loc[-1] = [start_datetime, self.__broker.start_cash]
		data.index = data.index + 1
		data.sort_index(ascending=True, inplace=True)
		data = data.groupby(pd.Grouper(key="datetime", freq="D"), dropna=False).sum(min_count=1)
		data["amount"] = data["amount"].rolling(min_periods=1, window=len(data.index)).sum()
		data["percent"] = data["amount"].pct_change(periods=1)
		return data.iloc[1:, :].reset_index()
