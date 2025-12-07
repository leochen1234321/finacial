"""
双均线策略
基于短期和长期均线交叉的趋势跟踪策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger()


class MAStrategy(BaseStrategy):
    """
    双均线策略

    买入信号：短期均线上穿长期均线（金叉）
    卖出信号：短期均线下穿长期均线（死叉）
    """

    def __init__(
        self,
        stocks: List[str] = None,
        fast_period: int = 5,
        slow_period: int = 20,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.15
    ):
        """
        初始化双均线策略

        Args:
            stocks: 监控的股票列表
            fast_period: 快线周期
            slow_period: 慢线周期
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        params = {
            'fast_period': fast_period,
            'slow_period': slow_period
        }

        super().__init__(
            name="双均线策略",
            stocks=stocks,
            params=params,
            position_pct=position_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )

    def calculate_signal(self, stock_code: str, data: pd.DataFrame) -> Dict:
        """
        计算交易信号

        Args:
            stock_code: 股票代码
            data: K线数据

        Returns:
            信号字典
        """
        result = {
            'signal': 'hold',
            'strength': 0,
            'reason': '',
            'indicators': {}
        }

        if len(data) < self.params['slow_period'] + 2:
            return result

        fast_period = self.params['fast_period']
        slow_period = self.params['slow_period']

        # 计算均线
        ma_fast = data['close'].rolling(window=fast_period).mean()
        ma_slow = data['close'].rolling(window=slow_period).mean()

        # 当前值
        current_fast = ma_fast.iloc[-1]
        current_slow = ma_slow.iloc[-1]
        prev_fast = ma_fast.iloc[-2]
        prev_slow = ma_slow.iloc[-2]
        current_price = data['close'].iloc[-1]

        result['indicators'] = {
            f'ma{fast_period}': current_fast,
            f'ma{slow_period}': current_slow,
            'price': current_price
        }

        # 判断金叉/死叉
        if prev_fast <= prev_slow and current_fast > current_slow:
            # 金叉买入
            strength = (current_fast - current_slow) / current_slow
            result['signal'] = 'buy'
            result['strength'] = min(abs(strength), 1)
            result['reason'] = f"MA{fast_period}上穿MA{slow_period}，金叉买入"
            logger.debug(f"[{self.name}] {stock_code} 金叉信号")

        elif prev_fast >= prev_slow and current_fast < current_slow:
            # 死叉卖出
            strength = (current_slow - current_fast) / current_slow
            result['signal'] = 'sell'
            result['strength'] = min(abs(strength), 1)
            result['reason'] = f"MA{fast_period}下穿MA{slow_period}，死叉卖出"
            logger.debug(f"[{self.name}] {stock_code} 死叉信号")

        # 趋势强度判断
        elif current_fast > current_slow:
            # 多头趋势
            trend_strength = (current_fast - current_slow) / current_slow
            if trend_strength > 0.02:  # 趋势较强时考虑加仓
                result['indicators']['trend'] = 'bullish'
                result['indicators']['trend_strength'] = trend_strength

        elif current_fast < current_slow:
            # 空头趋势
            trend_strength = (current_slow - current_fast) / current_slow
            if trend_strength > 0.02:  # 趋势较强时考虑减仓
                result['indicators']['trend'] = 'bearish'
                result['indicators']['trend_strength'] = trend_strength

        return result


class TripleMAStrategy(BaseStrategy):
    """
    三均线策略

    使用短、中、长三条均线判断趋势
    买入：短线>中线>长线，且短线上穿中线
    卖出：短线<中线<长线，且短线下穿中线
    """

    def __init__(
        self,
        stocks: List[str] = None,
        fast_period: int = 5,
        mid_period: int = 10,
        slow_period: int = 20,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.15
    ):
        params = {
            'fast_period': fast_period,
            'mid_period': mid_period,
            'slow_period': slow_period
        }

        super().__init__(
            name="三均线策略",
            stocks=stocks,
            params=params,
            position_pct=position_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )

    def calculate_signal(self, stock_code: str, data: pd.DataFrame) -> Dict:
        result = {
            'signal': 'hold',
            'strength': 0,
            'reason': '',
            'indicators': {}
        }

        if len(data) < self.params['slow_period'] + 2:
            return result

        fast = self.params['fast_period']
        mid = self.params['mid_period']
        slow = self.params['slow_period']

        ma_fast = data['close'].rolling(window=fast).mean()
        ma_mid = data['close'].rolling(window=mid).mean()
        ma_slow = data['close'].rolling(window=slow).mean()

        curr_fast = ma_fast.iloc[-1]
        curr_mid = ma_mid.iloc[-1]
        curr_slow = ma_slow.iloc[-1]
        prev_fast = ma_fast.iloc[-2]
        prev_mid = ma_mid.iloc[-2]

        result['indicators'] = {
            f'ma{fast}': curr_fast,
            f'ma{mid}': curr_mid,
            f'ma{slow}': curr_slow
        }

        # 多头排列且金叉
        if curr_fast > curr_mid > curr_slow:
            if prev_fast <= prev_mid and curr_fast > curr_mid:
                result['signal'] = 'buy'
                result['strength'] = 0.8
                result['reason'] = f"三线多头排列，MA{fast}上穿MA{mid}"

        # 空头排列且死叉
        elif curr_fast < curr_mid < curr_slow:
            if prev_fast >= prev_mid and curr_fast < curr_mid:
                result['signal'] = 'sell'
                result['strength'] = 0.8
                result['reason'] = f"三线空头排列，MA{fast}下穿MA{mid}"

        return result
