#!/usr/bin/env python3
"""
A股量化交易系统 - 主程序入口

功能：
1. 策略回测
2. 实盘交易
3. 系统监控

使用方法：
    python main.py backtest    # 运行回测
    python main.py trade       # 实盘交易
    python main.py monitor     # 监控模式
"""

import os
import sys
import json
import argparse
from datetime import datetime, date, timedelta
from typing import Dict, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger, get_logger
from utils.database import DatabaseManager
from utils.notification import NotificationManager
from core.data_manager import DataManager
from core.backtest_engine import BacktestEngine, print_backtest_report
from core.trading_engine import TradingEngine
from core.risk_manager import RiskManager, RiskConfig
from strategies import (
    MAStrategy,
    MACDStrategy,
    RSIStrategy,
    BollingerStrategy,
    KDJStrategy
)


def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def init_system(simulate: bool = True):
    """
    初始化系统组件

    Args:
        simulate: 是否模拟模式

    Returns:
        (db_manager, data_manager, risk_manager, notification_manager)
    """
    # 加载配置
    system_config = load_config('config/system_config.json')
    strategy_config = load_config('config/strategy_config.json')

    # 初始化日志
    log_level = system_config['system'].get('log_level', 'INFO')
    setup_logger(level=log_level)
    logger = get_logger()
    logger.info("=" * 50)
    logger.info("A股量化交易系统启动")
    logger.info("=" * 50)

    # 初始化数据库
    db_path = system_config['data']['database_path']
    db_manager = DatabaseManager(db_path)

    # 初始化数据管理器
    cache_days = system_config['data']['cache_days']
    data_manager = DataManager(db_manager=db_manager, cache_days=cache_days)

    # 初始化风控管理器
    risk_config = RiskConfig(
        max_daily_loss_pct=system_config['risk_control']['max_daily_loss_pct'],
        max_single_position_pct=system_config['risk_control']['max_single_position_pct'],
        max_total_position_pct=system_config['risk_control']['max_total_position_pct'],
        max_holding_stocks=system_config['risk_control']['max_holding_stocks'],
        default_stop_loss_pct=system_config['risk_control']['default_stop_loss_pct'],
        default_take_profit_pct=system_config['risk_control']['default_take_profit_pct'],
        max_drawdown_pct=system_config['risk_control']['max_drawdown_pct']
    )

    # 初始化通知管理器
    notification_manager = NotificationManager(system_config.get('notification', {}))

    risk_manager = RiskManager(
        config=risk_config,
        db_manager=db_manager,
        notification_manager=notification_manager
    )

    return db_manager, data_manager, risk_manager, notification_manager, system_config, strategy_config


def create_strategies(strategy_config: Dict) -> List:
    """
    根据配置创建策略实例

    Args:
        strategy_config: 策略配置

    Returns:
        策略实例列表
    """
    strategies = []
    strategy_configs = strategy_config.get('strategies', {})

    # 双均线策略
    if strategy_configs.get('ma_cross', {}).get('enabled'):
        config = strategy_configs['ma_cross']
        strategy = MAStrategy(
            stocks=config.get('stocks', []),
            fast_period=config['params']['fast_period'],
            slow_period=config['params']['slow_period'],
            position_pct=config.get('position_pct', 0.25),
            stop_loss_pct=config.get('stop_loss_pct', 0.08),
            take_profit_pct=config.get('take_profit_pct', 0.15)
        )
        strategies.append(strategy)

    # MACD策略
    if strategy_configs.get('macd', {}).get('enabled'):
        config = strategy_configs['macd']
        strategy = MACDStrategy(
            stocks=config.get('stocks', []),
            fast_period=config['params']['fast_period'],
            slow_period=config['params']['slow_period'],
            signal_period=config['params']['signal_period'],
            position_pct=config.get('position_pct', 0.25),
            stop_loss_pct=config.get('stop_loss_pct', 0.08),
            take_profit_pct=config.get('take_profit_pct', 0.15)
        )
        strategies.append(strategy)

    # RSI策略
    if strategy_configs.get('rsi', {}).get('enabled'):
        config = strategy_configs['rsi']
        strategy = RSIStrategy(
            stocks=config.get('stocks', []),
            period=config['params']['period'],
            oversold=config['params']['oversold'],
            overbought=config['params']['overbought'],
            position_pct=config.get('position_pct', 0.20),
            stop_loss_pct=config.get('stop_loss_pct', 0.06),
            take_profit_pct=config.get('take_profit_pct', 0.12)
        )
        strategies.append(strategy)

    # 布林带策略
    if strategy_configs.get('bollinger', {}).get('enabled'):
        config = strategy_configs['bollinger']
        strategy = BollingerStrategy(
            stocks=config.get('stocks', []),
            period=config['params']['period'],
            std_dev=config['params']['std_dev'],
            position_pct=config.get('position_pct', 0.20),
            stop_loss_pct=config.get('stop_loss_pct', 0.07),
            take_profit_pct=config.get('take_profit_pct', 0.14)
        )
        strategies.append(strategy)

    # KDJ策略
    if strategy_configs.get('kdj', {}).get('enabled'):
        config = strategy_configs['kdj']
        strategy = KDJStrategy(
            stocks=config.get('stocks', []),
            k_period=config['params']['k_period'],
            d_period=config['params']['d_period'],
            j_period=config['params']['j_period'],
            oversold=config['params']['oversold'],
            overbought=config['params']['overbought'],
            position_pct=config.get('position_pct', 0.20),
            stop_loss_pct=config.get('stop_loss_pct', 0.06),
            take_profit_pct=config.get('take_profit_pct', 0.12)
        )
        strategies.append(strategy)

    return strategies


def run_backtest(args):
    """运行回测"""
    logger = get_logger()
    logger.info("开始回测模式...")

    # 初始化系统
    db_manager, data_manager, risk_manager, _, system_config, strategy_config = init_system(simulate=True)

    # 获取回测配置
    backtest_config = strategy_config['global_settings']['backtest']
    initial_cash = backtest_config['initial_cash']
    start_date = args.start_date or backtest_config['start_date']
    end_date = args.end_date or backtest_config['end_date']

    # 创建策略
    strategies = create_strategies(strategy_config)

    if not strategies:
        logger.warning("没有启用的策略，请检查配置文件")
        return

    # 创建回测引擎
    backtest_engine = BacktestEngine(
        initial_cash=initial_cash,
        commission_rate=backtest_config['commission_rate'],
        stamp_tax_rate=backtest_config['stamp_tax_rate'],
        slippage=backtest_config['slippage'],
        db_manager=db_manager
    )

    # 对每个策略进行回测
    for strategy in strategies:
        logger.info(f"\n{'='*50}")
        logger.info(f"回测策略: {strategy.name}")
        logger.info(f"股票池: {strategy.stocks}")
        logger.info(f"{'='*50}")

        if not strategy.stocks:
            logger.warning(f"策略 {strategy.name} 没有配置股票池")
            continue

        # 获取历史数据
        data = {}
        for stock_code in strategy.stocks:
            logger.info(f"获取数据: {stock_code}")
            df = data_manager.get_history_klines(
                stock_code,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', '')
            )
            if not df.empty:
                data[stock_code] = df
            else:
                logger.warning(f"无法获取数据: {stock_code}")

        if not data:
            logger.warning(f"策略 {strategy.name} 无有效数据")
            continue

        # 运行回测
        result = backtest_engine.run(
            strategy=strategy,
            data=data,
            start_date=datetime.strptime(start_date, '%Y-%m-%d').date(),
            end_date=datetime.strptime(end_date, '%Y-%m-%d').date()
        )

        if result:
            print_backtest_report(result)

    logger.info("\n回测完成！")


def run_trade(args):
    """运行实盘交易"""
    logger = get_logger()
    logger.info("开始实盘交易模式...")

    simulate = args.simulate
    if simulate:
        logger.info("*** 模拟交易模式 - 不会实际下单 ***")

    # 初始化系统
    db_manager, data_manager, risk_manager, notification_manager, system_config, strategy_config = init_system(
        simulate=simulate
    )

    # 创建交易引擎
    trading_config = system_config['trading']
    trading_engine = TradingEngine(
        broker=trading_config['broker'],
        client_path=trading_config['client_path'],
        data_manager=data_manager,
        risk_manager=risk_manager,
        db_manager=db_manager,
        notification_manager=notification_manager,
        simulate=simulate
    )

    # 连接券商
    if not trading_engine.connect():
        logger.error("无法连接券商，退出")
        return

    # 设置风控引擎引用
    risk_manager.set_engine(trading_engine)

    # 创建并注册策略
    strategies = create_strategies(strategy_config)
    for strategy in strategies:
        trading_engine.register_strategy(strategy.name, strategy)

    # 启动交易引擎
    interval = system_config['data'].get('realtime_interval', 5)
    trading_engine.start(interval=interval)

    logger.info("交易引擎已启动，按 Ctrl+C 停止")

    try:
        # 主循环 - 定期输出状态
        import time
        while True:
            time.sleep(60)

            # 输出账户状态
            balance = trading_engine.get_balance()
            positions = trading_engine.get_positions()
            risk_status = risk_manager.get_risk_status()

            logger.info("-" * 40)
            logger.info(f"账户总资产: {balance.get('total_assets', 0):,.2f}")
            logger.info(f"可用资金: {balance.get('available_cash', 0):,.2f}")
            logger.info(f"持仓数量: {len(positions)}")
            logger.info(f"当日盈亏: {risk_status.get('daily_pnl', 0):,.2f} ({risk_status.get('daily_pnl_pct', 0):.2%})")
            logger.info(f"风控状态: {'正常' if not risk_status.get('trading_halted') else '已暂停'}")

    except KeyboardInterrupt:
        logger.info("\n收到停止信号...")

    finally:
        trading_engine.stop()
        trading_engine.disconnect()
        logger.info("交易引擎已停止")


def run_monitor(args):
    """监控模式 - 仅监控不交易"""
    logger = get_logger()
    logger.info("开始监控模式...")

    # 初始化系统
    db_manager, data_manager, _, _, system_config, strategy_config = init_system(simulate=True)

    # 创建策略
    strategies = create_strategies(strategy_config)

    # 收集所有监控的股票
    all_stocks = set()
    for strategy in strategies:
        all_stocks.update(strategy.stocks)

    logger.info(f"监控股票池: {list(all_stocks)}")

    import time
    try:
        while True:
            logger.info("\n" + "=" * 50)
            logger.info(f"市场快照 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 50)

            # 获取实时行情
            quotes = data_manager.get_realtime_quotes(list(all_stocks))

            for code, quote in quotes.items():
                logger.info(
                    f"{quote['name']}({code}): "
                    f"价格={quote['price']:.2f} "
                    f"涨跌={quote['change_pct']:.2%}"
                )

            # 计算信号
            logger.info("\n【策略信号】")
            for strategy in strategies:
                for stock_code in strategy.stocks:
                    try:
                        # 获取历史数据
                        df = data_manager.get_history_klines(stock_code)
                        if df.empty:
                            continue

                        df = data_manager.calculate_indicators(df)
                        signal_result = strategy.calculate_signal(stock_code, df)

                        if signal_result['signal'] != 'hold':
                            logger.info(
                                f"  [{strategy.name}] {stock_code}: "
                                f"{signal_result['signal'].upper()} "
                                f"({signal_result['reason']})"
                            )
                    except Exception as e:
                        logger.error(f"计算信号错误: {stock_code} - {e}")

            # 休息
            time.sleep(system_config['data'].get('realtime_interval', 10))

    except KeyboardInterrupt:
        logger.info("\n监控已停止")


def show_status(args):
    """显示系统状态"""
    logger = get_logger()

    # 初始化系统
    db_manager, _, _, _, _, strategy_config = init_system(simulate=True)

    print("\n" + "=" * 50)
    print("A股量化交易系统状态")
    print("=" * 50)

    # 显示已启用的策略
    print("\n【已启用策略】")
    for name, config in strategy_config['strategies'].items():
        if config.get('enabled'):
            print(f"  - {config['name']}: {config.get('stocks', [])}")

    # 显示最近交易记录
    print("\n【最近交易记录】")
    trades = db_manager.get_trades(limit=10)
    if trades:
        for trade in trades:
            print(
                f"  {trade['trade_time']} | "
                f"{trade['action']} {trade['stock_code']} "
                f"价格:{trade['price']:.2f} 数量:{trade['amount']}"
            )
    else:
        print("  无交易记录")

    # 显示持仓
    print("\n【当前持仓】")
    positions = db_manager.get_positions()
    if positions:
        for pos in positions:
            print(
                f"  {pos['stock_name']}({pos['stock_code']}): "
                f"数量={pos['amount']} "
                f"成本={pos['cost_price']:.2f} "
                f"盈亏={pos.get('profit_pct', 0):.2%}"
            )
    else:
        print("  无持仓")

    # 显示回测结果
    print("\n【最近回测结果】")
    backtest_results = db_manager.get_backtest_results(limit=5)
    if backtest_results:
        for result in backtest_results:
            print(
                f"  {result['strategy']}: "
                f"收益率={result['total_return']:.2%} "
                f"夏普={result['sharpe_ratio']:.2f} "
                f"回撤={result['max_drawdown']:.2%}"
            )
    else:
        print("  无回测记录")

    print("\n" + "=" * 50)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description='A股量化交易系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python main.py backtest                          # 使用默认配置回测
  python main.py backtest -s 2024-01-01 -e 2024-06-01  # 指定日期回测
  python main.py trade --simulate                  # 模拟交易
  python main.py trade                             # 实盘交易（请谨慎！）
  python main.py monitor                           # 监控模式
  python main.py status                            # 显示系统状态
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # 回测命令
    backtest_parser = subparsers.add_parser('backtest', help='运行策略回测')
    backtest_parser.add_argument('-s', '--start-date', type=str, help='开始日期 (YYYY-MM-DD)')
    backtest_parser.add_argument('-e', '--end-date', type=str, help='结束日期 (YYYY-MM-DD)')
    backtest_parser.add_argument('--stock', type=str, help='指定股票代码')

    # 交易命令
    trade_parser = subparsers.add_parser('trade', help='运行实盘交易')
    trade_parser.add_argument('--simulate', action='store_true', default=True, help='模拟模式（默认）')
    trade_parser.add_argument('--real', action='store_true', help='实盘模式（请谨慎！）')

    # 监控命令
    monitor_parser = subparsers.add_parser('monitor', help='监控模式')

    # 状态命令
    status_parser = subparsers.add_parser('status', help='显示系统状态')

    args = parser.parse_args()

    if args.command == 'backtest':
        run_backtest(args)
    elif args.command == 'trade':
        if args.real:
            args.simulate = False
            print("\n" + "!" * 50)
            print("警告：您正在进入实盘交易模式！")
            print("这将使用真实资金进行交易！")
            print("!" * 50)
            confirm = input("\n确认进入实盘模式？(yes/no): ")
            if confirm.lower() != 'yes':
                print("已取消")
                return
        run_trade(args)
    elif args.command == 'monitor':
        run_monitor(args)
    elif args.command == 'status':
        show_status(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
