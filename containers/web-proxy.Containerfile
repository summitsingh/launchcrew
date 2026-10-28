FROM docker.io/library/node:22-alpine
WORKDIR /app
COPY web/tls-proxy.mjs /app/tls-proxy.mjs
COPY containers/web-proxy-entrypoint.sh /usr/local/bin/web-proxy-entrypoint.sh
RUN chmod 755 /usr/local/bin/web-proxy-entrypoint.sh && chmod 644 /app/tls-proxy.mjs
USER node
EXPOSE 8443
# TLS reverse-proxy sidecar only. No app code is in this image.
# The web app container, in the same Fargate task, binds 127.0.0.1:3000
# only, and this proxy, on 0.0.0.0:8443, is the only container the
# ALB target group points at. Certificate material is decoded at task
# start from Secrets Manager base64 variables, without logging, see
# containers/web-proxy-entrypoint.sh. Plain HTTP proxy mode does not
# exist here, missing certificate material fails closed, exit 1.
CMD ["/usr/local/bin/web-proxy-entrypoint.sh"]
