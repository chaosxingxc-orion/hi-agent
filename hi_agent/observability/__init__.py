"""Observability package exports."""

from hi_agent.observability.collector import (
    Alert,
    AlertRule,
    MetricsCollector,
    default_alert_rules,
    get_metrics_collector,
    set_metrics_collector,
)
from hi_agent.observability.fallback import (
    FallbackTaxonomy,
    append_fallback_event,
    clear_fallback_events,
    get_fallback_events,
    record_fallback,
    record_llm_request,
)
from hi_agent.observability.metrics import (
    RunMetricsRecord,
    aggregate_counters,
    avg_token_per_run,
    p95_latency,
    run_success_rate,
)
from hi_agent.observability.notification import (
    InMemoryNotificationBackend,
    NotificationBackend,
    format_webhook_payload,
    send_notification,
)
from hi_agent.observability.trace_context import TraceContext as PropagatedTraceContext
from hi_agent.observability.trace_context import TraceContextManager
from hi_agent.observability.tracing import SpanRecord, TraceContext, Tracer

__all__ = [
    "Alert",
    "AlertRule",
    "FallbackTaxonomy",
    "InMemoryNotificationBackend",
    "MetricsCollector",
    "NotificationBackend",
    "PropagatedTraceContext",
    "RunMetricsRecord",
    "SpanRecord",
    "TraceContext",
    "TraceContextManager",
    "Tracer",
    "aggregate_counters",
    "append_fallback_event",
    "avg_token_per_run",
    "clear_fallback_events",
    "default_alert_rules",
    "format_webhook_payload",
    "get_fallback_events",
    "get_metrics_collector",
    "p95_latency",
    "record_fallback",
    "record_llm_request",
    "run_success_rate",
    "send_notification",
    "set_metrics_collector",
]
