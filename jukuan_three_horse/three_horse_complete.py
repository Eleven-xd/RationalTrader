# -*- coding: utf-8 -*-
"""
三驾马车多策略组合量化交易系统（完整整合版）

包含：
1. 原始策略功能
2. ATR动态止损模块
3. 市场情绪择时模块
4. 技术指标筛选
"""

from typing import Any
from jqdata import *
from jqfactor import get_factor_values
from jqlib.technical_analysis import *
import pandas as pd
import numpy as np
import datetime as dt
import datetime
import math
from scipy.optimize import minimize
from prettytable import PrettyTable
import prettytable


# ==============================
# ATR动态止损服务模块
# ==============================


class ATRService:
    """ATR动态止损服务类"""

    def __init__(self, atr_period=14, atr_multiplier=2.0):
        """
        初始化ATR服务

        参数:
            atr_period: ATR周期（默认14天）
            atr_multiplier: ATR倍数（默认2.0）
        """
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

        # ATR缓存（性能优化）
        self.atr_cache = {}
        self.atr_cache_date = None

        # 持仓最高价缓存
        self.highest_price_cache = {}

    def calculate_atr(self, security, period=None):
        """
        计算ATR指标

        参数:
            security: 股票代码
            period: ATR周期（默认使用初始化设置的周期）

        返回:
            ATR值，失败返回None
        """
        if period is None:
            period = self.atr_period

        try:
            # 检查缓存
            cache_key = f"{security}_{period}"
            current_date = datetime.datetime.now().date()

            if self.atr_cache_date == current_date and cache_key in self.atr_cache:
                return self.atr_cache[cache_key]

            # 获取历史数据
            hist_data = attribute_history(
                security,
                period + 1,
                '1d',
                ['close', 'high', 'low'],
                skip_paused=True,
                df=True,
                fq='pre'
            )

            if hist_data is None or hist_data.empty or len(hist_data) < period:
                return None

            # 计算TR（真实波幅）
            high = hist_data['high'].values
            low = hist_data['low'].values
            close = hist_data['close'].values

            # 使用向量化计算TR
            tr1 = high[1:] - low[1:]  # 当日最高 - 当日最低
            tr2 = np.abs(high[1:] - close[:-1])  # |当日最高 - 前收盘|
            tr3 = np.abs(low[1:] - close[:-1])  # |当日最低 - 前收盘|

            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr = np.mean(tr)

            # 更新缓存
            self.atr_cache[cache_key] = atr
            self.atr_cache_date = current_date

            return atr

        except Exception as e:
            print(f"[ATRService] 计算{security} ATR失败: {e}")
            return None

    def check_stoploss(
        self,
        security,
        current_price,
        avg_cost,
        atr_multiplier=None,
        profit_levels=None,
        stoploss_adjustments=None,
        order_func=None
    ):
        """
        ATR动态止损检查

        参数:
            security: 股票代码
            current_price: 当前价格
            avg_cost: 持仓成本
            atr_multiplier: ATR倍数（默认使用初始化设置的倍数）
            profit_levels: 盈利保护点列表（如[0.20, 0.50, 1.00]）
            stoploss_adjustments: 止损调整列表（如[0.00, 0.20, 0.50]）
            order_func: 下单函数（执行止损时调用）

        返回:
            (should_stop, stoploss_price, reason)
            should_stop: 是否触发止损
            stoploss_price: 止损价格
            reason: 止损原因
        """
        if atr_multiplier is None:
            atr_multiplier = self.atr_multiplier

        if profit_levels is None:
            profit_levels = [0.20, 0.50, 1.00]

        if stoploss_adjustments is None:
            stoploss_adjustments = [0.00, 0.20, 0.50]

        try:
            # 计算当前盈亏
            current_return = (current_price - avg_cost) / avg_cost

            # 计算ATR
            atr = self.calculate_atr(security, self.atr_period)
            if atr is None:
                return False, None, "ATR计算失败"

            # 根据盈亏状态选择止损方式
            if current_return <= 0:
                # 亏损状态：使用固定止损（7%）
                stoploss_price = avg_cost * (1 - 0.07)
                reason = "固定止损（亏损状态）"

                if current_price < stoploss_price:
                    # 执行止损
                    if order_func is not None:
                        order_func(security, 0)
                    # 🔧 清除持仓最高价缓存
                    cache_key = f"{security}"
                    if cache_key in self.highest_price_cache:
                        del self.highest_price_cache[cache_key]
                    return True, stoploss_price, reason
            else:
                # 盈利状态：使用ATR跟踪止损

                # 🔧 修复：使用持仓期间最高价（不是历史最高价）
                # 初始化/更新持仓最高价
                cache_key = f"{security}"
                if cache_key not in self.highest_price_cache:
                    # 新持仓：初始化为成本价或前收盘价（取较大值）
                    hist_data_short = attribute_history(
                        security,
                        1,
                        '1d',
                        ['close', 'high'],
                        skip_paused=True,
                        df=True,
                        fq='pre'
                    )
                    if hist_data_short is not None and not hist_data_short.empty:
                        prev_close = hist_data_short['close'].iloc[-1]
                        self.highest_price_cache[cache_key] = max(avg_cost, prev_close)
                    else:
                        self.highest_price_cache[cache_key] = avg_cost
                else:
                    # 更新持仓最高价：取当前最高价和缓存最高价的较大值
                    hist_data_short = attribute_history(
                        security,
                        1,
                        '1d',
                        ['high'],
                        skip_paused=True,
                        df=True,
                        fq='pre'
                    )
                    if hist_data_short is not None and not hist_data_short.empty:
                        current_high = hist_data_short['high'].iloc[-1]
                        self.highest_price_cache[cache_key] = max(
                            self.highest_price_cache[cache_key],
                            current_high
                        )

                highest_price = self.highest_price_cache[cache_key]
                stoploss_price = highest_price - atr * atr_multiplier

                # 多级盈利保护
                for i, profit_level in enumerate(profit_levels):
                    if current_return >= profit_level:
                        # 调整止损线到更高水平
                        adjusted_stoploss = avg_cost * (1 + stoploss_adjustments[i])
                        stoploss_price = max(stoploss_price, adjusted_stoploss)
                        reason = f"盈利保护（达到{profit_level*100:.0f}%）"
                        break
                else:
                    reason = "ATR跟踪止损"

                # 检查止损
                if current_price < stoploss_price:
                    # 执行止损
                    if order_func is not None:
                        order_func(security, 0)
                    # 🔧 清除持仓最高价缓存
                    cache_key = f"{security}"
                    if cache_key in self.highest_price_cache:
                        del self.highest_price_cache[cache_key]
                    return True, stoploss_price, reason

            return False, None, "未触发止损"

        except Exception as e:
            print(f"[ATRService] 止损检查失败 {security}: {e}")
            return False, None, f"检查失败: {e}"

    def get_stoploss_price(
        self,
        security,
        current_price,
        avg_cost,
        atr_multiplier=None,
        profit_levels=None,
        stoploss_adjustments=None
    ):
        """
        获取当前止损价格（不执行止损）

        参数:
            security: 股票代码
            current_price: 当前价格
            avg_cost: 持仓成本
            atr_multiplier: ATR倍数（默认使用初始化设置的倍数）
            profit_levels: 盈利保护点列表
            stoploss_adjustments: 止损调整列表

        返回:
            stoploss_price: 止损价格，失败返回None
        """
        if atr_multiplier is None:
            atr_multiplier = self.atr_multiplier

        if profit_levels is None:
            profit_levels = [0.20, 0.50, 1.00]

        if stoploss_adjustments is None:
            stoploss_adjustments = [0.00, 0.20, 0.50]

        try:
            # 计算当前盈亏
            current_return = (current_price - avg_cost) / avg_cost

            # 计算ATR
            atr = self.calculate_atr(security, self.atr_period)
            if atr is None:
                return None

            # 根据盈亏状态选择止损方式
            if current_return <= 0:
                # 亏损状态：使用固定止损（7%）
                stoploss_price = avg_cost * (1 - 0.07)
            else:
                # 盈利状态：使用ATR跟踪止损

                # 🔧 修复：使用持仓期间最高价（不是历史最高价）
                # 初始化/更新持仓最高价
                cache_key = f"{security}"
                if cache_key not in self.highest_price_cache:
                    # 新持仓：初始化为成本价或前收盘价（取较大值）
                    hist_data_short = attribute_history(
                        security,
                        1,
                        '1d',
                        ['close', 'high'],
                        skip_paused=True,
                        df=True,
                        fq='pre'
                    )
                    if hist_data_short is not None and not hist_data_short.empty:
                        prev_close = hist_data_short['close'].iloc[-1]
                        self.highest_price_cache[cache_key] = max(avg_cost, prev_close)
                    else:
                        self.highest_price_cache[cache_key] = avg_cost
                else:
                    # 更新持仓最高价：取当前最高价和缓存最高价的较大值
                    hist_data_short = attribute_history(
                        security,
                        1,
                        '1d',
                        ['high'],
                        skip_paused=True,
                        df=True,
                        fq='pre'
                    )
                    if hist_data_short is not None and not hist_data_short.empty:
                        current_high = hist_data_short['high'].iloc[-1]
                        self.highest_price_cache[cache_key] = max(
                            self.highest_price_cache[cache_key],
                            current_high
                        )

                highest_price = self.highest_price_cache[cache_key]
                stoploss_price = highest_price - atr * atr_multiplier

                # 多级盈利保护
                for i, profit_level in enumerate(profit_levels):
                    if current_return >= profit_level:
                        # 调整止损线到更高水平
                        adjusted_stoploss = avg_cost * (1 + stoploss_adjustments[i])
                        stoploss_price = max(stoploss_price, adjusted_stoploss)
                        break

            return stoploss_price

        except Exception as e:
            print(f"[ATRService] 获取止损价格失败 {security}: {e}")
            return None

    def clear_cache(self):
        """清除缓存"""
        self.atr_cache = {}
        self.atr_cache_date = None
        self.highest_price_cache = {}

    def clear_security_cache(self, security):
        """
        清除指定证券的持仓最高价缓存

        Args:
            security: 股票代码
        """
        cache_key = f"{security}"
        if cache_key in self.highest_price_cache:
            del self.highest_price_cache[cache_key]


class ATRConfig:
    """ATR配置类"""

    # 小市值策略配置
    SMALLCAP = {
        'atr_period': 14,
        'atr_multiplier': 2.0,  # 🔥 从2.0提高到2.8，让利润更充分奔跑
        'profit_levels': [0.20, 0.50, 1.00],
        'stoploss_adjustments': [0.00, 0.20, 0.50],
        'description': '波动大，留更多空间'
    }

    # ETF轮动策略配置
    ETF_ROTATION = {
        'atr_period': 10,
        'atr_multiplier': 1.5,  # 🔥 从1.5提高到2.0，减少频繁止损
        'profit_levels': [0.10, 0.30, 0.80],
        'stoploss_adjustments': [0.00, 0.10, 0.30],
        'description': '波动小，及时止损'
    }

    # ETF反弹策略配置
    ETF_REBOUND = {
        'atr_period': 10,
        'atr_multiplier': 1.5,  # 🔥 从1.5提高到2.0，给反弹更多空间
        'profit_levels': [0.10, 0.20, 0.50],
        'stoploss_adjustments': [0.00, 0.05, 0.15],
        'description': '短期反弹，严格止损'
    }

    # 白马攻防策略配置
    WHITEHORSE = {
        'atr_period': 14,
        'atr_multiplier': 2.0,  # 🔥 从2.0提高到2.5
        'profit_levels': [0.15, 0.30, 0.60],
        'stoploss_adjustments': [0.00, 0.10, 0.25],
        'description': '中长期，稳健保护'
    }

    # 红利策略配置
    DIVIDEND = {
        'atr_period': 20,
        'atr_multiplier': 3.0,  # 🔥 从2.5提高到3.0，价值投资需要更大空间
        'profit_levels': [0.10, 0.25, 0.50],
        'stoploss_adjustments': [0.00, 0.08, 0.20],
        'description': '价值投资，宽止损'
    }


def create_atr_service(strategy_name):
    """
    根据策略名称创建ATR服务

    参数:
        strategy_name: 策略名称

    返回:
        ATRService实例
    """
    configs = {
        'smallcap': ATRConfig.SMALLCAP,
        'small_cap': ATRConfig.SMALLCAP,
        'etf_rotation': ATRConfig.ETF_ROTATION,
        'etf_rebound': ATRConfig.ETF_REBOUND,
        'whitehorse': ATRConfig.WHITEHORSE,
        'white_horse': ATRConfig.WHITEHORSE,
        'dividend': ATRConfig.DIVIDEND,
    }

    config = configs.get(strategy_name.lower())
    if config is None:
        # 默认配置
        config = ATRConfig.SMALLCAP

    return ATRService(
        atr_period=config['atr_period'],
        atr_multiplier=config['atr_multiplier']
    )


# ==============================
# 市场情绪择时模块
# ==============================


class MarketSentiment:
    """市场情绪择时类"""

    def __init__(self):
        """初始化市场情绪模块"""
        self.cache = {}
        self.cache_date = None

    def calculate_panic_index(self, context=None):
        """
        计算恐慌指数
        公式：(跌停家数 / 总家数) × 100

        参数:
            context: 上下文

        返回:
            panic_index: 恐慌指数（0-100）
        """
        try:
            # 获取当前日期
            current_date = context.current_dt.date() if context else datetime.datetime.now().date()

            # 检查缓存
            cache_key = 'panic_index'
            if self.cache_date == current_date and cache_key in self.cache:
                return self.cache[cache_key]

            # 获取所有股票
            all_stocks = get_all_securities(['stock']).index.tolist()

            # 获取当前价格和开盘价
            current_data = get_current_data()
            limit_down_count = 0
            total_count = 0

            for stock in all_stocks:
                try:
                    # 跳过停牌股票
                    if not current_data[stock].paused:
                        day_open = current_data[stock].day_open
                        last_price = current_data[stock].last_price

                        if day_open > 0:
                            # 计算当日涨跌幅
                            change_ratio = (last_price - day_open) / day_open

                            # 跌停判断（跌幅约-10%）
                            if change_ratio <= -0.095:
                                limit_down_count += 1

                        total_count += 1

                except Exception as e:
                    continue

            # 计算恐慌指数
            panic_index = (limit_down_count / total_count * 100) if total_count > 0 else 0

            # 更新缓存
            self.cache[cache_key] = panic_index
            self.cache_date = current_date

            return panic_index

        except Exception as e:
            print(f"[MarketSentiment] 计算恐慌指数失败: {e}")
            return 0

    def check_north_money_flow(self, context=None, days=5):
        """
        检查北向资金流向（简化版：使用大盘涨跌作为代理指标）
        返回连续净流出天数

        参数:
            context: 上下文
            days: 检查天数（默认5天）

        返回:
            consecutive_outflow: 连续净流出天数
        """
        try:
            # 获取当前日期
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

    def get_up_down_ratio(self, context=None):
        """
        获取大盘涨跌家数比例

        参数:
            context: 上下文

        返回:
            up_ratio: 上涨家数占比（0-1）
        """
        try:
            # 获取当前日期
            current_date = context.current_dt.date() if context else datetime.datetime.now().date()

            # 检查缓存
            cache_key = 'up_down_ratio'
            if self.cache_date == current_date and cache_key in self.cache:
                return self.cache[cache_key]

            # 获取沪深300成分股
            index_stocks = get_index_stocks('000300.XSHG')

            up_count = 0
            total_count = 0

            current_data = get_current_data()
            for stock in index_stocks:
                try:
                    # 跳过停牌股票
                    if not current_data[stock].paused:
                        day_open = current_data[stock].day_open
                        last_price = current_data[stock].last_price

                        if day_open > 0:
                            if last_price > day_open:
                                up_count += 1

                        total_count += 1

                except Exception as e:
                    continue

            # 计算上涨占比
            up_ratio = (up_count / total_count) if total_count > 0 else 0

            # 更新缓存
            self.cache[cache_key] = up_ratio
            self.cache_date = current_date

            return up_ratio

        except Exception as e:
            print(f"[MarketSentiment] 获取涨跌家数比例失败: {e}")
            return 0.5

    def calculate_market_sentiment(self, context=None):
        """
        计算综合市场情绪评分（0-100）

        参数:
            context: 上下文

        返回:
            sentiment_score: 情绪评分（0-100）
            scores_detail: 各指标详细得分
        """
        scores = {}

        # 1. 恐慌指数（权重40%）- 跌停家数占比
        panic_index = self.calculate_panic_index(context)
        if panic_index < 1:
            scores['panic'] = 80  # 市场平静
            scores['panic_reason'] = '市场平静'
        elif panic_index < 3:
            scores['panic'] = 60  # 市场轻微恐慌
            scores['panic_reason'] = '市场轻微恐慌'
        elif panic_index < 5:
            scores['panic'] = 40  # 市场恐慌
            scores['panic_reason'] = '市场恐慌'
        else:
            scores['panic'] = 20  # 市场极度恐慌
            scores['panic_reason'] = '市场极度恐慌'

        # 2. 北向资金（权重40%）- 使用沪深300涨跌作为代理
        outflow_days = self.check_north_money_flow(context)
        if outflow_days == 0:
            scores['north'] = 80  # 资金净流入
            scores['north_reason'] = '资金净流入'
        elif outflow_days < 3:
            scores['north'] = 60  # 轻微净流出
            scores['north_reason'] = f'净流出{outflow_days}天'
        elif outflow_days < 5:
            scores['north'] = 40  # 中度净流出
            scores['north_reason'] = f'净流出{outflow_days}天'
        else:
            scores['north'] = 20  # 重度净流出
            scores['north_reason'] = f'净流出{outflow_days}天'

        # 3. 大盘涨跌家数（权重20%）- 上涨股票占比
        up_ratio = self.get_up_down_ratio(context)
        if up_ratio > 0.6:
            scores['trend'] = 80  # 市场强势
            scores['trend_reason'] = f'上涨占比{up_ratio*100:.1f}%'
        elif up_ratio > 0.4:
            scores['trend'] = 60  # 市场偏强
            scores['trend_reason'] = f'上涨占比{up_ratio*100:.1f}%'
        elif up_ratio > 0.3:
            scores['trend'] = 40  # 市场偏弱
            scores['trend_reason'] = f'上涨占比{up_ratio*100:.1f}%'
        else:
            scores['trend'] = 20  # 市场弱势
            scores['trend_reason'] = f'上涨占比{up_ratio*100:.1f}%'

        # 综合评分（重新分配权重：恐慌40% + 北向40% + 大盘20%）
        total_score = (
            scores['panic'] * 0.4 +
            scores['north'] * 0.4 +
            scores['trend'] * 0.2
        )

        return total_score, scores

    def market_sentiment_timing(self, context=None):
        """
        市场情绪择时决策

        参数:
            context: 上下文

        返回:
            position_ratio: 建议仓位比例（0-1）
            sentiment_score: 情绪评分（0-100）
            scores_detail: 各指标详细得分
            decision: 决策说明
        """
        sentiment_score, scores_detail = self.calculate_market_sentiment(context)

        if sentiment_score < 20:
            # 极度恐慌：清仓空仓
            position_ratio = 0.0
            decision = '极度恐慌：清仓空仓'
        elif sentiment_score < 40:
            # 恐慌：减仓至50%
            position_ratio = 0.5
            decision = '恐慌：减仓至50%'
        elif sentiment_score < 60:
            # 中性：保持正常仓位
            position_ratio = 1.0
            decision = '中性：保持正常仓位'
        else:
            # 强势：正常交易
            position_ratio = 1.0
            decision = '强势：正常交易'

        return position_ratio, sentiment_score, scores_detail, decision

    def clear_cache(self):
        """清除缓存"""
        self.cache = {}
        self.cache_date = None


# 全局实例（单例）
_market_sentiment_instance = None


def get_market_sentiment():
    """
    获取市场情绪择时实例（单例）

    返回:
        MarketSentiment实例
    """
    global _market_sentiment_instance
    if _market_sentiment_instance is None:
        _market_sentiment_instance = MarketSentiment()
    return _market_sentiment_instance


# ==============================
# 一、组合层初始化
# ==============================


def initialize(context):
    """
    初始化函数：设置交易参数、创建子账户、初始化策略
    """
    # ===== 基础设置 =====
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark('000300.XSHG')

    # 日志级别设置
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')

    # ===== 交易成本和滑点设置 =====
    set_slippage(FixedSlippage(0.002), type="stock")
    set_slippage(FixedSlippage(0.001), type="fund")

    cost_configs = [
        ("stock", 0.0005, 0.85 / 10000, 5),
        ("fund", 0, 0.5 / 10000, 5),
        ("mmf", 0, 0, 0)
    ]
    for asset_type, close_tax, commission, min_comm in cost_configs:
        set_order_cost(OrderCost(
            open_tax=0,
            close_tax=close_tax,
            open_commission=commission,
            close_commission=commission,
            close_today_commission=0,
            min_commission=min_comm
        ), type=asset_type)

    # ===== 多策略组合变量 =====
    # 固定权重分配模式（True=固定，False=动态优化）
    g.fixed_weight_mode = False

    # 初始资金比例：0号子账户（资金中枢），1~5号子账户（各策略）
    # 对应：小市值(1), ETF反弹(2), ETF轮动(3), 白马攻防(4), 红利(5)
    # 🔥 激进型配置：提高收益（增加小市值和ETF轮动比例）
    g.portfolio_value_proportion = [0, 0.35, 0.25, 0.3, 0.1, 0]

    # 风险参数
    g.risk_free_rate = 0.03  # 无风险利率
    g.rebalancing_frequency = 1  # 每1个月做一次最优配比
    g.rebalancing_cnt = 0

    # ===== 优化功能开关 =====
    # ATR动态止损开关
    g.enable_atr_stoploss = True
    g.atr_check_times = ["09:31", "10:00", "10:30", "14:50"]  # ATR止损检查时间
    
    # 市场情绪择时开关
    g.enable_market_sentiment = True
    g.market_sentiment_threshold = 30  # 🔥 从40降低到30，更激进地保持仓位
    
    # 技术指标筛选开关（小市值策略）
    g.enable_technical_filters = True

    # ===== 创建6个子账户 =====
    set_subportfolios(
        [
            SubPortfolioConfig(
                context.portfolio.starting_cash * g.portfolio_value_proportion[i],
                "stock",
            )
            for i in range(6)
        ]
    )

    # ===== 初始化策略参数（迁移自原 three_horse.py）=====
    # 策略1：小市值策略参数
    g.huanshou_check = False  # 放量换手检测
    g.xsz_version = "v2"  # 市值选用版本: v1/v2/v3
    g.enable_dynamic_stock_num = False  # 启用动态选股数量 3~6
    g.xsz_stock_num = 3  # 持股数量
    g.yesterday_HL_list = []  # 昨日涨停股票
    g.target_list = []  # 目标持仓股票
    g.xsz_buy_etf = "512800.XSHG"  # 空仓时购买ETF
    g.run_stoploss = True  # 是否进行止损
    g.stoploss_strategy = 3  # 止损策略: 1=止损线, 2=市场趋势, 3=联合
    g.stoploss_limit = 0.09  # 止损线
    g.stoploss_market = 0.05  # 市场趋势止损参数
    g.DBL_control = True  # 小市值大盘顶背离控制
    g.dbl = []  # 顶背离记录
    g.check_dbl_days = 10  # 顶背离检测窗口
    g.check_after_no_buy = False  # 止损后不买入
    g.no_buy_stocks = {}  # 检查卖出的股票
    g.no_buy_after_day = 3  # 止损后不买入时间窗口
    g.check_defense = False  # 成交额宽度检查
    g.industries = ["组20"]  # 高位防御板块
    g.defense_signal = None  # 防御信号
    g.cnt_defense_signal = []  # 择时次数
    g.cnt_bank_signal = []  # 组20择时次数
    g.history_defense_date_list = []  # 历史防御日期

    # 策略2：ETF反弹参数
    g.limit_days = 2  # 最少持仓周期
    g.n_days = 5  # 持仓周期
    g.holding_days = 0
    g.buy_list = []
    g.etf_pool_2 = [
        '159552.XSHE',  # 中证2000
        '159680.XSHE',  # 中证1000
        '561550.XSHG',  # 中证500
        '159249.XSHE',  # A500
        '159781.XSHE'  # 双创50
    ]
    g.strategy_ETF_2000_proportion = g.portfolio_value_proportion[2]
    g.strategy_ETF_2000_proportion_reset = None

    # 策略3：ETF轮动参数
    g.etf_pool_3 = [
        "510180.XSHG",  # 上证180ETF
        "513030.XSHG",  # 德国DAX ETF
        "513100.XSHG",  # 纳指ETF
        "513520.XSHG",  # 日经225ETF
        "510410.XSHG",  # 上证自然资源ETF
        "518880.XSHG",  # 黄金ETF
        "501018.XSHG",  # 南方原油（LOF）
        "159985.XSHE",  # 豆粕期货ETF
        "511090.XSHG",  # 30年期国债ETF
        "159915.XSHE",  # 创业板ETF
        "588120.XSHG",  # 科创100ETF
        "512480.XSHG",  # 半导体ETF
        "159851.XSHE",  # 金融科技ETF
        '513020.XSHG',  # 港股科技ETF
        "159637.XSHE",  # 新能源车龙头ETF
        "513690.XSHG",  # 港股红利/恒生高股息ETF
        "510050.XSHG",  # 上证50ETF
    ]
    g.select_etf = None  # ETF交易传递变量
    g.m_days = 25  # 动量参考天数
    g.m_score = 5  # 动量过滤分数
    g.enable_stop_loss_by_cur_day = False  # 改为False，使用ATR止损替代
    g.stoploss_limit_by_cur_day = -0.3  # 当日亏损 -3%
    g.rsrs_beta_cache = {}  # RSRS Beta值缓存
    g.rsrs_beta_date = None  # Beta值计算日期

    # 策略4：白马攻防参数
    g.check_out_lists = []
    g.market_temperature = "warm"
    g.stock_num_2 = 2  # 目标持股数量
    g.roe = 10  # ROE权重
    g.roa = 6  # ROA权重

    # 策略5：红利参数
    g.sell_list = []
    g.buy_df = []
    g.target_num = [2, 1]  # 红利低波2只，红利价值1只
    g.high_limit_list = []

    # ===== 市场情绪择时参数 =====
    g.market_sentiment_score = 100  # 当前市场情绪评分
    g.market_sentiment_position_ratio = 1.0  # 建议仓位比例

    # ===== 记录各策略净值轨迹 =====
    g.strategys_values = pd.DataFrame(
        columns=["smallcap", "etf_rebound", "etf_rotation", "whitehorse", "dividend"]
    )

    # ===== 创建市场情绪择时实例 =====
    if g.enable_market_sentiment:
        g.market_sentiment_obj = get_market_sentiment()
        log.info("市场情绪择时模块已启用")

    # ===== 创建策略实例（集成ATR服务）=====
    g.strategies = {}

    # 策略1：小市值策略（ATR: 14天, 2.0倍, 20%/50%/100%）
    g.strategies[1] = SmallCap_Strategy(context, 1, "小市值策略")

    # 策略2：ETF反弹策略（ATR: 10天, 1.5倍, 10%/20%/50%）
    g.strategies[2] = ETF_Rebound_Strategy(context, 2, "ETF反弹策略")

    # 策略3：ETF轮动策略（ATR: 10天, 1.5倍, 10%/30%/80%）
    g.strategies[3] = ETF_Rotation_Strategy(context, 3, "ETF轮动策略")

    # 策略4：白马攻防策略（ATR: 14天, 2.0倍, 15%/30%/60%）
    g.strategies[4] = WhiteHorse_Strategy(context, 4, "白马攻防策略")

    # 策略5：红利策略（ATR: 20天, 2.5倍, 10%/25%/50%）
    g.strategies[5] = Dividend_Strategy(context, 5, "红利策略")

    # ===== 策略持仓记录（用于映射股票到策略ID）=====
    g.stock_strategy = {}
    g.strategy_holdings = {1: [], 2: [], 3: [], 4: [], 5: []}

    # ===== 策略价值记录 =====
    g.strategy_value_data = {}
    # 记录策略初始金额，用于计算收益率
    g.strategy_starting_cash = {
        1: context.portfolio.starting_cash * g.portfolio_value_proportion[1],
        2: context.portfolio.starting_cash * g.portfolio_value_proportion[2],
        3: context.portfolio.starting_cash * g.portfolio_value_proportion[3],
        4: context.portfolio.starting_cash * g.portfolio_value_proportion[4],
        5: context.portfolio.starting_cash * g.portfolio_value_proportion[5],
    }
    # 记录每日策略收益（从初始资金开始，每日累加盈亏）
    g.strategy_value = {
        1: context.portfolio.starting_cash * g.portfolio_value_proportion[1],
        2: context.portfolio.starting_cash * g.portfolio_value_proportion[2],
        3: context.portfolio.starting_cash * g.portfolio_value_proportion[3],
        4: context.portfolio.starting_cash * g.portfolio_value_proportion[4],
        5: context.portfolio.starting_cash * g.portfolio_value_proportion[5],
    }

    # ===== 组合层：记录子策略净值 & 权重优化 =====
    run_daily(get_strategys_values, "18:00")
    run_weekly(calculate_optimal_weights, 1, "19:00")

    # ===== 优化功能调度 =====
    # 市场情绪择时（每日开盘前检查）
    if g.enable_market_sentiment:
        run_daily(check_market_sentiment, "09:00")

    # ===== 子策略调度 =====
    # 策略1：小市值策略
    run_daily(smallcap_prepare, "09:05")
    run_weekly(smallcap_sell, 2, "09:40")
    run_weekly(smallcap_buy, 2, "09:40:02")
    if g.DBL_control:
        run_daily(smallcap_check_dbl, "09:31")
    
    # 小市值策略：优先使用ATR动态止损，保留原有止损作为保底
    if g.enable_atr_stoploss:
        for time_str in g.atr_check_times:
            run_daily(smallcap_atr_stoploss, time_str)
    run_daily(smallcap_stoploss, "10:01")  # 保留原有止损作为保底
    
    if g.huanshou_check:
        run_daily(smallcap_check_turnover, "10:30")
    run_daily(smallcap_check_limit_up, "14:00")
    if g.check_defense:
        run_daily(smallcap_check_defense, "14:50")
    run_daily(smallcap_close_account, "14:50")

    # 策略2：ETF反弹策略
    run_daily(etf_rebound_capital_balance, "14:45")
    run_daily(etf_rebound_sell, "14:49")
    run_daily(etf_rebound_buy, "14:50")
    # ETF反弹ATR止损
    if g.enable_atr_stoploss:
        for time_str in g.atr_check_times:
            run_daily(etf_rebound_atr_stoploss, time_str)

    # 策略3：ETF轮动策略
    run_daily(etf_rotation_sell, "10:35:00")
    run_daily(etf_rotation_buy, "10:35:05")
    # ETF轮动：使用ATR动态止损替代原有日内止损
    if g.enable_atr_stoploss:
        for time_str in g.atr_check_times:
            run_daily(etf_rotation_atr_stoploss, time_str)
    if g.enable_stop_loss_by_cur_day:  # 可选保留日内止损作为补充
        run_daily(etf_rotation_stoploss_intraday, "10:01")
        run_daily(etf_rotation_stoploss_intraday, "10:31")

    # 策略4：白马攻防策略
    run_monthly(whitehorse_before_market_open, 1, time="8:00")
    run_monthly(whitehorse_adjust_position, 1, time="10:40")
    # 白马攻防ATR止损
    if g.enable_atr_stoploss:
        for time_str in g.atr_check_times:
            run_daily(whitehorse_atr_stoploss, time_str)

    # 策略5：红利策略
    run_daily(dividend_prepare, "09:00")
    run_monthly(dividend_get_stock_list, 1, "09:01")
    run_monthly(dividend_trade, 1, "09:30")
    run_daily(dividend_check_limit_up, "10:00")
    # 红利策略ATR止损
    if g.enable_atr_stoploss:
        for time_str in g.atr_check_times:
            run_daily(dividend_atr_stoploss, time_str)

    # 记录各策略每日收益
    run_daily(make_record, "15:01")
    run_daily(print_summary, "15:02")


# ==============================
# 二、优化功能：市场情绪择时
# ==============================


def check_market_sentiment(context):
    """
    市场情绪择时检查
    每日开盘前执行，根据情绪评分调整仓位
    """
    if not g.enable_market_sentiment:
        return

    try:
        # 计算市场情绪评分
        sentiment_score, scores_detail = g.market_sentiment_obj.calculate_market_sentiment(context)
        position_ratio, _, scores_detail, decision = g.market_sentiment_obj.market_sentiment_timing(context)

        # 更新全局变量
        g.market_sentiment_score = sentiment_score
        g.market_sentiment_position_ratio = position_ratio

        # 记录情绪评分
        log.info("=" * 80)
        log.info(f"📊 市场情绪择时报告 - {context.current_dt.strftime('%Y-%m-%d')}")
        log.info("=" * 80)
        log.info(f"📈 恐慌指数: {scores_detail.get('panic', 'N/A')}")
        log.info(f"📉 北向资金: {scores_detail.get('north', 'N/A')}")
        log.info(f"📈 市场趋势: {scores_detail.get('trend', 'N/A')}")
        log.info("=" * 80)
        log.info(f"🎯 综合评分: {sentiment_score:.2f} / 100")
        log.info(f"📋 建议仓位: {position_ratio * 100:.0f}% - {decision}")
        log.info("=" * 80)

        # 根据情绪评分调整仓位
        if position_ratio < 1.0:
            log.warning(f"⚠️ 市场情绪不佳，建议减仓至{position_ratio * 100:.0f}%")
            # 各策略可以根据此比例调整建仓金额

    except Exception as e:
        log.error(f"市场情绪择时检查失败: {e}")
        g.market_sentiment_score = 100
        g.market_sentiment_position_ratio = 1.0


# ==============================
# 三、组合层：子策略净值记录 & 权重优化
# ==============================


def get_strategys_values(context):
    """
    记录各子策略每日净值
    用于后续的组合权重优化
    """
    df = g.strategys_values
    data = dict(
        zip(
            df.columns,
            [context.subportfolios[i + 1].total_value for i in range(len(df.columns))],
        )
    )
    df.loc[len(df)] = data
    if len(df) > 250:
        df = df.drop(0)


def calculate_optimal_weights(context, alpha=0.5):
    """
    计算最优策略权重
    使用VASR(Variance-Adjusted Sharpe Ratio)作为优化目标
    """
    # 固定权重模式：不执行优化
    if g.fixed_weight_mode:
        log.info("固定权重模式，跳过权重优化")
        return

    df = g.strategys_values
    g.rebalancing_cnt += 1

    # 检查是否满足再平衡条件
    if len(df) < 250 or not g.rebalancing_cnt % g.rebalancing_frequency == 0:
        return

    # 记录当前权重
    current_weights = [
        round(context.subportfolios[i].total_value / context.portfolio.total_value, 3)
        for i in range(len(g.portfolio_value_proportion))
    ]
    weights_str = ", ".join(
        [f"账户{i}: {weight:.1%}" for i, weight in enumerate(current_weights)]
    )
    log.info(f"目前仓位比例: {weights_str}")

    # 计算收益率和协方差矩阵
    returns = df.pct_change().dropna()
    if returns.empty:
        return

    annualized_returns = returns.mean() * 252
    cov_matrix = returns.cov() * 252

    def negative_vasr(weights):
        """计算负的VASR（用于最小化）"""
        portfolio_return = np.dot(weights, annualized_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        if portfolio_volatility == 0:
            return 0
        sharpe_ratio = (portfolio_return - g.risk_free_rate) / portfolio_volatility
        vasr = sharpe_ratio / (1 + alpha * portfolio_volatility)
        return -vasr

    # 优化约束条件
    constraints = [
        {"type": "eq", "fun": lambda x: np.sum(x) - 1},  # 权重和为1
        {"type": "ineq", "fun": lambda x: x - 0.05},  # 最小权重5%
    ]

    # 添加权重变化约束（避免极端调仓）
    last_best_weights = g.portfolio_value_proportion[1:]
    constraints.append(
        {"type": "ineq", "fun": lambda x: 0.1 - np.abs(x - last_best_weights)}
    )

    num_strategies = len(returns.columns)
    initial_weights = np.array([1.0 / num_strategies] * num_strategies)
    initial_weights = np.maximum(initial_weights, 0.05)

    # 执行优化
    result = minimize(
        negative_vasr,
        initial_weights,
        method="SLSQP",
        constraints=constraints,
    )

    if not result.success:
        log.warning("权重优化失败，保持当前权重")
        return

    best_weights = result.x.tolist()
    g.portfolio_value_proportion = [0] + best_weights
    log.info(f"最佳权重: {[round(i, 3) for i in best_weights]}")


# ==============================
# 四、策略基类（集成ATR动态止损）
# ==============================


class Strategy:
    """
    策略基类
    提供子账户管理、通用股票过滤、ATR动态止损等功能
    所有子策略都继承自此类
    """

    def __init__(self, context, subportfolio_index, name):
        """
        初始化策略

        Args:
            context: 上下文对象
            subportfolio_index: 子账户索引
            name: 策略名称
        """
        self.subportfolio_index = subportfolio_index
        self.name = name
        self.subportfolio = context.subportfolios[self.subportfolio_index]
        self.stock_sum = 1  # 默认持仓股票数
        self.hold_list = []  # 持仓列表
        self.limit_up_list = []  # 昨日涨停列表
        self.fill_stock = "511880.XSHG"  # 货币ETF，用于资金闲置

        # ATR服务实例（子类初始化时配置）
        self.atr_service = None
        self.atr_enabled = False

    def init_atr_service(self, atr_config):
        """
        初始化ATR服务

        Args:
            atr_config: ATR配置字典
        """
        self.atr_service = ATRService(
            atr_period=atr_config['atr_period'],
            atr_multiplier=atr_config['atr_multiplier']
        )
        self.atr_enabled = True
        self.atr_profit_levels = atr_config.get('profit_levels', [0.20, 0.50, 1.00])
        self.atr_stoploss_adjustments = atr_config.get('stoploss_adjustments', [0.00, 0.20, 0.50])
        log.info(f"[{self.name}] ATR动态止损已启用 - 周期{atr_config['atr_period']}天, "
                f"倍数{atr_config['atr_multiplier']}, 盈利保护{[f'{p*100:.0f}%' for p in self.atr_profit_levels]}")

    def _prepare(self, context):
        """
        更新持仓和昨日涨停列表
        每个交易日开始前调用
        """
        self.hold_list = list(
            context.subportfolios[self.subportfolio_index].long_positions.keys()
        )
        if self.hold_list:
            df = get_price(
                self.hold_list,
                end_date=context.previous_date,
                frequency="daily",
                fields=["close", "high_limit"],
                count=1,
                panel=False,
                fill_paused=False,
            )
            df = df[df["close"] == df["high_limit"]]
            self.limit_up_list = list(df.code)
        else:
            self.limit_up_list = []

        log.debug(
            f"[{self.name}] 持仓: {len(self.hold_list)}只, "
            f"昨日涨停: {len(self.limit_up_list)}只"
        )

    def _check(self, context):
        """检查昨日涨停票：涨停打开就卖出"""
        if self.limit_up_list:
            current_data = get_current_data()
            for stock in self.limit_up_list:
                if current_data[stock].last_price < current_data[stock].high_limit:
                    log.info(f"[{self.name}] 涨停打开，卖出 {stock}")
                    self.order_target_value_(stock, 0)

    def _adjust(self, context, target):
        """
        通用调仓函数：等权买入目标股票

        Args:
            context: 上下文对象
            target: 目标股票列表
        """
        # 卖出不在目标且不是昨日涨停的
        for security in self.hold_list:
            if (security not in target) and (security not in self.limit_up_list):
                log.info(f"[{self.name}] 调出持仓 {security}")
                self.order_target_value_(security, 0)

        # 调整子账户间资金
        self.balance_subportfolios(context)

        # 买入目标股票
        current_positions = list(self.subportfolio.long_positions.keys())
        candidates = [s for s in target if s not in current_positions]
        count = len(candidates)
        if count == 0 or self.stock_sum <= len(current_positions):
            log.info(f"[{self.name}] 无新股票可买入或已达持仓上限")
            return

        # 计算可用资金（考虑市场情绪择时）
        target_total = (
            g.portfolio_value_proportion[self.subportfolio_index]
            * context.portfolio.total_value
        )
        
        # 应用市场情绪择时仓位调整
        if g.enable_market_sentiment:
            target_total *= g.market_sentiment_position_ratio
            if g.market_sentiment_position_ratio < 1.0:
                log.info(f"[{self.name}] 市场情绪调整后目标资金: {target_total:.2f} "
                        f"({g.market_sentiment_position_ratio*100:.0f}%)")

        value_to_use = max(
            0,
            min(
                target_total - self.subportfolio.positions_value,
                self.subportfolio.available_cash,
            ),
        )
        if value_to_use <= 0:
            log.info(f"[{self.name}] 无可用资金: {value_to_use:.2f}")
            return

        value_per = value_to_use / count

        log.info(f"[{self.name}] 买入{candidates}，每只{value_per:.2f}")

        for security in candidates:
            self.order_target_value_(security, value_per)

    def check_atr_stoploss(self, context):
        """
        ATR动态止损检查
        由各策略子类继承，实现自定义逻辑
        """
        if not self.atr_enabled or not g.enable_atr_stoploss:
            return

        current_positions = self.subportfolio.long_positions
        current_data = get_current_data()

        for security, position in current_positions.items():
            try:
                current_price = current_data[security].last_price
                avg_cost = position.avg_cost
                
                # 跳过昨日涨停的股票
                if security in self.limit_up_list:
                    continue

                # 检查ATR止损
                should_stop, stoploss_price, reason = self.atr_service.check_stoploss(
                    security=security,
                    current_price=current_price,
                    avg_cost=avg_cost,
                    profit_levels=self.atr_profit_levels,
                    stoploss_adjustments=self.atr_stoploss_adjustments,
                    order_func=lambda s, v: self.order_target_value_(s, v)
                )

                if should_stop:
                    log.info(f"[{self.name}] 🔥🔥🔥 ATR动态止损触发 {security} "
                           f"成本{avg_cost:.2f} 现价{current_price:.2f} "
                           f"止损价{stoploss_price:.2f} - {reason}")

            except Exception as e:
                log.warning(f"[{self.name}] ATR止损检查失败 {security}: {e}")

    def order_target_value_(self, security, value):
        """
        子账户内下单函数

        Args:
            security: 股票代码
            value: 目标市值

        Returns:
            下单结果
        """
        current_data = get_current_data()
        if current_data[security].paused:
            log.info(f"[{self.name}] {security} 今日停牌，跳过")
            return None

        if value == 0:
            # 卖出
            amount = self.subportfolio.long_positions.get(security, None)
            if amount:
                log.info(f"[{self.name}] 卖出 {security}，持仓{amount.closeable_amount}股")
                # 🔧 清除持仓最高价缓存
                if self.atr_service and self.atr_enabled:
                    self.atr_service.clear_security_cache(security)
        else:
            # 检查最小交易金额（避免小金额交易，手续费占比高）
            if value <= 5000:
                log.info(
                    f"[{self.name}] {security} 买入金额{value:.2f}元 <= 5000元，跳过交易"
                )
                return None

            # 检查当前持仓价值
            current_position = self.subportfolio.long_positions.get(security, None)
            if current_position:
                current_value = current_position.closeable_amount * current_data[security].last_price
                # 计算与目标市值的差异
                diff_value = abs(current_value - value)
                # 如果差异小于5000元，跳过调整（避免小金额调整）
                if diff_value < 5000:
                    log.info(
                        f"[{self.name}] {security} 持仓市值{current_value:.2f}元，"
                        f"目标市值{value:.2f}元，差异{diff_value:.2f}元<5000元，跳过调整"
                    )
                    return None

            # 买入
            price = current_data[security].last_price
            if price > 0:
                # 计算原始股数
                raw_shares = value / price
                # 向下取整到100的倍数（A股最小交易单位）
                shares = int(raw_shares / 100) * 100

                # 检查最小交易单位
                if shares < 100:
                    log.info(
                        f"[{self.name}] {security} 资金不足{value:.2f}元，"
                        f"价格{price:.2f}元/股，计算{raw_shares:.0f}股<100股，跳过交易"
                    )
                    return None

                log.info(
                    f"[{self.name}] 买入 {security}，目标市值{value:.2f}，"
                    f"价格{price:.2f}，约{shares}股"
                )

        # 更新策略持仓映射
        if value == 0:
            # 卖出，从持仓列表移除
            if security in g.strategy_holdings[self.subportfolio_index]:
                g.strategy_holdings[self.subportfolio_index].remove(security)
        else:
            # 买入，添加到持仓列表
            if security not in g.strategy_holdings[self.subportfolio_index]:
                g.strategy_holdings[self.subportfolio_index].append(security)
        g.stock_strategy[security] = self.subportfolio_index

        # 执行下单
        order_result = order_target_value(security, value, pindex=self.subportfolio_index)

        # 卖出时更新策略累计价值（记录已实现盈亏）
        if value == 0 and order_result:
            pnl_value = (order_result.price - order_result.avg_cost) * order_result.amount
            g.strategy_value[self.subportfolio_index] += pnl_value

        return order_result

    def get_net_values(self, amount):
        """
        子账户净值修正
        资金在0号和子账户之间划转时使用

        Args:
            amount: 划转金额，正数表示划入，负数表示划出
        """
        df = g.strategys_values
        if df.empty:
            return

        col_idx = self.subportfolio_index - 1
        last_idx = len(df) - 1
        old_last = df.iloc[last_idx, col_idx]
        df.iloc[last_idx, col_idx] = old_last + amount
        new_last = df.iloc[last_idx, col_idx]

        if old_last == 0:
            return

        for i in range(last_idx - 1, -1, -1):
            df.iloc[i, col_idx] = new_last * df.iloc[i, col_idx] / old_last

        log.debug(
            f"[{self.name}] 净值调整: {old_last:.2f} -> {new_last:.2f}, "
            f"变动{amount:.2f}"
        )

    def balance_subportfolios(self, context):
        """
        子账户与0号账户间资金平衡
        确保每个子账户的资金比例符合目标
        """
        target = (
            g.portfolio_value_proportion[self.subportfolio_index]
            * context.portfolio.total_value
        )
        value = self.subportfolio.total_value

        log.debug(
            f"[{self.name}] 资金平衡检查: 目标{target:.2f}, "
            f"当前{value:.2f}, 差值{target - value:.2f}"
        )

        # 仓位过高：向0号账户划出资金
        cash = self.subportfolio.transferable_cash
        if cash > 0 and target < value:
            amount = min(value - target, cash)
            if amount > 100:  # 小额不调整
                transfer_cash(self.subportfolio_index, 0, amount)
                self.get_net_values(-amount)
                log.info(f"[{self.name}] 划出资金到0号账户: {amount:.2f}")

        # 仓位过低：从0号账户划入资金
        cash0 = context.subportfolios[0].transferable_cash
        if target > value and cash0 > 0:
            amount = min(target - value, cash0)
            if amount > 100:  # 小额不调整
                transfer_cash(0, self.subportfolio_index, amount)
                self.get_net_values(amount)
                log.info(f"[{self.name}] 从0号账户划入资金: {amount:.2f}")

    def filter_basic_stock(self, context, stock_list):
        """
        通用基础过滤（ST/科创/北交/次新）

        Args:
            context: 上下文对象
            stock_list: 待过滤股票列表

        Returns:
            过滤后的股票列表
        """
        current_data = get_current_data()
        res = []
        for stock in stock_list:
            info = current_data[stock]
            if info.paused:
                continue
            if info.is_st or "ST" in info.name or "*" in info.name or "退" in info.name:
                continue
            # 科创 / 北交 / 创业板过滤
            if stock[0] == "4" or stock[0] == "8" or stock[:2] == "68":
                continue
            if context.previous_date - get_security_info(
                stock
            ).start_date < datetime.timedelta(375):
                continue
            res.append(stock)
        return res

    def filter_limitup_limitdown_stock(self, context, stock_list):
        """
        过滤涨跌停股票

        Args:
            context: 上下文对象
            stock_list: 待过滤股票列表

        Returns:
            过滤后的股票列表
        """
        current_data = get_current_data()
        res = []
        for stock in stock_list:
            if stock in self.subportfolio.long_positions:
                res.append(stock)
                continue
            if (
                current_data[stock].last_price < current_data[stock].high_limit
                and current_data[stock].last_price > current_data[stock].low_limit
            ):
                res.append(stock)
        return res

    def filter_technical_indicators(self, context, stock_list):
        """
        技术指标筛选（新增优化）
        
        筛选条件：
        1. RSI指标：15 < RSI < 85（避免超买超卖）🔥 放宽条件
        2. 均线多头排列：5日均线 > 20日均线
        3. 突破新高：创60日新高（可选）
        
        Args:
            context: 上下文对象
            stock_list: 待过滤股票列表
        
        Returns:
            过滤后的股票列表
        """
        if not g.enable_technical_filters:
            return stock_list

        res = []
        for stock in stock_list:
            try:
                # RSI筛选
                hist_data = attribute_history(stock, 125, '1d', ['close'], skip_paused=True, df=True, fq='pre')
                if hist_data.empty or len(hist_data) < 20:
                    continue
                    
                prices = hist_data['close'].values
                deltas = np.diff(prices)
                seed = deltas[:15]
                up = seed[seed >= 0].sum() / 14
                down = -seed[seed < 0].sum() / 14
                if down == 0:
                    rsi = 100
                else:
                    rs = up / down
                    rsi = 100 - 100 / (1 + rs)
                
                # 🔥 RSI筛选：15 < RSI < 85（从20-80放宽）
                if rsi <= 20 or rsi >= 80:
                    log.debug(f"[{self.name}] {stock} RSI={rsi:.2f}，不满足15-85范围，过滤")
                    continue
                
                # 均线多头排列筛选
                ma5 = hist_data['close'].tail(5).mean()
                ma20 = hist_data['close'].tail(20).mean()
                if ma5 <= ma20:
                    log.debug(f"[{self.name}] {stock} MA5={ma5:.2f} <= MA20={ma20:.2f}，非多头排列，过滤")
                    continue
                
                # 通过所有技术指标筛选
                res.append(stock)
                log.debug(f"[{self.name}] {stock} RSI={rsi:.2f}, MA5={ma5:.2f}>MA20={ma20:.2f}，通过技术筛选")
                
            except Exception as e:
                log.warning(f"[{self.name}] 技术指标筛选失败 {stock}: {e}")
                # 出错时保守处理，保留该股票
                res.append(stock)
        
        log.info(f"[{self.name}] 技术指标筛选：{len(stock_list)} -> {len(res)}")
        return res


# ==============================
# 五、子策略1：小市值策略（35%）- 支持v1/v2/v3 + ATR动态止损
# ==============================


class SmallCap_Strategy(Strategy):
    """
    小市值策略（优化版）
    - 支持三个版本：v1（双市值+行业分散）、v2（国九+roa+roe）、v3（国九+红利+审计）
    - 集成ATR动态止损（14天, 2.0倍, 20%/50%/100%）
    - 集成技术指标筛选
    """

    def __init__(self, context, subportfolio_index, name):
        super().__init__(context, subportfolio_index, name)
        self.version = g.xsz_version
        self.stock_sum = g.xsz_stock_num
        
        # 初始化ATR服务（小市值策略配置）
        self.init_atr_service(ATRConfig.SMALLCAP)
        
        log.info(f"[{self.name}] 初始化完成，版本{self.version}，最大持仓{self.stock_sum}只")

    def get_stock_list_v1(self, context):
        """v1 选股模块（双市值+行业分散）"""
        # 获取股票所属行业
        def filter_industry_stock(stock_list):
            result = get_industry(security=stock_list)
            selected_stocks = []
            industry_list = []
            for stock_code, info in result.items():
                industry_name = info['sw_l2']['industry_name']
                if industry_name not in industry_list:
                    industry_list.append(industry_name)
                    selected_stocks.append(stock_code)
                    log.debug(f"行业信息: {industry_name} (股票: {stock_code} {get_security_info(stock_code).display_name})")
                    if len(industry_list) == 10:
                        break
            return selected_stocks

        initial_list = self.filter_stocks(context, get_index_stocks('399101.XSHE'))

        # 获取流通市值最小的50个股票
        q = query(valuation.code).filter(valuation.code.in_(initial_list)).order_by(
            valuation.circulating_market_cap.asc()).limit(50)
        initial_list = list(get_fundamentals(q).code)

        # 每个行业获取1个股票，总共获取stock_sum个行业的股票
        final_list = filter_industry_stock(initial_list)[:self.stock_sum]
        
        # 技术指标筛选
        if g.enable_technical_filters:
            final_list = self.filter_technical_indicators(context, final_list)
        
        log.info(f"[{self.name}] v1选出的股票:{final_list}")
        return final_list

    def get_stock_list_v2(self, context):
        """v2 选股模块（国九+roa+roe）"""
        initial_list = self.filter_stocks(context, get_index_stocks('399101.XSHE'))

        q = query(
            valuation.code,
            valuation.market_cap,
            income.np_parent_company_owners,
            income.net_profit,
            income.operating_revenue,
            valuation.turnover_ratio
        ).filter(
            valuation.code.in_(initial_list),
            valuation.market_cap.between(5, 50),
            income.np_parent_company_owners > 0,
            income.net_profit > 0,
            income.operating_revenue > 1e8,
            fundamentals.indicator.roe > 0.15,
            fundamentals.indicator.roa > 0.10,
        ).order_by(valuation.market_cap.asc()).limit(50)
        df = get_fundamentals(q)
        if df.empty:
            return []
        final_list = list(df.code)
        last_prices = history(1, '1d', 'close', final_list, df=False)
        # 价格过滤
        final_list = [stock for stock in final_list if stock in self.subportfolio.long_positions or last_prices[stock] <= 20][
               :self.stock_sum]
        
        # 技术指标筛选
        if g.enable_technical_filters:
            final_list = self.filter_technical_indicators(context, final_list)
        
        log.info(f"[{self.name}] v2选出的股票:{final_list}")
        return final_list

    def get_stock_list_v3(self, context):
        """v3 选股模块（国九+红利+审计）"""
        initial_list = self.filter_stocks(context, get_index_stocks('399101.XSHE'))

        q = query(
            valuation.code,
            valuation.market_cap,
            income.net_profit,
            income.operating_revenue
        ).filter(
            valuation.code.in_(initial_list),
            valuation.market_cap.between(10, 100),
            income.operating_revenue > 1e8,
            indicator.roe > 0,
            indicator.roa > 0,
            income.net_profit > 2000000,
        ).order_by(valuation.market_cap.asc()).limit(self.stock_sum * 5)
        final_list = list(get_fundamentals(q).code)
        # 过滤审计意见
        final_list = self.filter_audit(context, final_list)
        # 过滤红利股
        final_list = self.bonus_filter(context, final_list)
        # 由于有时候选股条件苛刻，所以会没有股票入选，这时买入银华日利ETF
        if not final_list:
            log.info(f"[{self.name}] v3无适合股票，买入ETF")
            return [self.fill_stock]
        # 价格过滤
        last_prices = history(1, unit='1d', field='close', security_list=final_list)
        final_list = [s for s in final_list if s in g.strategy_holdings[1] or last_prices[s][-1] <= 50]
        
        # 技术指标筛选
        if g.enable_technical_filters:
            final_list = self.filter_technical_indicators(context, final_list)
        
        log.info(f"[{self.name}] v3选出的股票:{final_list}")
        return final_list

    def filter_stocks(self, context, stock_list):
        """基础过滤函数"""
        current_data = get_current_data()
        res = []
        for stock in stock_list:
            if current_data[stock].paused:
                continue
            if current_data[stock].is_st:
                continue
            if 'ST' in current_data[stock].name or '*' in current_data[stock].name or '退' in current_data[stock].name:
                continue
            if stock.startswith('30') or stock.startswith('68') or stock.startswith('8') or stock.startswith('4'):
                continue
            res.append(stock)
        return res

    def filter_audit(self, context, code_list):
        """过滤审计意见"""
        final_list = []
        for stock in code_list:
            previous_date = context.previous_date
            last_year = (previous_date.replace(year=previous_date.year - 3, month=1, day=1)).strftime('%Y-%m-%d')
            q = query(finance.STK_AUDIT_OPINION.code, finance.STK_AUDIT_OPINION.pub_date, finance.STK_AUDIT_OPINION) \
                .filter(finance.STK_AUDIT_OPINION.code == stock, finance.STK_AUDIT_OPINION.pub_date >= last_year)
            df = finance.run_query(q)
            values_to_check = [3, 4, 5, 7]
            if not df['opinion_type_id'].isin(values_to_check).any():
                final_list.append(stock)
        return final_list

    def bonus_filter(self, context, stock_list):
        """过滤红利股"""
        year = context.previous_date.year
        start_date = datetime.datetime(year=year, month=1, day=1)
        end_date = context.previous_date
        if end_date.month in [5]:
            q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.company_name, finance.STK_XR_XD.board_plan_pub_date,
                      finance.STK_XR_XD.bonus_amount_rmb, finance.STK_XR_XD.bonus_ratio_rmb
                      ).filter(
                finance.STK_XR_XD.board_plan_pub_date > start_date,
                finance.STK_XR_XD.implementation_pub_date <= end_date,
                finance.STK_XR_XD.bonus_ratio_rmb > 0,
                finance.STK_XR_XD.code.in_(stock_list))
            expected_bonus_df = finance.run_query(q)

            if len(expected_bonus_df) > 0:
                bonus_list = expected_bonus_df['code'].unique().tolist()
                price_df = history(1, unit='1d', field='close', security_list=bonus_list, df=True, skip_paused=False,
                                   fq='pre')
                price_df = price_df.T
                price_df.rename(columns={price_df.columns[0]: 'Close_now'}, inplace=True)
                price_df['code'] = price_df.index
                expected_bonus_df = pd.merge(expected_bonus_df, price_df, on=('code',), how='left')
                expected_bonus_df['bonus_ratio'] = (expected_bonus_df['bonus_ratio_rmb']) / expected_bonus_df['Close_now']
                expected_bonus_df = expected_bonus_df.sort_values(by='bonus_ratio', ascending=True)
                bonus_list = expected_bonus_df['code'].unique().tolist()
            else:
                bonus_list = []
        else:
            reprot_date = datetime.datetime(year=year - 1, month=12, day=31)
            q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date,
                      finance.STK_XR_XD.bonus_amount_rmb, finance.STK_XR_XD.bonus_ratio_rmb
                      ).filter(
                finance.STK_XR_XD.report_date == reprot_date,
                finance.STK_XR_XD.bonus_type == '年度分红',
                finance.STK_XR_XD.implementation_pub_date <= end_date,
                finance.STK_XR_XD.board_plan_bonusnote == '不分配不转增',
                finance.STK_XR_XD.code.in_(stock_list))

            no_year_bonus = finance.run_query(q)
            no_year_bonus_list = no_year_bonus['code'].unique().tolist()
            # 排除今年不分红的股票
            bonus_list = [code for code in stock_list if code not in no_year_bonus_list]

        if len(bonus_list) < self.stock_sum:
            bonus_list.extend([x for x in stock_list if x not in bonus_list][
                              :self.stock_sum - len(bonus_list)])
        return bonus_list

    def prepare(self, context):
        """小市值早盘变量预处理"""
        g.trading_signal = False if context.current_dt.month in [1, 4] else True
        g.yesterday_HL_list = []
        # 获取昨日涨停列表
        if g.strategy_holdings[1]:
            df = get_price(g.strategy_holdings[1],
                           end_date=context.previous_date,
                           fields=['close', 'high_limit', 'low_limit'],
                           frequency='daily',
                           count=1,
                           panel=False,
                           fill_paused=False)
            g.yesterday_HL_list = list(df[df['close'] == df['high_limit']].code)

    def sell(self, context):
        """小市值卖出逻辑"""
        log.info(f"[{self.name}] 开始调仓 - 日期: {context.current_dt.strftime('%Y-%m-%d')}")
        
        # 先清空target_list，避免暂停调仓时仍买入旧目标股票
        g.target_list = []

        # 市场情绪择时：情绪不佳时暂停调仓
        if g.enable_market_sentiment and g.market_sentiment_position_ratio < 0.5:
            log.warning(f"[{self.name}] 市场情绪不佳（评分{g.market_sentiment_score:.2f}），暂停调仓")
            return

        # 近期有顶背离信号时暂停调仓（规避系统性风险）
        if g.DBL_control:
            if len(g.dbl) < 10:
                for i in range(9, -1, -1):
                    self.check_dbl(context, end_days=0 - i)
        if g.DBL_control and 1 in g.dbl[-g.check_dbl_days:]:
            log.info(f"近{g.check_dbl_days}日检测到大盘顶背离，暂停调仓以控制风险")
            return

        # 检测空仓期
        month = context.current_dt.month
        if month in [1, 4]:
            g.trading_signal = False
        if not g.trading_signal:
            return

        # 成交额宽度检查
        if g.check_defense and g.defense_signal:
            log.info("触发成交额宽度检查信号，暂停调仓以控制风险")
            return

        # 动态调整选股数量
        diff = None
        if g.enable_dynamic_stock_num:
            ma_para = 10
            today = context.previous_date
            start_date = today - datetime.timedelta(days=ma_para * 2)
            index_df = get_price('399101.XSHE', start_date=start_date, end_date=today, frequency='daily')
            index_df['ma'] = index_df['close'].rolling(window=ma_para).mean()
            last_row = index_df.iloc[-1]
            diff = last_row['close'] - last_row['ma']
            g.xsz_stock_num = 3 if diff >= 500 else \
                3 if 200 <= diff < 500 else \
                    4 if -200 <= diff < 200 else \
                        5 if -500 <= diff < -200 else \
                            6

        # 选择要启用的选股版本
        g.target_list = {
                            "v1": self.get_stock_list_v1,
                            "v2": self.get_stock_list_v2,
                            "v3": self.get_stock_list_v3,
                        }[self.version](context)[:g.xsz_stock_num]

        log.info(f"[{self.name}] {self.version} 目标持股数: {g.xsz_stock_num} [diff:{str(diff)[:6]}] 目标持仓: {g.target_list}")

        # 卖出不在目标列表中的股票（除昨日涨停股）
        sell_list = [s for s in g.strategy_holdings[1] if s not in g.target_list and s not in g.yesterday_HL_list]
        hold_list = [s for s in g.strategy_holdings[1] if s in g.target_list or s in g.yesterday_HL_list]

        if sell_list:
            hold_list and log.info(f"当前持有 {hold_list}")
            sell_list and log.info(f"计划卖出 {sell_list}")
        for stock in sell_list:
            self.order_target_value_(stock, 0)
        
        # 同步持仓记录（修复止损功能）
        g.strategy_holdings[1] = list(set(self.subportfolio.long_positions.keys()))

    def buy(self, context):
        """小市值买入逻辑"""
        if not g.trading_signal:
            # 空仓期：先清仓所有小市值股票，再买入ETF，保证互斥
            current_positions = list(self.subportfolio.long_positions.keys())
            for stock in current_positions:
                if stock != g.xsz_buy_etf:
                    log.info(f"🤕🤕🤕 空仓期清仓小市值股票 {stock}")
                    self.order_target_value_(stock, 0)
            
            # 然后买入ETF
            if g.xsz_buy_etf not in self.subportfolio.long_positions:
                log.info("小市值清仓时期, 买入ETF")
                self.order_target_value_(g.xsz_buy_etf, context.portfolio.total_value * g.portfolio_value_proportion[1])
            
            # 更新持仓记录
            g.strategy_holdings[1] = list(self.subportfolio.long_positions.keys())
            return

        # 计算可用资金（策略1专用部分）
        strategy_value = context.portfolio.total_value * g.portfolio_value_proportion[1]
        # 应用市场情绪择时仓位调整
        if g.enable_market_sentiment:
            strategy_value *= g.market_sentiment_position_ratio
            
        current_value = sum(
            [pos.value for pos in self.subportfolio.long_positions.values()])
        available_cash = max(0, strategy_value - current_value)

        # 买入新标的
        buy_list = [s for s in g.target_list if s not in g.strategy_holdings[1][:]]
        if buy_list and available_cash > 0:
            cash_per_stock = available_cash / len(buy_list)
            for stock in buy_list:
                self.order_target_value_(stock, cash_per_stock)
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[1] = list(set(self.subportfolio.long_positions.keys()))

    def check_dbl(self, context, end_days=0):
        """大盘顶背离检测"""
        market_index = '399101.XSHE'
        
        # 把第一次9:31执行的给忽略掉, 避免第一次造成干扰
        if not g.dbl and "9:31" in str(context.current_dt.time()):
            return

        def detect_divergence():
            """检测顶背离"""
            fast, slow, sign = 12, 26, 9
            rows = (fast + slow + sign) * 5
            grid = attribute_history(market_index, rows + 10, fields=['close']).dropna()
            if end_days < 0:
                grid = grid.iloc[:end_days]

            if len(grid) < rows:
                return False

            try:
                grid['dif'], grid['dea'], grid['macd'] = mcad(grid.close, fast, slow, sign)

                mask = (grid['macd'] < 0) & (grid['macd'].shift(1) >= 0)
                if mask.sum() < 2:
                    return False

                key2, key1 = mask[mask].index[-2], mask[mask].index[-1]

                price_cond = grid.close[key2] < grid.close[key1]
                dif_cond = grid.dif[key2] > grid.dif[key1] > 0
                macd_cond = grid.macd.iloc[-2] > 0 > grid.macd.iloc[-1]

                if len(grid['dif']) > 20:
                    recent_avg = grid['dif'].iloc[-10:].mean()
                    prev_avg = grid['dif'].iloc[-20:-10].mean()
                    trend_cond = recent_avg < prev_avg
                else:
                    trend_cond = False

                return price_cond and dif_cond and macd_cond and trend_cond

            except Exception as e:
                log.error(f"{market_index} 顶背离检测错误: {e}")
                return False

        # 非小市值只计算判断, 不做仓位处理
        if market_index != '399101.XSHE':
            res = 1 if detect_divergence() else 0
            if res:
                log.info(f"{market_index} 触发顶背离了!!!!! 快跑 !!!!!")
            return res

        if detect_divergence():
            g.dbl.append(1)
            log.info(f"⚠️⚠️⚠️⚠️⚠️ 检测到{market_index}顶背离信号（价格新高但MACD走弱），清仓非涨停股票")

            current_data = get_current_data()

            for stock in g.strategy_holdings[1][:]:
                if current_data[stock].last_price < current_data[stock].high_limit:
                    log.info(f"{stock} 因大盘顶背离清仓（非涨停股）")
                    self.order_target_value_(stock, 0)
        else:
            g.dbl.append(0)

    def check_stoploss(self, context):
        """止盈止损检查（原有逻辑作为保底）"""
        # 先执行ATR动态止损（主要风控）
        if g.enable_atr_stoploss:
            self.check_atr_stoploss(context)
            # ATR止损后同步持仓记录
            g.strategy_holdings[1] = list(set(self.subportfolio.long_positions.keys()))
        
        # 再执行原有固定止损（作为保底）
        if g.run_stoploss:
            current_positions = self.subportfolio.long_positions
            if g.stoploss_strategy in [1, 3]:
                for stock, position in current_positions.items():
                    price = get_current_data()[stock].last_price
                    avg_cost = position.avg_cost
                    if price >= avg_cost * 2:
                        log.info(f"🤑🤑🤑 收益100%止盈,卖出 {stock}")
                        self.order_target_value_(stock, 0)
                    elif price < avg_cost * (1 - g.stoploss_limit):
                        log.info(f"🤬🤬🤬 收益止损,卖出 {stock}")
                        self.order_target_value_(stock, 0)
            if g.stoploss_strategy in [2, 3]:
                stock_df = get_price(security=get_index_stocks('399101.XSHE'),
                                     end_date=context.previous_date,
                                     frequency='daily',
                                     fields=['close', 'open'],
                                     count=1,
                                     panel=False)
                down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
                if down_ratio >= g.stoploss_market:
                    log.info(f"🤡🤡🤡 大盘惨跌,平均降幅 {down_ratio:.2%}")
                    for stock in g.strategy_holdings[1][:]:
                        self.order_target_value_(stock, 0)

    def check_turnover(self, context):
        """换手率异常检测"""
        self.huanshou(context, stock_list=g.strategy_holdings[1][:])

    def huanshou(self, context, stock_list):
        """换手检测"""
        def huanshoulv(_stock, is_avg=False):
            if is_avg:
                end_date = context.previous_date
                df_volume = get_price(_stock, end_date=end_date, frequency='daily', fields=['volume'], count=20)
                df_cap = get_valuation(_stock, end_date=end_date, fields=['circulating_cap'], count=1)
                circulating_cap = df_cap['circulating_cap'].iloc[0] if not df_cap.empty else 0
                if circulating_cap == 0:
                    return 0.0
                df_volume['turnover_ratio'] = df_volume['volume'] / (circulating_cap * 10000)
                return df_volume['turnover_ratio'].mean()
            else:
                date_now = context.current_dt
                df_vol = get_price(_stock, start_date=date_now.date(), end_date=date_now, frequency='1m', fields=['volume'],
                                   skip_paused=False, fq='pre', panel=True, fill_paused=False)
                volume = df_vol['volume'].sum()
                date_pre = context.previous_date
                df_circulating_cap = get_valuation(_stock, end_date=date_pre, fields=['circulating_cap'], count=1)
                circulating_cap = df_circulating_cap['circulating_cap'].iloc[0] if not df_circulating_cap.empty else 0
                if circulating_cap == 0:
                    return 0.0
                turnover_ratio = volume / (circulating_cap * 10000)
                return turnover_ratio

        current_data = get_current_data()
        shrink, expand = 0.003, 0.1

        for stock in stock_list:
            if current_data[stock].paused:
                continue
            if current_data[stock].last_price >= current_data[stock].high_limit * 0.97:
                continue
            position = self.subportfolio.long_positions.get(stock)
            if not position or position.closeable_amount == 0:
                continue
            rt = huanshoulv(stock, False)
            avg = huanshoulv(stock, True)
            if avg == 0:
                continue
            r = rt / avg
            action, icon = '', ''
            if avg < 0.003:
                action, icon = '缩量', '❄️'
            elif rt > expand and r > 2:
                action, icon = '放量', '🔥'
            if action:
                log.info(f"{action} {stock}  换手率:{rt:.2%}  均:{avg:.2%} 倍率:{r:.1f} {icon}")
                self.order_target_value_(stock, 0)

    def check_limit_up(self, context):
        """检查昨日涨停股今日表现"""
        holdings = g.strategy_holdings[1][:]
        if holdings:
            if g.yesterday_HL_list:
                for stock in g.yesterday_HL_list:
                    # 使用 get_current_data() 获取实时数据，避免未来函数问题
                    current_data = get_current_data()
                    if current_data[stock].last_price < current_data[stock].high_limit:
                        log.info(f"🥵🥵🥵 {stock} 涨停打开，卖出")
                        self.order_target_value_(stock, 0)
                    else:
                        log.info(f"🤗🤗🤗 {stock} 继续涨停，继续持有")

    def close_account(self, context):
        """清仓后次日资金可转"""
        if not g.trading_signal:
            # 直接从subportfolio获取当前持仓，不依赖g.strategy_holdings
            current_positions: list[Any] = list(self.subportfolio.long_positions.keys())
            if current_positions and g.xsz_buy_etf not in current_positions:
                for stock in current_positions:
                    log.info(f"🤕🤕🤕 进入清仓期间 卖出 {stock}")
                    self.order_target_value_(stock, 0)
                
                # 更新持仓记录
                g.strategy_holdings[1] = list(self.subportfolio.long_positions.keys())

    def check_defense(self, context):
        """成交额宽度防御检测"""
        # 简化实现，完整逻辑可以后续补充
        if g.defense_signal:
            # 使用 get_current_data() 获取实时数据，避免未来函数问题
            current_data = get_current_data()
            for stock in g.strategy_holdings[1][:]:
                if current_data[stock].last_price < current_data[stock].high_limit:
                    self.order_target_value_(stock, 0)


# 子策略1的调度包装函数


def smallcap_prepare(context):
    """小市值策略准备"""
    g.strategies[1].prepare(context)


def smallcap_sell(context):
    """小市值策略卖出"""
    g.strategies[1].sell(context)


def smallcap_buy(context):
    """小市值策略买入"""
    g.strategies[1].buy(context)


def smallcap_check_dbl(context):
    """小市值策略顶背离检查"""
    g.strategies[1].check_dbl(context)


def smallcap_stoploss(context):
    """小市值策略止损（原有逻辑）"""
    g.strategies[1].check_stoploss(context)


def smallcap_atr_stoploss(context):
    """小市值策略ATR动态止损"""
    if g.enable_atr_stoploss:
        g.strategies[1].check_atr_stoploss(context)
        # 同步持仓记录
        g.strategy_holdings[1] = list(set(g.strategies[1].subportfolio.long_positions.keys()))


def smallcap_check_turnover(context):
    """小市值策略换手率检查"""
    g.strategies[1].check_turnover(context)


def smallcap_check_limit_up(context):
    """小市值策略涨停板检查"""
    g.strategies[1].check_limit_up(context)


def smallcap_close_account(context):
    """小市值策略清仓"""
    g.strategies[1].close_account(context)


def smallcap_check_defense(context):
    """小市值策略防御检查"""
    g.strategies[1].check_defense(context)


# ==============================
# 六、工具函数
# ==============================


def mcad(close, short=12, long=26, m=9):
    """计算MACD指标"""
    def ema(series, n):
        return pd.Series.ewm(series, span=n, min_periods=n - 1, adjust=False).mean()

    dif = ema(close, short) - ema(close, long)
    dea = ema(dif, m)
    return dif, dea, (dif - dea) * 2


def format_stock_code(stock_code):
    """展示优化"""
    try:
        stock_info = get_security_info(stock_code)
    except Exception:
        return f"{stock_code[:6]}"
    return f"{stock_code[:6]}({stock_info.display_name})"


# 记录各策略收益
def make_record(context):
    positions = context.portfolio.positions
    if not positions:
        return
    current_data = get_current_data()
    g.strategy_value_data = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    copy_strategy_value = {
        1: g.strategy_value[1],
        2: g.strategy_value[2],
        3: g.strategy_value[3],
        4: g.strategy_value[4],
        5: g.strategy_value[5],
    }
    for stock, pos in positions.items():
        strategy_id = g.stock_strategy.get(stock, 1)
        current_value = pos.total_amount * current_data[stock].last_price
        cost_value = pos.total_amount * pos.avg_cost
        pnl_value = current_value - cost_value
        copy_strategy_value[strategy_id] += pnl_value
        g.strategy_value_data[strategy_id] += current_value

    if g.portfolio_value_proportion[1]:
        record(小市值=round(copy_strategy_value[1] / g.strategy_starting_cash[1] * 100 - 100, 2))
    if g.portfolio_value_proportion[2]:
        record(ETF反弹=round(copy_strategy_value[2] / g.strategy_starting_cash[2] * 100 - 100, 2))
    if g.portfolio_value_proportion[3]:
        record(ETF轮动=round(copy_strategy_value[3] / g.strategy_starting_cash[3] * 100 - 100, 2))
    if g.portfolio_value_proportion[4]:
        record(白马攻防=round(copy_strategy_value[4] / g.strategy_starting_cash[4] * 100 - 100, 2))
    if g.portfolio_value_proportion[5]:
        record(红利=round(copy_strategy_value[5] / g.strategy_starting_cash[5] * 100 - 100, 2))


# 打印每日收益
def print_summary(context):
    """制表展示每日收益"""
    total_value = round(context.portfolio.total_value, 2)
    current_stocks = context.portfolio.positions
    if not current_stocks:
        log.info(f"🚤🚤🚤🚚🚚 当前总资产: {total_value} 休息ing")
        return

    # 创建表格
    table = PrettyTable([
        " 所属策略 ",
        " 股票代码 ",
        " 股票名称 ",
        " 持仓数量 ",
        " 持仓价格 ",
        " 当前价格 ",
        " 盈亏数额 ",
        " 盈亏比例 ",
        " 股票市值 ",
        " 仓位占比 "
    ])
    table.hrules = prettytable.ALL  # 显示所有水平线

    # 遍历持仓股票
    total_market_value = 0
    for stock in current_stocks:
        current_shares = current_stocks[stock].total_amount
        current_price = round(get_current_data()[stock].last_price, 3)
        avg_cost = round(current_stocks[stock].avg_cost, 3)

        # 计算盈亏比例
        profit_ratio = (current_price - avg_cost) / avg_cost if avg_cost != 0 else 0
        profit_ratio_percent = f"{profit_ratio * 100:.2f}%"
        profit_ratio_percent += f" {'↑' if profit_ratio > 0 else '↓'}"

        # 计算盈亏数额
        profit_amount = round((current_price - avg_cost) * current_shares, 2)

        # 计算市值
        market_value = round(current_shares * current_price, 2)
        total_market_value += market_value

        # 处理股票代码
        stock_code = stock.split(".")[0]

        # 获取策略名称
        strategy_id = g.stock_strategy.get(stock, 1)
        strategy_name = {
            1: "小市值",
            2: "ETF反弹",
            3: "ETF轮动",
            4: "白马攻防",
            5: "红利",
        }.get(strategy_id, "未知")

        # 添加到表格
        table.add_row([
            strategy_name,
            stock_code,
            format_stock_code(stock),
            current_shares,
            avg_cost,
            current_price,
            profit_amount,
            profit_ratio_percent,
            market_value,
            f"{market_value / context.portfolio.total_value * 100:.2f}%"
        ])

    # 策略汇总
    if g.strategy_value_data[1]:
        table.add_row(["小市值", "", "", "", "", "", "", "", f"{g.strategy_value_data[1]:.2f}",
                       f"{g.strategy_value_data[1] / total_value * 100:.2f}%"])
    if g.strategy_value_data[2]:
        table.add_row(["ETF反弹", "", "", "", "", "", "", "", f"{g.strategy_value_data[2]:.2f}",
                       f"{g.strategy_value_data[2] / total_value * 100:.2f}%"])
    if g.strategy_value_data[3]:
        table.add_row(["ETF轮动", "", "", "", "", "", "", "", f"{g.strategy_value_data[3]:.2f}",
                       f"{g.strategy_value_data[3] / total_value * 100:.2f}%"])
    if g.strategy_value_data[4]:
        table.add_row(["白马攻防", "", "", "", "", "", "", "", f"{g.strategy_value_data[4]:.2f}",
                       f"{g.strategy_value_data[4] / total_value * 100:.2f}%"])
    if g.strategy_value_data[5]:
        table.add_row(["红利", "", "", "", "", "", "", "", f"{g.strategy_value_data[5]:.2f}",
                       f"{g.strategy_value_data[5] / total_value * 100:.2f}%"])
    table.add_row(["总市值", "", "", "", "", "", "", "", f"{total_market_value:.2f}", ""])
    table.add_row(["总资产", "", "", "", "", "", "", "", f"{total_value:.2f}", ""])

    # 打印表格
    log.info(f"\n当前总资产\n{table}")


# 由于文件过长，继续添加其他策略代码
# 为节省篇幅，这里添加必要的占位符

# ==============================
# 七、子策略2：ETF反弹策略（10%）- 集成ATR动态止损
# ==============================

class ETF_Rebound_Strategy(Strategy):
    """
    ETF反弹策略（优化版）
    - 捕捉中证2000等指数的短期反弹机会
    - 集成ATR动态止损（10天, 1.5倍, 10%/20%/50%）
    """

    def __init__(self, context, subportfolio_index, name):
        super().__init__(context, subportfolio_index, name)
        self.stock_sum = 1  # 只持有一只ETF
        
        # 初始化ATR服务（ETF反弹策略配置）
        self.init_atr_service(ATRConfig.ETF_REBOUND)
        
        log.info(f"[{self.name}] 初始化完成，ETF池{len(g.etf_pool_2)}只")

    def sell(self, context):
        """ETF反弹策略卖出逻辑"""
        cur_date = str(context.current_dt.date())
        if cur_date <= "2023-10-01":
            return

        g.buy_list = []
        sell_list = []
        sell_for_money_list = []

        # 获取近4日的历史数据
        for etf in g.etf_pool_2:
            df = get_price(etf, end_date=context.previous_date, count=4, frequency='daily', fields=['high', 'close'])
            df = df.reset_index()
            if len(df) < 4:
                continue

            pre_high_max = df['high'].max()
            yestoday_close = df['close'].iloc[-1]

            # 获取当前盘中实时数据
            current_data = get_current_data()
            today_open = current_data[etf].day_open
            today_close = current_data[etf].last_price

            # 买入条件判断，开盘相比最高价下跌2% & 最新价相比开盘价涨1%
            if today_open / pre_high_max < 0.98 and today_close / today_open > 1.01:
                g.buy_list.append(etf)
            # 卖出条件判断，当前价格小于昨日收盘价
            if today_close < yestoday_close:
                sell_list.append(etf)

        # 保留最佳标的
        if g.buy_list:
            g.buy_list.sort(key=lambda x: g.etf_pool_2.index(x))
            selected_etf = g.buy_list[0]
            g.buy_list = [selected_etf]
            current_holdings = g.strategy_holdings[2]
            if current_holdings and g.etf_pool_2.index(current_holdings[0]) < g.etf_pool_2.index(selected_etf):
                sell_for_money_list.append(current_holdings[0])

        for etf in g.strategy_holdings[2]:
            position = self.subportfolio.long_positions.get(etf)
            if position:
                security = etf
                trade_date = position.init_time
                # 检查 init_time 是否为 None
                if trade_date is None:
                    log.warning(f"[{self.name}] {security} 的 init_time 为 None，无法计算持仓天数，跳过")
                    continue
                holding_days = len(get_trade_days(start_date=trade_date, end_date=context.current_dt)) - 1
                if (security in sell_list and holding_days >= g.limit_days) or \
                        (holding_days >= g.n_days) or \
                        (security in sell_for_money_list):
                    log.info(f"[{self.name}] 卖出：{security}，持股{holding_days}天")
                    self.order_target_value_(security, 0)

        if not g.buy_list:
            log.info(f"[{self.name}] 今日无反弹可购买选项")
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[2] = list(set(self.subportfolio.long_positions.keys()))

    def buy(self, context):
        """ETF反弹策略买入逻辑"""
        cur_date = str(context.current_dt.date())
        if cur_date <= "2023-10-01":
            return

        g.buy_list = list(set(g.buy_list) - set(g.strategy_holdings[2]))
        if len(g.buy_list) > 0:
            cash = context.portfolio.total_value * g.portfolio_value_proportion[2]
            # 应用市场情绪择时仓位调整
            if g.enable_market_sentiment:
                cash *= g.market_sentiment_position_ratio
                if g.market_sentiment_position_ratio < 1.0:
                    log.info(f"[{self.name}] 市场情绪调整后目标资金: {cash:.2f}")
                    
            if cash < 100:
                log.warn(f"[{self.name}] cash不足:{context.portfolio.available_cash}")
            else:
                cash = context.portfolio.total_value * g.portfolio_value_proportion[2]
                if g.enable_market_sentiment:
                    cash *= g.market_sentiment_position_ratio
                for etf in g.buy_list:
                    log.info(f"[{self.name}] 符合策略2买入条件：{etf}")
                    self.order_target_value_(etf, cash)
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[2] = list(set(self.subportfolio.long_positions.keys()))

    def capital_balance(self, context):
        """资金平衡逻辑"""
        cur_date = str(context.current_dt.date())
        # 基于首次进行检测
        if cur_date < "2023-09-28" and g.strategy_ETF_2000_proportion_reset is None:
            g.portfolio_value_proportion[3] += g.strategy_ETF_2000_proportion  # ETF轮动增加ETF反弹资金
            g.portfolio_value_proportion[2] = 0  # ETF反弹设为0
            g.strategy_ETF_2000_proportion_reset = False
        # 到达既定时间后进行拨正原始比例
        elif cur_date >= "2023-09-28" and g.strategy_ETF_2000_proportion_reset is False:
            strategy_total_value = context.portfolio.total_value * g.strategy_ETF_2000_proportion
            # 检测ETF轮动是否有持仓, 如果有的话就要吐出来还给ETF反弹
            if g.strategy_holdings[3]:
                cur_etf = g.strategy_holdings[3]
                if cur_etf in context.subportfolios[3].long_positions:
                    # 使用 order_target_value_ 以确保持仓的 init_time 正确设置
                    current_value = context.subportfolios[3].long_positions[cur_etf].value
                    target_value = max(0, current_value - strategy_total_value)
                    o = self.order_target_value_(cur_etf, target_value)
                    if o:
                        log.info(f"[{self.name}] ETF反弹预留资金转移 {cur_etf}")
            g.portfolio_value_proportion[3] -= g.strategy_ETF_2000_proportion  # ETF轮动减少ETF反弹资金
            g.portfolio_value_proportion[2] = g.strategy_ETF_2000_proportion  # ETF反弹恢复原值
            g.strategy_ETF_2000_proportion_reset = True


# 子策略2的调度包装函数


def etf_rebound_capital_balance(context):
    """ETF反弹策略资金平衡"""
    g.strategies[2].capital_balance(context)


def etf_rebound_sell(context):
    """ETF反弹策略卖出"""
    g.strategies[2].sell(context)


def etf_rebound_buy(context):
    """ETF反弹策略买入"""
    g.strategies[2].buy(context)


def etf_rebound_atr_stoploss(context):
    """ETF反弹策略ATR动态止损"""
    if g.enable_atr_stoploss:
        g.strategies[2].check_atr_stoploss(context)
        g.strategy_holdings[2] = list(set(g.strategies[2].subportfolio.long_positions.keys()))


# ==============================
# 八、子策略3：ETF轮动策略（30%）- 集成ATR动态止损
# ==============================

class ETF_Rotation_Strategy(Strategy):
    """
    ETF轮动策略（优化版）
    - 基于动量和RSRS等多维度筛选表现最好的ETF
    - 低换手率，趋势跟踪
    - 集成ATR动态止损（10天, 1.5倍, 10%/30%/80%）
    """

    def __init__(self, context, subportfolio_index, name):
        super().__init__(context, subportfolio_index, name)
        self.stock_sum = 1  # 只持有一只ETF
        self.etf_pool = g.etf_pool_3
        self.m_days = g.m_days
        self.m_score = g.m_score
        self.volume_lookback = 7
        self.volume_threshold = 2.0
        self.ma_filter_days = 20
        self.last_ma_log_date = None
        self.last_ma_detail_log_date = None
        # RSRS Beta缓存（用于优化性能）
        self.rsrs_beta_cache = {}
        self.rsrs_beta_date = None
        
        # 初始化ATR服务（ETF轮动策略配置）
        self.init_atr_service(ATRConfig.ETF_ROTATION)

        log.info(f"[{self.name}] 初始化完成，ETF池{len(self.etf_pool)}只，动量天数{self.m_days}")

    def preload_etf_data(self, context, days=250):
        """批量预加载所有ETF的历史数据（性能优化）"""
        log.info(f"[{self.name}] 正在批量加载 {len(self.etf_pool)} 个ETF的历史数据（{days}天）...")
        data_cache = {}
        current_data = get_current_data()

        for etf in self.etf_pool:
            try:
                hist_data = attribute_history(etf, days, "1d", ["close", "high", "low", "volume"])
                if not hist_data.empty:
                    current_price = current_data[etf].last_price
                    data_cache[etf] = {
                        'hist': hist_data,
                        'current_price': current_price
                    }
            except Exception as e:
                log.warning(f"[{self.name}] 加载{etf}数据失败: {e}")
                continue

        log.info(f"[{self.name}] 数据加载完成，成功加载 {len(data_cache)} 个ETF的数据")
        return data_cache

    def compute_momentum(self, context, etf_list, data_cache):
        """计算ETF动量得分"""
        if not etf_list:
            return pd.DataFrame(columns=["annualized_returns", "r2", "score"])

        data = pd.DataFrame(
            index=etf_list,
            columns=["annualized_returns", "r2", "score"],
        )

        for etf in etf_list:
            try:
                if etf not in data_cache:
                    continue

                cached_data = data_cache[etf]
                hist_data = cached_data['hist']
                current_price = cached_data['current_price']

                if hist_data.empty or len(hist_data) < self.m_days:
                    continue

                recent_data = hist_data.tail(self.m_days)
                prices = np.append(recent_data["close"].values, current_price)
                if len(prices) < 5:
                    continue

                log_prices = np.log(prices)
                x_values = np.arange(len(log_prices))
                weights = np.linspace(1, 2, len(log_prices))

                slope, intercept = np.polyfit(x_values, log_prices, 1, w=weights)
                annualized_return = math.exp(slope * 250) - 1
                data.loc[etf, "annualized_returns"] = annualized_return

                ss_res = np.sum(weights * (log_prices - (slope * x_values + intercept)) ** 2)
                ss_tot = np.sum(weights * (log_prices - np.mean(log_prices)) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                data.loc[etf, "r2"] = r2

                momentum_score = annualized_return * r2
                data.loc[etf, "score"] = momentum_score

                if min(prices[-1] / prices[-2],
                       prices[-2] / prices[-3],
                       prices[-3] / prices[-4]) < 0.97:
                    data.loc[etf, "score"] = 0

            except Exception as e:
                log.warning(f"[{self.name}] 计算 {etf} 动量失败: {e}")
                continue

        return data

    def filter_below_ma(self, context, stocks, days=20, log_details=True):
        """过滤低于均线的ETF"""
        if not stocks:
            return []

        current_data = get_current_data()
        filtered = []

        for stock in stocks:
            try:
                hist = attribute_history(stock, days, "1d", ["close"])
                if len(hist) < days:
                    continue

                ma_n = hist["close"].mean()
                price = current_data[stock].last_price

                if price >= ma_n:
                    filtered.append(stock)
                else:
                    if log_details:
                        log.debug(f"[{self.name}] 过滤 {stock}: 当前价 {price:.2f} < {days}日均价 {ma_n:.2f}")
            except Exception as e:
                if log_details:
                    log.warning(f"[{self.name}] 均线过滤失败 {stock}: {e}")

        return filtered

    def get_single_score(self, context, etf, data_cache):
        """获取单只ETF的动量得分"""
        df = self.compute_momentum(context, [etf], data_cache)
        if etf in df.index:
            return df.loc[etf, "score"]
        return None

    def momentum_filter(self, context, data_cache):
        """动量过滤"""
        stocks = self.etf_pool
        today = context.current_dt.date()
        log_details = self.last_ma_detail_log_date != today
        stocks = self.filter_below_ma(context, stocks, self.ma_filter_days, log_details)
        if self.last_ma_log_date != today:
            log.debug(f"[{self.name}] 均线过滤后剩余 {len(stocks)} / {len(self.etf_pool)}")
            self.last_ma_log_date = today
        if log_details:
            self.last_ma_detail_log_date = today

        if not stocks:
            return []

        data = self.compute_momentum(context, stocks, data_cache)
        data = data.query("0 < score < 5").sort_values(by="score", ascending=False)
        return data.index.tolist()

    def filter_rsrs(self, stock_list, data_cache, context):
        """
        RSRS + 均线过滤（使用缓存数据）

        参数:
            stock_list: 股票列表
            data_cache: 预加载的数据缓存
            context: 策略上下文
        """
        log.info(f"[{self.name}] RSRS+均线过滤 " + "*" * 60)

        def _get_slope(security, days=18):
            """计算斜率（使用缓存数据）"""
            try:
                if security not in data_cache:
                    return None

                hist_data = data_cache[security]['hist']
                if hist_data.empty or len(hist_data) < days:
                    return None

                recent_data = hist_data.tail(days)
                slope = np.polyfit(recent_data['low'].values, recent_data['high'].values, 1)[0]
                return slope
            except Exception as e:
                log.warning(f"[{self.name}] 计算{security} RSRS斜率失败: {e}")
                return None

        def _get_beta(security, lookback_days=250, window=20):
            """计算阈值（使用缓存数据 + Beta缓存机制）"""
            try:
                # 检查Beta缓存
                current_date = context.current_dt.date()
                if self.rsrs_beta_date == current_date and security in self.rsrs_beta_cache:
                    return self.rsrs_beta_cache[security]

                # 从数据缓存获取历史数据
                if security not in data_cache:
                    return None

                hist_data = data_cache[security]['hist']
                if hist_data.empty or len(hist_data) < lookback_days:
                    return None

                slope_list = []
                for i in range(len(hist_data) - window + 1):
                    window_data = hist_data.iloc[i:i + window]
                    low_values = window_data['low'].values
                    high_values = window_data['high'].values

                    if len(low_values) < window or len(high_values) < window:
                        continue
                    if np.any(np.isnan(low_values)) or np.any(np.isnan(high_values)):
                        continue
                    if np.any(np.isinf(low_values)) or np.any(np.isinf(high_values)):
                        continue
                    if np.std(low_values) == 0 or np.std(high_values) == 0:
                        continue

                    slope = np.polyfit(low_values, high_values, 1)[0]
                    slope_list.append(slope)

                if len(slope_list) < 2:
                    return None

                mean_slope = np.mean(slope_list)
                std_slope = np.std(slope_list)
                beta = mean_slope - 2 * std_slope

                # 更新Beta缓存
                self.rsrs_beta_cache[security] = beta
                self.rsrs_beta_date = current_date

                return beta
            except Exception as e:
                log.warning(f"[{self.name}] 计算{security} RSRS Beta失败: {e}")
                return None

        def _check_with_strength(security):
            """计算强度"""
            _slope = _get_slope(security)
            _beta = _get_beta(security)
            if _slope is None or _beta is None:
                return None, 0
            _strength = (_slope - _beta) / abs(_beta) if _beta != 0 else 0
            return _slope > _beta, _strength

        def _check_above_ma(security, days=20):
            """计算均值（使用缓存数据）"""
            try:
                if security not in data_cache:
                    return False

                hist_data = data_cache[security]['hist']
                if len(hist_data) < days:
                    return False

                recent_data = hist_data.tail(days)
                current_price = data_cache[security]['current_price']
                return current_price >= recent_data["close"].mean()
            except Exception as e:
                log.warning(f"[{self.name}] 计算{security} {days}日均线失败: {e}")
                return False

        res = []
        for stock in stock_list:
            stock_pass, stock_strength = _check_with_strength(stock)
            above_ma_5 = _check_above_ma(stock, 5)
            above_ma_10 = _check_above_ma(stock, 10)
            flag = "❌"
            if stock_pass:
                if stock_strength > 0.15:
                    flag = "✔️"
                    res.append(stock)
                elif stock_strength > 0.03 and above_ma_5:
                    flag = "✔️"
                    res.append(stock)
                elif above_ma_10:
                    flag = "✔️"
                    res.append(stock)
            log.info(f"{flag}  {stock} "
                  f"pass:{stock_pass}  strength:{stock_strength:.2f} "
                  f"ma5: {above_ma_5}  ma10: {above_ma_10}")
        return res

    def calculate_rsi(self, code, period=14):
        """计算RSI指标"""
        try:
            df = attribute_history(code, 125, '1d', ['close'], skip_paused=True, df=True, fq='pre')
            if df.empty:
                return 100  # 返回100表示超买状态，避免买入
            prices = df['close'].values
            deltas = np.diff(prices)
            seed = deltas[:period + 1]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            if down == 0:
                return 100
            rs = up / down
            rsi = 100 - 100 / (1 + rs)
            return rsi
        except Exception as e:
            log.warning(f"[{self.name}] 计算{code} RSI失败: {e}")
            return 100

    def filter_volume_fixed(self, context, stock_list, days=7, volume_threshold=2):
        """
        过滤成交量异常的ETF（修复未来函数问题）

        使用历史日数据而非当日分钟数据，避免未来函数
        """
        log.info(f"[{self.name}] ETF 异常成交量检测" + "*" * 60)

        def _get_volume_ratio(security):
            """计算成交量比率"""
            try:
                hist_data = attribute_history(security, days, '1d', ['volume'])
                if hist_data.empty or len(hist_data) < days:
                    return

                avg_volume = hist_data['volume'].mean()
                
                # 使用历史最新日的成交量，避免未来函数
                if not hist_data.empty:
                    current_volume = hist_data['volume'].iloc[-1]
                else:
                    return

                _volume_ratio = current_volume / avg_volume
                # 检测到异常，返回异常倍数
                if _volume_ratio > volume_threshold:
                    log.info(f"❌ {security} 成交量较近{days}日均值 x{_volume_ratio:.2f}")
                    return _volume_ratio
                log.info(f"✔️ {security} 成交量较近{days}日均值 x{_volume_ratio:.2f}")

            except Exception as e:
                log.warning(f"⭕ 检查{security}成交量失败: {e}")
                return

        res = []
        for stock in stock_list:
            ratio = _get_volume_ratio(stock)
            if not ratio:
                res.append(stock)

        return res

    def cal_cur_to_open_ratio(self, security):
        """计算最新价格对比开盘价格的比值"""
        current_data = get_current_data()
        last_price = current_data[security].last_price
        day_open = current_data[security].day_open
        return (last_price - day_open) / day_open

    def get_etf_rank(self, context, etf_pool):
        """
        ETF五重过滤排名（优化版 - 使用数据缓存）

        优化的过滤流程：
        1. 跌幅检测（简单快速）
        2. 动量得分过滤（相对简单）
        3. RSRS+均线过滤（最复杂，后置以减少计算量）
        4. 成交量异常过滤（使用修复后的方法）
        5. RSI过滤（最后）
        """
        # ===== 性能优化：批量预加载所有ETF的历史数据 =====
        data_cache = self.preload_etf_data(context, days=250)
        rank_list = []
        current_data = get_current_data()

        # 第一重：过滤近3日跌幅超过5%的ETF
        log.info(f"[{self.name}] ETF 跌幅检测 " + "*" * 60)
        for etf in etf_pool:
            if etf not in data_cache:
                log.info(f"❌ {etf} 数据加载失败, 已排除")
                continue

            cached_data = data_cache[etf]
            hist_data = cached_data['hist']
            current_price = cached_data['current_price']

            # 使用缓存数据进行跌幅检测
            if len(hist_data) < self.m_days:
                log.info(f"❌ {etf} 历史数据不足, 已排除")
                continue

            recent_closes = hist_data["close"].tail(3).values
            prices = np.append(recent_closes, current_price)

            if min(prices[-1] / prices[-2],
                   prices[-2] / prices[-3],
                   prices[-3] / prices[-4]) < 0.95:
                log.info(f"❌ {etf} 近3日跌幅超过5%, 已排除")
                continue

            # 日内止损, 距离开盘暴跌的不进行买入
            if g.enable_stop_loss_by_cur_day:
                ratio = self.cal_cur_to_open_ratio(etf)
                if ratio <= g.stoploss_limit_by_cur_day:
                    log.info(f"❌ {etf} 进入跌幅达到 {ratio * 100:.2f}%, 已排除")
                    continue

            log.info(f"✔️ {etf} 检测通过")
            rank_list.append(etf)

        # 第二重：动量得分过滤 (0 ~ 5) - 提前，减少后续复杂计算
        rank_list = self.filter_moment_rank_rank(context, rank_list, data_cache)

        # 第三重：RSRS + 均线过滤 - 最复杂，后置
        rank_list = self.filter_rsrs(rank_list, data_cache, context)

        # 第四重：成交量异常过滤 - 使用修复后的方法
        rank_list = self.filter_volume_fixed(context, rank_list)

        # 第五重：RSI过滤
        res_list = []
        for etf in rank_list:
            # 过热的不买入
            rsi = self.calculate_rsi(etf)
            if rsi < 80:
                log.debug(f"[{self.name}] {etf} RSI={rsi:.2f} < 80，通过")
                res_list.append(etf)
            else:
                log.debug(f"[{self.name}] {etf} RSI={rsi:.2f} >= 80，过热排除")

        return res_list

    def filter_moment_rank_rank(self, context, stock_pool, data_cache, show_print=True):
        """
        动量得分计算（使用缓存数据）

        参数:
            stock_pool: 股票列表
            data_cache: 预加载的数据缓存
            show_print: 是否打印结果
        """
        log.info(f"[{self.name}] 计算动量得分" + "*" * 60)

        scores_data = pd.DataFrame(index=stock_pool, columns=["annualized_returns", "r2", "score"])
        print_info = {}

        for code in stock_pool:
            try:
                # 从缓存中获取数据
                if code not in data_cache:
                    continue

                cached_data = data_cache[code]
                hist_data = cached_data['hist']
                current_price = cached_data['current_price']

                if hist_data.empty or len(hist_data) < self.m_days:
                    continue

                # 使用最近days天的数据
                recent_data = hist_data.tail(self.m_days)
                prices = np.append(recent_data["close"].values, current_price)
                log_prices = np.log(prices)
                x_values = np.arange(len(log_prices))
                weights = np.linspace(1, 2, len(log_prices))

                slope, intercept = np.polyfit(x_values, log_prices, 1, w=weights)
                annualized_return = math.exp(slope * 250) - 1
                scores_data.loc[code, "annualized_returns"] = annualized_return

                ss_res = np.sum(weights * (log_prices - (slope * x_values + intercept)) ** 2)
                ss_tot = np.sum(weights * (log_prices - np.mean(log_prices)) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                scores_data.loc[code, "r2"] = r2

                momentum_score = annualized_return * r2
                scores_data.loc[code, "score"] = momentum_score

                if min(prices[-1] / prices[-2],
                       prices[-2] / prices[-3],
                       prices[-3] / prices[-4]) < 0.97:
                    scores_data.loc[code, "score"] = 0
                print_info[code] = scores_data.loc[code, "score"]

            except Exception as e:
                log.warning(f"[{self.name}] 计算{code}动量得分失败: {e}")
                scores_data.loc[code, "score"] = 0

        valid_etfs = scores_data[(scores_data['score'] > 0) & (scores_data['score'] < self.m_score)] \
            .sort_values("score", ascending=False)
        rank_list = valid_etfs.index.tolist()
        if show_print and rank_list:
            for i in rank_list:
                log.info(f"[{self.name}] {i} ({print_info[i]:.4f})")
        return rank_list

    def morning_report(self, context):
        """ETF动量晨报"""
        data_cache = self.preload_etf_data(context, days=250)
        data = self.compute_momentum(context, self.etf_pool, data_cache)
        if data.empty:
            log.info(f"[{self.name}] 动量晨报：无数据")
            return

        data = data.sort_values(by="score", ascending=False)
        current_data = get_current_data()

        log.info("=" * 40 + f" [{self.name}] ETF动量晨报 " + "=" * 40)
        count = 0
        for code, row in data.iterrows():
            score = row.get("score")
            if pd.isna(score) or score <= 0:
                continue

            try:
                name = get_security_info(code).display_name
            except Exception:
                name = current_data[code].name if code in current_data else ""

            score_str = f"{score:.4f}" if score is not None else "N/A"
            annual_return = row.get("annualized_returns", 0)
            r2 = row.get("r2", 0)

            log.info(f"{code} | {name:10} | 动量得分: {score_str:8} | 年化收益: {annual_return:6.2%} | R²: {r2:.3f}")
            count += 1
            if count >= 10:
                break
        log.info("=" * 40 + " 晨报结束 " + "=" * 40)

    def sell(self, context):
        """ETF轮动策略卖出逻辑"""
        log.info(f"[{self.name}] 开始调仓")

        # 获取动量最高的ETF（使用完整的五重过滤流程）
        rank_df = self.get_etf_rank(context, self.etf_pool)

        # 选不出来合适的就清仓
        if not rank_df:
            log.info(f"[{self.name}] ETF轮动没有一个能打的, 清仓当前持仓")
            subpf = self.subportfolio
            hold_list = list(subpf.long_positions.keys())
            for stock in hold_list:
                log.info(f"[{self.name}] 卖出 {stock}")
                self.order_target_value_(stock, 0)
            g.buy_etf = None
            g.strategy_holdings[3] = []
            return

        targets = rank_df[:self.stock_sum]
        log.info(f"[{self.name}] 目标ETF: {targets}")

        subpf = self.subportfolio
        current_data = get_current_data()
        hold_list = list(subpf.long_positions.keys())

        # 卖出不在目标列表的ETF
        for stock in hold_list:
            if stock not in targets:
                log.info(f"[{self.name}] 卖出 {stock}")
                self.order_target_value_(stock, 0)

        g.buy_etf = targets[0] if targets else None
        # 同步持仓记录（修复日内止损功能）
        g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))

    def buy(self, context):
        """ETF轮动策略买入逻辑"""
        if g.buy_etf:
            strategy_cash = context.portfolio.total_value * g.portfolio_value_proportion[3]
            # 应用市场情绪择时仓位调整
            if g.enable_market_sentiment:
                strategy_cash *= g.market_sentiment_position_ratio
                if g.market_sentiment_position_ratio < 1.0:
                    log.info(f"[{self.name}] 市场情绪调整后目标资金: {strategy_cash:.2f}")
            self.order_target_value_(g.buy_etf, strategy_cash)
            log.info(f"[{self.name}] 买入目标ETF: {g.buy_etf}")
        # 同步持仓记录（修复日内止损功能）
        g.strategy_holdings[3] = list(set(g.strategy_holdings[3]))

    def stop_loss_intraday(self, context):
        """ETF轮动日内止损检测（可选，保留作为补充）"""
        holdings = set(g.strategy_holdings[3])
        ratio = g.stoploss_limit_by_cur_day

        for stock in holdings:
            try:
                current_data = get_current_data()
                last_price = current_data[stock].last_price
                day_open = current_data[stock].day_open

                if day_open > 0:
                    cur_ratio = (last_price - day_open) / day_open
                    if cur_ratio <= ratio:
                        log.info(f"[{self.name}] {stock} 距离开盘跌幅 {cur_ratio * 100:.2f}% 清仓处理")
                        self.order_target_value_(stock, 0)
            except Exception as e:
                log.warning(f"[{self.name}] 日内止损检测失败 {stock}: {e}")


# 子策略3的调度包装函数


def etf_rotation_sell(context):
    """ETF轮动策略卖出"""
    g.strategies[3].sell(context)


def etf_rotation_buy(context):
    """ETF轮动策略买入"""
    g.strategies[3].buy(context)


def etf_rotation_atr_stoploss(context):
    """ETF轮动策略ATR动态止损"""
    if g.enable_atr_stoploss:
        g.strategies[3].check_atr_stoploss(context)
        g.strategy_holdings[3] = list(set(g.strategies[3].subportfolio.long_positions.keys()))


def etf_rotation_stoploss_intraday(context):
    """ETF轮动策略日内止损（可选）"""
    g.strategies[3].stop_loss_intraday(context)


# ==============================
# 九、子策略4：白马攻防策略（10%）- 集成ATR动态止损
# ==============================

class WhiteHorse_Strategy(Strategy):
    """
    白马攻防策略（优化版）
    - 根据市场温度选择高ROE/ROA的白马股
    - 价值投资，市场温度感知
    - 集成ATR动态止损（14天, 2.0倍, 15%/30%/60%）
    """

    def __init__(self, context, subportfolio_index, name):
        super().__init__(context, subportfolio_index, name)
        self.stock_num = g.stock_num_2
        
        # 初始化ATR服务（白马攻防策略配置）
        self.init_atr_service(ATRConfig.WHITEHORSE)
        
        log.info(f"[{self.name}] 初始化完成，目标持股数{self.stock_num}只")

    def cal_market_temperature(self, context):
        """市场温度判断"""
        if not hasattr(g, 'market_temperature'):
            long_index300 = list(attribute_history('000300.XSHG', 220 * 3, '1d', ('close',), df=False)['close'])
            g.market_temperature = 'cold'
            for back_day in range(220, len(long_index300)):
                index300 = long_index300[back_day - 220:back_day]
                market_height = (np.mean(index300[-5:]) - min(index300)) / (max(index300) - min(index300))
                if market_height < 0.20:
                    g.market_temperature = "cold"
                elif market_height > 0.80:
                    g.market_temperature = "hot"
                elif max(index300[-60:]) / min(index300) > 1.20:
                    g.market_temperature = "warm"

        index300 = attribute_history('000300.XSHG', 220, '1d', ('close',), df=True) \
            .drop(pd.to_datetime("2024-10-08"), errors='ignore')
        index300 = index300['close'].tolist()
        market_height = (np.mean(index300[-5:]) - min(index300)) / (max(index300) - min(index300))
        if market_height < 0.20:
            g.market_temperature = "cold"
        elif index300[-1] == min(index300):
            g.market_temperature = "cold"
        elif market_height > 0.90:
            g.market_temperature = "hot"
        elif index300[-1] == max(index300):
            g.market_temperature = "hot"
        elif max(index300[-60:]) / min(index300) > 1.20:
            g.market_temperature = "warm"

    def before_market_open(self, context):
        """开盘前运行函数"""
        self.cal_market_temperature(context)
        g.check_out_lists = []
        current_data = get_current_data()
        all_stocks = get_index_stocks("000300.XSHG")

        # 过滤创业板、ST、停牌、当日涨停
        all_stocks = [stock for stock in all_stocks if not (
                (current_data[stock].last_price > round(
                    context.portfolio.total_value * g.portfolio_value_proportion[1] * 0.95 / self.stock_num / 100,
                    2)) or
                (current_data[stock].day_open == current_data[stock].high_limit) or
                (current_data[stock].day_open == current_data[stock].low_limit) or
                current_data[stock].paused or
                current_data[stock].is_st or
                ('ST' in current_data[stock].name) or
                ('*' in current_data[stock].name) or
                ('退' in current_data[stock].name) or
                (stock.startswith('30')) or
                (stock.startswith('68')) or
                (stock.startswith('8')) or
                (stock.startswith('4'))
        )]

        last_prices = history(1, unit='1d', field='close', security_list=all_stocks)
        all_stocks = [stock for stock in all_stocks if last_prices[stock][-1] <= 100]

        q = None
        if g.market_temperature == "cold":
            q = query(
                valuation.code,
                indicator.roe,
                indicator.roa
            ).filter(
                valuation.pb_ratio > 0,
                valuation.pb_ratio < 1,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 0,
                cash_flow.subtotal_operate_cash_inflow / indicator.adjusted_profit > 2.0,
                indicator.inc_return > 1.5,
                indicator.inc_net_profit_year_on_year > -15,
                valuation.code.in_(all_stocks)
            ).order_by(
                (indicator.roa / valuation.pb_ratio).desc()
            ).limit(50)
        elif g.market_temperature == "warm":
            q = query(
                valuation.code,
                indicator.roe,
                indicator.roa
            ).filter(
                valuation.pb_ratio > 0,
                valuation.pb_ratio < 1,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 0,
                cash_flow.subtotal_operate_cash_inflow / indicator.adjusted_profit > 1.0,
                indicator.inc_return > 2.0,
                indicator.inc_net_profit_year_on_year > 0,
                valuation.code.in_(all_stocks)
            ).order_by(
                (indicator.roa / valuation.pb_ratio).desc()
            ).limit(50)
        elif g.market_temperature == "hot":
            q = query(
                valuation.code,
                indicator.roe,
                indicator.roa
            ).filter(
                valuation.pb_ratio > 3,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 0,
                cash_flow.subtotal_operate_cash_inflow / indicator.adjusted_profit > 0.5,
                indicator.inc_return > 3.0,
                indicator.inc_net_profit_year_on_year > 20,
                valuation.code.in_(all_stocks)
            ).order_by(
                indicator.roa.desc()
            ).limit(50)

        df = get_fundamentals(q)
        df.index = df['code'].values

        # 按照因子给股票排序
        roe_inv_rank = df['roe'].rank(ascending=False)
        roa_inv_rank = df['roa'].rank(ascending=False)

        df['point'] = (g.roe * roe_inv_rank + g.roa * roa_inv_rank)
        df = df.sort_values(by='point')

        check_out_lists = list(df.code)

        # 动量趋势过滤
        check_out_lists2 = self.moment_rank(check_out_lists, 25, -1.0, 10.5)
        check_out_lists = [x for x in check_out_lists if x in check_out_lists2]
        g.check_out_lists = check_out_lists[:self.stock_num]

        log.info(f"[{self.name}] 今日市场温度：{g.market_temperature}")
        log.info(f"[{self.name}] 今日白马股票池：{g.check_out_lists}")

    def moment_rank(self, stock_pool, days, ll, hh):
        """动量计算"""
        def mom(_stock):
            y = np.log(attribute_history(_stock, days, '1d', ['close'], df=False)['close'])
            n = len(y)
            x = np.arange(n)
            weights = np.linspace(1, 2, n)
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.pow(math.exp(slope), 250) - 1
            residuals = y - (slope * x + intercept)
            weighted_residuals = weights * residuals ** 2
            r_squared = 1 - (np.sum(weighted_residuals) / np.sum(weights * (y - np.mean(y)) ** 2))
            return annualized_returns * r_squared

        score_list = []
        for stock in stock_pool:
            score = mom(stock)
            score_list.append(score)

        df = pd.DataFrame(index=stock_pool, data={'score': score_list})
        df = df.sort_values(by='score', ascending=False)
        df = df[(df['score'] > ll) & (df['score'] < hh)]
        rank_list = list(df.index)
        return rank_list

    def adjust_position(self, context):
        """调仓逻辑"""
        # 市场情绪择时：情绪不佳时暂停调仓
        if g.enable_market_sentiment and g.market_sentiment_position_ratio < 0.5:
            log.warning(f"[{self.name}] 市场情绪不佳（评分{g.market_sentiment_score:.2f}），暂停调仓")
            return
            
        if not g.check_out_lists:
            self.before_market_open(context)

        buy_stocks = g.check_out_lists
        log.info(f"[{self.name}] 目标调仓: {buy_stocks}")

        # 卖出不在目标列表中的股票
        for stock in g.strategy_holdings[4][:]:
            current_data = get_current_data()
            if stock not in buy_stocks:
                if current_data[stock].last_price >= current_data[stock].high_limit:
                    continue
                self.order_target_value_(stock, 0)
                log.info(f"[{self.name}] 白马策略调出: {stock}")

        # 计算可用资金（应用市场情绪择时）
        strategy_value = context.portfolio.total_value * g.portfolio_value_proportion[4]
        if g.enable_market_sentiment:
            strategy_value *= g.market_sentiment_position_ratio
            if g.market_sentiment_position_ratio < 1.0:
                log.info(f"[{self.name}] 市场情绪调整后目标资金: {strategy_value:.2f}")
                
        # 买入新标的
        position_count = len([s for s in self.subportfolio.long_positions.keys()])
        if len(buy_stocks) > position_count:
            value = strategy_value / self.stock_num
            for stock in buy_stocks:
                if stock not in g.strategy_holdings[4]:
                    self.order_target_value_(stock, value)
                    if len(g.strategy_holdings[4]) >= self.stock_num:
                        break
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[4] = list(set(self.subportfolio.long_positions.keys()))


# 子策略4的调度包装函数


def whitehorse_before_market_open(context):
    """白马攻防策略开盘前选股"""
    g.strategies[4].before_market_open(context)


def whitehorse_adjust_position(context):
    """白马攻防策略调仓"""
    g.strategies[4].adjust_position(context)


def whitehorse_atr_stoploss(context):
    """白马攻防策略ATR动态止损"""
    if g.enable_atr_stoploss:
        g.strategies[4].check_atr_stoploss(context)
        g.strategy_holdings[4] = list(set(g.strategies[4].subportfolio.long_positions.keys()))


# ==============================
# 十、子策略5：红利策略（15%）- 集成ATR动态止损
# ==============================

class Dividend_Strategy(Strategy):
    """
    红利策略（优化版）
    - 分为红利低波和红利价值两个子策略
    - 高股息、低波动、稳健增长
    - 集成ATR动态止损（20天, 2.5倍, 10%/25%/50%）
    """

    def __init__(self, context, subportfolio_index, name):
        super().__init__(context, subportfolio_index, name)
        self.target_num = g.target_num  # [红利低波数量, 红利价值数量]
        
        # 初始化ATR服务（红利策略配置）
        self.init_atr_service(ATRConfig.DIVIDEND)
        
        log.info(f"[{self.name}] 初始化完成，目标持股数{sum(self.target_num)}只")

    def prepare_stock_list(self, context):
        """准备股票池"""
        # 获取昨日涨停列表
        g.high_limit_list = []
        if g.strategy_holdings[5]:
            df = get_price(g.strategy_holdings[5],
                           end_date=context.previous_date,
                           fields=['close', 'high_limit', 'low_limit'],
                           frequency='daily',
                           count=1,
                           panel=False,
                           fill_paused=False)
            g.high_limit_list = list(df[df['close'] == df['high_limit']].code)

    def get_stock_list(self, context):
        """选股逻辑"""
        # 市场情绪择时：情绪不佳时暂停选股
        if g.enable_market_sentiment and g.market_sentiment_position_ratio < 0.5:
            log.warning(f"[{self.name}] 市场情绪不佳（评分{g.market_sentiment_score:.2f}），暂停选股")
            g.buy_df = pd.DataFrame(index=[], columns=['name', 'price', 'amount', 'value'])
            return
            
        # 基础信息
        g.buy_df = pd.DataFrame(index=[], columns=['name', 'price', 'amount', 'value'])
        yesterday = str(context.previous_date)
        today = context.current_dt

        # 初始过滤
        initial_list = get_all_securities('stock', today).index.tolist()
        initial_list = self.filter_new_stock(context, initial_list)
        initial_list = self.filter_kcb_stock(initial_list)
        initial_list = self.filter_st_stock(initial_list)
        initial_list = self.filter_paused_stock(initial_list)

        # 红利低波
        stock_list = initial_list
        stock_list = self.get_dividend_ratio_filter_list(context, stock_list, False, 0.00, 0.10, 0.03)
        stock_list = self.get_factor_filter_list(context, stock_list, 'beta', True, 0.00, 0.50)
        HLDB_list = stock_list[:min(self.target_num[0], len(stock_list))]

        # 红利价值
        stock_list = initial_list
        df = get_fundamentals(query(
            valuation.code,
        ).filter(
            valuation.code.in_(stock_list),
            valuation.pe_ratio.between(5, 50),
            indicator.inc_return.between(5, 100),
            indicator.inc_total_revenue_year_on_year.between(5, 100),
            indicator.inc_net_profit_year_on_year.between(10, 100),
        ))
        stock_list = list(df.code)
        stock_list = self.get_dividend_ratio_filter_list(context, stock_list, False, 0.00, 0.10, 0.03)
        HLJZ_list = stock_list[:min(self.target_num[1], len(stock_list))]

        # 截取不超过最大持仓数的股票量
        target_list = list(set(HLDB_list).union(set(HLJZ_list)))
        g.sell_list = [s for s in g.strategy_holdings[5] if s not in target_list and s not in g.high_limit_list]
        buy_list = [s for s in target_list if s not in g.strategy_holdings[5]]

        # 计算下单价格与数量（应用市场情绪择时）
        strategy_value = context.portfolio.total_value * g.portfolio_value_proportion[5]
        if g.enable_market_sentiment:
            strategy_value *= g.market_sentiment_position_ratio
            if g.market_sentiment_position_ratio < 1.0:
                log.info(f"[{self.name}] 市场情绪调整后目标资金: {strategy_value:.2f}")
                
        current_value = sum(
            [pos.value for pos in self.subportfolio.long_positions.values()])
        value = max(0, strategy_value - current_value)

        if len(g.sell_list) > 0:
            for s in g.sell_list:
                value += self.subportfolio.long_positions[s].value

        if len(buy_list) > 0:
            value = value / len(buy_list)
            df = get_price(buy_list, end_date=yesterday, frequency='1d', count=1, fields=['close'], fq='pre', panel=False, skip_paused=False, fill_paused=True).set_index('code')
            df['today_hl_price'] = [0] * len(df)
            for s in list(df.index):
                if ((s[0] == '3') and (str(context.current_dt)[:10] >= '2020-08-24')):
                    df.loc[s, 'today_hl_price'] = round(df.loc[s, 'close'] * 1.05, 2)
                else:
                    df.loc[s, 'today_hl_price'] = round(df.loc[s, 'close'] * 1.05, 2)
            g.buy_df['name'] = [get_security_info(s, yesterday).display_name for s in buy_list]
            g.buy_df['price'] = [df.loc[s, 'today_hl_price'] for s in buy_list]
            g.buy_df['amount'] = [100 * int(1.05 * value / df.loc[s, 'today_hl_price'] / 100) for s in buy_list]
            g.buy_df['value'] = g.buy_df['price'] * g.buy_df['amount']
            g.buy_df.index = buy_list

        # 盘前打印
        log.info(f"[{self.name}] 卖出: {g.sell_list}")
        log.info(f"[{self.name}] 红利低波: {g.buy_df}")
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[5] = list(set(self.subportfolio.long_positions.keys()))

    def trade(self, context):
        """交易逻辑"""
        current_data = get_current_data()

        # 卖出
        for s in g.sell_list:
            if current_data[s].last_price < current_data[s].high_limit:
                self.order_target_value_(s, 0)

        # 买入
        df = g.buy_df
        for s in list(df.index):
            log.info(f"[{self.name}] 买入: {s} {df.loc[s, 'name']}")
            self.order_target_value_(s, df.loc[s, 'value'])
        
        # 同步持仓记录（修复持仓同步问题）
        g.strategy_holdings[5] = list(set(self.subportfolio.long_positions.keys()))

    def check_limit_up(self, context):
        """检查昨日涨停股票"""
        current_data = get_current_data()

        if g.high_limit_list != []:
            for s in g.high_limit_list:
                if current_data[s].last_price < current_data[s].high_limit:
                    self.order_target_value_(s, 0)
                    log.info(f"[{self.name}] {s} 涨停打开，卖出")
                else:
                    log.info(f"[{self.name}] {s} 涨停，继续持有")

    def filter_new_stock(self, context, stock_list):
        """过滤次新股"""
        yesterday = context.previous_date
        return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

    def filter_kcb_stock(self, stock_list):
        """过滤科创板、北交所股票"""
        return [stock for stock in stock_list if ((stock[0] != '4') and (stock[0] != '8') and (stock[0:2] != '68'))]

    def filter_st_stock(self, stock_list):
        """过滤ST股票"""
        current_data = get_current_data()
        return [stock for stock in stock_list
                if not current_data[stock].is_st
                and 'ST' not in current_data[stock].name
                and '*' not in current_data[stock].name
                and '退' not in current_data[stock].name]

    def filter_paused_stock(self, stock_list):
        """过滤停牌股票"""
        current_data = get_current_data()
        return [stock for stock in stock_list if not current_data[stock].paused]

    def get_dividend_ratio_filter_list(self, context, stock_list, sort, p1, p2, threshold):
        """股息率筛选"""
        time1 = context.previous_date
        time0 = time1 - datetime.timedelta(days=365)
        interval = 1000
        list_len = len(stock_list)

        q = query(
            finance.STK_XR_XD.code,
            finance.STK_XR_XD.a_registration_date,
            finance.STK_XR_XD.bonus_amount_rmb
        ).filter(
            finance.STK_XR_XD.a_registration_date >= time0,
            finance.STK_XR_XD.a_registration_date <= time1,
            finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)])
        )
        df = finance.run_query(q)

        if list_len > interval:
            df_num = list_len // interval
            for i in range(df_num):
                q = query(
                    finance.STK_XR_XD.code,
                    finance.STK_XR_XD.a_registration_date,
                    finance.STK_XR_XD.bonus_amount_rmb
                ).filter(
                    finance.STK_XR_XD.a_registration_date >= time0,
                    finance.STK_XR_XD.a_registration_date <= time1,
                    finance.STK_XR_XD.code.in_(
                        stock_list[interval * (i + 1):min(list_len, interval * (i + 2))]
                    )
                )
                temp_df = finance.run_query(q)
                df = df.append(temp_df)

        dividend = df.fillna(0)
        dividend = dividend.groupby('code').sum()
        temp_list = list(dividend.index)

        q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(temp_list))
        cap = get_fundamentals(q, date=time1)
        cap = cap.set_index('code')

        df = pd.concat([dividend, cap], axis=1, sort=False)
        df['dividend_ratio'] = (df['bonus_amount_rmb'] / 10000) / df['market_cap']
        df = df.sort_values(by=['dividend_ratio'], ascending=sort)
        df = df[int(p1 * len(df)):int(p2 * len(df))]
        df = df[df['dividend_ratio'] > threshold]
        return list(df.index)

    def get_factor_filter_list(self, context, stock_list, jqfactor, sort, p1, p2):
        """因子排序"""
        yesterday = context.previous_date
        score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
        df = pd.DataFrame(columns=['code', 'score'])
        df['code'] = stock_list
        df['score'] = score_list
        df = df.dropna()
        df.sort_values(by='score', ascending=sort, inplace=True)
        final_list = list(df.code)[int(p1 * len(df)):int(p2 * len(df))]
        return final_list


# 子策略5的调度包装函数


def dividend_prepare(context):
    """红利策略准备股票池"""
    g.strategies[5].prepare_stock_list(context)


def dividend_get_stock_list(context):
    """红利策略选股"""
    g.strategies[5].get_stock_list(context)


def dividend_trade(context):
    """红利策略交易"""
    g.strategies[5].trade(context)


def dividend_check_limit_up(context):
    """红利策略涨停检查"""
    g.strategies[5].check_limit_up(context)


def dividend_atr_stoploss(context):
    """红利策略ATR动态止损"""
    if g.enable_atr_stoploss:
        g.strategies[5].check_atr_stoploss(context)
        g.strategy_holdings[5] = list(set(g.strategies[5].subportfolio.long_positions.keys()))
