import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path


class TradeCalendar:

    def __init__(self):
        self.trade_calendar_path = (
            Path(__file__).parent.parent / "data" / "trade_calendar.csv"
        )
        if not self.trade_calendar_path.exists():
            dates = self._get_online_dates()
            dates.to_csv(self.trade_calendar_path, index=False)
        else:
            dates = pd.read_csv(self.trade_calendar_path)
            dates["trade_date"] = pd.to_datetime(dates["trade_date"])
            if (
                len(dates.loc[dates["trade_date"].dt.date >= datetime.now().date()])
                == 0
            ):
                dates = self._get_online_dates()
                dates.to_csv(self.trade_calendar_path, index=False)
        self.trade_dates = dates

    def _get_online_dates(self):
        dates = ak.tool_trade_date_hist_sina()
        dates = dates.loc[dates["trade_date"] >= date(2025, 1, 1)].copy()
        dates = dates.reset_index(drop=True)
        # 确保 trade_date 是 datetime 类型
        dates["trade_date"] = pd.to_datetime(dates["trade_date"])

        # 标注每月第4个星期三
        # dates["is_4th_wed"] = False
        # 按年和月分组
        for (year, month), group in dates.groupby(
            [dates["trade_date"].dt.year, dates["trade_date"].dt.month]
        ):
            target_date = self._get_4th_wed(year, month)
            d = dates.loc[dates["trade_date"].dt.date >= target_date]  # noqa
            target_index = d.index[0]
            dates.loc[target_index, "expired_date"] = 1

        dates = self._add_trade_dates_groups(dates)
        return dates

    def _add_trade_dates_groups(self, trade_dates):
        trade_dates.loc[
            trade_dates["expired_date"] == 1, "next_month_expired_index"
        ] = trade_dates.loc[trade_dates["expired_date"] == 1, "trade_date"].index
        trade_dates.loc[
            trade_dates["expired_date"] == 1, "next_month_expired_index"
        ] = trade_dates.loc[
            trade_dates["expired_date"] == 1, "next_month_expired_index"
        ].shift(
            -1
        )
        trade_dates.loc[trade_dates["expired_date"] == 1, "month_trade_days"] = (
            trade_dates.loc[
                trade_dates["expired_date"] == 1, "next_month_expired_index"
            ]
            - trade_dates.loc[trade_dates["expired_date"] == 1].index
        )
        start = trade_dates.loc[trade_dates["expired_date"] == 1].index[0]
        trade_dates = trade_dates.loc[start:]
        trade_dates["month_trade_days"] = trade_dates["month_trade_days"].ffill()
        trade_dates["month_trade_days"] = trade_dates["month_trade_days"].shift(1)
        trade_dates.reset_index(drop=True, inplace=True)
        changes = (
            trade_dates["month_trade_days"] != trade_dates["month_trade_days"].shift()
        )
        trade_dates["group"] = changes.cumsum()
        trade_dates["day_index_in_month"] = trade_dates.groupby("group").cumcount() + 1
        return trade_dates

    def _get_4th_wed(self, year, month):
        # 确定该月第一天是星期几
        first_day = date(year, month, 1)
        # 计算到第一个星期三需要加多少天
        days_until_first_wed = (
            2 - first_day.weekday() + 7
        ) % 7  # 若第一天是周三，则结果为 0
        first_wed = first_day + timedelta(days=days_until_first_wed)
        # 三周后的第四个星期三
        fourth_wed = first_wed + timedelta(days=21)
        return date(year, month, fourth_wed.day)

    def get_pre_trade_date(self, date):
        return (
            self.trade_dates.loc[
                self.trade_dates["trade_date"].dt.date < date, "trade_date"
            ]
            .max()
            .date()
        )

    def is_trade_date(self, date):
        return date in self.trade_dates["trade_date"].dt.date.tolist()

    def get_day_info(self, date):
        info = self.trade_dates.loc[self.trade_dates["trade_date"].dt.date == date]
        if not info.empty:
            return {
                "is_expired_date": (info.iloc[0]["expired_date"] == 1).item(),
                "trading_days_in_month": info.iloc[0]["month_trade_days"],
                "day_index_in_month": info.iloc[0]["day_index_in_month"],
            }


if __name__ == "__main__":
    trade_calendar = TradeCalendar()
    trade_calendar._get_online_dates()
    print(trade_calendar.trade_dates)
    print(trade_calendar.get_pre_trade_date(datetime.now().date()))
