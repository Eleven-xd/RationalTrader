# 三驾马车策略配置参数说明

## 📋 概述

本文档详细说明了 `three_horse_refractor.py`（重构版）的配置参数，以及如何通过修改参数来实现不同的优化功能，而**不改变核心策略逻辑**。

---

## 🎯 核心设计理念

### 配置优先级

```
原始策略逻辑 > 配置参数控制 > 新增功能
```

- **保持不变**：选股条件、调仓时机、买卖逻辑
- **可配置**：ATR止损、市场情绪择时、技术指标筛选
- **默认关闭**：所有优化功能默认关闭，需要手动开启

---

## 📊 配置参数分类

### 1️⃣ 基础策略参数（保持不变）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|---------|------|
| `g.xsz_version` | str | "v3" | 小市值选股版本 (v1/v2/v3) |
| `g.xsz_stock_num` | int | 3 | 小市值持仓数量 |
| `g.xsz_buy_etf` | str | "512800.XSHG" | 空仓期购买的ETF |
| `g.etf_pool_2` | list | [...] | ETF反弹策略的ETF池 |
| `g.etf_pool_3` | list | [...] | ETF轮动策略的ETF池 |
| `g.stock_num_2` | int | 2 | 白马攻防持仓数量 |
| `g.target_num` | list | [2, 1] | 红利策略：2只低波+1只价值 |

---

### 2️⃣ 风险控制参数（可配置）

| 参数 | 类型 | 默认值 | 说明 | 修改建议 |
|------|------|---------|------|---------|
| `g.stoploss_strategy` | int | 3 | 止损策略选择 | ⚙️ 可调 |
| `g.stoploss_limit` | float | 0.09 | 固定止损比例 | ⚙️ 可调 |
| `g.stoploss_market` | float | 0.05 | 市场趋势止损参数 | ⚙️ 可调 |
| `g.run_stoploss` | bool | True | 是否进行止损 | ⚙️ 可调 |
| `g.DBL_control` | bool | True | 小市值大盘顶背离控制 | ⚙️ 可调 |
| `g.huanshou_check` | bool | False | 放量换手检测 | ⚙️ 可调 |
| `g.check_defense` | bool | False | 成交额宽度检查 | ⚙️ 可调 |
| `g.enable_stop_loss_by_cur_day` | bool | True | 日内止损开关 | ⚙️ 可调 |

---

### 3️⃣ 新增优化功能参数（需要手动集成）

#### 3.1 ATR动态止损（新增）

| 参数 | 类型 | 默认值 | 说明 | 集成方式 |
|------|------|---------|------|---------|
| `g.enable_atr_stoploss` | bool | **False** | 开启ATR动态止损 | 需要集成 |
| `g.atr_check_times` | list | [] | ATR止损检查时间 | 需要集成 |

**策略差异化参数**（可扩展）：
```python
# 小市值ATR参数
g.smallcap_atr_period = 14
g.smallcap_atr_multiplier = 2.0
g.smallcap_profit_levels = [0.20, 0.50, 1.00]
g.smallcap_stoploss_adjustments = [0.00, 0.20, 0.50]

# ETF轮动ATR参数
g.etf_rotation_atr_period = 10
g.etf_rotation_atr_multiplier = 2.0
g.etf_rotation_profit_levels = [0.10, 0.30, 0.80]
g.etf_rotation_stoploss_adjustments = [0.00, 0.10, 0.30]
```

**配置说明**：
```python
# 关闭ATR止损（使用原始止损策略）
g.enable_atr_stoploss = False

# 开启ATR止损
g.enable_atr_stoploss = True
g.atr_check_times = ["10:00", "14:50"]
```

---

#### 3.2 市场情绪择时（新增）

| 参数 | 类型 | 默认值 | 说明 | 集成方式 |
|------|------|---------|------|---------|
| `g.enable_market_sentiment` | bool | **False** | 开启市场情绪择时 | 需要集成 |
| `g.market_sentiment_threshold` | int | 30 | 情绪评分阈值 | 需要集成 |

**择时规则**：
```
综合评分 < 20：清仓空仓（0%）
综合评分 20-40：减仓至50%
综合评分 ≥ 40：保持正常仓位（100%）
```

**评分维度**（3个指标）：
```
恐慌指数（40%）：跌停家数占比
北向资金（40%）：沪深300连续下跌天数
大盘涨跌（20%）：上涨股票占比
```

**配置说明**：
```python
# 关闭市场情绪择时（原始逻辑）
g.enable_market_sentiment = False

# 开启市场情绪择时
g.enable_market_sentiment = True
g.market_sentiment_threshold = 30
```

---

#### 3.3 技术指标筛选（新增）

| 参数 | 类型 | 默认值 | 说明 | 集成方式 |
|------|------|---------|------|---------|
| `g.enable_technical_filters` | bool | **False** | 开启技术指标筛选（小市值） | 需要集成 |

**筛选条件**：
```
RSI指标：15 < RSI < 85
均线多头：5日均线 > 20日均线
```

**配置说明**：
```python
# 关闭技术指标筛选（原始逻辑）
g.enable_technical_filters = False

# 开启技术指标筛选
g.enable_technical_filters = True
```

---

## 🔧 集成方案

### 方案1：渐进式集成（推荐）

#### 阶段1：添加ATR止损功能

**修改 `initialize()` 函数**，添加ATR相关参数初始化：

```python
def initialize(context):
    # ... 原有代码保持不变 ...
    
    # ===== 新增：ATR动态止损参数 =====
    g.enable_atr_stoploss = False  # 默认关闭
    g.atr_check_times = []  # 空列表表示不检查
    
    # 各策略的ATR参数（默认值）
    g.atr_configs = {
        1: {'period': 14, 'multiplier': 2.0, 'profit_levels': [0.20, 0.50, 1.00]},
        2: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        3: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        4: {'period': 14, 'multiplier': 2.0, 'profit_levels': [0.15, 0.30, 0.60]},
        5: {'period': 20, 'multiplier': 2.2, 'profit_levels': [0.10, 0.25, 0.50]},
    }
```

#### 阶段2：添加ATR检查函数

**在 `initialize()` 后添加ATR检查调度**：

```python
def initialize(context):
    # ... 原有代码保持不变 ...
    
    # 新增：ATR动态止损参数
    g.enable_atr_stoploss = False
    
    # ===== 新增：ATR检查调度 =====
    if g.enable_atr_stoploss and g.atr_check_times:
        for check_time in g.atr_check_times:
            run_daily(check_atr_stoploss, check_time)
```

#### 阶段3：实现ATR检查函数

```python
def check_atr_stoploss(context):
    """
    ATR动态止损检查（所有策略）
    
    集成说明：
    1. 保持原始止损逻辑不变
    2. 当 enable_atr_stoploss=True 时，覆盖原始止损
    3. 通过 check_atr_stoploss() 统一调用ATR服务
    """
    if not g.enable_atr_stoploss:
        # 使用原始止损逻辑（不做任何修改）
        return
    
    # 调用各策略的ATR止损检查
    for strategy_id in [1, 2, 3, 4, 5]:
        if g.strategy_holdings.get(strategy_id, []):
            check_strategy_atr_stoploss(context, strategy_id)

def check_strategy_atr_stoploss(context, strategy_id):
    """检查单个策略的ATR止损"""
    atr_config = g.atr_configs.get(strategy_id, {})
    if not atr_config:
        return
    
    # 这里需要从 three_horse_complete.py 复制 ATRService 类
    # 并实现简化的ATR检查逻辑
    pass
```

---

### 方案2：独立模块导入（高级）

**创建独立的优化模块文件**：

```
jukuan_three_horse/
├── three_horse_refractor.py          # 原始重构版（不变）
├── atr_stoploss_module.py             # ATR止损模块（新增）
├── market_sentiment_module.py        # 市场情绪模块（新增）
├── technical_filters_module.py       # 技术指标模块（新增）
└── config_module.py                  # 配置管理模块（新增）
```

**优点**：
- ✅ 完全隔离原始逻辑
- ✅ 模块化管理，易于维护
- ✅ 可独立测试每个模块
- ✅ 原始文件完全不变

---

## 📝 配置示例

### 配置1：完全原始（保守）

```python
def initialize(context):
    # ... 原有代码 ...
    
    # 新增功能全部关闭
    g.enable_atr_stoploss = False
    g.enable_market_sentiment = False
    g.enable_technical_filters = False
```

**效果**：
- 完全使用原始策略逻辑
- 所有止损、择时功能保持原样
- 适合对原始策略满意的用户

---

### 配置2：开启ATR止损（激进）

```python
def initialize(context):
    # ... 原有代码 ...
    
    # 开启ATR止损
    g.enable_atr_stoploss = True
    g.atr_check_times = ["10:00", "14:50"]
    
    # 关闭其他功能
    g.enable_market_sentiment = False
    g.enable_technical_filters = False
    
    # ATR参数（激进型）
    g.atr_configs = {
        1: {'period': 14, 'multiplier': 2.8, 'profit_levels': [0.20, 0.50, 1.00]},
        2: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        3: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        4: {'period': 14, 'multiplier': 2.5, 'profit_levels': [0.15, 0.30, 0.60]},
        5: {'period': 20, 'multiplier': 3.0, 'profit_levels': [0.10, 0.25, 0.50]},
    }
```

**效果**：
- 使用ATR动态止损替代固定止损
- 让利润更充分地奔跑
- 预期提高收益，但回撤也会增加

---

### 配置3：开启市场情绪择时（平衡）

```python
def initialize(context):
    # ... 原有代码 ...
    
    # 开启市场情绪择时
    g.enable_market_sentiment = True
    g.market_sentiment_threshold = 30
    
    # 关闭其他功能
    g.enable_atr_stoploss = False
    g.enable_technical_filters = False
```

**效果**：
- 在市场极端情况下减仓
- 规避系统性风险
- 预期降低最大回撤

---

### 配置4：全功能开启（最激进）

```python
def initialize(context):
    # ... 原有代码 ...
    
    # 开启所有优化功能
    g.enable_atr_stoploss = True
    g.enable_market_sentiment = True
    g.enable_technical_filters = True
    
    g.atr_check_times = ["09:31", "10:00", "14:50"]
    g.market_sentiment_threshold = 30
```

**效果**：
- 组合使用所有优化功能
- 预期收益最高，但回撤控制最强
- 适合经验丰富的激进型投资者

---

## 🎯 集成步骤（详细指南）

### 步骤1：准备ATR服务类

**操作**：
1. 从 `three_horse_complete.py` 复制 `ATRService` 类
2. 精简到 `atr_stoploss_module.py`
3. 只保留核心方法：
   - `calculate_atr()` - 计算ATR值
   - `check_stoploss()` - 检查止损

**文件结构**：
```python
# atr_stoploss_module.py
class ATRService:
    def __init__(self, period, multiplier, profit_levels, stoploss_adjustments):
        self.atr_period = period
        self.atr_multiplier = multiplier
        self.profit_levels = profit_levels
        self.stoploss_adjustments = stoploss_adjustments
        self.atr_cache = {}
        self.highest_price_cache = {}
    
    def calculate_atr(self, security, period=None):
        # 完整复制计算逻辑
        pass
    
    def check_stoploss(self, security, current_price, avg_cost, order_func):
        # 完整复制检查逻辑
        pass
```

---

### 步骤2：准备市场情绪模块

**操作**：
1. 从 `three_horse_complete.py` 复制 `MarketSentiment` 类
2. 精简到 `market_sentiment_module.py`
3. 修改择时触发逻辑（通过全局变量）

**文件结构**：
```python
# market_sentiment_module.py
class MarketSentiment:
    def __init__(self):
        self.cache = {}
        self.cache_date = None
    
    def calculate_market_sentiment(self, context):
        # 计算情绪评分
        pass
    
    def market_sentiment_timing(self, context):
        # 返回仓位比例
        return position_ratio, sentiment_score, scores_detail
```

---

### 步骤3：修改 three_horse_refractor.py

#### 3.1 添加参数初始化

**在 `initialize()` 函数末尾添加**：

```python
def initialize(context):
    # ... 原有代码保持不变 ...
    
    # ===== 新增：优化功能参数初始化 =====
    # ATR动态止损
    g.enable_atr_stoploss = False
    g.atr_check_times = []
    g.atr_configs = {
        1: {'period': 14, 'multiplier': 2.0, 'profit_levels': [0.20, 0.50, 1.00]},
        2: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        3: {'period': 10, 'multiplier': 2.0, 'profit_levels': [0.10, 0.30, 0.80]},
        4: {'period': 14, 'multiplier': 2.0, 'profit_levels': [0.15, 0.30, 0.60]},
        5: {'period': 20, 'multiplier': 2.2, 'profit_levels': [0.10, 0.25, 0.50]},
    }
    
    # 市场情绪择时
    g.enable_market_sentiment = False
    g.market_sentiment_threshold = 30
    
    # 技术指标筛选
    g.enable_technical_filters = False
```

#### 3.2 添加模块导入

**在文件顶部添加**：

```python
# 新增：优化功能模块导入
from atr_stoploss_module import ATRService
from market_sentiment_module import MarketSentiment

# ... 原有导入保持不变 ...
```

#### 3.3 初始化优化模块

**在 `initialize()` 函数中初始化**：

```python
def initialize(context):
    # ... 原有代码保持不变 ...
    
    # 初始化优化模块
    g.atr_service = None
    g.market_sentiment = None
    
    # 初始化ATR服务（如果启用）
    if g.enable_atr_stoploss:
        g.atr_service = ATRService()
        for strategy_id, config in g.atr_configs.items():
            g.strategies[strategy_id].atr_service = ATRService(
                period=config['period'],
                multiplier=config['multiplier']
            )
            g.strategies[strategy_id].atr_enabled = True
            log.info(f"策略{strategy_id}启用ATR止损：周期{config['period']}天，倍数{config['multiplier']}")
    
    # 初始化市场情绪模块（如果启用）
    if g.enable_market_sentiment:
        g.market_sentiment = MarketSentiment()
        log.info("市场情绪择时已启用")
```

#### 3.4 添加检查调度

**在 `initialize()` 函数末尾添加调度**：

```python
def initialize(context):
    # ... 原有代码 ...
    
    # ATR止损检查调度
    if g.enable_atr_stoploss and g.atr_check_times:
        for check_time in g.atr_check_times:
            run_daily(check_atr_stoploss_all, check_time)
    
    # 市场情绪择时调度
    if g.enable_market_sentiment:
        run_daily(check_market_sentiment_all, "09:00")

def check_atr_stoploss_all(context):
    """检查所有策略的ATR止损"""
    for strategy_id in [1, 2, 3, 4, 5]:
        if hasattr(g.strategies[strategy_id], 'check_atr_stoploss'):
            g.strategies[strategy_id].check_atr_stoploss(context)

def check_market_sentiment_all(context):
    """检查所有策略的市场情绪"""
    sentiment_score, scores_detail = g.market_sentiment.market_sentiment_timing(context)
    
    # 更新全局变量
    g.market_sentiment_score = sentiment_score
    position_ratio = 1.0
    if sentiment_score < 20:
        position_ratio = 0.0
    elif sentiment_score < 40:
        position_ratio = 0.5
    g.market_sentiment_position_ratio = position_ratio
    
    log.info(f"市场情绪择时：综合评分{sentiment_score:.2f}，建议仓位{position_ratio*100:.0f}%")
```

#### 3.5 修改买入函数集成择时

**在各策略的 `buy()` 函数中添加市场情绪因子**：

```python
# 小市值策略 buy() 修改
def smallcap_buy(context):
    if not g.trading_signal:
        return
    
    # ... 原有买入逻辑 ...
    
    # 新增：应用市场情绪择时
    if g.enable_market_sentiment:
        target_total = target_total * g.market_sentiment_position_ratio
        if g.market_sentiment_position_ratio < 1.0:
            log.info(f"市场情绪调整后目标资金: {target_total:.2f} ({g.market_sentiment_position_ratio*100:.0f}%)")
    
    # ... 原有买入逻辑继续 ...
```

---

## 📊 集成对比表

| 集成方式 | 优点 | 缺点 | 适用场景 |
|---------|------|------|---------|
| **渐进式集成** | 代码集中、修改小、易于调试 | 模块耦合度较高 | 功能逐步启用 |
| **独立模块导入** | 模块独立、易于测试、可替换 | 文件较多、需要管理导入 | 完整功能集成 |
| **复制配置文件** | 完全隔离、版本控制简单 | 功能分离、需要同步更新 | 稳定生产环境 |

---

## ⚠️ 注意事项

### 1. 向后兼容性

**保证**：
- ✅ 原始策略逻辑完全不变
- ✅ 所有新功能默认关闭
- ✅ 不修改现有的买卖逻辑
- ✅ 不改变现有的止损触发条件

**测试**：
- 新功能关闭时：回测结果应与原始版完全一致
- 新功能开启时：回测结果应体现优化效果

---

### 2. 性能考虑

**缓存机制**：
- ATR计算使用日级缓存
- 市场情绪计算使用日级缓存
- 避免重复计算影响性能

**检查频率**：
- ATR止损：建议每天1-2次（如10:00, 14:50）
- 市场情绪：每日1次（09:00）

---

### 3. 回测验证

**对比测试**：
```
配置1：原始版（全部关闭）
  └─> 回测结果应与 three_horse_refractor.py 一致
  
配置2：ATR止损开启
  └─> 回测对比：收益提升，回撤可控
  
配置3：市场情绪开启
  └─> 回测对比：回撤降低，收益略降
  
配置4：全部开启
  └─> 回测对比：综合表现最优
```

---

### 4. 调试建议

**日志输出**：
```python
# 添加功能状态日志
log.info("=" * 60)
log.info("🔧 优化功能配置状态")
log.info("=" * 60)
log.info(f"ATR动态止损: {'✅ 开启' if g.enable_atr_stoploss else '❌ 关闭'}")
log.info(f"市场情绪择时: {'✅ 开启' if g.enable_market_sentiment else '❌ 关闭'}")
log.info(f"技术指标筛选: {'✅ 开启' if g.enable_technical_filters else '❌ 关闭'}")
log.info("=" * 60)
```

---

## 🚀 快速开始

### 最小修改（启用ATR止损）

1. **复制ATRService类**
   ```
   从 three_horse_complete.py 复制到 atr_stoploss_module.py
   ```

2. **修改 three_horse_refractor.py**
   ```python
   # 顶部添加导入
   from atr_stoploss_module import ATRService
   
   # initialize() 添加参数
   g.enable_atr_stoploss = True
   g.atr_check_times = ["10:00", "14:50"]
   
   # initialize() 添加初始化
   if g.enable_atr_stoploss:
       for strategy_id, config in g.atr_configs.items():
           g.strategies[strategy_id].atr_service = ATRService(...)
   
   # initialize() 添加调度
   run_daily(check_atr_stoploss_all, "10:00")
   run_daily(check_atr_stoploss_all, "14:50")
   ```

3. **添加检查函数**
   ```python
   def check_atr_stoploss_all(context):
       for strategy_id in [1, 2, 3, 4, 5]:
           if hasattr(g.strategies[strategy_id], 'atr_service'):
               g.strategies[strategy_id].atr_service.check_stoploss(...)
   ```

---

## 📚 参考资料

### 相关文档

- `three_horse_refractor.py` - 原始重构版（保持不变）
- `three_horse_complete.py` - 完整版（包含所有优化功能）
- `ATR_BUGFIX.md` - ATR止损Bug修复说明
- `SENTIMENT_BUGFIX.md` - 市场情绪择时Bug修复说明
- `TUNING_GUIDE.md` - 参数调优指南

---

## 💡 最佳实践

### 推荐配置

**保守型**（新手）：
```
g.enable_atr_stoploss = False
g.enable_market_sentiment = False
g.enable_technical_filters = False
```

**平衡型**（有经验）：
```
g.enable_atr_stoploss = True
g.enable_market_sentiment = True
g.enable_technical_filters = False
g.atr_check_times = ["14:50"]
```

**激进型**（老手）：
```
g.enable_atr_stoploss = True
g.enable_market_sentiment = True
g.enable_technical_filters = True
g.atr_check_times = ["10:00", "14:50"]
```

---

**修改日期**：2026-01-20
**版本**：v1.0.0
**适用文件**：three_horse_refractor.py
**作者**：基于原始策略逻辑的配置参数方案
