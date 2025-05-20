from abc import ABC, abstractmethod
import threading
import time
from utils.logger import log


class BaseStrategy(ABC):
    def __init__(self, strategy_id, name, params):
        self.strategy_id = strategy_id
        self.name = name
        self.params = params
        self._running = False
        self._thread = None
        self._error_count = 10
        self._max_retries = 3  # 最大重试次数
        self._retry_delay = 5  # 重试延迟（秒）

    def start(self):
        """启动策略线程"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_with_error_handling)
        self._thread.daemon = True  # 设置为守护线程，这样主程序退出时线程会自动结束
        self._thread.start()
        # log(f"策略 {self.name} (ID: {self.strategy_id}) 已启动")

    def stop(self):
        """停止策略线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)  # 等待线程结束，最多等待5秒
        # log(f"策略 {self.name} (ID: {self.strategy_id}) 已停止")

    def _run_with_error_handling(self):
        """带错误处理的策略运行循环"""
        while self._running:
            try:
                self._error_count = 0  # 重置错误计数
                self.run()  # 运行策略的主要逻辑

            except Exception as e:
                self._error_count += 1
                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 发生错误: {str(e)}",
                    "error",
                )

                if self._error_count >= self._max_retries:
                    log(
                        f"策略 {self.name} (ID: {self.strategy_id}) 达到最大重试次数，停止运行",
                        "error",
                    )
                    self._running = False
                    break

                log(
                    f"策略 {self.name} (ID: {self.strategy_id}) 将在 {self._retry_delay} 秒后重试",
                    "warning",
                )
                time.sleep(self._retry_delay)

    @abstractmethod
    def run(self):
        """策略的主要运行逻辑，由具体策略实现"""
        pass
