from __future__ import (absolute_import, division, print_function, unicode_literals)
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class CSVData:
	"""
	Args:
		timestamp (int): Column index. Set '-1' if not exist
		datetime (int): Column index. Set '-1' if not exist
		tsformat (str): D, s, ms, us, ns
	"""
	files: list
	timestamp: int
	datetime: int
	open: int
	high: int
	low: int
	close: int
	volume: int
	dtformat: str = "%Y-%m-%d %H:%M:%S"
	tsformat: str = "s"
	separator: str = ","
	header: int = 0
	start_date: pd.Timestamp = None
	end_date: pd.Timestamp = None

	def read(self) -> pd.DataFrame:
		if self.timestamp == -1 and self.datetime == -1:
			raise Exception("Timestamp or datetime column is required.")

		usecols = []

		if self.datetime >= 0:
			usecols.append(self.datetime)
		else:
			usecols.append(self.timestamp)

		usecols = usecols + [self.open, self.high, self.low, self.close, self.volume]
		dfs = (pd.read_csv(f, sep=self.separator, header=self.header, usecols=usecols) for f in self.files)
		df = pd.concat(dfs, ignore_index=False)

		cols = {
			"open": self.open,
			"high": self.high,
			"low": self.low,
			"close": self.close,
			"volume": self.volume
		}

		if self.datetime >= 0:
			cols["datetime"] = self.datetime
		else:
			cols["timestamp"] = self.timestamp

		sorted_cols = sorted(cols.items(), key=lambda x: x[1], reverse=False)
		columns = {}

		for i, col in enumerate(sorted_cols):
			columns[df.columns[i]] = col[0]

		df = df.rename(columns=columns)

		if self.datetime >= 0:
			df["datetime"] = pd.to_datetime(df["datetime"], format=self.dtformat, utc=True)
		else:
			df["datetime"] = pd.to_datetime(df["timestamp"], unit=self.tsformat, utc=True)

		df = df.sort_values("datetime", ascending=True).set_index("datetime")

		if self.start_date is not None:
			df = df[df.index >= pd.to_datetime(self.start_date, utc=True)]

		if self.end_date is not None:
			df = df[df.index <= pd.to_datetime(self.end_date, utc=True)]

		return df
