# DASH HTTP recovery regression

`test_dash_http.py` creates a fragmented AAC/MP4 with SIDX and a local MPD,
then serves its bytes through a loopback HTTP Range server. It runs the real
libavformat reader; reconnect logic is not mocked. No Android device or external
media is needed, and artifacts are retained in `/tmp`.

Coverage: normal EOF, bounded Range EOF, reset, premature EOF, read timeout,
slow successful reads, interrupted initialization, disabled reconnect,
exhausted retries, missing media, cancellation, and missing SegmentList VOD.
Recovered streams must have the same complete packet count and payload hash
as the uninterrupted stream. Unrecoverable inputs must return an error, not EOF.
These tests cover transport and demuxing, not Android UI event delivery.

Build a native FFmpeg 7.1.1 with `patches/ijkffmpeg7` applied. Required features
are listed in the script. Given its configured and built source directory:

```sh
TASK_FFMPEG_BUILD=/path/to/native/ffmpeg-build
cc -std=c11 -Wall -Wextra -Werror -I"$TASK_FFMPEG_BUILD" \
  tests/dash_http_probe.c \
  "$TASK_FFMPEG_BUILD/libavformat/libavformat.a" \
  "$TASK_FFMPEG_BUILD/libavcodec/libavcodec.a" \
  "$TASK_FFMPEG_BUILD/libswresample/libswresample.a" \
  "$TASK_FFMPEG_BUILD/libavutil/libavutil.a" \
  $(pkg-config --libs libxml-2.0) -lm -pthread -o /tmp/dash_http_probe
python3 tests/test_dash_http.py \
  --ffmpeg "$TASK_FFMPEG_BUILD/ffmpeg" --probe /tmp/dash_http_probe
```

The implementation uses [FFmpeg's HTTP reconnect options](https://ffmpeg.org/ffmpeg-protocols.html#http),
including its existing delay/retry limits and interruption callback. DASH exposes
these options because a local MPD's file AVIO cannot inherit HTTP settings.
`timeout` is accepted as an alias for `rw_timeout` for existing IJK callers.
`reconnect_at_eof` and `reconnect_streamed` are intentionally not enabled: normal
VOD completion must stay terminal and byte-range continuation must not restart
a non-seekable response from byte zero. The HTTP defaults are unchanged; no
player-level reprepare timer or retry controller is introduced.

## DASH startup preparation

`test_dash_startup.py` adds real, generated MPEG-4 video and AAC audio to test
independent preparation of media types. In addition to the features above,
enable the rawvideo demuxer, rawvideo/MPEG-4 decoders and MPEG-4 encoder in the
native FFmpeg build. Link `dash_startup_probe.c` with the same command as
`dash_http_probe.c`, then run:

```sh
python3 tests/test_dash_startup.py \
  --ffmpeg "$TASK_FFMPEG_BUILD/ffmpeg" --probe /tmp/dash_startup_probe
```

Coverage: single-track input, concurrent audio/video requests, deterministic
stream order, per-stream packet count/hash preservation, shared initialization,
indexed initial positioning, unsupported-position acknowledgement and regular
seek, peer failure cancellation and user cancellation. An HTTP request barrier
proves overlap without relying solely on a small wall-clock timing difference.

The ownership model follows Media3 1.8.0's independent media loading and
serialized result publication (see
[ChunkSampleStream](https://github.com/androidx/media/blob/1.8.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/source/chunk/ChunkSampleStream.java)
and
[MergingMediaPeriod](https://github.com/androidx/media/blob/1.8.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/source/MergingMediaPeriod.java)).
FFmpeg's existing per-representation AVIO and child demuxer own the actual I/O.
At most two preparation workers supplement the calling demux thread; they all
join before streams are published or input-open returns. No worker remains
during playback. Shared initialization stays ordered within each media type;
live manifest refresh remains serialized. Only option/cookie snapshots are
locked, not network reads. Failures interrupt peers through an AVIO callback
whose lifetime is the DASH context, preserving persistent-connection safety.

`DASHSTART` logs one duration per media type and one total preparation duration.
They add no per-packet logging and can be correlated with IJK's existing
`IJKSTART` input-open/first-frame events. Initial positioning is acknowledged by
the exported `initial_position_applied` result, not by consumption of an option.
