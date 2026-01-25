# ETF-EPO 动态轮动策略详细说明文档

## 一、策略概述

### 1.1 策略来源与背景
本策略克隆自聚宽(JQData)社区文章《年化31%+、最大回撤12.6%-复现一个ETF-EPO策略》，作者为estivation。策略核心思想是将**动量因子**与**质量因子**进行加权混合，通过EPO(Elastic Portfolio Optimization)算法计算最优权重，并结合多种约束条件进行风险控制。

### 1.2 核心创新点
- **因子混合架构**：动量因子(30%) + 质量因子(70%)的加权评分体系
- **动态收缩机制**：基于波动率的GARCH锚定收缩系数
- **成交拥挤度约束**：通过量价关系识别并惩罚过度拥挤的交易
- **多层次风险控制**：行业敞口限制、A股持仓限制、最大权重限制

---

## 二、ETF池与基础配置

### 2.1 策略ETF池
```python
g.etf_pool = [
    "518880.XSHG",  # 黄金ETF (避险资产)
    "159915.XSHE",  # 创业板ETF (高成长)
    "513100.XSHG",  # 恒生ETF (港股)
    "513600.XSHG",  # 红利ETF (高股息)
    "159980.XSHE",  # 有色金属ETF (周期行业)
    "159930.XSHE",  # 能源ETF (周期行业)
    "159985.XSHE",  # 创新药ETF (医药行业)
]
```

### 2.2 ETF分类
| ETF代码 | 类型 | 说明 |
|---------|------|------|
| 518880.XSHG | 黄金 | 避险资产，与A股低相关 |
| 513600.XSHG | 红利 | 高股息策略，稳定收益 |
| 513100.XSHG | 港股 | 境外资产，地域分散 |
| 159915.XSHE | A股成长 | 创业板，高波动高收益 |
| 159930.XSHE | 能源 | 周期性行业 |
| 159980.XSHE | 有色 | 周期性行业 |
| 159985.XSHE | 医药 | 防御性行业 |

---

## 三、代码执行流程

### 3.1 整体架构图
```
initialize() 
    ↓
run_weekly(calc_factors) → 每周三 11:00 计算因子
    ↓
run_weekly(rebalance) → 每周三 11:15 执行调仓
```

### 3.2 initialize() 初始化流程 (第19-141行)

#### 3.2.1 基础设置
```python
set_benchmark("000300.XSHG")  # 基准：沪深300
set_option("use_real_price", True)  # 使用实时价格
set_slippage(FixedSlippage(3/10000))  # 滑点：0.03%
set_order_cost(...)  # 手续费：万2.5，最小0.2元
```

#### 3.2.2 窗口参数配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| momentum_window | 25 | 动量计算窗口 |
| momentum_lookback | 25 | 动量回看期 |
| quality_window | 25 | 质量因子窗口 |
| quality_lookback | 25 | 质量因子回看期 |
| cov_window | 60 | 协方差计算窗口 |
| garch_window | 120 | GARCH波动率预测窗口 |
| volume_short_window | 5 | 短期成交量均线 |
| volume_long_window | 20 | 长期成交量均线 |

#### 3.2.3 因子权重参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| score_weight_momentum | 0.3 | 动量因子权重 |
| score_weight_quality | 0.7 | 质量因子权重 |
| anchor_weight | 0.1 | 锚定信号权重(GARCH波动率) |
| signal_power | 1.4 | 信号幂次变换，增强分化 |

#### 3.2.4 风险控制参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_holdings | 6 | 最大持仓数量 |
| min_holdings | 1 | 最小持仓数量 |
| max_weight | 0.85 | 单只ETF最大权重 |
| use_dynamic_max_weight | True | 动态最大权重调整 |
| use_risk_parity | False | 风险平价开关 |

#### 3.2.5 行业/A股持仓限制
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_a_share_holdings | 2 | A股ETF最大持仓数 |
| a_share_weight_cap | 0.7 | A股ETF总权重上限 |
| max_industry_holdings | 1 | 单一行业ETF最大持仓数 |
| industry_weight_cap | 0.35 | 行业ETF总权重上限 |

#### 3.2.6 EPO算法参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| epo_risk_aversion | 8.0 | 风险厌恶系数 |
| epo_shrinkage | 0.2 | 协方差收缩系数 |
| use_dynamic_shrinkage | True | 动态收缩开关 |
| shrinkage_floor | 0.05 | 收缩系数下限 |
| shrinkage_cap | 0.6 | 收缩系数上限 |

#### 3.2.7 成交拥挤度参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| volume_ratio_threshold | 1.6 | 放量阈值(短期/长期成交量比) |
| volume_penalty_power | 0.8 | 放量惩罚幂次 |
| use_relative_crowding | True | 相对拥挤度开关 |
| relative_crowding_power | 1.0 | 相对拥挤度惩罚幂次 |

---

## 四、核心函数详解

### 4.1 calc_factors() - 因子计算 (第143-285行)

**功能**：计算所有ETF的多维因子得分

**执行流程**：
1. 获取前一交易日
2. 提取所需历史数据(max(garch_window)+5天)
3. 对每个ETF计算7个质量因子 + 1个动量因子
4. 将原始因子转换为排名得分或Z-score
5. 计算综合信号：signal = 0.3×momentum + 0.7×quality
6. 应用行业惩罚和溢价惩罚

**质量因子构成**：
| 因子名 | 计算方法 | 排名方向 |
|--------|----------|----------|
| sharpe_score | 年化夏普比率 | 越高越好 |
| mdd_score | 最大回撤 | 越低越好 |
| vol_score | 年化波动率 | 越低越好 |
| vol_stability_score | 波动率稳定性 | 越低越好 |
| volume_stability_score | 成交量稳定性 | 越低越好 |
| logret_score | 对数收益率 | 越高越好 |
| r2_score | 价格趋势R² | 越高越好 |

**动量因子**：
```python
momentum = 年化收益率 × R²
```
这种计算方式确保动量信号既有趋势强度(R²)又有实际收益(年化收益率)。

### 4.2 _compute_metrics() - 指标计算 (第486-539行)

**功能**：计算单个ETF的完整因子指标集

**核心计算函数**：

| 函数名 | 功能 | 公式 |
|--------|------|------|
| _calc_sharpe() | 夏普比率 | mean/std × √252 |
| _calc_max_drawdown() | 最大回撤 | min(price/max(price) - 1) |
| _calc_volatility() | 年化波动率 | std × √252 |
| _calc_vol_stability() | 波动率稳定性 | 滚动波动率的标准差 |
| _calc_volume_stability() | 成交量稳定性 | 成交量变化率的标准差 |
| _calc_log_return() | 对数收益率 | log(P_end/P_start) |
| _calc_r2() | 趋势R² | 1 - SS_res/SS_tot |
| _calc_momentum() | 动量因子 | 年化收益 × R² |
| _calc_volume_ratio() | 放量比 | 5日均量/20日均量 |
| _calc_trend_filter() | 趋势过滤 | 价格≥均线 且 回撤≤阈值 |

### 4.3 rebalance() - 调仓执行 (第287-401行)

**功能**：执行完整的调仓逻辑

**执行流程**：
```
1. 过滤信号为正的ETF
2. 筛选候选ETF(应用各种约束)
3. 构建收益率矩阵
4. 计算EPO最优权重
5. 应用成交拥挤度惩罚
6. 应用分组权重限制(行业/A股)
7. 执行交易订单
```

### 4.4 _epo_weights() - EPO权重计算 (第462-484行)

**核心算法**：
```python
# 1. 收缩协方差矩阵
shrunk_cov = (1-δ) × Cov + δ × diag(diag(Cov))
# δ为收缩系数，diag(diag(Cov))为单位矩阵

# 2. 计算逆协方差
inv_cov = shrunk_cov⁻¹

# 3. 最优权重
w = inv_cov × signal / λ
# λ为风险厌恶系数

# 4. 仅做多约束
w = max(0, w)
```

**EPO算法原理**：
- 基于均值-方差框架，但用因子信号替代预期收益
- 收缩协方差矩阵防止过拟合
- 风险厌恶系数控制组合波动

### 4.5 _build_anchor_signal() - 锚定信号 (第970-986行)

**功能**：基于GARCH模型预测波动率，生成反向锚定信号

**执行步骤**：
1. 用GARCH(1,1)模型预测未来波动率
2. 对ETF按波动率排名
3. 低波动ETF获得更高信号

**GARCH模型**：
```python
r_t = μ + ε_t
ε_t = σ_t × z_t
σ²_t = ω + α × ε²_{t-1} + β × σ²_{t-1}
```

### 4.6 _dynamic_shrinkage() - 动态收缩 (第958-968行)

**功能**：根据市场波动率自适应调整收缩系数

**公式**：
```python
shrinkage = 1.0 - 0.1 / avg_volatility
```
- 市场波动高时，收缩系数趋向收缩下限(保守)
- 市场波动低时，收缩系数趋向收缩上限(激进)

### 4.7 _execute_orders() - 订单执行 (第403-445行)

**功能**：安全执行调仓订单

**执行逻辑**：
1. 计算目标持仓份额
2. 先卖出不在目标列表中的持仓
3. 对需要减仓的ETF执行减仓
4. 释放资金后再执行加仓

**优势**：避免资金不足导致的订单失败

---

## 五、策略原理深度解析

### 5.1 因子框架原理

#### 5.1.1 动量因子 (30%)
动量因子捕捉资产的中期趋势强度。通过计算**年化收益率 × R²**，既考虑了收益幅度，又考虑了趋势的稳定性。R²越高，说明价格走势越接近线性趋势，反转可能性越低。

#### 5.1.2 质量因子 (70%)
质量因子从多个维度评估ETF的"质量"：
- **风险调整收益**：夏普比率
- **下行风险**：最大回撤、波动率
- **稳定性**：波动率稳定性、成交量稳定性
- **趋势强度**：R²、对数收益率

质量因子权重(70%)高于动量因子，体现了策略对"稳健收益"的偏好。

### 5.2 EPO算法原理

EPO(Elastic Portfolio Optimization)是Black-Litterman模型的简化版本：

1. **信号作为预期收益代理**：
   $$E[R] = \tau \times \Sigma \times \pi$$
   其中π是因子信号向量

2. **收缩协方差估计**：
   $$\hat{\Sigma} = (1-\delta)\Sigma + \delta D$$
   D是对角矩阵，防止协方差矩阵病态

3. **最优组合权重**：
   $$w = \frac{1}{\gamma} \hat{\Sigma}^{-1} E[R]$$

### 5.3 成交拥挤度检测

当某ETF出现放量上涨时，可能意味着：
- 大量跟风盘涌入
- 回调风险增加
- 短期泡沫形成

策略通过**短期/长期成交量比**识别这种情况，并相应降权。

### 5.4 动态调整机制

| 动态调整项 | 触发条件 | 调整方向 |
|------------|----------|----------|
| 最小持仓数 | 行业回撤大 | 从1→2，增加分散度 |
| 最大权重 | 行业回撤大 | 从85%→75%，降低集中度 |
| A股权重上限 | 行业回撤大 | 从70%→55%，降低敞口 |
| 收缩系数 | 波动率高 | 收缩系数↓，更保守 |

---

## 六、交易成本与滑点

### 6.1 交易成本设置
```python
OrderCost(
    open_tax=0,           # 买入印花税：0
    close_tax=0,          # 卖出印花税：0
    open_commission=2.5/10000,  # 买入佣金：万2.5
    close_commission=2.5/10000, # 卖出佣金：万2.5
    min_commission=0.2,   # 最低佣金：0.2元
)
```

### 6.2 滑点设置
```python
FixedSlippage(3/10000)  # 固定滑点：0.03%
```

---

## 七、策略改善建议

### 7.1 因子层面优化

#### 7.1.1 增加更多因子维度
- **质量因子**：可加入盈利质量、资产负债率等财务因子
- **动量因子**：可加入3个月、6个月、12个月多周期动量
- **情绪因子**：可加入期权隐含波动率、融券余额变化

#### 7.1.2 因子正交化
当前因子存在相关性高的问题，建议对因子进行**正交化处理**：
```python
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

def orthogonalize_factors(factor_df):
    scaler = StandardScaler()
    X = scaler.fit_transform(factor_df[factor_cols])
    pca = PCA(n_components=0.95)  # 保留95%方差
    return pca.fit_transform(X)
```

### 7.2 轮动频率优化

#### 7.2.1 自适应调仓周期
当前固定为每周调仓，可改为**根据市场状态自适应调整**：
- 市场趋势强时：维持周频
- 市场震荡时：降低频率至双周/月频

#### 7.2.2 日内择时
在每周三11:00-11:15调仓的基础上，可加入**日内择时**：
- 在开盘30分钟内执行订单，避免流动性不足
- 避开集合竞价阶段

### 7.3 风险控制增强

#### 7.3.1 加入波动率目标
```python
def apply_vol_target(weights, returns_df, target_vol=0.15):
    current_vol = returns_df.std() * np.sqrt(252)
    current_vol = (weights * current_vol).sum()
    scaling = target_vol / current_vol
    return weights * min(scaling, 1.0)
```

#### 7.3.2 加入VaR约束
```python
def apply_var_constraint(weights, returns_df, var_limit=0.05):
    portfolio_returns = returns_df.dot(weights)
    var = np.percentile(portfolio_returns, 5)
    if var < -var_limit:
        # 降权高波动资产
        pass
    return weights
```

#### 7.3.3 加入相关性过滤
当两只ETF相关性超过阈值时，限制其总权重：
```python
CORR_THRESHOLD = 0.8
```

### 7.4 EPO算法改进

#### 7.4.1 加入Black-Litterman框架
```python
def black_litterman(returns, signal, market_cap, tau=0.05):
    # 市值加权作为先验
    pi = np.log(market_cap / market_cap.sum())  
    # 融入信号观点
    P = np.eye(len(signal))
    Q = signal * 0.3  # 30%信心度
    # 计算后验收益
    posterior = ...
    return posterior
```

#### 7.4.2 加入风险预算约束
```python
def apply_risk_budget(weights, returns_df, risk_budget=None):
    vols = returns_df.std() * np.sqrt(252)
    risk_contrib = weights * vols / (weights * vols).sum()
    if risk_budget is None:
        risk_budget = np.ones(len(weights)) / len(weights)
    # 优化使风险贡献接近风险预算
```

### 7.5 交易执行优化

#### 7.5.1 引入算法交易
- 使用TWAP/VWAP算法执行大额订单
- 分时拆分订单，减少市场冲击

#### 7.5.2 加入流动性过滤
```python
def filter_by_liquidity(etfs, min_turnover=1e7):
    # 剔除日均成交额低于阈值的ETF
    pass
```

### 7.6 参数优化建议

#### 7.6.1 参数敏感性分析
建议对以下关键参数进行敏感性测试：
- momentum_window: [20, 25, 30]
- quality_window: [20, 25, 30]
- score_weight_momentum: [0.2, 0.3, 0.4]
- epo_risk_aversion: [6, 8, 10]

#### 7.6.2 引入机器学习优化
使用贝叶斯优化或遗传算法寻找最优参数组合：
```python
from bayes_opt import BayesianOptimization

def objective(momentum_window, quality_window, score_weight):
    # 运行回测
    return sharpe_ratio

optimizer = BayesianOptimization(objective, params)
optimizer.maximize()
```

### 7.7 策略容量与延展性

#### 7.7.1 扩展ETF池
当前仅7只ETF，可扩展至：
- 增加更多行业ETF
- 增加跨境ETF(美股、欧洲)
- 增加商品ETF

#### 7.7.2 加入主动管理ETF
考虑纳入增强型ETF，可能获得超额收益。

### 7.8 尾部风险管理

#### 7.8.1 加入尾部对冲
- 配置5-10%资产于看跌期权或VIX相关产品
- 在市场恐慌时对冲下行风险

#### 7.8.2 动态止损
```python
def apply_trailing_stop(context, trailing_pct=0.1):
    # 对持仓设置移动止损
    pass
```

---

## 八、策略性能基准

根据原始回测数据：
- **年化收益率**：31%+
- **最大回撤**：12.6%
- **夏普比率**：约1.5-2.0

---

## 九、总结

ETF-EPO策略是一个多因子驱动的动态资产配置策略，其核心优势在于：
1. **多维度评估**：同时考虑动量和质量因子
2. **自适应机制**：根据市场状态动态调整参数
3. **风险控制**：多层次约束防止过度集中
4. **量化框架**：可回测、可优化、可延展

建议在实盘应用前进行充分的参数稳定性测试和压力测试，并关注策略在不同市场环境下的表现差异。

---

*文档生成时间：2026年1月*
*策略来源：聚宽社区*
*代码版本：etf_epo.py (1017行)*
