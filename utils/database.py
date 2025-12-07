"""
数据库管理模块
使用SQLite存储交易记录、持仓信息、策略状态等
"""

import os
import sqlite3
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import json

from .logger import get_logger

logger = get_logger()


class DatabaseManager:
    """
    数据库管理器
    负责所有数据库操作，包括交易记录、持仓、策略状态等
    """

    def __init__(self, db_path: str = "data/trading.db"):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

        # 确保目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        # 初始化数据库表
        self._init_tables()
        logger.info(f"数据库初始化完成: {db_path}")

    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 交易记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_time TIMESTAMP NOT NULL,
                    stock_code VARCHAR(10) NOT NULL,
                    stock_name VARCHAR(50),
                    action VARCHAR(10) NOT NULL,
                    price DECIMAL(10, 3) NOT NULL,
                    amount INTEGER NOT NULL,
                    total_value DECIMAL(15, 2) NOT NULL,
                    commission DECIMAL(10, 2) DEFAULT 0,
                    strategy VARCHAR(50),
                    signal_reason TEXT,
                    status VARCHAR(20) DEFAULT 'success',
                    error_msg TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 持仓表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(10) NOT NULL UNIQUE,
                    stock_name VARCHAR(50),
                    amount INTEGER NOT NULL,
                    available_amount INTEGER NOT NULL,
                    cost_price DECIMAL(10, 3) NOT NULL,
                    current_price DECIMAL(10, 3),
                    market_value DECIMAL(15, 2),
                    profit DECIMAL(15, 2),
                    profit_pct DECIMAL(10, 4),
                    strategy VARCHAR(50),
                    buy_date DATE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 账户余额表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_balance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_date DATE NOT NULL,
                    total_assets DECIMAL(15, 2) NOT NULL,
                    available_cash DECIMAL(15, 2) NOT NULL,
                    market_value DECIMAL(15, 2) NOT NULL,
                    total_profit DECIMAL(15, 2),
                    daily_profit DECIMAL(15, 2),
                    daily_profit_pct DECIMAL(10, 4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 策略信号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_time TIMESTAMP NOT NULL,
                    stock_code VARCHAR(10) NOT NULL,
                    strategy VARCHAR(50) NOT NULL,
                    signal_type VARCHAR(20) NOT NULL,
                    signal_strength DECIMAL(5, 4),
                    indicators TEXT,
                    executed BOOLEAN DEFAULT FALSE,
                    trade_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            ''')

            # 回测结果表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy VARCHAR(50) NOT NULL,
                    stock_code VARCHAR(10),
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    initial_cash DECIMAL(15, 2),
                    final_value DECIMAL(15, 2),
                    total_return DECIMAL(10, 4),
                    annual_return DECIMAL(10, 4),
                    sharpe_ratio DECIMAL(10, 4),
                    max_drawdown DECIMAL(10, 4),
                    win_rate DECIMAL(10, 4),
                    profit_factor DECIMAL(10, 4),
                    total_trades INTEGER,
                    params TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 风控事件表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TIMESTAMP NOT NULL,
                    event_type VARCHAR(50) NOT NULL,
                    stock_code VARCHAR(10),
                    strategy VARCHAR(50),
                    trigger_value DECIMAL(10, 4),
                    threshold_value DECIMAL(10, 4),
                    action_taken VARCHAR(100),
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # K线数据缓存表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS kline_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(10) NOT NULL,
                    trade_date DATE NOT NULL,
                    open DECIMAL(10, 3),
                    high DECIMAL(10, 3),
                    low DECIMAL(10, 3),
                    close DECIMAL(10, 3),
                    volume BIGINT,
                    amount DECIMAL(20, 2),
                    turnover DECIMAL(10, 4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            ''')

            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(trade_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_time ON strategy_signals(signal_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_kline_stock_date ON kline_cache(stock_code, trade_date)')

    # ============ 交易记录相关 ============

    def insert_trade(
        self,
        stock_code: str,
        action: str,
        price: float,
        amount: int,
        stock_name: str = "",
        strategy: str = "",
        signal_reason: str = "",
        commission: float = 0,
        status: str = "success",
        error_msg: str = ""
    ) -> int:
        """
        插入交易记录

        Returns:
            新插入记录的ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            total_value = price * amount
            cursor.execute('''
                INSERT INTO trades
                (trade_time, stock_code, stock_name, action, price, amount,
                 total_value, commission, strategy, signal_reason, status, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now(), stock_code, stock_name, action, price, amount,
                total_value, commission, strategy, signal_reason, status, error_msg
            ))
            return cursor.lastrowid

    def get_trades(
        self,
        stock_code: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        strategy: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """获取交易记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM trades WHERE 1=1"
            params = []

            if stock_code:
                query += " AND stock_code = ?"
                params.append(stock_code)
            if start_date:
                query += " AND DATE(trade_time) >= ?"
                params.append(start_date)
            if end_date:
                query += " AND DATE(trade_time) <= ?"
                params.append(end_date)
            if strategy:
                query += " AND strategy = ?"
                params.append(strategy)

            query += f" ORDER BY trade_time DESC LIMIT {limit}"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_today_trades(self) -> List[Dict]:
        """获取今日交易记录"""
        return self.get_trades(start_date=date.today(), end_date=date.today())

    # ============ 持仓相关 ============

    def update_position(
        self,
        stock_code: str,
        stock_name: str,
        amount: int,
        available_amount: int,
        cost_price: float,
        current_price: float = None,
        strategy: str = "",
        buy_date: date = None
    ):
        """更新或插入持仓记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            market_value = current_price * amount if current_price else None
            profit = (current_price - cost_price) * amount if current_price else None
            profit_pct = (current_price / cost_price - 1) if current_price and cost_price > 0 else None

            cursor.execute('''
                INSERT INTO positions
                (stock_code, stock_name, amount, available_amount, cost_price,
                 current_price, market_value, profit, profit_pct, strategy, buy_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_code) DO UPDATE SET
                    stock_name = excluded.stock_name,
                    amount = excluded.amount,
                    available_amount = excluded.available_amount,
                    cost_price = excluded.cost_price,
                    current_price = excluded.current_price,
                    market_value = excluded.market_value,
                    profit = excluded.profit,
                    profit_pct = excluded.profit_pct,
                    strategy = excluded.strategy,
                    updated_at = excluded.updated_at
            ''', (
                stock_code, stock_name, amount, available_amount, cost_price,
                current_price, market_value, profit, profit_pct, strategy,
                buy_date or date.today(), datetime.now()
            ))

    def get_positions(self) -> List[Dict]:
        """获取所有持仓"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE amount > 0 ORDER BY stock_code')
            return [dict(row) for row in cursor.fetchall()]

    def get_position(self, stock_code: str) -> Optional[Dict]:
        """获取指定股票持仓"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE stock_code = ?', (stock_code,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_position(self, stock_code: str):
        """删除持仓记录（清仓时）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM positions WHERE stock_code = ?', (stock_code,))

    # ============ 账户余额相关 ============

    def record_daily_balance(
        self,
        total_assets: float,
        available_cash: float,
        market_value: float,
        total_profit: float = 0,
        daily_profit: float = 0,
        daily_profit_pct: float = 0
    ):
        """记录每日账户余额"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO account_balance
                (record_date, total_assets, available_cash, market_value,
                 total_profit, daily_profit, daily_profit_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                date.today(), total_assets, available_cash, market_value,
                total_profit, daily_profit, daily_profit_pct
            ))

    def get_balance_history(self, days: int = 30) -> List[Dict]:
        """获取账户余额历史"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM account_balance
                ORDER BY record_date DESC
                LIMIT ?
            ''', (days,))
            return [dict(row) for row in cursor.fetchall()]

    # ============ 策略信号相关 ============

    def insert_signal(
        self,
        stock_code: str,
        strategy: str,
        signal_type: str,
        signal_strength: float = 1.0,
        indicators: Dict = None
    ) -> int:
        """插入策略信号"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO strategy_signals
                (signal_time, stock_code, strategy, signal_type, signal_strength, indicators)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now(), stock_code, strategy, signal_type,
                signal_strength, json.dumps(indicators or {})
            ))
            return cursor.lastrowid

    def update_signal_executed(self, signal_id: int, trade_id: int):
        """更新信号执行状态"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE strategy_signals
                SET executed = TRUE, trade_id = ?
                WHERE id = ?
            ''', (trade_id, signal_id))

    def get_pending_signals(self, strategy: str = None) -> List[Dict]:
        """获取待执行的信号"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM strategy_signals WHERE executed = FALSE"
            params = []
            if strategy:
                query += " AND strategy = ?"
                params.append(strategy)
            query += " ORDER BY signal_time DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ============ 回测结果相关 ============

    def save_backtest_result(
        self,
        strategy: str,
        start_date: date,
        end_date: date,
        initial_cash: float,
        final_value: float,
        total_return: float,
        annual_return: float,
        sharpe_ratio: float,
        max_drawdown: float,
        win_rate: float,
        profit_factor: float,
        total_trades: int,
        stock_code: str = None,
        params: Dict = None
    ) -> int:
        """保存回测结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO backtest_results
                (strategy, stock_code, start_date, end_date, initial_cash, final_value,
                 total_return, annual_return, sharpe_ratio, max_drawdown, win_rate,
                 profit_factor, total_trades, params)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                strategy, stock_code, start_date, end_date, initial_cash, final_value,
                total_return, annual_return, sharpe_ratio, max_drawdown, win_rate,
                profit_factor, total_trades, json.dumps(params or {})
            ))
            return cursor.lastrowid

    def get_backtest_results(self, strategy: str = None, limit: int = 20) -> List[Dict]:
        """获取回测结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM backtest_results"
            params = []
            if strategy:
                query += " WHERE strategy = ?"
                params.append(strategy)
            query += f" ORDER BY created_at DESC LIMIT {limit}"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ============ 风控事件相关 ============

    def record_risk_event(
        self,
        event_type: str,
        trigger_value: float,
        threshold_value: float,
        action_taken: str,
        stock_code: str = None,
        strategy: str = None,
        details: str = ""
    ) -> int:
        """记录风控事件"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO risk_events
                (event_time, event_type, stock_code, strategy, trigger_value,
                 threshold_value, action_taken, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now(), event_type, stock_code, strategy,
                trigger_value, threshold_value, action_taken, details
            ))
            return cursor.lastrowid

    def get_risk_events(self, days: int = 7) -> List[Dict]:
        """获取最近的风控事件"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM risk_events
                WHERE DATE(event_time) >= DATE('now', ?)
                ORDER BY event_time DESC
            ''', (f'-{days} days',))
            return [dict(row) for row in cursor.fetchall()]

    # ============ K线缓存相关 ============

    def cache_klines(self, stock_code: str, klines: List[Dict]):
        """缓存K线数据"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for kline in klines:
                cursor.execute('''
                    INSERT OR REPLACE INTO kline_cache
                    (stock_code, trade_date, open, high, low, close, volume, amount, turnover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code, kline['date'], kline['open'], kline['high'],
                    kline['low'], kline['close'], kline['volume'],
                    kline.get('amount'), kline.get('turnover')
                ))

    def get_cached_klines(
        self,
        stock_code: str,
        start_date: date = None,
        end_date: date = None
    ) -> List[Dict]:
        """获取缓存的K线数据"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM kline_cache WHERE stock_code = ?"
            params = [stock_code]

            if start_date:
                query += " AND trade_date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND trade_date <= ?"
                params.append(end_date)

            query += " ORDER BY trade_date"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ============ 统计分析相关 ============

    def get_trade_statistics(
        self,
        start_date: date = None,
        end_date: date = None,
        strategy: str = None
    ) -> Dict:
        """获取交易统计"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            where_clauses = ["status = 'success'"]
            params = []

            if start_date:
                where_clauses.append("DATE(trade_time) >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append("DATE(trade_time) <= ?")
                params.append(end_date)
            if strategy:
                where_clauses.append("strategy = ?")
                params.append(strategy)

            where_sql = " AND ".join(where_clauses)

            # 总交易次数
            cursor.execute(f"SELECT COUNT(*) FROM trades WHERE {where_sql}", params)
            total_trades = cursor.fetchone()[0]

            # 买入/卖出次数
            cursor.execute(
                f"SELECT action, COUNT(*), SUM(total_value) FROM trades WHERE {where_sql} GROUP BY action",
                params
            )
            action_stats = {row[0]: {'count': row[1], 'value': row[2]} for row in cursor.fetchall()}

            # 按策略统计
            cursor.execute(
                f"SELECT strategy, COUNT(*) FROM trades WHERE {where_sql} GROUP BY strategy",
                params
            )
            strategy_stats = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                'total_trades': total_trades,
                'buy_count': action_stats.get('buy', {}).get('count', 0),
                'sell_count': action_stats.get('sell', {}).get('count', 0),
                'buy_value': action_stats.get('buy', {}).get('value', 0),
                'sell_value': action_stats.get('sell', {}).get('value', 0),
                'strategy_stats': strategy_stats
            }
