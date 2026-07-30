import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.argv[2] || 'dist/dev-id');
const port = Number(process.env.PORT || process.argv[3] || 4200);
const indexPath = path.join(root, 'index.html');

if (!fs.existsSync(indexPath)) {
  console.error(`Missing ${indexPath}`);
  process.exit(2);
}

const types = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.js', 'application/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'], ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'], ['.jpg', 'image/jpeg'], ['.jpeg', 'image/jpeg'], ['.gif', 'image/gif'],
  ['.svg', 'image/svg+xml'], ['.woff', 'font/woff'], ['.woff2', 'font/woff2'],
  ['.ttf', 'font/ttf'], ['.eot', 'application/vnd.ms-fontobject'], ['.ico', 'image/x-icon'],
]);

function send(res, file, status = 200) {
  const ext = path.extname(file).toLowerCase();
  res.writeHead(status, {
    'Content-Type': types.get(ext) || 'application/octet-stream',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const rel = decodeURIComponent(url.pathname).replace(/^\/+/, '');
  const candidate = path.resolve(root, rel || 'index.html');
  if (!candidate.startsWith(root + path.sep) && candidate !== root) {
    res.writeHead(400); res.end('Bad path'); return;
  }
  try {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return send(res, candidate);
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      const dirIndex = path.join(candidate, 'index.html');
      if (fs.existsSync(dirIndex)) return send(res, dirIndex);
    }
  } catch {}
  return send(res, indexPath);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`SPA server listening on http://127.0.0.1:${port}; root=${root}`);
});
