from enum import IntEnum
from py_vollib.black_scholes import implied_volatility
from py_vollib.black_scholes.greeks import analytical


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
