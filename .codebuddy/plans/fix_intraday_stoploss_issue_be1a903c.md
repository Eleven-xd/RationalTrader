---
name: fix_intraday_stoploss_issue
overview: 修复重构版本中ETF轮动策略的日内止损功能，确保持仓记录正确同步
todos:
  - id: fix-sell-sync
    content: 修复sell方法添加持仓记录同步代码
    status: completed
  - id: fix-buy-sync
    content: 修复buy方法添加持仓记录同步代码
    status: completed
    dependencies:
      - fix-sell-sync
  - id: fix-parameter
    content: 统一g.stoploss_limit_by_cur_day参数值
    status: completed
    dependencies:
      - fix-buy-sync
  - id: verify-fix
    content: 对比原始版本验证修复完整性
    status: completed
    dependencies:
      - fix-parameter
---

## Product Overview

修复ETF轮动策略重构版本中的日内止损功能bug，确保持仓记录正确同步

## Core Features

- 修复ETF_Rotation_Strategy.sell方法中缺少持仓记录同步的问题
- 修复ETF_Rotation_Strategy.buy方法中缺少持仓记录同步的问题
- 统一g.stoploss_limit_by_cur_day参数值，消除不一致

## Tech Stack

- 项目类型：Python量化交易策略
- 当前框架：聚宽策略重构版本

## 修复目标

在现有代码基础上进行精确修复，避免引入新的逻辑变更

## 问题分析

### Bug定位

**问题1：sell方法持仓同步缺失**

- 文件位置：`jukuan_three_horse/three_horse_refractor.py`
- 代码行数：2027-2059行
- 缺失代码：`g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))`
- 影响：卖出操作后持仓列表未同步，导致日内止损使用过时数据

**问题2：buy方法持仓同步缺失**

- 文件位置：`jukuan_three_horse/three_horse_refractor.py`
- 代码行数：2061-2066行
- 缺失代码：`g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))`
- 影响：买入操作后持仓列表未同步，导致日内止损使用过时数据

**问题3：参数不一致**

- 文件位置：`jukuan_three_horse/three_horse_refractor.py`
- 冲突1：第103行`g.stoploss_limit_by_cur_day = -0.03`
- 冲突2：第156行`g.stoploss_limit_by_cur_day = -0.3`
- 原始版本：第193行统一为`-0.3`
- 影响：参数冲突可能导致止损阈值不确定

### 数据流问题

```
卖出/买入操作 → 持仓变化 → g.strategy_holdings[3]未更新 → 
stop_loss_intraday使用过时持仓列表 → 日内止损失效
```

## Implementation Details

### 修复1：sell方法添加持仓同步

**位置**：`three_horse_refractor.py`第2059行之后

```python
def sell(self, context):
    """ETF轮动策略卖出逻辑"""
    log.info(f"[{self.name}] 开始调仓")
    
    # ... 现有代码保持不变 ...
    
    g.buy_etf = targets[0] if targets else None
    
    # 添加持仓记录同步
    g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))
```

### 修复2：buy方法添加持仓同步

**位置**：`three_horse_refractor.py`第2066行之后

```python
def buy(self, context):
    """ETF轮动策略买入逻辑"""
    if g.buy_etf:
        strategy_cash = context.portfolio.total_value * g.portfolio_value_proportion[3]
        self.order_target_value_(g.buy_etf, strategy_cash)
        log.info(f"[{self.name}] 买入目标ETF: {g.buy_etf}")
    
    # 添加持仓记录同步
    g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))
```

### 修复3：统一参数值

**位置**：`three_horse_refractor.py`第103行

```python
# 修改前
g.stoploss_limit_by_cur_day = -0.03  # 当日亏损 -3% 止损

# 修改后
g.stoploss_limit_by_cur_day = -0.3  # 当日亏损 -3% 止损
```

**理由**：保持与原始版本（第193行）和重构版本第156行一致，使用-0.3作为正确的日内止损阈值

### 关键代码结构

**ETF_Rotation_Strategy类**：重构后的ETF轮动策略类，封装了卖出、买入和日内止损方法

**持仓同步逻辑**：

- `list(set(g.strategy_holdings[3]))`：去重并转为列表，确保持仓记录唯一且可迭代
- 该同步操作与原始版本保持一致（第997行和第1004行）

**stop_loss_intraday方法**（第2068-2085行）：

- 使用`g.strategy_holdings[3]`作为止损检测的持仓列表
- 依赖正确的持仓数据才能正常工作

## Technical Considerations

### 修复验证

- 对比原始版本确保修复逻辑一致
- 检查sell和buy方法修复后的持仓列表更新时机正确
- 验证参数统一后不影响其他策略

### 风险控制

- 仅添加缺失代码，不修改现有业务逻辑
- 保持代码风格与原始版本一致
- 确保不影响其他策略的持仓记录更新

### 代码质量

- 修复后持仓列表通过set去重，避免重复记录
- 保持日志输出完整性
- 维护代码可读性