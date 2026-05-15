#!/bin/bash
# Run once on VPS (77.239.107.30) to enable HTTPS
set -e

echo "=== Installing nginx + certbot ==="
apt update && apt install -y nginx certbot python3-certbot-nginx

echo "=== Configuring nginx ==="
cat > /etc/nginx/sites-available/agent-api << 'NGINX'
server {
    server_name agent-api-ai.duckdns.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /mcp {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 120s;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/agent-api /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== Getting SSL certificate ==="
certbot --nginx -d agent-api-ai.duckdns.org --non-interactive --agree-tos --email admin@agent-api-ai.duckdns.org

echo "=== Enabling auto-renewal ==="
systemctl enable certbot.timer

echo "=== Done! HTTPS should be active ==="
curl -I https://agent-api-ai.duckdns.org/health
