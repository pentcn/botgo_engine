from enum import IntEnum
from py_vollib.black_scholes import implied_volatility
from py_vollib.black_scholes.greeks import analytical
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime


def calculate_margin(
    option_type: str,
    market_price: float,
    underlying_price: float,
    strike_price: float,
    contract_multiplier: int = 10000,
    margin_coeff: float = 0.12,
    min_coeff: float = 0.07,
) -> float:
    """
    计算ETF期权卖方保证金
    :param option_type: 期权类型，'c'（认购）或'p'（认沽）
    :param market_price: 合约前结算价（元/份）
    :param underlying_price: 标的收盘价（元）
    :param strike_price: 行权价格（元）
    :param contract_multiplier: 合约单位，默认10000
    :param margin_coeff: 保证金系数，默认0.12（12%）
    :param min_coeff: 最低保障系数，默认0.07（7%）
    :return: 保证金金额（元）
    """
    if option_type.lower() == "c":
        # 计算认购期权虚值额
        out_value = max(strike_price - underlying_price, 0) * contract_multiplier
        # 保证金计算公式
        part_a = underlying_price * contract_multiplier * margin_coeff - out_value
        part_b = underlying_price * contract_multiplier * min_coeff
    elif option_type.lower() == "p":
        # 计算认沽期权虚值额
        out_value = max(underlying_price - strike_price, 0) * contract_multiplier
        # 保证金计算公式
        part_a = strike_price * contract_multiplier * margin_coeff - out_value
        part_b = strike_price * contract_multiplier * min_coeff
    else:
        raise ValueError("无效的期权类型，请使用'c'或'p'")
    max_part = max(part_a, part_b)
    total_margin = market_price * contract_multiplier + max_part
    return round(total_margin, 2)


def calculate_iv_and_greeks(
    market_price: float,
    underlying_price: float,
    strike_price: float,
    t_days: float,  # 剩余时间（天数，自动转为年化）
    r: float,
    option_type: str,
    sigma_guess: float = 0.2,
) -> dict:
    """
    输入期权市场价格，返回隐含波动率和 Greeks 值（Delta/Theta/Vega等）

    Parameters:
    - market_price : 期权市场价格（必须 > 0）
    - underlying_price : 标的价格（正数）
    - strike_price : 行权价（正数）
    - t_days : 剩余时间（天数，例如30天输入30）
    - r : 无风险利率（年化，小数格式，例如5%输入0.05）
    - option_type : 期权类型 ('c'=认购/'p'=认沽)
    - sigma_guess : 初始波动率猜测值（默认0.2）
    Returns:
    - dict 包含 sigma, delta, gamma, theta, vega, rho
    """
    # 1. 输入参数验证
    if option_type not in ("c", "p"):
        raise ValueError("option_type 必须是 'c'（认购）或 'p'（认沽）")
    if (
        underlying_price <= 0
        or strike_price <= 0
        or t_days <= 0
        or r < 0
        or market_price <= 0
    ):
        raise ValueError("标的价格、行权价、剩余时间、利率和市场价必须为正数")
    # 2. 计算隐含波动率
    try:
        t = t_days / 365.0  # 将天数转为年化数值
        sigma = implied_volatility.implied_volatility(
            market_price, underlying_price, strike_price, t, r, option_type
        )
    except ValueError as e:
        raise ValueError(f"隐含波动率计算失败: {e}")
    # 3. 计算 Greeks（使用计算得到的 sigma）
    delta = analytical.delta(option_type, underlying_price, strike_price, t, r, sigma)
    gamma = analytical.gamma(option_type, underlying_price, strike_price, t, r, sigma)
    theta = analytical.theta(option_type, underlying_price, strike_price, t, r, sigma)
    vega = analytical.vega(option_type, underlying_price, strike_price, t, r, sigma)
    rho = analytical.rho(option_type, underlying_price, strike_price, t, r, sigma)
    # 4. 返回结果（保留四位小数）
    return {
        "sigma": round(sigma, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


class OptionCombinationType(IntEnum):
    """期权交易策略枚举"""

    BULL_CALL_SPREAD = 50  # 认购牛市价差策略
    BEAR_PUT_SPREAD = 51  # 认沽熊市价差策略
    BULL_PUT_SPREAD = 52  # 认沽牛市价差策略
    BEAR_CALL_SPREAD = 53  # 认购熊市价差策略
    SHORT_STRADDLE = 54  # 跨式空头
    SHORT_STRANGLE = 55  # 宽跨式空头
    MARGIN_TO_COVERED = 56  # 保证金开仓转备兑开仓
    COVERED_TO_MARGIN = 57  # 备兑开仓转保证金开仓

    @staticmethod
    def get_type_value_by_code(code):
        map_table = {
            "CNSJC": 50,
            "PXSJC": 51,
            "PNSJC": 52,
            "CXSJC": 53,
            "KS": 54,
            "KKS": 55,
            "ZBD": 56,
            "ZXJ": 57,
        }

        return map_table[code]


class OptionContract:
    """期权合约节点"""

    def __init__(self, contract_data: dict):
        self.data = contract_data
        self.instrument_id = contract_data["InstrumentID"]
        self.strike_price = contract_data["OptExercisePrice"]
        self.expire_date = contract_data["ExpireDate"]
        self.option_type = contract_data["OptType"]  # 'CALL' 或 'PUT'

        # 链式结构指针
        self.prev_strike: Optional["OptionContract"] = None  # 前一个行权价合约
        self.next_strike: Optional["OptionContract"] = None  # 后一个行权价合约
        self.prev_expiry: Optional["OptionContract"] = None  # 前一个到期时间合约
        self.next_expiry: Optional["OptionContract"] = None  # 后一个到期时间合约
        self.counterpart: Optional["OptionContract"] = None  # 对手合约


class MarketOptionChain:
    """期权市场链管理器，包含所有品种的期权链"""

    def __init__(self, df: pd.DataFrame):
        """
        初始化市场期权链
        :param df: 包含所有期权合约信息的DataFrame
        """
        self.df = df.copy()
        self.option_chains: Dict[str, Dict[str, "OptionChain"]] = {}
        self._build_chains()

    def _build_chains(self):
        """构建所有品种的期权链"""
        # 按标的代码分组
        grouped = self.df.groupby("OptUndlCode")

        for underlying_code, group_df in grouped:
            self.option_chains[underlying_code] = {}

            # 分离标准合约和非标准合约
            # 假设标准合约的合约单位是10000
            standard_df = group_df[group_df["VolumeMultiple"] == 10000]
            non_standard_df = group_df[group_df["VolumeMultiple"] != 10000]

            # 创建标准合约链
            if not standard_df.empty:
                self.option_chains[underlying_code]["standard"] = OptionChain(
                    standard_df, underlying_code, "standard"
                )

            # 创建非标准合约链
            if not non_standard_df.empty:
                self.option_chains[underlying_code]["non_standard"] = OptionChain(
                    non_standard_df, underlying_code, "non_standard"
                )

    def get_option_chain(
        self, underlying_code: str, chain_type: str = "standard"
    ) -> Optional["OptionChain"]:
        """
        获取指定标的的期权链
        :param underlying_code: 标的代码
        :param chain_type: 链类型 ('standard' 或 'non_standard')
        :return: OptionChain对象
        """
        if underlying_code in self.option_chains:
            return self.option_chains[underlying_code].get(chain_type)
        return None

    def get_all_underlying_codes(self) -> List[str]:
        """获取所有标的代码"""
        return list(self.option_chains.keys())

    def get_contract_by_id(self, instrument_id: str) -> Optional[OptionContract]:
        """根据合约代码获取合约对象"""
        # 首先在各个品种的期权链中查找
        for underlying_code in self.option_chains:
            for chain_type in self.option_chains[underlying_code]:
                option_chain = self.option_chains[underlying_code][chain_type]
                contract = option_chain.get_contract(instrument_id)
                if contract:
                    return contract
        return None


class OptionChain:
    """单个品种的期权链"""

    def __init__(self, df: pd.DataFrame, underlying_code: str, chain_type: str):
        """
        初始化期权链
        :param df: 该品种的期权合约DataFrame
        :param underlying_code: 标的代码
        :param chain_type: 链类型 ('standard' 或 'non_standard')
        """
        self.df = df.copy()
        self.underlying_code = underlying_code
        self.chain_type = chain_type

        # 合约存储
        self.contracts: Dict[str, OptionContract] = {}
        self.strike_chains: Dict[Tuple[str, str], List[OptionContract]] = (
            {}
        )  # (expire_date, option_type) -> contracts
        self.expiry_chains: Dict[Tuple[float, str], List[OptionContract]] = (
            {}
        )  # (strike_price, option_type) -> contracts

        self._build_chain_structure()

    def _build_chain_structure(self):
        """构建链式结构"""
        # 1. 创建所有合约节点
        for _, row in self.df.iterrows():
            contract = OptionContract(row.to_dict())
            self.contracts[contract.instrument_id] = contract

        # 2. 按到期日和期权类型分组，构建行权价链
        grouped_by_expiry = self.df.groupby(["ExpireDate", "OptType"])
        for (expire_date, option_type), group_df in grouped_by_expiry:
            # 按行权价排序
            sorted_contracts = []
            for _, row in group_df.sort_values("OptExercisePrice").iterrows():
                contract = self.contracts[row["InstrumentID"]]
                sorted_contracts.append(contract)

            self.strike_chains[(expire_date, option_type)] = sorted_contracts

            # 建立行权价链的前后关系
            for i in range(len(sorted_contracts)):
                if i > 0:
                    sorted_contracts[i].prev_strike = sorted_contracts[i - 1]
                if i < len(sorted_contracts) - 1:
                    sorted_contracts[i].next_strike = sorted_contracts[i + 1]

        # 3. 构建到期时间链 - 修改后的逻辑，只连接紧邻月份的合约
        # 获取所有到期日，按时间排序
        all_expire_dates = sorted(set(self.df["ExpireDate"]))

        # 为每个行权价和期权类型组合创建到期日映射
        grouped_by_strike = self.df.groupby(["OptExercisePrice", "OptType"])
        for (strike_price, option_type), group_df in grouped_by_strike:
            # 创建到期日到合约的映射
            expire_to_contract = {}
            for _, row in group_df.iterrows():
                contract = self.contracts[row["InstrumentID"]]
                expire_to_contract[contract.expire_date] = contract

            # 按到期日排序存储（只存储实际存在的合约）
            sorted_contracts = []
            for expire_date in all_expire_dates:
                if expire_date in expire_to_contract:
                    sorted_contracts.append(expire_to_contract[expire_date])

            self.expiry_chains[(strike_price, option_type)] = sorted_contracts

            # 建立到期时间链的前后关系 - 只连接紧邻的合约
            for expire_date in all_expire_dates:
                if expire_date not in expire_to_contract:
                    continue

                current_contract = expire_to_contract[expire_date]
                current_idx = all_expire_dates.index(expire_date)

                # 查找紧接着的前一个到期日的合约
                if current_idx > 0:
                    prev_expire_date = all_expire_dates[current_idx - 1]
                    if prev_expire_date in expire_to_contract:
                        current_contract.prev_expiry = expire_to_contract[
                            prev_expire_date
                        ]

                # 查找紧接着的下一个到期日的合约
                if current_idx < len(all_expire_dates) - 1:
                    next_expire_date = all_expire_dates[current_idx + 1]
                    if next_expire_date in expire_to_contract:
                        current_contract.next_expiry = expire_to_contract[
                            next_expire_date
                        ]

        # 4. 建立对手合约关系
        self._build_counterpart_relationships()

    def _build_counterpart_relationships(self):
        """建立对手合约（CALL-PUT）关系"""
        # 按到期日和行权价分组
        grouped = self.df.groupby(["ExpireDate", "OptExercisePrice"])

        for (expire_date, strike_price), group_df in grouped:
            call_contracts = []
            put_contracts = []

            for _, row in group_df.iterrows():
                contract = self.contracts[row["InstrumentID"]]
                if row["OptType"] == "CALL":
                    call_contracts.append(contract)
                elif row["OptType"] == "PUT":
                    put_contracts.append(contract)

            # 建立CALL和PUT的对手关系
            for call_contract in call_contracts:
                for put_contract in put_contracts:
                    call_contract.counterpart = put_contract
                    put_contract.counterpart = call_contract

    def get_contract(self, instrument_id: str) -> Optional[OptionContract]:
        """根据合约代码获取合约"""
        return self.contracts.get(instrument_id)

    def get_contracts_by_expiry(
        self, expire_date: str, option_type: str = None
    ) -> List[OptionContract]:
        """根据到期日获取合约列表"""
        if option_type:
            return self.strike_chains.get((expire_date, option_type), [])
        else:
            # 返回该到期日的所有合约
            call_contracts = self.strike_chains.get((expire_date, "CALL"), [])
            put_contracts = self.strike_chains.get((expire_date, "PUT"), [])
            return call_contracts + put_contracts

    def get_contracts_by_strike(
        self, strike_price: float, option_type: str = None
    ) -> List[OptionContract]:
        """根据行权价获取合约列表"""
        if option_type:
            return self.expiry_chains.get((strike_price, option_type), [])
        else:
            # 返回该行权价的所有合约
            call_contracts = self.expiry_chains.get((strike_price, "CALL"), [])
            put_contracts = self.expiry_chains.get((strike_price, "PUT"), [])
            return call_contracts + put_contracts

    def get_atm_contracts(
        self, underlying_price: float, expire_date: str = None
    ) -> Dict[str, OptionContract]:
        """获取平值期权合约"""
        # 如果没有指定到期日，选择最近的到期日
        if expire_date is None:
            expire_dates = sorted(set(self.df["ExpireDate"]))
            if expire_dates:
                expire_date = expire_dates[0]
            else:
                return {}

        # 找到最接近标的价格的行权价
        strikes = sorted(
            set(self.df[self.df["ExpireDate"] == expire_date]["OptExercisePrice"])
        )
        if not strikes:
            return {}

        atm_strike = min(strikes, key=lambda x: abs(x - underlying_price))

        # 返回该行权价的CALL和PUT合约
        result = {}
        call_contracts = self.get_contracts_by_strike(atm_strike, "CALL")
        put_contracts = self.get_contracts_by_strike(atm_strike, "PUT")

        for contract in call_contracts:
            if contract.expire_date == expire_date:
                result["CALL"] = contract
                break

        for contract in put_contracts:
            if contract.expire_date == expire_date:
                result["PUT"] = contract
                break

        return result

    def get_all_expire_dates(self) -> List[str]:
        """获取所有到期日"""
        return sorted(set(self.df["ExpireDate"]))

    def get_all_strike_prices(self) -> List[float]:
        """获取所有行权价"""
        return sorted(set(self.df["OptExercisePrice"]))

    def get_next_month_contract(
        self, contract: OptionContract
    ) -> Optional[OptionContract]:
        """
        获取指定合约在下一个月份的对应合约
        :param contract: 当前合约
        :return: 下一个月份的对应合约，如果不存在则返回None
        """
        all_expire_dates = self.get_all_expire_dates()
        try:
            current_idx = all_expire_dates.index(contract.expire_date)
            if current_idx < len(all_expire_dates) - 1:
                next_expire_date = all_expire_dates[current_idx + 1]
                # 查找同一行权价和期权类型的下一个月份合约
                next_contracts = self.get_contracts_by_expiry(
                    next_expire_date, contract.option_type
                )
                for next_contract in next_contracts:
                    if next_contract.strike_price == contract.strike_price:
                        return next_contract
            return None
        except ValueError:
            return None

    def get_prev_month_contract(
        self, contract: OptionContract
    ) -> Optional[OptionContract]:
        """
        获取指定合约在上一个月份的对应合约
        :param contract: 当前合约
        :return: 上一个月份的对应合约，如果不存在则返回None
        """
        all_expire_dates = self.get_all_expire_dates()
        try:
            current_idx = all_expire_dates.index(contract.expire_date)
            if current_idx > 0:
                prev_expire_date = all_expire_dates[current_idx - 1]
                # 查找同一行权价和期权类型的上一个月份合约
                prev_contracts = self.get_contracts_by_expiry(
                    prev_expire_date, contract.option_type
                )
                for prev_contract in prev_contracts:
                    if prev_contract.strike_price == contract.strike_price:
                        return prev_contract
            return None
        except ValueError:
            return None


if __name__ == "__main__":
    import dolphindb as ddb

    # 连接数据库获取期权合约数据
    conn = ddb.session()
    conn.connect(
        "192.168.0.31",
        8848,
        "admin",
        "123456",
    )
    sql = f"""
        select * from loadTable("dfs://RealTimeData", "instruments")
        where date = (select max(date) from loadTable("dfs://RealTimeData", "instruments"))
    """
    df = conn.run(sql)
    conn.close()

    # 创建市场期权链
    market_chain = MarketOptionChain(df)

    # 获取所有标的代码
    underlying_codes = market_chain.get_all_underlying_codes()
    print(f"所有标的代码: {underlying_codes}")

    # 获取某个标的的期权链
    if underlying_codes:
        underlying_code = underlying_codes[0]
        option_chain = market_chain.get_option_chain(underlying_code, "standard")

        if option_chain:
            print(f"\n{underlying_code} 标准合约期权链:")
            print(f"所有到期日: {option_chain.get_all_expire_dates()}")
            print(f"所有行权价: {option_chain.get_all_strike_prices()}")

            # 演示链式导航
            expire_dates = option_chain.get_all_expire_dates()
            if expire_dates:
                expire_date = expire_dates[0]
                call_contracts = option_chain.get_contracts_by_expiry(
                    expire_date, "CALL"
                )

                if call_contracts:
                    print(f"\n{expire_date} 到期的CALL合约链式导航演示:")
                    contract = call_contracts[0]  # 获取第一个合约

                    print(
                        f"当前合约: {contract.instrument_id} (行权价: {contract.strike_price})"
                    )

                    # 导航到下一个行权价
                    if contract.next_strike:
                        print(
                            f"下一个行权价合约: {contract.next_strike.instrument_id} (行权价: {contract.next_strike.strike_price})"
                        )

                    # 导航到下一个到期时间
                    if contract.next_expiry:
                        print(
                            f"下一个到期时间合约: {contract.next_expiry.instrument_id} (到期日: {contract.next_expiry.expire_date})"
                        )

                    # 导航到对手合约
                    if contract.counterpart:
                        print(
                            f"对手合约: {contract.counterpart.instrument_id} (类型: {contract.counterpart.option_type})"
                        )

            # 演示获取平值期权
            underlying_price = 2.643  # 假设标的价格
            atm_contracts = option_chain.get_atm_contracts(underlying_price)
            if atm_contracts:
                print(f"\n平值期权合约 (标的价格: {underlying_price}):")
                for option_type, contract in atm_contracts.items():
                    print(
                        f"{option_type}: {contract.instrument_id} (行权价: {contract.strike_price})"
                    )

    # 演示根据合约代码获取合约
    sample_contract = market_chain.get_contract_by_id("90004697")  # 假设的合约代码
    if sample_contract:
        print(f"\n合约信息: {sample_contract.instrument_id}")
        print(f"标的代码: {sample_contract.data['OptUndlCode']}")
        print(f"行权价: {sample_contract.strike_price}")
        print(f"到期日: {sample_contract.expire_date}")
        print(f"期权类型: {sample_contract.option_type}")

        # 现在可以直接使用链式导航功能
        if sample_contract.counterpart:
            print(f"对手合约: {sample_contract.counterpart.instrument_id}")
        if sample_contract.next_strike:
            print(f"下一个行权价合约: {sample_contract.next_strike.instrument_id}")
        if sample_contract.prev_strike:
            print(f"上一个行权价合约: {sample_contract.prev_strike.instrument_id}")
        if sample_contract.next_expiry:
            print(f"下一个到期时间合约: {sample_contract.next_expiry.instrument_id}")
        if sample_contract.prev_expiry:
            print(f"上一个到期时间合约: {sample_contract.prev_expiry.instrument_id}")
