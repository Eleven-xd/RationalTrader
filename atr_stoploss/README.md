# ATR动态止损计算器

基于ATR（Average True Range）指标的动态止损价格计算工具。

## 功能特点

- 支持A股股票代码输入（如 600000 或 600000.SH）
- 基于Tushare实时数据源
- 可自定义ATR计算周期（默认14天）
- 可自定义ATR倍数（默认2.0倍）
- 美观的网页界面，实时显示计算结果
- 自动识别股票代码格式

## ATR动态止损原理

ATR（平均真实波幅）是一个衡量市场波动性的技术指标。

### 计算公式

1. **真实波幅（TR）**
   ```
   TR = max(最高价-最低价, |最高价-前收盘价|, |最低价-前收盘价|)
   ```

2. **ATR**
   ```
   ATR = TR的N日移动平均（通常N=14）
   ```

3. **动态止损价格**
   ```
   止损价 = 最高价 - ATR × 倍数
   ```

### 优势

- **自适应波动性**：高波动时扩大止损距离，低波动时收窄止损距离
- **趋势跟踪**：随着价格上涨，止损线跟随上移
- **避免震荡市被洗盘**：给价格更多波动空间

## 安装步骤

### 1. 安装Python依赖

```bash
cd atr_stoploss
pip install -r requirements.txt
```

### 2. 设置Tushare API Token

首先需要在[Tushare官网](https://tushare.pro/)注册账号并获取API Token。

**方法一：设置环境变量（推荐）**
```bash
export TUSHARE_TOKEN='your_token_here'
```

**方法二：在代码中设置**
编辑 `app.py` 文件，修改第15行：
```python
TUSHARE_TOKEN = 'your_token_here'
```

### 3. 启动服务

```bash
python app.py
```

服务将在 `http://localhost:5000` 启动。

## 使用方法

1. 在浏览器中打开 `http://localhost:5000`
2. 输入股票代码：
   - 支持6位数字：`600000`（自动识别为上海股票）
   - 支持完整代码：`600000.SH` 或 `000001.SZ`
3. 调整参数（可选）：
   - ATR周期：默认14天（建议范围7-30天）
   - ATR倍数：默认2.0倍（建议范围1.0-3.0倍）
4. 点击"计算止损价格"按钮
5. 查看计算结果

## 计算结果说明

- **当前价格**：最新收盘价
- **期间最高价**：计算周期内的最高价
- **ATR值**：当前ATR指标值
- **收益率**：当前价相对最高价的收益率
- **建议止损价格**：根据ATR计算出的动态止损价
- **距离最高价**：止损价距离最高价的百分比距离

## 参数建议

### ATR周期
- **短线策略**：7-10天
- **中线策略**：14天（默认）
- **长线策略**：20-30天

### ATR倍数
- **保守型**：1.5-2.0倍
- **平衡型**：2.0-2.5倍（默认2.0倍）
- **激进型**：2.5-3.5倍

## 技术栈

- **后端**：Flask + Tushare
- **前端**：原生HTML + CSS + JavaScript
- **数据处理**：Pandas + NumPy

## API接口

### POST /api/calculate

计算ATR动态止损价格

**请求参数：**
```json
{
  "stock_code": "600000.SH",
  "atr_period": 14,
  "atr_multiplier": 2.0
}
```

**响应示例：**
```json
{
  "success": true,
  "data": {
    "stock_code": "600000.SH",
    "stock_name": "浦发银行",
    "current_price": 10.23,
    "highest_price": 10.50,
    "atr": 0.15,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "stop_loss_price": 10.20,
    "distance_percent": 2.86,
    "return_ratio": -2.57,
    "latest_date": "2025-01-18"
  }
}
```

## 注意事项

1. **Tushare Token**：首次使用需要注册Tushare账号并获取Token
2. **数据限制**：免费版Tushare有调用频率限制，请勿频繁刷新
3. **计算基准**：止损价格基于期间最高价计算，实际使用时建议结合持仓成本价
4. **仅供参考**：本工具仅提供计算参考，不构成投资建议

## 常见问题

**Q: 提示"获取股票数据失败"？**

A: 请检查：
1. 股票代码格式是否正确
2. Tushare Token是否正确设置
3. 网络连接是否正常

**Q: 如何获取Tushare Token？**

A: 访问 https://tushare.pro/ 注册账号，登录后在个人中心获取Token。

**Q: 支持哪些市场？**

A: 目前支持上海证券交易所（.SH）和深圳证券交易所（.SZ）的A股股票。

## 许可证

MIT License
