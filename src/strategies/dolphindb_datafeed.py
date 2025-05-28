import dolphindb as ddb
import pandas as pd
from datetime import time, datetime
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
        df = df.loc[df["datetime"].dt.time >= time(9, 30, 0)]
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
            select * from loadTable("{self.market_db_config["DB_NAME"]}", "{self.market_db_config["OPTION_CONTRACT_TABLE"]}")
            where date = (select max(date) from loadTable("{self.market_db_config["DB_NAME"]}", "{self.market_db_config["OPTION_CONTRACT_TABLE"]}"))
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
                "filter": f'strategy="{strategy_id}" && created >= "{query_date}"  && volume>0'  # noqa
            },  # noqa
        )
        if len(records) == 0:
            return []
        return records

    def get_combinations_positions(self, strategy_id, query_date=datetime.now().date()):
        records = self.client.collection("strategyCombinations").get_full_list(
            -1,
            {
                "filter": f'strategy="{strategy_id}" && created >= "{query_date}" && volume>0'
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
            }
        )

    def save_strategy_combinations(
        self,
        strategy_id,
        instrument_id,
        instrument_name,
        volume,
    ):
        self.client.collection("strategyCombinations").create(
            {
                "strategy": strategy_id,
                "instrumentId": instrument_id,
                "instrumentName": instrument_name,
                "volume": volume,
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
            }
        )

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

    def calcuate_risk(self, symbols):
        # 从instruments中获取所有相关合约和标的的信息
        contracts = {}
        underlying_symbols = set()

        for symbol in symbols:
            contract = self.option_contracts.loc[
                self.option_contracts["InstrumentID"] == symbol
            ]
            if contract.empty:
                continue
            contracts[f'{symbol}.{contract["ExchangeID"].item()}'] = contract
            underlying_symbols.add(
                f"{contract['OptUndlCode'].item()}.{contract['OptUndlMarket'].item()}"
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
                    == f"{contract['OptUndlCode'].item()}.{contract['OptUndlMarket'].item()}"
                ),
                None,
            )

            if not contract_tick or not underlying_tick:
                continue

            # 计算保证金
            margin = calculate_margin(
                option_type=contract["OptType"].item()[0].lower(),
                market_price=contract_tick["lastPrice"],
                underlying_price=underlying_tick["lastPrice"],
                strike_price=contract["OptExercisePrice"].item(),
                contract_multiplier=contract["VolumeMultiple"].item(),
            )

            # 计算剩余天数
            days_to_expiry = (
                parse(str(contract["ExpireDate"].item())).date() - datetime.now().date()
            ).days + 1

            # 计算希腊字母值
            greeks = calculate_iv_and_greeks(
                market_price=contract_tick["lastPrice"],
                underlying_price=underlying_tick["lastPrice"],
                strike_price=contract["OptExercisePrice"].item(),
                t_days=days_to_expiry,
                r=0.0,  # 假设无风险利率为3%
                option_type=contract["OptType"].item()[0].lower(),
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
