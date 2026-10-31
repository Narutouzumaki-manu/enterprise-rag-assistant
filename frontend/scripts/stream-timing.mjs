// frontend/scripts/stream-timing.mjs
// Diagnostic script to measure whether POST /chat/stream arrives progressively through the Vite dev proxy.

import { performance } from 'node:perf_hooks';

const EMAIL = process.env.TEST_EMAIL;
const PASSWORD = process.env.TEST_PASSWORD;
const QUESTION = process.env.QUESTION || 'What was the total revenue reported?';

if (!EMAIL || !PASSWORD) {
  console.error('Error: TEST_EMAIL and TEST_PASSWORD environment variables must be set.');
  process.exit(1);
}

const BASES = ['http://127.0.0.1:8000', 'http://localhost:5173'];

function getTimeoutSignal(ms = 300_000) {
  if (typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(ms);
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(new Error('Request timed out')), ms);
  return controller.signal;
}

function parseEventsFromChunk(chunkText) {
  const events = [];
  let keepAlives = 0;
  const lines = chunkText.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith(':') && trimmed.includes('keep-alive')) {
      keepAlives++;
    } else if (trimmed.startsWith('event:')) {
      const eventName = trimmed.slice(6).trim();
      if (eventName) {
        events.push(eventName);
      }
    }
  }
  return { events, keepAlives };
}

async function testBase(base) {
  console.log(`\n========================================`);
  console.log(`Testing BASE: ${base}`);
  console.log(`========================================`);

  // Step a: Login
  console.log(`1. Logging in to ${base}/auth/login...`);
  let loginRes;
  try {
    loginRes = await fetch(`${base}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
      signal: getTimeoutSignal(300_000),
    });
  } catch (err) {
    console.error(`Connection failed for ${base}: ${err.message}`);
    return null;
  }

  if (loginRes.status === 401) {
    console.error('login failed');
    process.exit(1);
  }

  if (!loginRes.ok) {
    console.error(`Login failed with HTTP ${loginRes.status} ${loginRes.statusText}`);
    return null;
  }

  const loginData = await loginRes.json();
  const token = loginData.access_token;
  if (!token) {
    console.error('No access_token returned in login response.');
    return null;
  }
  console.log('Login successful.');

  // Step b: Create session
  console.log(`2. Creating session at ${base}/sessions...`);
  let sessionRes;
  try {
    sessionRes = await fetch(`${base}/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
      signal: getTimeoutSignal(300_000),
    });
  } catch (err) {
    console.error(`Session creation failed for ${base}: ${err.message}`);
    return null;
  }

  if (!sessionRes.ok) {
    console.error(`Session creation failed with HTTP ${sessionRes.status}`);
    return null;
  }

  const sessionData = await sessionRes.json();
  const sessionId = sessionData.session_id;
  if (!sessionId) {
    console.error('No session_id returned from session creation.');
    return null;
  }
  console.log(`Session created: ${sessionId}`);

  // Step c: Stream chat
  console.log(`3. Streaming POST ${base}/chat/stream...`);
  console.log(`Question: "${QUESTION}"\n`);

  const reqStart = performance.now();
  let streamRes;
  try {
    streamRes = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: sessionId,
        query: QUESTION,
      }),
      signal: getTimeoutSignal(300_000),
    });
  } catch (err) {
    console.error(`Stream request failed for ${base}: ${err.message}`);
    return null;
  }

  if (!streamRes.ok) {
    console.error(`Stream request failed with HTTP ${streamRes.status} ${streamRes.statusText}`);
    return null;
  }

  if (!streamRes.body) {
    console.error('Response has no body.');
    return null;
  }

  // Step d & e: Read chunks
  const reader = streamRes.body.getReader();
  const decoder = new TextDecoder();
  const chunks = [];
  let totalKeepAlives = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const timeMs = Math.round(performance.now() - reqStart);
      const byteLength = value ? value.byteLength : 0;
      const text = decoder.decode(value, { stream: true });
      const { events, keepAlives } = parseEventsFromChunk(text);
      totalKeepAlives += keepAlives;

      chunks.push({
        timeMs,
        bytes: byteLength,
        events,
      });

      console.log(`+${timeMs}ms  ${byteLength}B  events=[${events.join(',')}]`);
    }
  } catch (err) {
    console.error(`Error reading stream from ${base}: ${err.message}`);
    return null;
  }

  // Step f: Print summary
  const totalChunks = chunks.length;
  const timeFirst = totalChunks > 0 ? chunks[0].timeMs : 0;
  const timeLast = totalChunks > 0 ? chunks[totalChunks - 1].timeMs : 0;
  const spread = totalChunks > 0 ? timeLast - timeFirst : 0;

  let distinctArrivalTimes = 0;
  let lastCountedTime = -Infinity;
  for (const c of chunks) {
    if (c.timeMs - lastCountedTime > 100) {
      distinctArrivalTimes++;
      lastCountedTime = c.timeMs;
    }
  }

  const contentType = streamRes.headers.get('content-type') || '(none)';
  const cacheControl = streamRes.headers.get('cache-control') || '(none)';
  const xAccelBuffering = streamRes.headers.get('x-accel-buffering') || '(none)';
  const contentEncoding = streamRes.headers.get('content-encoding') || '(none)';
  const transferEncoding = streamRes.headers.get('transfer-encoding') || '(none)';

  console.log(`\n--- Summary for ${base} ---`);
  console.log(`Total chunks:             ${totalChunks}`);
  console.log(`Keep-alive lines ignored: ${totalKeepAlives}`);
  console.log(`Time of first chunk:      ${timeFirst} ms`);
  console.log(`Time of last chunk:       ${timeLast} ms`);
  console.log(`Spread (last - first):    ${spread} ms`);
  console.log(`Distinct arrival times:   ${distinctArrivalTimes} (>100 ms apart)`);
  console.log(`Status:                   ${streamRes.status}`);
  console.log(`content-type:             ${contentType}`);
  console.log(`cache-control:            ${cacheControl}`);
  console.log(`x-accel-buffering:        ${xAccelBuffering}`);
  console.log(`content-encoding:         ${contentEncoding}`);
  console.log(`transfer-encoding:        ${transferEncoding}`);

  return {
    base,
    totalChunks,
    timeFirst,
    timeLast,
    spread,
    distinctArrivalTimes,
  };
}

async function main() {
  const results = {};

  for (const base of BASES) {
    results[base] = await testBase(base);
  }

  console.log(`\n========================================`);
  console.log(`VERDICT ANALYSIS`);
  console.log(`========================================`);

  const direct = results['http://127.0.0.1:8000'];
  const proxy = results['http://localhost:5173'];

  if (!direct || !proxy) {
    const missing = [];
    if (!direct) missing.push('http://127.0.0.1:8000 (direct)');
    if (!proxy) missing.push('http://localhost:5173 (proxy)');
    console.log(`VERDICT: INCONCLUSIVE (${missing.join(' and ')} failed or was unreachable)`);
    return;
  }

  console.log(`Direct (8000):  spread=${direct.spread}ms, distinctTimes=${direct.distinctArrivalTimes}, chunks=${direct.totalChunks}`);
  console.log(`Proxy  (5173):  spread=${proxy.spread}ms, distinctTimes=${proxy.distinctArrivalTimes}, chunks=${proxy.totalChunks}`);
  console.log(`Spread ratio:   ${direct.spread > 0 ? (proxy.spread / direct.spread * 100).toFixed(1) : 0}% (proxy spread / direct spread)`);

  // PROGRESSIVE: proxy spread >= 50% of direct spread AND proxy has at least 3 distinct arrival times
  if (direct.spread > 0 && proxy.spread >= 0.5 * direct.spread && proxy.distinctArrivalTimes >= 3) {
    console.log(`VERDICT: PROGRESSIVE`);
    console.log(`Proxy spread (${proxy.spread} ms) >= 50% of direct spread (${direct.spread} ms) and proxy has ${proxy.distinctArrivalTimes} distinct arrival times (>= 3).`);
  }
  // BUFFERED: proxy delivered everything within 300 ms of its first chunk while direct was spread over > 1500 ms
  else if (proxy.spread <= 300 && direct.spread > 1500) {
    console.log(`VERDICT: BUFFERED`);
    console.log(`Proxy spread (${proxy.spread} ms) <= 300 ms while direct spread was ${direct.spread} ms (> 1500 ms).`);
  }
  // INCONCLUSIVE
  else {
    let reason = 'spread or timing patterns did not clearly meet PROGRESSIVE or BUFFERED criteria';
    if (direct.spread <= 1500) {
      reason = `the direct run was too fast (direct spread was ${direct.spread} ms <= 1500 ms)`;
    } else if (proxy.distinctArrivalTimes < 3) {
      reason = `proxy had only ${proxy.distinctArrivalTimes} distinct arrival times (< 3)`;
    } else if (proxy.spread < 0.5 * direct.spread) {
      reason = `proxy spread (${proxy.spread} ms) was < 50% of direct spread (${direct.spread} ms)`;
    }
    console.log(`VERDICT: INCONCLUSIVE (${reason})`);
  }
}

main().catch((err) => {
  console.error('Fatal error in diagnostic script:', err);
  process.exit(1);
});

