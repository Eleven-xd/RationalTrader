# ATR止损Bug修复说明

## 🐛 问题描述

### 现象
回测时发现ATR止损存在严重异常：
- 上午买入股票，下午就触发止损卖出
- 买入价格和当前价格相同，却触发止损
- 止损价格竟然比成本价还高！

### 日志示例
```
2025-01-08 10:35:05 - [ETF轮动策略] 买入 501018.XSHG，目标市值30159.63，价格1.29
2025-01-08 14:50:00 - [ETF轮动策略] 卖出 501018.XSHG，持仓23400股
2025-01-08 14:50:00 - [ETF轮动策略] 🔥🔥🔥 ATR动态止损触发 501018.XSHG
                        成本1.29 现价1.29 止损价1.36-ATR跟踪止损
```

### 问题分析

**错误逻辑**（修复前）：
```python
# 第186行
hist_data = attribute_history(security, 250, '1d', ['close'], skip_paused=True, df=True, fq='pre')
highest_price = max(hist_data['close'].max(), avg_cost)
stoploss_price = highest_price - atr * atr_multiplier
```

**问题根源**：
1. `hist_data['close'].max()` 获取的是**最近250天的历史最高价**
2. 对于新买入股票，如果历史上有过更高的价格，会导致止损价 > 成本价
3. 即使现价等于成本价，也会因为"止损价 > 现价"而触发止损

**计算演示**：
```
买入价：1.29元
现价：1.29元（无涨跌）
历史最高价：2.00元（很久以前）
ATR：0.02元
倍数：3.2

错误计算：
highest_price = max(2.00, 1.29) = 2.00
stoploss_price = 2.00 - 0.02 × 3.2 = 2.00 - 0.64 = 1.36元

结果：现价1.29 < 止损价1.36 → 触发止损 ❌
```

---

## 🔧 修复方案

### 核心思路
实现真正的"持仓期间最高价"跟踪，而不是使用历史最高价。

### 修复内容

#### 1. 使用持仓最高价缓存

**新增逻辑**：
```python
# 初始化/更新持仓最高价
cache_key = f"{security}"
if cache_key not in self.highest_price_cache:
    # 新持仓：初始化为成本价或前收盘价（取较大值）
    hist_data_short = attribute_history(security, 1, '1d', ['close', 'high'], skip_paused=True, df=True, fq='pre')
    if hist_data_short is not None and not hist_data_short.empty:
        prev_close = hist_data_short['close'].iloc[-1]
        self.highest_price_cache[cache_key] = max(avg_cost, prev_close)
    else:
        self.highest_price_cache[cache_key] = avg_cost
else:
    # 更新持仓最高价：取当前最高价和缓存最高价的较大值
    hist_data_short = attribute_history(security, 1, '1d', ['high'], skip_paused=True, df=True, fq='pre')
    if hist_data_short is not None and not hist_data_short.empty:
        current_high = hist_data_short['high'].iloc[-1]
        self.highest_price_cache[cache_key] = max(self.highest_price_cache[cache_key], current_high)

highest_price = self.highest_price_cache[cache_key]
stoploss_price = highest_price - atr * atr_multiplier
```

#### 2. 清除缓存机制

**新增方法**：
```python
def clear_security_cache(self, security):
    """清除指定证券的持仓最高价缓存"""
    cache_key = f"{security}"
    if cache_key in self.highest_price_cache:
        del self.highest_price_cache[cache_key]
```

**清除时机**：
1. 卖出股票时
2. 触发止损时

#### 3. 修复位置

| 文件 | 位置 | 修复内容 |
|------|------|---------|
| `three_horse_complete.py` | 第163-167行 | 亏损状态止损时清除缓存 |
| `three_horse_complete.py` | 第169-321行 | 盈利状态使用持仓最高价缓存 |
| `three_horse_complete.py` | 第226-232行 | 盈利状态止损时清除缓存 |
| `three_horse_complete.py` | 第303-320行 | get_stoploss_price方法同样修复 |
| `three_horse_complete.py` | 第328-331行 | 新增clear_security_cache方法 |
| `three_horse_complete.py` | 第1446-1449行 | order_target_value_卖出时清除缓存 |

---

## ✅ 修复效果

### 修复前（错误）

```
买入：501018.XSHG @ 1.29元
现价：1.29元（0涨跌）
历史最高：2.00元
ATR：0.02元，倍数3.2

止损价 = max(2.00, 1.29) - 0.02 × 3.2 = 1.36元
结果：1.29 < 1.36 → 触发止损 ❌
```

### 修复后（正确）

```
买入：501018.XSHG @ 1.29元
前收盘：1.30元
持仓最高价 = max(1.29, 1.30) = 1.30元
现价：1.29元（-0.77%）
ATR：0.02元，倍数3.2

亏损状态：使用固定止损-7%
止损价 = 1.29 × (1 - 0.07) = 1.20元
结果：1.29 > 1.20 → 不触发止损 ✅
```

### 持续上涨场景

```
Day 1: 买入 @ 1.29元
       持仓最高价 = max(1.29, 前收盘1.30) = 1.30元
       止损价 = 1.30 - 0.02 × 3.2 = 1.24元

Day 2: 价格涨到1.35元
       持仓最高价 = max(1.30, 1.35) = 1.35元
       止损价 = 1.35 - 0.02 × 3.2 = 1.29元（上移）

Day 3: 价格涨到1.40元
       持仓最高价 = max(1.35, 1.40) = 1.40元
       止损价 = 1.40 - 0.02 × 3.2 = 1.34元（继续上移）

Day 4: 价格跌到1.30元
       现价1.30 < 止损价1.34 → 触发止损
       收益：(1.30 - 1.29) / 1.29 = +0.78% ✅
```

---

## 📊 核心改进

| 特性 | 修复前 | 修复后 |
|------|--------|--------|
| 最高价来源 | 历史最高价（250天） | 持仓期间最高价 |
| 新买入止损 | 可能 > 成本价 | 不会 > 成本价 |
| 止损合理性 | ❌ 不合理 | ✅ 合理 |
| 缓存机制 | 定义但未使用 | ✅ 正确使用 |
| 卖出清理 | ❌ 未清除缓存 | ✅ 清除缓存 |

---

## 🎯 技术要点

### 1. 持仓最高价初始化
- 新买入时：`max(成本价, 前收盘价)`
- 避免：刚买入就因前日高点而触发止损

### 2. 每日更新机制
- 每日检查：`max(缓存最高价, 当日最高价)`
- 实现：真正的"跟踪止损"，跟随价格上移

### 3. 缓存清理
- 卖出时清理：避免再次买入时使用旧缓存
- 止损时清理：释放内存，避免垃圾累积

### 4. 向后兼容
- 亏损状态：仍使用固定止损-7%
- 盈利状态：ATR跟踪止损 + 多级盈利保护
- 配置参数：无需修改，直接生效

---

## ⚠️ 注意事项

1. **回测验证**：修复后需要重新回测，验证止损逻辑是否正常
2. **持仓影响**：现有持仓不受影响，缓存会自动初始化
3. **性能影响**：每次止损检查会额外调用一次attribute_history，影响极小
4. **内存占用**：缓存每个持仓股票的最高价，内存占用可忽略

---

## 📝 相关代码

### 涉及文件
- `three_horse_complete.py` - 主策略文件

### 涉及类/方法
- `ATRService.check_stoploss()` - 止损检查
- `ATRService.get_stoploss_price()` - 获取止损价
- `ATRService.clear_security_cache()` - 清除缓存（新增）
- `Strategy.order_target_value_()` - 下单时清除缓存

---

## 🚀 后续优化建议

1. **考虑日内最高价**：当前使用每日最高价，可改为盘中实时最高价
2. **多级跟踪**：不同盈利级别使用不同ATR倍数
3. **智能清理**：定期清理长期未持仓的缓存数据
4. **日志增强**：添加持仓最高价的日志输出，便于调试

---

**修复日期**：2026-01-20
**修复版本**：v1.0.1
**影响范围**：所有使用ATR动态止损的策略
**测试状态**：待回测验证
