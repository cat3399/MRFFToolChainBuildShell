#! /usr/bin/env bash

# FFmpeg 7 build target for the classic IJK player.
#
# Keep LIB_NAME as "ijkffmpeg" so the existing Android CMake packaging
# contract remains stable while the source repository and API level move to
# upstream FFmpeg 7.1.1.

export LIB_NAME='ijkffmpeg'
export LIPO_LIBS="libavcodec libavformat libavutil libswscale libswresample libavfilter"
export LIB_DEPENDS_BIN="nasm pkg-config"
export GIT_LOCAL_REPO=extra/ffmpeg
export REPO_DIR=ijkffmpeg7
# Start from a clean upstream baseline. The generic ffmpeg-n7.1.1 patch set
# contains ffmpeg-kit/debugly changes that are not part of the classic IJK
# port and currently mixes AVInputFormat with FFInputFormat.
export PATCH_DIR=

if [[ "$GIT_FFMPEG_UPSTREAM" != "" ]] ;then
    export GIT_UPSTREAM="$GIT_FFMPEG_UPSTREAM"
else
    export GIT_UPSTREAM=https://github.com/FFmpeg/FFmpeg.git
fi

export GIT_COMMIT=n7.1.1
export GIT_REPO_VERSION=7.1.1
