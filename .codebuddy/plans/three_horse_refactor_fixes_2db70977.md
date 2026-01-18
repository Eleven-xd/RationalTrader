---
name: three_horse_refactor_fixes
overview: 修复ETF轮动策略缺失的RSRS+均线过滤、成交量过滤、RSI过滤等关键逻辑，并解决未来函数问题。
todos:
  - id: analyze-differences
    content: 使用 [subagent:code-explorer] 分析原版和重构版ETF轮动策略的代码差异
    status: completed
  - id: implement-rsrs
    content: 在ETF_Rotation_Strategy类中实现完整的filter_rsrs方法及辅助函数
    status: completed
    dependencies:
      - analyze-differences
  - id: fix-volume-filter
    content: 修复成交量过滤函数，替换存在未来函数的get_volume_ratio方法
    status: completed
    dependencies:
      - analyze-differences
  - id: implement-rsi
    content: 在ETF_Rotation_Strategy类中实现calculate_rsi方法
    status: completed
    dependencies:
      - analyze-differences
  - id: implement-get-etf-rank
    content: 实现完整的get_etf_rank选股流程方法，串联五重过滤逻辑
    status: completed
    dependencies:
      - implement-rsrs
      - fix-volume-filter
      - implement-rsi
  - id: integrate-sell-method
    content: 修改sell方法，使用get_etf_rank替代现有的momentum_filter
    status: completed
    dependencies:
      - implement-get-etf-rank
  - id: verify-logic
    content: 验证修复后的策略逻辑与原版完全对齐
    status: completed
    dependencies:
      - implement-get-etf-rank
---

## 产品概述

修复ETF轮动策略（three_horse_refractor.py）中缺失的关键策略逻辑，使其与原版实现（three_horse_origin.py）完全对齐，解决未来函数问题，确保策略逻辑的一致性和准确性。

## 核心功能

- 实现完整的RSRS+均线过滤逻辑（包含斜率计算、Beta阈值计算、强度判定和多重均线判断）
- 修复成交量过滤函数中的未来函数问题（使用历史数据替代分钟级实时数据）
- 实现RSI过滤功能（计算RSI指标并过滤过热ETF）
- 对齐动量排名过滤逻辑（filter_moment_rank）
- 完善ETF轮动策略的选股流程（五重过滤：跌幅检测、动量得分、RSRS+均线、成交量、RSI）
- 添加RSRS Beta缓存机制以提升性能

## 技术栈

- 编程语言：Python
- 数据处理：pandas、numpy
- 回测框架：聚宽API（attribute_history、get_current_data、get_price等）
- 日志系统：logging

## 技术架构

### 系统架构

基于已有的面向对象策略架构，在ETF_Rotation_Strategy类中补充缺失的方法，保持代码风格一致。

### 模块划分

- **ETF_Rotation_Strategy类**：ETF轮动策略主类
- `filter_rsrs()`：RSRS+均线过滤方法
- `filter_volume_fixed()`：修复后的成交量过滤方法
- `calculate_rsi()`：RSI计算方法
- `get_etf_rank()`：完整的ETF选股流程方法
- `_get_slope()`：RSRS斜率计算辅助函数
- `_get_beta()`：RSRS Beta阈值计算辅助函数
- `_check_with_strength()`：强度判定辅助函数
- `_check_above_ma()`：均线判断辅助函数

### 数据流

ETF池 → 数据预加载 → 跌幅检测 → 动量得分过滤 → RSRS+均线过滤 → 成交量过滤 → RSI过滤 → 最终选股结果

## 实现细节

### 核心目录结构

```
/Users/dylan/Main/RationalTrader/.vscode/jukuan_three_horse/
├── three_horse_origin.py       # 原版策略文件（参考）
└── three_horse_refractor.py    # 重构版策略文件（需修复）
    ├── class ETF_Rotation_Strategy (1485-1760行)
    │   ├── filter_rsrs()           # 新增：RSRS+均线过滤
    │   ├── filter_volume_fixed()   # 新增：修复未来函数的成交量过滤
    │   ├── calculate_rsi()         # 新增：RSI计算
    │   ├── get_etf_rank()          # 新增：完整选股流程
    │   ├── _get_slope()            # 新增：斜率计算
    │   ├── _get_beta()             # 新增：Beta计算（带缓存）
    │   ├── _check_with_strength()  # 新增：强度判定
    │   └── _check_above_ma()       # 新增：均线判断
    │   ├── momentum_filter()       # 修改：集成新过滤逻辑
    │   ├── sell()                  # 修改：使用get_etf_rank
    │   └── get_volume_ratio()      # 废弃：存在未来函数问题
```

### 关键代码结构

**RSRS Beta缓存机制**：

```python
# 在ETF_Rotation_Strategy类中添加实例变量
self.rsrs_beta_cache = {}  # Beta缓存字典
self.rsrs_beta_date = None  # Beta缓存日期
```

**RSRS+均线过滤逻辑**：

```python
def filter_rsrs(self, stock_list, data_cache, context):
    """RSRS+均线过滤，包含斜率、Beta、强度和多重均线判断"""
    # 实现逻辑与原版766-889行完全对齐
    pass
```

**修复未来函数的成交量过滤**：

```python
def filter_volume_fixed(self, context, stock_list, days=7, volume_threshold=2):
    """使用历史数据计算成交量比率，避免未来函数"""
    # 使用attribute_history获取历史最新日成交量，而非当日分钟数据
    pass
```

### 技术实现方案

1. **RSRS过滤实现**：复制原版逻辑，使用预加载的data_cache，添加Beta缓存机制
2. **成交量过滤修复**：将get_price获取分钟数据改为使用attribute_history获取历史最新日数据
3. **RSI过滤实现**：实现标准RSI计算公式（14周期）
4. **选股流程整合**：在get_etf_rank方法中串联五重过滤逻辑，与原版892-959行对齐

### 集成点

- 与现有的preload_etf_data方法集成，使用数据缓存
- 与现有的momentum_filter方法配合，在sell方法中调用完整的get_etf_rank
- 利用Strategy基类的日志系统（log.info、log.warning、log.debug）

## 技术考虑

### 性能优化

- RSRS Beta缓存：避免重复计算，同一日复用Beta值
- 批量数据预加载：减少API调用次数
- 过滤顺序优化：先快速过滤，后复杂计算

### 代码质量

- 保持与原版逻辑完全一致，便于对比验证
- 添加详细的日志输出，便于调试
- 处理异常情况，避免程序中断

## Agent扩展

### SubAgent

- **code-explorer**
- 目的：搜索并对比原版和重构版代码，找出所有逻辑差异点
- 预期结果：提供完整的差异分析报告，定位所有需要修复的代码位置