import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from socketserver import ThreadingMixIn
import threading
from typing import Any, Optional, Union

import cv2
import numpy as np
import requests
from ultralytics import YOLO

_inference_lock = threading.Lock()


class NavigationBackendHandler(BaseHTTPRequestHandler):
    model: Optional[Any] = None
    osrm_url: str = "http://localhost:5000"
    fallback_osrm_url: str = "https://router.project-osrm.org"

    def _send(
        self,
        code: int,
        payload: Union[dict, bytes],
        content_type: str = "application/json",
    ) -> None:
        """Unified helper to send HTTP responses with socket error handling."""
        try:
            self.send_response(code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Type", content_type)
            self.end_headers()
            body = (
                json.dumps(payload).encode("utf-8")
                if isinstance(payload, dict)
                else payload
            )
            self.wfile.write(body)
        except (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
            OSError,
        ):
            pass

    def do_OPTIONS(self) -> None:
        self._send(200, b"")

    def do_POST(self) -> None:
        if self.path != "/detect":
            return self._send(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_b64 = json.loads(self.rfile.read(length).decode("utf-8")).get(
                "image", ""
            )
            if not raw_b64:
                return self._send(400, {"error": "Missing image"})

            frame = cv2.imdecode(
                np.frombuffer(
                    base64.b64decode(raw_b64.split(",", 1)[-1]), np.uint8
                ),
                cv2.IMREAD_COLOR,
            )

            status = None
            if frame is not None and self.model is not None:
                with _inference_lock:
                    results = self.model.predict(
                        cv2.resize(frame, (640, 640)), verbose=False
                    )[0]

                boxes: Any = results.boxes
                detected = (
                    {self.model.names[int(box.cls[0])] for box in boxes}
                    if boxes is not None
                    else set()
                )

                if "Red" in detected:
                    status = "stop, red light"
                elif "Yellow" in detected:
                    status = "stop, yellow light"
                elif "Green" in detected:
                    status = "go, green light"

            self._send(200, {"status": status})
        except (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
            OSError,
        ):
            pass
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_GET(self) -> None:
        if not self.path.startswith("/route/"):
            return self._send(404, {"error": "Not found"})
        
        # Try local OSRM first
        primary_target = f"{self.osrm_url.rstrip('/')}{self.path}"
        try:
            resp = requests.get(primary_target, timeout=3)
            if resp.status_code == 200:
                return self._send(
                    resp.status_code,
                    resp.content,
                    resp.headers.get("Content-Type", "application/json"),
                )
        except Exception:
            pass

        # Automatic failover to public demo OSRM if local instance is unavailable
        fallback_target = f"{self.fallback_osrm_url.rstrip('/')}{self.path}"
        try:
            resp = requests.get(fallback_target, timeout=8)
            self._send(
                resp.status_code,
                resp.content,
                resp.headers.get("Content-Type", "application/json"),
            )
        except Exception as e:
            self._send(502, {"error": f"OSRM Routing Error: {e}"})

    def log_message(self, format: str, *args: Any) -> None:
        return


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def run_backend_server(
    model_path: str, osrm_url: str, port: int = 5001
) -> None:
    handler = NavigationBackendHandler
    handler.model = YOLO(model_path)
    handler.osrm_url = osrm_url
    ThreadedHTTPServer(("0.0.0.0", port), handler).serve_forever()