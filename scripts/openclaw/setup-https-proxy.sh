#!/bin/bash
# Setup nginx HTTPS reverse proxy for OpenClaw gateway
# Run with: sudo bash setup-https-proxy.sh

set -e

LOCAL_IP="192.168.1.10"
OPENCLAW_PORT="18789"
SSL_DIR="/etc/nginx/ssl"
CERT_DAYS="3650"  # 10 years for a local self-signed cert

echo "=== OpenClaw HTTPS Reverse Proxy Setup ==="
echo ""

# 1. Create SSL directory
mkdir -p "$SSL_DIR"

# 2. Generate self-signed certificate for the local IP
echo "[1/3] Generating self-signed SSL certificate for $LOCAL_IP ..."
openssl req -x509 -nodes -days "$CERT_DAYS" \
  -newkey rsa:2048 \
  -keyout "$SSL_DIR/openclaw.key" \
  -out "$SSL_DIR/openclaw.crt" \
  -subj "/CN=$LOCAL_IP" \
  -addext "subjectAltName=IP:$LOCAL_IP,IP:127.0.0.1"

chmod 600 "$SSL_DIR/openclaw.key"
chmod 644 "$SSL_DIR/openclaw.crt"

# 3. Write nginx site config
echo "[2/3] Writing nginx config ..."
cat > /etc/nginx/sites-available/openclaw <<'NGINX'
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name 192.168.1.10;

    ssl_certificate     /etc/nginx/ssl/openclaw.crt;
    ssl_certificate_key /etc/nginx/ssl/openclaw.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Proxy all traffic to OpenClaw gateway
    location / {
        proxy_pass http://127.0.0.1:18789;
        proxy_http_version 1.1;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Pass through client info
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts for long-lived WebSocket connections
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
NGINX

# 4. Enable the site and test config
ln -sf /etc/nginx/sites-available/openclaw /etc/nginx/sites-enabled/openclaw

echo "[3/3] Testing nginx configuration ..."
nginx -t

# 5. Reload nginx
systemctl reload nginx

echo ""
echo "=== Done! ==="
echo ""
echo "Access OpenClaw at: https://$LOCAL_IP/__openclaw__/canvas/"
echo ""
echo "Your browser will show a certificate warning because it's self-signed."
echo "Click 'Advanced' -> 'Proceed' (or 'Accept the Risk') to continue."
echo "You only need to do this once per browser."
