#!/usr/bin/env python3
"""DASH transport regression using a local, fault-injecting Range server.

Requires an FFmpeg 7 build with this patch series and dash,mov,wav,libxml2,
HTTP, AAC encode/decode and PCM decode enabled, plus dash_http_probe.c linked
against that same build. No devices, external media or network are used.
Test files are retained in /tmp for diagnosis; nothing is installed or deleted.
"""
import argparse
import http.server
import pathlib
import re
import socket
import struct
import subprocess
import tempfile
import threading
import time
import wave


def atoms(data):
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        assert size >= 8
        yield kind, offset, size
        offset += size


class RangeServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        state = self.server.state
        data = state["data"]
        start, end = 0, len(data) - 1
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if match:
            start = int(match[1])
            if match[2]:
                end = min(int(match[2]), end)
        state["requests"].append((start, end))
        if start > end:
            self.send_error(416)
            return
        mode = state["mode"]
        if mode == "missing" and start >= state["media_start"]:
            self.send_error(404)
            return
        self.send_response(206)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        fault = state["fault"]
        hit = start <= fault <= end and mode in {"reset", "eof", "timeout", "always"}
        if hit and (not state["injected"] or mode == "always"):
            state["injected"] = True
            payload = data[start:fault]
            self.wfile.write(payload)
            self.wfile.flush()
            if mode == "timeout":
                time.sleep(0.8)
            if mode in {"reset", "always"}:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                           struct.pack("ii", 1, 0))
            self.close_connection = True
            return
        if mode == "slow":
            for offset in range(start, end + 1, 1024):
                self.wfile.write(data[offset:min(offset + 1024, end + 1)])
                self.wfile.flush()
                time.sleep(0.01)
        else:
            self.wfile.write(data[start:end + 1])


def run_probe(probe, path, reconnect, deadline=None):
    cmd = [probe, str(path), str(reconnect)]
    if deadline:
        cmd.append(str(deadline))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    fields = dict(re.findall(r"(\w+)=([\w-]+)", result.stdout))
    assert fields, (cmd, result.stderr)
    return result, fields


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--probe", required=True)
    args = parser.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="ijk-dash-http-"))
    with wave.open(str(work / "audio.wav"), "wb") as wav:
        wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        samples = b"".join(struct.pack("<h", 5000 if i % 100 < 50 else -5000)
                           for i in range(48000))
        wav.writeframes(samples * 12)
    subprocess.run([args.ffmpeg, "-v", "error", "-i", str(work / "audio.wav"),
                    "-c:a", "aac", "-b:a", "96k", "-movflags",
                    "empty_moov+frag_keyframe+dash+global_sidx", "-frag_duration",
                    "1000000", str(work / "media.mp4")], check=True, timeout=30)
    data = (work / "media.mp4").read_bytes()
    boxes = list(atoms(data))
    index = next((offset, size) for kind, offset, size in boxes if kind == b"sidx")
    media = [offset for kind, offset, size in boxes if kind == b"moof"]
    assert len(media) > 3
    server = RangeServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/media.mp4"
    mpd = work / "input.mpd"
    mpd.write_text(f'''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
      profiles="urn:mpeg:dash:profile:isoff-on-demand:2011" mediaPresentationDuration="PT12.1S">
      <Period><AdaptationSet mimeType="audio/mp4"><Representation id="a" bandwidth="96000">
      <BaseURL>{url}</BaseURL><SegmentBase indexRange="{index[0]}-{sum(index)-1}">
      <Initialization range="0-{index[0]-1}"/></SegmentBase>
      </Representation></AdaptationSet></Period></MPD>''')
    # One full-file VOD fragment exercises the non-SIDX open-error path too.
    segmentlist = work / "list.mpd"
    segmentlist.write_text(f'''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
      profiles="urn:mpeg:dash:profile:isoff-on-demand:2011" mediaPresentationDuration="PT12.1S">
      <Period><AdaptationSet mimeType="audio/mp4"><Representation id="a" bandwidth="96000">
      <SegmentList duration="13"><SegmentURL media="{url}"/></SegmentList>
      </Representation></AdaptationSet></Period></MPD>''')

    def state(mode, fault=None):
        server.state = {"data": data, "mode": mode, "fault": fault or media[4] + 500,
                        "media_start": media[0], "injected": False, "requests": []}

    def probe(label, mode, reconnect=1, path=mpd, fault=None, deadline=None):
        state(mode, fault)
        result, fields = run_probe(args.probe, path, reconnect, deadline)
        (work / f"{label}.log").write_text(result.stderr + result.stdout)
        return result, fields, list(server.state["requests"])

    try:
        state("normal")
        result = subprocess.run([args.probe, "range", url], capture_output=True,
                                text=True, timeout=5)
        assert result.returncode == 0 and len(server.state["requests"]) == 1, result
        assert "Will reconnect" not in result.stderr, result.stderr
        print("PASS HTTP Range EOF does not reconnect before resource EOF")
        result, normal, requests = probe("normal", "normal")
        assert result.returncode == 0 and int(normal["packets"]) > 500, normal
        # Adjacent init/index metadata and the media request stay separate;
        # reaching the metadata range end must not cause a retry loop.
        assert len(requests) <= 3, requests
        print("PASS normal EOF and bounded metadata ranges")
        for mode in ("reset", "eof", "timeout", "slow"):
            result, fields, requests = probe(mode, mode)
            assert result.returncode == 0 and fields == normal, (mode, fields, normal)
            if mode != "slow":
                # A TCP reset can discard bytes already written by the server
                # but not received by HTTP. Resume from the client's actual
                # offset; packet hashes detect any duplicated or lost bytes.
                assert any(media[0] < start <= media[4] + 500
                           for start, _ in requests[2:]), requests
            print(f"PASS {mode}: identical packet count and payload hash")
        result, fields, _ = probe("metadata-eof", "eof", fault=index[0] // 2)
        assert result.returncode == 0 and fields == normal, fields
        print("PASS metadata interruption resumes at the original byte offset")
        for label, mode, reconnect in (("disabled", "reset", 0),
                                        ("exhausted", "always", 1),
                                        ("missing", "missing", 1)):
            result, fields, requests = probe(label, mode, reconnect)
            assert result.returncode == 2 and fields["eof"] == "0", fields
            # A successfully read prefix resets HTTP's per-read retry budget.
            # Bound retries without progress, not total requests with progress.
            offsets = [start for start, _ in requests]
            assert max(offsets.count(start) for start in offsets) <= 2, requests
            print(f"PASS {label}: finite read failure, not EOF")
        result, fields, _ = probe("cancel", "timeout", deadline=150)
        assert result.returncode == 2 and fields["exit"] == "1", fields
        print("PASS interruption cancels a blocked read")
        # Return 404 for the full-file SegmentList too.
        state("missing")
        server.state["media_start"] = 0
        result, fields = run_probe(args.probe, segmentlist, 1)
        (work / "missing-segmentlist.log").write_text(result.stderr + result.stdout)
        assert result.returncode == 2 and fields["eof"] == "0", fields
        print("PASS missing VOD SegmentList fragment is not skipped to EOF")
    finally:
        server.shutdown()
        server.server_close()
        print(f"Artifacts: {work}")


if __name__ == "__main__":
    main()
