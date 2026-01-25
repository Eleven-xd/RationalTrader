# 克隆自聚宽文章：https://www.joinquant.com/post/66279
# 标题：年化31%+、最大回撤12.6%-复现一个ETF-EPO策略
# 作者：estivation

# 动量 + 质量因子 -> EPO 权重（动态收缩 + GARCH 锚定）
# -> 成交拥挤度约束 + 滑动窗口指标
# -> 多周期动量 + 相对/绝对动量自适应切换（优化版）

# ==============================================================================
# 策略配置指南
# ==============================================================================
#
# 【配置动量类型】
#
# 1. 关闭相对动量（推荐 - 当前配置）:
#     g.use_multi_period_momentum = True   # 启用多周期动量
#     g.use_adaptive_momentum = False       # 关闭自适应模式
#     g.force_absolute_momentum = True      # 强制使用绝对动量
#     g.enable_relative_momentum = False     # 完全禁用相对动量
#
# 2. 启用相对动量（不推荐 - 可能降低收益）:
#     g.use_multi_period_momentum = True
#     g.use_adaptive_momentum = True
#     g.force_absolute_momentum = False
#     g.enable_relative_momentum = True
#
# 3. 使用原版单周期动量（25天: 年化收益×R²）:
#     g.use_multi_period_momentum = False
#     g.force_absolute_momentum = False
#
# 【配置多周期动量参数】
#     g.momentum_periods = [20, 40, 60]     # 回看周期
#     g.momentum_weights = [0.5, 0.3, 0.2]  # 权重配置
#     g.momentum_use_r2_factor = True       # 使用R²稳定性因子
#
# ==============================================================================

from jqdata import *
import numpy as np
import pandas as pd
import math
from prettytable import PrettyTable
import prettytable

try:
    from arch import arch_model

    _ARCH_AVAILABLE = True
except Exception:
    arch_model = None
    _ARCH_AVAILABLE = False


ETF_NAME_MAP = {
    "518880.XSHG": "黄金ETF",
    "159915.XSHE": "创业板ETF",
    "513100.XSHG": "恒生ETF",
    "513600.XSHG": "红利ETF",
    "159980.XSHE": "有色ETF",
    "159930.XSHE": "能源ETF",
    "159985.XSHE": "创新药ETF",
}

ETF_CATEGORY_MAP = {
    "518880.XSHG": "商品",
    "159915.XSHE": "A股成长",
    "513100.XSHG": "港股",
    "513600.XSHG": "红利",
    "159980.XSHE": "周期行业",
    "159930.XSHE": "能源行业",
    "159985.XSHE": "医药行业",
}


def _format_etf_code(etf_code):
    """美化ETF代码显示"""
    name = ETF_NAME_MAP.get(etf_code, "ETF")
    code = etf_code.split(".")[0]
    return f"{code}({name})"


def _get_etf_name(etf_code):
    """获取ETF名称"""
    return ETF_NAME_MAP.get(etf_code, etf_code)


def _get_etf_category(etf_code):
    """获取ETF分类"""
    return ETF_CATEGORY_MAP.get(etf_code, "其他")


def _get_trend_emoji(trend_ok):
    """获取趋势状态表情"""
    return "✅ 上涨趋势" if trend_ok else "⚠️ 趋势不佳"


def _get_signal_bar(signal, max_signal=1.0):
    """生成信号强度进度条"""
    if pd.isna(signal) or signal <= 0:
        return "░░░░░░░░░░"
    ratio = min(signal / max_signal, 1.0) if max_signal > 0 else 0
    filled = int(ratio * 10)
    return "█" * filled + "░" * (10 - filled)


def _get_pnl_emoji(pnl_ratio):
    """根据盈亏比例返回表情"""
    if pnl_ratio > 0.1:
        return "🤑 大涨"
    elif pnl_ratio > 0.05:
        return "😄 上涨"
    elif pnl_ratio > 0:
        return "📈 小涨"
    elif pnl_ratio > -0.05:
        return "📉 小跌"
    elif pnl_ratio > -0.1:
        return "😟 大跌"
    else:
        return "🤬 暴跌"


def _print_header(title, width=70):
    """打印分隔标题"""
    log.info("")
    log.info(f"{'=' * width}")
    log.info(f"  {title}")
    log.info(f"{'=' * width}")


def _print_subheader(subtitle):
    """打印副标题"""
    log.info(f"─── {subtitle} ───")


def _print_factor_table(factor_df, top_n=7):
    """使用PrettyTable打印因子得分排名"""
    if factor_df is None or factor_df.empty:
        return

    _print_header("📊 因子信号排名")

    table = PrettyTable(
        [
            "排名",
            "ETF代码",
            "ETF名称",
            "综合信号",
            "动量分",
            "质量分",
            "放量比",
            "趋势",
        ]
    )
    table.hrules = prettytable.ALL
    table.align = "r"
    table.align = "l"

    sorted_df = factor_df.sort_values("signal", ascending=False).head(top_n)

    for rank, (etf, row) in enumerate(sorted_df.iterrows(), 1):
        momentum_score = row.get("momentum_score", row.get("momentum_z", 0))
        quality_score = row.get("quality_score", 0)
        signal = row.get("signal", 0)
        volume_ratio = row.get("volume_ratio", 1.0)
        trend_ok = row.get("trend_ok", True)

        trend_emoji = "✅" if trend_ok else "⚠️"

        table.add_row(
            [
                f"#{rank}",
                _format_etf_code(etf),
                _get_etf_name(etf),
                f"{signal:.4f}",
                f"{momentum_score:.3f}",
                f"{quality_score:.3f}",
                f"{volume_ratio:.2f}x",
                trend_emoji,
            ]
        )

    log.info(f"\n{table}\n")


def _print_weight_table(target_weights, factor_df, total_value):
    """使用PrettyTable打印目标权重"""
    if not target_weights or factor_df is None:
        return

    _print_header("🎯 调仓目标")

    table = PrettyTable(
        [
            "ETF代码",
            "ETF名称",
            "分类",
            "目标权重",
            "预估金额",
            "信号得分",
            "动量分",
            "质量分",
            "放量比",
            "趋势",
        ]
    )
    table.hrules = prettytable.ALL
    table.align = "l"
    table.align = "r"

    sorted_weights = dict(
        sorted(target_weights.items(), key=lambda x: x[1], reverse=True)
    )

    for etf, weight in sorted_weights.items():
        if etf not in factor_df.index:
            continue

        row = factor_df.loc[etf]
        est_amount = total_value * weight
        momentum_score = row.get("momentum_score", row.get("momentum_z", 0))
        quality_score = row.get("quality_score", 0)
        signal = row.get("signal", 0)
        volume_ratio = row.get("volume_ratio", 1.0)
        trend_ok = row.get("trend_ok", True)
        trend_emoji = "✅" if trend_ok else "⚠️"

        table.add_row(
            [
                _format_etf_code(etf),
                _get_etf_name(etf),
                _get_etf_category(etf),
                f"{weight * 100:.1f}%",
                f"¥{est_amount:,.0f}",
                f"{signal:.4f}",
                f"{momentum_score:.3f}",
                f"{quality_score:.3f}",
                f"{volume_ratio:.2f}x",
                trend_emoji,
            ]
        )

    log.info(f"\n📈 总资产: ¥{total_value:,.2f}")
    log.info(f"\n{table}\n")

    weight_summary = ", ".join(
        [f"{_get_etf_name(k)}: {v * 100:.1f}%" for k, v in sorted_weights.items()]
    )
    log.info(f"📋 权重分配: {weight_summary}")


def _print_metrics_summary(metrics_df):
    """打印关键指标汇总"""
    if metrics_df is None or metrics_df.empty:
        return

    _print_header("📈 策略指标监控")

    top_etf = metrics_df["signal"].idxmax()
    best_signal = metrics_df.loc[top_etf, "signal"]
    best_momentum = metrics_df.loc[top_etf, "momentum"]
    best_quality = metrics_df.loc[top_etf, "quality_score"]

    worst_etf = metrics_df["signal"].idxmin()
    worst_signal = metrics_df.loc[worst_etf, "signal"]

    avg_signal = metrics_df["signal"].mean()
    avg_momentum = metrics_df["momentum"].mean()
    avg_quality = metrics_df["quality_score"].mean()

    log.info(f"🏆 最佳信号: {_get_etf_name(top_etf)} = {best_signal:.4f}")
    log.info(f"   动量得分: {best_momentum:.4f} | 质量得分: {best_quality:.4f}")
    log.info(f"")
    log.info(f"📉 最差信号: {_get_etf_name(worst_etf)} = {worst_signal:.4f}")
    log.info(f"")
    log.info(f"📊 平均信号: {avg_signal:.4f}")
    log.info(f"   平均动量: {avg_momentum:.4f} | 平均质量: {avg_quality:.4f}")

    if "momentum_mode" in metrics_df.columns:
        mode_counts = metrics_df["momentum_mode"].value_counts()
        log.info(f"")
        log.info(f"🔀 动量模式分布:")
        for mode, count in mode_counts.items():
            if mode == "relative":
                mode_name = "相对动量"
            elif mode == "hybrid":
                mode_name = "混合动量"
            elif mode == "original":
                mode_name = "原版动量"
            else:
                mode_name = "绝对动量"
            log.info(f"   {mode_name}: {count}只")


def _print_daily_summary(context, positions):
    """每日收盘后打印持仓汇总"""
    _print_header(f"📅 每日收盘汇总 - {context.current_dt.strftime('%Y-%m-%d')}")

    total_value = context.portfolio.total_value

    if not positions:
        log.info(f"🚤 当前总资产: ¥{total_value:,.2f}  (空仓)")
        return

    table = PrettyTable(
        [
            "ETF代码",
            "ETF名称",
            "持仓数量",
            "持仓成本",
            "当前价格",
            "盈亏比例",
            "盈亏金额",
            "市值",
            "仓位占比",
        ]
    )
    table.hrules = prettytable.ALL
    table.align = "l"
    table.align = "r"

    total_market_value = 0
    for etf, pos in positions.items():
        current_price = pos.price
        avg_cost = pos.avg_cost
        shares = pos.total_amount
        market_value = shares * current_price
        total_market_value += market_value

        pnl_ratio = (current_price - avg_cost) / avg_cost if avg_cost > 0 else 0
        pnl_amount = (current_price - avg_cost) * shares
        weight = market_value / total_value

        pnl_emoji = _get_pnl_emoji(pnl_ratio)
        pnl_str = f"{pnl_emoji} {pnl_ratio * 100:+.2f}%"

        table.add_row(
            [
                _format_etf_code(etf),
                _get_etf_name(etf),
                f"{shares:,}",
                f"¥{avg_cost:.3f}",
                f"¥{current_price:.3f}",
                pnl_str,
                f"¥{pnl_amount:+,.0f}",
                f"¥{market_value:,.0f}",
                f"{weight * 100:.1f}%",
            ]
        )

    log.info(f"\n💰 总资产: ¥{total_value:,.2f}")
    log.info(f"📊 持仓市值: ¥{total_market_value:,.2f}")
    log.info(f"\n{table}\n")

    category_weights = {}
    for etf in positions.keys():
        category = _get_etf_category(etf)
        weight = positions[etf].total_amount * positions[etf].price / total_value
        category_weights[category] = category_weights.get(category, 0) + weight

    cat_str = ", ".join(
        [
            f"{k}: {v * 100:.1f}%"
            for k, v in sorted(
                category_weights.items(), key=lambda x: x[1], reverse=True
            )
        ]
    )
    log.info(f"📈 分类配置: {cat_str}")


def _print_rebalance_summary(changes):
    """打印调仓变更汇总"""
    if not changes:
        log.info("\n📋 本次调仓: 无变更")
        return

    buys = [etf for etf, change in changes.items() if change == "BUY"]
    sells = [etf for etf, change in changes.items() if change == "SELL"]
    holds = [etf for etf, change in changes.items() if change == "HOLD"]

    _print_header("🔄 调仓执行摘要")

    if buys:
        log.info(f"\n🟢 买入 ({len(buys)}只):")
        for etf in buys:
            log.info(f"   + {_format_etf_code(etf)} ({_get_etf_name(etf)})")

    if sells:
        log.info(f"\n🔴 卖出 ({len(sells)}只):")
        for etf in sells:
            log.info(f"   - {_format_etf_code(etf)} ({_get_etf_name(etf)})")

    if holds:
        log.info(f"\n🟡 持有 ({len(holds)}只):")
        hold_str = ", ".join([_get_etf_name(e) for e in holds])
        log.info(f"   = {hold_str}")


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(3 / 10000))
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=2.5 / 10000,
            close_commission=2.5 / 10000,
            min_commission=0.2,
        ),
        type="fund",
    )
    log.set_level("system", "error")
    log.set_level("order", "error")

    g.etf_pool = [
        "518880.XSHG",
        "159915.XSHE",
        "513100.XSHG",
        "513600.XSHG",
        "159980.XSHE",
        "159930.XSHE",
        "159985.XSHE",
    ]

    g.momentum_window = 25
    g.momentum_lookback = 25
    g.quality_window = 25
    g.quality_lookback = 25
    g.cov_window = 60
    g.garch_window = 120
    g.volume_short_window = 5
    g.volume_long_window = 20

    g.score_weight_momentum = 0.3
    g.score_weight_quality = 0.7
    g.anchor_weight = 0.1
    g.max_holdings = 6
    g.use_rank_scoring = True
    g.quality_floor = 0.4
    g.momentum_floor = 0.0
    g.signal_power = 1.4
    g.use_window_mean = True
    g.min_holdings = 1
    g.min_holdings_risk = 2
    g.min_holdings_dd_threshold = 0.05
    g.use_dynamic_min_holdings = True
    g.max_weight = 0.85
    g.max_weight_high = 0.85
    g.max_weight_low = 0.75
    g.max_weight_dd_threshold = 0.05
    g.use_dynamic_max_weight = True
    g.use_risk_parity = False
    g.use_trend_filter = False
    g.trend_window = 20
    g.max_dd_filter = 0.08
    g.trend_penalty = 0.6
    g.trend_hard_filter = False
    g.min_lot = 100
    g.fallback_etf = "518880.XSHG"
    g.max_a_share_holdings = 2
    g.a_share_weight_cap = 0.7
    g.a_share_weight_cap_high = 0.7
    g.a_share_weight_cap_low = 0.55
    g.a_share_dd_threshold = 0.05
    g.use_dynamic_a_share_cap = True
    g.industry_penalty = 0.85
    g.industry_weight_cap_high = 0.35
    g.industry_weight_cap_low = 0.25
    g.industry_dd_threshold = 0.05
    g.use_dynamic_industry_cap = True
    g.max_industry_holdings = 1
    g.industry_weight_cap = 0.35
    g.avoid_industry = False
    g.premium_filter_enabled = True
    g.premium_threshold = 5.0
    g.premium_penalty = 0.5
    g.premium_hard_filter = False
    g.premium_etfs = {"513100.XSHG"}
    g.a_share_etfs = {
        "159915.XSHE",
        "159930.XSHE",
        "159980.XSHE",
    }
    g.industry_etfs = {
        "159930.XSHE",
        "159980.XSHE",
    }

    g.epo_risk_aversion = 8.0
    g.epo_shrinkage = 0.2
    g.use_dynamic_shrinkage = True
    g.shrinkage_floor = 0.05
    g.shrinkage_cap = 0.6

    g.volume_ratio_threshold = 1.6
    g.volume_penalty_power = 0.8
    g.use_relative_crowding = True
    g.relative_crowding_power = 1.0
    g.relative_crowding_floor = 0.6
    g.relative_crowding_ceiling = 1.6
    g.dd_penalty_threshold = 0.05
    g.dd_penalty_power = 1.0
    g.dd_penalty_floor = 0.6

    g.rebalance_weekday = 3
    g.factor_time = "11:00"
    g.rebalance_time = "11:15"

    g.price_cache = {}
    g.factor_df = None

    run_weekly(calc_factors, weekday=g.rebalance_weekday, time=g.factor_time)
    run_weekly(rebalance, weekday=g.rebalance_weekday, time=g.rebalance_time)

    run_daily(daily_summary, "15:00")

    g.benchmark_etf = "000300.XSHG"

    # ======================================================================
    # 多周期动量参数配置（新增）
    # ======================================================================
    # 是否启用多周期动量计算（替代原版单周期25天动量）
    # True: 使用多周期加权动量
    # False: 使用原版单周期动量 (25天: 年化收益 × R²)
    g.use_multi_period_momentum = True

    # 多周期动量的回看周期配置
    # 默认: [20, 40, 60] = 20天(短期) + 40天(中期) + 60天(长期)
    # 注意: 总数据需求 = max(periods) + 5 = 65天
    g.momentum_periods = [20, 40, 60]

    # 各周期权重配置（必须与periods长度一致，权重和=1.0）
    # 推荐配置:
    #   [0.5, 0.3, 0.2] -> 短期为主，响应较快
    #   [0.4, 0.4, 0.2] -> 均衡配置
    #   [0.6, 0.25, 0.15] -> 更激进，短期权重更高
    g.momentum_weights = [0.5, 0.3, 0.2]

    # 是否在动量计算中引入R²稳定性因子
    # True: 动量 = 收益率 × R²（确保趋势稳定）
    # False: 动量 = 收益率（可能选中波动大的标的）
    g.momentum_use_r2_factor = True

    # ======================================================================
    # 相对动量/自适应动量参数配置（新增）
    # ======================================================================
    # 是否启用自适应动量模式（根据市场环境切换绝对/相对动量）
    # True: 根据市场环境自动选择动量类型
    # False: 强制使用绝对动量（推荐：关闭相对动量）
    g.use_adaptive_momentum = False

    # 自适应动量模式下的市场环境检测周期（天数）
    # 较短周期响应更快，但可能更敏感
    # 推荐: 20天（20个交易日约1个月）
    g.market_regime_window = 20

    # 当 use_adaptive_momentum=False 时，是否强制使用绝对动量
    # True: 强制使用绝对动量（推荐：True，关闭相对动量）
    # False: 使用原版单周期动量
    g.force_absolute_momentum = True

    # 相对动量开关（如果想完全禁用相对动量相关逻辑，设置以下参数）
    g.enable_relative_momentum = False

    # 相对动量的混合权重（当自适应模式开启时使用）
    # 格式: [绝对动量权重, 相对动量权重]
    # 例如 [0.7, 0.3] 表示 70%绝对动量 + 30%相对动量
    g.momentum_mix_weights = [0.7, 0.3]

    # 市场环境切换阈值
    # 强劲牛市阈值: 20日涨幅 > strong_bull_threshold 时，100%使用绝对动量
    # 牛市阈值: 20日涨幅 > bull_threshold 时，增加绝对动量权重
    # 熊市阈值: 20日涨幅 < bear_threshold 时，增加相对动量权重
    g.strong_bull_threshold = 0.08  # 8%
    g.bull_threshold = 0.03  # 3%
    g.bear_threshold = -0.05  # -5%


def calc_factors(context):
    g.price_cache = {}
    g.factor_df = None

    prev_day = _previous_trade_day(context)
    if prev_day is None:
        log.warn("no previous trade day")
        return

    need_days = (
        max(
            g.momentum_lookback,
            g.quality_lookback,
            g.cov_window,
            g.volume_long_window,
            g.garch_window,
            120,
        )
        + 5
    )
    min_len = max(g.momentum_window, g.quality_window, g.volume_long_window) + 1

    for etf in g.etf_pool:
        data = get_price(
            etf,
            count=need_days,
            end_date=prev_day,
            frequency="daily",
            fields=["close", "volume", "money"],
        )
        if data is None or data.empty:
            continue
        data = data.dropna()
        if len(data) < min_len:
            continue
        g.price_cache[etf] = data

    if not g.price_cache:
        log.warn("no price data in cache")
        return

    metrics = {}
    for etf, data in g.price_cache.items():
        close = data["close"].values
        if "money" in data:
            turnover = data["money"].fillna(0).values
        else:
            turnover = data["volume"].fillna(0).values
        metrics[etf] = _compute_metrics(close, turnover, etf)

    metrics_df = pd.DataFrame(metrics).T
    if metrics_df.empty:
        log.warn("empty metrics")
        return

    if g.use_rank_scoring:
        metrics_df["momentum_score"] = _rank_score(metrics_df["momentum"], True)
        metrics_df["sharpe_score"] = _rank_score(metrics_df["sharpe"], True)
        metrics_df["mdd_score"] = _rank_score(metrics_df["max_drawdown"], False)
        metrics_df["vol_score"] = _rank_score(metrics_df["volatility"], False)
        metrics_df["vol_stability_score"] = _rank_score(
            metrics_df["vol_stability"], False
        )
        metrics_df["volume_stability_score"] = _rank_score(
            metrics_df["volume_stability"], False
        )
        metrics_df["logret_score"] = _rank_score(metrics_df["log_return"], True)
        metrics_df["r2_score"] = _rank_score(metrics_df["r2"], True)

        metrics_df["quality_score"] = metrics_df[
            [
                "sharpe_score",
                "mdd_score",
                "vol_score",
                "vol_stability_score",
                "volume_stability_score",
                "logret_score",
                "r2_score",
            ]
        ].mean(axis=1)
        metrics_df["signal"] = (
            g.score_weight_momentum * metrics_df["momentum_score"]
            + g.score_weight_quality * metrics_df["quality_score"]
        )
        if g.industry_penalty < 1:
            metrics_df.loc[metrics_df.index.isin(g.industry_etfs), "signal"] *= (
                g.industry_penalty
            )
        if g.trend_penalty < 1:
            metrics_df.loc[~metrics_df["trend_ok"], "signal"] *= g.trend_penalty
    else:
        metrics_df["momentum_z"] = _zscore(metrics_df["momentum"])
        metrics_df["sharpe_z"] = _zscore(metrics_df["sharpe"])
        metrics_df["mdd_z"] = _zscore(-metrics_df["max_drawdown"])
        metrics_df["vol_z"] = _zscore(-metrics_df["volatility"])
        metrics_df["vol_stability_z"] = _zscore(-metrics_df["vol_stability"])
        metrics_df["volume_stability_z"] = _zscore(-metrics_df["volume_stability"])
        metrics_df["logret_z"] = _zscore(metrics_df["log_return"])
        metrics_df["r2_z"] = _zscore(metrics_df["r2"])
        metrics_df["quality_score"] = metrics_df[
            [
                "sharpe_z",
                "mdd_z",
                "vol_z",
                "vol_stability_z",
                "volume_stability_z",
                "logret_z",
                "r2_z",
            ]
        ].mean(axis=1)
        metrics_df["signal"] = (
            g.score_weight_momentum * metrics_df["momentum_z"]
            + g.score_weight_quality * metrics_df["quality_score"]
        )
        if g.industry_penalty < 1:
            metrics_df.loc[metrics_df.index.isin(g.industry_etfs), "signal"] *= (
                g.industry_penalty
            )
        if g.trend_penalty < 1:
            metrics_df.loc[~metrics_df["trend_ok"], "signal"] *= g.trend_penalty

    metrics_df["premium"] = 0.0
    metrics_df["premium_ok"] = True
    if g.premium_filter_enabled:
        for etf in g.premium_etfs:
            if etf not in metrics_df.index:
                continue
            close = g.price_cache.get(etf)
            if close is None or close.empty:
                continue
            nav = _get_unit_nav(etf, prev_day)
            if nav is None or nav <= 0:
                continue
            premium = (close["close"].values[-1] - nav) / nav * 100
            metrics_df.at[etf, "premium"] = premium
            metrics_df.at[etf, "premium_ok"] = premium <= g.premium_threshold
        if g.premium_penalty < 1:
            metrics_df.loc[~metrics_df["premium_ok"], "signal"] *= g.premium_penalty

    g.factor_df = metrics_df

    _print_header(f"📊 因子计算完成 - {context.current_dt.strftime('%Y-%m-%d')}")
    _print_factor_table(metrics_df, top_n=len(g.etf_pool))
    _print_metrics_summary(metrics_df)


def rebalance(context):
    if g.factor_df is None or g.factor_df.empty:
        log.warn("no factor data")
        return

    factor_df = g.factor_df
    if g.use_rank_scoring:
        mask = (factor_df["momentum"] > g.momentum_floor) & (
            factor_df["quality_score"] >= g.quality_floor
        )
        if g.use_trend_filter and getattr(g, "trend_hard_filter", True):
            mask &= factor_df["trend_ok"]
        if (
            g.premium_filter_enabled
            and getattr(g, "premium_hard_filter", True)
            and "premium_ok" in factor_df.columns
        ):
            mask &= factor_df["premium_ok"]
        signal_series = factor_df.loc[mask, "signal"]
    else:
        signal_series = factor_df["signal"]
        signal_series = signal_series[signal_series > 0]

    if signal_series.empty:
        _print_header("⚠️ 无有效信号 - 清仓")
        log.info("🚫 所有ETF信号为负，执行清仓")
        _execute_orders(context, {})
        return

    candidates = _select_candidates(signal_series, factor_df)
    if not candidates:
        _print_header("⚠️ 无候选标的 - 清仓")
        log.info("🚫 约束条件过滤后无候选ETF，执行清仓")
        _execute_orders(context, {})
        return
    returns_df = _build_returns_df(candidates)
    if returns_df.empty or returns_df.shape[1] == 0:
        log.warn("no returns for EPO")
        return

    signals = g.factor_df.loc[returns_df.columns, "signal"].values
    if g.anchor_weight > 0:
        anchor_signal = _build_anchor_signal(returns_df.columns)
        signals = (1 - g.anchor_weight) * signals + g.anchor_weight * anchor_signal
    signals = np.clip(signals, 0, None)
    if g.signal_power != 1.0:
        signals = np.power(signals, g.signal_power)

    shrinkage = g.epo_shrinkage
    if g.use_dynamic_shrinkage:
        shrinkage = _dynamic_shrinkage(returns_df)
    weights = _epo_weights(
        returns_df,
        signals,
        g.epo_risk_aversion,
        shrinkage,
    )

    if g.use_risk_parity:
        weights = _apply_risk_parity(weights, returns_df)

    penalties = []
    for etf in returns_df.columns:
        ratio = g.factor_df.loc[etf, "volume_ratio"]
        penalty = 1.0
        if ratio > g.volume_ratio_threshold:
            penalty = ratio ** (-g.volume_penalty_power)
        penalties.append(penalty)

    penalties = np.array(penalties, dtype=float)
    if g.use_relative_crowding:
        ratios = g.factor_df.loc[returns_df.columns, "volume_ratio"]
        ratios = ratios.replace([np.inf, -np.inf], np.nan)
        median = np.nanmedian(ratios.values)
        if median and not np.isnan(median):
            rel = ratios.values / median
            rel = np.clip(rel, g.relative_crowding_floor, g.relative_crowding_ceiling)
            rel_penalty = np.power(rel, -g.relative_crowding_power)
            penalties = penalties * rel_penalty

    dd = g.factor_df.loc[returns_df.columns, "trend_dd"]
    dd = dd.replace([np.inf, -np.inf], np.nan)
    if g.dd_penalty_threshold and not dd.isna().all():
        ratio = dd.values / g.dd_penalty_threshold
        dd_penalty = np.ones_like(ratio, dtype=float)
        mask = ratio > 1
        dd_penalty[mask] = ratio[mask] ** (-g.dd_penalty_power)
        dd_penalty = np.clip(dd_penalty, g.dd_penalty_floor, 1.0)
        penalties = penalties * dd_penalty

    weights = _normalize(np.array(weights) * penalties)
    a_share_cap = g.a_share_weight_cap
    if g.use_dynamic_a_share_cap:
        a_share_cap = _dynamic_a_share_cap(returns_df.columns, factor_df)
    if a_share_cap is not None:
        weights = _apply_group_weight_cap(
            weights, list(returns_df.columns), g.a_share_etfs, a_share_cap
        )
    industry_cap = g.industry_weight_cap
    if g.use_dynamic_industry_cap:
        industry_cap = _dynamic_industry_cap(returns_df.columns, factor_df)
    if industry_cap is not None:
        weights = _apply_group_weight_cap(
            weights, list(returns_df.columns), g.industry_etfs, industry_cap
        )
    max_weight = g.max_weight
    if g.use_dynamic_max_weight:
        max_weight = _dynamic_max_weight(list(returns_df.columns), factor_df)
    if max_weight:
        weights = _apply_weight_cap(weights, max_weight)
    target_weights = dict(zip(returns_df.columns, weights))

    _print_header(f"🔄 调仓执行 - {context.current_dt.strftime('%Y-%m-%d')}")
    _print_weight_table(target_weights, factor_df, context.portfolio.total_value)

    current_positions = context.portfolio.positions
    changes = {}
    for etf in target_weights:
        if etf in current_positions:
            changes[etf] = "HOLD"
    for etf in current_positions:
        if etf not in target_weights:
            changes[etf] = "SELL"
    for etf in target_weights:
        if etf not in current_positions:
            changes[etf] = "BUY"

    _print_rebalance_summary(changes)

    _execute_orders(context, target_weights)


def _execute_orders(context, target_weights):
    current_data = get_current_data()
    total_value = context.portfolio.total_value
    target_weights = _adjust_weights_for_trading(
        target_weights, current_data, total_value
    )
    if not target_weights:
        return

    target_shares = {}
    for etf, weight in target_weights.items():
        price = current_data[etf].last_price
        if price is None or np.isnan(price) or price <= 0:
            continue
        target_value = total_value * weight
        shares = int(target_value / price // g.min_lot) * g.min_lot
        if shares < g.min_lot:
            shares = 0
        target_shares[etf] = shares

    for etf in list(context.portfolio.positions.keys()):
        if etf not in target_shares and not current_data[etf].paused:
            log.info(f"🔴 卖出 {_format_etf_code(etf)} ({_get_etf_name(etf)})")
            order_target(etf, 0)

    for etf, shares in target_shares.items():
        if current_data[etf].paused:
            continue
        current_pos = context.portfolio.positions.get(etf)
        current_shares = current_pos.total_amount if current_pos else 0
        if shares < current_shares:
            log.info(f"🔴 减仓 {_format_etf_code(etf)}: {current_shares} -> {shares}股")
            order_target(etf, shares)

    for etf, shares in target_shares.items():
        if current_data[etf].paused:
            continue
        current_pos = context.portfolio.positions.get(etf)
        current_shares = current_pos.total_amount if current_pos else 0
        if shares > current_shares:
            log.info(f"🟢 加仓 {_format_etf_code(etf)}: {current_shares} -> {shares}股")
            order_target(etf, shares)


def daily_summary(context):
    """每日收盘后打印持仓汇总"""
    positions = context.portfolio.positions
    _print_daily_summary(context, positions)


def _build_returns_df(etfs):
    series_list = []
    for etf in etfs:
        data = g.price_cache.get(etf)
        if data is None or data.empty:
            continue
        rets = data["close"].pct_change().dropna().tail(g.cov_window)
        if rets.empty:
            continue
        series_list.append(rets.rename(etf))
    if not series_list:
        return pd.DataFrame()
    return pd.concat(series_list, axis=1, join="inner").dropna()


def _epo_weights(returns_df, signals, risk_aversion, shrinkage):
    n = returns_df.shape[1]
    if returns_df.shape[0] < 2 or n == 0:
        return np.ones(n) / max(n, 1)

    cov = returns_df.cov().values
    diag = np.diag(np.diag(cov))
    shrunk = (1 - shrinkage) * cov + shrinkage * diag
    shrunk = shrunk + np.eye(n) * 1e-6

    try:
        inv_cov = np.linalg.inv(shrunk)
    except np.linalg.LinAlgError:
        inv_cov = np.linalg.pinv(shrunk)

    raw = inv_cov.dot(signals)
    if risk_aversion > 0:
        raw = raw / risk_aversion

    raw = np.maximum(0, raw)
    return _normalize(raw)


def _compute_metrics(close, volume, etf_code=None):
    """
    计算ETF的多维因子指标

    Args:
        close: 收盘价序列
        volume: 成交量序列
        etf_code: ETF代码，用于选择合适的基准
    """
    quality_prices = close[-g.quality_lookback :]
    momentum_prices = close[-g.momentum_lookback :]
    quality_volume = volume[-g.quality_lookback :]

    sharpe = _rolling_metric_on_prices(
        quality_prices,
        g.quality_window,
        lambda p: _calc_sharpe(np.diff(p) / p[:-1]),
    )
    max_dd = _rolling_metric_on_prices(
        quality_prices, g.quality_window, _calc_max_drawdown
    )
    volatility = _rolling_metric_on_prices(
        quality_prices,
        g.quality_window,
        lambda p: _calc_volatility(np.diff(p) / p[:-1]),
    )
    vol_stability = _rolling_metric_on_prices(
        quality_prices,
        g.quality_window,
        lambda p: _calc_vol_stability(np.diff(p) / p[:-1]),
    )
    log_return = _rolling_metric_on_prices(
        quality_prices, g.quality_window, _calc_log_return
    )
    r2_q = _rolling_metric_on_prices(
        quality_prices, g.quality_window, _calc_r2_log_prices
    )
    volume_stability = _rolling_metric_on_volume(
        quality_volume, g.quality_window, _calc_volume_stability
    )

    momentum, momentum_mode = _calc_adaptive_momentum_with_etf(close, etf_code)

    volume_ratio = _calc_volume_ratio(volume)
    trend_ok, trend_dd = _calc_trend_filter(close)

    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "volatility": volatility,
        "vol_stability": vol_stability,
        "volume_stability": volume_stability,
        "log_return": log_return,
        "r2": r2_q,
        "momentum": momentum,
        "momentum_mode": momentum_mode,
        "volume_ratio": volume_ratio,
        "trend_ok": trend_ok,
        "trend_dd": trend_dd,
    }


def _calc_sharpe(returns):
    if len(returns) < 2:
        return 0.0
    mean = np.mean(returns)
    std = np.std(returns)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _calc_max_drawdown(prices):
    if len(prices) < 2:
        return 0.0
    running_max = np.maximum.accumulate(prices)
    drawdowns = prices / running_max - 1
    return abs(np.min(drawdowns))


def _calc_vol_stability(returns):
    if len(returns) < 2:
        return 0.0
    vol_window = max(5, int(len(returns) / 5))
    if len(returns) < vol_window + 1:
        return np.std(returns)
    rolling_vol = pd.Series(returns).rolling(vol_window).std().dropna()
    if rolling_vol.empty:
        return np.std(returns)
    return np.std(rolling_vol.values)


def _calc_volatility(returns):
    if len(returns) < 2:
        return 0.0
    return np.std(returns) * math.sqrt(252)


def _calc_volume_stability(volumes):
    volumes = np.array(volumes, dtype=float)
    if len(volumes) < 2:
        return 0.0
    prev = volumes[:-1]
    prev[prev == 0] = np.nan
    volume_returns = (volumes[1:] - prev) / prev
    volume_returns = volume_returns[~np.isnan(volume_returns)]
    if len(volume_returns) == 0:
        return 0.0
    return np.std(volume_returns)


def _calc_r2(log_prices):
    if len(log_prices) < 2:
        return 0.0
    x = np.arange(len(log_prices))
    slope, intercept = np.polyfit(x, log_prices, 1)
    fitted = slope * x + intercept
    ss_res = np.sum((log_prices - fitted) ** 2)
    ss_tot = np.sum((log_prices - np.mean(log_prices)) ** 2)
    if ss_tot == 0:
        return 0.0
    return 1 - ss_res / ss_tot


def _calc_annualized_return(log_prices):
    if len(log_prices) < 2:
        return 0.0
    slope = np.polyfit(np.arange(len(log_prices)), log_prices, 1)[0]
    return math.exp(slope * 252) - 1


def _calc_volume_ratio(volume):
    if len(volume) < g.volume_long_window:
        return 1.0
    short_avg = np.mean(volume[-g.volume_short_window :])
    long_avg = np.mean(volume[-g.volume_long_window :])
    if long_avg <= 0:
        return 1.0
    return short_avg / long_avg


def _calc_trend_filter(close):
    if len(close) < g.trend_window:
        return True, 0.0
    window = close[-g.trend_window :]
    ma = float(np.mean(window))
    dd = _calc_max_drawdown(window)
    if ma <= 0:
        return False, dd
    return close[-1] >= ma and dd <= g.max_dd_filter, dd


def _calc_log_return(prices):
    if len(prices) < 2 or prices[0] <= 0:
        return 0.0
    return math.log(prices[-1] / prices[0])


def _calc_r2_log_prices(prices):
    prices = np.array(prices, dtype=float)
    if len(prices) < 2 or np.any(prices <= 0):
        return 0.0
    return _calc_r2(np.log(prices))


def _calc_momentum(prices):
    prices = np.array(prices, dtype=float)
    if len(prices) < 2 or np.any(prices <= 0):
        return 0.0
    log_prices = np.log(prices)
    return _calc_annualized_return(log_prices) * _calc_r2(log_prices)


def _calc_relative_momentum(prices, benchmark_prices):
    """计算相对动量：ETF相对于基准的超额收益趋势"""
    if len(prices) < 20 or len(benchmark_prices) < 20:
        return 0.0

    prices = np.array(prices)
    benchmark_prices = np.array(benchmark_prices)

    etf_ret = (prices[-1] / prices[0]) ** (252 / len(prices)) - 1
    bench_ret = (benchmark_prices[-1] / benchmark_prices[0]) ** (
        252 / len(benchmark_prices)
    ) - 1

    relative_ret = etf_ret - bench_ret

    etf_log = np.log(prices)
    bench_log = np.log(benchmark_prices)
    etf_r2 = _calc_r2(etf_log)
    bench_r2 = _calc_r2(bench_log)

    combined_r2 = (etf_r2 + bench_r2) / 2

    return relative_ret * combined_r2


def _calc_multi_period_momentum(
    close_prices, periods=None, weights=None, use_r2_factor=None
):
    """
    计算多周期加权动量（可配置版本）

    参数说明：
    ---------
    close_prices : array-like
        价格序列
    periods : list, optional
        回看周期列表，默认使用 g.momentum_periods
    weights : list, optional
        各周期权重，默认使用 g.momentum_weights
    use_r2_factor : bool, optional
        是否使用R²因子，默认使用 g.momentum_use_r2_factor

    权重配置建议：
    ------------
    g.momentum_periods = [20, 40, 60]  # 短/中/长三周期
    g.momentum_weights = [0.5, 0.3, 0.2]  # 短期权重更高

    优势：
    -----
    1. 多周期平滑，避免单周期噪音
    2. 短期权重高，响应较快
    3. R²因子确保趋势稳定性

    使用方法：
    --------
    # 使用配置文件设置（推荐）
    momentum = _calc_multi_period_momentum(close_prices)

    # 自定义参数
    momentum = _calc_multi_period_momentum(
        close_prices,
        periods=[15, 30, 45],
        weights=[0.6, 0.3, 0.1],
        use_r2_factor=True
    )
    """
    if periods is None:
        periods = getattr(g, "momentum_periods", [20, 40, 60])
    if weights is None:
        weights = getattr(g, "momentum_weights", [0.5, 0.3, 0.2])
    if use_r2_factor is None:
        use_r2_factor = getattr(g, "momentum_use_r2_factor", True)

    prices = np.array(close_prices, dtype=float)
    if len(prices) < 2 or np.any(prices <= 0):
        return 0.0

    total_weight = 0.0
    weighted_momentum = 0.0

    for period, weight in zip(periods, weights):
        if len(prices) >= period:
            period_prices = prices[-period:]
            log_prices = np.log(period_prices)

            ret = (prices[-1] / prices[-period]) ** (252 / period) - 1

            if use_r2_factor:
                r2 = _calc_r2(log_prices)
                weighted_momentum += ret * r2 * weight
            else:
                weighted_momentum += ret * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0

    return weighted_momentum / total_weight


def _calc_adaptive_momentum_with_etf(close_prices, etf_code=None):
    """
    动量计算主入口（支持多周期 + 自适应模式配置）

    参数配置说明：
    -------------

    关闭相对动量（推荐配置）:
        g.use_multi_period_momentum = True   # 启用多周期动量
        g.use_adaptive_momentum = False       # 关闭自适应模式
        g.force_absolute_momentum = True      # 强制使用绝对动量
        g.enable_relative_momentum = False     # 完全禁用相对动量

    启用相对动量（不推荐）:
        g.use_multi_period_momentum = True
        g.use_adaptive_momentum = True
        g.enable_relative_momentum = True

    使用原版单周期动量:
        g.use_multi_period_momentum = False
        g.force_absolute_momentum = False

    动量模式返回值：
    --------------
    (momentum_value, mode_name)
    mode_name: "absolute" | "relative" | "hybrid" | "original"

    Returns:
        tuple: (动量值, 动量模式)
    """
    # 获取配置参数
    use_multi_period = getattr(g, "use_multi_period_momentum", True)
    use_adaptive = getattr(g, "use_adaptive_momentum", False)
    force_absolute = getattr(g, "force_absolute_momentum", True)
    enable_relative = getattr(g, "enable_relative_momentum", False)

    # 模式1: 强制绝对动量（关闭相对动量）
    if force_absolute:
        if use_multi_period:
            momentum = _calc_multi_period_momentum(close_prices)
            return momentum, "absolute"
        else:
            momentum = _calc_momentum(close_prices)
            return momentum, "original"

    # 模式2: 使用自适应动量（根据市场环境切换）
    if use_adaptive and enable_relative:
        return _calc_adaptive_momentum_internal(close_prices, etf_code)

    # 模式3: 使用原版单周期动量
    momentum = _calc_momentum(close_prices)
    return momentum, "original"


def _calc_adaptive_momentum_internal(close_prices, etf_code=None):
    """
    内部函数：自适应动量计算（根据市场环境切换绝对/相对动量）

    说明：
    -----
    此函数仅在 g.use_adaptive_momentum=True 且 g.enable_relative_momentum=True 时调用

    市场环境判断（基于20日涨幅）：
    - 强劲牛市 (>8%): 100%绝对动量
    - 牛市 (>3%): 70%绝对 + 30%相对
    - 熊市 (<-5%): 40%绝对 + 60%相对
    - 中性: 100%绝对动量
    """
    benchmark_prices = None
    if etf_code == "518880.XSHG":
        benchmark_prices = None
    elif etf_code == "513100.XSHG":
        try:
            benchmark_data = get_price(
                "HSI",
                count=120,
                end_date=context.previous_date
                if hasattr(context, "previous_date")
                else None,
                frequency="daily",
                fields=["close"],
            )
            if benchmark_data is not None and not benchmark_data.empty:
                benchmark_prices = benchmark_data["close"].values
        except:
            benchmark_prices = None
    else:
        try:
            benchmark_data = get_price(
                g.benchmark_etf,
                count=120,
                end_date=context.previous_date
                if hasattr(context, "previous_date")
                else None,
                frequency="daily",
                fields=["close"],
            )
            if benchmark_data is not None and not benchmark_data.empty:
                benchmark_prices = benchmark_data["close"].values
        except:
            benchmark_prices = None

    abs_momentum = _calc_multi_period_momentum(close_prices)

    if benchmark_prices is not None and len(benchmark_prices) >= 60:
        rel_momentum = _calc_relative_momentum(
            close_prices,
            benchmark_prices[-len(close_prices) :]
            if len(benchmark_prices) > len(close_prices)
            else benchmark_prices,
        )
    else:
        rel_momentum = 0

    market_regime = _detect_market_regime_v2(
        close_prices, benchmark_prices if benchmark_prices is not None else np.ones(120)
    )

    mix_weights = getattr(g, "momentum_mix_weights", [0.7, 0.3])

    if market_regime == "strong_bull":
        return abs_momentum, "absolute"
    elif market_regime == "bull":
        return mix_weights[0] * abs_momentum + mix_weights[1] * rel_momentum, "hybrid"
    elif market_regime == "bear":
        return (1 - mix_weights[1]) * abs_momentum + mix_weights[
            1
        ] * rel_momentum, "relative"
    else:
        return abs_momentum, "absolute"


def _calc_adaptive_momentum(close_prices, benchmark_prices=None):
    """兼容旧版本接口"""
    return _calc_adaptive_momentum_with_etf(close_prices, None)


def _detect_market_regime_v2(prices, benchmark_prices):
    """
    优化版市场环境检测（缩短检测周期）

    Returns:
        "strong_bull": 强劲牛市 - 纯绝对动量
        "bull": 牛市 - 混合
        "neutral": 中性 - 纯绝对动量
        "bear": 熊市 - 相对动量
    """
    prices = np.array(prices)

    if len(prices) < 20:
        return "neutral"

    ret_20d = prices[-1] / prices[-20] - 1

    if ret_20d > 0.08:
        return "strong_bull"
    elif ret_20d > 0.03:
        return "bull"
    elif ret_20d < -0.05:
        return "bear"
    else:
        return "neutral"


def _detect_market_regime(prices, benchmark_prices):
    """兼容旧版本"""
    return _detect_market_regime_v2(prices, benchmark_prices)

    etf_60d = prices[-1] / prices[-60] - 1
    bench_60d = benchmark_prices[-1] / benchmark_prices[-60] - 1

    if etf_60d > 0.05 and bench_60d > 0.03:
        return "bull"
    elif etf_60d < -0.05 or bench_60d < -0.03:
        return "bear"
    else:
        return "neutral"


def _calc_volume_ratio(volume):
    if len(volume) < g.volume_long_window:
        return 1.0
    short_avg = np.mean(volume[-g.volume_short_window :])
    long_avg = np.mean(volume[-g.volume_long_window :])
    if long_avg <= 0:
        return 1.0
    return short_avg / long_avg


def _rolling_metric_on_prices(prices, window, func):
    prices = np.array(prices, dtype=float)
    if len(prices) < 2:
        return 0.0
    if len(prices) < window:
        return func(prices)
    if not g.use_window_mean:
        return func(prices[-window:])
    values = []
    for i in range(window, len(prices) + 1):
        values.append(func(prices[i - window : i]))
    return float(np.mean(values)) if values else func(prices)


def _rolling_metric_on_volume(volumes, window, func):
    volumes = np.array(volumes, dtype=float)
    if len(volumes) < 2:
        return 0.0
    if len(volumes) < window:
        return func(volumes)
    if not g.use_window_mean:
        return func(volumes[-window:])
    values = []
    for i in range(window, len(volumes) + 1):
        values.append(func(volumes[i - window : i]))
    return float(np.mean(values)) if values else func(volumes)


def _normalize(values):
    total = np.sum(values)
    if total <= 0:
        return np.ones(len(values)) / max(len(values), 1)
    return values / total


def _apply_risk_parity(weights, returns_df):
    vols = returns_df.std() * math.sqrt(252)
    vols = vols.replace([np.inf, -np.inf], np.nan)
    if vols.isna().all():
        return weights
    vols = vols.fillna(vols.median())
    inv_vol = 1.0 / (vols.values + 1e-10)
    scaled = np.array(weights) * inv_vol
    return _normalize(scaled)


def _apply_weight_cap(weights, cap):
    weights = np.array(weights, dtype=float)
    if cap <= 0 or len(weights) == 0:
        return weights
    weights = _normalize(weights)
    n = len(weights)
    if cap * n < 1 - 1e-8:
        return weights

    capped = np.zeros_like(weights)
    remaining = 1.0
    active = np.ones(n, dtype=bool)
    base = weights.copy()
    for _ in range(n):
        if not active.any():
            break
        total = base[active].sum()
        if total <= 0:
            capped[active] = remaining / active.sum()
            remaining = 0.0
            break
        alloc = base[active] / total * remaining
        over = alloc > cap
        if not over.any():
            capped[active] = alloc
            remaining = 0.0
            break
        idx = np.where(active)[0]
        over_idx = idx[over]
        capped[over_idx] = cap
        remaining -= cap * len(over_idx)
        active[over_idx] = False
    if remaining > 1e-8 and active.any():
        capped[active] += remaining / active.sum()
    return capped


def _apply_group_weight_cap(weights, assets, group_set, cap):
    weights = np.array(weights, dtype=float)
    if cap is None or cap <= 0:
        return weights
    assets = list(assets)
    group_idx = [i for i, a in enumerate(assets) if a in group_set]
    if not group_idx:
        return weights
    group_weight = weights[group_idx].sum()
    if group_weight <= cap:
        return weights
    non_idx = [i for i in range(len(weights)) if i not in group_idx]
    if not non_idx:
        return weights
    scale = cap / max(group_weight, 1e-10)
    weights[group_idx] *= scale
    remaining = 1.0 - weights[group_idx].sum()
    non_weight = weights[non_idx].sum()
    if non_weight > 0:
        weights[non_idx] = weights[non_idx] / non_weight * remaining
    return weights


def _dynamic_a_share_cap(assets, factor_df):
    if not getattr(g, "use_dynamic_a_share_cap", False):
        return g.a_share_weight_cap
    if factor_df is None or factor_df.empty:
        return g.a_share_weight_cap
    a_assets = [a for a in assets if a in g.a_share_etfs]
    if not a_assets:
        return g.a_share_weight_cap
    dd = factor_df.loc[a_assets, "trend_dd"]
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna()
    if dd.empty:
        return g.a_share_weight_cap
    dd_metric = float(np.nanpercentile(dd.values, 75))
    threshold = getattr(g, "a_share_dd_threshold", None)
    low = getattr(g, "a_share_weight_cap_low", g.a_share_weight_cap)
    high = getattr(g, "a_share_weight_cap_high", g.a_share_weight_cap)
    if threshold is None:
        return g.a_share_weight_cap
    if dd_metric >= threshold:
        return low
    return high


def _dynamic_industry_cap(assets, factor_df):
    if not getattr(g, "use_dynamic_industry_cap", False):
        return g.industry_weight_cap
    if factor_df is None or factor_df.empty:
        return g.industry_weight_cap
    i_assets = [a for a in assets if a in g.industry_etfs]
    if not i_assets:
        return g.industry_weight_cap
    dd = factor_df.loc[i_assets, "trend_dd"]
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna()
    if dd.empty:
        return g.industry_weight_cap
    dd_metric = float(np.nanpercentile(dd.values, 75))
    threshold = getattr(g, "industry_dd_threshold", None)
    low = getattr(g, "industry_weight_cap_low", g.industry_weight_cap)
    high = getattr(g, "industry_weight_cap_high", g.industry_weight_cap)
    if threshold is None:
        return g.industry_weight_cap
    if dd_metric >= threshold:
        return low
    return high


def _dynamic_max_weight(assets, factor_df):
    if not getattr(g, "use_dynamic_max_weight", False):
        return g.max_weight
    if factor_df is None or factor_df.empty:
        return g.max_weight
    assets = list(assets)
    dd = factor_df.loc[assets, "trend_dd"]
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna()
    if dd.empty:
        return g.max_weight
    dd_metric = float(np.nanpercentile(dd.values, 75))
    threshold = getattr(g, "max_weight_dd_threshold", None)
    low = getattr(g, "max_weight_low", g.max_weight)
    high = getattr(g, "max_weight_high", g.max_weight)
    if threshold is None:
        return g.max_weight
    if dd_metric >= threshold:
        return low
    return high


def _select_candidates(signal_series, factor_df):
    if signal_series.empty:
        return []
    min_holdings = g.min_holdings
    if g.use_dynamic_min_holdings and factor_df is not None and not factor_df.empty:
        dd = factor_df.loc[signal_series.index, "trend_dd"]
        dd = dd.replace([np.inf, -np.inf], np.nan).dropna()
        if not dd.empty:
            dd_metric = float(np.nanpercentile(dd.values, 75))
            if dd_metric >= g.min_holdings_dd_threshold:
                min_holdings = g.min_holdings_risk
    signal_series = signal_series.sort_values(ascending=False)
    selected = []
    a_share_count = 0
    industry_count = 0
    max_industry = getattr(g, "max_industry_holdings", None)

    for etf in signal_series.index:
        if g.avoid_industry and etf in g.industry_etfs:
            continue
        if max_industry is not None and etf in g.industry_etfs:
            if industry_count >= max_industry:
                continue
            industry_count += 1
        if etf in g.a_share_etfs:
            if a_share_count >= g.max_a_share_holdings:
                continue
            a_share_count += 1
        selected.append(etf)
        if g.max_holdings and len(selected) >= g.max_holdings:
            break

    if min_holdings and len(selected) < min_holdings:
        fallback = factor_df["signal"].sort_values(ascending=False)
        for etf in fallback.index:
            if etf in selected:
                continue
            if g.avoid_industry and etf in g.industry_etfs:
                continue
            if max_industry is not None and etf in g.industry_etfs:
                if industry_count >= max_industry:
                    continue
                industry_count += 1
            if etf in g.a_share_etfs and a_share_count >= g.max_a_share_holdings:
                continue
            if etf in g.a_share_etfs:
                a_share_count += 1
            selected.append(etf)
            if len(selected) >= min_holdings:
                break

    return selected


def _adjust_weights_for_trading(target_weights, current_data, total_value):
    if not target_weights:
        return {}
    assets = []
    weights = []
    for etf, weight in target_weights.items():
        price = current_data[etf].last_price
        if price is None or np.isnan(price) or price <= 0:
            continue
        if total_value * weight < g.min_lot * price:
            continue
        assets.append(etf)
        weights.append(weight)
    if not assets:
        return {}
    weights = _normalize(np.array(weights))
    a_share_cap = g.a_share_weight_cap
    if g.use_dynamic_a_share_cap and g.factor_df is not None:
        a_share_cap = _dynamic_a_share_cap(assets, g.factor_df)
    if a_share_cap is not None:
        weights = _apply_group_weight_cap(weights, assets, g.a_share_etfs, a_share_cap)
    industry_cap = g.industry_weight_cap
    if g.use_dynamic_industry_cap and g.factor_df is not None:
        industry_cap = _dynamic_industry_cap(assets, g.factor_df)
    if industry_cap is not None:
        weights = _apply_group_weight_cap(
            weights, assets, g.industry_etfs, industry_cap
        )
    max_weight = g.max_weight
    if g.use_dynamic_max_weight and g.factor_df is not None:
        max_weight = _dynamic_max_weight(list(assets), g.factor_df)
    if max_weight:
        weights = _apply_weight_cap(weights, max_weight)
    return dict(zip(assets, weights))


def _zscore(series):
    std = series.std()
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _rank_score(series, higher_is_better=True):
    if series.empty:
        return pd.Series(0.0, index=series.index)
    rank = series.rank(pct=True, ascending=True)
    if higher_is_better:
        return rank
    return 1 - rank


def _previous_trade_day(context):
    trade_days = get_trade_days(end_date=context.current_dt, count=2)
    if len(trade_days) < 2:
        return None
    return trade_days[-2]


def _get_unit_nav(etf, ref_date):
    try:
        nav = get_extras("unit_net_value", etf, end_date=ref_date, count=1)
        if nav is None or nav.empty:
            nav = get_extras(
                "unit_net_value", etf, start_date=ref_date, end_date=ref_date
            )
        if nav is None or nav.empty:
            return None
        if etf in nav.columns:
            value = nav[etf].iloc[-1]
        else:
            value = nav.iloc[-1, 0]
        if value is None or np.isnan(value):
            return None
        return float(value)
    except Exception:
        return None


def _dynamic_shrinkage(returns_df):
    vols = returns_df.std() * math.sqrt(252)
    vols = vols.replace([np.inf, -np.inf], np.nan).dropna()
    if vols.empty:
        return g.epo_shrinkage
    avg_vol = vols.mean()
    if avg_vol <= 0 or np.isnan(avg_vol):
        return g.epo_shrinkage
    shrink = 1.0 - 0.1 / max(avg_vol, 1e-6)
    return float(np.clip(shrink, g.shrinkage_floor, g.shrinkage_cap))


def _build_anchor_signal(etfs):
    vol_forecasts = []
    for etf in etfs:
        data = g.price_cache.get(etf)
        if data is None or data.empty:
            vol_forecasts.append(np.nan)
            continue
        rets = data["close"].pct_change().dropna().tail(g.garch_window).values
        vol_forecasts.append(_forecast_volatility(rets))

    series = pd.Series(vol_forecasts, index=etfs)
    series = series.replace([np.inf, -np.inf], np.nan)
    if series.isna().all():
        return np.zeros(len(etfs))
    series = series.fillna(series.median())
    return _zscore(-series).values


def _forecast_volatility(returns):
    returns = np.array(returns, dtype=float)
    if len(returns) < 10:
        return np.std(returns) * math.sqrt(252) if len(returns) > 1 else 0.0

    if _ARCH_AVAILABLE:
        try:
            model = arch_model(returns * 100, mean="Constant", vol="GARCH", p=1, q=1)
            res = model.fit(disp="off")
            forecast = res.forecast(horizon=1, reindex=False)
            var = float(forecast.variance.values[-1, 0])
            return math.sqrt(max(var, 0.0)) / 100 * math.sqrt(252)
        except Exception:
            pass

    return _ewma_volatility(returns)


def _ewma_volatility(returns, lam=0.94):
    if len(returns) < 2:
        return 0.0
    var = returns[0] ** 2
    for r in returns[1:]:
        var = lam * var + (1 - lam) * (r**2)
    return math.sqrt(max(var, 0.0)) * math.sqrt(252)


def handle_data(context, data):
    pass
