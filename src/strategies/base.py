import threading
import pandas as pd
import time
from abc import ABC, abstractmethod
from queue import Queue
from utils.logger import log
from utils.common import DataFrameWrapper
from utils.trade_calendar import TradeCalendar


class BaseStrategy(ABC):
    def __init__(self, strategy_id, name, params, datafeed):
        self.strategy_id = strategy_id
        self.name = name
        self.datafeed = datafeed
        self._running = False
        self._thread = None
        self._error_count = 10
        self._max_retries = 3  # 最大重试次数
        self._retry_delay = 5  # 重试延迟（秒）
        self._queue = Queue()
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

    def start(self):
        """启动策略线程"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_with_error_handling)
        self._thread.daemon = True  # 设置为守护线程，这样主程序退出时线程会自动结束
        self._thread.start()
        # log(f"策略 {self.name} (ID: {self.strategy_id}) 已启动")

    def stop(self):
        """停止策略线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)  # 等待线程结束，最多等待5秒
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
                    self.strategy_positions = self.datafeed.get_strategy_positions(
                        self.strategy_id
                    )  # noqa
                symbol, period, bar = self._queue.get()
                self.bars._df.loc[len(self.bars._df)] = bar
                self.bars._df = self.bars._df.tail(self.min_bars_count)
                self.bars._df = self.bars._df.reset_index(drop=True)
                self.on_bar(symbol, period, bar)
                time.sleep(1)  # 模拟策略执行间隔

            except Exception as e:
                log(f"RSI策略 {self.name} 执行出错: {str(e)}", "error")
                raise  # 重新抛出异常，让基类处理重试逻辑

    @abstractmethod
    def on_bar(self, symbol, period, bar):
        """处理接收到的K线数据"""
        pass

    def _on_data_arrived(self, symbol, period, bar):
        """处理接收到的数据"""
        self._queue.put((symbol, period, bar))


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
