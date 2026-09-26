#!/bin/sh
# dsh refuses --host 0.0.0.0 (no login on the web UI). It listens on loopback inside the
# container; socat exposes it on the container IP only. That port is reachable solely through
# the host web bridge, which the host firewall opens to scrum4me-caddy only, and Caddy adds
# basic_auth. See README.md.
set -e
socat TCP-LISTEN:3081,bind=172.30.80.10,fork,reuseaddr TCP:127.0.0.1:3080 &
exec dsh "$@"
