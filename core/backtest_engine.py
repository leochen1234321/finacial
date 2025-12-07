"""
回测引擎模块
支持策略回测、参数优化、绩效分析
"""

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple, Type, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger
from utils.database import DatabaseManager

logger = get_logger()


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """订单"""
    stock_code: str
    side: OrderSide
    price: float
    amount: int
    timestamp: datetime
    strategy: str = ""
    reason: str = ""


@dataclass
class Trade:
    """成交记录"""
    stock_code: str
    side: OrderSide
    price: float
    amount: int
    timestamp: datetime
    commission: float = 0
    tax: float = 0


@dataclass
class Position:
    """持仓"""
    stock_code: str
    amount: int
    cost_price: float
    buy_date: date


@dataclass
class BacktestResult:
    """回测结果"""
    strategy: str
    stock_code: str
    start_date: date
    end_date: date

    # 资金曲线
    initial_cash: float
    final_value: float
    equity_curve: List[Tuple[date, float]] = field(default_factory=list)

    # 收益指标
    total_return: float = 0
    annual_return: float = 0
    benchmark_return: float = 0
    alpha: float = 0
    beta: float = 0

    # 风险指标
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    max_drawdown: float = 0
    max_drawdown_duration: int = 0  # 最大回撤持续天数
    volatility: float = 0

    # 交易统计
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0
    profit_factor: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    max_win: float = 0
    max_loss: float = 0

    # 交易明细
    trades: List[Trade] = field(default_factory=list)

    # 参数
    params: Dict = field(default_factory=dict)


class BacktestEngine:
    """
    回测引擎
    支持单股票/多股票回测、参数优化
    """

    def __init__(
        self,
        initial_cash: float = 100000,
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        slippage: float = 0.002,
        db_manager: DatabaseManager = None
    ):
        """
        初始化回测引擎

        Args:
            initial_cash: 初始资金
            commission_rate: 佣金费率（双向收取）
            stamp_tax_rate: 印花税率（仅卖出收取）
            slippage: 滑点
            db_manager: 数据库管理器
        """
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage = slippage
        self.db = db_manager

        # 回测状态
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.orders: List[Order] = []
        self.equity_curve: List[Tuple[date, float]] = []

        # 当前数据
        self.current_date: date = None
        self.current_data: Dict[str, pd.Series] = {}
        self.history_data: Dict[str, pd.DataFrame] = {}

    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_cash
        self.positions = {}
        self.trades = []
        self.orders = []
        self.equity_curve = []
        self.current_date = None
        self.current_data = {}

    def run(
        self,
        strategy,
        data: Dict[str, pd.DataFrame],
        start_date: date = None,
        end_date: date = None
    ) -> BacktestResult:
        """
        运行回测

        Args:
            strategy: 策略实例，需实现on_bar方法
            data: {stock_code: DataFrame} K线数据字典
            start_date: 回测开始日期
            end_date: 回测结束日期

        Returns:
            回测结果
        """
        self.reset()
        self.history_data = data

        # 获取所有交易日期
        all_dates = set()
        for df in data.values():
            df_dates = pd.to_datetime(df['date']).dt.date
            all_dates.update(df_dates)

        all_dates = sorted(all_dates)

        if start_date:
            all_dates = [d for d in all_dates if d >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d <= end_date]

        if not all_dates:
            logger.error("无有效交易日期")
            return None

        logger.info(f"开始回测: {all_dates[0]} 至 {all_dates[-1]}, 共{len(all_dates)}个交易日")

        # 初始化策略
        strategy.initialize(self)

        # 逐日回测
        for trade_date in all_dates:
            self.current_date = trade_date

            # 获取当日数据
            self.current_data = {}
            for stock_code, df in data.items():
                df_date = pd.to_datetime(df['date']).dt.date
                row = df[df_date == trade_date]
                if not row.empty:
                    self.current_data[stock_code] = row.iloc[0]

            if not self.current_data:
                continue

            # 调用策略
            try:
                strategy.on_bar(self.current_data)
            except Exception as e:
                logger.error(f"策略执行错误 {trade_date}: {e}")

            # 处理订单
            self._process_orders()

            # 记录权益
            equity = self._calculate_equity()
            self.equity_curve.append((trade_date, equity))

        # 清仓（回测结束）
        self._close_all_positions()

        # 生成回测结果
        result = self._generate_result(
            strategy=strategy.name,
            stock_codes=list(data.keys()),
            start_date=all_dates[0],
            end_date=all_dates[-1],
            params=strategy.params
        )

        # 保存到数据库
        if self.db:
            self._save_result(result)

        return result

    def buy(
        self,
        stock_code: str,
        amount: int = None,
        price: float = None,
        percent: float = None,
        reason: str = ""
    ):
        """
        买入下单

        Args:
            stock_code: 股票代码
            amount: 买入数量（手数 * 100）
            price: 限价（None为市价）
            percent: 按资金比例买入
            reason: 买入原因
        """
        if stock_code not in self.current_data:
            return

        current_price = self.current_data[stock_code]['close']
        order_price = price or current_price

        # 计算数量
        if amount is None and percent:
            available_cash = self.cash * percent
            amount = int(available_cash / (order_price * (1 + self.slippage))) // 100 * 100

        if amount <= 0:
            return

        order = Order(
            stock_code=stock_code,
            side=OrderSide.BUY,
            price=order_price,
            amount=amount,
            timestamp=datetime.combine(self.current_date, datetime.min.time()),
            reason=reason
        )
        self.orders.append(order)

    def sell(
        self,
        stock_code: str,
        amount: int = None,
        price: float = None,
        percent: float = None,
        reason: str = ""
    ):
        """
        卖出下单

        Args:
            stock_code: 股票代码
            amount: 卖出数量
            price: 限价
            percent: 按持仓比例卖出
            reason: 卖出原因
        """
        if stock_code not in self.positions:
            return

        position = self.positions[stock_code]
        current_price = self.current_data.get(stock_code, {})
        if isinstance(current_price, pd.Series):
            current_price = current_price['close']
        else:
            return

        order_price = price or current_price

        # 计算数量
        if amount is None:
            if percent:
                amount = int(position.amount * percent) // 100 * 100
            else:
                amount = position.amount

        amount = min(amount, position.amount)
        if amount <= 0:
            return

        order = Order(
            stock_code=stock_code,
            side=OrderSide.SELL,
            price=order_price,
            amount=amount,
            timestamp=datetime.combine(self.current_date, datetime.min.time()),
            reason=reason
        )
        self.orders.append(order)

    def close_position(self, stock_code: str, reason: str = ""):
        """平仓"""
        self.sell(stock_code, percent=1.0, reason=reason)

    def _process_orders(self):
        """处理订单队列"""
        for order in self.orders:
            if order.side == OrderSide.BUY:
                self._execute_buy(order)
            else:
                self._execute_sell(order)
        self.orders = []

    def _execute_buy(self, order: Order):
        """执行买入"""
        # 计算成交价（加滑点）
        fill_price = order.price * (1 + self.slippage)

        # 计算费用
        total_cost = fill_price * order.amount
        commission = max(total_cost * self.commission_rate, 5)  # 最低5元

        # 检查资金
        if self.cash < total_cost + commission:
            logger.debug(f"资金不足，无法买入 {order.stock_code}")
            return

        # 扣减资金
        self.cash -= (total_cost + commission)

        # 更新持仓
        if order.stock_code in self.positions:
            pos = self.positions[order.stock_code]
            new_amount = pos.amount + order.amount
            new_cost = (pos.cost_price * pos.amount + fill_price * order.amount) / new_amount
            pos.amount = new_amount
            pos.cost_price = new_cost
        else:
            self.positions[order.stock_code] = Position(
                stock_code=order.stock_code,
                amount=order.amount,
                cost_price=fill_price,
                buy_date=self.current_date
            )

        # 记录成交
        trade = Trade(
            stock_code=order.stock_code,
            side=OrderSide.BUY,
            price=fill_price,
            amount=order.amount,
            timestamp=order.timestamp,
            commission=commission
        )
        self.trades.append(trade)

        logger.debug(f"买入成交: {order.stock_code} 价格:{fill_price:.2f} 数量:{order.amount}")

    def _execute_sell(self, order: Order):
        """执行卖出"""
        if order.stock_code not in self.positions:
            return

        position = self.positions[order.stock_code]
        sell_amount = min(order.amount, position.amount)

        # 计算成交价（减滑点）
        fill_price = order.price * (1 - self.slippage)

        # 计算费用
        total_value = fill_price * sell_amount
        commission = max(total_value * self.commission_rate, 5)
        tax = total_value * self.stamp_tax_rate

        # 增加资金
        self.cash += (total_value - commission - tax)

        # 更新持仓
        position.amount -= sell_amount
        if position.amount <= 0:
            del self.positions[order.stock_code]

        # 记录成交
        trade = Trade(
            stock_code=order.stock_code,
            side=OrderSide.SELL,
            price=fill_price,
            amount=sell_amount,
            timestamp=order.timestamp,
            commission=commission,
            tax=tax
        )
        self.trades.append(trade)

        logger.debug(f"卖出成交: {order.stock_code} 价格:{fill_price:.2f} 数量:{sell_amount}")

    def _close_all_positions(self):
        """清仓所有持仓"""
        for stock_code in list(self.positions.keys()):
            if stock_code in self.current_data:
                self.close_position(stock_code, reason="回测结束清仓")
        self._process_orders()

    def _calculate_equity(self) -> float:
        """计算当前权益"""
        equity = self.cash

        for stock_code, position in self.positions.items():
            if stock_code in self.current_data:
                current_price = self.current_data[stock_code]['close']
                equity += position.amount * current_price

        return equity

    def _generate_result(
        self,
        strategy: str,
        stock_codes: List[str],
        start_date: date,
        end_date: date,
        params: Dict
    ) -> BacktestResult:
        """生成回测结果"""
        result = BacktestResult(
            strategy=strategy,
            stock_code=','.join(stock_codes),
            start_date=start_date,
            end_date=end_date,
            initial_cash=self.initial_cash,
            final_value=self.cash,
            equity_curve=self.equity_curve,
            trades=self.trades,
            params=params
        )

        # 计算收益指标
        if self.equity_curve:
            equity_values = [e[1] for e in self.equity_curve]

            # 总收益率
            result.total_return = (equity_values[-1] / self.initial_cash) - 1

            # 年化收益率
            days = (end_date - start_date).days
            if days > 0:
                result.annual_return = (1 + result.total_return) ** (365 / days) - 1

            # 计算日收益率
            daily_returns = []
            for i in range(1, len(equity_values)):
                daily_return = equity_values[i] / equity_values[i-1] - 1
                daily_returns.append(daily_return)

            if daily_returns:
                # 波动率
                result.volatility = np.std(daily_returns) * np.sqrt(252)

                # 夏普比率（假设无风险利率3%）
                risk_free_rate = 0.03
                if result.volatility > 0:
                    result.sharpe_ratio = (result.annual_return - risk_free_rate) / result.volatility

                # 索提诺比率
                negative_returns = [r for r in daily_returns if r < 0]
                if negative_returns:
                    downside_std = np.std(negative_returns) * np.sqrt(252)
                    if downside_std > 0:
                        result.sortino_ratio = (result.annual_return - risk_free_rate) / downside_std

            # 最大回撤
            max_value = equity_values[0]
            max_drawdown = 0
            for value in equity_values:
                max_value = max(max_value, value)
                drawdown = (max_value - value) / max_value
                max_drawdown = max(max_drawdown, drawdown)
            result.max_drawdown = max_drawdown

        # 交易统计
        if self.trades:
            result.total_trades = len([t for t in self.trades if t.side == OrderSide.SELL])

            # 计算每笔交易盈亏
            trade_profits = []
            buy_trades = {}

            for trade in self.trades:
                if trade.side == OrderSide.BUY:
                    if trade.stock_code not in buy_trades:
                        buy_trades[trade.stock_code] = []
                    buy_trades[trade.stock_code].append(trade)
                else:
                    # 配对买入交易计算盈亏
                    if trade.stock_code in buy_trades and buy_trades[trade.stock_code]:
                        buy_trade = buy_trades[trade.stock_code].pop(0)
                        profit = (trade.price - buy_trade.price) * trade.amount
                        profit -= trade.commission + trade.tax + buy_trade.commission
                        trade_profits.append(profit)

            if trade_profits:
                wins = [p for p in trade_profits if p > 0]
                losses = [p for p in trade_profits if p < 0]

                result.win_trades = len(wins)
                result.lose_trades = len(losses)
                result.win_rate = len(wins) / len(trade_profits) if trade_profits else 0

                result.avg_win = np.mean(wins) if wins else 0
                result.avg_loss = np.mean(losses) if losses else 0
                result.max_win = max(wins) if wins else 0
                result.max_loss = min(losses) if losses else 0

                total_win = sum(wins)
                total_loss = abs(sum(losses))
                result.profit_factor = total_win / total_loss if total_loss > 0 else float('inf')

        return result

    def _save_result(self, result: BacktestResult):
        """保存回测结果到数据库"""
        try:
            self.db.save_backtest_result(
                strategy=result.strategy,
                stock_code=result.stock_code,
                start_date=result.start_date,
                end_date=result.end_date,
                initial_cash=result.initial_cash,
                final_value=result.final_value,
                total_return=result.total_return,
                annual_return=result.annual_return,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                profit_factor=result.profit_factor,
                total_trades=result.total_trades,
                params=result.params
            )
        except Exception as e:
            logger.error(f"保存回测结果失败: {e}")

    def get_position(self, stock_code: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(stock_code)

    def get_position_amount(self, stock_code: str) -> int:
        """获取持仓数量"""
        pos = self.positions.get(stock_code)
        return pos.amount if pos else 0

    def get_cash(self) -> float:
        """获取可用资金"""
        return self.cash

    def get_equity(self) -> float:
        """获取当前权益"""
        return self._calculate_equity()

    def get_history(self, stock_code: str, field: str, length: int) -> np.ndarray:
        """
        获取历史数据

        Args:
            stock_code: 股票代码
            field: 字段名 (open/high/low/close/volume)
            length: 回看长度

        Returns:
            历史数据数组
        """
        if stock_code not in self.history_data:
            return np.array([])

        df = self.history_data[stock_code]
        df_dates = pd.to_datetime(df['date']).dt.date

        # 获取当前日期之前的数据
        mask = df_dates <= self.current_date
        history_df = df[mask].tail(length)

        return history_df[field].values


def print_backtest_report(result: BacktestResult):
    """打印回测报告"""
    print("\n" + "=" * 60)
    print(f"回测报告 - {result.strategy}")
    print("=" * 60)

    print(f"\n【基本信息】")
    print(f"  股票代码: {result.stock_code}")
    print(f"  回测区间: {result.start_date} 至 {result.end_date}")
    print(f"  初始资金: {result.initial_cash:,.2f}")
    print(f"  最终权益: {result.final_value:,.2f}")

    print(f"\n【收益指标】")
    print(f"  总收益率: {result.total_return:.2%}")
    print(f"  年化收益: {result.annual_return:.2%}")
    print(f"  夏普比率: {result.sharpe_ratio:.4f}")
    print(f"  索提诺比率: {result.sortino_ratio:.4f}")

    print(f"\n【风险指标】")
    print(f"  最大回撤: {result.max_drawdown:.2%}")
    print(f"  波动率: {result.volatility:.2%}")

    print(f"\n【交易统计】")
    print(f"  总交易次数: {result.total_trades}")
    print(f"  盈利次数: {result.win_trades}")
    print(f"  亏损次数: {result.lose_trades}")
    print(f"  胜率: {result.win_rate:.2%}")
    print(f"  盈亏比: {result.profit_factor:.4f}")
    print(f"  平均盈利: {result.avg_win:,.2f}")
    print(f"  平均亏损: {result.avg_loss:,.2f}")

    print("\n" + "=" * 60)
