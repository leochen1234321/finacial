"""
风控管理模块
负责交易前风控检查和实时风控监控
"""

from datetime import datetime, date, time
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass

from utils.logger import get_logger, TradeLogger
from utils.database import DatabaseManager
from utils.notification import NotificationManager

logger = get_logger()
trade_logger = TradeLogger()


@dataclass
class RiskConfig:
    """风控配置"""
    # 单日最大亏损比例
    max_daily_loss_pct: float = 0.05

    # 单只股票最大仓位比例
    max_single_position_pct: float = 0.30

    # 总仓位上限比例
    max_total_position_pct: float = 0.80

    # 最大持股数量
    max_holding_stocks: int = 3

    # 默认止损比例
    default_stop_loss_pct: float = 0.10

    # 默认止盈比例
    default_take_profit_pct: float = 0.20

    # 最大回撤比例
    max_drawdown_pct: float = 0.15

    # 单笔最大交易金额
    max_single_trade_value: float = 50000

    # 是否允许追涨（涨幅超过阈值不买）
    allow_chase_rise: bool = False
    chase_rise_threshold: float = 0.05

    # 是否允许抄底（跌幅超过阈值不买）
    allow_catch_falling: bool = True
    catch_falling_threshold: float = -0.08


class RiskManager:
    """
    风控管理器
    负责交易风控检查和监控
    """

    def __init__(
        self,
        config: RiskConfig = None,
        db_manager: DatabaseManager = None,
        notification_manager: NotificationManager = None
    ):
        """
        初始化风控管理器

        Args:
            config: 风控配置
            db_manager: 数据库管理器
            notification_manager: 通知管理器
        """
        self.config = config or RiskConfig()
        self.db = db_manager
        self.notifier = notification_manager

        # 交易引擎引用（后续设置）
        self.engine = None

        # 当日统计
        self._today_start_value = None
        self._today_trades_count = 0
        self._today_buy_value = 0
        self._today_sell_value = 0

        # 最高净值（计算回撤用）
        self._peak_value = None

        # 风控开关
        self.enabled = True
        self.trading_halted = False
        self.halt_reason = ""

    def set_engine(self, engine):
        """设置交易引擎引用"""
        self.engine = engine

    def reset_daily_stats(self):
        """重置每日统计"""
        self._today_start_value = None
        self._today_trades_count = 0
        self._today_buy_value = 0
        self._today_sell_value = 0
        self.trading_halted = False
        self.halt_reason = ""
        logger.info("风控每日统计已重置")

    def check_buy_order(
        self,
        stock_code: str,
        price: float,
        amount: int,
        strategy: str = ""
    ) -> Dict:
        """
        买入订单风控检查

        Args:
            stock_code: 股票代码
            price: 买入价格
            amount: 买入数量
            strategy: 策略名称

        Returns:
            {'allowed': bool, 'reason': str}
        """
        result = {'allowed': True, 'reason': ''}

        if not self.enabled:
            return result

        # 检查是否已暂停交易
        if self.trading_halted:
            return {'allowed': False, 'reason': f"交易已暂停: {self.halt_reason}"}

        trade_value = price * amount

        # 1. 检查单笔交易金额
        if trade_value > self.config.max_single_trade_value:
            return {
                'allowed': False,
                'reason': f"单笔交易金额{trade_value:.2f}超过限制{self.config.max_single_trade_value:.2f}"
            }

        if not self.engine:
            return result

        # 获取账户信息
        balance = self.engine.get_balance()
        positions = self.engine.get_positions()

        total_assets = balance.get('total_assets', 0)
        available_cash = balance.get('available_cash', 0)
        market_value = balance.get('market_value', 0)

        # 2. 检查可用资金
        if trade_value > available_cash:
            return {'allowed': False, 'reason': f"可用资金不足: 需要{trade_value:.2f}, 可用{available_cash:.2f}"}

        # 3. 检查总仓位
        new_position_value = market_value + trade_value
        new_position_pct = new_position_value / total_assets if total_assets > 0 else 1
        if new_position_pct > self.config.max_total_position_pct:
            return {
                'allowed': False,
                'reason': f"总仓位将达到{new_position_pct:.1%}，超过限制{self.config.max_total_position_pct:.1%}"
            }

        # 4. 检查单只股票仓位
        existing_position = next((p for p in positions if p['stock_code'] == stock_code), None)
        existing_value = existing_position['market_value'] if existing_position else 0
        new_stock_value = existing_value + trade_value
        new_stock_pct = new_stock_value / total_assets if total_assets > 0 else 1
        if new_stock_pct > self.config.max_single_position_pct:
            return {
                'allowed': False,
                'reason': f"单股仓位将达到{new_stock_pct:.1%}，超过限制{self.config.max_single_position_pct:.1%}"
            }

        # 5. 检查持股数量
        if not existing_position:
            holding_count = len([p for p in positions if p['amount'] > 0])
            if holding_count >= self.config.max_holding_stocks:
                return {
                    'allowed': False,
                    'reason': f"持股数量{holding_count}已达上限{self.config.max_holding_stocks}"
                }

        # 6. 检查当日亏损
        if self._today_start_value:
            current_value = self.engine.get_balance().get('total_assets', 0)
            daily_loss_pct = (current_value - self._today_start_value) / self._today_start_value
            if daily_loss_pct < -self.config.max_daily_loss_pct:
                self._halt_trading(f"当日亏损{daily_loss_pct:.2%}超过限制")
                return {'allowed': False, 'reason': self.halt_reason}

        # 7. 检查追涨（可选）
        if not self.config.allow_chase_rise and self.engine.data_manager:
            quote = self.engine.data_manager.get_realtime_quote(stock_code)
            if quote and quote.get('change_pct', 0) > self.config.chase_rise_threshold:
                return {
                    'allowed': False,
                    'reason': f"股票涨幅{quote['change_pct']:.2%}超过追涨阈值{self.config.chase_rise_threshold:.2%}"
                }

        return result

    def check_sell_order(
        self,
        stock_code: str,
        price: float,
        amount: int,
        strategy: str = ""
    ) -> Dict:
        """
        卖出订单风控检查

        Args:
            stock_code: 股票代码
            price: 卖出价格
            amount: 卖出数量
            strategy: 策略名称

        Returns:
            {'allowed': bool, 'reason': str}
        """
        result = {'allowed': True, 'reason': ''}

        if not self.enabled:
            return result

        if not self.engine:
            return result

        # 检查持仓
        position = self.engine.get_position(stock_code)
        if not position:
            return {'allowed': False, 'reason': f"无持仓: {stock_code}"}

        available = position.get('available', position.get('amount', 0))
        if amount > available:
            return {'allowed': False, 'reason': f"可卖数量不足: 需要{amount}, 可卖{available}"}

        return result

    def check_position_risk(self, position: Dict) -> Dict:
        """
        检查单个持仓的风险状态

        Args:
            position: 持仓信息

        Returns:
            {'stop_loss': bool, 'take_profit': bool, 'reason': str}
        """
        result = {'stop_loss': False, 'take_profit': False, 'reason': ''}

        profit_pct = position.get('profit_pct', 0)

        # 检查止损
        if profit_pct < -self.config.default_stop_loss_pct:
            result['stop_loss'] = True
            result['reason'] = f"触发止损: 亏损{profit_pct:.2%}"

        # 检查止盈
        elif profit_pct > self.config.default_take_profit_pct:
            result['take_profit'] = True
            result['reason'] = f"触发止盈: 盈利{profit_pct:.2%}"

        return result

    def update(self):
        """
        更新风控状态（定时调用）
        """
        if not self.enabled or not self.engine:
            return

        # 初始化当日起始净值
        if self._today_start_value is None:
            balance = self.engine.get_balance()
            self._today_start_value = balance.get('total_assets', 0)
            self._peak_value = self._today_start_value
            logger.info(f"风控初始化，当日起始净值: {self._today_start_value:.2f}")

        # 获取当前状态
        balance = self.engine.get_balance()
        positions = self.engine.get_positions()
        current_value = balance.get('total_assets', 0)

        # 更新最高净值
        if current_value > self._peak_value:
            self._peak_value = current_value

        # 1. 检查当日亏损
        if self._today_start_value > 0:
            daily_loss_pct = (current_value - self._today_start_value) / self._today_start_value
            if daily_loss_pct < -self.config.max_daily_loss_pct and not self.trading_halted:
                self._halt_trading(f"当日亏损{daily_loss_pct:.2%}超过限制{self.config.max_daily_loss_pct:.2%}")
                self._record_risk_event(
                    event_type="当日亏损超限",
                    trigger_value=daily_loss_pct,
                    threshold_value=-self.config.max_daily_loss_pct,
                    action_taken="暂停交易"
                )

        # 2. 检查最大回撤
        if self._peak_value > 0:
            drawdown = (self._peak_value - current_value) / self._peak_value
            if drawdown > self.config.max_drawdown_pct and not self.trading_halted:
                self._halt_trading(f"回撤{drawdown:.2%}超过限制{self.config.max_drawdown_pct:.2%}")
                self._record_risk_event(
                    event_type="最大回撤超限",
                    trigger_value=drawdown,
                    threshold_value=self.config.max_drawdown_pct,
                    action_taken="暂停交易"
                )

        # 3. 检查各持仓止损止盈
        for position in positions:
            risk_status = self.check_position_risk(position)

            if risk_status['stop_loss']:
                stock_code = position['stock_code']
                stock_name = position.get('stock_name', '')
                profit_pct = position.get('profit_pct', 0)

                logger.warning(f"止损触发: {stock_code} {stock_name}, 亏损{profit_pct:.2%}")

                # 记录风控事件
                self._record_risk_event(
                    event_type="止损触发",
                    stock_code=stock_code,
                    trigger_value=profit_pct,
                    threshold_value=-self.config.default_stop_loss_pct,
                    action_taken="卖出平仓",
                    details=f"{stock_name} 亏损{profit_pct:.2%}"
                )

                # 执行止损（如果引擎可用）
                if self.engine:
                    self.engine.close_position(
                        stock_code=stock_code,
                        strategy="风控止损",
                        reason=risk_status['reason']
                    )

            elif risk_status['take_profit']:
                stock_code = position['stock_code']
                stock_name = position.get('stock_name', '')
                profit_pct = position.get('profit_pct', 0)

                logger.info(f"止盈触发: {stock_code} {stock_name}, 盈利{profit_pct:.2%}")

                # 记录风控事件
                self._record_risk_event(
                    event_type="止盈触发",
                    stock_code=stock_code,
                    trigger_value=profit_pct,
                    threshold_value=self.config.default_take_profit_pct,
                    action_taken="卖出平仓",
                    details=f"{stock_name} 盈利{profit_pct:.2%}"
                )

                # 执行止盈
                if self.engine:
                    self.engine.close_position(
                        stock_code=stock_code,
                        strategy="风控止盈",
                        reason=risk_status['reason']
                    )

    def _halt_trading(self, reason: str):
        """暂停交易"""
        self.trading_halted = True
        self.halt_reason = reason
        logger.warning(f"风控暂停交易: {reason}")

        # 发送通知
        if self.notifier:
            self.notifier.notify_risk_warning(
                event_type="交易暂停",
                details=reason,
                action_taken="已暂停所有交易"
            )

        trade_logger.log_risk("交易暂停", reason)

    def _record_risk_event(
        self,
        event_type: str,
        trigger_value: float,
        threshold_value: float,
        action_taken: str,
        stock_code: str = None,
        strategy: str = None,
        details: str = ""
    ):
        """记录风控事件"""
        if self.db:
            self.db.record_risk_event(
                event_type=event_type,
                stock_code=stock_code,
                strategy=strategy,
                trigger_value=trigger_value,
                threshold_value=threshold_value,
                action_taken=action_taken,
                details=details
            )

        # 发送通知
        if self.notifier:
            self.notifier.notify_risk_warning(
                event_type=event_type,
                details=details or f"触发值:{trigger_value:.2%}, 阈值:{threshold_value:.2%}",
                action_taken=action_taken
            )

    def get_risk_status(self) -> Dict:
        """
        获取当前风控状态

        Returns:
            风控状态字典
        """
        status = {
            'enabled': self.enabled,
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'today_start_value': self._today_start_value,
            'peak_value': self._peak_value,
            'daily_pnl': 0,
            'daily_pnl_pct': 0,
            'drawdown': 0,
            'drawdown_pct': 0
        }

        if self.engine:
            balance = self.engine.get_balance()
            current_value = balance.get('total_assets', 0)

            if self._today_start_value and self._today_start_value > 0:
                status['daily_pnl'] = current_value - self._today_start_value
                status['daily_pnl_pct'] = status['daily_pnl'] / self._today_start_value

            if self._peak_value and self._peak_value > 0:
                status['drawdown'] = self._peak_value - current_value
                status['drawdown_pct'] = status['drawdown'] / self._peak_value

        return status

    def set_stop_loss(self, stock_code: str, stop_loss_pct: float):
        """设置个股止损比例"""
        # 可以扩展为支持个股独立止损设置
        pass

    def set_take_profit(self, stock_code: str, take_profit_pct: float):
        """设置个股止盈比例"""
        # 可以扩展为支持个股独立止盈设置
        pass
