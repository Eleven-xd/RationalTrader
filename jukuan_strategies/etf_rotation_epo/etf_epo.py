# 克隆自聚宽文章：https://www.joinquant.com/post/66279
# 标题：年化31%+、最大回撤12.6%-复现一个ETF-EPO策略
# 作者：estivation

# 动量 + 质量因子 -> EPO 权重（动态收缩 + GARCH 锚定）
# -> 成交拥挤度约束 + 滑动窗口指标
from jqdata import *
import numpy as np
import pandas as pd
import math
try:
    from arch import arch_model
    _ARCH_AVAILABLE = True
except Exception:
    arch_model = None
    _ARCH_AVAILABLE = False


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

    # ETF 池来自实盘日志的推断。
    g.etf_pool = [
        "518880.XSHG",
        "159915.XSHE",
        "513100.XSHG",
        "513600.XSHG",
        "159980.XSHE",
        "159930.XSHE",
        "159985.XSHE",
    ]

    # 窗口参数
    g.momentum_window = 25
    g.momentum_lookback = 25
    g.quality_window = 25
    g.quality_lookback = 25
    g.cov_window = 60
    g.garch_window = 120
    g.volume_short_window = 5
    g.volume_long_window = 20

    # 因子混合参数
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
        "159915.XSHE",  # 创业板
        "159930.XSHE",  # 能源（行业）
        "159980.XSHE",  # 有色（行业）
    }
    g.industry_etfs = {
        "159930.XSHE",
        "159980.XSHE",
    }

    # EPO 参数
    g.epo_risk_aversion = 8.0
    g.epo_shrinkage = 0.2
    g.use_dynamic_shrinkage = True
    g.shrinkage_floor = 0.05
    g.shrinkage_cap = 0.6

    # 成交拥挤度惩罚
    g.volume_ratio_threshold = 1.6
    g.volume_penalty_power = 0.8
    g.use_relative_crowding = True
    g.relative_crowding_power = 1.0
    g.relative_crowding_floor = 0.6
    g.relative_crowding_ceiling = 1.6
    g.dd_penalty_threshold = 0.05
    g.dd_penalty_power = 1.0
    g.dd_penalty_floor = 0.6

    # 每周调仓（周三）
    g.rebalance_weekday = 3
    g.factor_time = "11:00"
    g.rebalance_time = "11:15"

    g.price_cache = {}
    g.factor_df = None

    run_weekly(calc_factors, weekday=g.rebalance_weekday, time=g.factor_time)
    run_weekly(rebalance, weekday=g.rebalance_weekday, time=g.rebalance_time)


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
        metrics[etf] = _compute_metrics(close, turnover)

    metrics_df = pd.DataFrame(metrics).T
    if metrics_df.empty:
        log.warn("empty metrics")
        return

    if g.use_rank_scoring:
        metrics_df["momentum_score"] = _rank_score(metrics_df["momentum"], True)
        metrics_df["sharpe_score"] = _rank_score(metrics_df["sharpe"], True)
        metrics_df["mdd_score"] = _rank_score(metrics_df["max_drawdown"], False)
        metrics_df["vol_score"] = _rank_score(metrics_df["volatility"], False)
        metrics_df["vol_stability_score"] = _rank_score(metrics_df["vol_stability"], False)
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
            metrics_df.loc[
                metrics_df.index.isin(g.industry_etfs), "signal"
            ] *= g.industry_penalty
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
            metrics_df.loc[
                metrics_df.index.isin(g.industry_etfs), "signal"
            ] *= g.industry_penalty
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
    log.info(
        "signal top: {}".format(
            metrics_df["signal"].sort_values(ascending=False).head(5).to_dict()
        )
    )


def rebalance(context):
    if g.factor_df is None or g.factor_df.empty:
        log.warn("no factor data")
        return

    factor_df = g.factor_df
    if g.use_rank_scoring:
        mask = (
            (factor_df["momentum"] > g.momentum_floor)
            & (factor_df["quality_score"] >= g.quality_floor)
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
        log.warn("no positive signals, clear positions")
        _execute_orders(context, {})
        return

    candidates = _select_candidates(signal_series, factor_df)
    if not candidates:
        log.warn("no candidates after constraints, clear positions")
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

    # 成交拥挤度惩罚（短期成交激增时降权）。
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
    log.info("target weights: {}".format({k: round(v, 4) for k, v in target_weights.items()}))

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

    # 卖出不在目标列表中的持仓。
    for etf in list(context.portfolio.positions.keys()):
        if etf not in target_shares and not current_data[etf].paused:
            order_target(etf, 0)

    # 先减仓释放资金。
    for etf, shares in target_shares.items():
        if current_data[etf].paused:
            continue
        current_pos = context.portfolio.positions.get(etf)
        current_shares = current_pos.total_amount if current_pos else 0
        if shares < current_shares:
            order_target(etf, shares)

    # 卖出后再加仓。
    for etf, shares in target_shares.items():
        if current_data[etf].paused:
            continue
        current_pos = context.portfolio.positions.get(etf)
        current_shares = current_pos.total_amount if current_pos else 0
        if shares > current_shares:
            order_target(etf, shares)


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

    # 仅做多约束。
    raw = np.maximum(0, raw)
    return _normalize(raw)


def _compute_metrics(close, volume):
    quality_prices = close[-g.quality_lookback:]
    momentum_prices = close[-g.momentum_lookback:]
    quality_volume = volume[-g.quality_lookback:]

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

    momentum = _rolling_metric_on_prices(
        momentum_prices, g.momentum_window, _calc_momentum
    )

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
    short_avg = np.mean(volume[-g.volume_short_window:])
    long_avg = np.mean(volume[-g.volume_long_window:])
    if long_avg <= 0:
        return 1.0
    return short_avg / long_avg


def _calc_trend_filter(close):
    if len(close) < g.trend_window:
        return True, 0.0
    window = close[-g.trend_window:]
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
        weights = _apply_group_weight_cap(
            weights, assets, g.a_share_etfs, a_share_cap
        )
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
            nav = get_extras("unit_net_value", etf, start_date=ref_date, end_date=ref_date)
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
        var = lam * var + (1 - lam) * (r ** 2)
    return math.sqrt(max(var, 0.0)) * math.sqrt(252)


def handle_data(context, data):
    pass
