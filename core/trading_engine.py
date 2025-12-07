"""
实盘交易引擎模块
基于easytrader实现自动化交易
"""

import time
from datetime import datetime, date
from typing import Optional, List, Dict, Callable
from enum import Enum
import threading

from utils.logger import get_logger, TradeLogger
from utils.database import DatabaseManager
from utils.notification import NotificationManager
from .data_manager import DataManager
from .risk_manager import RiskManager

logger = get_logger()
trade_logger = TradeLogger()


class TradingStatus(Enum):
    """交易引擎状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class TradingEngine:
    """
    实盘交易引擎
    负责连接券商、执行交易、管理订单
    """

    def __init__(
        self,
        broker: str = "ths",
        client_path: str = None,
        data_manager: DataManager = None,
        risk_manager: RiskManager = None,
        db_manager: DatabaseManager = None,
        notification_manager: NotificationManager = None,
        simulate: bool = True
    ):
        """
        初始化交易引擎

        Args:
            broker: 券商类型 (ths同花顺/universal通用)
            client_path: 券商客户端路径
            data_manager: 数据管理器
            risk_manager: 风控管理器
            db_manager: 数据库管理器
            notification_manager: 通知管理器
            simulate: 是否模拟交易（不实际下单）
        """
        self.broker = broker
        self.client_path = client_path
        self.data_manager = data_manager
        self.risk_manager = risk_manager
        self.db = db_manager
        self.notifier = notification_manager
        self.simulate = simulate

        self.status = TradingStatus.STOPPED
        self.user = None  # easytrader用户对象
        self.strategies: Dict[str, object] = {}  # 策略实例
        self._running = False
        self._thread = None

        # 账户信息缓存
        self._balance_cache = None
        self._position_cache = None
        self._cache_time = None
        self._cache_ttl = 5  # 缓存5秒

    def connect(self) -> bool:
        """
        连接券商客户端

        Returns:
            是否连接成功
        """
        if self.simulate:
            logger.info("模拟模式：跳过券商连接")
            self.status = TradingStatus.RUNNING
            return True

        try:
            import easytrader

            self.user = easytrader.use(self.broker)
            self.user.connect(self.client_path)

            # 验证连接
            balance = self.user.balance
            logger.info(f"券商连接成功，账户资金: {balance}")

            self.status = TradingStatus.RUNNING
            return True

        except ImportError:
            logger.error("请安装easytrader: pip install easytrader")
            self.status = TradingStatus.ERROR
            return False
        except Exception as e:
            logger.error(f"券商连接失败: {e}")
            self.status = TradingStatus.ERROR
            return False

    def disconnect(self):
        """断开连接"""
        self.stop()
        self.user = None
        self.status = TradingStatus.STOPPED
        logger.info("已断开券商连接")

    def get_balance(self, use_cache: bool = True) -> Dict:
        """
        获取账户余额

        Returns:
            账户余额信息字典
        """
        now = datetime.now()

        # 检查缓存
        if use_cache and self._balance_cache and self._cache_time:
            if (now - self._cache_time).seconds < self._cache_ttl:
                return self._balance_cache

        if self.simulate:
            # 模拟数据
            balance = {
                'total_assets': 100000,
                'available_cash': 50000,
                'market_value': 50000,
                'frozen': 0
            }
        else:
            try:
                raw_balance = self.user.balance
                balance = {
                    'total_assets': float(raw_balance.get('总资产', 0) or raw_balance.get('资产', 0)),
                    'available_cash': float(raw_balance.get('可用资金', 0) or raw_balance.get('可用', 0)),
                    'market_value': float(raw_balance.get('股票市值', 0) or raw_balance.get('市值', 0)),
                    'frozen': float(raw_balance.get('冻结资金', 0) or 0)
                }
            except Exception as e:
                logger.error(f"获取账户余额失败: {e}")
                return {}

        self._balance_cache = balance
        self._cache_time = now
        return balance

    def get_positions(self, use_cache: bool = True) -> List[Dict]:
        """
        获取持仓列表

        Returns:
            持仓列表
        """
        now = datetime.now()

        if use_cache and self._position_cache and self._cache_time:
            if (now - self._cache_time).seconds < self._cache_ttl:
                return self._position_cache

        if self.simulate:
            # 从数据库读取模拟持仓
            if self.db:
                positions = self.db.get_positions()
            else:
                positions = []
        else:
            try:
                raw_positions = self.user.position
                positions = []
                for pos in raw_positions:
                    positions.append({
                        'stock_code': pos.get('证券代码', ''),
                        'stock_name': pos.get('证券名称', ''),
                        'amount': int(pos.get('股票余额', 0) or pos.get('持仓量', 0)),
                        'available': int(pos.get('可用余额', 0) or pos.get('可卖', 0)),
                        'cost_price': float(pos.get('成本价', 0) or pos.get('买入均价', 0)),
                        'current_price': float(pos.get('市价', 0) or pos.get('当前价', 0)),
                        'market_value': float(pos.get('市值', 0)),
                        'profit': float(pos.get('盈亏', 0) or pos.get('浮动盈亏', 0)),
                        'profit_pct': float(pos.get('盈亏比例', 0) or 0) / 100
                    })
            except Exception as e:
                logger.error(f"获取持仓失败: {e}")
                return []

        self._position_cache = positions
        self._cache_time = now
        return positions

    def get_position(self, stock_code: str) -> Optional[Dict]:
        """获取指定股票持仓"""
        positions = self.get_positions()
        for pos in positions:
            if pos['stock_code'] == stock_code:
                return pos
        return None

    def buy(
        self,
        stock_code: str,
        price: float = None,
        amount: int = None,
        percent: float = None,
        strategy: str = "",
        reason: str = ""
    ) -> Dict:
        """
        买入股票

        Args:
            stock_code: 股票代码
            price: 买入价格（None为市价）
            amount: 买入数量
            percent: 按可用资金比例买入
            strategy: 策略名称
            reason: 买入原因

        Returns:
            交易结果字典
        """
        result = {'success': False, 'message': '', 'order_id': None}

        # 检查交易时间
        if self.data_manager and not self.data_manager.is_safe_trading_time():
            result['message'] = "非安全交易时间"
            logger.warning(result['message'])
            return result

        # 获取当前价格
        if price is None:
            quote = self.data_manager.get_realtime_quote(stock_code) if self.data_manager else None
            if quote:
                price = quote['price']
            else:
                result['message'] = "无法获取当前价格"
                return result

        # 计算数量
        if amount is None and percent:
            balance = self.get_balance()
            available_cash = balance.get('available_cash', 0)
            amount = int(available_cash * percent / price) // 100 * 100

        if amount <= 0:
            result['message'] = "买入数量无效"
            return result

        # 风控检查
        if self.risk_manager:
            risk_check = self.risk_manager.check_buy_order(
                stock_code=stock_code,
                price=price,
                amount=amount
            )
            if not risk_check['allowed']:
                result['message'] = f"风控拒绝: {risk_check['reason']}"
                logger.warning(result['message'])
                return result

        # 获取股票名称
        stock_name = ""
        if self.data_manager:
            stock_name = self.data_manager.get_stock_name(stock_code)

        # 执行买入
        if self.simulate:
            logger.info(f"[模拟买入] {stock_code} {stock_name} 价格:{price:.2f} 数量:{amount}")
            result['success'] = True
            result['message'] = "模拟买入成功"
            result['order_id'] = f"SIM_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            try:
                order_result = self.user.buy(stock_code, price=price, amount=amount)
                result['success'] = True
                result['message'] = "买入委托成功"
                result['order_id'] = order_result.get('委托编号')
                logger.info(f"买入委托: {stock_code} 价格:{price} 数量:{amount}")
            except Exception as e:
                result['message'] = f"买入失败: {e}"
                logger.error(result['message'])

        # 记录交易
        if result['success'] and self.db:
            self.db.insert_trade(
                stock_code=stock_code,
                stock_name=stock_name,
                action='buy',
                price=price,
                amount=amount,
                strategy=strategy,
                signal_reason=reason,
                status='success' if result['success'] else 'failed',
                error_msg=result['message'] if not result['success'] else ''
            )

        # 记录日志
        trade_logger.log_order(
            action='买入',
            stock_code=stock_code,
            stock_name=stock_name,
            price=price,
            amount=amount,
            strategy=strategy,
            reason=reason
        )

        # 发送通知
        if result['success'] and self.notifier:
            self.notifier.notify_trade(
                action='buy',
                stock_code=stock_code,
                stock_name=stock_name,
                price=price,
                amount=amount,
                strategy=strategy
            )

        return result

    def sell(
        self,
        stock_code: str,
        price: float = None,
        amount: int = None,
        percent: float = None,
        strategy: str = "",
        reason: str = ""
    ) -> Dict:
        """
        卖出股票

        Args:
            stock_code: 股票代码
            price: 卖出价格（None为市价）
            amount: 卖出数量
            percent: 按持仓比例卖出
            strategy: 策略名称
            reason: 卖出原因

        Returns:
            交易结果字典
        """
        result = {'success': False, 'message': '', 'order_id': None}

        # 检查持仓
        position = self.get_position(stock_code)
        if not position:
            result['message'] = f"无持仓: {stock_code}"
            return result

        available = position.get('available', position.get('amount', 0))

        # 计算数量
        if amount is None:
            if percent:
                amount = int(available * percent) // 100 * 100
            else:
                amount = available

        amount = min(amount, available)
        if amount <= 0:
            result['message'] = "可卖数量不足"
            return result

        # 获取当前价格
        if price is None:
            quote = self.data_manager.get_realtime_quote(stock_code) if self.data_manager else None
            if quote:
                price = quote['price']
            else:
                price = position.get('current_price', 0)

        stock_name = position.get('stock_name', '')

        # 执行卖出
        if self.simulate:
            logger.info(f"[模拟卖出] {stock_code} {stock_name} 价格:{price:.2f} 数量:{amount}")
            result['success'] = True
            result['message'] = "模拟卖出成功"
            result['order_id'] = f"SIM_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            try:
                order_result = self.user.sell(stock_code, price=price, amount=amount)
                result['success'] = True
                result['message'] = "卖出委托成功"
                result['order_id'] = order_result.get('委托编号')
                logger.info(f"卖出委托: {stock_code} 价格:{price} 数量:{amount}")
            except Exception as e:
                result['message'] = f"卖出失败: {e}"
                logger.error(result['message'])

        # 记录交易
        if result['success'] and self.db:
            self.db.insert_trade(
                stock_code=stock_code,
                stock_name=stock_name,
                action='sell',
                price=price,
                amount=amount,
                strategy=strategy,
                signal_reason=reason,
                status='success' if result['success'] else 'failed',
                error_msg=result['message'] if not result['success'] else ''
            )

        # 记录日志
        trade_logger.log_order(
            action='卖出',
            stock_code=stock_code,
            stock_name=stock_name,
            price=price,
            amount=amount,
            strategy=strategy,
            reason=reason
        )

        # 发送通知
        if result['success'] and self.notifier:
            self.notifier.notify_trade(
                action='sell',
                stock_code=stock_code,
                stock_name=stock_name,
                price=price,
                amount=amount,
                strategy=strategy
            )

        return result

    def close_position(self, stock_code: str, strategy: str = "", reason: str = "") -> Dict:
        """平仓"""
        return self.sell(stock_code, percent=1.0, strategy=strategy, reason=reason)

    def register_strategy(self, name: str, strategy):
        """
        注册策略

        Args:
            name: 策略名称
            strategy: 策略实例
        """
        self.strategies[name] = strategy
        strategy.set_engine(self)
        logger.info(f"注册策略: {name}")

    def unregister_strategy(self, name: str):
        """注销策略"""
        if name in self.strategies:
            del self.strategies[name]
            logger.info(f"注销策略: {name}")

    def start(self, interval: float = 5.0):
        """
        启动交易引擎

        Args:
            interval: 策略执行间隔（秒）
        """
        if self._running:
            logger.warning("交易引擎已在运行")
            return

        self._running = True
        self.status = TradingStatus.RUNNING
        self._thread = threading.Thread(target=self._run_loop, args=(interval,), daemon=True)
        self._thread.start()
        logger.info(f"交易引擎已启动，执行间隔: {interval}秒")

    def stop(self):
        """停止交易引擎"""
        self._running = False
        self.status = TradingStatus.STOPPED
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("交易引擎已停止")

    def pause(self):
        """暂停交易"""
        self.status = TradingStatus.PAUSED
        logger.info("交易引擎已暂停")

    def resume(self):
        """恢复交易"""
        self.status = TradingStatus.RUNNING
        logger.info("交易引擎已恢复")

    def _run_loop(self, interval: float):
        """主循环"""
        while self._running:
            try:
                if self.status == TradingStatus.RUNNING:
                    # 检查是否为交易时间
                    if self.data_manager and self.data_manager.is_trading_time():
                        self._execute_strategies()

                        # 更新风控状态
                        if self.risk_manager:
                            self.risk_manager.update()

                time.sleep(interval)

            except Exception as e:
                logger.error(f"交易循环错误: {e}")
                time.sleep(interval)

    def _execute_strategies(self):
        """执行所有策略"""
        for name, strategy in self.strategies.items():
            try:
                if hasattr(strategy, 'enabled') and not strategy.enabled:
                    continue

                strategy.on_tick()

            except Exception as e:
                logger.error(f"策略执行错误 [{name}]: {e}")

    def get_today_trades(self) -> List[Dict]:
        """获取今日成交"""
        if self.simulate:
            if self.db:
                return self.db.get_today_trades()
            return []

        try:
            return self.user.today_trades
        except Exception as e:
            logger.error(f"获取今日成交失败: {e}")
            return []

    def get_today_entrusts(self) -> List[Dict]:
        """获取今日委托"""
        if self.simulate:
            return []

        try:
            return self.user.today_entrusts
        except Exception as e:
            logger.error(f"获取今日委托失败: {e}")
            return []

    def cancel_entrust(self, entrust_no: str) -> bool:
        """撤销委托"""
        if self.simulate:
            logger.info(f"[模拟撤单] {entrust_no}")
            return True

        try:
            self.user.cancel_entrust(entrust_no)
            logger.info(f"撤单成功: {entrust_no}")
            return True
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False
