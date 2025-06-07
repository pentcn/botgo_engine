import importlib.util
import inspect
import sys
import os
from pathlib import Path
from utils.logger import log
from .implementations.wangba import WangBaStrategy
from .base import BaseStrategy


class StrategyFactory:
    _strategies = {
        "wangba": WangBaStrategy,
    }

    _user_strategies_loaded = False
    _original_sys_path = None

    @classmethod
    def _setup_user_strategy_environment(cls):
        """为用户策略设置运行环境，自动添加项目路径"""
        if cls._original_sys_path is None:
            cls._original_sys_path = sys.path.copy()
        
        # 获取当前项目的src目录路径
        current_file = Path(__file__)
        project_src_dir = current_file.parent.parent  # 从factory.py向上两级到src目录
        project_root_dir = project_src_dir.parent     # 再向上一级到项目根目录
        
        # 将项目路径添加到sys.path（如果还没有添加）
        src_path = str(project_src_dir)
        root_path = str(project_root_dir)
        
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        if root_path not in sys.path:
            sys.path.insert(0, root_path)
        
        log(f"用户策略环境设置完成，项目路径已自动添加: {src_path}")

    @classmethod
    def _cleanup_user_strategy_environment(cls):
        """清理用户策略环境（可选，用于调试）"""
        if cls._original_sys_path is not None:
            # 注意：通常不需要清理，因为路径添加是全局的且有益的
            pass

    @classmethod
    def _load_user_strategies(cls):
        """从用户目录下的.botgo子目录加载策略文件"""
        if cls._user_strategies_loaded:
            return

        try:
            # 设置用户策略运行环境
            cls._setup_user_strategy_environment()
            
            # 获取用户主目录
            user_home = Path.home()
            botgo_dir = user_home / ".botgo"

            if not botgo_dir.exists():
                log(f"用户策略目录不存在: {botgo_dir}")
                cls._user_strategies_loaded = True
                return

            log(f"开始扫描用户策略目录: {botgo_dir}")

            # 扫描.botgo目录下的所有.py文件
            for py_file in botgo_dir.glob("*.py"):
                if py_file.name.startswith("__"):
                    continue  # 跳过__init__.py等特殊文件

                try:
                    cls._load_strategy_from_file(py_file)
                except Exception as e:
                    log(f"加载策略文件 {py_file} 失败: {str(e)}", "error")

            cls._user_strategies_loaded = True
            log(f"用户策略加载完成，当前可用策略: {list(cls._strategies.keys())}")

        except Exception as e:
            log(f"加载用户策略时发生错误: {str(e)}", "error")
            cls._user_strategies_loaded = True

    @classmethod
    def _load_strategy_from_file(cls, file_path):
        """从指定文件加载策略类"""
        module_name = file_path.stem

        # 动态导入模块
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建模块规范: {file_path}")

        module = importlib.util.module_from_spec(spec)
        
        # 在执行模块前，确保环境已设置
        cls._setup_user_strategy_environment()
        
        spec.loader.exec_module(module)

        # 查找继承自BaseStrategy的类
        strategy_classes = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj != BaseStrategy
                and hasattr(obj, '__module__')
                and hasattr(obj, '__bases__')
            ):
                # 检查类是否定义在当前模块中
                if obj.__module__ == module_name or obj.__module__ == '__main__':
                    # 检查是否继承自BaseStrategy（通过类名和模块路径）
                    is_base_strategy_subclass = False
                    for base in obj.__mro__:  # 使用方法解析顺序检查所有基类
                        if (base.__name__ == 'BaseStrategy' and 
                            hasattr(base, '__module__') and 
                            'strategies.base' in base.__module__):
                            is_base_strategy_subclass = True
                            break
                    
                    if is_base_strategy_subclass:
                        strategy_classes.append((name, obj))

        if not strategy_classes:
            log(f"文件 {file_path} 中未找到有效的策略类")
            return

        # 注册找到的策略类
        for class_name, strategy_class in strategy_classes:
            # 使用文件名作为策略名称（转换为小写并用下划线分隔）
            strategy_name = cls._convert_class_name_to_strategy_name(class_name)

            if strategy_name in cls._strategies:
                log(
                    f"策略名称冲突，跳过: {strategy_name} (来自 {file_path})", "warning"
                )
                continue

            cls._strategies[strategy_name] = strategy_class
            log(f"成功注册用户策略: {strategy_name} -> {class_name} (来自 {file_path})")

    @classmethod
    def _convert_class_name_to_strategy_name(cls, class_name):
        """将类名转换为策略名称
        例如: MyCustomStrategy -> my_custom_strategy
        """
        # 移除Strategy后缀（如果存在）
        if class_name.endswith("Strategy"):
            class_name = class_name[:-8]

        # 将驼峰命名转换为下划线命名
        result = []
        for i, char in enumerate(class_name):
            if char.isupper() and i > 0:
                result.append("_")
            result.append(char.lower())

        return "".join(result)

    @classmethod
    def create_strategy(cls, datafeed, strategy_id, name, params):
        # 首次调用时加载用户策略
        cls._load_user_strategies()

        strategy_class = cls._strategies.get(name)
        if not strategy_class:
            available_strategies = list(cls._strategies.keys())
            raise ValueError(
                f"未知的策略类型: {name}。可用策略: {available_strategies}"
            )
        return strategy_class(datafeed, strategy_id, name, params)

    @classmethod
    def get_available_strategies(cls):
        """获取所有可用的策略名称"""
        cls._load_user_strategies()
        return list(cls._strategies.keys())

    @classmethod
    def reload_user_strategies(cls):
        """重新加载用户策略（用于开发调试）"""
        cls._user_strategies_loaded = False
        # 清除之前加载的用户策略（保留内置策略）
        builtin_strategies = {
            "moving_average": MovingAverageStrategy,
            "rsi": RSIStrategy,
            "wangba": WangBaStrategy,
        }
        cls._strategies = builtin_strategies.copy()
        cls._load_user_strategies()
