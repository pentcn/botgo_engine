from pandas_ta import macd, atr
from indicators.dsrt import DSRT
from ..base import BaseStrategy
from utils.option import OptionCombinationType


class WangBaStrategy(BaseStrategy):
    def __init__(self, datafeed, strategy_id, name, params):
        super().__init__(datafeed, strategy_id, name, params)
        self.user_id = "v4w3357rsqml48g"
        self.overbought = params.get("overbought", 70)
        self.oversold = params.get("oversold", 30)

        # 测试买卖单
        call_1 = "10009326.SHO"  # 6月2700
        call_2 = "10009327.SHO"  # 6月2750
        put_1 = "10009335.SHO"  # 6月2700
        put_2 = "10009336.SHO"  # 6月2750

        self.sell_open(call_1, 20)
        self.buy_open(call_2, 20)
        # self.sell_close(put_1, 1)
        # self.buy_close(put_2, 1)
        # self.cancel("14")
        # self.make_combination(
        #     OptionCombinationType.BULL_CALL_SPREAD, call_1, True, call_2, False, 1
        # )
        # self.release_combination("202505300000821")

        # symbol_1 = self.datafeed.find_contract_symbol(call_1, 1, -1)
        # symbol_2 = self.datafeed.find_std_contract_symbol(
        #     2.75, (0.99, 1.01), 0, "510050", False, True
        # )
        # print(symbol_2)

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
