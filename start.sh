#!/bin/bash
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    python3 start.py
elif command -v python >/dev/null 2>&1; then
    python start.py
else
    echo "❌ 没找到 Python。请先安装 Python 3.9+："
    echo "   macOS:  brew install python"
    echo "   Linux:  apt install python3 / dnf install python3 / pacman -S python"
    exit 1
fi
