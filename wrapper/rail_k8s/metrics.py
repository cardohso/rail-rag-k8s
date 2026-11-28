"""Prometheus metrics. Names start with rail_ so dashboards and alerts can find them."""

from prometheus_client import Counter, Gauge, Histogram

LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0)

HTTP_REQUESTS = Counter(
    "rail_http_requests_total", "HTTP requests by route and status.", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "rail_http_request_duration_seconds",
    "HTTP request duration by route.",
    ["route"],
    buckets=LATENCY_BUCKETS,
)
# What autoscaling watches: requests being handled right now in this pod.
IN_FLIGHT = Gauge("rail_http_requests_in_flight", "Requests currently being handled.")

GENERATOR_CALLS = Counter(
    "rail_generator_calls_total", "Generator (LLM) calls by outcome.", ["outcome"]
)
GENERATOR_DURATION = Histogram(
    "rail_generator_call_duration_seconds",
    "Duration of one generator call.",
    buckets=LATENCY_BUCKETS,
)
EMBED_DURATION = Histogram(
    "rail_embed_query_duration_seconds",
    "Query embedding time (CPU in this process).",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
RETRIEVAL_DURATION = Histogram(
    "rail_retrieval_duration_seconds",
    "Qdrant search time as seen by the api.",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0),
)
# One per answered /ask: "answered", or upstream's refusal reason (four fixed values, so the label
# stays small: low_retrieval_score, no_relevant_passages, insufficient_context, no_citations).
ASK_OUTCOMES = Counter("rail_ask_outcomes_total", "Answered or refused /ask requests, by reason.", ["outcome"])
BACKEND_ERRORS = Counter("rail_backend_errors_total", "Failed calls to a backend.", ["backend"])

READY = Gauge("rail_ready", "1 when this pod finished startup and can serve.")
STARTUP_SECONDS = Gauge("rail_startup_seconds", "Seconds from process start until ready.")
