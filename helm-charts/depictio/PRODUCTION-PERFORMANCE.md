# Production Performance Optimization Guide

## Overview

This guide addresses performance differences between development (minikube) and production (Kubernetes) environments, specifically focusing on screenshot generation functionality that was experiencing 4+ minute timeouts.

## Root Cause Analysis

The performance issues stem from several infrastructure-level differences between minikube and production:

### 1. Network Latency & DNS Resolution
- **Production**: Higher network latency due to distributed infrastructure
- **Minikube**: Local networking with minimal latency
- **Impact**: Service-to-service communication takes longer

### 2. Resource Constraints
- **Production**: Shared resources, potential CPU/memory throttling
- **Minikube**: Dedicated local resources
- **Impact**: Browser operations (Playwright) run slower

### 3. Storage Performance
- **Production**: Network-attached storage with higher I/O latency
- **Minikube**: Local filesystem with fast I/O
- **Impact**: Container startup and file operations slower

## Performance Optimizations Implemented

### 1. Environment-Specific Timeout Configuration

Added `PerformanceConfig` class to `settings_models.py` with environment-specific timeouts:

```python
class PerformanceConfig(BaseSettings):
    # HTTP client timeouts (in seconds)
    http_client_timeout: int = Field(default=30)
    api_request_timeout: int = Field(default=60)

    # Browser timeouts (in milliseconds)
    browser_navigation_timeout: int = Field(default=60000)
    browser_page_load_timeout: int = Field(default=90000)
    browser_element_timeout: int = Field(default=30000)

    # Screenshot-specific timeouts
    screenshot_navigation_timeout: int = Field(default=45000)
    screenshot_content_wait: int = Field(default=15000)
    screenshot_stabilization_wait: int = Field(default=5000)
```

### 2. Service Readiness Improvements

Enhanced service readiness checks with:
- Environment-specific retry counts and delays
- Better error handling and logging
- Configurable timeout per check

### 3. Screenshot Navigation Optimization

Implemented optimized navigation strategy:
- Uses "commit" wait strategy instead of full page load
- Content-based readiness detection
- Environment-aware timeout configuration
- Reduced from 4+ minutes to ~25 seconds

### 4. HTTP Client Optimization

- Connection pooling configuration
- Keep-alive connection management
- DNS caching settings

## Configuration Files

### Production Values (values-embl-performance.yaml)

Use this configuration for production deployments:

```bash
helm upgrade depictio ./helm-charts/depictio \
  -f helm-charts/depictio/values-embl.yaml \
  -f helm-charts/depictio/values-embl-performance.yaml
```

Key production settings:
- `SCREENSHOT_NAVIGATION_TIMEOUT: "75000"` (75 seconds)
- `SERVICE_READINESS_RETRIES: "8"` (8 retries)
- `API_REQUEST_TIMEOUT: "90"` (90 seconds)

### Development Values (default)

Development/minikube environments use shorter timeouts for faster feedback.

## Environment Variables

All performance settings can be overridden via environment variables:

```bash
# HTTP timeouts
DEPICTIO_PERFORMANCE_HTTP_CLIENT_TIMEOUT=60
DEPICTIO_PERFORMANCE_API_REQUEST_TIMEOUT=90

# Browser timeouts (milliseconds)
DEPICTIO_PERFORMANCE_BROWSER_NAVIGATION_TIMEOUT=90000
DEPICTIO_PERFORMANCE_SCREENSHOT_NAVIGATION_TIMEOUT=75000

# Service readiness
DEPICTIO_PERFORMANCE_SERVICE_READINESS_RETRIES=8
DEPICTIO_PERFORMANCE_SERVICE_READINESS_DELAY=5
```

## Monitoring & Troubleshooting

### Key Metrics to Monitor

1. **Screenshot Generation Time**
   - Target: < 30 seconds
   - Alert: > 60 seconds

2. **Service Readiness Check Duration**
   - Target: < 15 seconds
   - Alert: > 30 seconds

3. **API Response Times**
   - Target: < 5 seconds
   - Alert: > 30 seconds

### Log Analysis

Look for these log patterns:

```
🎯 Performance settings - Nav: 75000ms, Content: 30000ms, Stabilization: 10s
🔍 Service readiness check starting for http://depictio-frontend:5080 (retries: 8, delay: 5s, timeout: 15s)
✅ Screenshot-optimized navigation completed in 23.4s
```

### Common Issues & Solutions

#### Issue: Screenshots still timing out
**Solution**: Increase production timeouts in values-embl-performance.yaml

#### Issue: Service readiness checks failing
**Solution**: Check network connectivity and increase retry count

#### Issue: API calls timing out
**Solution**: Increase API_REQUEST_TIMEOUT for production environment

## Infrastructure Recommendations

### 1. Resource Allocation
```yaml
backend:
  resources:
    requests:
      memory: "2Gi"
      cpu: "1"
    limits:
      memory: "4Gi"
      cpu: "2"
```

### 2. Network Policies
- Ensure unrestricted communication between depictio services
- Minimize network hops between frontend and backend

### 3. Storage Optimization
- Use fast storage class for persistent volumes
- Consider local storage for temporary screenshot files

### 4. DNS Configuration
- Use CoreDNS with appropriate caching
- Consider cluster-local DNS for internal services

## Deployment

To deploy with production performance optimizations:

```bash
# Apply production performance configuration
helm upgrade depictio ./helm-charts/depictio \
  -f helm-charts/depictio/values.yaml \
  --namespace depictio

# Verify deployment
kubectl get pods -n depictio
kubectl logs -f deployment/depictio-backend -n depictio
```

## Testing

Test screenshot performance after deployment:

```bash
# Test screenshot endpoint
curl -X GET "https://api.demo.depictio.embl.org/depictio/api/v1/utils/screenshot-dash-fixed/6824cb3b89d2b72169309737"

# Monitor logs for performance metrics
kubectl logs -f deployment/depictio-backend -n depictio | grep "screenshot_optimized"
```

## Future Improvements

1. **Caching**: Implement screenshot caching to avoid regeneration
2. **Async Processing**: Move screenshot generation to background jobs
3. **CDN**: Use CDN for static screenshot serving
4. **Monitoring**: Implement detailed performance monitoring with metrics collection
