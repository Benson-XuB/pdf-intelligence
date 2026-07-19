#!/usr/bin/env bash
# =============================================================================
# PDF Intelligence — 一键部署脚本 (Hetzner Ubuntu 22.04 / 24.04)
#
# 用法：
#   1. 租好 Hetzner CX22 (4GB RAM, €3.99/月)
#   2. SSH 登录后把代码传上去：git clone <你的仓库> /opt/pdf-intelligence
#   3. 以 root 运行：bash /opt/pdf-intelligence/deploy/deploy.sh
#   4. 按提示输入域名
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${RED}[✗]${NC} $*"; }
info() { echo -e "${CYAN}[→]${NC} $*"; }

APP_DIR="/opt/pdf-intelligence"
DOMAIN=""
EMAIL=""

# ── 解析参数 ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="$2"; shift 2 ;;
        --email)  EMAIL="$2";  shift 2 ;;
        *) shift ;;
    esac
done

if [[ -z "$DOMAIN" ]]; then
    echo ""
    info "你的域名是什么？（例如：pdf.yourdomain.com）"
    read -rp "> " DOMAIN
fi
if [[ -z "$EMAIL" ]]; then
    info "Let's Encrypt 通知邮箱（例如：you@gmail.com）"
    read -rp "> " EMAIL
fi

echo ""
log "开始部署 PDF Intelligence"
log "域名: $DOMAIN"
log "邮箱: $EMAIL"
echo ""

# ── 1. 系统更新 + 基础工具 ────────────────────────────────────────
info "1/8 更新系统包…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git curl build-essential > /dev/null 2>&1
log "系统包安装完成"

# ── 2. 创建应用用户 ────────────────────────────────────────────────
info "2/8 创建应用用户…"
if ! id pdfintel &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" pdfintel
fi
mkdir -p "$APP_DIR"/{data/{uploads,outputs,filings},logs}
chown -R pdfintel:pdfintel "$APP_DIR"
log "应用用户已就绪"

# ── 3. Python 虚拟环境 ─────────────────────────────────────────────
info "3/8 创建 Python 虚拟环境…"
if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q -i https://pypi.org/simple/ --timeout 120
log "虚拟环境已就绪"

# ── 4. 安装依赖 ────────────────────────────────────────────────────
info "4/8 安装 Python 依赖（这一步会下载 Docling 模型，需要几分钟）…"
cd "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -e . --timeout 120 -i https://pypi.org/simple/
log "依赖安装完成"

# ── 5. 配置环境变量 ────────────────────────────────────────────────
info "5/8 检查 .env 配置…"
if [[ ! -f "$APP_DIR/.env" ]]; then
    cat > "$APP_DIR/.env" << 'ENVEOF'
# ── 必填 ───────────────────────────────
BASE_URL=https://__DOMAIN__
JWT_SECRET=__JWT__

# Google OAuth（去 https://console.cloud.google.com 申请）
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Stripe Payments（去 https://dashboard.stripe.com 获取）
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# ── 可选 ───────────────────────────────
# DASHSCOPE_API_KEY=          # Qwen VL 云视觉（阿里巴巴）
# DEEPSEEK_API_KEY=           # DeepSeek-V3 高精度
# SENDGRID_API_KEY=           # Magic Link 邮件发送

CONFIDENCE_THRESHOLD=0.85
UPLOAD_DIR=./data/uploads
OUTPUT_DIR=./data/outputs
FILING_CACHE_DIR=./data/filings
ENABLE_DOCLING=true
DOCLING_FAST_MODE=false
DOCLING_USE_VLM=false
GUEST_MAX_UPLOADS=1
ENVEOF

    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s|__DOMAIN__|$DOMAIN|g" "$APP_DIR/.env"
    sed -i "s|__JWT__|$JWT_SECRET|g" "$APP_DIR/.env"
    log ".env 已创建 — 请编辑填入 API Keys"
else
    warn ".env 已存在，跳过"
fi

# ── 6. systemd 服务 ─────────────────────────────────────────────────
info "6/8 配置 systemd 服务…"
cat > /etc/systemd/system/pdf-intelligence.service << SERVICEEOF
[Unit]
Description=PDF Intelligence API
After=network.target

[Service]
Type=simple
User=pdfintel
Group=pdfintel
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8100
Restart=always
RestartSec=3
StandardOutput=append:$APP_DIR/logs/uvicorn.log
StandardError=append:$APP_DIR/logs/uvicorn_error.log

# 防止 OOM (Docling 模型加载时内存可能飙升)
MemoryHigh=3G
MemoryMax=3800M

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable pdf-intelligence
systemctl start pdf-intelligence
sleep 2
if systemctl is-active --quiet pdf-intelligence; then
    log "systemd 服务运行中"
else
    warn "服务启动失败，查看: journalctl -u pdf-intelligence -n 30"
fi

# ── 7. Nginx 反向代理（先配 HTTP，certbot 会自动加上 HTTPS）───
info "7/8 配置 Nginx（HTTP 模式）…"
cat > "/etc/nginx/sites-available/$DOMAIN" << 'NGINXEOF'
server {
    listen 80;
    server_name __DOMAIN__;

    client_max_body_size 50M;
    client_body_timeout 120s;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;

    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }
}
NGINXEOF
sed -i "s|__DOMAIN__|$DOMAIN|g" "/etc/nginx/sites-available/$DOMAIN"

ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
log "Nginx 配置完成"

# ── 8. HTTPS 证书 ──────────────────────────────────────────────────
info "8/8 申请 SSL 证书…"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" || {
    warn "SSL 证书申请失败。请检查域名 DNS 是否已指向本服务器 IP。"
    warn "可以先 HTTP 访问，之后再运行: certbot --nginx -d $DOMAIN"
}

# ── 完成 ───────────────────────────────────────────────────────────
echo ""
echo "=============================================="
log "部署完成！"
echo ""
info "检查服务状态："
info "  systemctl status pdf-intelligence"
info "  systemctl status nginx"
echo ""
info "查看日志："
info "  journalctl -u pdf-intelligence -f"
echo ""
info "下一步："
info "  1. 编辑 .env 填入 API Keys: vim $APP_DIR/.env"
info "  2. 开放防火墙: ufw allow 80/tcp && ufw allow 443/tcp"
info "  3. 打开浏览器访问: https://$DOMAIN"
echo ""
info "Google OAuth 回调地址请设置为:"
info "  https://$DOMAIN/api/auth/google/callback"
echo "=============================================="
