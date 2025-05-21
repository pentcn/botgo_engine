import pandas as pd


# 定义 DataFrame 包装类
class DataFrameWrapper:
    def __init__(self, dataframe):
        self._df = dataframe

    def __getitem__(self, index):
        """通过索引直接访问行 (支持负数及切片)"""
        return self._df.iloc[index]

    # 可选：保留直接操作原 DataFrame 的能力
    def __getattr__(self, name):
        """将未定义属性访问转发到内部 DataFrame"""
        return getattr(self._df, name)


# 自定义主类
class MyClass:
    def __init__(self, df):
        self.bars = DataFrameWrapper(df)  # 使用包装类


# ---------- 测试用例 ----------
# 创建示例数据
data = {
    "datetime": ["2025-05-20 13:07:00", "2025-05-20 13:08:00", "2025-05-20 13:09:00"],
    "open": [4.011, 4.011, 4.009],
    "high": [4.012, 4.011, 4.010],
    "close": [4.010, 4.009, 4.010],
}
df = pd.DataFrame(data)
# 初始化主类实例
obj = MyClass(df)
# 通过 self.bars[-1].open 访问最后一行的 open 值
print(obj.bars[-1].open)  # 输出: 4.009
print(obj.bars.open[-1])
