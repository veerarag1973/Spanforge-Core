# Kubernetes deployment guide for spanforge

This guide explains how to run a spanforge-instrumented application on Kubernetes, alongside an OpenTelemetry Collector sidecar.

## Prerequisites

- Kubernetes cluster (1.25+)
- `kubectl` configured
- Docker image built and pushed to your registry

## 1. Build and push the image

```bash
docker build -t registry.example.com/my-org/spanforge-app:v1.0.0 -f examples/docker/Dockerfile .
docker push registry.example.com/my-org/spanforge-app:v1.0.0
```

## 2. Create a Secret for the signing key

```bash
kubectl create secret generic spanforge-secrets \
  --from-literal=SPANFORGE_SIGNING_KEY="$(openssl rand -base64 32)"
```

## 3. Deployment manifest

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spanforge-app
  labels:
    app: spanforge-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: spanforge-app
  template:
    metadata:
      labels:
        app: spanforge-app
      annotations:
        # Prometheus scraping (if metrics endpoint exposed)
        prometheus.io/scrape: "true"
        prometheus.io/port: "8888"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        seccompProfile:
          type: RuntimeDefault

      containers:
        # ── Application container ─────────────────────────────────────────
        - name: app
          image: registry.example.com/my-org/spanforge-app:v1.0.0
          env:
            - name: SPANFORGE_SERVICE_NAME
              value: "spanforge-app"
            - name: SPANFORGE_ENV
              value: "production"
            - name: SPANFORGE_EXPORTER
              value: "otlp"
            - name: SPANFORGE_ENDPOINT
              value: "http://localhost:4318/v1/traces"   # sidecar collector
            - name: SPANFORGE_SAMPLE_RATE
              value: "0.1"
            - name: SPANFORGE_SIGNING_KEY
              valueFrom:
                secretKeyRef:
                  name: spanforge-secrets
                  key: SPANFORGE_SIGNING_KEY
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"

        # ── OTel Collector sidecar ────────────────────────────────────────
        - name: otel-collector
          image: otel/opentelemetry-collector-contrib:0.100.0
          args: ["--config=/conf/otel-config.yaml"]
          volumeMounts:
            - name: otel-config
              mountPath: /conf
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "200m"
              memory: "256Mi"

      volumes:
        - name: otel-config
          configMap:
            name: otel-collector-config
```

## 4. ConfigMap for the OTel Collector

```yaml
# k8s/otel-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
data:
  otel-config.yaml: |
    receivers:
      otlp:
        protocols:
          http:
            endpoint: 0.0.0.0:4318
    processors:
      batch:
        timeout: 2s
    exporters:
      otlp:
        endpoint: <your-backend>:4317
        tls:
          insecure: false
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [otlp]
```

## 5. Apply

```bash
kubectl apply -f k8s/otel-configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl rollout status deployment/spanforge-app
```

## 6. Health checks

Add liveness and readiness probes if your app exposes the spanforge HTTP server (`spanforge serve`):

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8888
  initialDelaySeconds: 5
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8888
  initialDelaySeconds: 3
  periodSeconds: 5
```

## 7. Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: spanforge-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: spanforge-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## See also

- [Docker compose setup](../../examples/docker/docker-compose.yml)
- [Configuration reference](../configuration.md)
- [OTLP integration](../integrations/)

---

## 8. Compliance-grade deployment

For production environments subject to regulatory requirements (EU AI Act,
GDPR, SOC 2, HIPAA), apply the following hardening steps:

### Signing key management

Rotate `SPANFORGE_SIGNING_KEY` regularly. Use an external secret manager
(e.g. HashiCorp Vault, AWS Secrets Manager) synced to Kubernetes Secrets
via the CSI driver:

```yaml
volumes:
  - name: secrets-store
    csi:
      driver: secrets-store.csi.k8s.io
      readOnly: true
      volumeAttributes:
        secretProviderClass: spanforge-signing-key
```

### WORM-compatible audit storage

Route signed audit chains to write-once storage for tamper-proof
evidence retention:

```yaml
exporters:
  otlp:
    endpoint: <compliance-backend>:4317
  awss3:
    s3_bucket: spanforge-audit-worm
    s3_prefix: "audit-chains/"
    marshaler: otlp_json
```

### Network policies

Restrict egress to only the compliance backend and OTel collector:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: spanforge-egress
spec:
  podSelector:
    matchLabels:
      app: spanforge-app
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: otel-collector
      ports:
        - port: 4318
```

### Compliance verification

Add a post-deployment check that verifies audit chain integrity:

```bash
kubectl exec deploy/spanforge-app -- python -m spanforge.signing verify-chain \
  --source otlp --last 1000
```
