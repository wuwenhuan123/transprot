from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from transprot.core.models import AppConfig, TranslationProvider
from transprot.services.translation import TranslatorRouter


class _TranslationHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        response = {"translatedText": f"translated::{body['q']}"}
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class BasicHttpTranslatorIntegrationTests(unittest.TestCase):
    def test_basic_http_translation_roundtrip(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _TranslationHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            router = TranslatorRouter()
            config = AppConfig(
                translation_provider=TranslationProvider.BASIC_HTTP,
                api_base_url=f"http://127.0.0.1:{server.server_port}",
                timeout_sec=5,
            )
            result = router.translate("hello", config)
            self.assertEqual(result.translated_text, "translated::hello")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
