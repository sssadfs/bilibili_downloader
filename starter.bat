@echo off
chcp 65001 >nul
echo ==========================================
echo   Bilibili 视频批量下载器
echo ==========================================
echo.
echo 使用 conda 环境: bilibili
echo.

C:\Users\admin\miniconda3\envs\bilibili\python.exe "%~dp0bilibili_downloader.py"

echo.
pause
