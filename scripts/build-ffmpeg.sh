#!/usr/bin/env bash
# Build the Windows x64 video engine with exactly one third-party media library:
# x264. Run on Ubuntu 24.04 / WSL; the resulting programs run on Windows.
# Prerequisites: gcc-mingw-w64-x86-64-posix nasm make pkg-config curl xz-utils.
set -euo pipefail

script_file="$(realpath "${BASH_SOURCE[0]}")"
script_dir="$(dirname "$script_file")"
repo_root="$(cd "$script_dir/.." && pwd)"
output_dir="${1:-$repo_root/build/ffmpeg}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
source_dir="$repo_root/third_party/sources"
mkdir -p "$source_dir"
work_dir="${DIKEY_FFMPEG_WORK:-$(mktemp -d /tmp/dikey-ffmpeg.XXXXXXXX)}"
mkdir -p "$work_dir"
prefix="$work_dir/prefix"
jobs="${DIKEY_BUILD_JOBS:-$(nproc)}"

ffmpeg_version="9.0.2"
x264_commit="b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
ffmpeg_archive="ffmpeg-$ffmpeg_version.tar.xz"
x264_archive="x264-$x264_commit.tar.gz"
ffmpeg_sha="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
x264_sha="cd71a7515b0e9a012e1ac9b1f8415bebcaf6fc97d4db32286642ac4c0fbe24f9"
if [[ -f "$script_dir/$ffmpeg_archive" && -f "$script_dir/$x264_archive" ]]; then
  # The corresponding-source release archive can be rebuilt independently.
  source_dir="$script_dir"
fi

fetch() {
  local url="$1" filename="$2" checksum="$3"
  if [[ ! -f "$source_dir/$filename" ]]; then
    curl --fail --location --retry 3 "$url" --output "$source_dir/$filename"
  fi
  printf '%s  %s\n' "$checksum" "$source_dir/$filename" | sha256sum --check -
}

fetch "https://ffmpeg.org/releases/$ffmpeg_archive" "$ffmpeg_archive" "$ffmpeg_sha"
fetch "https://code.videolan.org/videolan/x264/-/archive/$x264_commit/$x264_archive" "$x264_archive" "$x264_sha"
printf '%s  %s\n%s  %s\n' "$ffmpeg_sha" "$ffmpeg_archive" "$x264_sha" "$x264_archive" > "$source_dir/SHA256SUMS.txt"

tar -xf "$source_dir/$ffmpeg_archive" -C "$work_dir"
tar -xf "$source_dir/$x264_archive" -C "$work_dir"

(
  cd "$work_dir/x264-$x264_commit"
  ./configure --host=x86_64-w64-mingw32 --cross-prefix=x86_64-w64-mingw32- \
    --prefix="$prefix" --enable-static --disable-cli --disable-opencl \
    --extra-ldflags="-static -static-libgcc"
  make -j "$jobs"
  make install
) 2>&1 | tee "$work_dir/x264-build.log"

(
  cd "$work_dir/ffmpeg-$ffmpeg_version"
  PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" ./configure \
    --target-os=mingw32 --arch=x86_64 --cross-prefix=x86_64-w64-mingw32- \
    --pkg-config=pkg-config --pkg-config-flags=--static \
    --extra-cflags="-I$prefix/include" --extra-ldflags="-L$prefix/lib -static -static-libgcc" \
    --prefix="$prefix" --disable-autodetect --disable-shared --enable-static \
    --disable-doc --disable-debug --disable-network --disable-everything \
    --enable-gpl --enable-version3 --enable-libx264 \
    --enable-ffmpeg --enable-ffprobe --disable-ffplay \
    --enable-avcodec --enable-avformat --enable-avfilter --enable-avdevice \
    --enable-swscale --enable-swresample --enable-decoders --enable-parsers \
    --enable-filters --enable-bsfs --enable-protocol=file,pipe \
    --enable-indev=lavfi \
    --enable-demuxer=mov,matroska,avi,mpegts,mpegtsraw,mpegps,mpegvideo,asf,flv,ogg,mp3,aac,wav,image2,image2pipe,rawvideo \
    --enable-muxer=mp4,mov,matroska,webm,avi,mpegts,image2,image2pipe,rawvideo,md5,framemd5,null,wav,ogg \
    --enable-encoder=libx264,aac,mjpeg,png,rawvideo,pcm_s16le,wrapped_avframe
  make -j "$jobs" ffmpeg.exe ffprobe.exe
) 2>&1 | tee "$work_dir/ffmpeg-build.log"

cp "$work_dir/ffmpeg-$ffmpeg_version/ffmpeg.exe" "$output_dir/ffmpeg.exe"
cp "$work_dir/ffmpeg-$ffmpeg_version/ffprobe.exe" "$output_dir/ffprobe.exe"
cp "$work_dir/ffmpeg-$ffmpeg_version/COPYING.GPLv3" "$output_dir/LICENSE"
cp "$work_dir/ffmpeg-$ffmpeg_version/COPYING.GPLv2" "$output_dir/FFmpeg-GPLv2.txt"
cp "$work_dir/x264-$x264_commit/COPYING" "$output_dir/x264-COPYING.txt"
cp "$work_dir/ffmpeg-$ffmpeg_version/ffbuild/config.log" "$output_dir/config.log"
cp "$work_dir/ffmpeg-$ffmpeg_version/ffbuild/config.mak" "$output_dir/config.mak"
cp "$work_dir/x264-$x264_commit/config.log" "$output_dir/x264-config.log"
cp "$work_dir/x264-$x264_commit/config.mak" "$output_dir/x264-config.mak"
if [[ "$script_file" != "$source_dir/build-ffmpeg.sh" ]]; then
  cp "$script_file" "$source_dir/build-ffmpeg.sh"
fi
cp "$source_dir/SHA256SUMS.txt" "$output_dir/SOURCE-SHA256SUMS.txt"
mkdir -p "$output_dir/toolchain-notices"
for package in mingw-w64-common gcc-mingw-w64-base gcc-mingw-w64-x86-64-posix-runtime; do
  if [[ -f "/usr/share/doc/$package/copyright" ]]; then
    cp "/usr/share/doc/$package/copyright" "$output_dir/toolchain-notices/$package-copyright.txt"
  fi
done
x86_64-w64-mingw32-gcc --version > "$output_dir/compiler-version.txt"
dpkg-query -W gcc-mingw-w64-x86-64-posix gcc-mingw-w64-x86-64-posix-runtime mingw-w64-common nasm > "$output_dir/build-package-versions.txt"
(cd "$output_dir" && sha256sum ffmpeg.exe ffprobe.exe > BINARY-SHA256SUMS.txt)
cat > "$output_dir/README.txt" <<EOF
Dikey Studio Windows x64 video engine

FFmpeg $ffmpeg_version, unmodified upstream release source.
FFmpeg source: https://ffmpeg.org/releases/$ffmpeg_archive
x264 source commit: $x264_commit
x264 source: https://code.videolan.org/videolan/x264/-/archive/$x264_commit/$x264_archive
License: GNU GPL version 3 or later for this combined FFmpeg build.

This build enables x264 and FFmpeg's internal media components only.
It does not include Gyan's full-build external media library collection.
Windows system libraries and the MinGW/GCC toolchain runtime are used;
their notices and applicable runtime exceptions are retained separately.

Rebuild on Ubuntu 24.04 with:
  sudo apt-get install gcc-mingw-w64-x86-64-posix nasm make pkg-config curl xz-utils
  bash scripts/build-ffmpeg.sh build/ffmpeg

From the extracted standalone corresponding-source release archive instead:
  bash build-ffmpeg.sh ./ffmpeg-windows

Release source archive contains both original source tarballs, this build script,
checksums, compiler/package versions and original license notices.
No patches were applied to either upstream source archive.
Configuration: runtime folder contains config.log/config.mak and x264-config.log/x264-config.mak.
The source bundle names FFmpeg's copies ffmpeg-config.log and ffmpeg-config.mak.
EOF
cp "$output_dir/README.txt" "$source_dir/README.txt"
cp "$output_dir/compiler-version.txt" "$source_dir/compiler-version.txt"
cp "$output_dir/build-package-versions.txt" "$source_dir/build-package-versions.txt"
cp "$output_dir/LICENSE" "$source_dir/FFmpeg-GPLv3.txt"
cp "$output_dir/x264-COPYING.txt" "$source_dir/x264-COPYING.txt"
cp "$output_dir/config.mak" "$source_dir/ffmpeg-config.mak"
cp "$output_dir/config.log" "$source_dir/ffmpeg-config.log"
cp "$output_dir/x264-config.mak" "$source_dir/x264-config.mak"
cp "$output_dir/x264-config.log" "$source_dir/x264-config.log"
cp -R "$output_dir/toolchain-notices" "$source_dir/"
echo "Windows video engine ready: $output_dir"
echo "Corresponding media sources and build recipe: $source_dir"
echo "Intermediate build files retained in: $work_dir"
