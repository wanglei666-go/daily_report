#!/bin/bash
# 由 cron 调用，不依赖交互登录。路径相对本脚本所在目录。
# 日志由脚本写入 briefing.log；此处只追加 stderr，避免重复记两遍。
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
export PATH=/usr/bin:/bin
export LANG=zh_CN.UTF-8
export TZ=Asia/Shanghai
exec /usr/bin/python3 "$DIR/briefing_server.py" 2>> "$DIR/briefing.log"
