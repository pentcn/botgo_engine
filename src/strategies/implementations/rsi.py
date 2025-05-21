from ..base import BaseStrategy
from utils.logger import log
import time


class RSIStrategy(BaseStrategy):
    def __init__(self, datafeed, strategy_id, name, params):
        super().__init__(strategy_id, name, params, datafeed)
        self.overbought = params.get("overbought", 70)
        self.oversold = params.get("oversold", 30)

    def on_bar(self, symbol, period, bar):
        """处理接收到的K线数据"""
        print(self.bars)
