import threading
import pandas as pd
import time
import json
from abc import ABC, abstractmethod
from datetime import datetime
from queue import Queue
from utils.logger import log
from utils.common import DataFrameWrapper, record2dataframe
from utils.trade_calendar import TradeCalendar
import numpy as np


class BaseStrategy(ABC):
    def __init__(self, datafeed, strategy_id, name, params):
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
            self._update_strategy_info(deal_info)
            self.on_deal(deal_info)
            time.sleep(0.1)

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

            # 处理K线数据
            symbol, period, bar = (
                self._queue.get()
            )  # 这里可以保持阻塞，因为K线是按周期产生的
            self.bars._df.loc[len(self.bars._df)] = bar
            self.bars._df = self.bars._df.tail(self.min_bars_count)
            self.bars._df = self.bars._df.reset_index(drop=True)
            self.on_bar(symbol, period, bar)

        # except Exception as e:
        #     log(f"策略 {self.name} 执行出错: {str(e)}", "error")
        #     raise

    def set_user(self, user_id):
        self.user_id = user_id

    def _trade(self, command_id, symbol, volume):
        data = {
            "opType": command_id,  # 50：买入开仓 51：卖出平仓 52：卖出开仓  53：买入平仓
            "orderType": 1101,
            "orderCode": symbol,
            "prType": 14,
            "price": -1,
            "volume": volume,
            "strategyName": self.name,
            "quickTrade": 1,
            "userOrderId": self.strategy_id,
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def buy_open(self, symbol, volume):
        self._trade(50, symbol, volume)

    def buy_close(self, symbol, volume):
        self._trade(53, symbol, volume)

    def sell_open(self, symbol, volume):
        self._trade(52, symbol, volume)

    def sell_close(self, symbol, volume):
        self._trade(51, symbol, volume)

    def cancel(self, task_id):
        data = {
            "orderType": -100,
            "orderCode": task_id,
            "strategyName": self.name,
            "userOrderId": self.strategy_id,
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def make_combination(
        self, comd_type, code_1, is_buyer_1, code_2, is_buyer_2, volume
    ):
        json_obj = {
            f"{code_1}": 48 if is_buyer_1 else 49,
            f"{code_2}": 48 if is_buyer_2 else 49,
        }
        # 准备要插入的数据
        data = {
            "opType": comd_type.value,
            "orderType": -200,
            "orderCode": json.dumps(json_obj),
            "volume": volume,
            "strategyName": self.name,
            "userOrderId": self.strategy_id,
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def release_combination(self, comb_id):
        data = {
            "orderType": -300,
            "orderCode": comb_id,
            "strategyName": self.name,
            "userOrderId": self.strategy_id,
            "user": self.user_id,
            "accountId": self.account_id,
        }
        self.datafeed.create_trade_command(data)

    def close_combination(self, comb_id): ...

    def move_combination(self, comb_id): ...

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
                self.strategy_account.set_last_account()
            elif deal_record.direction == 49:  # 构造组合
                self.strategy_combinations.combine(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                )
                self.strategy_account.set_last_account()
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
                    multi = self.datafeed.get_contract_info(
                        deal_record.instrument_id, "VolumeMultiple"
                    )
                    profit = profit * multi
                    profit = profit - self.strategy_positions.get_commission(
                        deal_record.instrument_id
                    )
                    self.strategy_account.add_profit(profit)

                self.strategy_positions.close(
                    deal_record.instrument_id,
                    deal_record.instrument_name,
                    deal_record.volume,
                    deal_record.price,
                    direction,
                    self.commission,
                )
                self.strategy_account.set_last_account()
            else:
                raise ValueError(f"未知的交易类型: {deal_record}")

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

    @property
    def option_contracts(self):
        if self.instruments is None or self.instruments.empty:
            self.instruments = self.load_last_option_contracts()
            return self.instruments
        else:
            date = self.instruments.iloc[0]["Date"]
            if date != datetime.now().date():
                self.instruments = self.load_last_option_contracts()
            return self.instruments

    def get_contract_info(self, instrument_id, column_name):
        contract = self.option_contracts.loc[
            self.option_contracts["InstrumentID"] == instrument_id
        ]
        if contract.empty:
            return None
        return contract.iloc[0][column_name].item()

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
        idx = positions_df.groupby(["instrument_id", "direction"])[
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
                row["commission"],
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
        return pos["volume"].item()

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
            )


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

    def set_last_account(self):
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

        def get_element_from_risks(risks, instrument_id):
            for risk in risks:
                if risk["instrument_id"] == instrument_id:
                    return risk
            return None

        def adjust_margin_by_combinations(init_margin):
            total_margin = init_margin
            combinations = self.strategy.strategy_combinations.combinations
            for _, row in combinations.iterrows():
                pair = row["instrument_id"].split("/")
                strikes = list(
                    map(
                        lambda x: self.datafeed.option_contracts.loc[
                            self.datafeed.option_contracts["InstrumentID"] == x
                        ],
                        pair,
                    )
                )

                if len(strikes) == 2:
                    strike_1 = strikes[0]["OptExercisePrice"].item()
                    strike_2 = strikes[1]["OptExercisePrice"].item()
                    delta_1 = get_element_from_risks(risks, pair[0])["delta"]
                    delta_2 = get_element_from_risks(risks, pair[1])["delta"]
                    if delta_1 * delta_2 > 0:  # 价差组合
                        diff = (strike_1 - strike_2) * strikes[0][
                            "VolumeMultiple"
                        ].item()
                        if (delta_1 > 0 and strike_1 > strike_2) or (
                            delta_1 < 0 and strike_1 < strike_2
                        ):  # 认购牛市或认沽熊市
                            comb_margin = 0
                        else:  # 认购熊市或认沽牛市
                            comb_margin = abs(diff * row["volume"] * 1.06)
                        old_margin = (
                            get_element_from_risks(risks, pair[0])["margin"]
                            * row["volume"]
                        )
                        total_margin = total_margin + comb_margin - old_margin
                    elif delta_1 * delta_2 < 0:  # 跨式或宽跨式组合
                        margin_1 = get_element_from_risks(risks, pair[0])[
                            "margin"
                        ]  # noqa
                        margin_2 = get_element_from_risks(risks, pair[1])[
                            "margin"
                        ]  # noqa
                        price_1 = get_element_from_risks(risks, pair[0])[
                            "price"
                        ]  # noqa
                        price_2 = get_element_from_risks(risks, pair[1])[
                            "price"
                        ]  # noqa
                        comb_margin = max(margin_1, margin_2) + min(
                            price_1, price_2
                        )  # noqa
                        total_margin = (
                            total_margin
                            + (comb_margin - margin_1 - margin_2)
                            * row["volume"]  # noqa
                        )
                    else:
                        log(f"未知的组合类型: {row['instrument_name']}", "error")
            return total_margin

        if self.strategy.strategy_positions is not None:
            symbols = self.strategy.strategy_positions.get_active_symbols()
            risks = self.datafeed.calcuate_risk(symbols)
            positions = self.strategy.strategy_positions.positions.copy()
            if positions.empty:
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
                return
            self.positions = calcuate_greeks(positions, risks)
            price_dict = {
                item["instrument_id"]: item["price"] for item in risks
            }  # noqa
            self.positions["price"] = self.positions["instrument_id"].map(
                price_dict
            )  # noqa

            total_margin = self.positions["margin"].sum()
            total_margin = adjust_margin_by_combinations(total_margin)
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
        )

    def add_profit(self, profit):
        self.account["profit"] = self.account["profit"] + profit
