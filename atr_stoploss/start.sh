#!/bin/bash
# ATR动态止损计算器启动脚本

echo "========================================="
echo "  ATR动态止损计算器"
echo "========================================="
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3，请先安装Python3"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装依赖包..."
pip install -r requirements.txt -q

# 检查Tushare Token
if [ -z "$TUSHARE_TOKEN" ]; then
    echo ""
    echo "========================================="
    echo "警告: 未设置TUSHARE_TOKEN环境变量"
    echo "========================================="
    echo "请先设置您的Tushare API Token:"
    echo "export TUSHARE_TOKEN='your_token_here'"
    echo ""
    echo "或者访问 https://tushare.pro/ 注册获取Token"
    echo "========================================="
    echo ""
fi

# 启动应用
echo "启动Flask服务..."
echo "访问地址: http://localhost:5000"
echo ""
echo "按 Ctrl+C 停止服务"
echo "========================================="
echo ""

python app.py
