import secrets
import string
import pandas as pd
import uuid
import base64


def short_uuid():
    """高性能实现，直接操作bytes"""
    raw = uuid.uuid4().bytes
    # Base64转换（URL安全）
    result = base64.b64encode(raw, altchars=b"-_").decode("ascii")
    # 移除填充符并替换可能的点
    return result.rstrip("=").replace("|", "_")


def generate_action_name(length=12):
    if length < 1:
        raise ValueError("Length must be at least 1")

    # 首字符为字母（大小写均可）
    first_char = secrets.choice(string.ascii_letters)
    # 剩余字符为字母/数字/下划线（权重控制下划线出现频率）
    valid_chars = string.ascii_letters + string.digits + "_"
    rest_chars = "".join(secrets.choice(valid_chars) for _ in range(length - 1))

    return first_char + rest_chars


def record2dataframe(records):
    values = []
    for record in records:
        record_dict = {
            name: getattr(record, name)
            for name in dir(record)
            if (
                not name.startswith("_")
                and not name
                in [
                    "collection_id",
                    "collection_name",
                    "is_new",
                    "load",
                    "load_expanded",
                    "parse_expanded",
                    "expand",
                ]
            )
        }
        values.append(record_dict)
    if len(values) == 0:
        return pd.DataFrame()

    return pd.DataFrame(values)


def decompose(n, m):
    q = n // m  # 商，表示 m 的个数
    r = n % m  # 余数
    if r == 0:
        return [m] * q
    else:
        return [m] * q + [r]


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
