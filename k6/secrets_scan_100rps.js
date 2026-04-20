/**
 * DX-024: SpanForge secrets scan load test — 100 rps sustained
 *
 * Target endpoint: POST /v1/scan/secrets
 * SLO:
 *   - p95 latency ≤ 200 ms
 *   - error rate  < 1 %
 *
 * Usage:
 *   k6 run k6/secrets_scan_100rps.js
 *   k6 run --env BASE_URL=http://my-server:7464 k6/secrets_scan_100rps.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:7464';

export const errorRate = new Rate('error_rate');
export const p95Latency = new Trend('p95_latency', true);

export const options = {
  scenarios: {
    secrets_100rps: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<200'],
    error_rate: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
  },
};

const TEXTS = [
  // Benign text
  'This is a normal log line with no sensitive data.',
  'User requested /api/v1/status — 200 OK in 42ms.',
  // Synthetic secrets (safe to test against — not real credentials)
  'AKIA1234567890ABCDEF is an AWS access key pattern for testing.',
  'ghp_AAAAABBBBBCCCCCDDDDDEEEEE12345 matches GitHub PAT pattern.',
  'sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDE is an OpenAI-style key.',
];

const HEADERS = {
  'Content-Type': 'application/json',
  'X-SF-API-Key': __ENV.SF_API_KEY || 'sfk-local-test-key',
};

let idx = 0;

export default function () {
  const text = TEXTS[idx % TEXTS.length];
  idx++;

  const payload = JSON.stringify({ text });
  const res = http.post(`${BASE_URL}/v1/scan/secrets`, payload, { headers: HEADERS });

  const ok = check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has findings field': (r) => {
      try {
        const body = JSON.parse(r.body);
        return 'findings' in body || 'detected' in body || 'secrets' in body;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!ok);
  p95Latency.add(res.timings.duration);
}
