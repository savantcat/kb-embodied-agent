#!/usr/bin/env bash
# 演示/录制前清场：释放所有被占用的数字人名额（含上次浏览器崩溃留下的残留会话）。
# 用法：bash scripts/pre_demo_clean.sh
# 说明：只在本机演示环境用；会调用管理侧强制释放接口，口令从 .env 读取且不打印。
set -uo pipefail

BASE="${KB_BASE:-http://127.0.0.1:8080}"
ENVF="$(cd "$(dirname "$0")/.." && pwd)/.env"
TOKEN="$(grep -E '^ADMIN_TOKEN=' "$ENVF" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | tr -d '\n')"

echo "== 清场前 =="
curl -s -m 8 "$BASE/api/stats" || { echo "后端没起来（$BASE）"; exit 1; }
echo
echo "== 强制释放所有会话 =="
curl -s -m 15 -X POST "$BASE/api/admin/release?token=$TOKEN"
echo
echo "== 清场后（busy_now 应为 0） =="
curl -s -m 8 "$BASE/api/stats"
echo
