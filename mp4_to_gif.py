#!/usr/bin/env python3
"""Convert an MP4 to a WeChat sticker GIF (240x240, 8fps, <1MB).

Usage: mp4_to_gif.py <input.mp4> <output.gif> [size] [fps] [max_bytes]
Defaults: size=240 fps=8 max_bytes=1000000
Requires: ffmpeg；gifsicle 可选（用于压到 1MB 内）
"""
import os
import shutil
import subprocess
import sys
import tempfile


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{r.stderr[-500:]}")


def gif_size(path):
    return os.path.getsize(path)


def convert(src, dst, size, fps):
    with tempfile.TemporaryDirectory() as td:
        pal = os.path.join(td, "palette.png")
        run(["ffmpeg", "-y", "-i", src, "-vf",
             f"fps={fps},scale={size}:{size}:flags=lanczos,palettegen", pal])
        run(["ffmpeg", "-y", "-i", src, "-i", pal, "-filter_complex",
             f"fps={fps},scale={size}:{size}:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
             "-loop", "0", dst])


def maybe_gifsicle(dst):
    if not shutil.which("gifsicle"):
        print("WARN: 未安装 gifsicle，跳过有损压缩", file=sys.stderr)
        return
    run(["gifsicle", "--batch", "--optimize=3", "--lossy=200", dst])


def main():
    src, dst = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 240
    fps = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    max_bytes = int(sys.argv[5]) if len(sys.argv) > 5 else 1_000_000

    if not shutil.which("ffmpeg"):
        sys.exit("FAILED: 未找到 ffmpeg，请先安装后再生成动图")

    convert(src, dst, size, fps)
    if gif_size(dst) > max_bytes:
        maybe_gifsicle(dst)
    if gif_size(dst) > max_bytes:
        convert(src, dst, size, 6)
        maybe_gifsicle(dst)
    print(f"OK {dst} {gif_size(dst)} bytes")


if __name__ == "__main__":
    main()
