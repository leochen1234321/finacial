"""
MACD策略
基于MACD指标的动量交易策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger()


class MACDStrategy(BaseStrategy):
    """
    MACD策略

    买入信号：
    1. DIF上穿DEA（金叉）
    2. MACD柱由负转正

    卖出信号：
    1. DIF下穿DEA（死叉）
    2. MACD柱由正转负
    """

    def __init__(
        self,
        stocks: List[str] = None,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.15
    ):
        """
        初始化MACD策略

        Args:
            stocks: 监控的股票列表
            fast_period: 快线EMA周期
            slow_period: 慢线EMA周期
            signal_period: 信号线周期
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        params = {
            'fast_period': fast_period,
            'slow_period': slow_period,
            'signal_period': signal_period
        }

        super().__init__(
            name="MACD策略",
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

        min_length = self.params['slow_period'] + self.params['signal_period'] + 2
        if len(data) < min_length:
            return result

        fast = self.params['fast_period']
        slow = self.params['slow_period']
        signal = self.params['signal_period']

        # 计算MACD
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd = 2 * (dif - dea)

        # 当前和前一值
        curr_dif = dif.iloc[-1]
        curr_dea = dea.iloc[-1]
        curr_macd = macd.iloc[-1]
        prev_dif = dif.iloc[-2]
        prev_dea = dea.iloc[-2]
        prev_macd = macd.iloc[-2]

        result['indicators'] = {
            'dif': curr_dif,
            'dea': curr_dea,
            'macd': curr_macd
        }

        # 金叉买入
        if prev_dif <= prev_dea and curr_dif > curr_dea:
            # 零轴上方金叉信号更强
            if curr_dif > 0:
                result['signal'] = 'buy'
                result['strength'] = 0.9
                result['reason'] = "MACD零轴上方金叉，强势买入"
            else:
                result['signal'] = 'buy'
                result['strength'] = 0.6
                result['reason'] = "MACD零轴下方金叉，试探性买入"

            logger.debug(f"[{self.name}] {stock_code} MACD金叉")

        # 死叉卖出
        elif prev_dif >= prev_dea and curr_dif < curr_dea:
            # 零轴下方死叉信号更强
            if curr_dif < 0:
                result['signal'] = 'sell'
                result['strength'] = 0.9
                result['reason'] = "MACD零轴下方死叉，强势卖出"
            else:
                result['signal'] = 'sell'
                result['strength'] = 0.6
                result['reason'] = "MACD零轴上方死叉，减仓卖出"

            logger.debug(f"[{self.name}] {stock_code} MACD死叉")

        # MACD柱状图转向
        elif prev_macd < 0 and curr_macd > 0:
            result['indicators']['macd_turn'] = 'positive'
        elif prev_macd > 0 and curr_macd < 0:
            result['indicators']['macd_turn'] = 'negative'

        # 背离检测（高级功能）
        self._check_divergence(data, dif, result)

        return result

    def _check_divergence(self, data: pd.DataFrame, dif: pd.Series, result: Dict):
        """
        检测MACD背离

        顶背离：价格创新高，DIF未创新高 -> 卖出信号
        底背离：价格创新低，DIF未创新低 -> 买入信号
        """
        if len(data) < 60:
            return

        # 获取最近的高点和低点
        recent_highs = data['high'].tail(30)
        recent_lows = data['low'].tail(30)
        recent_dif = dif.tail(30)

        # 找到价格高点
        price_high_idx = recent_highs.idxmax()
        price_high = recent_highs.max()
        current_price = data['close'].iloc[-1]

        # 找到价格低点
        price_low_idx = recent_lows.idxmin()
        price_low = recent_lows.min()

        # 简单背离检测
        # 顶背离：当前价格接近前高，但DIF明显走低
        if current_price >= price_high * 0.98:
            dif_at_high = recent_dif.loc[price_high_idx] if price_high_idx in recent_dif.index else None
            if dif_at_high and dif.iloc[-1] < dif_at_high * 0.8:
                result['indicators']['divergence'] = 'top_divergence'
                if result['signal'] == 'hold':
                    result['signal'] = 'sell'
                    result['strength'] = 0.5
                    result['reason'] = "MACD顶背离，建议减仓"

        # 底背离：当前价格接近前低，但DIF明显走高
        if current_price <= price_low * 1.02:
            dif_at_low = recent_dif.loc[price_low_idx] if price_low_idx in recent_dif.index else None
            if dif_at_low and dif.iloc[-1] > dif_at_low * 1.2:
                result['indicators']['divergence'] = 'bottom_divergence'
                if result['signal'] == 'hold':
                    result['signal'] = 'buy'
                    result['strength'] = 0.5
                    result['reason'] = "MACD底背离，建议试探性买入"
