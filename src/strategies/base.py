import threading
import pandas as pd
import time
import json
from abc import ABC, abstractmethod
from datetime import datetime
from queue import Queue
from typing import Any, Dict, Set
from utils.logger import log
from utils.common import DataFrameWrapper, record2dataframe, short_uuid, decompose
from utils.option import OptionCombinationType, MarketOptionChain
from utils.trade_calendar import TradeCalendar
import numpy as np


class StateVariable:
    """状态变量描述符 - 实现友好的状态访问"""

    def __init__(self, default_value: Any = None, description: str = ""):
        self.default_value = default_value
        self.description = description
        self.name = None  # 将在 __set_name__ 中设置

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance._strategy_state.get(self.name, self.default_value)

    def __set__(self, instance, value):
        if instance is None:
            return

        # 更新内存中的状态
        instance._strategy_state[self.name] = value

        # 如果策略已初始化完成，则自动保存到数据库
        if (
            hasattr(instance, "_strategy_initialized")
            and instance._strategy_initialized
            and hasattr(instance, "user_id")
            and instance.user_id
        ):
            instance.save_strategy_state()


class BaseStrategy(ABC):
    def __init__(self, datafeed, strategy_id, name, params):
        self.strategy_id = strategy_id
        self.name = name
        self.datafeed = datafeed
        self._running = False
        self._thread = None
        self._deal_thread = None  # 新增交易信息处理线程
        self._deal_lock = threading.Lock()  # 添加交易信息处理锁
        self._error_count = 10
        self._max_retries = 3  # 最大重试次数
        self._retry_delay = 5  # 重试延迟（秒）
        self._queue = Queue()  # K线的队列
        self._deal_queue = Queue()  # 交易信息的队列
        self.params = params
        self.period = params.get("period", None)
        self.symbol = params.get("symbol", None)
        self.commission = params.get("commission", 1.8)
        self.min_bars_count = params.get("min_bars_count", 300)
        self.account_id = params.get("account_id", None)
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

        self.user_id = None

        # 策略状态持久化相关属性
        self._strategy_state = {}  # 存储策略的自定义状态变量
        self._state_loaded = False  # 标记状态是否已加载
        self._strategy_initialized = False  # 标记策略是否完全初始化

        # 友好状态访问相关属性
        self._state_variables: Set[str] = set()  # 存储状态变量名称

        # 发现并初始化状态变量
        self._discover_state_variables()
        self._initialize_state_variables()

        # 在策略初始化时自动加载状态
        self._load_strategy_state_on_init()

        # 标记策略是否初始化完成,即on_post_init方法是否执行完成
        self.has_init = False

    def on_post_init(self): ...

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

        # 策略停止时保存最终状态
        if self._strategy_state and self.user_id:
            self.save_strategy_state(force_save=True)
            log(f"策略 {self.name} (ID: {self.strategy_id}) 最终状态已保存")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._deal_thread and self._deal_thread.is_alive():
            self._deal_thread.join(timeout=5)
        # log(f"策略 {self.name} (ID: {self.strategy_id}) 已停止")

    def _run_with_error_handling(self):
        """带错误处理的策略运行循环"""
        while self._running:
            # try:
            self._error_count = 0  # 重置错误计数
            self.run()  # 运行策略的主要逻辑

        # except Exception as e:
        #     self._error_count += 1
        #     log(
        #         f"策略 {self.name} (ID: {self.strategy_id}) 发生错误: {str(e)}",
        #         "error",
        #     )

        #     if self._error_count >= self._max_retries:
        #         log(
        #             f"策略 {self.name} (ID: {self.strategy_id}) 达到最大重试次数，停止运行",  # noqa
        #             "error",
        #         )
        #         self._running = False
        #         break

        #     log(
        #         f"策略 {self.name} (ID: {self.strategy_id}) 将在 {self._retry_delay} 秒后重试",  # noqa
        #         "warning",
        #     )
        #     time.sleep(self._retry_delay)

    def _run_deal_processor(self):
        """交易信息处理线程"""
        while self._running:
            # try:
            # 使用get_nowait()避免阻塞，如果队列为空则继续循环
            deal_info = self._deal_queue.get()
            with self._deal_lock:
                self._update_strategy_info(deal_info)
                self.on_deal(deal_info)
            time.sleep(0.01)

        # except Exception as e:
        #     log(f"策略 {self.name} 处理交易信息时出错: {str(e)}", "error")
        #     continue

    def run(self):
        """策略的主要运行逻辑"""
        while self._running:
            # try:
            if self.bars.empty:
                self.bars._df = self.datafeed.load_bars(
                    self.symbol, self.min_bars_count, self.period
                )
            if self.strategy_positions is None:
                self.strategy_positions = StrategyPosition(self)  # noqa
                self.strategy_positions.refresh()
            if self.strategy_combinations is None:
                self.strategy_combinations = StrategyCombination(self)  # noqa
                self.strategy_combinations.refresh()
            if self.strategy_account is None:
                self.strategy_account = StrategyAccount(self)
                self.strategy_account.refresh()

            if not self.has_init:
                self.has_init = True
                self.on_post_init()

            # 处理K线数据
            symbol, period, bar = (
                self._queue.get()
            )  # 这里可以保持阻塞，因为K线是按周期产生的
            self.bars._df.loc[len(self.bars._df)] = bar
            self.bars._df = self.bars._df.tail(self.min_bars_count)
            self.bars._df = self.bars._df.reset_index(drop=True)

            # 确保状态已加载
            self._ensure_state_loaded()

            self.on_bar(symbol, period, bar)

            # # 定期自动保存状态
            # self._auto_save_state()

        # except Exception as e:
        #     log(f"策略 {self.name} 执行出错: {str(e)}", "error")
        #     raise

    def set_user(self, user_id):
        self.user_id = user_id
        # 用户ID设置后立即加载状态
        self.load_strategy_state()
        # 标记策略完全初始化完成
        self._strategy_initialized = True
        log(f"策略 {self.name} 用户设置完成: {user_id}, 状态已加载")

    def _trade(
        self, command_id, symbol, volume, follow_trade_info="", max_order_size=-1
    ):
        if max_order_size == -1:
            max_order_size = volume

        for vol in decompose(volume, max_order_size):
            remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
            if follow_trade_info != "":
                remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
            data = {
                "opType": command_id,  # 50：买入开仓 51：卖出平仓 52：卖出开仓  53：买入平仓
                "orderType": 1101,
                "orderCode": symbol,
                "prType": 14,  # 14对手价，5最新价
                "price": -1,
                "volume": vol,
                "strategyName": self.name,
                "quickTrade": 1,
                "userOrderId": remark,
                "user": self.user_id,
                "accountId": self.account_id,
            }
            self.datafeed.create_trade_command(data)

    def buy_open(self, symbol, volume, follow_trade_info="", max_order_size=-1):
        self._trade(50, symbol, volume, follow_trade_info, max_order_size)

    def buy_close(self, symbol, volume, follow_trade_info="", max_order_size=-1):
        self._trade(53, symbol, volume, follow_trade_info, max_order_size)

    def sell_open(self, symbol, volume, follow_trade_info="", max_order_size=-1):
        self._trade(52, symbol, volume, follow_trade_info, max_order_size)

    def sell_close(self, symbol, volume, follow_trade_info="", max_order_size=-1):
        self._trade(51, symbol, volume, follow_trade_info, max_order_size)

    # def cancel(self, task_id, follow_trade_info=""):
    #     remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
    #     if follow_trade_info != "":
    #         remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
    #     data = {
    #         "orderType": -100,
    #         "orderCode": task_id,
    #         "strategyName": self.name,
    #         "userOrderId": remark,
    #         "user": self.user_id,
    #         "accountId": self.account_id,
    #     }
    #     self.datafeed.create_trade_command(data)

    def make_combination(
        self, comd_type, code_1, is_buyer_1, code_2, is_buyer_2, volume
    ):
        json_obj = {
            f"{code_1}": 48 if is_buyer_1 else 49,
            f"{code_2}": 48 if is_buyer_2 else 49,
        }
        # 准备要插入的数据
        data = {
            "opType": comd_type,
            "orderType": -200,
            "orderCode": json.dumps(json_obj),
            "volume": volume,
            "strategyName": self.name,
            "userOrderId": f"{self.strategy_id}|{short_uuid()}",
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def release_combination(self, comb_id, follow_trade_info=""):
        remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
        if follow_trade_info != "":
            remark = f"{self.strategy_id}|{short_uuid()}|{follow_trade_info}"
        data = {
            "orderType": -300,
            "orderCode": comb_id,
            "strategyName": self.name,
            "userOrderId": remark,
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def close_combination(self, code_1, code_2, volume):
        records = self.datafeed.get_comb_records(code_1, code_2, self.user_id)

        for record in records:
            if record.volume >= volume:
                first_pos_type = (
                    str(volume)
                    if record.first_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                second_pos_type = (
                    str(volume)
                    if record.second_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                pos_type = "/".join(
                    [
                        first_pos_type,
                        second_pos_type,
                        str(
                            OptionCombinationType.get_type_value_by_code(
                                record.comb_code
                            )
                        ),
                    ]
                )

                self.release_combination(record.comb_id, pos_type)
                break
            else:
                volume = volume - record.volume
                first_pos_type = (
                    str(volume)
                    if record.first_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                second_pos_type = (
                    str(volume)
                    if record.second_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                pos_type = "/".join(
                    [
                        first_pos_type,
                        second_pos_type,
                        str(
                            OptionCombinationType.get_type_value_by_code(
                                record.comb_code
                            )
                        ),
                    ]
                )

                self.release_combination(record.comb_id, pos_type)

    def move_combination(self, code_1, code_2, target_code_1, target_code_2, volume):
        records = self.datafeed.get_comb_records(code_1, code_2, self.user_id)
        if records is None:
            log(f"不存在满足条件的组合{code_1}/{code_2}, 无法完成组合移仓")
            return

        for record in records:
            if record.volume >= volume:
                first_pos_type = (
                    str(volume)
                    if record.first_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                second_pos_type = (
                    str(volume)
                    if record.second_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                pos_type = "/".join(
                    [
                        first_pos_type,
                        second_pos_type,
                        str(
                            OptionCombinationType.get_type_value_by_code(
                                record.comb_code
                            )
                        ),
                    ]
                )
                remark = f"{pos_type}|{target_code_1}/{target_code_2}"

                self.release_combination(record.comb_id, remark)
                break
            else:
                volume = volume - record.volume
                first_pos_type = (
                    str(volume)
                    if record.first_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                second_pos_type = (
                    str(volume)
                    if record.second_code_pos_type == 48
                    else f"{-1 * volume}"
                )
                pos_type = "/".join(
                    [
                        first_pos_type,
                        second_pos_type,
                        str(
                            OptionCombinationType.get_type_value_by_code(
                                record.comb_code
                            )
                        ),
                    ]
                )
                remark = f"{pos_type}|{target_code_1}/{target_code_2}"
                self.release_combination(record.comb_id, remark)

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
            if deal_record.direction == 49:  # 构造组合
                self.strategy_combinations.combine(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                )
                self.strategy_account.set_last_account()

            elif deal_record.direction == 48:  # 拆分组合
                self.strategy_combinations.release(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                )
                self.strategy_account.set_last_account()
                # 根据remark信息，执行拆分组合后的后续操作
                self.after_release(
                    deal_record.instrument_id,
                    deal_record.volume,
                    deal_record.exchange_id,
                    deal_record.remark,
                )
        else:
            if deal_record.offset_flag == 48:  # 开仓
                if deal_record.direction == 48:  # 买入
                    direction = 1
                    commission = self.commission
                elif deal_record.direction == 49:  # 卖出
                    direction = -1
                    commission = 0
                self.strategy_positions.open(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                    deal_record.price,
                    direction,
                    commission,
                )
                self.strategy_account.set_last_account()

                # 根据remark信息，执行开仓后的后续操作
                self.after_open(
                    f"{deal_record.instrument_id}.{deal_record.exchange_id}",
                    deal_record.volume,
                    direction == 1,
                    deal_record.remark,
                )
            elif deal_record.offset_flag == 49:  # 平仓
                if deal_record.direction == 48:  # 买入
                    direction = -1  # 针对义务仓
                elif deal_record.direction == 49:  # 卖出
                    direction = 1  # 针对权利仓

                volume = self.strategy_positions.get_volume(
                    deal_record.instrument_id
                )  # noqa
                if volume == deal_record.volume:  # 某个合约全部平仓才计算盈利
                    open_price = self.strategy_positions.get_open_price(
                        deal_record.instrument_id
                    )
                    profit = (
                        (deal_record.price - open_price)
                        * deal_record.volume
                        * direction
                    )
                    multi = self.datafeed.market_option_chain.get_contract_by_id(
                        deal_record.instrument_id
                    ).data["VolumeMultiple"]
                    profit = profit * multi
                    profit = profit - self.strategy_positions.get_commission(
                        deal_record.instrument_id
                    )
                    profit = profit - self.commission * deal_record.volume
                    self.strategy_account.add_profit(profit)
                    self.strategy_account.adjust_available_margin(
                        -self.commission * deal_record.volume
                    )

                self.strategy_positions.close(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                    deal_record.price,
                    direction,
                    self.commission,
                )
                self.strategy_account.set_last_account()
                # 根据remark信息，执行平仓后的后续操作
                self.after_close(deal_record.volume, direction == 1, deal_record.remark)
            else:
                raise ValueError(f"未知的交易类型: {deal_record}")

        time.sleep(0.01)

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
        info = remark.split("|")
        return {"strategy_id": info[0]}

    def after_release(self, comb_symbol, volume, exchange_id, remark):
        """
        拆分组合后的后续操作信息,组合的备注信息格式如下：
        策略ID|uuid|a/b|symbol1/symbol2
        a/b: 解除后是否平仓合约，0:不平仓，1:权利仓平仓, -1：义务仓平仓
        symbol1/symbol2: 平仓后是否开仓（移仓）symbol1和symbol2不为空就开仓，否则不操作
        """
        origin_code_1, origin_code_2 = comb_symbol.split("/")
        info = remark.split("|")
        close_flag_1, close_flag_2, comb_type = (
            info[2].split("/") if len(info) >= 3 else (0, 0, 0)
        )
        close_flag_1 = int(close_flag_1)
        close_flag_2 = int(close_flag_2)
        comb_type = int(comb_type)

        next_symbol_1, next_symbol_2 = (
            info[3].split("/") if len(info) >= 4 else ("", "")
        )

        rest_vol = volume - abs(close_flag_1)
        volume = abs(close_flag_1)

        waiting_comb_flag_1 = "1" if close_flag_1 > 0 else "-1"
        waiting_comb_flag_2 = "1" if close_flag_2 > 0 else "-1"
        if close_flag_1 > 0:  # 权利仓
            self.sell_close(
                f"{origin_code_1}.{exchange_id}",
                volume,
                "|".join([next_symbol_1, next_symbol_2, "1", waiting_comb_flag_2]),
            )
        elif close_flag_1 < 0:  # 义务仓
            self.buy_close(
                f"{origin_code_1}.{exchange_id}",
                volume,
                "|".join([next_symbol_1, next_symbol_2, "-1", waiting_comb_flag_2]),
            )
        if close_flag_2 > 0:
            self.sell_close(
                f"{origin_code_2}.{exchange_id}",
                volume,
                "|".join([next_symbol_2, next_symbol_1, "1", waiting_comb_flag_1]),
            )
        elif close_flag_2 < 0:  # 义务仓
            self.buy_close(
                f"{origin_code_2}.{exchange_id}",
                volume,
                "|".join([next_symbol_2, next_symbol_1, "-1", waiting_comb_flag_1]),
            )

        if rest_vol > 0:
            self.make_combination(
                comb_type,
                f"{origin_code_1}.{exchange_id}",
                close_flag_1 > 0,
                f"{origin_code_2}.{exchange_id}",
                close_flag_2 > 0,
                rest_vol,
            )

    def after_close(self, volume, is_buyer=True, remark=""):
        """
        平仓后的后续操作信息,平仓的备注信息格式如下：
        策略ID|uuid|symbol1/symbol2|a
        symbol1: 平仓后需要新开的合约代码
        symbol2: 新开仓后，如果有可用的symbol2合约，构造组合
        a:1，待构造组合为权利仓，-1 待构造组合为义务仓
        """
        info = remark.split("|")
        new_symbol = info[2] if len(info) >= 3 else ""
        opposite_symbol = "|".join(info[3:]) if len(info) >= 4 else ""
        if new_symbol != "":
            if is_buyer:
                self.buy_open(new_symbol, volume, opposite_symbol)
            else:
                self.sell_open(new_symbol, volume, opposite_symbol)

    def after_open(self, symbol, volume, is_buyer, remark=""):
        """
        开仓后根据remark作后续操作，开仓备注信息格式如下：
        策略ID|uuid|symbol|a
        symbol:待构造组合的symbol
        a=1：表明构造组合的symbol为权利仓 ; a=-1表明义务仓
        """
        info = remark.split("|")
        value = info[4] if len(info) >= 5 else ""
        opposite_is_buyer = True if value == "1" else False
        opposite_symbol = info[2] if len(info) >= 3 else ""
        opposite_strike, opposite_type = self.datafeed.get_strike(opposite_symbol)
        strike, pos_type = self.datafeed.get_strike(symbol)

        opponent_volume = self.datafeed.get_available_volume(
            self.user_id, opposite_symbol.split(".")[0]
        )
        vol = min(opponent_volume, volume)
        if vol == 0:
            return

        if strike is None or opposite_strike is None:
            return

        if is_buyer:
            first_opt = (True, symbol, strike, pos_type)
            second_opt = (
                opposite_is_buyer,
                opposite_symbol,
                opposite_strike,
                opposite_type,
            )
        else:
            first_opt = (
                opposite_is_buyer,
                opposite_symbol,
                opposite_strike,
                opposite_type,
            )
            second_opt = (True if int(value) > 0 else False, symbol, strike, pos_type)

        comb_type = None
        if first_opt[0]:  # 价差组合
            if first_opt[3] == "CALL":
                if first_opt[2] < second_opt[2]:  # 认购牛市价差
                    comb_type = OptionCombinationType.BULL_CALL_SPREAD
                else:  # 认购熊市价差
                    comb_type = OptionCombinationType.BEAR_CALL_SPREAD
            else:
                if first_opt[2] < second_opt[2]:  # 认沽牛市价差
                    comb_type = OptionCombinationType.BULL_PUT_SPREAD
                else:  # 认沽熊市价差
                    comb_type = OptionCombinationType.BEAR_PUT_SPREAD

        elif first_opt[2] == second_opt[2]:  # 跨式组合
            comb_type = OptionCombinationType.SHORT_STRADDLE
        else:  # 宽跨式组合
            comb_type = OptionCombinationType.SHORT_STRANGLE

        if comb_type is not None:
            self.make_combination(
                comb_type.value,
                first_opt[1],
                first_opt[0],
                second_opt[1],
                second_opt[0],
                vol,
            )

    def save_strategy_state(self, state_data=None, force_save=False):
        """
        保存策略状态到数据库

        Args:
            state_data (dict, optional): 要保存的状态数据，如果为None则保存self._strategy_state
            force_save (bool): 是否强制保存，忽略时间间隔限制
        """
        try:
            current_time = time.time()

            # 检查是否需要保存（除非强制保存）
            # if (
            #     not force_save
            #     and (current_time - self._last_state_save_time)
            #     < self._state_auto_save_interval
            # ):
            #     return

            # 确定要保存的数据
            if state_data is None:
                # 优先保存状态变量，同时保持向后兼容
                if self._state_variables:
                    state_data = {
                        name: self._strategy_state.get(name)
                        for name in self._state_variables
                    }
                    # 添加非状态变量的数据（向后兼容）
                    for key, value in self._strategy_state.items():
                        if key not in self._state_variables:
                            state_data[key] = value
                else:
                    state_data = self._strategy_state.copy()

            # 使用datafeed的方法保存状态
            success = self.datafeed.save_strategy_state_to_db(
                self.strategy_id,
                self.user_id,
                self.name,
                json.dumps(
                    state_data, default=str
                ),  # 使用default=str处理不可序列化的对象
                int(current_time),  # 使用时间戳作为版本号
            )

            if success:
                self._last_state_save_time = current_time
                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 状态已保存，包含 {len(state_data)} 个变量"
                )

            return success

        except Exception as e:
            log(f"保存策略状态失败: {str(e)}", "error")

    def load_strategy_state(self):
        """
        从数据库加载策略状态

        Returns:
            dict: 加载的状态数据，如果没有找到则返回空字典
        """
        try:
            if not self.user_id:
                log(f"策略 {self.name} 用户ID未设置，无法加载状态", "warning")
                return {}

            # 使用datafeed的方法加载状态
            record_data = self.datafeed.load_strategy_state_from_db(
                self.strategy_id, self.user_id
            )

            if record_data:
                state_data = record_data["state_data"]

                # 只更新已定义的状态变量
                for var_name in self._state_variables:
                    if var_name in state_data:
                        self._strategy_state[var_name] = state_data[var_name]

                # 同时支持旧方式的状态变量
                for key, value in state_data.items():
                    if key not in self._state_variables:
                        self._strategy_state[key] = value

                self._state_loaded = True
                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 状态已加载，包含 {len(state_data)} 个变量"
                )
                return state_data
            else:
                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 未找到历史状态，使用默认值"
                )
                # 如果没有历史状态且有状态变量定义，保存初始状态
                if self._state_variables and self.user_id:
                    self.save_strategy_state(force_save=True)
                return {}

        except Exception as e:
            log(f"加载策略状态失败: {str(e)}", "error")
            return {}

    def get_state_variable(self, key, default_value=None):
        """
        获取策略状态变量

        Args:
            key (str): 变量名
            default_value: 默认值

        Returns:
            变量值或默认值
        """
        return self._strategy_state.get(key, default_value)

    def set_state_variable(self, key, value):
        """
        设置策略状态变量

        Args:
            key (str): 变量名
            value: 变量值
        """
        self._strategy_state[key] = value

        # 状态变化时立即保存
        if self.user_id:
            self.save_strategy_state()

    def update_state_variables(self, variables_dict):
        """
        批量更新策略状态变量

        Args:
            variables_dict (dict): 要更新的变量字典
        """
        self._strategy_state.update(variables_dict)

        # 批量更新后立即保存
        if self.user_id:
            self.save_strategy_state()

    def clear_state_variables(self):
        """清空所有策略状态变量"""
        self._strategy_state.clear()

    def get_all_state_variables(self):
        """获取所有策略状态变量的副本"""
        return self._strategy_state.copy()

    def _load_strategy_state_on_init(self):
        """策略初始化时自动加载状态"""
        # 延迟加载，等待user_id设置
        pass

    # def _auto_save_state(self):
    #     """自动保存状态（在策略运行过程中定期调用）"""
    #     # 对于分钟级策略，可以禁用定时保存，改为状态变化时立即保存
    #     pass

    def _ensure_state_loaded(self):
        """确保状态已加载"""
        if not self._state_loaded and self.user_id:
            self.load_strategy_state()

    def _discover_state_variables(self):
        """发现类中定义的所有状态变量"""
        for cls in reversed(self.__class__.__mro__):
            for name, value in cls.__dict__.items():
                if isinstance(value, StateVariable):
                    self._state_variables.add(name)

        if self._state_variables:
            log(f"策略 {self.name} 发现状态变量: {list(self._state_variables)}")

    def _initialize_state_variables(self):
        """初始化状态变量为默认值"""
        for var_name in self._state_variables:
            descriptor = getattr(self.__class__, var_name)
            if isinstance(descriptor, StateVariable):
                self._strategy_state[var_name] = descriptor.default_value

    def get_state_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        summary = {}
        for var_name in self._state_variables:
            descriptor = getattr(self.__class__, var_name)
            summary[var_name] = {
                "value": self._strategy_state.get(var_name),
                "default": descriptor.default_value,
                "description": descriptor.description,
            }
        return summary

    def reset_state_variable(self, var_name: str):
        """重置状态变量为默认值"""
        if var_name in self._state_variables:
            descriptor = getattr(self.__class__, var_name)
            setattr(self, var_name, descriptor.default_value)
            log(f"状态变量 {var_name} 已重置为默认值: {descriptor.default_value}")
        else:
            log(f"状态变量 {var_name} 不存在", "warning")

    def reset_all_state_variables(self):
        """重置所有状态变量为默认值"""
        for var_name in self._state_variables:
            self.reset_state_variable(var_name)
        log("所有状态变量已重置为默认值")

    def delete_strategy_state(self):
        """
        删除策略状态

        Returns:
            bool: 删除是否成功
        """
        try:
            if not self.user_id:
                log(f"策略 {self.name} 用户ID未设置，无法删除状态", "warning")
                return False

            success = self.datafeed.delete_strategy_state_from_db(
                self.strategy_id, self.user_id
            )

            if success:
                self._strategy_state.clear()
                self._state_loaded = False
                log(f"策略 {self.name} (ID: {self.strategy_id}) 状态已删除")

            return success

        except Exception as e:
            log(f"删除策略状态失败: {str(e)}", "error")
            return False

    def get_strategy_state_history(self, limit=10):
        """
        获取策略状态历史记录

        Args:
            limit (int): 返回记录数量限制

        Returns:
            list: 历史记录列表
        """
        try:
            if not self.user_id:
                log(f"策略 {self.name} 用户ID未设置，无法获取状态历史", "warning")
                return []

            return self.datafeed.get_strategy_state_history(
                self.strategy_id, self.user_id, limit
            )

        except Exception as e:
            log(f"获取策略状态历史失败: {str(e)}", "error")
            return []


class BaseDataFeed(ABC):
    def __init__(self):
        self._running = False
        self._subscribed_handlers = {}
        self._bars_cache = {}
        self.trade_calendar = TradeCalendar()
        self._market_option_chain = None  # 缓存MarketOptionChain实例

    @property
    def market_option_chain(self):
        """获取市场期权链实例"""
        if self._market_option_chain is None:
            self._market_option_chain = MarketOptionChain(
                self.load_last_option_contracts()
            )
        return self._market_option_chain

    def get_contract_info(self, symbol):
        symbol = symbol.split(".")[0]
        contract_obj = self.get_option_contract_by_id(symbol)
        if contract_obj:
            return {
                "strike": contract_obj.strike_price,
                "expire_date": contract_obj.expire_date,
                "undl": contract_obj.data["OptUndlCode"],
                "opt_type": contract_obj.option_type,
                "multi": contract_obj.data["VolumeMultiple"],
                "monthly": contract_obj.data["monthly"],
            }
        return None

    def get_option_contract_by_id(self, instrument_id):
        """
        使用MarketOptionChain获取期权合约对象
        :param instrument_id: 合约代码
        :return: OptionContract对象或None
        """
        instrument_id = instrument_id.split(".")[0]
        if self.market_option_chain:
            return self.market_option_chain.get_contract_by_id(instrument_id)
        return None

    def get_option_chain(self, underlying_code, chain_type="standard"):
        """
        获取指定标的的期权链
        :param underlying_code: 标的代码
        :param chain_type: 链类型 ('standard' 或 'non_standard')
        :return: OptionChain对象
        """
        if self.market_option_chain:
            return self.market_option_chain.get_option_chain(
                underlying_code, chain_type
            )
        return None

    def get_all_underlying_codes(self):
        """获取所有标的代码"""
        if self.market_option_chain:
            return self.market_option_chain.get_all_underlying_codes()
        return []

    def get_atm_contracts(
        self, underlying_code, underlying_price, expire_date=None, chain_type="standard"
    ):
        """
        获取平值期权合约
        :param underlying_code: 标的代码
        :param underlying_price: 标的价格
        :param expire_date: 到期日（可选）
        :param chain_type: 链类型
        :return: {'CALL': contract, 'PUT': contract}
        """
        option_chain = self.get_option_chain(underlying_code, chain_type)
        if option_chain:
            return option_chain.get_atm_contracts(underlying_price, expire_date)
        return {}

    def get_contracts_by_expiry(
        self, underlying_code, expire_date, option_type=None, chain_type="standard"
    ):
        """
        根据到期日获取合约列表
        :param underlying_code: 标的代码
        :param expire_date: 到期日
        :param option_type: 期权类型（可选）
        :param chain_type: 链类型
        :return: 合约列表
        """
        option_chain = self.get_option_chain(underlying_code, chain_type)
        if option_chain:
            return option_chain.get_contracts_by_expiry(expire_date, option_type)
        return []

    def get_contracts_by_strike(
        self, underlying_code, strike_price, option_type=None, chain_type="standard"
    ):
        """
        根据行权价获取合约列表
        :param underlying_code: 标的代码
        :param strike_price: 行权价
        :param option_type: 期权类型（可选）
        :param chain_type: 链类型
        :return: 合约列表
        """
        option_chain = self.get_option_chain(underlying_code, chain_type)
        if option_chain:
            return option_chain.get_contracts_by_strike(strike_price, option_type)
        return []

    def get_option_contract_by_moneyness(
        self,
        price,
        moneyness_range,
        monthly,
        undl,
        is_call=True,
        need_higher_strike=True,
        chain_type="standard",
    ):
        """
        使用期权链根据价值度查找期权合约
        :param price: 标的价格
        :param moneyness_range: 价值度范围 [min, max]
        :param monthly: 月份索引
        :param undl: 标的代码
        :param is_call: 是否为看涨期权
        :param need_higher_strike: 是否需要更高的行权价
        :param chain_type: 链类型
        :return: 合约代码字符串或None
        """
        underlying_code = undl.split(".")[0]
        option_chain = self.get_option_chain(underlying_code, chain_type)

        if not option_chain:
            return None

        # 获取所有到期日，按时间排序
        all_expire_dates = sorted(option_chain.get_all_expire_dates())

        if monthly >= len(all_expire_dates):
            return None

        expire_date = all_expire_dates[monthly]
        option_type = "CALL" if is_call else "PUT"

        # 获取指定到期日和期权类型的合约
        contracts = option_chain.get_contracts_by_expiry(expire_date, option_type)

        if not contracts:
            return None

        # 计算价值度并筛选
        valid_contracts = []
        for contract in contracts:
            if is_call:
                moneyness = price / contract.strike_price
            else:
                moneyness = contract.strike_price / price

            if moneyness_range[0] <= moneyness <= moneyness_range[1]:
                valid_contracts.append((contract, moneyness))

        if not valid_contracts:
            return None

        # 按行权价排序
        valid_contracts.sort(key=lambda x: x[0].strike_price)

        # 选择合约
        selected_contract = (
            valid_contracts[-1][0] if need_higher_strike else valid_contracts[0][0]
        )

        return (
            f'{selected_contract.instrument_id}.{selected_contract.data["ExchangeID"]}'
        )

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
        def get_last_max_idx(series):
            """获取分组中最大值对应的最后一个索引"""
            max_val = series.max()
            max_positions = series[series == max_val].index
            return max_positions[-1]  # 返回最后一个最大值的索引

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
        # idx = positions_df.groupby(["instrument_id", "direction"])[
        #     "created"
        # ].idxmax()  # noqa
        idx = positions_df.groupby(["instrument_id", "direction"])["created"].apply(
            get_last_max_idx
        )
        df = positions_df.loc[idx]
        df = df.sort_values(by="created")
        df = df.loc[df["volume"] > 0]
        self.positions = df.reset_index(drop=True)

        # 如果当天是交易日，却没有持仓记录，则保存最新持仓
        if self.datafeed.trade_calendar.is_trade_date(today) and (
            self.positions.empty or self.positions.iloc[0]["created"].date() != today
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
                row["commission"],
                self.strategy.user_id,
            )

    def open(
        self,
        instrument_id,
        instrument_name,
        volume,
        price,
        direction,
        commission,  # noqa
    ):
        self.positions = self.positions.reset_index(drop=True)
        if not self.positions.empty:
            mask = (self.positions["instrument_id"] == instrument_id) & (
                self.positions["direction"] == direction
            )
            idxs = np.where(mask)[0]
        else:
            idxs = []
        if len(idxs) == 0:
            # 新增持仓
            new_position = {
                "instrument_id": instrument_id,
                "instrument_name": instrument_name,
                "direction": direction,
                "volume": volume,
                "open_price": price,
                "commission": commission * volume,
                # "created": now,
            }
            if not self.positions.empty:
                self.positions.loc[len(self.positions)] = new_position
            else:
                self.positions = pd.DataFrame([new_position])
            save_volume = volume
            save_price = price
            save_commission = commission * volume
        else:
            idx = idxs[0].item()
            old_volume = self.positions.at[idx, "volume"].item()
            old_price = self.positions.at[idx, "open_price"].item()
            old_commission = self.positions.at[idx, "commission"].item()
            new_volume = old_volume + volume
            new_commission = old_commission + commission * volume
            # 加权均价
            new_price = (old_price * old_volume + price * volume) / new_volume
            self.positions.at[idx, "volume"] = new_volume
            self.positions.at[idx, "open_price"] = new_price
            self.positions.at[idx, "commission"] = new_commission
            # self.positions.at[idx, "created"] = now
            save_volume = new_volume
            save_price = new_price
            save_commission = new_commission
        # 保存到数据库
        self.datafeed.save_strategy_position(
            self.strategy.strategy_id,
            instrument_id,
            instrument_name,
            direction,
            save_volume,
            save_price,
            save_commission,
            self.strategy.user_id,
        )

    def close(
        self,
        instrument_id,
        instrument_name,
        volume,
        price,
        direction,
        commission,  # noqa
    ):
        self.positions = self.positions.reset_index(drop=True)
        mask = (self.positions["instrument_id"] == instrument_id) & (
            self.positions["direction"] == direction
        )
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            # 没有持仓，直接返回或抛异常
            return
        idx = idxs[0].item()
        old_volume = self.positions.at[idx, "volume"].item()
        old_commission = self.positions.at[idx, "commission"].item()
        old_price = self.positions.at[idx, "open_price"].item()
        new_volume = old_volume - volume
        new_commission = old_commission + commission * volume
        if new_volume > 0:
            # 移动加权平均法调整剩余均价
            new_price = (old_price * old_volume - price * volume) / new_volume
            self.positions.at[idx, "volume"] = new_volume
            self.positions.at[idx, "open_price"] = new_price
            self.positions.at[idx, "commission"] = new_commission
            save_volume = new_volume
            save_price = new_price
            save_commission = new_commission
        else:
            # 平完仓，删除该行
            self.positions = self.positions.drop(idx).reset_index(drop=True)
            save_volume = 0
            save_price = (old_price - price) * volume
            save_commission = new_commission
        # 保存到数据库
        self.datafeed.save_strategy_position(
            self.strategy.strategy_id,
            instrument_id,
            instrument_name,
            direction,
            save_volume,
            save_price,
            save_commission,
            self.strategy.user_id,
        )

    def get_active_symbols(self):
        """获取当前持仓的标的"""
        if self.positions.empty:
            return []
        return self.positions["instrument_id"].unique().tolist()

    def get_open_price(self, symbol):

        return self.positions.loc[self.positions["instrument_id"] == symbol][
            "open_price"
        ].item()

    def get_volume(self, symbol):
        pos = self.positions.loc[self.positions["instrument_id"] == symbol]
        if pos.empty:
            return 0
        if len(pos) == 1:
            return pos["volume"].item()
        else:
            return pos["volume"].sum().item()

    def get_commission(self, symbol):
        pos = self.positions.loc[self.positions["instrument_id"] == symbol]
        if pos.empty:
            return 0
        return pos["commission"].item()


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
                self.strategy.user_id,
            )

    def release(self, instrument_id, instrument_name, volume):
        if self.combinations.empty:
            return

        existing_combination = self.combinations[
            self.combinations["instrument_id"] == instrument_id
        ]
        if existing_combination.empty:
            return
        existing_combination_volume = int(
            existing_combination.iloc[0]["volume"]
        )  # noqa
        new_volume = existing_combination_volume - volume
        self.combinations.loc[existing_combination.index[0], "volume"] = (
            new_volume  # noqa
        )
        self.datafeed.save_strategy_combinations(
            self.strategy.strategy_id,
            instrument_id,
            instrument_name,
            new_volume,
            self.strategy.user_id,
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
                self.strategy.user_id,
            )
        else:
            existing_combination_volume = int(
                existing_combination.iloc[0]["volume"]
            )  # noqa
            new_volume = existing_combination_volume + volume
            self.combinations.loc[existing_combination.index[0], "volume"] = (
                new_volume  # noqa
            )
            self.datafeed.save_strategy_combinations(
                self.strategy.strategy_id,
                instrument_id,
                instrument_name,
                new_volume,
                self.strategy.user_id,
            )

    def get_combs_profit_info(self):
        info = []
        for _, row in self.combinations.iterrows():
            pair = row["instrument_id"].split("/")
            pos = self.strategy.strategy_account.positions[
                self.strategy.strategy_account.positions["instrument_id"].isin(pair)
            ]
            if len(pos) == 2:
                pos = pos.sort_values(
                    by="direction", ascending=False
                )  # 如果是价差组合，确保买方在前面
                profit = (
                    (pos["price"] - pos["open_price"])
                    * pos["direction"]
                    * row["volume"]
                )
                profit = profit.sum() * pos.iloc[0]["vol_mul"].item()
                info.append(
                    {
                        "code_1": f"{pos.iloc[0]['instrument_id']}.{pos.iloc[0]['exchange_id']}",
                        "code_2": f"{pos.iloc[1]['instrument_id']}.{pos.iloc[1]['exchange_id']}",
                        "profit": profit,
                        "volume": row["volume"],
                    }
                )
        if len(info) == 0:
            return pd.DataFrame()
        return pd.DataFrame(info)


class StrategyAccount:
    def __init__(self, strategy):
        self.strategy = strategy
        self.datafeed = strategy.datafeed
        self.account = {}
        self.positions = None

    def refresh(self):
        account = self.datafeed.get_strategy_account(self.strategy.strategy_id)
        if account is not None:
            self.account = {
                "margin": account.margin,
                "available_margin": account.available_margin,
                "init_cash": account.init_cash,
                "profit": account.profit,
                "delta": account.delta,
                "gamma": account.gamma,
                "vega": account.vega,
                "theta": account.theta,
                "rho": account.rho,
            }
        self.set_last_account()

    def adjust_margin_by_comb(self, opt_type="BOTH"):
        if self.positions is None:
            return 0
        if opt_type == "BOTH":
            total_margin = self.positions["margin"].sum()
        elif opt_type == "CALL":
            total_margin = self.positions[self.positions["opt_type"] == "CALL"][
                "margin"
            ].sum()
        elif opt_type == "PUT":
            total_margin = self.positions[self.positions["opt_type"] == "PUT"][
                "margin"
            ].sum()
        else:
            raise ValueError(f"Invalid option type: {opt_type}")
        if total_margin is None:
            total_margin = 0
        else:
            total_margin = total_margin.item()

        combinations = self.strategy.strategy_combinations.combinations
        for _, row in combinations.iterrows():
            pair = row["instrument_id"].split("/")
            pos = self.positions[self.positions["instrument_id"].isin(pair)]
            pos = pos.sort_values(by="direction", ascending=False)

            if len(pos) == 2:
                if opt_type != "BOTH" and pos["opt_type"].iloc[0] != opt_type:
                    continue
                if pos["direction"].prod() < 0:  # 价差组合
                    diff = abs(pos["strike"].diff().iloc[1]) * pos["vol_mul"].iloc[0]
                    if (
                        pos["opt_type"].iloc[0] == "CALL"
                        and pos["strike"].iloc[0] < pos["strike"].iloc[1]
                    ) or (
                        pos["opt_type"].iloc[0] == "PUT"
                        and pos["strike"].iloc[0] > pos["strike"].iloc[1]
                    ):
                        comb_margin = 0
                    else:
                        comb_margin = abs(diff * row["volume"] * 1.06)
                    old_margin = pos["margin"] / pos["volume"] * row["volume"]
                    old_margin = old_margin.sum()
                    total_margin = total_margin + comb_margin - old_margin
                if pos["direction"].prod() > 0:  # 跨式或宽跨式组合
                    comb_margin = (pos["margin"] / pos["volume"]).max() + (
                        pos["price"] / pos["volume"]
                    ).min()
                    comb_margin = comb_margin * row["volume"]  # noqa
                    total_margin = total_margin + (comb_margin - pos["margin"].sum())
        return total_margin

    def get_month_margin(self, month, opt_type="BOTH"):
        """
        返回指定月度、指定合约类型的保证金（float）
        :param month: 月度（int）
        :param opt_type: "BOTH"/"CALL"/"PUT"
        :return: float
        """
        margin_total = 0.0
        if self.positions is None:
            return margin_total
        for idx, row in self.positions.iterrows():
            if opt_type != "BOTH" and row["opt_type"] != opt_type:
                continue
            info = self.datafeed.get_contract_info(row["instrument_id"])
            if info is None or info["monthly"] != month:
                continue
            margin = row["margin"] if not pd.isna(row["margin"]) else 0
            margin_total += margin

        combinations = self.strategy.strategy_combinations.combinations
        for _, comb_row in combinations.iterrows():
            pair = comb_row["instrument_id"].split("/")
            pos = self.positions[self.positions["instrument_id"].isin(pair)]
            pos = pos.sort_values(by="direction", ascending=False)
            if len(pos) == 2:
                info0 = self.datafeed.get_contract_info(pos.iloc[0]["instrument_id"])
                comb_month = info0["monthly"] if info0 else None
                if comb_month != month:
                    continue
                if opt_type != "BOTH" and pos["opt_type"].iloc[0] != opt_type:
                    continue
                if pos["direction"].prod() < 0:  # 价差组合
                    diff = abs(pos["strike"].diff().iloc[1]) * pos["vol_mul"].iloc[0]
                    if (
                        pos["opt_type"].iloc[0] == "CALL"
                        and pos["strike"].iloc[0] < pos["strike"].iloc[1]
                    ) or (
                        pos["opt_type"].iloc[0] == "PUT"
                        and pos["strike"].iloc[0] > pos["strike"].iloc[1]
                    ):
                        comb_margin = 0
                    else:
                        comb_margin = abs(diff * comb_row["volume"] * 1.06)
                    old_margin = pos["margin"] / pos["volume"] * comb_row["volume"]
                    old_margin = old_margin.sum()
                    margin_total += comb_margin - old_margin
                if pos["direction"].prod() > 0:  # 跨式或宽跨式组合
                    comb_margin = (pos["margin"] / pos["volume"]).max() + (
                        pos["price"] / pos["volume"]
                    ).min()
                    comb_margin = comb_margin * comb_row["volume"]  # noqa
                    margin_total += comb_margin - pos["margin"].sum()
        return margin_total

    def set_last_account(self):
        def reset_account():
            if self.account != {}:
                self.account = {
                    "margin": 0,
                    "available_margin": self.account["available_margin"]
                    + self.account["margin"],
                    "init_cash": self.account["init_cash"],
                    "profit": self.account["profit"],
                    "delta": 0,
                    "gamma": 0,
                    "vega": 0,
                    "theta": 0,
                    "rho": 0,
                }
                self.save()

        def calcuate_greeks(positions, risks):

            # 按合约计算卖方保证金
            positions["per_margin"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["margin"] for risk in risks}
            )
            positions["margin"] = 0
            positions.loc[positions["direction"] == -1, "margin"] = (
                positions["per_margin"] * positions["volume"]
            )

            # 计算delta
            positions["per_delta"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["delta"] for risk in risks}
            )
            positions["delta"] = (
                positions["per_delta"] * positions["volume"] * positions["direction"]
            )

            # 计算gamma
            positions["per_gamma"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["gamma"] for risk in risks}
            )
            positions["gamma"] = (
                positions["per_gamma"] * positions["volume"] * positions["direction"]
            )

            # 计算vega
            positions["per_vega"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["vega"] for risk in risks}
            )
            positions["vega"] = (
                positions["per_vega"] * positions["volume"] * positions["direction"]
            )

            # 计算theta
            positions["per_theta"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["theta"] for risk in risks}
            )
            positions["theta"] = (
                positions["per_theta"] * positions["volume"] * positions["direction"]
            )

            # 计算pho
            positions["per_rho"] = positions["instrument_id"].map(
                {risk["instrument_id"]: risk["rho"] for risk in risks}
            )
            positions["rho"] = (
                positions["per_rho"] * positions["volume"] * positions["direction"]
            )
            del positions["per_margin"]
            del positions["per_delta"]
            del positions["per_gamma"]
            del positions["per_vega"]
            del positions["per_theta"]
            del positions["per_rho"]
            return positions

        def get_option_details(id):
            """统一获取期权行权价和乘数"""
            try:
                contract = self.datafeed.get_option_contract_by_id(id)
                if contract is not None:
                    return pd.Series(
                        {
                            "strike": contract.data["OptExercisePrice"],
                            "vol_mul": contract.data["VolumeMultiple"],
                            "opt_type": contract.data["OptType"],
                            "exchange_id": contract.data["ExchangeID"],
                        }
                    )
                else:
                    return pd.Series(
                        {
                            "strike": None,
                            "vol_mul": None,
                            "opt_type": None,
                            "exchange_id": None,
                        }
                    )
            except Exception:
                return pd.Series(
                    {
                        "strike": None,
                        "vol_mul": None,
                        "opt_type": None,
                        "exchange_id": None,
                    }
                )

        def create_positions():
            symbols = self.strategy.strategy_positions.get_active_symbols()
            risks = self.datafeed.calculate_risk(symbols)
            if risks is None:
                return
            positions = self.strategy.strategy_positions.positions.copy()
            if positions.empty:
                reset_account()
                return
            positions = calcuate_greeks(positions, risks)
            price_dict = {
                item["instrument_id"]: item["price"] for item in risks
            }  # noqa
            positions["price"] = positions["instrument_id"].map(price_dict)  # noqa
            positions[["strike", "vol_mul", "opt_type", "exchange_id"]] = positions[
                "instrument_id"
            ].apply(get_option_details)

            return positions

        if self.strategy.strategy_positions is not None:
            self.positions = create_positions()

            # total_margin = self.positions["margin"].sum()
            # total_margin = adjust_margin_by_combinations(total_margin)
            if self.positions is None:
                return
            total_margin = self.adjust_margin_by_comb("BOTH")
            if total_margin is None:
                total_margin = 0

            floating_profit = (
                self.positions["price"] - self.positions["open_price"]
            )  # noqa
            floating_profit = floating_profit * self.positions["volume"]
            floating_profit = floating_profit * self.positions["direction"]
            floating_profit = floating_profit.sum() * 10000

            buyer_position = self.positions[self.positions["direction"] == 1]
            cost = (
                buyer_position["open_price"] * buyer_position["volume"]
            ).sum()  # noqa

            available_margin = (
                self.account["init_cash"]
                + self.account["profit"]
                - total_margin
                - self.positions["commission"].sum()
                - cost
                + floating_profit
            )
            self.account = {
                "margin": total_margin,
                "available_margin": available_margin,
                "init_cash": self.account["init_cash"],
                "profit": self.account["profit"],
                "delta": self.positions["delta"].sum(),
                "gamma": self.positions["gamma"].sum(),
                "vega": self.positions["vega"].sum(),
                "theta": self.positions["theta"].sum(),
                "rho": self.positions["rho"].sum(),
            }

            self.save()

    def save(self):
        self.datafeed.save_strategy_account(
            self.strategy.strategy_id,
            self.account["margin"],
            self.account["available_margin"],
            self.account["init_cash"],
            self.account["profit"],
            self.account["delta"],
            self.account["gamma"],
            self.account["vega"],
            self.account["theta"],
            self.account["rho"],
            self.strategy.user_id,
        )

    def add_profit(self, profit):
        self.account["profit"] = self.account["profit"] + profit

    def adjust_available_margin(self, value):
        self.account["available_margin"] += value

    def get_uncomb_position2(self, opt_type="CALL", is_seller=True):
        direction = -1 if is_seller else 1
        for _, row in self.strategy.strategy_combinations.combinations.iterrows():
            pair = row["instrument_id"].split("/")
            comb_volume = row["volume"]
            for instrument_id in pair:
                pos = self.positions[self.positions["instrument_id"] == instrument_id]
                if (
                    len(pos) == 1
                    and pos["direction"].item() == direction
                    and pos["opt_type"].item() == opt_type
                ):
                    volume = pos["volume"].item()
                    if volume > comb_volume:
                        return (
                            f'{instrument_id}.{pos["exchange_id"].item()}',
                            volume - comb_volume,
                        )

        if self.positions is not None:
            for _, row in self.positions.iterrows():
                if row["direction"] == direction and row["opt_type"] == opt_type:
                    return row["instrument_id"], row["volume"]
        return None, None

    def get_uncomb_position(self, opt_type="CALL", is_seller=True):
        """
        返回未构成组合的符合条件的合约及数量

        Args:
            opt_type (str): 期权类型，"CALL" 或 "PUT"
            is_seller (bool): 是否是卖方，True表示卖方(-1方向)，False表示买方(1方向)

        Returns:
            tuple: (合约代码, 未组合数量) 或 (None, None)
        """
        if self.positions is None or self.positions.empty:
            return None, None

        direction = -1 if is_seller else 1

        # 筛选符合条件的持仓
        filtered_positions = self.positions[
            (self.positions["direction"] == direction)
            & (self.positions["opt_type"] == opt_type)
        ]

        if filtered_positions.empty:
            return None, None

        # 对每个符合条件的持仓，计算其参与组合的总量
        for _, pos_row in filtered_positions.iterrows():
            instrument_id = pos_row["instrument_id"]
            total_volume = pos_row["volume"]

            # 计算该合约参与组合的总量
            combined_volume = 0
            if (
                hasattr(self.strategy, "strategy_combinations")
                and self.strategy.strategy_combinations is not None
                and not self.strategy.strategy_combinations.combinations.empty
            ):

                for (
                    _,
                    comb_row,
                ) in self.strategy.strategy_combinations.combinations.iterrows():
                    # 组合的instrument_id格式为 "symbol1/symbol2"
                    pair = comb_row["instrument_id"].split("/")
                    instrument_name = comb_row["instrument_name"]

                    # 判断组合中成份合约的方向
                    if "价差" in instrument_name:
                        # 价差组合：pair[0]方向是1(买方)，pair[1]方向是-1(卖方)
                        if instrument_id == pair[0] and direction == 1:
                            combined_volume += comb_row["volume"]
                        elif instrument_id == pair[1] and direction == -1:
                            combined_volume += comb_row["volume"]
                    else:
                        # 非价差组合：pair[0]和pair[1]方向都是-1(卖方)
                        if instrument_id in pair and direction == -1:
                            combined_volume += comb_row["volume"]

            # 计算未组合的数量
            uncombined_volume = total_volume - combined_volume

            if uncombined_volume > 0:
                # 构造完整的合约代码
                exchange_id = pos_row.get("exchange_id", "")
                if exchange_id:
                    symbol = f"{instrument_id}.{exchange_id}"
                else:
                    symbol = instrument_id
                return symbol, uncombined_volume

        return None, None

    def get_vertical_comb_profit(self, comb_id, volume):
        if self.positions is None:
            self.set_last_account()

        positions = self.positions
        code_1, code_2 = comb_id.split("/")
        pos_1 = positions.loc[
            (positions["direction"] == 1) & (positions["instrument_id"] == code_1)
        ]
        pos_2 = positions.loc[
            (positions["direction"] == -1) & (positions["instrument_id"] == code_2)
        ]

        profit = (pos_1["price"] - pos_1["open_price"]).item() * volume + (
            pos_2["open_price"] - pos_2["price"]
        ).item() * volume

        return profit

    def get_vertical_comb_open_spead(self, comb_id, volume):
        if self.positions is None:
            self.set_last_account()
        positions = self.positions
        code_1, code_2 = comb_id.split("/")
        pos_1 = positions.loc[
            (positions["direction"] == 1) & (positions["instrument_id"] == code_1)
        ].iloc[0]
        pos_2 = positions.loc[
            (positions["direction"] == -1) & (positions["instrument_id"] == code_2)
        ].iloc[0]

        spread = (
            pos_1["open_price"] * pos_1["direction"]
            + pos_2["open_price"] * pos_2["direction"]
        ) * volume
        spread = -spread
        return spread
