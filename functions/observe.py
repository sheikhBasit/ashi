"""
Observability for ASHI — emits OpenTelemetry spans to Langfuse.
Every TCU step is a span. Every LLM call is a child span.
"""
import base64
import os
import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

_tracer: Optional[trace.Tracer] = None
_metrics_path = os.path.expanduser("~/.ashi/metrics.prom")


def _b64(pk: str, sk: str) -> str:
    return base64.b64encode(f"{pk}:{sk}".encode()).decode()


def _get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "pk-lf-local")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "sk-lf-local")

        exporter = OTLPSpanExporter(
            endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
            headers={
                "Authorization": f"Basic {_b64(public_key, secret_key)}",
                "Content-Type": "application/x-protobuf",
            },
        )
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ashi")
    return _tracer


class TCUTrace:
    """Context manager that wraps a full TCU execution as an OTel trace."""

    def __init__(self, tcu_id: str, intent: str, model: str):
        self.tcu_id = tcu_id
        self.intent = intent
        self.model = model
        self._span = None

    def __enter__(self):
        tracer = _get_tracer()
        self._span = tracer.start_span(f"tcu.{self.tcu_id}")
        self._span.set_attribute("ashi.tcu_id", self.tcu_id)
        self._span.set_attribute("ashi.intent", self.intent)
        self._span.set_attribute("ashi.model", self.model)
        return self

    def __exit__(self, exc_type, exc_val, _exc_tb):
        if self._span:
            if exc_type:
                self._span.set_attribute("ashi.error", str(exc_val))
            self._span.end()

    @contextmanager
    def step_span(self, step_name: str, skill: Optional[str] = None):
        tracer = _get_tracer()
        ctx = trace.set_span_in_context(self._span)
        with tracer.start_as_current_span(f"step.{step_name}", context=ctx) as span:
            if skill:
                span.set_attribute("ashi.skill", skill)
            yield span


def emit_metric(name: str, value: float, labels: Optional[dict] = None) -> None:
    """Append a Prometheus-format metric line to ~/.ashi/metrics.prom."""
    label_str = ""
    if labels:
        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    line = f"{name}{label_str} {value} {int(time.time() * 1000)}\n"
    os.makedirs(os.path.dirname(_metrics_path), exist_ok=True)
    with open(_metrics_path, "a") as f:
        f.write(line)
