@echo off
cd /d "%~dp0"
python scripts/crawl.py %*
