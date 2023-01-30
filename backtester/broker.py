from __future__ import (absolute_import, division, print_function, unicode_literals)

class Broker:
	def __init__(self, start_cash: float = 0):
		self.__start_cash = start_cash
		self.__cash = start_cash

	def _add_cash(self, amount: float):
		self.__cash += amount

	def _sub_cash(self, amount: float):
		self.__cash -= amount

	@property
	def start_cash(self) -> float:
		return self.__start_cash

	@property
	def cash(self) -> float:
		return self.__cash
