# acme-dns API for the lab's machines (mgmt01, pve01) to publish their DNS-01 answers.
# Only /update is reachable; registering accounts is only possible on this machine
# (127.0.0.1:8053). HTTPS only: there is no port-80 server for this name.
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name acme-ns.radicallydecent.com;
    ssl_certificate /etc/letsencrypt/live/acme-ns.radicallydecent.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/acme-ns.radicallydecent.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 1k;

    location = /update {
        limit_except POST { deny all; }
        proxy_pass http://127.0.0.1:8053;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
    location / { return 404; }
}
