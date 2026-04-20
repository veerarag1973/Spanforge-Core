# SpanForge k6 Load Tests (DX-024)
#
# Requirements:
#   k6 >= 0.50  (https://k6.io/docs/getting-started/installation/)
#   SpanForge server running on localhost:7464
#     docker compose -f docker-compose.selfhosted.yml up -d
#
# Run individual scripts:
#   k6 run k6/score_100rps.js
#   k6 run k6/pii_scan_50rps.js
#   k6 run k6/secrets_scan_100rps.js
#
# SLO thresholds (enforced in each script):
#   p95 latency  ≤ 200 ms
#   error rate   < 1 %
#   HTTP 2xx     ≥ 99 %
