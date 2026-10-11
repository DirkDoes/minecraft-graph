import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };
const appFiles = new Set(['index.html', 'app.js', 'app.css', 'core.mjs', 'graph-worker.js']);

export function createAppServer() {
  return createServer(async (req, res) => {
    if (!['GET', 'HEAD'].includes(req.method)) {
      res.writeHead(405, { Allow: 'GET, HEAD' }).end('Method not allowed');
      return;
    }
    let relative;
    try {
      relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).slice(1) || 'index.html';
    } catch {
      res.writeHead(400).end('Invalid URL');
      return;
    }
    const filename = path.resolve(root, relative);
    const allowed = appFiles.has(relative) || /^(data|assets)\/[\w./-]+$/.test(relative);
    if (!allowed || !filename.startsWith(root + path.sep) || relative.split('/').includes('..') || !types[path.extname(filename)]) {
      res.writeHead(404).end('Not found');
      return;
    }
    try {
      const body = await readFile(filename);
      res.writeHead(200, {
        'Content-Type': types[path.extname(filename)] + (path.extname(filename) === '.png' ? '' : '; charset=utf-8'),
        'Content-Length': body.length,
        'Cache-Control': relative.startsWith('assets/') ? 'public, max-age=3600' : 'no-cache',
        'X-Content-Type-Options': 'nosniff',
      });
      res.end(req.method === 'HEAD' ? undefined : body);
    } catch (error) {
      const status = ['ENOENT', 'EISDIR', 'ENOTDIR'].includes(error.code) ? 404 : 500;
      res.writeHead(status).end(status === 404 ? 'Not found' : 'Could not read file');
    }
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be an integer from 1 to 65535');
  const server = createAppServer();
  server.on('error', error => {
    console.error(error.code === 'EADDRINUSE' ? `Port ${port} is in use. Set PORT to another port and try again.` : error.message);
    process.exitCode = 1;
  });
  server.listen(port, '127.0.0.1', () => console.log(`Minecraft Graph · http://127.0.0.1:${port}`));
}
