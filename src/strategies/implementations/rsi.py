from ..base import BaseStrategy
from utils.logger import log
import time


class RSIStrategy(BaseStrategy):
    def __init__(self, strategy_id, name, params):
        super().__init__(strategy_id, name, params)
        self.period = params.get("period", 14)
        self.overbought = params.get("overbought", 70)
        self.oversold = params.get("oversold", 30)
        self.symbol = params.get("symbol", "BTC/USDT")

    def run(self):
        """策略的主要运行逻辑"""
        while self._running:
            try:
                # 模拟策略运行
                log(f"RSI策略 {self.name} 正在运行 - 交易对: {self.symbol}")
                # TODO: 实现实际的策略逻辑
                time.sleep(1)  # 模拟策略执行间隔

            except Exception as e:
                log(f"RSI策略 {self.name} 执行出错: {str(e)}", "error")
                raise  # 重新抛出异常，让基类处理重试逻辑
