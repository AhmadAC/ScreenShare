# Proxy

!> When using a proxy enable `ScreenShare_TRUST_PROXY_HEADERS`. See [Configuration](config.md).

## nginx

### At root path

```nginx
upstream ScreenShare {
  # Set this to the address configured in
  # ScreenShare_SERVER_ADDRESS. Default 5050
  server 127.0.0.1:5050;
}

server {
  listen 80;

  # Here goes your domain / subdomain
  server_name ScreenShare.example.com;

  location / {
    # Proxy to ScreenShare
    proxy_pass         http://ScreenShare;
    proxy_http_version 1.1;

    # Set headers for proxying WebSocket
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_redirect     http:// $scheme://;

    # Set proxy headers
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto http;

    # The proxy must preserve the host because ScreenShare verifies it with the origin
    # for WebSocket connections
    proxy_set_header   Host $http_host;
  }
}
```

### At a sub path

```nginx
upstream ScreenShare {
  # Set this to the address configured in
  # ScreenShare_SERVER_ADDRESS. Default 5050
  server 127.0.0.1:5050;
}

server {
  listen 80;

  # Here goes your domain / subdomain
  server_name ScreenShare.example.com;

  location /ScreenShare/ {
    rewrite ^/ScreenShare(/.*) $1 break;
  
    # Proxy to ScreenShare
    proxy_pass         http://ScreenShare;
    proxy_http_version 1.1;

    # Set headers for proxying WebSocket
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_redirect     http:// $scheme://;

    # Set proxy headers
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto http;

    # The proxy must preserve the host because ScreenShare verifies it with the origin
    # for WebSocket connections
    proxy_set_header   Host $http_host;
  }
}
```

## Apache (httpd)

The following modules are required:

* mod_proxy
* mod_proxy_wstunnel
* mod_proxy_http

### At root path

```apache
<VirtualHost *:80>
    ServerName ScreenShare.example.com
    Keepalive On

    # The proxy must preserve the host because ScreenShare verifies it with the origin
    # for WebSocket connections
    ProxyPreserveHost On

    # Replace 5050 with the port defined in ScreenShare_SERVER_ADDRESS.
    # Default 5050

    # Proxy web socket requests to /stream
    ProxyPass "/stream" ws://127.0.0.1:5050/stream retry=0 timeout=5

    # Proxy all other requests to /
    ProxyPass "/" http://127.0.0.1:5050/ retry=0 timeout=5

    ProxyPassReverse / http://127.0.0.1:5050/
</VirtualHost>
```

### At a sub path

```apache
<VirtualHost *:80>
    ServerName ScreenShare.example.com
    Keepalive On

    Redirect 301 "/ScreenShare" "/ScreenShare/"

    # The proxy must preserve the host because ScreenShare verifies it with the origin
    # for WebSocket connections
    ProxyPreserveHost On

    # Proxy web socket requests to /stream
    ProxyPass "/ScreenShare/stream" ws://127.0.0.1:5050/stream retry=0 timeout=5

    # Proxy all other requests to /
    ProxyPass "/ScreenShare/" http://127.0.0.1:5050/ retry=0 timeout=5
    #                 ^- !!trailing slash is required!!

    ProxyPassReverse /ScreenShare/ http://127.0.0.1:5050/
</VirtualHost>
```
