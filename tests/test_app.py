"""Behavior and local-service security checks. No X account or network required."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def waiting_fixture_worker(_kind, _payload, events):
    """A cancellable subprocess fixture; it never reads network or user data."""
    os.setsid()
    events.put(("update", {"message": "synthetic worker ready"}))
    while True:
        time.sleep(0.05)


def publishing_fixture_worker(_kind, payload, events):
    """Publish fixture bytes to exercise storage and HTTP, without an X request."""
    os.setsid()
    output = Path(payload["work_dir"]) / "final.mp4"
    output.write_bytes(b"synthetic MP4 fixture bytes" * 50)
    events.put(("done", {"path": str(output), "filename": "collision.mp4"}))


class URLTests(unittest.TestCase):
    def test_normalizes_supported_public_post_links(self):
        cases = {
            "https://x.com/example/status/123456789?s=20": "https://x.com/example/status/123456789",
            "https://twitter.com/example/status/123456789#fragment": "https://x.com/example/status/123456789",
            "https://x.com/example/status/123456789/video/1": "https://x.com/example/status/123456789",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(app.normalize_url(source), expected)

    def test_rejects_urls_that_could_escape_the_x_allowlist(self):
        bad_urls = [
            "https://x.com.evil.invalid/example/status/123",
            "https://evilx.com/example/status/123",
            "https://x.com@evil.invalid/example/status/123",
            "https://evil@x.com/example/status/123",
            "https://x.com:8443/example/status/123",
            "https://x.com:443/example/status/123",
            "http://127.0.0.1/example/status/123",
            "http://localhost/example/status/123",
            "file:///etc/passwd",
            "ftp://x.com/example/status/123",
            "https://x.com/example/status/not-a-number",
            "https://x.com/example/status/123/../../secret",
            "https://x.com/example/status/123%2f..%2fsecret",
            "https://x.com/example",
        ]
        for source in bad_urls:
            with self.subTest(source=source):
                with self.assertRaises(app.UserError):
                    app.normalize_url(source)


def video_format(format_id, width=1280, height=720, fps=30, tbr=1000, **extra):
    result = {
        "format_id": format_id,
        "url": "https://video.example.invalid/" + format_id + ".mp4",
        "ext": "mp4",
        "vcodec": "avc1.64001f",
        "acodec": "mp4a.40.2",
        "protocol": "https",
        "width": width,
        "height": height,
        "fps": fps,
        "tbr": tbr,
    }
    result.update(extra)
    return result


class FormatTests(unittest.TestCase):
    def test_filters_unusable_formats_and_orders_by_resolution_fps_bitrate(self):
        entry = {
            "id": "test-video",
            "title": "Synthetic test video",
            "duration": 3,
            "formats": [
                video_format("720"),
                video_format("1080-low", 1920, 1080, 30, 2000),
                video_format("1080-high", 1920, 1080, 60, 4000),
                video_format("2160", 3840, 2160, 30, 7000),
                video_format("audio", width=None, height=None, vcodec="none", ext="m4a"),
                video_format("webm", ext="webm", vcodec="vp9"),
                video_format("drm", has_drm=True),
                video_format("invalid-protocol", protocol="rtmp"),
            ],
        }
        result = app.make_video(entry)
        self.assertEqual(result["id"], "test-video")
        self.assertEqual([fmt["id"] for fmt in result["formats"]], ["2160", "1080-high", "1080-low", "720"])
        self.assertEqual(result["duration"], 3)
        self.assertTrue(all(fmt.get("label") for fmt in result["formats"]))

    def test_keeps_hls_and_unknown_dimensions_with_real_video_codec(self):
        entry = {
            "id": "hls-video",
            "title": "HLS example",
            "formats": [
                video_format("hls", protocol="m3u8_native", url="https://video.example.invalid/master.m3u8"),
                video_format("unknown", width=None, height=None),
            ],
        }
        result = app.make_video(entry)
        self.assertEqual({fmt["id"] for fmt in result["formats"]}, {"hls", "unknown"})

    def test_drm_only_and_audio_only_are_not_download_choices(self):
        for unusable in [video_format("drm", has_drm=True), video_format("audio", vcodec="none")]:
            with self.subTest(format=unusable["format_id"]):
                with self.assertRaises(app.UserError):
                    app.make_video({"id": "none", "title": "Unavailable", "formats": [unusable]})

    def test_equal_resolution_and_fps_uses_bitrate(self):
        result = app.make_video({"id": "same", "formats": [video_format("low", tbr=700), video_format("high", tbr=1900)]})
        self.assertEqual([fmt["id"] for fmt in result["formats"]], ["high", "low"])

    def test_equal_resolution_prefers_hls_over_higher_direct_bitrate(self):
        result = app.make_video({"id": "same", "formats": [
            video_format("direct", tbr=9000),
            video_format("hls", tbr=1000, protocol="m3u8_native", url="https://video.example.invalid/playlist.m3u8"),
        ]})
        self.assertEqual([fmt["id"] for fmt in result["formats"]], ["hls", "direct"])


class ErrorTests(unittest.TestCase):
    def test_common_errors_are_distinct_and_localized(self):
        examples = [
            ("login", "This video requires login"),
            ("access", "This tweet is private"),
            ("unavailable", "This tweet has been deleted"),
            ("no_video", "No video could be found in this tweet"),
            ("drm", "This video is DRM protected"),
            ("network", "Unable to download webpage: timed out"),
            ("network", "Unable to connect to proxy: Tunnel connection failed: 503 Service Unavailable"),
            ("network", "Unable to download JSON metadata: HTTP Error 503: Service Unavailable"),
            ("network", "HTTP Error 502: Bad Gateway"),
            ("rate_limit", "HTTP Error 429: Too Many Requests"),
            ("ffmpeg", "ffmpeg not found. Please install or provide the path"),
            ("storage", "No space left on device"),
        ]
        for expected, message in examples:
            with self.subTest(error=expected):
                result = app.friendly_error(RuntimeError(message))
                self.assertEqual(result["code"], expected)
                self.assertRegex(result["message"], r"[\u4e00-\u9fff]")

    def test_unknown_error_has_a_safe_chinese_fallback(self):
        result = app.friendly_error(RuntimeError("Unexpected extraction failure"))
        self.assertEqual(result["code"], "extractor")
        self.assertRegex(result["message"], r"[\u4e00-\u9fff]")


class CancellationTests(unittest.TestCase):
    def test_cancel_stops_worker_and_cleans_only_its_temporary_files(self):
        with tempfile.TemporaryDirectory(prefix="x-video-lab-cancel-") as temporary:
            directory = Path(temporary)
            preserved = directory / "existing.mp4"
            preserved.write_bytes(b"existing user file")
            state = app.AppState(directory)
            try:
                with patch.object(app, "worker", waiting_fixture_worker):
                    job_id = state.start_job("download", {"url": "https://x.com/example/status/123"})
                job = state.jobs[job_id]
                work = Path(job["work_dir"])
                (work / "partial.mp4.part").write_bytes(b"partial test file")
                deadline = time.monotonic() + 5
                while state.public_job(job_id)["message"] != "synthetic worker ready" and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertEqual(state.public_job(job_id)["message"], "synthetic worker ready")
                state.cancel(job_id)
                state.cancel(job_id)  # Repeated cancellation is harmless.
                self.assertEqual(state.public_job(job_id)["status"], "cancelled")
                self.assertFalse(job["process"].is_alive())
                deadline = time.monotonic() + 3
                while work.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(work.exists())
                self.assertEqual(preserved.read_bytes(), b"existing user file")
                public = state.public_job(job_id)
                self.assertNotIn("process", public)
                self.assertNotIn("work_dir", public)
                self.assertFalse(state.files)
            finally:
                state.close()


class HTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="x-video-lab-tests-")
        cls.directory = Path(cls.temp.name)
        cls.state = app.AppState(cls.directory / "downloads")
        cls.server = app.LocalServer(("127.0.0.1", 0), cls.state)
        cls.port = cls.server.server_address[1]
        cls.origin = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.state.close()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        if headers:
            request_headers.update(headers)
        body = json.dumps(payload).encode() if payload is not None else b""
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
            request_headers["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True)
            for key, value in request_headers.items():
                if value is not None:
                    connection.putheader(key, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def authorized_headers(self):
        return {"Origin": self.origin, "X-CSRF-Token": self.state.csrf}

    def test_status_can_be_read_without_csrf(self):
        status, headers, body = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertIsInstance(json.loads(body), dict)

    def test_bad_host_and_absent_host_are_rejected(self):
        for host in ["attacker.invalid", "127.0.0.1.attacker.invalid", f"localhost:{self.port + 1}", None]:
            with self.subTest(host=host):
                status, _, _ = self.request("GET", "/api/status", headers={"Host": host})
                self.assertIn(status, {400, 403, 421})

    def test_mutation_requires_csrf(self):
        for token in [None, "wrong-token"]:
            with self.subTest(token=token):
                status, _, _ = self.request("POST", "/api/inspect", {"url": "invalid"}, {"Origin": self.origin, "X-CSRF-Token": token})
                self.assertEqual(status, 403)

    def test_mutation_rejects_foreign_origin_even_with_valid_token(self):
        for origin in ["https://attacker.invalid", f"http://127.0.0.1:{self.port + 1}", "null"]:
            with self.subTest(origin=origin):
                status, _, _ = self.request("POST", "/api/inspect", {"url": "invalid"}, {"Origin": origin, "X-CSRF-Token": self.state.csrf})
                self.assertEqual(status, 403)

    def test_authorized_invalid_url_fails_without_a_download(self):
        status, _, body = self.request("POST", "/api/inspect", {"url": "https://attacker.invalid/video"}, self.authorized_headers())
        self.assertIn(status, {400, 422})
        self.assertRegex(body.decode(), r"[\u4e00-\u9fff]")

    def test_unknown_and_traversal_paths_do_not_serve_project_files(self):
        for path in ["/app.py", "/.env", "/../app.py", "/%2e%2e/app.py", "/files/../app.py", "/files/%2e%2e/app.py", "/files/no-such-file.mp4"]:
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertIn(status, {400, 403, 404})
                self.assertNotIn(b"import yt_dlp", body)

    def test_completed_download_preserves_colliding_file_and_serves_new_output(self):
        existing = self.state.download_dir / "collision.mp4"
        existing.write_bytes(b"existing user video")
        inspection_id = "synthetic-inspection"
        self.state.inspections[inspection_id] = {
            "created": time.time(), "url": "https://x.com/example/status/123",
            "videos": [{"id": "synthetic", "formats": [{"id": "fixture"}]}],
        }
        with patch.object(app, "worker", publishing_fixture_worker):
            status, _, body = self.request(
                "POST", "/api/download",
                {"inspection_id": inspection_id, "video_id": "synthetic", "format_id": "fixture"},
                self.authorized_headers(),
            )
        self.assertEqual(status, 202)
        job_id = json.loads(body)["job_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, _, body = self.request("GET", f"/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            job = json.loads(body)
            if job["status"] in app.TERMINAL:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(existing.read_bytes(), b"existing user video")
        self.assertEqual(job["result"]["filename"], "collision (1).mp4")
        status, headers, body = self.request("GET", "/files/" + job["result"]["file_id"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "video/mp4")
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertEqual(body, b"synthetic MP4 fixture bytes" * 50)


if __name__ == "__main__":
    unittest.main()
