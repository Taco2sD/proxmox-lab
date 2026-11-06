# Proxmox UI of the home lab, through the WireGuard tunnel to pve01 (10.99.0.2).
# HTTPS only (no port-80 server). pve01 has its own Let's Encrypt certificate for this
# name (Proxmox ACME, DNS-01 via acme-dns), so the hop through the tunnel is verified too.
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name pve.radicallydecent.com;
    ssl_certificate /etc/letsencrypt/live/pve.radicallydecent.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pve.radicallydecent.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    auth_basic "Lab";
    auth_basic_user_file /etc/nginx/lab.htpasswd;

    location / {
        proxy_pass https://10.99.0.2:8006;
        proxy_ssl_verify on;
        proxy_ssl_server_name on;
        proxy_ssl_name pve.radicallydecent.com;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;      # VM consoles use websockets
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        client_max_body_size 0;
    }
}
