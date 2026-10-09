"""A real local HLS download/remux test using synthetic media only."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class QuietHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class FallbackFixtureHTTPHandler(QuietHTTPHandler):
    def do_GET(self):
        self.server.requested_paths.append(self.path)
        if self.path == "/blocked.mp4":
            self.send_error(403, "Forbidden")
        else:
            super().do_GET()


def fallback_entry(base, selected_path):
    return {
        "_type": "video", "id": "synthetic-fallback", "title": "Synthetic CDN fallback",
        "extractor_key": "Twitter", "extractor": "twitter", "duration": 2.5,
        "webpage_url": "https://x.com/example/status/123456789",
        "formats": [
            {"format_id": "direct", "url": base + selected_path, "ext": "mp4", "protocol": "http",
             "vcodec": "h264", "acodec": "aac", "width": 320, "height": 180, "fps": 24},
            {"format_id": "hls", "url": base + "/playlist.m3u8", "ext": "mp4", "protocol": "m3u8_native",
             "vcodec": "h264", "acodec": "aac", "width": 320, "height": 180, "fps": 24},
            {"format_id": "lower", "url": base + "/lower.m3u8", "ext": "mp4", "protocol": "m3u8_native",
             "vcodec": "h264", "acodec": "aac", "width": 160, "height": 90, "fps": 24},
        ],
    }


@unittest.skipUnless(
    importlib.util.find_spec("yt_dlp") and shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "Install project requirements and FFmpeg to run the synthetic HLS integration test",
)
class HLSIntegrationTests(unittest.TestCase):
    def setUp(self):
        # A synthetic loopback fixture must not inherit this Mac's system proxy.
        # Production requests keep their existing proxy and extractor restrictions.
        original_options = app.ydl_options

        def local_options(*args, **kwargs):
            options = original_options(*args, **kwargs)
            options["proxy"] = ""
            return options

        patcher = patch.object(app, "ydl_options", local_options)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_transient_empty_response_retries_with_existing_checkpoint(self):
        import yt_dlp

        with tempfile.TemporaryDirectory(prefix="x-video-lab-resume-") as temporary:
            directory = Path(temporary)
            partial = directory / "source.mp4.part"
            checkpoint = directory / "source.mp4.ytdl"
            events = []
            calls = []

            def process_result(_entry, download):
                self.assertTrue(download)
                calls.append(True)
                if len(calls) == 1:
                    partial.write_bytes(b"existing downloaded fragment" * 50)
                    checkpoint.write_text('{"fragment_index": 7}')
                    raise yt_dlp.utils.DownloadError("ERROR: Did not get any data blocks")
                self.assertEqual(partial.read_bytes(), b"existing downloaded fragment" * 50)
                self.assertEqual(json.loads(checkpoint.read_text())["fragment_index"], 7)
                (directory / "source.mp4").write_bytes(b"synthetic completed media" * 100)
                partial.unlink()
                checkpoint.unlink()

            metadata = {
                "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.5"},
                "streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}],
            }
            with patch.object(yt_dlp, "YoutubeDL") as downloader, patch.object(app.time, "sleep") as sleep, patch.object(
                app.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(metadata), returncode=0)
            ):
                downloader.return_value.__enter__.return_value.process_ie_result.side_effect = process_result
                output = app.download_entry(fallback_entry("http://127.0.0.1", "/fixture.mp4"), "direct", directory, events.append)
            self.assertEqual(len(calls), 2)
            sleep.assert_called_once()
            self.assertEqual(output, directory / "source.mp4")
            self.assertTrue(any("已有进度" in event.get("message", "") for event in events))

    def test_repeated_empty_responses_stop_after_five_stalled_attempts(self):
        import yt_dlp

        with tempfile.TemporaryDirectory(prefix="x-video-lab-stalled-") as temporary:
            directory = Path(temporary)
            with patch.object(yt_dlp, "YoutubeDL") as downloader, patch.object(app.time, "sleep") as sleep:
                process = downloader.return_value.__enter__.return_value.process_ie_result
                process.side_effect = yt_dlp.utils.DownloadError("ERROR: Did not get any data blocks")
                with self.assertRaises(yt_dlp.utils.DownloadError):
                    app.download_entry(fallback_entry("http://127.0.0.1", "/fixture.mp4"), "direct", directory, lambda _event: None)
                self.assertEqual(process.call_count, 5)
                self.assertEqual(sleep.call_count, 4)
            self.assertFalse((directory / "source.mp4").exists())

    def test_duration_guard_catches_long_clip_truncation_and_allows_mux_rounding(self):
        import yt_dlp

        cases = [(15749.336, 15747.436, True), (15749.336, 15747.236, False),
                 (120, 118.1, True), (120, 117.9, False), (36000, 35997, True), (36000, 35996, False)]
        with tempfile.TemporaryDirectory(prefix="x-video-lab-duration-") as temporary:
            directory = Path(temporary)
            (directory / "source.mp4").write_bytes(b"synthetic complete media" * 100)
            for expected, actual, accepted in cases:
                with self.subTest(expected=expected, actual=actual):
                    entry = fallback_entry("http://127.0.0.1", "/fixture.mp4")
                    entry["duration"] = expected
                    metadata = {
                        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": str(actual)},
                        "streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}],
                    }
                    with patch.object(yt_dlp, "YoutubeDL"), patch.object(
                        app.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(metadata), returncode=0)
                    ):
                        if accepted:
                            self.assertEqual(app.download_entry(entry, "direct", directory, lambda _event: None), directory / "source.mp4")
                        else:
                            with self.assertRaises(app.UserError) as raised:
                                app.download_entry(entry, "direct", directory, lambda _event: None)
                            self.assertEqual(raised.exception.code, "incomplete")

    def test_direct_404_falls_back_to_same_resolution_hls_and_valid_mp4(self):
        with tempfile.TemporaryDirectory(prefix="x-video-lab-fallback-") as temporary:
            root = Path(temporary)
            media = root / "source"
            media.mkdir()
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", "2.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-g", "12", "-sc_threshold", "0", "-c:a", "aac",
                    "-f", "hls", "-hls_time", "0.5", "-hls_list_size", "0",
                    "-hls_segment_filename", str(media / "segment%03d.ts"),
                    str(media / "playlist.m3u8"),
                ],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(FallbackFixtureHTTPHandler, directory=str(media)))
            server.daemon_threads = True
            server.requested_paths = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            download = root / "download"
            download.mkdir()
            stale = download / "source.stale.part"
            stale.write_bytes(b"owned stale partial")
            retained = download / "keep.txt"
            retained.write_text("retained fixture")
            events = []
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                output = app.download_entry(fallback_entry(base, "/missing.mp4"), "direct", download, events.append)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            self.assertIn("/missing.mp4", server.requested_paths)
            self.assertIn("/playlist.m3u8", server.requested_paths)
            self.assertNotIn("/lower.m3u8", server.requested_paths)
            self.assertTrue(any("同清晰度" in event.get("message", "") for event in events))
            self.assertFalse(stale.exists())
            self.assertEqual(retained.read_text(), "retained fixture")
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            metadata = json.loads(probe.stdout)
            self.assertIn("mp4", metadata["format"]["format_name"])
            self.assertGreater(float(metadata["format"]["duration"]), 2.0)
            video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"], video["codec_name"]), (320, 180, "h264"))
            self.assertEqual(next(stream["codec_name"] for stream in metadata["streams"] if stream["codec_type"] == "audio"), "aac")

    def test_direct_403_does_not_try_an_hls_alternative(self):
        import yt_dlp

        with tempfile.TemporaryDirectory(prefix="x-video-lab-forbidden-") as temporary:
            root = Path(temporary)
            media = root / "source"
            media.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(FallbackFixtureHTTPHandler, directory=str(media)))
            server.daemon_threads = True
            server.requested_paths = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            download = root / "download"
            download.mkdir()
            events = []
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaises(yt_dlp.utils.DownloadError) as raised:
                    app.download_entry(fallback_entry(base, "/blocked.mp4"), "direct", download, events.append)
                self.assertIn("403", str(raised.exception))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            self.assertIn("/blocked.mp4", server.requested_paths)
            self.assertTrue(all(path == "/blocked.mp4" for path in server.requested_paths))
            self.assertFalse(any("同清晰度" in event.get("message", "") for event in events))
            self.assertFalse((download / "final.mp4").exists())

    def test_unknown_codec_is_checked_and_incompatible_mp4_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="x-video-lab-codec-") as temporary:
            root = Path(temporary)
            media = root / "source"
            media.mkdir()
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-t", "1.2", "-c:v", "mpeg4", "-an", str(media / "legacy.mp4"),
                ],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHTTPHandler, directory=str(media)))
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            download = root / "download"
            download.mkdir()
            try:
                entry = {
                    "_type": "video", "id": "synthetic-codec", "title": "Unknown codec fixture",
                    "extractor_key": "Twitter", "extractor": "twitter", "duration": 1.2,
                    "webpage_url": "https://x.com/example/status/123456789",
                    "formats": [{
                        "format_id": "unknown", "url": f"http://127.0.0.1:{server.server_port}/legacy.mp4",
                        "ext": "mp4", "protocol": "http", "vcodec": "unknown", "acodec": "none",
                        "width": 320, "height": 180, "fps": 24,
                    }],
                }
                self.assertEqual(app.make_video(entry)["formats"][0]["id"], "unknown")
                with self.assertRaises(app.UserError) as raised:
                    app.download_entry(entry, "unknown", download, lambda _event: None)
                self.assertEqual(raised.exception.code, "unsupported_codec")
                self.assertIn("Safari", raised.exception.message)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_local_hls_segments_are_downloaded_and_saved_as_playable_mp4(self):
        with tempfile.TemporaryDirectory(prefix="x-video-lab-hls-") as temporary:
            root = Path(temporary)
            media = root / "source"
            media.mkdir()
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", "2.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-g", "12", "-sc_threshold", "0", "-c:a", "aac",
                    "-f", "hls", "-hls_time", "0.5", "-hls_list_size", "0",
                    "-hls_segment_filename", str(media / "segment%03d.ts"),
                    str(media / "playlist.m3u8"),
                ],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            self.assertGreaterEqual(len(list(media.glob("segment*.ts"))), 2)
            handler = partial(QuietHTTPHandler, directory=str(media))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            progress = []
            download = root / "download"
            download.mkdir()
            try:
                url = f"http://127.0.0.1:{server.server_port}/playlist.m3u8"
                entry = {
                    "_type": "video", "id": "synthetic-hls", "title": "Synthetic HLS test",
                    "extractor_key": "Twitter", "extractor": "twitter", "duration": 2.5,
                    "webpage_url": "https://x.com/example/status/123456789",
                    "formats": [{
                        "format_id": "hls", "url": url, "ext": "mp4",
                        "protocol": "m3u8_native", "vcodec": "h264", "acodec": "aac",
                        "width": 320, "height": 180, "fps": 24,
                    }],
                }
                output = app.download_entry(entry, "hls", download, progress.append)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1000)
            self.assertTrue(any(event.get("progress", {}).get("downloaded_bytes", 0) > 0 for event in progress))
            self.assertTrue(any(event.get("progress", {}).get("percent") == 95 for event in progress))
            self.assertTrue(any(event.get("progress", {}).get("percent") == 97 for event in progress))
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            metadata = json.loads(probe.stdout)
            self.assertIn("mp4", metadata["format"]["format_name"])
            self.assertGreater(float(metadata["format"]["duration"]), 2.0)
            self.assertEqual({stream["codec_type"] for stream in metadata["streams"]}, {"video", "audio"})
            self.assertEqual(next(stream["codec_name"] for stream in metadata["streams"] if stream["codec_type"] == "video"), "h264")

    def test_separate_direct_mp4_video_and_aac_audio_are_merged(self):
        with tempfile.TemporaryDirectory(prefix="x-video-lab-audio-") as temporary:
            root = Path(temporary)
            media = root / "source"
            media.mkdir()
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", "1.5", "-map", "0:v", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(media / "video.mp4"),
                    "-t", "1.5", "-map", "1:a", "-c:a", "aac", "-vn", str(media / "audio.m4a"),
                ],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHTTPHandler, directory=str(media)))
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            progress = []
            download = root / "download"
            download.mkdir()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                entry = {
                    "_type": "video", "id": "synthetic-separate", "title": "Synthetic separate audio test",
                    "extractor_key": "Twitter", "extractor": "twitter", "duration": 1.5,
                    "webpage_url": "https://x.com/example/status/123456789",
                    "formats": [
                        {"format_id": "video", "url": base + "/video.mp4", "ext": "mp4", "protocol": "http",
                         "vcodec": "h264", "acodec": "none", "width": 320, "height": 180, "fps": 24},
                        {"format_id": "audio", "url": base + "/audio.m4a", "ext": "m4a", "protocol": "http",
                         "vcodec": "none", "acodec": None, "abr": 96},
                    ],
                }
                output = app.download_entry(entry, "video", download, progress.append)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            metadata = json.loads(probe.stdout)
            # Video -> audio -> merge must form one total, without restarting.
            values = [event["progress"]["percent"] for event in progress
                      if event.get("progress", {}).get("percent") is not None]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(value < 100 for value in values))
            self.assertTrue(any(event.get("progress", {}).get("stage") == "画面" for event in progress))
            self.assertTrue(any(event.get("progress", {}).get("stage") == "音轨" for event in progress))
            ready_audio = next(event["progress"]["percent"] for event in progress if "准备音轨" in event.get("message", ""))
            audio_values = [event["progress"]["percent"] for event in progress if event.get("progress", {}).get("stage") == "音轨"]
            self.assertGreaterEqual(min(audio_values), ready_audio)
            self.assertIn("mp4", metadata["format"]["format_name"])
            self.assertEqual({stream["codec_type"] for stream in metadata["streams"]}, {"video", "audio"})
            self.assertEqual(next(stream["codec_name"] for stream in metadata["streams"] if stream["codec_type"] == "audio"), "aac")
            self.assertGreater(float(metadata["format"]["duration"]), 1.0)


if __name__ == "__main__":
    unittest.main()
