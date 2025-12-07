"""
RSI策略
基于相对强弱指标的超买超卖交易策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger()


class RSIStrategy(BaseStrategy):
    """
    RSI策略

    买入信号：RSI从超卖区（<30）向上突破
    卖出信号：RSI从超买区（>70）向下突破
    """

    def __init__(
        self,
        stocks: List[str] = None,
        period: int = 14,
        oversold: float = 30,
        overbought: float = 70,
        position_pct: float = 0.20,
        stop_loss_pct: float = 0.06,
        take_profit_pct: float = 0.12
    ):
        """
        初始化RSI策略

        Args:
            stocks: 监控的股票列表
            period: RSI计算周期
            oversold: 超卖阈值
            overbought: 超买阈值
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        params = {
            'period': period,
            'oversold': oversold,
            'overbought': overbought
        }

        super().__init__(
            name="RSI策略",
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
        oversold = self.params['oversold']
        overbought = self.params['overbought']

        # 计算RSI
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        result['indicators'] = {
            'rsi': curr_rsi,
            'oversold': oversold,
            'overbought': overbought
        }

        # 从超卖区向上突破
        if prev_rsi < oversold and curr_rsi >= oversold:
            # RSI越低，信号越强
            strength = (oversold - prev_rsi) / oversold
            result['signal'] = 'buy'
            result['strength'] = min(0.5 + strength, 1)
            result['reason'] = f"RSI从超卖区({prev_rsi:.1f})向上突破{oversold}"
            logger.debug(f"[{self.name}] {stock_code} RSI超卖反弹")

        # 从超买区向下突破
        elif prev_rsi > overbought and curr_rsi <= overbought:
            # RSI越高，信号越强
            strength = (prev_rsi - overbought) / (100 - overbought)
            result['signal'] = 'sell'
            result['strength'] = min(0.5 + strength, 1)
            result['reason'] = f"RSI从超买区({prev_rsi:.1f})向下突破{overbought}"
            logger.debug(f"[{self.name}] {stock_code} RSI超买回落")

        # 极端超卖（RSI < 20）
        elif curr_rsi < 20:
            result['indicators']['extreme_oversold'] = True
            result['reason'] = f"RSI极端超卖({curr_rsi:.1f})"

        # 极端超买（RSI > 80）
        elif curr_rsi > 80:
            result['indicators']['extreme_overbought'] = True
            result['reason'] = f"RSI极端超买({curr_rsi:.1f})"

        return result


class RSIDivergenceStrategy(BaseStrategy):
    """
    RSI背离策略

    结合价格走势和RSI判断背离
    """

    def __init__(
        self,
        stocks: List[str] = None,
        period: int = 14,
        lookback: int = 20,
        position_pct: float = 0.20,
        stop_loss_pct: float = 0.06,
        take_profit_pct: float = 0.12
    ):
        params = {
            'period': period,
            'lookback': lookback
        }

        super().__init__(
            name="RSI背离策略",
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

        period = self.params['period']
        lookback = self.params['lookback']

        if len(data) < period + lookback:
            return result

        # 计算RSI
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        curr_rsi = rsi.iloc[-1]
        result['indicators']['rsi'] = curr_rsi

        # 获取最近的价格和RSI
        recent_prices = data['close'].tail(lookback)
        recent_rsi = rsi.tail(lookback)

        # 寻找价格高点和RSI高点
        price_highs = self._find_peaks(recent_prices)
        rsi_highs = self._find_peaks(recent_rsi)

        # 寻找价格低点和RSI低点
        price_lows = self._find_troughs(recent_prices)
        rsi_lows = self._find_troughs(recent_rsi)

        # 顶背离检测：价格创新高，RSI未创新高
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if (price_highs[-1] > price_highs[-2] and
                rsi_highs[-1] < rsi_highs[-2]):
                result['signal'] = 'sell'
                result['strength'] = 0.7
                result['reason'] = "RSI顶背离：价格新高但RSI未新高"
                result['indicators']['divergence'] = 'top'

        # 底背离检测：价格创新低，RSI未创新低
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if (price_lows[-1] < price_lows[-2] and
                rsi_lows[-1] > rsi_lows[-2]):
                result['signal'] = 'buy'
                result['strength'] = 0.7
                result['reason'] = "RSI底背离：价格新低但RSI未新低"
                result['indicators']['divergence'] = 'bottom'

        return result

    def _find_peaks(self, series: pd.Series) -> List[float]:
        """寻找序列中的高点"""
        peaks = []
        values = series.values
        for i in range(1, len(values) - 1):
            if values[i] > values[i-1] and values[i] > values[i+1]:
                peaks.append(values[i])
        return peaks

    def _find_troughs(self, series: pd.Series) -> List[float]:
        """寻找序列中的低点"""
        troughs = []
        values = series.values
        for i in range(1, len(values) - 1):
            if values[i] < values[i-1] and values[i] < values[i+1]:
                troughs.append(values[i])
        return troughs
