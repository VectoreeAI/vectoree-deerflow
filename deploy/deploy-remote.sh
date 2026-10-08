#!/usr/bin/env bash
# 服务器上拉 GitLab 镜像并重启 compose。不在服务器上构建，也不删数据卷。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.deploy.yml}"
cd "$ROOT_DIR"

read_dotenv() {
  local key="$1"
  local line value
  line="$(grep -E "^[[:space:]]*${key}=" .env | tail -n 1 || true)"
  [[ -z "$line" ]] && return 0
  value="${line#*=}"
  value="${value%$'\r'}"
  if [[ "$value" =~ ^\"(.*)\"$ ]]; then
    value="${BASH_REMATCH[1]}"
  elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
    value="${BASH_REMATCH[1]}"
  fi
  printf '%s' "$value"
}

upsert_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if [[ -f .env ]]; then
    grep -vE "^[[:space:]]*${key}=" .env >"$tmp" || true
  fi
  printf '%s=%s\n' "$key" "$val" >>"$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

ensure_secret() {
  local key="$1" current value
  current="$(read_dotenv "$key")"
  if [[ -n "$current" ]]; then
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    value="$(openssl rand -hex 32)"
  else
    value="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  upsert_env "$key" "$value"
}

apply_dotenv() {
  local var="$1"
  local from_file
  from_file="$(read_dotenv "$var")"
  if [[ -n "$from_file" ]]; then
    printf -v "$var" '%s' "$from_file"
  fi
}

seed_file() {
  local dest="$1" src="$2"
  if [[ -f "$dest" ]]; then
    return 0
  fi
  if [[ ! -f "$src" ]]; then
    echo "Missing $src; cannot create $dest"
    exit 1
  fi
  cp "$src" "$dest"
  if [[ "$dest" == ".env" ]]; then
    chmod 600 .env
  fi
  echo "[remote] Created $dest from $src"
}

IN_GATEWAY_IMAGE="${DEERFLOW_GATEWAY_IMAGE:-}"
IN_FRONTEND_IMAGE="${DEERFLOW_FRONTEND_IMAGE:-}"
IN_API_URL="${VECTOREE_API_URL:-}"
IN_DEPLOY_MODE="${DEPLOY_MODE:-}"

seed_file .env deploy/env.example
seed_file config.yaml config.example.yaml
seed_file extensions_config.json extensions_config.example.json
mkdir -p skills/public skills/custom

ensure_secret BETTER_AUTH_SECRET
ensure_secret DEER_FLOW_INTERNAL_AUTH_TOKEN

if [[ -n "$IN_GATEWAY_IMAGE" ]]; then
  upsert_env DEERFLOW_GATEWAY_IMAGE "$IN_GATEWAY_IMAGE"
fi
if [[ -n "$IN_FRONTEND_IMAGE" ]]; then
  upsert_env DEERFLOW_FRONTEND_IMAGE "$IN_FRONTEND_IMAGE"
fi
if [[ -n "$IN_API_URL" ]]; then
  upsert_env VECTOREE_API_URL "$IN_API_URL"
fi
if [[ -n "$IN_DEPLOY_MODE" ]]; then
  case "$IN_DEPLOY_MODE" in
    local|cloud) upsert_env DEPLOY_MODE "$IN_DEPLOY_MODE" ;;
    *)
      echo "DEPLOY_MODE must be local or cloud"
      exit 1
      ;;
  esac
fi

apply_dotenv DEERFLOW_GATEWAY_IMAGE
apply_dotenv DEERFLOW_FRONTEND_IMAGE
apply_dotenv VECTOREE_API_URL
apply_dotenv DEERFLOW_WEB_PORT
apply_dotenv DEPLOY_MODE

if [[ -z "${DEERFLOW_GATEWAY_IMAGE:-}" || -z "${DEERFLOW_FRONTEND_IMAGE:-}" ]]; then
  echo "Set DEERFLOW_GATEWAY_IMAGE and DEERFLOW_FRONTEND_IMAGE in .env"
  exit 1
fi

export DEERFLOW_GATEWAY_IMAGE DEERFLOW_FRONTEND_IMAGE
export VECTOREE_API_URL="${VECTOREE_API_URL:-https://vectoree.ai}"
export DEERFLOW_WEB_PORT="${DEERFLOW_WEB_PORT:-5174}"
case "${DEPLOY_MODE:-local}" in
  local|cloud) ;;
  *)
    echo "DEPLOY_MODE must be local or cloud"
    exit 1
    ;;
esac
export DEPLOY_MODE="${DEPLOY_MODE:-local}"

COMPOSE_BIN=()
setup_compose() {
  export DOCKER_CLI_PLUGIN_EXTRA_DIRS="${DOCKER_CLI_PLUGIN_EXTRA_DIRS:-/usr/libexec/docker/cli-plugins:/usr/lib/docker/cli-plugins}"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_BIN=(docker compose)
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BIN=(docker-compose)
    return
  fi
  echo "[remote] ERROR: Docker Compose is not installed."
  exit 1
}
dc() {
  "${COMPOSE_BIN[@]}" -f "$COMPOSE_FILE" "$@"
}

setup_compose
echo "[remote] Using: ${COMPOSE_BIN[*]}"

for svc in gateway frontend nginx redis; do
  attempt=1
  max=5
  while true; do
    echo "[remote] Pull ${svc} (${attempt}/${max})..."
    if dc pull "$svc"; then
      break
    fi
    if [[ "$attempt" -ge "$max" ]]; then
      echo "[remote] ERROR: pull ${svc} failed after ${max} attempts"
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 15
  done
done

echo "[remote] Starting stack..."
dc up -d --remove-orphans --no-build

echo "[remote] Waiting for http://127.0.0.1:${DEERFLOW_WEB_PORT}/health ..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${DEERFLOW_WEB_PORT}/health" >/dev/null 2>&1; then
    echo "[remote] OK — http://127.0.0.1:${DEERFLOW_WEB_PORT}/health"
    exit 0
  fi
  sleep 5
done

echo "[remote] Health check failed:"
dc logs --tail=80 gateway nginx || true
exit 1
