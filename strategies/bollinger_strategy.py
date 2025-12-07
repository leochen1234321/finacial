"""
布林带策略
基于布林带的波动率交易策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger()


class BollingerStrategy(BaseStrategy):
    """
    布林带策略

    买入信号：价格触及下轨后反弹
    卖出信号：价格触及上轨后回落
    """

    def __init__(
        self,
        stocks: List[str] = None,
        period: int = 20,
        std_dev: float = 2.0,
        position_pct: float = 0.20,
        stop_loss_pct: float = 0.07,
        take_profit_pct: float = 0.14
    ):
        """
        初始化布林带策略

        Args:
            stocks: 监控的股票列表
            period: 移动平均周期
            std_dev: 标准差倍数
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        params = {
            'period': period,
            'std_dev': std_dev
        }

        super().__init__(
            name="布林带策略",
            stocks=stocks,
            params=params,
            position_pct=position_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )

    def calculate_signal(self, stock_code: str, data: pd.DataFrame) -> Dict:
        """
        计算交易信号
        """
        result = {
            'signal': 'hold',
            'strength': 0,
            'reason': '',
            'indicators': {}
        }

        if len(data) < self.params['period'] + 2:
            return result

        period = self.params['period']
        std_dev = self.params['std_dev']

        # 计算布林带
        middle = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        # 当前值
        curr_price = data['close'].iloc[-1]
        curr_upper = upper.iloc[-1]
        curr_middle = middle.iloc[-1]
        curr_lower = lower.iloc[-1]

        prev_price = data['close'].iloc[-2]
        prev_lower = lower.iloc[-2]
        prev_upper = upper.iloc[-2]

        # 计算带宽
        bandwidth = (curr_upper - curr_lower) / curr_middle

        result['indicators'] = {
            'upper': curr_upper,
            'middle': curr_middle,
            'lower': curr_lower,
            'bandwidth': bandwidth,
            'price': curr_price
        }

        # 计算价格在布林带中的位置 (0-1)
        if curr_upper != curr_lower:
            position_ratio = (curr_price - curr_lower) / (curr_upper - curr_lower)
            result['indicators']['position_ratio'] = position_ratio

        # 下轨反弹买入
        if prev_price <= prev_lower and curr_price > curr_lower:
            result['signal'] = 'buy'
            result['strength'] = 0.7
            result['reason'] = f"价格触及布林带下轨后反弹"
            logger.debug(f"[{self.name}] {stock_code} 下轨反弹")

        # 上轨回落卖出
        elif prev_price >= prev_upper and curr_price < curr_upper:
            result['signal'] = 'sell'
            result['strength'] = 0.7
            result['reason'] = f"价格触及布林带上轨后回落"
            logger.debug(f"[{self.name}] {stock_code} 上轨回落")

        # 突破下轨（极端超卖）
        elif curr_price < curr_lower:
            result['indicators']['extreme_oversold'] = True

        # 突破上轨（极端超买）
        elif curr_price > curr_upper:
            result['indicators']['extreme_overbought'] = True

        # 带宽收窄（预示大行情）
        if bandwidth < 0.1:
            result['indicators']['squeeze'] = True

        return result


class BollingerBreakoutStrategy(BaseStrategy):
    """
    布林带突破策略

    买入信号：价格向上突破上轨（趋势启动）
    卖出信号：价格跌破中轨
    """

    def __init__(
        self,
        stocks: List[str] = None,
        period: int = 20,
        std_dev: float = 2.0,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.20
    ):
        params = {
            'period': period,
            'std_dev': std_dev
        }

        super().__init__(
            name="布林带突破策略",
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

        if len(data) < self.params['period'] + 5:
            return result

        period = self.params['period']
        std_dev = self.params['std_dev']

        # 计算布林带
        middle = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        curr_price = data['close'].iloc[-1]
        curr_upper = upper.iloc[-1]
        curr_middle = middle.iloc[-1]
        curr_lower = lower.iloc[-1]
        prev_price = data['close'].iloc[-2]
        prev_upper = upper.iloc[-2]
        prev_middle = middle.iloc[-2]

        # 计算带宽变化（带宽扩张说明波动加大）
        curr_bandwidth = (curr_upper - curr_lower) / curr_middle
        prev_bandwidth = (upper.iloc[-2] - lower.iloc[-2]) / middle.iloc[-2]

        result['indicators'] = {
            'upper': curr_upper,
            'middle': curr_middle,
            'lower': curr_lower,
            'bandwidth': curr_bandwidth,
            'bandwidth_expanding': curr_bandwidth > prev_bandwidth
        }

        # 向上突破上轨（伴随带宽扩张）
        if prev_price <= prev_upper and curr_price > curr_upper:
            if curr_bandwidth > prev_bandwidth:  # 带宽扩张
                result['signal'] = 'buy'
                result['strength'] = 0.8
                result['reason'] = "价格突破布林带上轨，带宽扩张，趋势启动"
            else:
                result['indicators']['breakout_upper'] = True

        # 跌破中轨卖出
        elif prev_price >= prev_middle and curr_price < curr_middle:
            result['signal'] = 'sell'
            result['strength'] = 0.6
            result['reason'] = "价格跌破布林带中轨，趋势可能转弱"

        return result
