# ATR动态止损优化方案

## 一、项目概述

### 1.1 当前策略现状

**策略组成**：
- 策略1：小市值策略（35%）
- 策略2：ETF反弹（10%）
- 策略3：ETF轮动（30%）
- 策略4：白马攻防（10%）
- 策略5：红利策略（15%）

**当前止损机制**：
- 小市值：9%固定止损 + 100%固定止盈 + 大盘跌幅5%清仓
- ETF轮动：仅日内-3%止损
- 其他策略：无明确止损机制

### 1.2 存在的问题

1. **固定止损不适应波动性**：
   - 高波动股票容易频繁止损
   - 低波动股票止损过晚
   - 未实现利润保护

2. **缺少趋势跟踪**：
   - 无法让利润奔跑
   - 未考虑持仓期间最高价

3. **择时机制粗糙**：
   - 仅依赖顶背离和1/4月空仓
   - 未考虑市场情绪指标

4. **技术指标筛选不足**：
   - 仅基于基本面选股
   - 未考虑技术面因素

---

## 二、优化目标

### 2.1 核心优化

1. **ATR动态止损**：
   - 自适应波动性，避免震荡市频繁止损
   - 实现跟踪止损，保护利润
   - 给趋势更多发展空间

2. **多级止盈机制**：
   - 第一档：盈利20%，止损提高到成本价
   - 第二档：盈利50%，止损提高到成本价+20%
   - 第三档：盈利100%，全部止盈或继续跟踪

3. **市场情绪择时**：
   - 综合恐慌指数、跌停比例、北向资金等指标
   - 避免系统性风险

4. **技术指标筛选**：
   - RSI、成交量、均线等指标过滤
   - 提高选股质量

### 2.2 策略差异化

| 策略 | ATR周期 | ATR倍数 | 盈利保护点 | 特点 |
|------|---------|---------|-----------|------|
| 小市值 | 14天 | 2.0 | 20%/50%/100% | 波动大，留更多空间 |
| ETF轮动 | 10天 | 1.5 | 10%/30%/80% | 波动小，及时止损 |
| ETF反弹 | 10天 | 1.5 | 10%/20%/50% | 短期反弹，严格止损 |
| 白马攻防 | 14天 | 2.0 | 15%/30%/60% | 中长期，稳健保护 |
| 红利策略 | 20天 | 2.5 | 10%/25%/50% | 价值投资，宽止损 |

---

## 三、ATR动态止损机制设计

### 3.1 核心原理

**ATR（Average True Range）**：平均真实波幅，衡量价格波动性

**止损计算公式**：
```
动态止损价 = 持仓期间最高价 - ATR × 倍数
```

**止损触发条件**：
1. 亏损状态：使用固定止损（7%）
2. 盈利状态：使用ATR跟踪止损

### 3.2 实现逻辑

#### 步骤1：计算ATR

```python
def calculate_atr(security, period=14):
    """
    计算ATR指标
    参数：
        security: 股票代码
        period: ATR周期（默认14天）
    返回：
        ATR值
    """
    # 1. 获取历史数据
    hist_data = attribute_history(security, period + 1, '1d',
                                   ['close', 'high', 'low'],
                                   skip_paused=True, df=True, fq='pre')

    # 2. 计算TR（真实波幅）
    high = hist_data['high'].values
    low = hist_data['low'].values
    close = hist_data['close'].values

    # TR = max(当日最高-当日最低, |当日最高-前收盘|, |当日最低-前收盘|)
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    # 3. ATR = TR的移动平均
    atr = np.mean(tr)

    return atr
```

#### 步骤2：动态止损检查

```python
def check_atr_stoploss(context, position):
    """
    ATR动态止损检查
    参数：
        context: 上下文
        position: 持仓信息
    """
    security = position.security
    current_price = position.current_price
    avg_cost = position.avg_cost
    current_return = (current_price - avg_cost) / avg_cost

    # 1. 计算ATR
    atr = calculate_atr(security, atr_period)
    if atr is None:
        return

    # 2. 根据盈亏状态选择止损方式
    if current_return <= 0:
        # 亏损状态：固定止损
        stoploss_price = avg_cost * (1 - 0.07)
        if current_price < stoploss_price:
            # 执行止损
            order_target_value(security, 0)
    else:
        # 盈利状态：ATR跟踪止损
        hist_data = attribute_history(security, 250, '1d', ['close'],
                                       skip_paused=True, df=True, fq='pre')
        highest_price = max(hist_data['close'].max(), avg_cost)

        stoploss_price = highest_price - atr * atr_multiplier

        # 3. 多级盈利保护
        for i, profit_level in enumerate(profit_levels):
            if current_return >= profit_level:
                adjusted_stoploss = avg_cost * (1 + stoploss_adjustments[i])
                stoploss_price = max(stoploss_price, adjusted_stoploss)
                break

        # 4. 检查止损
        if current_price < stoploss_price:
            order_target_value(security, 0)
```

### 3.3 止损优先级

1. **大盘跌幅清仓**（最高优先级）
2. **ATR动态止损**（中优先级）
3. **固定止损**（最低优先级，保底）

---

## 四、多级止盈机制

### 4.1 止盈档位设计

| 档位 | 盈利比例 | 止损调整 | 说明 |
|------|---------|---------|------|
| 第一档 | 20% | 提高到成本价 | 锁定本金，不亏钱 |
| 第二档 | 50% | 提高到成本价+20% | 锁定20%利润 |
| 第三档 | 100% | 全部止盈或继续跟踪 | 根据趋势决定 |

### 4.2 策略差异化配置

**小市值策略**：
```python
profit_levels = [0.20, 0.50, 1.00]
stoploss_adjustments = [0.00, 0.20, 0.50]
```

**ETF轮动策略**：
```python
profit_levels = [0.10, 0.30, 0.80]
stoploss_adjustments = [0.00, 0.10, 0.30]
```

---

## 五、市场情绪择时

### 5.1 情绪指标体系

#### 5.1.1 恐慌指数

```python
def calculate_panic_index(context):
    """
    计算恐慌指数
    = (跌停家数 / 总家数) × 100
    """
    # 获取当日跌停家数
    limit_down_count = count_limit_down_stocks(context)

    # 获取总家数
    total_count = len(get_all_securities(['stock']))

    # 计算恐慌指数
    panic_index = (limit_down_count / total_count) * 100

    return panic_index
```

#### 5.1.2 北向资金流向

```python
def check_north_money_flow(context):
    """
    检查北向资金流向
    返回：连续净流出天数
    """
    # 获取北向资金历史数据
    north_money_data = get_north_money_flow(days=5)

    # 计算连续净流出天数
    consecutive_outflow = 0
    for i in range(len(north_money_data)):
        if north_money_data[i] < 0:
            consecutive_outflow += 1
        else:
            break

    return consecutive_outflow
```

#### 5.1.3 新股破发率

```python
def calculate_ipo_break_rate(context):
    """
    计算新股破发率
    = (破发新股数 / 新股总数) × 100
    """
    # 获取近30日上市新股
    ipo_stocks = get_ipo_stocks(days=30)

    # 统计破发数量
    break_count = 0
    for stock in ipo_stocks:
        current_price = get_current_data()[stock].last_price
        issue_price = get_issue_price(stock)
        if current_price < issue_price:
            break_count += 1

    # 计算破发率
    break_rate = (break_count / len(ipo_stocks)) * 100

    return break_rate
```

### 5.2 综合评分机制

```python
def calculate_market_sentiment(context):
    """
    计算市场情绪评分（0-100）
    """
    scores = {}

    # 1. 恐慌指数（权重30%）
    panic_index = calculate_panic_index(context)
    if panic_index < 1:
        scores['panic'] = 80  # 市场平静
    elif panic_index < 3:
        scores['panic'] = 60  # 市场轻微恐慌
    elif panic_index < 5:
        scores['panic'] = 40  # 市场恐慌
    else:
        scores['panic'] = 20  # 市场极度恐慌

    # 2. 北向资金（权重30%）
    outflow_days = check_north_money_flow(context)
    if outflow_days == 0:
        scores['north'] = 80  # 资金净流入
    elif outflow_days < 3:
        scores['north'] = 60  # 轻微净流出
    elif outflow_days < 5:
        scores['north'] = 40  # 中度净流出
    else:
        scores['north'] = 20  # 重度净流出

    # 3. 新股破发率（权重20%）
    break_rate = calculate_ipo_break_rate(context)
    if break_rate < 20:
        scores['ipo'] = 80  # IPO表现良好
    elif break_rate < 40:
        scores['ipo'] = 60  # IPO表现一般
    elif break_rate < 60:
        scores['ipo'] = 40  # IPO表现较差
    else:
        scores['ipo'] = 20  # IPO表现极差

    # 4. 大盘涨跌家数（权重20%）
    up_down_ratio = get_up_down_ratio(context)
    if up_down_ratio > 0.6:
        scores['trend'] = 80  # 市场强势
    elif up_down_ratio > 0.4:
        scores['trend'] = 60  # 市场偏强
    elif up_down_ratio > 0.3:
        scores['trend'] = 40  # 市场偏弱
    else:
        scores['trend'] = 20  # 市场弱势

    # 综合评分
    total_score = (
        scores['panic'] * 0.3 +
        scores['north'] * 0.3 +
        scores['ipo'] * 0.2 +
        scores['trend'] * 0.2
    )

    return total_score
```

### 5.3 择时决策

```python
def market_sentiment_timing(context):
    """
    市场情绪择时决策
    返回：仓位比例（0-1）
    """
    sentiment_score = calculate_market_sentiment(context)

    if sentiment_score < 20:
        # 极度恐慌：清仓空仓
        return 0.0
    elif sentiment_score < 40:
        # 恐慌：减仓至50%
        return 0.5
    elif sentiment_score < 60:
        # 中性：保持正常仓位
        return 1.0
    else:
        # 强势：正常交易
        return 1.0
```

---

## 六、技术指标筛选

### 6.1 RSI指标

```python
def calculate_rsi(security, period=14):
    """
    计算RSI相对强弱指标
    参数：
        security: 股票代码
        period: RSI周期（默认14天）
    返回：
        RSI值（0-100）
    """
    # 获取历史数据
    hist_data = attribute_history(security, period + 1, '1d', ['close'],
                                   skip_paused=True, df=True, fq='pre')

    # 计算涨跌幅
    close = hist_data['close'].values
    changes = np.diff(close)

    # 分离上涨和下跌
    gains = np.where(changes > 0, changes, 0)
    losses = np.where(changes < 0, -changes, 0)

    # 计算平均涨跌幅
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    # 计算RSI
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi
```

**筛选条件**：
- RSI < 30：超卖，可买入
- RSI > 70：超买，避免买入
- 理想范围：20 < RSI < 80

### 6.2 成交量因子

```python
def calculate_turnover_rate(security, period=20):
    """
    计算换手率
    参数：
        security: 股票代码
        period: 周期（默认20天）
    返回：
        平均换手率
    """
    # 获取成交量和流通股本
    hist_data = attribute_history(security, period, '1d', ['volume', 'money'],
                                   skip_paused=True, df=True, fq='pre')

    # 获取流通股本
    circulating_cap = get_circulating_cap(security)

    # 计算换手率
    turnover_rates = []
    for i in range(len(hist_data)):
        volume = hist_data['volume'].values[i]
        if circulating_cap > 0:
            turnover_rate = volume / circulating_cap
            turnover_rates.append(turnover_rate)

    # 计算平均换手率
    avg_turnover_rate = np.mean(turnover_rates)

    return avg_turnover_rate
```

**筛选条件**：
- 平均换手率 > 3%：活跃，可买入
- 换手率 < 1%：不活跃，避免买入

### 6.3 均线多头排列

```python
def check_ma_bullish_alignment(security, short=5, long=20):
    """
    检查均线多头排列
    参数：
        security: 股票代码
        short: 短期均线（默认5日）
        long: 长期均线（默认20日）
    返回：
        True: 多头排列，False: 否
    """
    # 计算均线
    ma_short = calculate_ma(security, short)
    ma_long = calculate_ma(security, long)

    # 检查多头排列
    if ma_short > ma_long:
        return True
    else:
        return False
```

**筛选条件**：
- 5日均线 > 20日均线：多头排列，可买入
- 5日均线 < 20日均线：空头排列，避免买入

### 6.4 突破新高

```python
def check_new_high(security, period=60):
    """
    检查是否突破新高
    参数：
        security: 股票代码
        period: 周期（默认60天）
    返回：
        True: 突破新高，False: 否
    """
    # 获取历史数据
    hist_data = attribute_history(security, period, '1d', ['high'],
                                   skip_paused=True, df=True, fq='pre')

    # 获取当前价格
    current_price = get_current_data()[security].last_price

    # 检查是否突破新高
    if current_price > hist_data['high'].max():
        return True
    else:
        return False
```

**筛选条件**：
- 突破60日新高：趋势强劲，优先买入

---

## 七、实施步骤

### 7.1 阶段1：ATR框架实现（1-2天）

**任务**：
1. 创建ATR服务类
2. 实现ATR计算方法
3. 实现动态止损检查方法
4. 添加缓存机制（性能优化）

**输出**：
- `atr_service.py`: ATR服务类

### 7.2 阶段2：市场情绪择时模块（1-2天）

**任务**：
1. 实现恐慌指数计算
2. 实现北向资金流向检查
3. 实现新股破发率计算
4. 实现综合评分机制
5. 实现择时决策逻辑

**输出**：
- `market_sentiment.py`: 市场情绪择时模块

### 7.3 阶段3：技术指标筛选模块（1天）

**任务**：
1. 实现RSI指标计算
2. 实现成交量因子计算
3. 实现均线多头排列检查
4. 实现突破新高检查
5. 实现综合筛选逻辑

**输出**：
- `technical_indicators.py`: 技术指标筛选模块

### 7.4 阶段4：复制并优化主策略文件（2-3天）

**任务**：
1. 复制 `three_horse_refractor.py` 创建 `three_horse_optimized.py`
2. 导入ATR、市场情绪、技术指标模块
3. 在Strategy基类中集成ATR止损方法
4. 为各策略配置差异化参数

**输出**：
- `three_horse_optimized.py`: 优化版策略文件

### 7.5 阶段5：策略集成（2-3天）

**任务**：
1. 为小市值策略集成ATR动态止损
2. 为ETF轮动策略集成ATR动态止损
3. 为ETF反弹策略集成ATR止损
4. 为白马攻防策略集成ATR止损
5. 为红利策略集成ATR止损
6. 添加市场情绪择时到所有策略
7. 添加技术指标筛选到小市值策略

**输出**：
- 完整的优化策略

### 7.6 阶段6：配置参数和功能开关（1天）

**任务**：
1. 添加ATR相关配置参数
2. 添加功能开关（可独立启用/禁用各优化）
3. 更新README文档

**输出**：
- 配置参数文件
- 更新的README文档

### 7.7 阶段7：回测验证（2-3天）

**任务**：
1. 回测2023-2025年数据
2. 对比优化前后指标（夏普比率、最大回撤、胜率）
3. 参数敏感性分析
4. 优化参数调整

**输出**：
- 回测报告
- 参数优化建议

### 7.8 阶段8：实盘模拟测试（1个月）

**任务**：
1. 模拟盘测试1个月
2. 监控实盘表现
3. 根据结果微调参数
4. 逐步切换到实盘

**输出**：
- 模拟盘测试报告
- 实盘切换建议

---

## 八、预期效果

### 8.1 量化指标改善

| 指标 | 优化前 | 预期优化后 | 改善幅度 |
|------|--------|-----------|---------|
| 夏普比率 | 1.2 | 1.5-1.8 | +25%-50% |
| 最大回撤 | 15% | 10-12% | -20%-33% |
| 胜率 | 45% | 50-55% | +5-10% |
| 年化收益 | 20% | 22-25% | +10%-25% |

### 8.2 风险控制提升

1. **减少无谓止损**：
   - 震荡市止损次数减少30%
   - 给趋势更多发展空间

2. **及时保护利润**：
   - 盈利20%后锁定本金
   - 盈利50%后锁定20%利润

3. **规避系统性风险**：
   - 恐慌指数预警
   - 北向资金流出减仓

### 8.3 选股质量提升

1. **技术指标过滤**：
   - 排除超买股票
   - 优选活跃股票

2. **趋势确认**：
   - 多头排列
   - 突破新高

---

## 九、风险管理

### 9.1 参数调整风险

**风险**：参数设置不当可能导致止损过严或过宽

**应对**：
- 回测验证参数合理性
- 实盘前先模拟盘测试
- 监控实盘表现，及时调整

### 9.2 过度优化风险

**风险**：过度优化可能导致策略过拟合

**应对**：
- 参数选择有逻辑依据
- 避免过度细分市场环境
- 保持策略简单有效

### 9.3 实施风险

**风险**：策略改动较大，可能引入新bug

**应对**：
- 分阶段实施，逐步验证
- 每次修改后充分测试
- 保留原策略作为备选

---

## 十、总结

本优化方案通过引入ATR动态止损、多级止盈、市场情绪择时、技术指标筛选等优化，全面提升策略的风险控制能力和盈利稳定性。

**核心优势**：
1. 自适应波动性，避免震荡市频繁止损
2. 实现利润保护，让利润奔跑
3. 综合择时，规避系统性风险
4. 技术筛选，提高选股质量

**实施建议**：
1. 优先实施ATR动态止损（效果最显著）
2. 逐步实施其他优化（降低风险）
3. 充分测试验证（确保稳定性）
4. 实盘监控调整（持续优化）

通过本优化方案的实施，预期可以显著提升策略的夏普比率和稳定性，同时降低最大回撤，为投资者创造更稳健的收益。
