# A股量化交易系统

基于 Python 的 A股量化交易框架，支持策略回测和实盘交易。

## 功能特点

- **多策略支持**：双均线、MACD、RSI、布林带、KDJ 等常见策略
- **策略回测**：完整的回测引擎，支持佣金、滑点、印花税计算
- **实盘交易**：基于 easytrader 实现自动化交易（需要 Windows 环境）
- **风控系统**：止损止盈、仓位控制、最大回撤限制
- **数据管理**：使用 akshare 获取行情数据，SQLite 存储交易记录
- **通知功能**：支持邮件和企业微信通知

## 项目结构

```
quant_trading_system/
├── config/
│   ├── system_config.json      # 系统配置
│   └── strategy_config.json    # 策略配置
├── core/
│   ├── backtest_engine.py      # 回测引擎
│   ├── trading_engine.py       # 实盘引擎
│   ├── data_manager.py         # 数据管理
│   └── risk_manager.py         # 风控管理
├── strategies/
│   ├── base_strategy.py        # 策略基类
│   ├── ma_strategy.py          # 双均线策略
│   ├── macd_strategy.py        # MACD策略
│   ├── rsi_strategy.py         # RSI策略
│   ├── bollinger_strategy.py   # 布林带策略
│   └── kdj_strategy.py         # KDJ策略
├── utils/
│   ├── logger.py               # 日志工具
│   ├── notification.py         # 通知工具
│   └── database.py             # 数据库工具
├── data/                       # 数据目录
├── logs/                       # 日志目录
├── main.py                     # 主程序入口
├── requirements.txt            # 依赖列表
└── README.md                   # 说明文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置系统

编辑 `config/system_config.json` 配置系统参数：

```json
{
    "trading": {
        "broker": "ths",
        "client_path": "C:\\同花顺\\xiadan.exe"
    },
    "risk_control": {
        "max_daily_loss_pct": 0.05,
        "max_single_position_pct": 0.30
    }
}
```

编辑 `config/strategy_config.json` 配置策略参数：

```json
{
    "strategies": {
        "ma_cross": {
            "enabled": true,
            "stocks": ["000001", "600000"],
            "params": {
                "fast_period": 5,
                "slow_period": 20
            }
        }
    }
}
```

### 3. 运行回测

```bash
# 使用默认配置回测
python main.py backtest

# 指定日期范围
python main.py backtest -s 2024-01-01 -e 2024-06-01
```

### 4. 监控模式

```bash
python main.py monitor
```

### 5. 模拟交易

```bash
python main.py trade --simulate
```

### 6. 实盘交易（请谨慎！）

```bash
python main.py trade --real
```

## 策略说明

### 双均线策略 (MAStrategy)

基于短期和长期均线交叉的趋势跟踪策略：
- **买入信号**：短期均线上穿长期均线（金叉）
- **卖出信号**：短期均线下穿长期均线（死叉）

参数：
- `fast_period`: 快线周期（默认5）
- `slow_period`: 慢线周期（默认20）

### MACD策略 (MACDStrategy)

基于MACD指标的动量策略：
- **买入信号**：DIF上穿DEA（金叉）
- **卖出信号**：DIF下穿DEA（死叉）

参数：
- `fast_period`: 快线EMA周期（默认12）
- `slow_period`: 慢线EMA周期（默认26）
- `signal_period`: 信号线周期（默认9）

### RSI策略 (RSIStrategy)

基于RSI超买超卖的反转策略：
- **买入信号**：RSI从超卖区（<30）向上突破
- **卖出信号**：RSI从超买区（>70）向下突破

参数：
- `period`: RSI计算周期（默认14）
- `oversold`: 超卖阈值（默认30）
- `overbought`: 超买阈值（默认70）

### 布林带策略 (BollingerStrategy)

基于布林带的波动率策略：
- **买入信号**：价格触及下轨后反弹
- **卖出信号**：价格触及上轨后回落

参数：
- `period`: 移动平均周期（默认20）
- `std_dev`: 标准差倍数（默认2.0）

### KDJ策略 (KDJStrategy)

基于KDJ指标的超买超卖策略：
- **买入信号**：K线上穿D线（金叉）+ J值从超卖区反弹
- **卖出信号**：K线下穿D线（死叉）+ J值从超买区回落

参数：
- `k_period`: K值计算周期（默认9）
- `oversold`: 超卖阈值（默认20）
- `overbought`: 超买阈值（默认80）

## 风控系统

系统内置多层风控机制：

1. **单日最大亏损**：默认-5%，触发后暂停交易
2. **单只股票最大仓位**：默认30%
3. **总仓位上限**：默认80%
4. **最大持股数量**：默认3只
5. **止损设置**：默认-10%
6. **止盈设置**：默认+20%
7. **最大回撤**：默认15%，触发后暂停交易

## 实盘交易说明

### 前提条件

1. **Windows 系统**（easytrader 依赖 Windows GUI 自动化）
2. **同花顺/东方财富客户端**
3. **Tesseract OCR**（用于验证码识别）

### 同花顺设置

1. 下载并安装同花顺客户端（推荐 v8.70.42 或 v8.60.64）
2. 系统设置 > 界面设置 > 超时时间设为 0
3. 系统设置 > 交易设置 > 所有默认值设为空
4. 快速交易 > 所有操作不需确认

### 安装 easytrader

```bash
pip install easytrader
```

### 安装 Tesseract OCR

下载地址：https://github.com/UB-Mannheim/tesseract/wiki

安装后配置路径：
```python
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

## 注意事项

1. **回测不等于实盘**：回测结果仅供参考，实盘可能有滑点、延迟等影响
2. **风险控制**：务必设置合理的止损止盈
3. **小资金测试**：建议先用小资金测试策略
4. **合规性**：GUI 自动化交易属于灰色地带，请谨慎使用

## 测试建议

```
第1周：模拟测试（不实际下单）
第2-4周：1000-5000元小资金测试
第2个月：10000-30000元资金
稳定后：逐步增加到正常资金量
```

## 扩展开发

### 添加新策略

1. 继承 `BaseStrategy` 基类
2. 实现 `calculate_signal` 方法
3. 在 `strategies/__init__.py` 中导出
4. 在 `strategy_config.json` 中添加配置

```python
from strategies.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, stocks=None, **kwargs):
        super().__init__(
            name="我的策略",
            stocks=stocks,
            params={'my_param': 10},
            **kwargs
        )

    def calculate_signal(self, stock_code, data):
        # 实现你的信号逻辑
        return {
            'signal': 'buy',  # buy/sell/hold
            'strength': 0.8,
            'reason': '触发条件',
            'indicators': {}
        }
```

## 许可证

MIT License

## 免责声明

本系统仅供学习和研究使用，不构成投资建议。使用本系统进行实盘交易的风险由用户自行承担。
