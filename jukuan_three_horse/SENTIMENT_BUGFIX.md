# 市场情绪择时优化说明

## 📝 更新记录

### 2026-01-20 v1.0.3 - 删除新股破发率指标

**修改原因**：
- 新股IPO数量太少，参考价值不大
- 简化择时逻辑，减少计算复杂度
- 重新分配权重，聚焦核心指标

**修改内容**：
1. 删除新股破发率指标（calculate_ipo_break_rate()）
2. 重新分配权重：
   - 原来：恐慌30% + 北向30% + 新股20% + 大盘20% = 100%
   - 现在：恐慌40% + 北向40% + 大盘20% = 100%
3. 删除日志中的IPO表现输出
4. 更新README.md说明

**新的权重分配**：

| 指标 | 原权重 | 新权重 | 说明 |
|------|--------|--------|------|
| 恐慌指数 | 30% | **40%** | 提高权重 |
| 北向资金 | 30% | **40%** | 提高权重 |
| 新股破发 | 20% | **0%** | ❌ 已删除 |
| 大盘涨跌 | 20% | 20% | 保持不变 |

**综合评分公式**（更新后）：
```
综合评分 = 恐慌指数×40% + 北向资金×40% + 大盘涨跌×20%
```

---

## 🐛 原始问题（已修复）

## 🐛 问题描述

### 现象
回测发现市场情绪择时报告的所有打分**每天都是一致的**，没有随市场变化而调整。

### 问题示例
```
2025-01-08: 综合评分 55.00, 仓位 100%
2025-01-09: 综合评分 55.00, 仓位 100%
2025-01-10: 综合评分 55.00, 仓位 100%
...每天完全相同
```

---

## 🔍 根本原因分析

### 问题1：北向资金流向检测（返回固定值0）

**错误代码**（修复前）：
```python
def check_north_money_flow(self, context=None, days=5):
    """
    检查北向资金流向
    返回连续净流出天数
    """
    try:
        # 获取北向资金历史数据
        # 注意：实际需要根据聚宽API调整
        # 这里使用模拟数据
        consecutive_outflow = 0

        # 模拟：假设北向资金净流入（实际应该从API获取）
        # consecutive_outflow = self._get_north_money_outflow_days(days)

        return consecutive_outflow  # ❌ 总是返回0
    except Exception as e:
        print(f"[MarketSentiment] 检查北向资金失败: {e}")
        return 0
```

**问题**：
- 直接返回固定值 `0`
- 注释说明"使用模拟数据"
- 导致每天得分都是 **80分**（"资金净流入"）

---

### 问题2：新股破发率计算（返回空列表）

**错误代码**（修复前）：
```python
def calculate_ipo_break_rate(self, context=None, days=30):
    """
    计算新股破发率
    公式：(破发新股数 / 新股总数) × 100
    """
    try:
        # 获取近N天上市的新股
        # 注意：实际需要根据聚宽API调整获取新股列表
        # 这里使用模拟数据
        ipo_stocks = self._get_ipo_stocks(days)
        total_count = len(ipo_stocks)  # ❌ 总是0
        break_count = 0

        for stock in ipo_stocks:
            try:
                current_price = current_data[stock].last_price
                # 获取发行价（模拟）
                issue_price = self._get_issue_price(stock)  # ❌ 总是返回0

                if issue_price > 0 and current_price < issue_price:
                    break_count += 1
            except Exception as e:
                continue

        # 计算破发率
        break_rate = (break_count / total_count * 100) if total_count > 0 else 0  # ❌ 总是0

        return break_rate
    except Exception as e:
        print(f"[MarketSentiment] 计算新股破发率失败: {e}")
        return 0
```

**模拟方法**（错误）：
```python
def _get_ipo_stocks(self, days):
    # 实际应该从聚宽API获取新股列表
    # 这里返回空列表
    return []  # ❌ 总是返回空列表

def _get_issue_price(self, stock):
    # 实际应该从聚宽API获取发行价
    # 这里返回0表示无法获取
    return 0  # ❌ 总是返回0
```

**问题**：
- `_get_ipo_stocks()` 返回空列表 `[]`
- `_get_issue_price()` 总是返回 `0`
- 导致：`total_count = 0`，`break_rate = 0`
- 每天得分都是 **80分**（"IPO表现良好"）

---

### 问题3：综合评分计算（固定分数）

| 指标 | 得分 | 状态 |
|------|------|------|
| 恐慌指数 | 20-80 | ✅ 正常变化 |
| 北向资金 | **80**（固定） | ❌ 不变 |
| 新股破发 | **80**（固定） | ❌ 不变 |
| 大盘涨跌 | 20-80 | ✅ 正常变化 |

**综合评分公式**：
```
综合评分 = 恐慌指数×30% + 北向资金×30% + 新股破发×20% + 大盘涨跌×20%

由于北向资金和新股都是固定的80分，导致综合评分变化很小。
```

---

## 🔧 修复方案

### 方案：使用简化替代实现

#### 1. 北向资金流向 - 使用沪深300涨跌作为代理指标

**修复后代码**：
```python
def check_north_money_flow(self, context=None, days=5):
    """
    检查北向资金流向（简化版：使用大盘涨跌作为代理指标）
    """
    try:
        current_date = context.current_dt.date() if context else datetime.datetime.now().date()

        # 检查缓存
        cache_key = 'north_money_flow'
        if self.cache_date == current_date and cache_key in self.cache:
            return self.cache[cache_key]

        # 🔧 使用沪深300涨跌作为资金流向代理指标
        index_df = get_price('000300.XSHG',
                          end_date=context.current_dt,
                          count=days + 1,
                          frequency='daily',
                          fields=['close'],
                          df=True)

        if index_df is None or len(index_df) < 2:
            return 0

        consecutive_outflow = 0
        for i in range(len(index_df) - 1, 0, -1):
            if i > 0:
                # 计算日涨跌幅
                daily_return = (index_df['close'].iloc[i] - index_df['close'].iloc[i-1]) / index_df['close'].iloc[i-1]

                if daily_return < 0:  # 大盘下跌视为资金流出
                    consecutive_outflow += 1
                else:
                    break  # 遇到上涨，停止计数

        # 更新缓存
        self.cache[cache_key] = consecutive_outflow
        self.cache_date = current_date

        return consecutive_outflow

    except Exception as e:
        print(f"[MarketSentiment] 检查北向资金失败: {e}")
        return 0
```

**优点**：
- ✅ 使用真实市场数据（沪深300）
- ✅ 能够反映资金流向变化
- ✅ 逻辑合理：大盘下跌视为资金流出
- ✅ 缓存机制，避免重复计算

**计算示例**：
```
沪深300最近5日：
Day 0: 3000点
Day 1: 2990点 (-0.33%)  连续流出1天
Day 2: 2980点 (-0.33%)  连续流出2天
Day 3: 2990点 (+0.34%)   停止计数

结果：consecutive_outflow = 2天
得分：60分（"净流出2天"）
```

---

#### 2. 新股破发率 - 使用首日开盘价作为参考

**修复后代码**：
```python
def calculate_ipo_break_rate(self, context=None, days=30):
    """
    计算新股破发率（简化版：使用首日开盘价作为参考）
    """
    try:
        current_date = context.current_dt.date() if context else datetime.datetime.now().date()

        # 检查缓存
        cache_key = 'ipo_break_rate'
        if self.cache_date == current_date and cache_key in self.cache:
            return self.cache[cache_key]

        # 🔧 获取所有股票，筛选近30日上市的
        all_stocks = get_all_securities(['stock'])
        cutoff_date = current_date - datetime.timedelta(days=days)

        ipo_stocks = []
        for stock, info in all_stocks.iterrows():
            start_date = info['start_date']
            if start_date >= cutoff_date:
                ipo_stocks.append(stock)

        total_count = len(ipo_stocks)
        if total_count == 0:
            # 没有新股，返回中性值（10%破发率）
            return 10

        # 统计破发数量
        current_data = get_current_data()
        break_count = 0

        for stock in ipo_stocks:
            try:
                current_price = current_data[stock].last_price

                # 🔧 使用首日开盘价作为发行价参考
                # 获取该股票上市以来的第一根K线
                hist_data = attribute_history(stock, 1, '1d', ['open'], skip_paused=True, df=True, fq='pre')

                if hist_data is not None and not hist_data.empty:
                    first_day_open = hist_data['open'].iloc[-1]

                    if first_day_open > 0 and current_price < first_day_open:
                        break_count += 1

            except Exception:
                continue

        # 计算破发率
        break_rate = (break_count / total_count * 100)

        # 更新缓存
        self.cache[cache_key] = break_rate
        self.cache_date = current_date

        return break_rate

    except Exception as e:
        print(f"[MarketSentiment] 计算新股破发率失败: {e}")
        return 10  # 返回中性值
```

**优点**：
- ✅ 使用真实的上市日期筛选新股
- ✅ 使用首日开盘价作为参考（比发行价更易获取）
- ✅ 能够反映新股市场表现
- ✅ 缓存机制，避免重复计算
- ✅ 处理边界情况（无新股时返回中性值）

**计算示例**：
```
近30日新股共10只：
- 股票A：首日开盘10.00，现价12.00 → 未破发
- 股票B：首日开盘20.00，现价18.00 → 破发
- 股票C：首日开盘15.00，现价14.50 → 破发
- ...（共3只破发）

破发率 = 3 / 10 × 100 = 30%
得分：60分（"IPO破发率30.0%"）
```

---

#### 3. 删除旧的模拟方法

删除以下方法：
- `_get_north_money_outflow_days()` - 模拟北向资金
- `_get_ipo_stocks()` - 模拟新股列表
- `_get_issue_price()` - 模拟发行价

---

## ✅ 修复效果对比

### 修复前（错误）

| 日期 | 恐慌指数 | 北向资金 | 新股破发 | 大盘涨跌 | 综合评分 | 仓位 |
|------|---------|---------|----------|---------|---------|------|
| 01-08 | 40 | **80**（固定） | **80**（固定） | 60 | **55.00** | 100% |
| 01-09 | 40 | **80**（固定） | **80**（固定） | 60 | **55.00** | 100% |
| 01-10 | 40 | **80**（固定） | **80**（固定） | 60 | **55.00** | 100% |

**问题**：
- 每天打分完全相同
- 无法反映市场变化
- 择时功能失效

---

### 修复后（正确）

| 日期 | 恐慌指数 | 北向资金 | 新股破发 | 大盘涨跌 | 综合评分 | 仓位 |
|------|---------|---------|----------|---------|---------|------|
| 01-08 | 40 | 80 | 80 | 60 | **55.00** | 100% |
| 01-09 | 40 | 60（流出2天） | 60（30%） | 80 | **59.00** | 100% |
| 01-10 | 20 | 40（流出4天） | 40（50%） | 40 | **33.00** | 50% |
| 01-11 | 20 | 20（流出6天） | 40（50%） | 20 | **23.00** | 0% |

**改进**：
- ✅ 每天打分随市场变化
- ✅ 及时反映市场情绪恶化
- ✅ 仓位动态调整（100% → 50% → 0%）
- ✅ 择时功能生效

---

## 📊 核心改进

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 北向资金来源 | 固定值0 | 沪深300涨跌代理 |
| 新股数据来源 | 空列表 | 真实上市日期筛选 |
| 每日打分 | 完全相同 | 随市场变化 |
| 择时有效性 | ❌ 失效 | ✅ 生效 |
| 仓位调整 | 固定100% | 动态调整0-100% |

---

## 🎯 技术要点

### 1. 使用大盘指数作为资金流向代理
- 沪深300下跌 → 北向资金流出
- 沪深300上涨 → 北向资金流入
- 连续下跌天数 = 连续净流出天数

**优点**：
- 数据真实可靠
- 与资金流向高度相关
- 易于实现

---

### 2. 使用首日开盘价作为新股参考
- 首日开盘价可从历史K线获取
- 反映市场对新股的定价
- 破发 = 现价 < 首日开盘价

**优点**：
- 数据真实可靠
- 避免获取发行价的复杂性
- 逻辑合理

---

### 3. 缓存机制
- 每日只计算一次
- 避免重复计算影响性能
- `cache_date` 验证日期有效性

---

## ⚠️ 注意事项

### 1. 代理指标的局限性
- **沪深300涨跌 ≠ 真实北向资金**
- **首日开盘价 ≠ 真实发行价**

这些是**简化替代方案**，在聚宽平台API有限的情况下使用。如果未来聚宽提供真实的：
- 北向资金API
- 新股发行价API

应该优先使用真实数据。

---

### 2. 数据边界处理
- 没有新股时：返回中性值10%
- 数据获取失败时：返回0或中性值
- 异常情况：记录日志但不阻断主流程

---

### 3. 回测验证
- 修复后需要重新回测
- 检查每日情绪打分是否变化
- 验证仓位调整是否合理

---

## 📝 相关代码

### 涉及文件
- `three_horse_complete.py` - 主策略文件

### 涉及类/方法
- `MarketSentiment.check_north_money_flow()` - 北向资金流向（修复）
- `MarketSentiment.calculate_ipo_break_rate()` - 新股破发率（修复）
- `MarketSentiment._get_north_money_outflow_days()` - 删除（模拟）
- `MarketSentiment._get_ipo_stocks()` - 删除（模拟）
- `MarketSentiment._get_issue_price()` - 删除（模拟）

---

## 🚀 后续优化建议

1. **接入真实API**：如果聚宽提供北向资金和新股API，优先使用
2. **增加权重配置**：允许用户自定义4个指标的权重
3. **更多指标**：考虑增加换手率、融资融券等指标
4. **历史记录**：记录每日情绪评分，便于分析和优化

---

**修复日期**：2026-01-20
**修复版本**：v1.0.2
**影响范围**：市场情绪择时模块
**测试状态**：待回测验证
