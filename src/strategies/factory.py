# from utils.logger import log
from .implementations.moving_average import MovingAverageStrategy
from .implementations.rsi import RSIStrategy
from .implementations.wangba import WangBaStrategy


class StrategyFactory:
    _strategies = {
        "moving_average": MovingAverageStrategy,
        "rsi": RSIStrategy,
        "wangba": WangBaStrategy,
    }

    @classmethod
    def create_strategy(cls, datafeed, strategy_id, name, params):
        strategy_class = cls._strategies.get(name)
        if not strategy_class:
            raise ValueError(f"未知的策略类型: {name}")
        return strategy_class(datafeed, strategy_id, name, params)
