"""
KDJ策略
基于随机指标的超买超卖交易策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger()


class KDJStrategy(BaseStrategy):
    """
    KDJ策略

    买入信号：
    1. K线上穿D线（金叉）
    2. J值从超卖区（<20）向上

    卖出信号：
    1. K线下穿D线（死叉）
    2. J值从超买区（>80）向下
    """

    def __init__(
        self,
        stocks: List[str] = None,
        k_period: int = 9,
        d_period: int = 3,
        j_period: int = 3,
        oversold: float = 20,
        overbought: float = 80,
        position_pct: float = 0.20,
        stop_loss_pct: float = 0.06,
        take_profit_pct: float = 0.12
    ):
        """
        初始化KDJ策略

        Args:
            stocks: 监控的股票列表
            k_period: K值计算周期
            d_period: D值平滑周期
            j_period: J值计算参数
            oversold: 超卖阈值
            overbought: 超买阈值
            position_pct: 单只股票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        params = {
            'k_period': k_period,
            'd_period': d_period,
            'j_period': j_period,
            'oversold': oversold,
            'overbought': overbought
        }

        super().__init__(
            name="KDJ策略",
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

        k_period = self.params['k_period']
        if len(data) < k_period + 5:
            return result

        oversold = self.params['oversold']
        overbought = self.params['overbought']

        # 计算KDJ
        low_list = data['low'].rolling(window=k_period).min()
        high_list = data['high'].rolling(window=k_period).max()

        # RSV
        rsv = (data['close'] - low_list) / (high_list - low_list) * 100
        rsv = rsv.fillna(50)

        # K、D、J值
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d

        # 当前和前一值
        curr_k = k.iloc[-1]
        curr_d = d.iloc[-1]
        curr_j = j.iloc[-1]
        prev_k = k.iloc[-2]
        prev_d = d.iloc[-2]
        prev_j = j.iloc[-2]

        result['indicators'] = {
            'k': curr_k,
            'd': curr_d,
            'j': curr_j,
            'oversold': oversold,
            'overbought': overbought
        }

        # K线上穿D线（金叉）
        if prev_k <= prev_d and curr_k > curr_d:
            # 超卖区金叉信号更强
            if curr_k < 50:
                strength = (50 - curr_k) / 50 * 0.5 + 0.5
                result['signal'] = 'buy'
                result['strength'] = min(strength, 1)
                result['reason'] = f"KDJ金叉（K={curr_k:.1f}, D={curr_d:.1f}），低位买入"
                logger.debug(f"[{self.name}] {stock_code} KDJ金叉")
            else:
                result['indicators']['golden_cross'] = True

        # K线下穿D线（死叉）
        elif prev_k >= prev_d and curr_k < curr_d:
            # 超买区死叉信号更强
            if curr_k > 50:
                strength = (curr_k - 50) / 50 * 0.5 + 0.5
                result['signal'] = 'sell'
                result['strength'] = min(strength, 1)
                result['reason'] = f"KDJ死叉（K={curr_k:.1f}, D={curr_d:.1f}），高位卖出"
                logger.debug(f"[{self.name}] {stock_code} KDJ死叉")
            else:
                result['indicators']['death_cross'] = True

        # J值超卖反弹
        elif prev_j < oversold and curr_j >= oversold:
            result['signal'] = 'buy'
            result['strength'] = 0.6
            result['reason'] = f"J值从超卖区({prev_j:.1f})反弹"

        # J值超买回落
        elif prev_j > overbought and curr_j <= overbought:
            result['signal'] = 'sell'
            result['strength'] = 0.6
            result['reason'] = f"J值从超买区({prev_j:.1f})回落"

        # 极端J值
        if curr_j < 0:
            result['indicators']['extreme_oversold'] = True
        elif curr_j > 100:
            result['indicators']['extreme_overbought'] = True

        return result


class KDJMACDStrategy(BaseStrategy):
    """
    KDJ+MACD组合策略

    买入信号：KDJ金叉 + MACD金叉/MACD>0
    卖出信号：KDJ死叉 + MACD死叉/MACD<0
    """

    def __init__(
        self,
        stocks: List[str] = None,
        k_period: int = 9,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        position_pct: float = 0.25,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.15
    ):
        params = {
            'k_period': k_period,
            'macd_fast': macd_fast,
            'macd_slow': macd_slow,
            'macd_signal': macd_signal
        }

        super().__init__(
            name="KDJ+MACD组合策略",
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

        if len(data) < 35:
            return result

        # 计算KDJ
        k_period = self.params['k_period']
        low_list = data['low'].rolling(window=k_period).min()
        high_list = data['high'].rolling(window=k_period).max()
        rsv = (data['close'] - low_list) / (high_list - low_list) * 100
        rsv = rsv.fillna(50)
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()

        # 计算MACD
        ema_fast = data['close'].ewm(span=self.params['macd_fast'], adjust=False).mean()
        ema_slow = data['close'].ewm(span=self.params['macd_slow'], adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.params['macd_signal'], adjust=False).mean()
        macd = 2 * (dif - dea)

        # 当前值
        curr_k, prev_k = k.iloc[-1], k.iloc[-2]
        curr_d, prev_d = d.iloc[-1], d.iloc[-2]
        curr_dif, prev_dif = dif.iloc[-1], dif.iloc[-2]
        curr_dea, prev_dea = dea.iloc[-1], dea.iloc[-2]
        curr_macd = macd.iloc[-1]

        result['indicators'] = {
            'k': curr_k, 'd': curr_d,
            'dif': curr_dif, 'dea': curr_dea, 'macd': curr_macd
        }

        # KDJ金叉
        kdj_golden = prev_k <= prev_d and curr_k > curr_d
        # MACD金叉或DIF>0
        macd_bullish = (prev_dif <= prev_dea and curr_dif > curr_dea) or curr_dif > 0

        # KDJ死叉
        kdj_death = prev_k >= prev_d and curr_k < curr_d
        # MACD死叉或DIF<0
        macd_bearish = (prev_dif >= prev_dea and curr_dif < curr_dea) or curr_dif < 0

        # 组合信号
        if kdj_golden and macd_bullish:
            result['signal'] = 'buy'
            result['strength'] = 0.85
            result['reason'] = "KDJ金叉 + MACD看多，双重确认买入"

        elif kdj_death and macd_bearish:
            result['signal'] = 'sell'
            result['strength'] = 0.85
            result['reason'] = "KDJ死叉 + MACD看空，双重确认卖出"

        return result
