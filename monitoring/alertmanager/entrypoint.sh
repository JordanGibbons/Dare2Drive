#!/bin/sh
# Substitute NTFY_RELAY_URL in the config template before starting alertmanager.
# Default matches the Docker Compose service name; override for Railway.
NTFY_RELAY_URL="${NTFY_RELAY_URL:-http://ntfy-relay:9096}"

sed "s|http://ntfy-relay:9096|${NTFY_RELAY_URL}|g" \
    /etc/alertmanager/alertmanager.yml.template \
    > /tmp/alertmanager.yml

exec /bin/alertmanager --config.file=/tmp/alertmanager.yml "$@"
