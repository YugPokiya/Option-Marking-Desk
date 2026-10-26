import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HTTP_REQUESTS = Counter("omd_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("omd_http_request_duration_seconds", "HTTP latency", ["route"])
FITS = Counter("omd_fits_total", "Smile fits", ["method", "arbitrage_free"])
FIT_SECONDS = Histogram(
    "omd_fit_duration_seconds", "Smile fit + marking time", buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")  # template (/chains/{chain_id}) keeps cardinality low
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(path).observe(time.perf_counter() - start)
        return response
