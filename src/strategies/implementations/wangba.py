from pandas_ta import macd, atr
from indicators.dsrt import DSRT
from ..base import BaseStrategy, StateVariable
from utils.logger import log

# from utils.option import OptionCombinationType


class WangBaStrategy(BaseStrategy):
    proctect_price = StateVariable(0.0, description="保护价格")
    loss_price = StateVariable(0.0, description="亏损价格")

    def __init__(self, datafeed, strategy_id, name, params):
        super().__init__(datafeed, strategy_id, name, params)
        # self.user_id = "v4w3357rsqml48g"
        self.overbought = params.get("overbought", 70)
        self.oversold = params.get("oversold", 30)

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

    def on_post_init(self):
        # 测试买卖单
        self.call_1 = "10009326.SHO"  # 6月2700
        self.call_2 = "10009327.SHO"  # 6月2750
        self.put_1 = "10009335.SHO"  # 6月2700
        self.put_2 = "10009336.SHO"  # 6月2750

        # self.run_test_scene_1()
        # self.run_test_scene_2()
        # self.run_test_scene_3()
        # self.run_test_scene_4()
        # self.run_test_scene_5()
        # self.run_test_scene_6()
        # self.run_test_scene_7()
        # self.run_test_scene_8()
        # self.run_test_scene_9() # 未通过，可能是测试服务器的问题
        # self.run_test_scene_10()  # 未通过，可能是测试服务器的问题
        # self.run_test_scene_11()  #

        print("以上测试通过了，需要测试各种组合的移仓操作")

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
        # print(deal_info)
        ...

    def run_test_scene_1(self):
        """
        测试场景1：简单开仓
        卖出call_1，买入call_2
        """

        self.sell_open(self.call_1, 20)
        self.buy_open(self.call_2, 20)

    def run_test_scene_2(self):
        """
        测试场景2：简单平仓
        卖出call_1，买入call_2
        """
        self.buy_close(self.call_1, 13)
        self.sell_close(self.call_2, 13)

    def run_test_scene_3(self):
        """
        测试场景3： 开仓并构成认购熊市价差
        """
        log("构造认购熊市价差")
        self.sell_open(
            self.call_1, 11, f"{self.call_2}|-1|1"
        )  # -1 本仓位是业务仓，1 待组合的仓位是权利仓
        self.buy_open(self.call_2, 11, f"{self.call_1}|1|-1")

    def run_test_scene_4(self):
        """
        测试场景4： 开仓并构成认购牛市价差
        """
        self.buy_open(self.call_1, 11, f"{self.call_2}|1|-1")
        self.sell_open(self.call_2, 11, f"{self.call_1}|-1|1")

    def run_test_scene_5(self):
        """
        测试场景5： 开仓并构成认沽牛市价差
        """
        self.buy_open(self.put_1, 11, f"{self.put_2}|1|-1")
        self.sell_open(self.put_2, 11, f"{self.put_1}|-1|1")

    def run_test_scene_6(self):
        """
        测试场景5： 开仓并构成认沽熊市价差
        """
        self.buy_open(self.put_2, 11, f"{self.put_1}|1|-1")
        self.sell_open(self.put_1, 11, f"{self.put_2}|-1|1")

    def run_test_scene_7(self):
        """
        测试场景5： 开仓并构成跨式策略
        """
        self.sell_open(self.call_1, 11, f"{self.put_1}|-1|-1")
        self.sell_open(self.put_1, 11, f"{self.call_1}|-1|-1")

    def run_test_scene_8(self):
        """
        测试场景5： 开仓并构成宽跨式策略
        """
        self.sell_open(self.call_2, 11, f"{self.put_1}|-1|-1")
        self.sell_open(self.put_1, 11, f"{self.call_2}|-1|-1")

    def run_test_scene_9(self):
        """
        测试场景5： 组合平仓
        """
        self.close_combination(self.call_1, self.call_2, 3)

    def run_test_scene_10(self):
        """
        测试场景5： 原始构造组合
        """
        self.make_combination(53, "10009327.SHO", True, "10009326.SHO", False, 8)

    def run_test_scene_11(self):
        """
        测试场景5： 原始构造组合
        """
        self.move_combination(
            "10009327.SHO", "10009326.SHO", "10009327.SHO", "10009326.SHO", 11
        )
