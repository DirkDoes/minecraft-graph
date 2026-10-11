import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAppServer } from '../server.mjs';

test('serves browser modules and denies private files, traversal and writes', async () => {
  const server = createAppServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const index = await fetch(base + '/');
    assert.equal(index.status, 200);
    assert.match(index.headers.get('content-type'), /^text\/html/);
    assert.match(await index.text(), /<canvas/);
    const head = await fetch(base + '/data/graph.json', { method: 'HEAD' });
    assert.equal(head.status, 200);
    assert.match(head.headers.get('content-type'), /^application\/json/);
    assert.equal(await head.text(), '');
    for (const pathname of ['/server.mjs', '/.cache/client.jar', '/assets/%2e%2e/server.mjs', '/assets/..%5cserver.mjs']) {
      assert.equal((await fetch(base + pathname)).status, 404, pathname);
    }
    assert.equal((await fetch(base + '/app.css', { method: 'POST' })).status, 405);
    assert.equal((await fetch(base + '/%zz')).status, 400);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
