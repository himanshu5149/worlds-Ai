"""Prometheus metrics (prometheus_client) + OTel tracing bootstrap."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response


class Metrics:
    def __init__(self):
        self.chat_requests = Counter(
            "prism_chat_requests_total", "Chat requests by outcome", ["outcome"]
        )
        self.request_latency = Histogram(
            "prism_request_latency_seconds",
            "End-to-end chat latency",
            buckets=(0.5, 1, 2, 4, 8, 12, 20, 30, 60),
        )
        self.model_latency = Histogram(
            "prism_model_latency_seconds", "Per-model latency", ["model_id"],
            buckets=(0.25, 0.5, 1, 2, 4, 8, 12, 20, 30, 60),
        )
        self.model_invocations = Counter(
            "prism_model_invocations_total", "Invocation outcomes", ["model_id", "status"]
        )
        self.provider_errors = Counter(
            "prism_provider_errors_total", "Typed provider failures", ["provider", "error_type"]
        )
        self.model_status = Gauge(
            "prism_model_status", "Health-manager status value", ["model_id"]
        )
        self.cache_hits = Counter("prism_cache_hits_total", "Semantic cache hits")
        self.cache_misses = Counter("prism_cache_misses_total", "Semantic cache misses")
        self.feedback_ratings = Counter(
            "prism_feedback_total", "User feedback", ["rating"]
        )
        self.fused_answers = Counter("prism_fused_answers_total", "Fused final answers")
        self.fallback_events = Counter(
            "prism_fallback_events_total", "Fallback chain activations", ["stage"]
        )

    def observe_chat(self, outcome: str, latency_s: float) -> None:
        self.chat_requests.labels(outcome=outcome).inc()
        self.request_latency.observe(latency_s)


_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type="text/plain; version=0.0.4")


def init_tracing(settings) -> None:
    """Best-effort OpenTelemetry bootstrap (disabled by default)."""
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "prism-api"}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
        )
        trace.set_tracer_provider(provider)
    except ImportError:
        pass
