# test_remark_operations.py

import json
import time
from datetime import datetime
from enum import IntEnum
from src.utils.pb_client import get_pb_client
from src.utils.common import short_uuid

# 初始化客户端
client = get_pb_client()


class OptionCombinationType(IntEnum):
    """期权交易策略枚举"""

    BULL_CALL_SPREAD = 50  # 认购牛市价差策略
    BEAR_PUT_SPREAD = 51  # 认沽熊市价差策略
    BULL_PUT_SPREAD = 52  # 认沽牛市价差策略
    BEAR_CALL_SPREAD = 53  # 认购熊市价差策略
    SHORT_STRADDLE = 54  # 跨式空头
    SHORT_STRANGLE = 55  # 宽跨式空头
    MARGIN_TO_COVERED = 56  # 保证金开仓转备兑开仓
    COVERED_TO_MARGIN = 57  # 备兑开仓转保证金开仓


def create_test_deal(
    client,
    instrument_id,
    volume,
    price,
    direction,  # 48: 买入, 49: 卖出
    offset_flag,  # 48: 开仓, 49: 平仓, -1: 组合操作
    remark="",
    exchange_id="SHO",
    account_id="840092285",
    user_id="v4w3357rsqml48g",
    entrust_type=48,  # 48: 普通, 66: 构建组合, 67: 拆分组合
):
    """创建测试用的deals记录"""

    direction_map = {48: "买入", 49: "卖出"}
    offset_map = {48: "开仓", 49: "平仓", -1: "组合操作"}

    opt_name = ""
    if offset_flag == -1:
        if entrust_type == 66:
            opt_name = "构建组合持仓"
        elif entrust_type == 67:
            opt_name = "拆分组合持仓"
    else:
        opt_name = f"{direction_map[direction]}{offset_map[offset_flag]}"

    base_remark = f"7416w114037s7c8|{short_uuid()}"
    final_remark = base_remark if remark == "" else f"{base_remark}|{remark}"

    data = {
        "exchangeId": exchange_id,
        "exchangeName": "上证股票期权",
        "instrumentId": instrument_id,
        "direction": direction,
        "offsetFlag": offset_flag,
        "price": price,
        "optName": opt_name,
        "entrustType": entrust_type,
        "accountId": account_id,
        "remark": final_remark,
        "user": user_id,
        "volume": volume,
    }

    print(
        f"创建deals记录: {opt_name} {instrument_id} {volume}手 价格:{price} remark:{final_remark}"
    )
    client.collection("deals").create(data)
    time.sleep(0.5)  # 给系统处理时间
    return final_remark


def create_test_positions(client, user_id, instrument_id, volume, can_use_volume=None):
    """创建测试用的持仓记录"""
    if can_use_volume is None:
        can_use_volume = volume

    data = {
        "user": user_id,
        "instrumentId": instrument_id,
        "instrumentName": f"期权合约{instrument_id}",
        "volume": volume,
        "canUseVolume": can_use_volume,
        "direction": -1,  # 1: 权利仓, -1: 业务仓
        "openPrice": 0.05,
    }

    print(f"创建持仓记录: {instrument_id} {volume}手 可用:{can_use_volume}手")
    client.collection("positions").create(data)


def create_test_combinations(client, user_id, first_code, second_code, comb_id, volume):
    """创建测试用的组合记录"""
    data = {
        "user": user_id,
        "firstCode": first_code,
        "secondCode": second_code,
        "combId": comb_id,
        "volume": volume,
        "firstCodePosType": 48,  # 权利仓
        "secondCodePosType": 49,  # 义务仓
        "exchangeId": "SHO",
        "combCode": "BULL_CALL_SPREAD",
    }

    print(f"创建组合记录: {first_code}/{second_code} {volume}手")
    client.collection("combinations").create(data)


def check_trade_commands(client, test_description):
    """检查生成的交易指令"""
    print(f"\n=== 检查 {test_description} 后生成的交易指令 ===")
    records = client.collection("tradeCommands").get_list(1, 10, {"sort": "-created"})

    if len(records.items) == 0:
        print("❌ 没有生成任何交易指令")
        return

    for i, record in enumerate(records.items):
        print(f"指令 {i+1}:")
        print(f"  操作类型: {record.op_type}")
        print(f"  订单类型: {record.order_type}")
        print(f"  合约代码: {record.order_code}")
        print(f"  数量: {record.volume}")
        print(f"  用户订单ID: {record.user_order_id}")
        print(f"  创建时间: {record.created}")
        print()


def clear_test_data(client):
    """清理测试数据"""
    collections = ["deals", "tradeCommands", "positions", "combinations"]

    for collection in collections:
        records = client.collection(collection).get_full_list()
        for record in records:
            client.collection(collection).delete(record.id)

    print("✅ 测试数据已清理")


def test_scenario_1_after_open_combination():
    """测试场景1: 开仓后构建组合"""
    print("\n" + "=" * 60)
    print("测试场景1: 开仓后构建组合")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 先创建一些持仓数据，模拟有可用的对冲合约
    create_test_positions(client, "v4w3357rsqml48g", "10008555", 10, 10)

    # 2. 创建开仓成交记录，remark指示要与10008555构建组合，10008555为义务仓(-1)
    remark = "10008555.SHO|-1"
    create_test_deal(
        client=client,
        instrument_id="10008554",
        volume=5,
        price=0.0186,
        direction=48,  # 买入
        offset_flag=48,  # 开仓
        remark=remark,
    )

    check_trade_commands(client, "开仓后构建组合")


def test_scenario_2_after_close_with_new_open():
    """测试场景2: 平仓后开新仓"""
    print("\n" + "=" * 60)
    print("测试场景2: 平仓后开新仓")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建平仓成交记录，remark指示平仓后要开10008801.SHO，然后与10008809.SHO构建组合
    remark = "10008801.SHO|10008809.SHO|-1"
    create_test_deal(
        client=client,
        instrument_id="10008547",
        volume=3,
        price=0.0378,
        direction=48,  # 买入
        offset_flag=49,  # 平仓
        remark=remark,
    )

    check_trade_commands(client, "平仓后开新仓")


def test_scenario_3_release_combination_only():
    """测试场景3: 拆分组合但不平仓"""
    print("\n" + "=" * 60)
    print("测试场景3: 拆分组合但不平仓")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建组合数据
    create_test_combinations(
        client, "v4w3357rsqml48g", "10008547", "10008555", "comb_001", 5
    )

    # 2. 创建拆分组合记录，remark指示不平仓(0/0)
    remark = "0/0"
    create_test_deal(
        client=client,
        instrument_id="10008547/10008555",
        volume=2,
        price=0,
        direction=48,  # 拆分
        offset_flag=-1,  # 组合操作
        remark=remark,
        entrust_type=67,  # 拆分组合
    )

    check_trade_commands(client, "拆分组合但不平仓")


def test_scenario_4_release_combination_with_close():
    """测试场景4: 拆分组合后平仓"""
    print("\n" + "=" * 60)
    print("测试场景4: 拆分组合后平仓")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建组合数据
    create_test_combinations(
        client, "v4w3357rsqml48g", "10008547", "10008555", "comb_002", 5
    )

    # 2. 创建拆分组合记录，remark指示两个合约都要平仓(1/1)
    remark = "1/1"
    create_test_deal(
        client=client,
        instrument_id="10008547/10008555",
        volume=3,
        price=0,
        direction=48,  # 拆分
        offset_flag=-1,  # 组合操作
        remark=remark,
        entrust_type=67,  # 拆分组合
    )

    check_trade_commands(client, "拆分组合后平仓")


def test_scenario_5_release_combination_with_move():
    """测试场景5: 拆分组合后移仓"""
    print("\n" + "=" * 60)
    print("测试场景5: 拆分组合后移仓(平仓后开新仓)")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建组合数据
    create_test_combinations(
        client, "v4w3357rsqml48g", "10008547", "10008555", "comb_003", 5
    )

    # 2. 创建拆分组合记录，remark指示平仓后开新的合约组合
    remark = "1/1|10008801.SHO/10008809.SHO"
    create_test_deal(
        client=client,
        instrument_id="10008547/10008555",
        volume=2,
        price=0,
        direction=48,  # 拆分
        offset_flag=-1,  # 组合操作
        remark=remark,
        entrust_type=67,  # 拆分组合
    )

    check_trade_commands(client, "拆分组合后移仓")


def test_scenario_6_build_combination():
    """测试场景6: 构建组合"""
    print("\n" + "=" * 60)
    print("测试场景6: 构建组合")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建构建组合记录
    create_test_deal(
        client=client,
        instrument_id="10008546/10008555",
        volume=6,
        price=0,
        direction=49,  # 构建
        offset_flag=-1,  # 组合操作
        remark="",
        entrust_type=66,  # 构建组合
    )

    check_trade_commands(client, "构建组合")


def test_scenario_7_partial_close_flags():
    """测试场景7: 部分平仓标志(1/0 或 0/1)"""
    print("\n" + "=" * 60)
    print("测试场景7: 部分平仓标志")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建组合数据
    create_test_combinations(
        client, "v4w3357rsqml48g", "10008547", "10008555", "comb_004", 5
    )

    # 2. 只平第一个合约，保留第二个合约
    remark = "1/0"
    create_test_deal(
        client=client,
        instrument_id="10008547/10008555",
        volume=1,
        price=0,
        direction=48,  # 拆分
        offset_flag=-1,  # 组合操作
        remark=remark,
        entrust_type=67,  # 拆分组合
    )

    check_trade_commands(client, "部分平仓标志(1/0)")


def test_scenario_8_complex_remark():
    """测试场景8: 复杂的remark格式"""
    print("\n" + "=" * 60)
    print("测试场景8: 复杂的remark格式")
    print("=" * 60)

    # 清理数据
    clear_test_data(client)

    # 1. 创建开仓成交，remark包含多层信息
    create_test_positions(client, "v4w3357rsqml48g", "10008809", 8, 5)  # 可用量少于总量

    remark = "10008809.SHO|additional_info|1"
    create_test_deal(
        client=client,
        instrument_id="10008801",
        volume=3,
        price=0.0250,
        direction=49,  # 卖出
        offset_flag=48,  # 开仓
        remark=remark,
    )

    check_trade_commands(client, "复杂的remark格式")


def run_all_tests():
    """运行所有测试场景"""
    print("开始运行remark后续操作测试...")
    print("注意: 这些测试需要策略监控服务正在运行以处理deals记录")

    try:
        test_scenario_1_after_open_combination()
        test_scenario_2_after_close_with_new_open()
        test_scenario_3_release_combination_only()
        test_scenario_4_release_combination_with_close()
        test_scenario_5_release_combination_with_move()
        test_scenario_6_build_combination()
        test_scenario_7_partial_close_flags()
        test_scenario_8_complex_remark()

        print("\n" + "=" * 60)
        print("✅ 所有测试场景已执行完成")
        print("=" * 60)
        print("\n请检查 tradeCommands 表中是否生成了正确的后续交易指令")
        print("如果没有生成指令，请确认:")
        print("1. 策略监控服务是否正在运行")
        print("2. deals集合是否正确配置了订阅监听")
        print("3. remark格式是否符合预期")

    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # 清理测试数据
        print("\n正在清理测试数据...")
        clear_test_data(client)


if __name__ == "__main__":
    run_all_tests()
