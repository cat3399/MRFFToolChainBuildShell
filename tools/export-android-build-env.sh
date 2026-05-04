#! /usr/bin/env bash
#
# Copyright (C) 2021 Matt Reach<qianlongxu@gmail.com>

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# https://stackoverflow.com/questions/59895/how-do-i-get-the-directory-where-a-bash-script-is-located-from-within-the-script
# https://developer.android.com/ndk/guides/abis?hl=zh-cn#cmake_1


export MR_ANDROID_API=${MR_ANDROID_API:-14}

case $_MR_ARCH in
    *v7a)
    export MR_TRIPLE=armv7a-linux-androideabi$MR_ANDROID_API
    export MR_FF_ARCH=arm
    export MR_ANDROID_ABI=armeabi-v7a
    export MR_GCC_TOOLCHAIN_NAME=arm-linux-androideabi
    export MR_BINUTILS_PREFIX=arm-linux-androideabi
    export MR_CLANG_TARGET=armv7-none-linux-androideabi
    export MR_PLATFORM_ARCH=arm
    ;;
    x86)
    export MR_TRIPLE=i686-linux-android$MR_ANDROID_API
    export MR_FF_ARCH=i686
    export MR_ANDROID_ABI=x86
    export MR_GCC_TOOLCHAIN_NAME=x86
    export MR_BINUTILS_PREFIX=i686-linux-android
    export MR_CLANG_TARGET=i686-none-linux-android
    export MR_PLATFORM_ARCH=x86
    ;;
    x86_64)
    if [[ $MR_ANDROID_API -lt 21 ]]; then
        echo "x86_64 requires Android API 21 or newer; Android 4.0 builds only support 32-bit ABIs." >&2
        exit 1
    fi
    export MR_TRIPLE=x86_64-linux-android$MR_ANDROID_API
    export MR_FF_ARCH=x86_64
    export MR_ANDROID_ABI=x86_64
    export MR_GCC_TOOLCHAIN_NAME=x86_64
    export MR_BINUTILS_PREFIX=x86_64-linux-android
    export MR_CLANG_TARGET=x86_64-none-linux-android
    export MR_PLATFORM_ARCH=x86_64
    ;;
    arm64*)
    if [[ $MR_ANDROID_API -lt 21 ]]; then
        echo "arm64-v8a requires Android API 21 or newer; Android 4.0 builds only support 32-bit ABIs." >&2
        exit 1
    fi
    export MR_TRIPLE=aarch64-linux-android$MR_ANDROID_API
    export MR_FF_ARCH=aarch64
    export MR_ANDROID_ABI=arm64-v8a
    export MR_GCC_TOOLCHAIN_NAME=aarch64-linux-android
    export MR_BINUTILS_PREFIX=aarch64-linux-android
    export MR_CLANG_TARGET=aarch64-none-linux-android
    export MR_PLATFORM_ARCH=arm64
    ;;
    *)
    echo "unknown architecture $_MR_ARCH";
    exit 1
    ;;
esac

# x86_64
export MR_ARCH="$_MR_ARCH"

# Common prefix for ld, as, etc.
CROSS_PREFIX_WITH_PATH=${MR_TOOLCHAIN_ROOT}/bin/llvm-
LEGACY_BINUTILS_DIR="${MR_ANDROID_NDK_HOME}/toolchains/${MR_GCC_TOOLCHAIN_NAME}-4.9/prebuilt/${MR_HOST_TAG}/bin"
GCC_TOOLCHAIN_ROOT="${MR_ANDROID_NDK_HOME}/toolchains/${MR_GCC_TOOLCHAIN_NAME}-4.9/prebuilt/${MR_HOST_TAG}"
MR_PLATFORM_SYSROOT="${MR_ANDROID_NDK_HOME}/platforms/android-${MR_ANDROID_API}/arch-${MR_PLATFORM_ARCH}"

function resolve_android_binutil() {
    local llvm_tool="${CROSS_PREFIX_WITH_PATH}$1"
    local legacy_tool="${LEGACY_BINUTILS_DIR}/${MR_BINUTILS_PREFIX}-$1"

    if [[ -x "$llvm_tool" ]]; then
        echo "$llvm_tool"
    elif [[ -x "$legacy_tool" ]]; then
        echo "$legacy_tool"
    else
        echo "$llvm_tool"
    fi
}

# Exporting Binutils paths, if passing just CROSS_PREFIX_WITH_PATH is not enough
# The MR_ prefix is used to eliminate passing those values implicitly to build systems
export  MR_ADDR2LINE=$(resolve_android_binutil addr2line)
export         MR_AR=$(resolve_android_binutil ar)
export         MR_NM=$(resolve_android_binutil nm)
export    MR_OBJCOPY=$(resolve_android_binutil objcopy)
export    MR_OBJDUMP=$(resolve_android_binutil objdump)
export     MR_RANLIB=$(resolve_android_binutil ranlib)
export    MR_READELF=$(resolve_android_binutil readelf)
export       MR_SIZE=$(resolve_android_binutil size)
export    MR_STRINGS=$(resolve_android_binutil strings)
export      MR_STRIP=$(resolve_android_binutil strip)
export       MR_LIPO=${CROSS_PREFIX_WITH_PATH}lipo

TRIPLE_CC="${MR_TOOLCHAIN_ROOT}/bin/${MR_TRIPLE}-clang"
TRIPLE_CXX="${TRIPLE_CC}++"
if [[ -x "$TRIPLE_CC" ]]; then
    export  MR_TRIPLE_CC="$TRIPLE_CC"
    export MR_TRIPLE_CXX="$TRIPLE_CXX"
    export MR_TARGET_CFLAGS=
else
    MR_LINK_SYSROOT="$MR_SYS_ROOT"
    if [[ -d "$MR_PLATFORM_SYSROOT" ]]; then
        MR_LINK_SYSROOT="$MR_PLATFORM_SYSROOT"
    fi

    MR_UNIFIED_INCLUDES="-isystem ${MR_SYS_ROOT}/usr/include"
    if [[ -d "${MR_SYS_ROOT}/usr/include/${MR_BINUTILS_PREFIX}" ]]; then
        MR_UNIFIED_INCLUDES="${MR_UNIFIED_INCLUDES} -isystem ${MR_SYS_ROOT}/usr/include/${MR_BINUTILS_PREFIX}"
    fi

    export  MR_TRIPLE_CC="${MR_TOOLCHAIN_ROOT}/bin/clang"
    export MR_TRIPLE_CXX="${MR_TOOLCHAIN_ROOT}/bin/clang++"
    export MR_TARGET_CFLAGS="--target=${MR_CLANG_TARGET} --gcc-toolchain=${GCC_TOOLCHAIN_ROOT} --sysroot=${MR_LINK_SYSROOT} ${MR_UNIFIED_INCLUDES} -D__ANDROID_API__=${MR_ANDROID_API}"
fi
# find clang from NDK toolchain
export         MR_CC=${MR_TOOLCHAIN_ROOT}/bin/clang
export        MR_CXX=${MR_CC}++
# llvm-as for LLVM IR
# export         MR_AS=${CROSS_PREFIX_WITH_PATH}as
export         MR_AS=${MR_TRIPLE_CC}
export       MR_YASM=${MR_TOOLCHAIN_ROOT}/bin/yasm


export MR_DEFAULT_CFLAGS="$MR_INIT_CFLAGS -D__ANDROID__ $MR_TARGET_CFLAGS"

# openssl-armv7a
# android/ffmpeg-x86_64
export MR_BUILD_SOURCE="${MR_SRC_ROOT}/${REPO_DIR}-${_MR_ARCH}"
# android/fftutorial-x86_64
export MR_BUILD_PREFIX="${MR_PRODUCT_ROOT}/${LIB_NAME}-${_MR_ARCH}"

echo "MR_ARCH         : [$MR_ARCH]"
echo "MR_TRIPLE       : [$MR_TRIPLE]"
echo "MR_ANDROID_API  : [$MR_ANDROID_API]"
echo "MR_ANDROID_NDK  : [$MR_NDK_REL]"
echo "MR_BUILD_SOURCE : [$MR_BUILD_SOURCE]"
echo "MR_BUILD_PREFIX : [$MR_BUILD_PREFIX]"
echo "MR_DEFAULT_CFLAGS : [$MR_DEFAULT_CFLAGS]"
echo "MR_ANDROID_NDK_HOME: [$MR_ANDROID_NDK_HOME]"

# 
THIS_DIR=$(DIRNAME=$(dirname "${BASH_SOURCE[0]}"); cd "${DIRNAME}"; pwd)
source "$THIS_DIR/export-android-pkg-config-dir.sh"

echo "PKG_CONFIG_LIBDIR: [$PKG_CONFIG_LIBDIR]"
