from __future__ import (absolute_import, division, print_function, unicode_literals)
import pandas as pd
from .reference import *
from . import utils

class Position:
	def __init__(self, side: str, price: float, size: float, created_at: pd.Timestamp, leverage: int, close_price_column: str = "close"):
		self.__side = side
		self.__price = price
		self.__size = size
		self.__created_at = created_at
		self.__leverage = leverage
		self.__close_price_column = close_price_column

	def _increase(self, price: float, size: float):
		self.__price = (self.notional + (price * size)) / (self.__size + size)
		self.__size += size

	def _decrease(self, size: float):
		self.__size -= size

	@property
	def side(self) -> str:
		return self.__side

	@property
	def price(self) -> float:
		return self.__price

	@property
	def size(self) -> float:
		return self.__size

	@property
	def created_at(self) -> pd.Timestamp:
		return self.__created_at

	@property
	def leverage(self) -> int:
		return self.__leverage

	@property
	def notional(self) -> float:
		return self.__price * self.__size

	@property
	def margin(self) -> float:
		return self.notional * (1 / self.__leverage)

	@property
	def liquidation_price(self) -> float:
		return utils.get_liquidation_price(self.__side, self.__price, self.__leverage)

	@property
	def close_price_column(self) -> str:
		return self.__close_price_column

	def get_breakeven_price(self, fee_rate: float) -> float:
		return utils.get_breakeven_price(self.__side, self.__price, self.__size, fee_rate)

	def get_unrealized_pnl(self, price: float) -> float:
		if self.__side == POSITION_SIDE_LONG:
			return (price - self.__price) * self.__size
		elif self.__side == POSITION_SIDE_SHORT:
			return (self.__price - price) * self.__size
		else:
			raise Exception("Unknown position side.")
