#!/usr/bin/env bash
# 演示/录制前自检 + 清场
#   1) 后端在不在
#   2) 容器能不能连到星云平台（这一步坏了最坑：页面一切正常，一开麦就废）
#   3) 释放所有被占用的数字人名额（含上次浏览器崩溃留下的残留）
# 用法：bash scripts/pre_demo_clean.sh
set -uo pipefail

BASE="${KB_BASE:-http://127.0.0.1:8080}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="$DIR/.env"
TOKEN="$(grep -E '^ADMIN_TOKEN=' "$ENVF" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | tr -d '\n')"

echo "== 1/3 后端健康 =="
curl -s -m 8 "$BASE/api/health" || { echo; echo "后端没起来（$BASE）：先 docker compose up -d"; exit 1; }
echo

echo "== 2/3 容器 → 星云平台连通性 =="
docker compose -f "$DIR/docker-compose.yml" exec -T backend python - <<'PY'
import socket, time
ok = True
for name, host in (("星云平台", "nebula-agent.xingyun3d.com"), ("百度(对照)", "www.baidu.com")):
    t = time.time()
    try:
        s = socket.create_connection((host, 443), timeout=8)
        s.close()
        print("  %s: 通 (%.2fs)" % (name, time.time() - t))
    except Exception as e:
        ok = False
        print("  %s: 失败 %s  <== 容器出网坏了" % (name, type(e).__name__))
if not ok:
    print("  >>> 修法：docker compose down && docker network prune -f && docker compose up -d")
    raise SystemExit(2)
PY
RC=$?
if [ "$RC" -ne 0 ]; then echo "  ⚠ 连通性检查未通过，先修网络再录制"; fi
echo

echo "== 3/3 释放所有占位名额 =="
curl -s -m 15 -X POST "$BASE/api/admin/release?token=$TOKEN"
echo
curl -s -m 8 "$BASE/api/stats"
echo
echo "（busy_now 应为 0；day_sessions/day_points 是当日累计）"
