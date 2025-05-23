from ..base import BaseStrategy
from pandas_ta import macd, atr
from indicators.dsrt import DSRT


class WangBaStrategy(BaseStrategy):
    def __init__(self, datafeed, strategy_id, name, params):
        super().__init__(strategy_id, name, params, datafeed)
        self.overbought = params.get("overbought", 70)
        self.oversold = params.get("oversold", 30)

    def on_bar(self, symbol, period, bar):
        """处理接收到的K线数据"""
        print(
            symbol,
            period == self.period,
            self.bars[-1].datetime,
            self.bars[-1].close,  # noqa
        )
        dsrt = list(DSRT(self.bars.close, self.bars.high, self.bars.low))
        macd_hist = list(macd(self.bars.close)["MACDh_12_26_9"])
        atr_value = list(
            atr(self.bars.high, self.bars.low, self.bars.close, length=14)
        )  # noqa
        print(dsrt[-1], macd_hist[-1], atr_value[-1])

    def on_deal(self, deal_info):
        print(deal_info)
