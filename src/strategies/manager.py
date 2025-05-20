from utils.pb_client import get_pb_client
from pocketbase.services.realtime_service import MessageData
from utils.logger import log
from .factory import StrategyFactory
import threading

# 用于保存当前已启动的策略实例
running_strategies = {}
# 用于保护running_strategies的锁
_strategies_lock = threading.Lock()


def get_user_name(user_id):
    """获取用户名"""
    try:
        client = get_pb_client()
        user = client.collection("users").get_one(user_id)
        return user.name
    except Exception as e:
        log(f"获取用户信息失败: {str(e)}", "error")
        return "未知用户"


def start_strategy(strategy):
    try:
        user_name = get_user_name(strategy.user)
        log(f"启动策略: {strategy.name} (用户: {user_name}, id={strategy.id})")

        # 创建策略实例
        strategy_instance = StrategyFactory.create_strategy(
            strategy.id, strategy.name, strategy.params
        )

        # 启动策略
        strategy_instance.start()

        # 保存策略实例
        with _strategies_lock:
            running_strategies[strategy.id] = strategy_instance

    except Exception as e:
        log(f"启动策略失败: {str(e)}", "error")


def stop_strategy(strategy):
    try:
        user_name = get_user_name(strategy.user)
        log(f"停止策略: {strategy.name} (用户: {user_name}, id={strategy.id})")

        # 获取策略实例并停止
        with _strategies_lock:
            strategy_instance = running_strategies.get(strategy.id)
            if strategy_instance:
                strategy_instance.stop()
                running_strategies.pop(strategy.id)

    except Exception as e:
        log(f"停止策略失败: {str(e)}", "error")


def on_strategy_event(e: MessageData):
    record = e.record
    if e.action not in ["create", "update"]:
        return
    if record.active:
        if record.id not in running_strategies:
            start_strategy(record)
    else:
        if record.id in running_strategies:
            stop_strategy(record)


def start_active_strategies():
    """启动所有活跃的策略"""
    client = get_pb_client()
    service = client.collection("strategies")

    try:
        # 获取所有活跃的策略，并展开用户关系
        active_strategies = service.get_list(
            1, 100, {"filter": "active = true", "expand": "user"}
        )

        if not active_strategies.items:
            log("没有找到活跃的策略")
            return

        log(f"找到 {len(active_strategies.items)} 个活跃的策略")

        # 启动每个活跃的策略
        for strategy in active_strategies.items:
            if strategy.id not in running_strategies:
                start_strategy(strategy)

    except Exception as e:
        log(f"启动活跃策略时发生错误: {str(e)}", "error")


def monitor_strategies():
    client = get_pb_client()
    service = client.collection("strategies")

    # 首先启动所有活跃的策略
    start_active_strategies()

    log("开始监听策略的运行状态...")
    service.subscribe(on_strategy_event)

    # 阻塞主线程，保持订阅
    import time

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("退出监听")
        service.unsubscribe()
