#!/usr/bin/env bash
set -euo pipefail

project_dir="${1:-/opt/ai-creator-backend}"
service_user="${2:-ai-creator}"
unit_source="${project_dir}/deploy/systemd"
env_dir="/etc/ai-creator"
env_file="${env_dir}/ai-creator.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo ${0} [项目目录] [服务用户]" >&2
  exit 1
fi

if [[ ! -x "${project_dir}/.venv/bin/celery" || ! -x "${project_dir}/.venv/bin/uvicorn" ]]; then
  echo "未找到 ${project_dir}/.venv，请先创建虚拟环境并安装 requirements.txt" >&2
  exit 1
fi

if ! id "${service_user}" >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/ai-creator --create-home --shell /usr/sbin/nologin "${service_user}"
fi

install -d -m 0750 -o "${service_user}" -g "${service_user}" "${env_dir}"
if [[ ! -f "${env_file}" ]]; then
  install -m 0600 -o "${service_user}" -g "${service_user}" "${project_dir}/.env.production.example" "${env_file}"
  echo "已创建 ${env_file}，请先填写真实配置，然后重新运行本脚本。" >&2
  exit 2
fi

required_keys=(DATABASE_URL REDIS_URL JWT_SECRET ADMIN_PASSWORD CLIPCAT_API_KEY)
for key in "${required_keys[@]}"; do
  value="$(sed -n "s/^${key}=//p" "${env_file}" | tail -n 1)"
  if [[ -z "${value}" || "${value}" == *replace-with* ]]; then
    echo "${env_file} 中的 ${key} 尚未配置。" >&2
    exit 3
  fi
done

for service in ai-creator-api ai-creator-worker ai-creator-beat; do
  sed \
    -e "s|User=ai-creator|User=${service_user}|" \
    -e "s|Group=ai-creator|Group=${service_user}|" \
    -e "s|/opt/ai-creator-backend|${project_dir}|g" \
    "${unit_source}/${service}.service" > "/etc/systemd/system/${service}.service"
done

systemctl daemon-reload
systemctl enable --now ai-creator-api.service ai-creator-worker.service ai-creator-beat.service

echo "服务已安装并启动。"
systemctl --no-pager --full status ai-creator-api.service ai-creator-worker.service ai-creator-beat.service || true
