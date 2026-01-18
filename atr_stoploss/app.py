#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATR动态止损计算器
基于Tushare数据源的ATR指标计算工具
"""

import tushare as ts
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# 配置Tushare Token
TUSHARE_TOKEN = "a2827e2cc490fbb8fc2f6523020158a4b2a13bab2acb596d0dfc6e88"#os.getenv('TUSHARE_TOKEN', 'a2827e2cc490fbb8fc2f6523020158a4b2a13bab2acb596d0dfc6e88')

# 初始化Tushare
if TUSHARE_TOKEN:
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
else:
    pro = None
    print("警告: 未设置TUSHARE_TOKEN环境变量，请先设置您的Tushare API Token")


def calculate_atr(df, period=14):
    """
    计算ATR指标

    Args:
        df: 包含close, high, low列的DataFrame
        period: ATR计算周期，默认14天

    Returns:
        ATR值
    """
    if len(df) < period + 1:
        return None

    # 计算真实波幅TR
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values

    # TR = max(最高价-最低价, |最高价-前收盘价|, |最低价-前收盘价|)
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    # 计算ATR (使用简单移动平均)
    atr = np.mean(tr[:period])

    return atr


def get_stock_data(ts_code, period=60):
    """
    获取股票历史数据

    Args:
        ts_code: 股票代码，格式如 '000001.SZ' 或 '600000.SH'
        period: 获取历史数据的天数

    Returns:
        DataFrame: 包含close, high, low的数据
    """
    if not pro:
        return None

    try:
        # 获取日K线数据
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=period * 2)).strftime('%Y%m%d')

        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df.empty:
            return None

        # 按日期升序排列
        df = df.sort_values('trade_date')
        df = df.tail(period)  # 取最近N天数据

        # 重命名列
        df = df[['trade_date', 'close', 'high', 'low']].rename(
            columns={'trade_date': 'date'}
        )

        return df

    except Exception as e:
        print(f"获取股票数据错误: {e}")
        return None


def calculate_stop_loss_price(df, atr_multiplier=2.0, atr_period=14):
    """
    计算ATR动态止损价格

    Args:
        df: 历史数据DataFrame
        atr_multiplier: ATR倍数，通常2-3倍
        atr_period: ATR计算周期，通常14天

    Returns:
        dict: 包含止损价格和相关信息
    """
    if df is None or len(df) < atr_period + 1:
        return None

    # 计算ATR
    atr = calculate_atr(df, atr_period)
    if atr is None:
        return None

    # 获取最新价格和最高价
    current_price = df['close'].iloc[-1]
    highest_price = df['high'].max()

    # 计算止损价格
    # 使用最高价作为参考点，如果持有期间最高价高于当前价
    # 否则使用成本价（这里简化为使用当前价）
    reference_price = highest_price

    stop_loss_price = reference_price - atr_multiplier * atr

    # 计算收益率
    return_ratio = ((current_price - reference_price) / reference_price) * 100

    return {
        'stock_code': '',
        'stock_name': '',
        'current_price': round(current_price, 2),
        'highest_price': round(highest_price, 2),
        'atr': round(atr, 2),
        'atr_period': atr_period,
        'atr_multiplier': atr_multiplier,
        'stop_loss_price': round(stop_loss_price, 2),
        'distance_percent': round(((reference_price - stop_loss_price) / reference_price) * 100, 2),
        'return_ratio': round(return_ratio, 2),
        'latest_date': df['date'].iloc[-1]
    }


def get_stock_name(ts_code):
    """
    获取股票名称

    Args:
        ts_code: 股票代码

    Returns:
        str: 股票名称
    """
    if not pro:
        return '未知'

    try:
        df = pro.stock_basic(ts_code=ts_code)
        if not df.empty:
            return df['name'].iloc[0]
    except Exception as e:
        print(f"获取股票名称错误: {e}")

    return '未知'


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/calculate', methods=['POST'])
def calculate():
    """ATR止损计算API"""
    try:
        data = request.json
        ts_code = data.get('stock_code', '').strip()
        atr_period = int(data.get('atr_period', 14))
        atr_multiplier = float(data.get('atr_multiplier', 2.0))

        # 验证输入
        if not ts_code:
            return jsonify({'error': '请输入股票代码'}), 400

        # 标准化股票代码格式
        ts_code = ts_code.upper()

        # 如果用户只输入数字，尝试转换为标准格式
        if ts_code.isdigit() and len(ts_code) == 6:
            if ts_code.startswith('6'):
                ts_code = f"{ts_code}.SH"
            else:
                ts_code = f"{ts_code}.SZ"

        # 获取股票数据
        df = get_stock_data(ts_code, period=60)
        if df is None:
            return jsonify({'error': '获取股票数据失败，请检查股票代码是否正确'}), 400

        # 获取股票名称
        stock_name = get_stock_name(ts_code)

        # 计算止损价格
        result = calculate_stop_loss_price(df, atr_multiplier, atr_period)
        if result is None:
            return jsonify({'error': '计算失败，数据不足'}), 400

        # 添加股票信息
        result['stock_code'] = ts_code
        result['stock_name'] = stock_name

        return jsonify({'success': True, 'data': result})

    except Exception as e:
        return jsonify({'error': f'计算错误: {str(e)}'}), 500


if __name__ == '__main__':
    # 检查Tushare Token
    if not TUSHARE_TOKEN:
        print("========================================")
        print("警告: 未设置TUSHARE_TOKEN环境变量")
        print("请先设置您的Tushare API Token:")
        print("export TUSHARE_TOKEN='your_token_here'")
        print("========================================")
        print()

    app.run(debug=True, host='0.0.0.0', port=5000)
