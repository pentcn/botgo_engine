from utils.logger import log
from .implementations.moving_average import MovingAverageStrategy
from .implementations.rsi import RSIStrategy


class StrategyFactory:
    _strategies = {
        "moving_average": MovingAverageStrategy,
        "rsi": RSIStrategy,
    }

    @classmethod
    def create_strategy(cls, name, params):
        strategy_class = cls._strategies.get(name)
        if not strategy_class:
            raise ValueError(f"未知的策略类型: {name}")
        return strategy_class(params)
