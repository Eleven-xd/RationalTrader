@echo off
chcp 65001 > nul
echo =========================================
echo   ATR动态止损计算器
echo =========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
echo 安装依赖包...
pip install -r requirements.txt -q

REM 检查Tushare Token
if "%TUSHARE_TOKEN%"=="" (
    echo.
    echo =========================================
    echo 警告: 未设置TUSHARE_TOKEN环境变量
    echo =========================================
    echo 请先设置您的Tushare API Token:
    echo set TUSHARE_TOKEN=your_token_here
    echo.
    echo 或者访问 https://tushare.pro/ 注册获取Token
    echo =========================================
    echo.
)

REM 启动应用
echo 启动Flask服务...
echo 访问地址: http://localhost:5000
echo.
echo 按 Ctrl+C 停止服务
echo =========================================
echo.

python app.py
pause
