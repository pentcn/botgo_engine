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
