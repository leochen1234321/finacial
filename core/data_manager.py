"""
数据管理模块
负责获取和管理行情数据
使用akshare获取实时和历史数据
"""

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
import time

from utils.logger import get_logger
from utils.database import DatabaseManager

logger = get_logger()


class DataManager:
    """
    数据管理器
    负责获取实时行情、历史K线数据等
    """

    def __init__(self, db_manager: DatabaseManager = None, cache_days: int = 365):
        """
        初始化数据管理器

        Args:
            db_manager: 数据库管理器实例
            cache_days: 缓存数据天数
        """
        self.db = db_manager
        self.cache_days = cache_days
        self._realtime_cache = {}
        self._realtime_cache_time = None
        self._cache_ttl = 3  # 实时数据缓存3秒

        # 延迟导入akshare
        self._ak = None

    @property
    def ak(self):
        """延迟加载akshare"""
        if self._ak is None:
            try:
                import akshare as ak
                self._ak = ak
                logger.info("akshare加载成功")
            except ImportError:
                logger.error("请安装akshare: pip install akshare")
                raise
        return self._ak

    def get_realtime_quote(self, stock_code: str) -> Optional[Dict]:
        """
        获取单只股票实时行情

        Args:
            stock_code: 股票代码（6位数字）

        Returns:
            包含实时行情的字典，失败返回None
        """
        quotes = self.get_realtime_quotes([stock_code])
        return quotes.get(stock_code)

    def get_realtime_quotes(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        批量获取实时行情

        Args:
            stock_codes: 股票代码列表

        Returns:
            {stock_code: quote_dict} 字典
        """
        now = datetime.now()

        # 检查缓存是否有效
        if (self._realtime_cache_time and
            (now - self._realtime_cache_time).seconds < self._cache_ttl and
            all(code in self._realtime_cache for code in stock_codes)):
            return {code: self._realtime_cache[code] for code in stock_codes}

        try:
            # 获取全市场实时行情
            df = self.ak.stock_zh_a_spot_em()

            result = {}
            for code in stock_codes:
                # 匹配股票代码
                row = df[df['代码'] == code]
                if row.empty:
                    logger.warning(f"未找到股票: {code}")
                    continue

                row = row.iloc[0]
                result[code] = {
                    'code': code,
                    'name': row['名称'],
                    'price': float(row['最新价']) if pd.notna(row['最新价']) else 0,
                    'open': float(row['今开']) if pd.notna(row['今开']) else 0,
                    'high': float(row['最高']) if pd.notna(row['最高']) else 0,
                    'low': float(row['最低']) if pd.notna(row['最低']) else 0,
                    'pre_close': float(row['昨收']) if pd.notna(row['昨收']) else 0,
                    'volume': int(row['成交量']) if pd.notna(row['成交量']) else 0,
                    'amount': float(row['成交额']) if pd.notna(row['成交额']) else 0,
                    'change_pct': float(row['涨跌幅']) / 100 if pd.notna(row['涨跌幅']) else 0,
                    'change': float(row['涨跌额']) if pd.notna(row['涨跌额']) else 0,
                    'turnover': float(row['换手率']) / 100 if pd.notna(row['换手率']) else 0,
                    'time': now
                }

            # 更新缓存
            self._realtime_cache.update(result)
            self._realtime_cache_time = now

            return result

        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return {}

    def get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        quote = self.get_realtime_quote(stock_code)
        return quote['name'] if quote else ""

    def get_history_klines(
        self,
        stock_code: str,
        start_date: str = None,
        end_date: str = None,
        period: str = "daily",
        adjust: str = "qfq",
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        获取历史K线数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            period: 周期 (daily/weekly/monthly)
            adjust: 复权类型 (qfq前复权/hfq后复权/空字符串不复权)
            use_cache: 是否使用数据库缓存

        Returns:
            K线数据DataFrame
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=self.cache_days)).strftime('%Y%m%d')

        # 尝试从缓存读取
        if use_cache and self.db:
            cached = self._get_cached_klines(stock_code, start_date, end_date)
            if cached is not None and len(cached) > 0:
                logger.debug(f"从缓存读取K线: {stock_code}, 共{len(cached)}条")
                return cached

        # 从akshare获取
        try:
            df = self.ak.stock_zh_a_hist(
                symbol=stock_code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )

            if df.empty:
                logger.warning(f"未获取到K线数据: {stock_code}")
                return pd.DataFrame()

            # 标准化列名
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '换手率': 'turnover'
            })

            # 转换日期
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            # 缓存到数据库
            if use_cache and self.db:
                self._cache_klines(stock_code, df)

            logger.info(f"获取K线数据: {stock_code}, 共{len(df)}条")
            return df

        except Exception as e:
            logger.error(f"获取K线数据失败: {stock_code}, {e}")
            return pd.DataFrame()

    def _get_cached_klines(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """从数据库缓存读取K线"""
        try:
            start_dt = datetime.strptime(start_date, '%Y%m%d').date()
            end_dt = datetime.strptime(end_date, '%Y%m%d').date()

            cached = self.db.get_cached_klines(stock_code, start_dt, end_dt)
            if not cached:
                return None

            df = pd.DataFrame(cached)
            df['date'] = pd.to_datetime(df['trade_date'])
            df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']]

            # 检查数据完整性（简单检查：期间交易日约为日历日的70%）
            expected_days = (end_dt - start_dt).days * 0.7
            if len(df) < expected_days * 0.8:
                return None  # 缓存数据不完整

            return df

        except Exception as e:
            logger.error(f"读取缓存失败: {e}")
            return None

    def _cache_klines(self, stock_code: str, df: pd.DataFrame):
        """缓存K线到数据库"""
        try:
            klines = []
            for _, row in df.iterrows():
                klines.append({
                    'date': row['date'].date() if hasattr(row['date'], 'date') else row['date'],
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume'],
                    'amount': row.get('amount'),
                    'turnover': row.get('turnover')
                })
            self.db.cache_klines(stock_code, klines)
        except Exception as e:
            logger.error(f"缓存K线失败: {e}")

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算常用技术指标

        Args:
            df: K线数据DataFrame

        Returns:
            添加了技术指标的DataFrame
        """
        if df.empty:
            return df

        df = df.copy()

        # 移动平均线
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

        # 布林带
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

        # 成交量均线
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        df['vol_ma10'] = df['volume'].rolling(window=10).mean()

        return df

    def get_stock_list(
        self,
        market: str = None,
        exclude_st: bool = True,
        exclude_new: bool = True,
        new_days: int = 60,
        min_price: float = None,
        max_price: float = None
    ) -> pd.DataFrame:
        """
        获取股票列表

        Args:
            market: 市场 (sh/sz/None表示全部)
            exclude_st: 是否排除ST股票
            exclude_new: 是否排除新股
            new_days: 新股定义的天数
            min_price: 最低价格
            max_price: 最高价格

        Returns:
            股票列表DataFrame
        """
        try:
            df = self.ak.stock_zh_a_spot_em()

            # 筛选市场
            if market:
                if market.lower() == 'sh':
                    df = df[df['代码'].str.startswith('6')]
                elif market.lower() == 'sz':
                    df = df[~df['代码'].str.startswith('6')]

            # 排除ST
            if exclude_st:
                df = df[~df['名称'].str.contains('ST|\\*ST', case=False, na=False)]

            # 价格筛选
            if min_price is not None:
                df = df[df['最新价'] >= min_price]
            if max_price is not None:
                df = df[df['最新价'] <= max_price]

            # 排除新股（需要额外获取上市日期，这里简化处理）
            # 实际可以通过其他接口获取上市日期进行筛选

            return df[['代码', '名称', '最新价', '涨跌幅', '成交量', '成交额', '换手率']]

        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return pd.DataFrame()

    def get_index_quote(self, index_code: str = "000001") -> Optional[Dict]:
        """
        获取指数行情

        Args:
            index_code: 指数代码 (000001上证指数, 399001深证成指, 399006创业板指)

        Returns:
            指数行情字典
        """
        try:
            df = self.ak.stock_zh_index_spot_em()
            row = df[df['代码'] == index_code]

            if row.empty:
                return None

            row = row.iloc[0]
            return {
                'code': index_code,
                'name': row['名称'],
                'price': float(row['最新价']),
                'change_pct': float(row['涨跌幅']) / 100,
                'change': float(row['涨跌额']),
                'volume': float(row['成交量']),
                'amount': float(row['成交额'])
            }

        except Exception as e:
            logger.error(f"获取指数行情失败: {e}")
            return None

    def is_trading_time(self) -> bool:
        """判断当前是否为交易时间"""
        now = datetime.now()
        weekday = now.weekday()

        # 周末不交易
        if weekday >= 5:
            return False

        current_time = now.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()

        return (morning_start <= current_time <= morning_end or
                afternoon_start <= current_time <= afternoon_end)

    def is_safe_trading_time(self) -> bool:
        """判断是否为安全交易时间（避开开盘和收盘）"""
        now = datetime.now()
        weekday = now.weekday()

        if weekday >= 5:
            return False

        current_time = now.time()
        safe_start = datetime.strptime("09:45", "%H:%M").time()
        safe_end = datetime.strptime("14:45", "%H:%M").time()
        lunch_start = datetime.strptime("11:30", "%H:%M").time()
        lunch_end = datetime.strptime("13:00", "%H:%M").time()

        if lunch_start <= current_time <= lunch_end:
            return False

        return safe_start <= current_time <= safe_end
