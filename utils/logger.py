"""
日志管理模块
提供统一的日志记录功能
"""

import os
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
from typing import Optional


def setup_logger(
    name: str = "quant_trading",
    log_dir: str = "logs",
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    设置并返回日志记录器

    Args:
        name: 日志记录器名称
        log_dir: 日志文件存储目录
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的日志文件数量

    Returns:
        配置好的日志记录器
    """
    # 创建日志目录
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 获取或创建logger
    logger = logging.getLogger(name)

    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    # 日志格式
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器 - 所有日志
    today = datetime.now().strftime('%Y%m%d')
    file_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f'{name}_{today}.log'),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 错误日志单独文件
    error_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f'{name}_error.log'),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # 交易日志单独文件
    trade_logger = logging.getLogger(f"{name}.trade")
    trade_logger.setLevel(logging.INFO)
    trade_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f'{name}_trade.log'),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    trade_formatter = logging.Formatter(
        fmt='%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    trade_handler.setFormatter(trade_formatter)
    trade_logger.addHandler(trade_handler)

    return logger


def get_logger(name: str = "quant_trading") -> logging.Logger:
    """
    获取已配置的日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器
    """
    return logging.getLogger(name)


def get_trade_logger(name: str = "quant_trading") -> logging.Logger:
    """
    获取交易专用日志记录器

    Args:
        name: 主日志记录器名称

    Returns:
        交易日志记录器
    """
    return logging.getLogger(f"{name}.trade")


class TradeLogger:
    """
    交易日志记录器类
    提供结构化的交易日志记录
    """

    def __init__(self, name: str = "quant_trading"):
        self.logger = get_trade_logger(name)

    def log_order(
        self,
        action: str,
        stock_code: str,
        stock_name: str,
        price: float,
        amount: int,
        strategy: str,
        reason: str = ""
    ):
        """记录订单日志"""
        msg = (
            f"[{action}] {stock_code} {stock_name} | "
            f"价格: {price:.2f} | 数量: {amount} | "
            f"策略: {strategy} | 原因: {reason}"
        )
        self.logger.info(msg)

    def log_signal(
        self,
        stock_code: str,
        strategy: str,
        signal: str,
        indicators: dict
    ):
        """记录信号日志"""
        indicator_str = ", ".join([f"{k}={v:.4f}" for k, v in indicators.items()])
        msg = f"[信号] {stock_code} | 策略: {strategy} | 信号: {signal} | 指标: {indicator_str}"
        self.logger.info(msg)

    def log_risk(
        self,
        event: str,
        details: str
    ):
        """记录风控日志"""
        msg = f"[风控] {event} | {details}"
        self.logger.warning(msg)

    def log_position(
        self,
        stock_code: str,
        stock_name: str,
        cost: float,
        current_price: float,
        amount: int,
        profit_pct: float
    ):
        """记录持仓日志"""
        msg = (
            f"[持仓] {stock_code} {stock_name} | "
            f"成本: {cost:.2f} | 现价: {current_price:.2f} | "
            f"数量: {amount} | 盈亏: {profit_pct:.2%}"
        )
        self.logger.info(msg)
