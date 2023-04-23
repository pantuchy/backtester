from __future__ import (absolute_import, division, print_function, unicode_literals)
from typing import final
from typing import Union
import math
import datetime as dt
from pandas.api.types import is_datetime64_ns_dtype
from datetime import timezone
from .backtester import *
from .position import *
from .reference import *
from .report import *

class Strategy(Backtester):
	def __init__(self):
		super().__init__()
		self.__data = None

		self.__positions = {
			POSITION_SIDE_LONG: None,
			POSITION_SIDE_SHORT: None
		}

	@final
	def __skip_next(self) -> bool:
		if self.__data is None:
			return True

		return False

	@final
	def __before_next(self):
		if self.__data["datetime"].hour in self.cfg.funding_rate_hours and self.__data["datetime"].minute == 0:
			if self.__positions[POSITION_SIDE_LONG] is not None and self.cfg.leverage > 1:
				fee = self.__positions[POSITION_SIDE_LONG].notional * self.cfg.funding_rate
				self.broker._sub_cash(fee)
				self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_FUNDING_FEE, fee * -1])

			if self.__positions[POSITION_SIDE_SHORT] is not None:
				fee = self.__positions[POSITION_SIDE_SHORT].notional * self.cfg.funding_rate
				self.broker._sub_cash(fee)
				self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_FUNDING_FEE, fee * -1])

	@final
	def __after_next(self):
		if self.__data["datetime"].hour == 0 and self.__data["datetime"].minute == 0:
			amount = self.broker.cash

			if self.__positions[POSITION_SIDE_LONG] is not None:
				pnl = self.__positions[POSITION_SIDE_LONG].get_unrealized_pnl(self.__data[self.__positions[POSITION_SIDE_LONG].close_price_column])
				amount += self.__positions[POSITION_SIDE_LONG].margin + pnl

			if self.__positions[POSITION_SIDE_SHORT] is not None:
				pnl = self.__positions[POSITION_SIDE_SHORT].get_unrealized_pnl(self.__data[self.__positions[POSITION_SIDE_SHORT].close_price_column])
				amount += self.__positions[POSITION_SIDE_SHORT].margin + pnl

			self.store._add_portfolio_history([self.__data["datetime"], amount])

	@property
	def data(self) -> tuple:
		return self.__data

	@property
	def long(self) -> Union[Position, None]:
		return self.__positions[POSITION_SIDE_LONG]

	@property
	def short(self) -> Union[Position, None]:
		return self.__positions[POSITION_SIDE_SHORT]

	@property
	def has_long(self) -> bool:
		return self.__positions[POSITION_SIDE_LONG] is not None

	@property
	def has_short(self) -> bool:
		return self.__positions[POSITION_SIDE_SHORT] is not None

	@final
	def open_long(self, quantity: float, price: float = 0, close_price_column: str = "close"):
		if math.isnan(quantity) or quantity <= 0:
			raise Exception("Quantity must be greater zero")

		entry_price = price if price > 0 else self.__data[close_price_column]
		notional = entry_price * quantity
		fee = notional * self.cfg.fee_rate

		if self.__positions[POSITION_SIDE_LONG] is not None:
			margin = notional * (1 / self.__positions[POSITION_SIDE_LONG].leverage)

			if self.broker.cash < margin + fee:
				raise Exception("Insufficient funds")

			self.__positions[POSITION_SIDE_LONG]._increase(entry_price, quantity)
			self.broker._sub_cash(margin + fee)
		else:
			margin = notional * (1 / self.cfg.leverage)

			if self.broker.cash < margin + fee:
				raise Exception("Insufficient funds")

			self.__positions[POSITION_SIDE_LONG] = Position(
				side=POSITION_SIDE_LONG,
				price=entry_price,
				size=quantity,
				created_at=self.__data["datetime"],
				leverage=self.cfg.leverage,
				close_price_column=close_price_column
			)

			self.broker._sub_cash(margin + fee)

		self.store._add_trade([self.__data["datetime"], ORDER_SIDE_BUY, quantity, entry_price, notional, fee, math.nan])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_COMMISSION, fee * -1])

	@final
	def close_long(self, quantity: float = 0, price: float = 0):
		if self.__positions[POSITION_SIDE_LONG] is None:
			raise Exception(f"No opened {POSITION_SIDE_LONG} positions")

		if quantity < 0:
			raise Exception("Quantity must be greater zero")

		exit_price = price if price > 0 else self.__data[self.__positions[POSITION_SIDE_LONG].close_price_column]
		qty = self.__positions[POSITION_SIDE_LONG].size if quantity == 0 or quantity >= self.__positions[POSITION_SIDE_LONG].size else quantity
		pnl = (exit_price - self.__positions[POSITION_SIDE_LONG].price) * qty
		notional = exit_price * qty
		fee = notional * self.cfg.fee_rate
		margin = (self.__positions[POSITION_SIDE_LONG].price * qty) * (1 / self.__positions[POSITION_SIDE_LONG].leverage)
		self.broker._add_cash(margin + pnl - fee)
		self.__positions[POSITION_SIDE_LONG]._decrease(qty)
		self.store._add_trade([self.__data["datetime"], ORDER_SIDE_SELL, qty, exit_price, notional, fee, pnl])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_REALIZED_PNL, pnl])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_COMMISSION, fee * -1])

		if self.__positions[POSITION_SIDE_LONG].size <= 0:
			self.__positions[POSITION_SIDE_LONG] = None

	@final
	def open_short(self, quantity: float, price: float = 0, close_price_column: str = "close"):
		if math.isnan(quantity) or quantity <= 0:
			raise Exception("Quantity must be greater zero")

		entry_price = price if price > 0 else self.__data[close_price_column]
		notional = entry_price * quantity
		fee = notional * self.cfg.fee_rate

		if self.__positions[POSITION_SIDE_SHORT] is not None:
			margin = notional * (1 / self.__positions[POSITION_SIDE_SHORT].leverage)

			if self.broker.cash < margin + fee:
				raise Exception("Insufficient funds")

			self.__positions[POSITION_SIDE_SHORT]._increase(entry_price, quantity)
			self.broker._sub_cash(margin + fee)
		else:
			margin = notional * (1 / self.cfg.leverage)

			if self.broker.cash < margin + fee:
				raise Exception("Insufficient funds")

			self.__positions[POSITION_SIDE_SHORT] = Position(
				side=POSITION_SIDE_SHORT,
				price=entry_price,
				size=quantity,
				created_at=self.__data["datetime"],
				leverage=self.cfg.leverage,
				close_price_column=close_price_column
			)

			self.broker._sub_cash(margin + fee)

		self.store._add_trade([self.__data["datetime"], ORDER_SIDE_SELL, quantity, entry_price, notional, fee, math.nan])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_COMMISSION, fee * -1])

	@final
	def close_short(self, quantity: float = 0, price: float = 0):
		if self.__positions[POSITION_SIDE_SHORT] is None:
			raise Exception(f"No opened {POSITION_SIDE_SHORT} positions")

		if quantity < 0:
			raise Exception("Quantity must be greater zero")

		exit_price = price if price > 0 else self.__data[self.__positions[POSITION_SIDE_SHORT].close_price_column]
		qty = self.__positions[POSITION_SIDE_SHORT].size if quantity == 0 or quantity >= self.__positions[POSITION_SIDE_SHORT].size else quantity
		pnl = (self.__positions[POSITION_SIDE_SHORT].price - exit_price) * qty
		notional = exit_price * qty
		fee = notional * self.cfg.fee_rate
		margin = (self.__positions[POSITION_SIDE_SHORT].price * qty) * (1 / self.__positions[POSITION_SIDE_SHORT].leverage)
		self.broker._add_cash(margin + pnl - fee)
		self.__positions[POSITION_SIDE_SHORT]._decrease(qty)
		self.store._add_trade([self.__data["datetime"], ORDER_SIDE_BUY, qty, exit_price, notional, fee, pnl])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_REALIZED_PNL, pnl])
		self.store._add_transaction([self.__data["datetime"], TRANSACTION_TYPE_COMMISSION, fee * -1])

		if self.__positions[POSITION_SIDE_SHORT].size <= 0:
			self.__positions[POSITION_SIDE_SHORT] = None

	def next(self):
		pass

	@final
	def run(self) -> Report:
		if self.store.data is None or len(self.store.data) == 0:
			raise Exception("Data feed is empty")

		if self.broker.cash == 0:
			raise Exception("Insufficient funds")

		if not "datetime" in self.store.data.columns or not is_datetime64_ns_dtype(self.store.data["datetime"]):
			raise Exception("Data feed must have column 'datetime' as Pandas Timestamp")

		for row in self.store.data.values:
			self.__data = dict(zip(self.store.data.columns, row))

			if self.__skip_next():
				continue

			self.__before_next()
			self.next()
			self.__after_next()

		return Report(
			strategy=self.__class__.__name__,
			broker=self.broker,
			cfg=self.cfg,
			store=self.store,
		)
