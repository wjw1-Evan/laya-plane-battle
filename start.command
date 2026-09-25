#!/bin/bash
# 飞机大战 · Laya 控制版 —— 双击启动(macOS)
# 自动复用/创建运行环境,启动本地决策服务并打开浏览器。
cd "$(dirname "$0")"

PORT=8787
VENV="$HOME/laya-venv"

# 1) 已有服务在跑?直接打开页面
if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; then
  open "http://127.0.0.1:$PORT/"
  echo "Laya 决策服务已在运行,已打开游戏页面。"
  exit 0
fi

# 2) Python 环境:优先复用 ~/laya-venv;没有就自建(仅首次需要联网装 laya)
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  echo "首次运行:创建虚拟环境并安装 laya…"
  PYBIN=$(command -v python3.12 || command -v python3.11 || command -v python3)
  $PYBIN -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q laya tiktoken
fi
"$PY" -c "import laya" 2>/dev/null || "$VENV/bin/pip" install -q laya

# 3) 模型缓存检查:直接看本地缓存文件;缺失时走国内镜像下载(已缓存则完全离线)
SNAP=$(ls -d "$HOME"/.cache/huggingface/hub/models--convaiinnovations--laya/snapshots/*/ 2>/dev/null | head -1)
if [ -f "$SNAP/multilingual/model.safetensors" ]; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
else
  export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
  echo "首次运行:下载 Laya 模型(约 750MB,走 hf-mirror)…"
fi
export LAYA_DEVICE=mps   # Apple GPU 加速,比 CPU 快 ~40%(server 内有锁串行化)

# 4) 启动决策服务并打开游戏(守护:意外退出 2 秒后自动重启)
echo "启动 Laya 决策服务(模型加载约 5-10 秒)…"
( sleep 6; open "http://127.0.0.1:8787/" ) &
while true; do "$PY" server.py; echo "服务退出,2 秒后重启…"; sleep 2; done
