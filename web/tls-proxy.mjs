// LaunchCrew web TLS reverse proxy, sidecar only.
// Listens on 0.0.0.0:8443 with TLS, proxies to the web app on
// localhost:3000 only. The web app must bind 127.0.0.1 in TLS mode,
// so it is private within the task network namespace, and it is never
// exposed directly to the ALB or to the internet. The ALB target group
// points at this proxy, port 8443, not at the app.
// Certificate material is read from files named by TLS_CERT_FILE and
// TLS_KEY_FILE, which the proxy entrypoint decodes from base64
// environment variables supplied by Secrets Manager, without logging
// any certificate, key, or secret value. This file never logs a
// request body, header, or secret, only a startup line with host
// and port, and a proxy error line with status code only.
// TLS_PROXY_TARGET defaults to http://127.0.0.1:3000, and must be a
// loopback target, otherwise the proxy refuses to start, so the app
// cannot be proxied to an external host by accident.
import https from 'node:https';
import http from 'node:http';
import fs from 'node:fs';

const certFile = process.env.TLS_CERT_FILE;
const keyFile = process.env.TLS_KEY_FILE;
const target = process.env.TLS_PROXY_TARGET || 'http://127.0.0.1:3000';
const port = Number(process.env.TLS_PROXY_PORT || 8443);
if (!certFile || !keyFile) {
  console.error('tls-proxy: TLS_CERT_FILE and TLS_KEY_FILE are required');
  process.exit(1);
}
let targetUrl;
try {
  targetUrl = new URL(target);
} catch {
  console.error('tls-proxy: TLS_PROXY_TARGET is not a valid URL');
  process.exit(1);
}
if (targetUrl.hostname !== '127.0.0.1' && targetUrl.hostname !== 'localhost') {
  console.error('tls-proxy: TLS_PROXY_TARGET must be loopback only');
  process.exit(1);
}
const options = {
  cert: fs.readFileSync(certFile),
  key: fs.readFileSync(keyFile),
};
const server = https.createServer(options, (req, res) => {
  const proxyReq = http.request(
    {
      hostname: targetUrl.hostname,
      port: Number(targetUrl.port || 3000),
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `127.0.0.1:${targetUrl.port || 3000}` },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );
  proxyReq.on('error', () => {
    if (!res.headersSent) {
      res.writeHead(502, { 'content-type': 'text/plain' });
    }
    res.end('Bad gateway');
  });
  req.pipe(proxyReq);
});
server.listen(port, '0.0.0.0', () => {
  console.log(`tls-proxy: listening on 0.0.0.0:${port}, target ${targetUrl.hostname}:${targetUrl.port || 3000}`);
});
