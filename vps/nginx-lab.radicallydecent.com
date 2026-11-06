# /etc/nginx/sites-available/lab.radicallydecent.com on the VPS: the self-service portal
# and its browser terminal. HTTPS only (no port-80 server).
#
#   browser --TLS--> VPS (password prompt) --TLS, verified--> pve01 relay (TCP only,
#   10.99.0.2:8443 over WireGuard) --> mgmt01:8443 (portal + Guacamole, nothing else)
#
# mgmt01 has its own Let's Encrypt certificate for this name, so this hop is verified.
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name lab.radicallydecent.com;
    ssl_certificate /etc/letsencrypt/live/lab.radicallydecent.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lab.radicallydecent.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    auth_basic "Lab";
    auth_basic_user_file /etc/nginx/lab.htpasswd;

    location / {
        proxy_pass https://10.99.0.2:8443;
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;                        # site -> LE intermediate -> root (nginx default: 1)
        proxy_ssl_server_name on;
        proxy_ssl_name lab.radicallydecent.com;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;          # Guacamole's terminal: WebSocket
        proxy_set_header Connection $http_connection;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization "";               # the lab never sees the demo password
        proxy_buffering off;
        proxy_read_timeout 3600s;
        client_max_body_size 64m;
    }
}
