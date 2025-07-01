import dolphindb as ddb
import pandas as pd
from datetime import time, datetime, timezone
from time import sleep
from dateutil.parser import parse
from .base import BaseDataFeed
from utils.common import generate_action_name
from utils.option import calculate_iv_and_greeks, calculate_margin


class DolphinDBDataFeed(BaseDataFeed):

    def __init__(self, history_db_config, market_db_config, client):
        super().__init__()
        self.history_db_config = history_db_config
        self.market_db_config = market_db_config
        self.instruments = None
        self.conn = None
        self.handler_id = generate_action_name(6)
        self.client = client

    def load_history_minute_bars(self, symbol, count, period=1):
        conn = ddb.session()
        conn.connect(
            self.history_db_config["DB_HOST"],
            self.history_db_config["DB_PORT"],
            self.history_db_config["DB_USER"],
            self.history_db_config["DB_PASSWORD"],
        )
        if period == 1:
            sql = f"""
                select datetime,open,high,low,close,volume,amount
                from loadTable("{self.history_db_config["DB_NAME"]}", "{self.history_db_config["BAR_TABLE"]}")
                where symbol = '{symbol}'
                order by datetime desc
                limit {count}
            """
        else:
            sql = f"""
                select first(open) as open, max(high) as high, min(low) as low,
                last(close) as close,
                sum(volume) as volume , sum(amount) as amount
                from loadTable("{self.history_db_config["DB_NAME"]}", "{self.history_db_config["BAR_TABLE"]}")
                where symbol = '{symbol}'
                group by bar(datetime, {period}m) as datetime
                order by datetime desc
                limit {count}
            """
        df = conn.run(sql)
        df = df.sort_values(by="datetime", ascending=True)
        df = df.reset_index(drop=True)
        conn.close()
        return df

    def load_active_minute_bars(self, symbol, period=1):
        conn = ddb.session()
        conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        if period == 1:
            sql = f"""
                select datetime,open,high,low,close,volume,amount
                from {self.market_db_config["STREAM_BAR_TABLE"]}
                where symbol = '{symbol}'
                order by datetime
            """
        else:
            sql = f"""
                select first(open) as open, max(high) as high, min(low) as low,
                last(close) as close,
                sum(volume) as volume , sum(amount) as amount
                from {self.market_db_config["STREAM_BAR_TABLE"]}
                where symbol = '{symbol}'
                group by bar(datetime, {period}m) as datetime
                order by datetime
            """
        df = conn.run(sql)
        df = df.loc[
            df["datetime"].dt.time >= time(9, 30, 0)
        ]  # dolphin提供的时间是utc时间，需要减去8小时
        conn.close()
        return df

    def load_option_contracts(self, date):
        conn = ddb.session()
        conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        sql = f"""
            select * from loadTable("{self.market_db_config["DB_NAME"]}", "{self.market_db_config["OPTION_CONTRACT_TABLE"]}")
            where date = {date.strftime("%Y.%m.%d")}
        """
        df = conn.run(sql)
        conn.close()
        return df

    def load_last_option_contracts(self):
        conn = ddb.session()
        conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        sql = f"""
            select * from loadTable("{self.market_db_config["DB_NAME"]}", "instruments")
            where date = (select max(date) from loadTable("{self.market_db_config["DB_NAME"]}", "instruments"))
        """
        df = conn.run(sql)
        conn.close()
        return df

    def get_last_tick(self, symbol):
        conn = ddb.session()
        conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        sql = f"""
                select *
                from {self.market_db_config["TICK_TABLE"]}
                where symbol = '{symbol}'
                order by time desc limit 1
                """
        df = conn.run(sql)
        conn.close()
        if len(df) == 0:
            return None
        return df.to_dict("records")[0]

    def get_last_ticks(self, symbols):
        conn = ddb.session()
        conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        symbols_str = ",".join([f"'{symbol}'" for symbol in symbols])
        sql = f"""
            SELECT *
            FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY time DESC) AS rn
            FROM tick
            WHERE symbol IN  ({symbols_str})
            ) AS tmp
            WHERE rn = 1
            """
        df = conn.run(sql)
        conn.close()
        if len(df) == 0:
            return None
        return df.to_dict("records")

    def load_bars(self, symbol, count, period=1):
        history_bars = self.load_history_minute_bars(symbol, count, period)
        active_bars = self.load_active_minute_bars(symbol, period)
        df = pd.concat([history_bars, active_bars], ignore_index=True)
        return df

    def start(self):
        self.running = True
        self.conn = ddb.session()
        self.conn.connect(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["DB_USER"],
            self.market_db_config["DB_PASSWORD"],
        )
        self.conn.enableStreaming()
        self.conn.subscribe(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self._on_data_arrived,
            self.market_db_config["STREAM_BAR_TABLE"],
            self.handler_id,
            offset=-1,
            resub=True,
        )

    def stop(self):
        self.running = False
        if self.conn is None:
            return
        self.conn.unsubscribe(
            self.market_db_config["DB_HOST"],
            self.market_db_config["DB_PORT"],
            self.market_db_config["STREAM_BAR_TABLE"],
            actionName=self.handler_id,
        )
        self.conn.close()

    def get_strategy_account(self, strategy_id):
        records = self.client.collection("strategyAccount").get_list(
            1, 20, {"filter": f'strategy="{strategy_id}"', "sort": "-created"}
        )
        if len(records.items) == 0:
            return None
        return records.items[0]

    def get_strategy_positions(
        self, strategy_id, query_date=datetime.now().date()
    ):  # noqa
        query_date = query_date.strftime("%Y-%m-%d")
        records = self.client.collection("strategyPositions").get_full_list(
            -1,
            {
                "filter": f'strategy="{strategy_id}" && created >= "{query_date}"'  # noqa
            },  # noqa
        )
        if len(records) == 0:
            return []
        return records

    def get_combinations_positions(self, strategy_id, query_date=datetime.now().date()):
        records = self.client.collection("strategyCombinations").get_full_list(
            -1,
            {
                "filter": f'strategy="{strategy_id}" && created >= "{query_date}" && volume>0',
                "sort": "-created",
            },
        )
        if len(records) == 0:
            return []
        return records

    def save_strategy_position(
        self,
        strategy_id,
        instrument_id,
        instrument_name,
        direction,
        volume,
        open_price,  # noqa
        commission,
        user_id,
    ):
        self.client.collection("strategyPositions").create(
            {
                "strategy": strategy_id,
                "instrumentId": instrument_id,
                "instrumentName": instrument_name,
                "direction": direction,
                "volume": volume,
                "openPrice": open_price,
                "commission": commission,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "user": user_id,
            }
        )

    def save_strategy_combinations(
        self,
        strategy_id,
        instrument_id,
        instrument_name,
        volume,
        user_id,
    ):
        self.client.collection("strategyCombinations").create(
            {
                "strategy": strategy_id,
                "instrumentId": instrument_id,
                "instrumentName": instrument_name,
                "volume": volume,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "user": user_id,
            }
        )

    def save_strategy_account(
        self,
        strategy_id,
        margin,
        available_margin,
        init_cash,
        profit,
        delta,
        gamma,
        vega,
        theta,
        rho,
        user_id,
    ):
        self.client.collection("strategyAccount").create(
            {
                "strategy": strategy_id,
                "margin": margin,
                "availableMargin": available_margin,
                "initCash": init_cash,
                "profit": profit,
                "delta": delta,
                "gamma": gamma,
                "vega": vega,
                "theta": theta,
                "rho": rho,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
                "user": user_id,
            }
        )

    def create_trade_command(self, data):
        data["created"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.client.collection("tradeCommands").create(data)
        sleep(0.0001)

    def get_last_strategy_positions_date(self, strategy_id):
        records = self.client.collection("strategyPositions").get_list(
            1, 1, {"filter": f'strategy="{strategy_id}"', "sort": "-created"}
        )
        if len(records.items) == 0:
            return None
        return records.items[-1].created.date()

    def get_last_strategy_combinations_date(self, strategy_id):
        records = self.client.collection("strategyCombinations").get_list(
            1, 1, {"filter": f'strategy="{strategy_id}"', "sort": "-created"}
        )
        if len(records.items) == 0:
            return None
        return records.items[-1].created.date()

    def get_available_volume(self, user_id, symbol):
        records = self.client.collection("positions").get_list(
            1,
            1,
            {
                "filter": f'user="{user_id}" && instrumentId="{symbol}"',
                "sort": "-created",
            },
        )
        if len(records.items) == 1:
            return records.items[0].can_use_volume

        return 0

    def _on_data_arrived(self, bar_data):
        symbol = bar_data[1]
        if symbol in self._subscribed_handlers:
            bar_data = {
                "datetime": bar_data[0],
                "open": round(bar_data[2], 3),
                "high": round(bar_data[3], 3),
                "low": round(bar_data[4], 3),
                "close": round(bar_data[5], 3),
                "volume": round(bar_data[6], 3),
                "amount": round(bar_data[7], 3),
            }
            if symbol in self._bars_cache:
                for _, bars in self._bars_cache[symbol].items():
                    bars.append(bar_data)

            for period, handlers in self._subscribed_handlers[symbol].items():
                if period == len(self._bars_cache[symbol][period]):
                    for handler in handlers:
                        bars = self._bars_cache[symbol][period]
                        last_bar = {
                            "datetime": bars[-1]["datetime"],
                            "open": bars[0]["open"],
                            "high": max(bar["high"] for bar in bars),
                            "low": min(bar["low"] for bar in bars),
                            "close": bars[-1]["close"],
                            "volume": sum(bar["volume"] for bar in bars),
                            "amount": sum(bar["amount"] for bar in bars),
                        }
                        handler(symbol, period, last_bar)
                    self._bars_cache[symbol][period] = []

    def calculate_risk(self, symbols):
        symbols = [symbol.split(".")[0] for symbol in symbols]

        # 从instruments中获取所有相关合约和标的的信息
        contracts = {}
        underlying_symbols = set()

        for symbol in symbols:
            contract = self.get_option_contract_by_id(symbol)
            if contract is None:
                continue
            contracts[f'{symbol}.{contract.data["ExchangeID"]}'] = contract
            underlying_symbols.add(
                f"{contract.data['OptUndlCode']}.{contract.data['OptUndlMarket']}"
            )

        if not contracts:
            return None

        # 获取所有合约和标的最新价格
        all_symbols = list(contracts.keys()) + list(underlying_symbols)
        ticks = self.get_last_ticks(all_symbols)
        if not ticks:
            return None

        results = []
        for symbol, contract in contracts.items():
            # 获取合约和标的最新价格
            contract_tick = next((t for t in ticks if t["symbol"] == symbol), None)
            underlying_tick = next(
                (
                    t
                    for t in ticks
                    if t["symbol"]
                    == f"{contract.data['OptUndlCode']}.{contract.data['OptUndlMarket']}"
                ),
                None,
            )

            if not contract_tick or not underlying_tick:
                continue

            # 计算保证金
            margin = calculate_margin(
                option_type=contract.data["OptType"][0].lower(),
                market_price=contract_tick["lastPrice"],
                underlying_price=underlying_tick["lastPrice"],
                strike_price=contract.data["OptExercisePrice"],
                contract_multiplier=contract.data["VolumeMultiple"],
            )

            # 计算剩余天数
            days_to_expiry = (
                parse(str(contract.data["ExpireDate"])).date() - datetime.now().date()
            ).days + 1

            # 计算希腊字母值
            greeks = calculate_iv_and_greeks(
                market_price=contract_tick["lastPrice"],
                underlying_price=underlying_tick["lastPrice"],
                strike_price=contract.data["OptExercisePrice"],
                t_days=days_to_expiry,
                r=0.0,  # 假设无风险利率为3%
                option_type=contract.data["OptType"][0].lower(),
            )

            results.append(
                {
                    "instrument_id": symbol.split(".")[0],
                    "margin": margin * 1.2,  # 券商默认提高保证金20%
                    "delta": greeks["delta"],
                    "gamma": greeks["gamma"],
                    "theta": greeks["theta"],
                    "vega": greeks["vega"],
                    "rho": greeks["rho"],
                    "sigma": greeks["sigma"],
                    "undl_price": underlying_tick["lastPrice"],
                    "price": contract_tick["lastPrice"],
                }
            )

        return results

    def get_comb_records(self, code_1, code_2, user_id):
        code_1 = code_1.split(".")[0]
        code_2 = code_2.split(".")[0]
        records = self.client.collection("combinations").get_full_list(
            -1,
            {
                "filter": f'user="{user_id}" && firstCode="{code_1}" && secondCode="{code_2}"'
            },
        )
        # if len(records) == 0:
        #     # code_1, code_2 = code_2, code_1
        #     records = self.client.collection("combinations").get_full_list(
        #         -1,
        #         {
        #             "filter": f'user="{user_id}" && firstCode="{code_2}" && secondCode="{code_1}"'
        #         },
        #     )
        #     if len(records) == 0:
        #         return None

        return records

    def get_comb_info(self, code_1, code_2, user_id):
        records = self.get_comb_records(code_1, code_2, user_id)
        if records is None:
            return None
        record = records[0]

        return {
            record.first_code: record.first_code_pos_type,
            record.second_code: record.second_code_pos_type,
            "exchange_id": record.exchange_id,
        }

    def get_strike(self, instrument_id):
        contract = self.get_option_contract_by_id(instrument_id.split(".")[0])
        if contract is not None:
            return contract.data["OptExercisePrice"], contract.data["OptType"]
        return None, None

    # 策略状态持久化相关方法
    def save_strategy_state_to_db(
        self, strategy_id, user_id, strategy_name, state_data, version
    ):
        """
        保存策略状态到数据库

        Args:
            strategy_id (str): 策略ID
            user_id (str): 用户ID
            strategy_name (str): 策略名称
            state_data (str): JSON格式的状态数据
            version (int): 版本号

        Returns:
            bool: 保存是否成功
        """
        try:
            save_data = {
                "user": user_id,
                "strategy": strategy_id,
                "state_data": state_data,
                "version": version,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
            }

            # 使用PocketBase客户端保存数据
            self.client.collection("strategyStates").create(save_data)
            return True

        except Exception as e:
            from utils.logger import log

            log(f"保存策略状态到数据库失败: {str(e)}", "error")
            return False

    def load_strategy_state_from_db(self, strategy_id, user_id):
        """
        从数据库加载策略状态

        Args:
            strategy_id (str): 策略ID
            user_id (str): 用户ID

        Returns:
            dict: 状态数据，如果没有找到则返回None
        """
        try:
            records = self.client.collection("strategyStates").get_list(
                1,
                1,
                {
                    "filter": f'strategy="{strategy_id}" && user="{user_id}"',
                    "sort": "-created",
                },
            )

            if len(records.items) > 0:
                record = records.items[0]
                return {
                    "state_data": record.state_data,
                    "last_updated": record.updated,
                    "version": getattr(record, "version", 0),
                }
            else:
                return None

        except Exception as e:
            from utils.logger import log

            log(f"从数据库加载策略状态失败: {str(e)}", "error")
            return None

    def delete_strategy_state_from_db(self, strategy_id, user_id):
        """
        从数据库删除策略状态

        Args:
            strategy_id (str): 策略ID
            user_id (str): 用户ID

        Returns:
            bool: 删除是否成功
        """
        try:
            records = self.client.collection("strategyStates").get_list(
                1, 50, {"filter": f'strategy="{strategy_id}" && user="{user_id}"'}
            )

            for record in records.items:
                self.client.collection("strategyStates").delete(record.id)

            return True

        except Exception as e:
            from utils.logger import log

            log(f"从数据库删除策略状态失败: {str(e)}", "error")
            return False

    def get_strategy_state_history(self, strategy_id, user_id, limit=10):
        """
        获取策略状态历史记录

        Args:
            strategy_id (str): 策略ID
            user_id (str): 用户ID
            limit (int): 返回记录数量限制

        Returns:
            list: 历史记录列表
        """
        try:
            records = self.client.collection("strategyStates").get_list(
                1,
                limit,
                {
                    "filter": f'strategy="{strategy_id}" && user="{user_id}"',
                    "sort": "-created",
                },
            )

            history = []
            for record in records.items:
                history.append(
                    {
                        "id": record.id,
                        "state_data": record.state_data,
                        "last_updated": record.updated,
                        "version": getattr(record, "version", 0),
                        "created": record.created,
                    }
                )

            return history

        except Exception as e:
            from utils.logger import log

            log(f"获取策略状态历史失败: {str(e)}", "error")
            return []
