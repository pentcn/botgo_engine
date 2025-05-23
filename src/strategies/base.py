import threading
import pandas as pd
import time
from abc import ABC, abstractmethod
from datetime import datetime
from queue import Queue
from utils.logger import log
from utils.common import DataFrameWrapper, record2dataframe
from utils.trade_calendar import TradeCalendar


class BaseStrategy(ABC):
    def __init__(self, strategy_id, name, params, datafeed):
        self.strategy_id = strategy_id
        self.name = name
        self.datafeed = datafeed
        self._running = False
        self._thread = None
        self._deal_thread = None  # 新增交易信息处理线程
        self._error_count = 10
        self._max_retries = 3  # 最大重试次数
        self._retry_delay = 5  # 重试延迟（秒）
        self._queue = Queue()  # K线的队列
        self._deal_queue = Queue()  # 交易信息的队列
        self.period = params.get("period", None)
        self.symbol = params.get("symbol", None)
        self.min_bars_count = params.get("min_bars_count", 300)
        self.bars = DataFrameWrapper(
            pd.DataFrame(
                columns=[
                    "datetime",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]  # noqa
            )
        )
        # self.bars = DataFrameWrapper(self._bars)

        if self.period is None or self.symbol is None:
            raise ValueError(
                f"错误: {self.strategy_id} - {self.name} 的 period 和 symbol 是必填参数"
            )

        self.datafeed.subscribe(self.symbol, self.period, self._on_data_arrived)  # noqa
        self.strategy_account = None
        self.strategy_positions = None
        self.strategy_combinations = None

    def start(self):
        """启动策略线程"""
        if self._running:
            return

        self._running = True
        # 启动主策略线程
        self._thread = threading.Thread(target=self._run_with_error_handling)
        self._thread.daemon = True

        # 启动交易信息处理线程
        self._deal_thread = threading.Thread(target=self._run_deal_processor)
        self._deal_thread.daemon = True

        self._thread.start()
        self._deal_thread.start()

    def stop(self):
        """停止策略线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._deal_thread and self._deal_thread.is_alive():
            self._deal_thread.join(timeout=5)
        # log(f"策略 {self.name} (ID: {self.strategy_id}) 已停止")

    def _run_with_error_handling(self):
        """带错误处理的策略运行循环"""
        while self._running:
            try:
                self._error_count = 0  # 重置错误计数
                self.run()  # 运行策略的主要逻辑

            except Exception as e:
                self._error_count += 1
                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 发生错误: {str(e)}",
                    "error",
                )

                if self._error_count >= self._max_retries:
                    log(
                        f"策略 {self.name} (ID: {self.strategy_id}) 达到最大重试次数，停止运行",
                        "error",
                    )
                    self._running = False
                    break

                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 将在 {self._retry_delay} 秒后重试",
                    "warning",
                )
                time.sleep(self._retry_delay)

    def _run_deal_processor(self):
        """交易信息处理线程"""
        while self._running:
            try:
                # 使用get_nowait()避免阻塞，如果队列为空则继续循环
                deal_info = self._deal_queue.get()
                self._update_strategy_info(deal_info)
                self.on_deal(deal_info)
                time.sleep(0.1)

            except Exception as e:
                log(f"策略 {self.name} 处理交易信息时出错: {str(e)}", "error")
                # 这里可以选择是否要重试，因为交易信息处理失败通常不需要重试
                continue

    def run(self):
        """策略的主要运行逻辑"""
        while self._running:
            try:
                if self.bars.empty:
                    self.bars._df = self.datafeed.load_bars(
                        self.symbol, self.min_bars_count, self.period
                    )
                if self.strategy_account is None:
                    self.strategy_account = self.datafeed.get_strategy_account(
                        self.strategy_id
                    )
                if self.strategy_positions is None:
                    self.strategy_positions = StrategyPosition(self)  # noqa
                    self.strategy_positions.refresh()
                if self.strategy_combinations is None:
                    self.strategy_combinations = StrategyCombination(self)  # noqa
                    self.strategy_combinations.refresh()

                # 处理K线数据
                symbol, period, bar = (
                    self._queue.get()
                )  # 这里可以保持阻塞，因为K线是按周期产生的
                self.bars._df.loc[len(self.bars._df)] = bar
                self.bars._df = self.bars._df.tail(self.min_bars_count)
                self.bars._df = self.bars._df.reset_index(drop=True)
                self.on_bar(symbol, period, bar)

            except Exception as e:
                log(f"策略 {self.name} 执行出错: {str(e)}", "error")
                raise

    @abstractmethod
    def on_bar(self, symbol, period, bar):
        """处理接收到的K线数据"""
        pass

    @abstractmethod
    def on_deal(self, deal_info):
        """处理接收到的交易信息"""
        pass

    def _update_strategy_info(self, deal_record):
        if "/" in deal_record.instrument_id:
            if deal_record.direction == 48:  # 拆分组合
                self.strategy_combinations.release(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                )
            elif deal_record.direction == 49:  # 合并组合
                self.strategy_combinations.combine(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                )
        else:
            ...

    def update_combinations(self): ...

    def update_positions(self): ...
    def _on_data_arrived(self, symbol, period, bar):
        """处理接收到的数据"""
        self._queue.put((symbol, period, bar))

    def _on_deal_arrived(self, deal_info):
        """处理接收到的交易信息"""
        self._deal_queue.put(deal_info)

    @staticmethod
    def parse_deal_remark(remark):
        if remark == "":
            return {}
        info = remark.split(".")
        return {"strategy_id": info[0]}


class BaseDataFeed(ABC):
    def __init__(self):
        self._running = False
        self._subscribed_handlers = {}
        self._bars_cache = {}
        self.trade_calendar = TradeCalendar()

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    def subscribe(self, symbol, period, handler):
        if symbol not in self._subscribed_handlers:
            self._subscribed_handlers[symbol] = {period: []}
            self._bars_cache[symbol] = {period: []}
        elif period not in self._subscribed_handlers[symbol]:
            self._subscribed_handlers[symbol][period] = []
            self._bars_cache[symbol][period] = []

        self._subscribed_handlers[symbol][period].append(handler)

    @property
    def running(self):
        return self._running

    @running.setter
    def running(self, value):
        self._running = value


class StrategyPosition:

    def __init__(self, strategy):

        self.strategy = strategy
        self.datafeed = strategy.datafeed
        self.positions = pd.DataFrame()

    def refresh(self):
        today = datetime.now().date()
        # 获取当天的所有持仓记录，如果不存在，则获取最近交易日的持仓记录
        positions = self.datafeed.get_strategy_positions(
            self.strategy.strategy_id, today
        )
        if positions == []:
            last_trade_date = self.datafeed.get_last_strategy_positions_date(
                self.strategy.strategy_id
            )
            if last_trade_date is None:
                return
            positions = self.datafeed.get_strategy_positions(
                self.strategy.strategy_id, last_trade_date
            )
        # 过滤持仓记录，仅仅保留相同标的和持仓方向的最新记录，这就是最新的持仓
        positions_df = record2dataframe(positions)
        positions_df = positions_df.sort_values(by="created")
        idx = positions_df.groupby(["instrumentId", "direction"])[
            "created"
        ].idxmax()  # noqa
        df = positions_df.loc[idx]
        df = df.sort_values(by="created")
        self.positions = df.reset_index(drop=True)

        # 如果当天是交易日，却没有持仓记录，则保存最新持仓
        if (
            self.datafeed.trade_calendar.is_trade_date(today)
            and self.positions.iloc[0]["created"].date() != today
        ):
            self.save()

    def save(self):
        for _, row in self.positions.iterrows():
            self.datafeed.save_strategy_position(
                self.strategy.strategy_id,
                row["instrument_id"],
                row["instrument_name"],
                row["direction"],
                row["volume"],
                row["open_price"],
            )


class StrategyCombination:

    def __init__(self, strategy):

        self.strategy = strategy
        self.datafeed = strategy.datafeed
        self.combinations = pd.DataFrame()

    def refresh(self):
        today = datetime.now().date()
        # 获取当天的所有持仓记录，如果不存在，则获取最近交易日的持仓记录
        combinations = self.datafeed.get_combinations_positions(
            self.strategy.strategy_id, today
        )
        if combinations == []:
            last_trade_date = self.datafeed.get_last_strategy_combinations_date(  # noqa
                self.strategy.strategy_id
            )
            if last_trade_date is None:
                return
            combinations = self.datafeed.get_combinations_positions(
                self.strategy.strategy_id, last_trade_date
            )
        # 过滤持仓记录，仅仅保留相同标的和持仓方向的最新记录，这就是最新的持仓
        combinations_df = record2dataframe(combinations)
        combinations_df = combinations_df.sort_values(by="created")
        idx = combinations_df.groupby(["instrument_id"])["created"].idxmax()  # noqa
        df = combinations_df.loc[idx]
        df = df.sort_values(by="created")
        self.combinations = df.reset_index(drop=True)

        # 如果当天是交易日，却没有持仓记录，则保存最新持仓
        if (
            self.datafeed.trade_calendar.is_trade_date(today)
            and self.combinations.iloc[0]["created"].date() != today
        ):
            self.save()

    def save(self):
        for _, row in self.combinations.iterrows():
            self.datafeed.save_strategy_combinations(
                self.strategy.strategy_id,
                row["instrument_id"],
                row["instrument_name"],
                row["volume"],
            )

    def release(self, instrument_id, instrument_name, volume):
        if self.combinations.empty:
            return

        existing_combination = self.combinations[
            self.combinations["instrument_id"] == instrument_id
        ]
        if existing_combination.empty:
            return
        existing_combination_volume = int(existing_combination.iloc[0]["volume"])
        new_volume = existing_combination_volume - volume
        self.combinations.loc[existing_combination.index[0], "volume"] = new_volume
        self.datafeed.save_strategy_combinations(
            self.strategy.strategy_id,
            instrument_id,
            instrument_name,
            new_volume,
        )

    def combine(self, instrument_id, instrument_name, volume):
        if self.combinations.empty:
            existing_combination = pd.DataFrame()
        else:
            existing_combination = self.combinations[
                self.combinations["instrument_id"] == instrument_id
            ]
        if existing_combination.empty:
            combination = {
                "strategy": self.strategy.strategy_id,
                "instrument_id": instrument_id,
                "instrument_name": instrument_name,
                "volume": volume,
            }
            if self.combinations.empty:
                self.combinations = pd.DataFrame([combination])
            else:
                self.combinations.loc[len(self.combinations)] = combination
            self.datafeed.save_strategy_combinations(
                self.strategy.strategy_id,
                instrument_id,
                instrument_name,
                volume,
            )
        else:
            existing_combination_volume = int(existing_combination.iloc[0]["volume"])
            new_volume = existing_combination_volume + volume
            self.combinations.loc[existing_combination.index[0], "volume"] = new_volume
            self.datafeed.save_strategy_combinations(
                self.strategy.strategy_id,
                instrument_id,
                instrument_name,
                new_volume,
            )


if __name__ == "__main__":
    from utils.pb_client import get_pb_client
    from utils.config import load_market_db_config, load_history_db_config
    from strategies.dolphindb_datafeed import DolphinDBDataFeed

    client = get_pb_client()

    global datafeed
    datafeed = DolphinDBDataFeed(
        load_history_db_config(), load_market_db_config(), client
    )  # noqa

    class DemoStrategy:

        def __init__(self):
            self.strategy_id = "7416w114037s7c8"

    positions = StrategyPosition(DemoStrategy(), datafeed)
    positions.refresh()
