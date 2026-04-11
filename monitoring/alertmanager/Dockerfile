FROM prom/alertmanager:v0.27.0

COPY alertmanager.yml /etc/alertmanager/alertmanager.yml.template
COPY entrypoint.sh /entrypoint.sh

USER root
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
