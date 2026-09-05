#!/usr/bin/env python3
"""DASH preparation using real audio/video and a loopback HTTP Range server.

Requires the recovery test build plus rawvideo/mpeg4 decode, MPEG-4 encode
and rawvideo demux. No Android device, external media or internet is used.
Artifacts are retained in /tmp. Run on the native Linux build host.
"""
import argparse
import http.server
import pathlib
import re
import subprocess
import tempfile
import threading
import time
import wave
from urllib.parse import urlsplit

from test_dash_http import atoms


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class State:
    def __init__(self, media, mode):
        self.media = media
        self.mode = mode
        self.arrived = {name: threading.Event() for name in media}
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.requests = []
        self.overlap = False


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # Seeking/cancelling may close an otherwise reusable HTTP socket.
            self.close_connection = True

    def log_message(self, *args):
        pass

    def do_GET(self):
        state = self.server.state
        name = pathlib.PurePosixPath(urlsplit(self.path).path).stem
        data = state.media[name]
        start, end = 0, len(data) - 1
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if match:
            start = int(match[1])
            if match[2]:
                end = min(int(match[2]), end)
        with state.lock:
            state.requests.append((name, start, end))
        if start > end:
            self.send_error(416)
            return
        if start == 0:
            state.arrived[name].set()
            if state.mode in {"overlap", "failure", "cancel"}:
                peer = "audio" if name == "video" else "video"
                both = state.arrived[peer].wait(2)
                with state.lock:
                    state.overlap |= both
        if state.mode == "failure" and name == "video":
            self.send_error(404)
            return
        self.send_response(206)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(end - start + 1))
        # Exercise concurrent updates to the shared HTTP cookie snapshot.
        self.send_header("Set-Cookie", f"{name}=1; Path=/")
        self.end_headers()
        if state.mode in {"failure", "cancel"}:
            state.release.wait(4)
            self.close_connection = True
            return
        if state.mode == "overlap" and start == 0:
            time.sleep(0.12)
        try:
            self.wfile.write(data[start:end + 1])
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def make_media(ffmpeg, work):
    raw = work / "video.yuv"
    # Twelve seconds, changing luma, 64x64 YUV420p; no external video fixture.
    with raw.open("wb") as output:
        for frame in range(360):
            output.write(bytes([32 + frame % 180]) * (64 * 64))
            output.write(bytes([128]) * (64 * 64 // 2))
    with wave.open(str(work / "audio.wav"), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x88\x13\x78\xec" * (48000 * 12 // 2))
    movflags = "empty_moov+frag_keyframe+dash+global_sidx"
    subprocess.run([ffmpeg, "-v", "error", "-f", "rawvideo", "-pixel_format",
                    "yuv420p", "-video_size", "64x64", "-framerate", "30",
                    "-i", str(raw), "-c:v", "mpeg4", "-g", "30", "-bf", "0",
                    "-movflags", movflags, "-frag_duration", "1000000",
                    str(work / "video.mp4")], check=True, timeout=30)
    subprocess.run([ffmpeg, "-v", "error", "-i", str(work / "audio.wav"),
                    "-c:a", "aac", "-b:a", "96k", "-movflags", movflags,
                    "-frag_duration", "1000000", str(work / "audio.mp4")],
                   check=True, timeout=30)
    return {name: (work / f"{name}.mp4").read_bytes()
            for name in ("video", "audio")}


def write_mpd(work, server, media, tracks, full_file=()):
    adaptations = []
    for index, name in enumerate(tracks):
        url = f"http://127.0.0.1:{server.server_port}/{name}.mp4"
        segment = ""
        if name not in full_file:
            offset, size = next((offset, size) for kind, offset, size
                                in atoms(media[name]) if kind == b"sidx")
            segment = (f'<SegmentBase indexRange="{offset}-{offset + size - 1}">'
                       f'<Initialization range="0-{offset - 1}"/></SegmentBase>')
        adaptations.append(
            f'<AdaptationSet mimeType="{name}/mp4"><Representation '
            f'id="{name}{index}" bandwidth="96000"><BaseURL>{url}</BaseURL>'
            f'{segment}</Representation></AdaptationSet>')
    path = work / "input.mpd"
    path.write_text(
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" '
        'profiles="urn:mpeg:dash:profile:isoff-on-demand:2011" '
        'mediaPresentationDuration="PT12.1S"><Period>' +
        "".join(adaptations) + '</Period></MPD>')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--probe", required=True)
    args = parser.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="ijk-dash-startup-"))
    media = make_media(args.ffmpeg, work)
    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def run(label, tracks=("video", "audio"), mode="normal", position=0,
            full_file=(), cancel_ms=0):
        state = State(media, mode)
        server.state = state
        path = write_mpd(work, server, media, tracks, full_file)
        try:
            result = subprocess.run([args.probe, str(path), str(position),
                                     str(cancel_ms)], capture_output=True,
                                    text=True, timeout=8)
            (work / f"{label}.log").write_text(result.stderr + result.stdout)
        finally:
            state.release.set()
        lines = [dict(re.findall(r"(\w+)=([\w-]+)", line))
                 for line in result.stdout.splitlines()]
        streams = [line for line in lines if "stream" in line]
        for stream in streams:
            stream["fingerprints"] = [line["hash"] for line in lines
                                      if line.get("packet_stream") == stream["stream"]]
        fields = {key: value for line in lines
                  if "stream" not in line and "packet_stream" not in line
                  for key, value in line.items()}
        return result, fields, streams, state

    def check_packets(streams, expected):
        # DASH currently returns EOF when its first component finishes. AAC
        # encoder padding extends beyond the video, so compare every returned
        # packet to the isolated track's prefix, and require all tracks to
        # reach the common end. This test does not change that EOF policy.
        common_end = min(int(value["last_pts_us"]) for value in expected.values())
        for stream in streams:
            baseline = expected[stream["type"]]
            count = int(stream["packets"])
            assert stream["fingerprints"] == baseline["fingerprints"][:count]
            assert int(stream["last_pts_us"]) >= common_end, stream

    try:
        expected = {}
        for name in ("video", "audio"):
            result, fields, streams, _ = run(name, tracks=(name,))
            assert result.returncode == 0 and fields["streams"] == "1", result
            expected[name] = streams[0]
        print("PASS single-track preparation and complete packet baselines")

        result, fields, streams, state = run("parallel", mode="overlap")
        assert result.returncode == 0 and fields["streams"] == "2", result
        assert state.overlap and int(fields["open_us"]) < 1_000_000, fields
        assert [stream["type"] for stream in streams] == ["video", "audio"], streams
        check_packets(streams, expected)
        print("PASS independent A/V requests overlap; ordered streams and identical payloads")

        result, fields, streams, state = run("common-init", tracks=("video", "video", "audio"))
        assert result.returncode == 0 and fields["streams"] == "3", result
        assert sum(name == "video" and start == 0 for name, start, _ in state.requests) == 1
        check_packets(streams, expected)
        print("PASS shared initialization reused without cross-track mutation")

        result, fields, streams, _ = run("initial-position", position=5_000_000)
        assert result.returncode == 0 and fields["applied"] == "1", result
        assert all(4_000_000 <= int(stream["first_pts_us"]) <= 5_100_000
                   for stream in streams), streams
        print("PASS both indexed tracks acknowledge and start near the requested position")

        result, fields, streams, _ = run("position-fallback", position=5_000_000,
                                         full_file=("video", "audio"))
        assert result.returncode == 0 and fields["applied"] == "0", result
        assert fields["seek_ret"] == "0", fields
        assert all(4_000_000 <= int(stream["first_pts_us"]) <= 5_100_000
                   for stream in streams), streams
        print("PASS unsupported early positioning is not acknowledged; regular seek works")

        result, fields, _, state = run("peer-failure", mode="failure")
        assert result.returncode == 2 and fields["http404"] == "1", result
        assert state.overlap and int(fields["open_us"]) < 1_000_000, fields
        print("PASS failed video cancels blocked audio and preserves the original HTTP error")

        result, fields, _, state = run("cancel", mode="cancel", cancel_ms=200)
        assert result.returncode == 2 and fields["exit"] == "1", result
        assert state.overlap and int(fields["open_us"]) < 1_000_000, fields
        print("PASS cancellation joins both blocked preparation workers")
    finally:
        server.shutdown()
        server.server_close()
        print(f"Artifacts: {work}")


if __name__ == "__main__":
    main()
