from threading import Lock


class APIMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.request_count = 0
            self.error_count = 0
            self.total_response_time_ms = 0.0
            self.max_response_time_ms = 0.0
            self._routes: dict[str, dict[str, float | int]] = {}

    def record_request(self, *, method: str, path: str, status_code: int, duration_ms: float) -> None:
        route_key = f"{method} {path}"
        with self._lock:
            self.request_count += 1
            if status_code >= 400:
                self.error_count += 1

            self.total_response_time_ms += duration_ms
            self.max_response_time_ms = max(self.max_response_time_ms, duration_ms)

            route_metrics = self._routes.setdefault(
                route_key,
                {"count": 0, "error_count": 0, "total_response_time_ms": 0.0, "max_response_time_ms": 0.0},
            )
            route_metrics["count"] += 1
            if status_code >= 400:
                route_metrics["error_count"] += 1
            route_metrics["total_response_time_ms"] += duration_ms
            route_metrics["max_response_time_ms"] = max(route_metrics["max_response_time_ms"], duration_ms)

    def snapshot(self) -> dict:
        with self._lock:
            average_response_time_ms = self.total_response_time_ms / self.request_count if self.request_count else 0.0
            routes = {
                route: {
                    "count": data["count"],
                    "error_count": data["error_count"],
                    "average_response_time_ms": round(
                        data["total_response_time_ms"] / data["count"], 2
                    ) if data["count"] else 0.0,
                    "max_response_time_ms": round(data["max_response_time_ms"], 2),
                }
                for route, data in sorted(self._routes.items())
            }

            return {
                "request_count": self.request_count,
                "error_count": self.error_count,
                "average_response_time_ms": round(average_response_time_ms, 2),
                "max_response_time_ms": round(self.max_response_time_ms, 2),
                "routes": routes,
            }
