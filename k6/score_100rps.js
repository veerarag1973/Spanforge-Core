/**
 * DX-024: SpanForge scoring pipeline load test — 100 rps sustained
 *
 * Target endpoint: POST /v1/trust/score  (or POST /v1/trust-gate as proxy)
 * SLO:
 *   - p95 latency ≤ 200 ms
 *   - error rate  < 1 %
 *   - http_req_failed rate < 0.01 (1 %)
 *
 * Usage:
 *   k6 run k6/score_100rps.js
 *   k6 run --env BASE_URL=http://my-server:7464 k6/score_100rps.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:7464';

export const errorRate = new Rate('error_rate');
export const p95Latency = new Trend('p95_latency', true);

export const options = {
  scenarios: {
    score_100rps: {
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

const PAYLOAD = JSON.stringify({
  project_id: 'k6-load-test',
  text: 'The capital of France is Paris.',
  context: 'Paris is the capital and most populous city of France.',
  model: 'gpt-4',
});

const HEADERS = {
  'Content-Type': 'application/json',
  'X-SF-API-Key': __ENV.SF_API_KEY || 'sfk-local-test-key',
};

export default function () {
  const res = http.post(`${BASE_URL}/v1/trust-gate`, PAYLOAD, { headers: HEADERS });

  const ok = check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has pass field': (r) => {
      try {
        const body = JSON.parse(r.body);
        return 'pass' in body || 'overall_score' in body;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!ok);
  p95Latency.add(res.timings.duration);
}
