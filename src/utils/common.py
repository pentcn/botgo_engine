import secrets
import string


def generate_action_name(length=12):
    if length < 1:
        raise ValueError("Length must be at least 1")

    # 首字符为字母（大小写均可）
    first_char = secrets.choice(string.ascii_letters)
    # 剩余字符为字母/数字/下划线（权重控制下划线出现频率）
    valid_chars = string.ascii_letters + string.digits + "_"
    rest_chars = "".join(secrets.choice(valid_chars) for _ in range(length - 1))

    return first_char + rest_chars


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

    def __call__(self):
        return self._df
