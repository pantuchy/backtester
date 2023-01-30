from __future__ import (absolute_import, division, print_function, unicode_literals)
import pandas as pd
from .reference import *

class Store:
	def __init__(self):
		self.__data = None
		self.__portfolio_history = []
		self.__transaction_history = []
		self.__trade_history = []

	@property
	def data(self) -> pd.DataFrame:
		return self.__data

	@data.setter
	def data(self, data: pd.DataFrame):
		self.__data = data

	@property
	def transactions(self) -> list:
		return self.__transaction_history

	def _add_transaction(self, row: list):
		self.__transaction_history.append(row)

	@property
	def trades(self) -> list:
		return self.__trade_history

	def _add_trade(self, row: list):
		self.__trade_history.append(row)

	@property
	def portfolio_history(self) -> list:
		return self.__portfolio_history

	def _add_portfolio_history(self, row: list):
		self.__portfolio_history.append(row)
