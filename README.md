# BotGo Engine

BotGo Engine 是一个专业的量化交易策略引擎，支持期权交易、技术指标分析和策略状态持久化。

## 🚀 核心特性

- **策略状态持久化**：基于StateVariable描述符的友好状态管理系统
- **期权交易支持**：完整的期权组合交易功能，支持各种期权策略
- **实时数据处理**：集成DolphinDB和PocketBase，支持实时行情和历史数据
- **技术指标分析**：内置多种技术指标，支持自定义指标开发
- **多用户支持**：基于PocketBase的多用户策略隔离
- **灵活的策略框架**：易于扩展的策略基类，支持快速策略开发

## 📦 安装

### 环境要求

- Python 3.8+
- DolphinDB 服务器
- PocketBase 服务器

### 安装依赖

```bash
pip install -r requirements.txt
```

### 环境配置

1. 复制环境配置文件：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，配置数据库连接信息：
```env
# DolphinDB 配置
MARKET_DOLPHIN_HOST=localhost
MARKET_DOLPHIN_PORT=8848
MARKET_DOLPHIN_USER=admin
MARKET_DOLPHIN_PASSWORD=123456
MARKET_DATABASE_NAME=market_db
MARKET_BARTABLE_NAME=bar_table

HISTORY_DOLPHIN_HOST=localhost
HISTORY_DOLPHIN_PORT=8849
HISTORY_DOLPHIN_USER=admin
HISTORY_DOLPHIN_PASSWORD=123456
HISTORY_DATABASE_NAME=history_db
HISTROY_BARTABLE_NAME=history_bar_table

# PocketBase 配置
POCKETBASE_URL=http://localhost:8090
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=admin123456
```

## 🎯 快速开始

### 1. 创建策略

使用新的StateVariable系统创建策略：

```python
from strategies.base import BaseStrategy, StateVariable

class MyStrategy(BaseStrategy):
    # 定义状态变量
    position = StateVariable(0, description="持仓数量")
    profit = StateVariable(0.0, description="累计盈亏")
    last_signal = StateVariable("", description="最后信号")
    
    def __init__(self, datafeed, strategy_id, name, params):
        super().__init__(datafeed, strategy_id, name, params)
        
    def on_bar(self, symbol, period, bar):
        # 策略逻辑
        if self.should_buy():
            self.position = 100  # 自动保存到数据库
            self.last_signal = "BUY"
            
    def should_buy(self):
        # 买入条件
        return True
```

### 2. 运行策略

```python
from strategies.manager import monitor_strategies

# 启动策略监控
monitor_strategies()
```

### 3. 状态管理

#### 友好的状态访问方式

```python
# 读取状态
current_position = self.position
total_profit = self.profit

# 更新状态（自动保存）
self.position += 50
self.profit = calculate_profit()

# 批量更新
self.update_state_variables({
    'position': 200,
    'profit': 1500.0,
    'last_signal': 'SELL'
})
```

#### 传统方式（向后兼容）

```python
# 仍然支持传统方式
position = self.get_state_variable("position", 0)
self.set_state_variable("position", position + 100)
```

## 📊 技术指标

### 内置指标

- **DSRT**：自定义技术指标
- **MACD**：移动平均收敛散度
- **ATR**：平均真实波幅
- **RSI**：相对强弱指数

### 使用示例

```python
from pandas_ta import macd, atr
from indicators.dsrt import DSRT

def on_bar(self, symbol, period, bar):
    # 计算技术指标
    dsrt_values = DSRT(self.bars.close, self.bars.high, self.bars.low)
    macd_hist = macd(self.bars.close)["MACDh_12_26_9"]
    atr_value = atr(self.bars.high, self.bars.low, self.bars.close, length=14)
```

## 🔧 期权交易

### 基本操作

```python
# 买开
self.buy_open("10009326.SHO", 10)

# 卖开
self.sell_open("10009327.SHO", 10)

# 买平
self.buy_close("10009326.SHO", 5)

# 卖平
self.sell_close("10009327.SHO", 5)

# 撤单
self.cancel("order_id")
```

### 期权组合

```python
from utils.option import OptionCombinationType

# 创建牛市价差组合
self.make_combination(
    OptionCombinationType.BULL_CALL_SPREAD,
    "call_option_1", True,
    "call_option_2", False,
    quantity=1
)

# 释放组合
self.release_combination("combination_id")
```

## 🗄️ 数据库架构

### PocketBase 表结构

#### strategies 表
- `id`: 策略ID
- `name`: 策略名称
- `user`: 用户关联
- `status`: 策略状态

#### strategyStates 表
- `strategy`: 策略关联 (relation to strategies)
- `user`: 用户关联 (relation to users)
- `state_data`: 状态数据 (JSON)
- `version`: 版本号

### DolphinDB 配置

支持实时行情数据和历史数据查询，配置灵活的数据源。

## 🧪 测试

运行测试套件：

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest test/test_state_persistence.py

# 运行状态管理测试
python test_friendly_access.py
```

## 📁 项目结构

```
botgo_engine/
├── src/
│   ├── strategies/          # 策略模块
│   │   ├── base.py         # 基础策略类
│   │   ├── manager.py      # 策略管理器
│   │   ├── factory.py      # 策略工厂
│   │   ├── dolphindb_datafeed.py  # 数据源
│   │   └── implementations/  # 策略实现
│   ├── utils/              # 工具模块
│   │   ├── config.py       # 配置管理
│   │   ├── logger.py       # 日志工具
│   │   ├── pb_client.py    # PocketBase客户端
│   │   ├── option.py       # 期权工具
│   │   └── common.py       # 通用工具
│   ├── indicators/         # 技术指标
│   └── main.py            # 主程序入口
├── test/                  # 测试文件
├── requirements.txt       # 依赖文件
└── README.md             # 项目文档
```

## 🔄 状态持久化系统

### StateVariable 特性

- **自动保存**：状态变化时立即保存到数据库
- **类型安全**：支持各种Python数据类型
- **描述信息**：为每个状态变量添加描述
- **IDE支持**：完整的代码补全和类型检查

### 最佳实践

1. **状态变量定义**：在类级别定义所有状态变量
2. **初始值设置**：为每个状态变量提供合理的默认值
3. **描述信息**：添加清晰的描述信息便于维护
4. **数据类型**：使用适当的数据类型（int, float, str, list, dict等）

## 🚨 注意事项

1. **数据库连接**：确保DolphinDB和PocketBase服务正常运行
2. **状态大小**：避免在状态中存储过大的数据结构
3. **并发安全**：状态更新是线程安全的
4. **错误处理**：状态保存失败不会中断策略运行

## 📝 更新日志

### v2.0.0 (最新)
- 新增StateVariable描述符系统
- 优化状态持久化性能
- 改进期权交易功能
- 增强错误处理机制

### v1.0.0
- 基础策略框架
- DolphinDB数据源集成
- PocketBase状态存储

## 🤝 贡献

欢迎提交Issue和Pull Request来改进项目。

## 📄 许可证

本项目采用MIT许可证。

## 📞 支持

如有问题，请通过以下方式联系：

- 提交Issue：[GitHub Issues](https://github.com/your-repo/botgo_engine/issues)
- 邮箱：support@example.com

---

**BotGo Engine** - 让量化交易更简单、更高效！ 