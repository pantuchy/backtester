from __future__ import (absolute_import, division, print_function, unicode_literals)
import datetime as dt
import pandas as pd
import numpy as np
import math
from bokeh import events
from bokeh.plotting import figure, show, ColumnDataSource, output_file
from bokeh.io import output_notebook
from bokeh.models import PrintfTickFormatter, NumeralTickFormatter, DatetimeTickFormatter, HoverTool
from bokeh.models import CustomJS, CrosshairTool, Div, Spacer, BasicTicker, ColorBar, LinearColorMapper
from bokeh.palettes import RdYlGn
from bokeh.transform import transform
from bokeh.layouts import row, column
from . import store
from . import config
from .reference import *
from .broker import *

def _is_notebook() -> bool:
	try:
		from IPython import get_ipython

		if "IPKernelApp" not in get_ipython().config:
			return False
	except ImportError:
		return False
	except AttributeError:
		return False

	return True

class Report(object):
	def __init__(self, strategy: str, duration: dt.timedelta, broker: Broker, cfg: config.Config, store: store.Store):
		self.__start_datetime = store.data.iloc[0].datetime
		self.__end_datetime = store.data.iloc[-1].datetime
		self.__strategy = strategy
		self.__duration = duration
		self.__broker = broker
		self.__config = cfg
		self.__store = store

		self.__transactions = pd.DataFrame(
			self.__store.transactions,
			columns=["datetime", "type", "amount"]
		).round({"amount": self.__config.quote_precision})

		self.__trades = pd.DataFrame(
			self.__store.trades,
			columns=["datetime", "side", "quantity", "price", "notional", "fee", "realized_pnl"]
		).round({
			"quantity": self.__config.base_precision,
			"price": self.__config.price_precision,
			"notional": self.__config.quote_precision,
			"fee": self.__config.quote_precision,
			"realized_pnl": self.__config.quote_precision
		})

		txn_data = self.__transactions[["datetime", "amount"]].copy()
		txn_data.loc[-1] = [self.__start_datetime, self.__broker.start_cash]
		txn_data.index = txn_data.index + 1
		txn_data.sort_index(ascending=True, inplace=True)
		txn_data = txn_data.groupby(pd.Grouper(key="datetime", freq="D"), dropna=False).sum(min_count=1)
		txn_data["amount"] = txn_data.amount.rolling(min_periods=1, window=len(txn_data.index)).sum()
		txn_data = txn_data.rename(columns={"amount": "realized"})
		txn_data_uniq = txn_data.drop_duplicates(subset="realized", keep="last")
		real_change = txn_data_uniq.realized.pct_change()
		real_wealth_index = self.__broker.start_cash * (1 + real_change).cumprod()
		draws = pd.DataFrame()
		draws["prev_peaks"] = real_wealth_index.cummax()
		draws = draws.reset_index().groupby("prev_peaks")["datetime"].agg(["min", "max"])
		draws["duration"] = draws["max"].sub(draws["min"])
		draws = draws[draws["duration"] > pd.Timedelta(days=0)]
		self.__drawdowns = draws.rename(columns={"min": "from_date", "max": "to_date"}).reset_index()

		#Benchmark Returns
		bench = self.__store.data.set_index("datetime").resample("D").agg({
			"open": "first",
			"high": "max",
			"low": "min",
			"close": "last",
			"volume": "sum"
		})

		bench["avg_price"] = bench[["open", "high", "low", "close"]].sum(axis=1) / 4
		bench["avg_price"].replace(0, np.nan, inplace=True)
		bench["daily_return"] = bench["avg_price"] / bench["avg_price"].shift(1)
		bench["balance"] = self.__broker.start_cash * bench["daily_return"].cumprod()
		self.__bench_return = bench.iloc[-1].balance - self.__broker.start_cash
		bench = bench.round({"balance": self.__config.quote_precision}).rename(columns={"balance": "benchmark"})

		#Portfolio History
		pf = pd.DataFrame(
			self.__store.portfolio_history,
			columns=["datetime", "unrealized"]
		).set_index("datetime").fillna(method="ffill").round({"unrealized": self.__config.quote_precision})

		pf = pd.concat([pf, txn_data], ignore_index=False, axis=1).fillna(method="ffill")
		real_change = txn_data.realized.pct_change()
		real_wealth_index = self.__broker.start_cash * (1 + real_change).cumprod()
		draws = pd.DataFrame()
		draws["prev_peaks"] = real_wealth_index.cummax()
		pf["realized_drawdown"] = ((real_wealth_index - draws["prev_peaks"]) / draws["prev_peaks"]) * 100
		pf = pd.concat([pf, bench[["benchmark"]]], ignore_index=False, axis=1)
		daily_return = pf.pct_change(periods=1).realized
		self.__sharpe_ratio = (len(pf)**0.5) * (daily_return.mean() / daily_return.std()) if daily_return.mean() > 0 and daily_return.mean() > 0 else 0
		self.__portfolio_history = pf.reset_index()
		self.__daily_return = daily_return.mean()
		self.__weekly_return = pf.pct_change(periods=7).realized.mean()
		self.__monthly_return = pf.pct_change(periods=30).realized.mean()
		self.__annual_return = pf.pct_change(periods=365).realized.mean()
		self.__max_drawdown_idx = pf.realized_drawdown.idxmin()
		fee_types = [TRANSACTION_TYPE_COMMISSION, TRANSACTION_TYPE_FUNDING_FEE]
		self.__total_fees = self.__transactions.loc[self.__transactions["type"].isin(fee_types)]["amount"].sum()
		self.__cumm_return = self.__portfolio_history.iloc[-1].realized - self.__broker.start_cash
		self.__win_ratio, self.__loss_ratio = self.__get_win_loss_ratio()
		self.__max_drawdown = 0
		self.__max_drawdown_pct = 0

		if pd.notna(self.__max_drawdown_idx):
			self.__max_drawdown = self.__broker.start_cash - pf.loc[self.__max_drawdown_idx].realized

			md = self.__drawdowns[
				(self.__max_drawdown_idx > self.__drawdowns["from_date"]) &
				(self.__max_drawdown_idx < self.__drawdowns["to_date"])
			]

			if len(md.index) > 0:
				self.__max_drawdown = pf.loc[self.__max_drawdown_idx].realized - md.prev_peaks.iloc[0]

		if not math.isnan(self.__portfolio_history.realized_drawdown.min()):
			self.__max_drawdown_pct = self.__portfolio_history.realized_drawdown.min()

		self.__long_ratio, self.__short_ratio = self.__get_long_short_ratio()

		# Monthly Returns
		start_datetime = self.__start_datetime - pd.DateOffset(months=1)
		mr = self.__transactions[["datetime", "amount"]].copy()
		mr.loc[-1] = [start_datetime, self.__broker.start_cash]
		mr.index = mr.index + 1
		mr.sort_index(ascending=True, inplace=True)
		mr = mr.groupby(pd.Grouper(key="datetime", freq="M"), dropna=False).sum(min_count=1)
		mr["amount"] = mr.amount.rolling(min_periods=1, window=len(mr.index)).sum()
		mr["pct_diff"] = mr.amount.pct_change() * 100
		mr = mr.iloc[1:, :].reset_index()
		mr["month"] = mr.datetime.dt.strftime("%b")
		mr["year"] = mr.datetime.dt.year
		self.__monthly_returns = mr

		# Annual Returns
		ar = self.__transactions[["datetime", "amount"]].copy()
		ar.loc[-1] = [start_datetime, self.__broker.start_cash]
		ar.index = ar.index + 1
		ar.sort_index(ascending=True, inplace=True)
		ar = ar.groupby(pd.Grouper(key="datetime", freq="Y"), dropna=False).sum(min_count=1)
		ar["amount"] = ar.amount.rolling(min_periods=1, window=len(ar.index)).sum()
		ar["pct_diff"] = ar.amount.pct_change() * 100
		ar = ar.iloc[1:, :].reset_index()
		ar["year"] = ar.datetime.dt.year
		self.__annual_returns = ar

		#Trades Qty
		if len(self.__trades.index) > 0:
			self.__tqty_data = self.__trades[["datetime", "side"]].copy().groupby(pd.Grouper(key="datetime", freq="D"), dropna=False).count()
			self.__tqty_data["weekly_trades_qty"] = self.__tqty_data["side"].rolling(min_periods=0, window=7).sum()
			self.__tqty_data["monthly_trades_qty"] = self.__tqty_data["side"].rolling(min_periods=0, window=30).sum()
			self.__tqty_data["annual_trades_qty"] = self.__tqty_data["side"].rolling(min_periods=0, window=365).sum()

		#Trades Interval
		tid = self.__trades[["datetime", "realized_pnl"]].copy()
		tid = tid.loc[tid["realized_pnl"].isna()]
		tid = tid.reset_index(drop=True)
		tid["datetime_delta"] = tid["datetime"].diff()
		self.__tintval_data = tid

		#Trade Duration
		tdd = self.__trades[["datetime", "realized_pnl"]].copy()
		tdd["datetime_delta"] = tdd["datetime"].diff()
		tdd = tdd.loc[tdd["realized_pnl"].notna()]
		tdd = tdd.reset_index(drop=True)
		self.__tdur_data = tdd

	def __get_win_loss_ratio(self) -> tuple[float, float]:
		pnls = self.__transactions.loc[self.__transactions["type"] == TRANSACTION_TYPE_REALIZED_PNL]
		win_qty = len(pnls.loc[pnls["amount"] > 0].index)
		loss_qty = len(pnls.loc[pnls["amount"] < 0].index)
		win_ratio = 0
		loss_ratio = 0

		if len(pnls.index) > 0:
			win_ratio = win_qty / len(pnls.index) * 100
			loss_ratio = loss_qty / len(pnls.index) * 100

		return win_ratio, loss_ratio

	def __get_long_short_ratio(self) -> tuple[float, float]:
		positions = self.__trades.loc[self.__trades["realized_pnl"].isna()]
		long_qty = len(positions.loc[positions["side"] == ORDER_SIDE_BUY].index)
		short_qty = len(positions.loc[positions["side"] == ORDER_SIDE_SELL].index)
		long_ratio = 0
		short_ratio = 0

		if len(positions.index) > 0:
			long_ratio = long_qty / len(positions.index) * 100
			short_ratio = short_qty / len(positions.index) * 100

		return long_ratio, short_ratio

	def plot(self, to_file: bool = False):
		if to_file or not _is_notebook():
			output_file(filename="report.html", title="Report")
		else:
			output_notebook()

		layout_columns = []
		tools = "xpan, xwheel_zoom, reset, save"
		cross = CrosshairTool()
		cross.line_color = "black"
		cross.line_alpha = 0.5

		hover = HoverTool(
			tooltips=[
				("Date", "@datetime{%Y-%m-%d}"),
				("Unrealized", "@unrealized{%0.2f}"),
				("Realized", "@realized{%0.2f}"),
				("Benchmark", "@benchmark{%0.2f}"),
				("Drawdown", "@realized_drawdown{%0.2f}%")
			],
			formatters={
				"@datetime": "datetime",
				"@unrealized": "printf",
				"@realized": "printf",
				"@benchmark": "printf",
				"@realized_drawdown": "printf"
			},
			mode="vline",
			show_arrow=False,
			line_policy="none"
		)

		if len(self.__portfolio_history.index > 0):
			source = ColumnDataSource(data=self.__portfolio_history)

			ph = figure(
				width=1000,
				height=480,
				tools=tools,
				title=f"Portfolio History",
				x_axis_label="Date",
				y_axis_label=f"Portfolio Value",
				x_axis_type="datetime",
				active_drag="xpan",
				active_scroll="xwheel_zoom",
				toolbar_location="right",
				sizing_mode="scale_width"
			)

			ph.add_tools(hover)
			ph.add_tools(cross)

			ph.line("datetime", "unrealized", source=source, legend_label="Unrealized", line_width=2, line_color="silver"),
			ph.line("datetime", "realized", source=source, legend_label="Realized", line_width=2, line_color="forestgreen"),
			ph.line("datetime", "benchmark", source=source, legend_label="Benchmark", line_width=2, line_color="red")

			ph.legend.location = "top_left"
			ph.legend.click_policy = "hide"
			ph.y_range.only_visible = True
			ph.xaxis[0].formatter = DatetimeTickFormatter(years="%Y", months="%Y-%m", days="%Y-%m-%d", hours="%Y-%m-%d %H:%M", minutes="%Y-%m-%d %H:%M")
			ph.yaxis[0].formatter = NumeralTickFormatter(format="0.00")
			layout_columns.append(ph)

			dr = figure(
				width=1000,
				height=200,
				tools=tools,
				title="Drawdown History (%)",
				x_axis_label="Date",
				y_axis_label="Drawdown",
				x_axis_type="datetime",
				active_drag="xpan",
				active_scroll="xwheel_zoom",
				toolbar_location="right",
				x_range=ph.x_range,
				sizing_mode="scale_width"
			)

			dr.add_tools(hover)
			dr.add_tools(cross)
			dr.varea(x="datetime", y1=0, y2="realized_drawdown", source=source, level="underlay", fill_alpha=0.2, fill_color="tomato")
			dr.line("datetime", "realized_drawdown", source=source, legend_label="Percent", line_width=2, line_color="tomato")
			dr.legend.visible = False
			dr.xaxis[0].formatter = DatetimeTickFormatter(years="%Y", months="%Y-%m", days="%Y-%m-%d", hours="%Y-%m-%d %H:%M", minutes="%Y-%m-%d %H:%M")
			dr.yaxis[0].formatter = PrintfTickFormatter(format="%0.2f %%")
			layout_columns.append(dr)

		stats_template = """
			<style type="text/css" scoped>
				.stats table {{
					border-spacing: 10px;
					width: 100%;
				}}
				.stats table td {{
					text-align: right;
				}}
				.stats table td:first-child {{
					text-align: left;
					font-weight: bold;
				}}
			</style>

			<div class="stats">
				<table class="stats-table">
					<tr>
						<td>Strategy</td>
						<td>{strategy}</td>
					</tr>
					<tr>
						<td>Start Datetime</td>
						<td>{start_datetime}</td>
					</tr>
					<tr>
						<td>End Datetime</td>
						<td>{end_datetime}</td>
					</tr>
					<tr>
						<td>Initial Portfolio</td>
						<td>{initial_portfolio:.2f}</td>
					</tr>
					<tr>
						<td>Ending Portfolio</td>
						<td>{ending_portfolio:.2f}</td>
					</tr>
					<tr>
						<td>Max. Portfolio</td>
						<td>{max_portfolio:.2f}</td>
					</tr>
					<tr>
						<td>Min. Portfolio</td>
						<td>{min_portfolio:.2f}</td>
					</tr>
					<tr>
						<td>Max. Drawdown</td>
						<td>{max_drawdown:.2f} ({max_drawdown_pct:.2f}%)</td>
					</tr>
					<tr>
						<td>Drawdown Duration (avg)</td>
						<td>{avg_drawdown_dur}</td>
					</tr>
					<tr>
						<td>Drawdown Duration (max)</td>
						<td>{max_drawdown_dur}</td>
					</tr>
					<tr>
						<td>Cumulative Return</td>
						<td>{cumm_return:.2f} ({cumm_return_pct:.2f}%)</td>
					</tr>
					<tr>
						<td>Daily Return (avg)</td>
						<td>{daily_return:.2f}%</td>
					</tr>
					<tr>
						<td>Weekly Return (avg)</td>
						<td>{weekly_return:.2f}%</td>
					</tr>
					<tr>
						<td>Monthly Return (avg)</td>
						<td>{monthly_return:.2f}%</td>
					</tr>
					<tr>
						<td>Annual Return (avg)</td>
						<td>{annual_return:.2f}%</td>
					</tr>
					<tr>
						<td>Benchmark Return</td>
						<td>{bench_return:.2f} ({bench_return_pct:.2f}%)</td>
					</tr>
					<tr>
						<td>Sharpe Ratio</td>
						<td>{sharpe_ratio:.2f}</td>
					</tr>
					<tr>
						<td>Win / Loss Ratio</td>
						<td>{win_ratio:.1f}% / {loss_ratio:.1f}%</td>
					</tr>
					<tr>
						<td>Long / Short Ratio</td>
						<td>{long_ratio:.1f}% / {short_ratio:.1f}%</td>
					</tr>
					<tr>
						<td>Total Trades Qty</td>
						<td>{trades_qty:.0f}</td>
					</tr>
					<tr>
						<td>Daily Trades Qty (avg)</td>
						<td>{daily_trades_qty:.1f}</td>
					</tr>
					<tr>
						<td>Weekly Trades Qty (avg)</td>
						<td>{weekly_trades_qty:.1f}</td>
					</tr>
					<tr>
						<td>Monthly Trades Qty (avg)</td>
						<td>{monthly_trades_qty:.1f}</td>
					</tr>
					<tr>
						<td>Annual Trades Qty (avg)</td>
						<td>{annual_trades_qty:.1f}</td>
					</tr>
					<tr>
						<td>Trades Interval (avg)</td>
						<td>{avg_trades_interval}</td>
					</tr>
					<tr>
						<td>Trades Interval (max)</td>
						<td>{max_trades_interval}</td>
					</tr>
					<tr>
						<td>Trade Duration (avg)</td>
						<td>{avg_trade_duration}</td>
					</tr>
					<tr>
						<td>Trade Duration (max)</td>
						<td>{max_trade_duration}</td>
					</tr>
					<tr>
						<td>Total Fees</td>
						<td>{fees:.2f}</td>
					</tr>
					<tr>
						<td>Turnover</td>
						<td>{turnover:.2f}</td>
					</tr>
					<tr>
						<td>Backtest Duration</td>
						<td>{backtest_duration}</td>
					</tr>
				</table>
			</div>
		"""

		stats = Div(
			text=stats_template.format(
				strategy=self.__strategy,
				start_datetime=self.__start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
				end_datetime=self.__end_datetime.strftime('%Y-%m-%d %H:%M:%S'),
				initial_portfolio=self.__broker.start_cash,
				ending_portfolio=self.__portfolio_history.iloc[-1].realized,
				max_portfolio=self.__portfolio_history.realized.max(),
				min_portfolio=self.__portfolio_history.realized.min(),
				max_drawdown=self.__max_drawdown,
				max_drawdown_pct=self.__max_drawdown_pct,
				avg_drawdown_dur=str(self.__drawdowns.duration.mean()).split(".")[0],
				max_drawdown_dur=str(self.__drawdowns.duration.max()).split(".")[0],
				cumm_return=self.__cumm_return,
				cumm_return_pct=(self.__cumm_return / self.__broker.start_cash) * 100,
				daily_return=self.__daily_return * 100,
				weekly_return=self.__weekly_return * 100,
				monthly_return=self.__monthly_return * 100,
				annual_return=self.__annual_return * 100,
				bench_return=self.__bench_return,
				bench_return_pct=(self.__bench_return / self.__broker.start_cash) * 100,
		      sharpe_ratio=self.__sharpe_ratio,
				win_ratio=self.__win_ratio,
				loss_ratio=self.__loss_ratio,
				long_ratio=self.__long_ratio,
				short_ratio=self.__short_ratio,
				trades_qty=len(self.__trades.index) / 2 if len(self.__trades.index) > 0 else 0,
				daily_trades_qty=self.__tqty_data["side"].mean() / 2 if len(self.__trades.index) > 0 else 0,
				weekly_trades_qty=self.__tqty_data["weekly_trades_qty"].mean() / 2 if len(self.__trades.index) > 0 else 0,
				monthly_trades_qty=self.__tqty_data["monthly_trades_qty"].mean() / 2 if len(self.__trades.index) > 0 else 0,
				annual_trades_qty=self.__tqty_data["annual_trades_qty"].mean() / 2 if len(self.__trades.index) > 0 else 0,
				avg_trades_interval=str(self.__tintval_data["datetime_delta"].mean()).split(".")[0],
				max_trades_interval=str(self.__tintval_data["datetime_delta"].max()).split(".")[0],
				avg_trade_duration=str(self.__tdur_data["datetime_delta"].mean()).split(".")[0],
				max_trade_duration=str(self.__tdur_data["datetime_delta"].max()).split(".")[0],
				fees=abs(self.__total_fees),
				turnover=self.__trades["notional"].sum() if len(self.__trades.index) > 0 else 0,
				backtest_duration=self.__duration
			),
			width=400,
			height=500,
			sizing_mode="stretch_height"
		)

		# Monthly Returns
		if len(self.__monthly_returns.index) > 0:
			month_columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
			index = self.__monthly_returns.year.drop_duplicates(keep="last").sort_values().values

			mr = pd.DataFrame(
				columns=month_columns,
				index=index
			)

			for r in self.__monthly_returns.itertuples():
				mr.loc[r.year, r.month] = r.pct_diff

			mr.index.name = "year"
			mr.columns.name = "month"
			mr_data = mr.stack().rename("value").reset_index()
			mr_data["year"] = mr_data["year"].apply(str)
			high = mr_data.value.max()
			low = mr_data.value.min()

			if high > low:
				if high > 100:
					low = -100
				else:
					low = high * -1

			mapper = LinearColorMapper(
				palette=RdYlGn[11][::-1],
				high=high,
				low=low,
				nan_color="grey"
			)

			mrp = figure(
				title="Monthly Returns (%)",
				width=1000,
				height=150,
				tools="save",
				toolbar_location=None,
				x_range=month_columns,
				y_range=list(mr_data.year.drop_duplicates().sort_values(ascending=False)),
				sizing_mode="scale_width"
			)

			hover = HoverTool(
				tooltips=[
					("Period", "@month @year"),
					("Return", "@value{%0.2f}%")
				],
				formatters={
					"@year": "printf",
					"@month": "printf",
					"@value": "printf"
				}
			)

			mrp.add_tools(hover)

			mrp.rect(
				x="month",
				y="year",
				width=1,
				height=1,
				source=ColumnDataSource(mr_data),
				line_color="gainsboro",
				fill_color=transform("value", mapper)
			)

			color_bar = ColorBar(color_mapper=mapper, location=(0, 0), ticker=BasicTicker(desired_num_ticks=len(RdYlGn[11])))
			mrp.add_layout(color_bar, "right")
			layout_columns.append(mrp)

		# Annual Returns
		if len(self.__annual_returns.index) > 0:
			years = [str(y) for y in self.__annual_returns.year.drop_duplicates(keep="last").values]
			source = ColumnDataSource(data=dict(year=years, value=self.__annual_returns.pct_diff.values))

			arp = figure(
				x_range=years,
				width=1000,
				height=150,
				toolbar_location=None,
				title="Annual Returns (%)",
				sizing_mode="scale_width"
			)

			hover = HoverTool(
				tooltips=[
					("Year", "@year"),
					("Return", "@value{%0.2f}%")
				],
				formatters={
					"@year": "printf",
					"@value": "printf"
				}
			)

			arp.add_tools(hover)

			arp.vbar(
				x="year",
				top="value",
				width=0.4,
				source=source,
				line_color="white",
				fill_color="steelblue"
			)

			arp.yaxis[0].formatter = PrintfTickFormatter(format="%0.2f %%")
			arp.xgrid.grid_line_color = None
			arp.y_range.start = self.__annual_returns.pct_diff.min() * 1.1 if self.__annual_returns.pct_diff.min() < 0 else 0
			arp.y_range.end = self.__annual_returns.pct_diff.max() * 1.1 if self.__annual_returns.pct_diff.max() > 0 else 0
			layout_columns.append(arp)

		# col1 = column([ph, dr, mrp, arp], sizing_mode="scale_width")
		col1 = column(layout_columns, sizing_mode="scale_width")
		col2 = column([stats], sizing_mode="stretch_height")
		space = Spacer(width=25, sizing_mode="stretch_height")
		row1 = row([col1, space, col2], sizing_mode="scale_width")
		layout = column([row1], sizing_mode="scale_width")
		show(layout)

	@property
	def transactions(self) -> pd.DataFrame:
		return self.__transactions

	@property
	def trades(self) -> pd.DataFrame:
		return self.__trades

	@property
	def drawdowns(self) -> pd.DataFrame:
		return self.__drawdowns
