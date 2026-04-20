/**
 * DX-024: SpanForge PII scan load test — 50 rps sustained
 *
 * Target endpoint: POST /v1/scan/pii
 * SLO:
 *   - p95 latency ≤ 200 ms
 *   - error rate  < 1 %
 *
 * Usage:
 *   k6 run k6/pii_scan_50rps.js
 *   k6 run --env BASE_URL=http://my-server:7464 k6/pii_scan_50rps.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:7464';

export const errorRate = new Rate('error_rate');
export const p95Latency = new Trend('p95_latency', true);

export const options = {
  scenarios: {
    pii_50rps: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 25,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<200'],
    error_rate: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
  },
};

const TEXTS = [
  'Please contact John Doe at john.doe@example.com or (555) 867-5309.',
  'My SSN is 123-45-6789 and my DOB is 01/15/1990.',
  'Ship to: 123 Main St, Springfield, IL 62701.',
  'No PII here — just a routine status check from the load test harness.',
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
  const res = http.post(`${BASE_URL}/v1/scan/pii`, payload, { headers: HEADERS });

  const ok = check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has findings or redacted': (r) => {
      try {
        const body = JSON.parse(r.body);
        return 'findings' in body || 'redacted_text' in body || 'entities' in body;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!ok);
  p95Latency.add(res.timings.duration);
}
