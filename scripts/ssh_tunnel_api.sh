#!/usr/bin/env bash
# 本机运行：把服务器 80 映射到本机 8080（本机 80 通常需 root）
# 用法: ./scripts/ssh_tunnel_api.sh [user@host]
set -euo pipefail

REMOTE="${1:-user@123.59.0.91}"
SSH_PORT="${SSH_PORT:-22333}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
REMOTE_PORT="${REMOTE_PORT:-80}"

echo "建立隧道: 本机 http://127.0.0.1:${LOCAL_PORT} -> ${REMOTE}:${REMOTE_PORT}"
echo "Postman 请访问: http://127.0.0.1:${LOCAL_PORT}/health"
echo "按 Ctrl+C 关闭隧道"
exec ssh -p "${SSH_PORT}" -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${REMOTE}"
