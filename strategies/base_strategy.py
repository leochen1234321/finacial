"""
策略基类模块
定义策略的基本接口和通用功能
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np

from utils.logger import get_logger, TradeLogger

logger = get_logger()
trade_logger = TradeLogger()


class BaseStrategy(ABC):
    """
    策略基类
    所有策略都应继承此类并实现相关方法
    """

    def __init__(
        self,
        name: str,
        stocks: List[str] = None,
        params: Dict = None,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.15
    ):
        """
        初始化策略

        Args:
            name: 策略名称
            stocks: 监控的股票列表
            params: 策略参数
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        self.name = name
        self.stocks = stocks or []
        self.params = params or {}
        self.position_pct = position_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

        # 引擎引用
        self.engine = None
        self.backtest_engine = None

        # 状态
        self.enabled = True
        self.initialized = False

        # 信号记录
        self.last_signals: Dict[str, str] = {}  # {stock_code: signal}

    def set_engine(self, engine):
        """设置交易引擎"""
        self.engine = engine

    def initialize(self, backtest_engine=None):
        """
        初始化策略（回测时调用）

        Args:
            backtest_engine: 回测引擎实例
        """
        self.backtest_engine = backtest_engine
        self.initialized = True
        self.on_init()

    def on_init(self):
        """初始化回调，子类可重写"""
        pass

    @abstractmethod
    def calculate_signal(self, stock_code: str, data: pd.DataFrame) -> Dict:
        """
        计算交易信号

        Args:
            stock_code: 股票代码
            data: K线数据（包含技术指标）

        Returns:
            {
                'signal': 'buy'/'sell'/'hold',
                'strength': 信号强度 0-1,
                'reason': 信号原因,
                'indicators': {指标名: 指标值}
            }
        """
        pass

    def on_bar(self, bar_data: Dict[str, pd.Series]):
        """
        K线回调（回测模式）

        Args:
            bar_data: {stock_code: Series} 当前K线数据
        """
        for stock_code in self.stocks:
            if stock_code not in bar_data:
                continue

            # 获取历史数据并计算信号
            history = self._get_history_data(stock_code)
            if history is None or len(history) < 30:
                continue

            signal_result = self.calculate_signal(stock_code, history)
            signal = signal_result.get('signal', 'hold')
            reason = signal_result.get('reason', '')

            # 执行交易
            if signal == 'buy':
                self._do_buy(stock_code, reason)
            elif signal == 'sell':
                self._do_sell(stock_code, reason)

    def on_tick(self):
        """
        Tick回调（实盘模式）
        每个执行周期调用一次
        """
        if not self.enabled or not self.engine:
            return

        for stock_code in self.stocks:
            try:
                # 获取历史数据
                data_manager = self.engine.data_manager
                if not data_manager:
                    continue

                history = data_manager.get_history_klines(stock_code)
                if history is None or len(history) < 30:
                    continue

                # 计算技术指标
                history = data_manager.calculate_indicators(history)

                # 计算信号
                signal_result = self.calculate_signal(stock_code, history)
                signal = signal_result.get('signal', 'hold')
                reason = signal_result.get('reason', '')
                indicators = signal_result.get('indicators', {})

                # 记录信号
                if signal != 'hold':
                    trade_logger.log_signal(
                        stock_code=stock_code,
                        strategy=self.name,
                        signal=signal,
                        indicators=indicators
                    )

                # 检查信号变化
                last_signal = self.last_signals.get(stock_code, 'hold')
                if signal != last_signal and signal != 'hold':
                    self.last_signals[stock_code] = signal

                    # 执行交易
                    if signal == 'buy':
                        self._live_buy(stock_code, reason)
                    elif signal == 'sell':
                        self._live_sell(stock_code, reason)

            except Exception as e:
                logger.error(f"策略执行错误 [{self.name}] {stock_code}: {e}")

    def _get_history_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """获取历史数据（回测模式）"""
        if not self.backtest_engine:
            return None

        if stock_code not in self.backtest_engine.history_data:
            return None

        df = self.backtest_engine.history_data[stock_code].copy()
        current_date = self.backtest_engine.current_date

        # 只返回当前日期之前的数据
        df_dates = pd.to_datetime(df['date']).dt.date
        df = df[df_dates <= current_date]

        # 计算技术指标
        df = self._calculate_indicators(df)

        return df

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        if df.empty:
            return df

        df = df.copy()

        # MA
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()

        # MACD
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = df['ema12'] - df['ema26']
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['dif'] - df['dea'])

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        df['boll_mid'] = df['close'].rolling(window=20).mean()
        df['boll_std'] = df['close'].rolling(window=20).std()
        df['boll_upper'] = df['boll_mid'] + 2 * df['boll_std']
        df['boll_lower'] = df['boll_mid'] - 2 * df['boll_std']

        # KDJ
        low_list = df['low'].rolling(window=9).min()
        high_list = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_list) / (high_list - low_list) * 100
        df['kdj_k'] = rsv.ewm(com=2, adjust=False).mean()
        df['kdj_d'] = df['kdj_k'].ewm(com=2, adjust=False).mean()
        df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

        return df

    def _do_buy(self, stock_code: str, reason: str):
        """执行买入（回测模式）"""
        if not self.backtest_engine:
            return

        # 检查是否已持仓
        position = self.backtest_engine.get_position(stock_code)
        if position:
            return

        self.backtest_engine.buy(
            stock_code=stock_code,
            percent=self.position_pct,
            reason=f"[{self.name}] {reason}"
        )

    def _do_sell(self, stock_code: str, reason: str):
        """执行卖出（回测模式）"""
        if not self.backtest_engine:
            return

        # 检查是否有持仓
        position = self.backtest_engine.get_position(stock_code)
        if not position:
            return

        self.backtest_engine.close_position(
            stock_code=stock_code,
            reason=f"[{self.name}] {reason}"
        )

    def _live_buy(self, stock_code: str, reason: str):
        """执行买入（实盘模式）"""
        if not self.engine:
            return

        # 检查是否已持仓
        position = self.engine.get_position(stock_code)
        if position and position.get('amount', 0) > 0:
            return

        self.engine.buy(
            stock_code=stock_code,
            percent=self.position_pct,
            strategy=self.name,
            reason=reason
        )

    def _live_sell(self, stock_code: str, reason: str):
        """执行卖出（实盘模式）"""
        if not self.engine:
            return

        # 检查是否有持仓
        position = self.engine.get_position(stock_code)
        if not position or position.get('available', 0) <= 0:
            return

        self.engine.close_position(
            stock_code=stock_code,
            strategy=self.name,
            reason=reason
        )

    def check_stop_loss(self, stock_code: str, current_price: float, cost_price: float) -> bool:
        """检查止损"""
        if cost_price <= 0:
            return False
        profit_pct = (current_price - cost_price) / cost_price
        return profit_pct < -self.stop_loss_pct

    def check_take_profit(self, stock_code: str, current_price: float, cost_price: float) -> bool:
        """检查止盈"""
        if cost_price <= 0:
            return False
        profit_pct = (current_price - cost_price) / cost_price
        return profit_pct > self.take_profit_pct

    def get_status(self) -> Dict:
        """获取策略状态"""
        return {
            'name': self.name,
            'enabled': self.enabled,
            'stocks': self.stocks,
            'params': self.params,
            'position_pct': self.position_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'last_signals': self.last_signals
        }

    def update_params(self, params: Dict):
        """更新策略参数"""
        self.params.update(params)
        logger.info(f"策略参数已更新: {self.name}, {params}")

    def add_stock(self, stock_code: str):
        """添加监控股票"""
        if stock_code not in self.stocks:
            self.stocks.append(stock_code)
            logger.info(f"添加监控股票: {self.name} - {stock_code}")

    def remove_stock(self, stock_code: str):
        """移除监控股票"""
        if stock_code in self.stocks:
            self.stocks.remove(stock_code)
            logger.info(f"移除监控股票: {self.name} - {stock_code}")
