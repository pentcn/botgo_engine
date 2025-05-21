import pandas as pd


def sma(X, N, M):
    """
    使用矢量运算计算通达信风格的 SMA（简单移动平均）

    参数:
    X (pd.Series 或 np.array): 输入的时间序列数据
    N (int): 移动平均的周期
    M (int): 权重，必须小于 N

    返回:
    pd.Series: 计算得到的 SMA 序列
    """
    if not isinstance(X, pd.Series):
        X = pd.Series(X)
    if N <= M:
        raise ValueError("N 必须大于 M")
    X = X.fillna(0)
    Y = pd.Series(index=X.index, dtype=float)
    Y.iloc[0] = X.iloc[0]  # 初始值设为 X 的第一个值

    # 使用向量化操作计算 SMA
    # coef = (N - M) / N
    Y = Y.fillna(0)  # 将 NaN 值填充为 0
    for i in range(1, len(X)):
        Y.iloc[i] = (M * X.iloc[i] + (N - M) * Y.iloc[i - 1]) / N

    return Y


def DSRT(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.Series:
    llv = low.rolling(55).min()
    hhv = high.rolling(55).max()
    v11 = 3 * sma((close - llv) / (hhv - llv) * 100, 5, 1) - 2 * sma(
        sma((close - llv) / (hhv - llv) * 100, 5, 1), 3, 1
    )
    trendline = v11.ewm(span=3, adjust=False).mean()

    return trendline
