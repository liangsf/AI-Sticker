#!/usr/bin/env python3
"""Make a WeChat chat-page icon: remove solid-color background (green screen),
trim to content, resize to 50x50 with transparency.

Usage: make_icon.py <input.png> <output.png> [bg_hex] [size]
bg_hex: background color to remove, default 00FF00 (chroma green)
Requires: PIL, numpy, scipy
"""
import sys
from collections import deque
import numpy as np
from PIL import Image
from scipy import ndimage

def main():
    src, dst = sys.argv[1], sys.argv[2]
    bg_hex = sys.argv[3] if len(sys.argv) > 3 else "00FF00"
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    br, bg_, bb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))

    a = np.array(Image.open(src).convert("RGBA")).astype(int)
    h, w = a.shape[:2]

    # Chroma mask: pixels close to bg color
    dist = np.abs(a[:,:,0]-br) + np.abs(a[:,:,1]-bg_) + np.abs(a[:,:,2]-bb)
    chroma = dist < 150

    # Flood fill from borders only (protects interior colors matching bg)
    visited = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h-1):
            if chroma[y, x] and not visited[y, x]:
                visited[y, x] = True; dq.append((y, x))
    for y in range(h):
        for x in (0, w-1):
            if chroma[y, x] and not visited[y, x]:
                visited[y, x] = True; dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
            ny, nx = y+dy, x+dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and chroma[ny, nx]:
                visited[ny, nx] = True; dq.append((ny, nx))

    # Dilate mask to eat color fringe, then kill remaining fringe pixels
    mask = ndimage.binary_dilation(visited, iterations=2)
    alpha = a[:,:,3].copy()
    alpha[mask] = 0
    edge = ndimage.binary_dilation(mask, iterations=3) & ~mask
    fringe = edge & (dist > 150) & (
        (np.abs(a[:,:,0]-br) + np.abs(a[:,:,2]-bb) > np.abs(a[:,:,1]-bg_) + 60)
        | (dist < 220))
    alpha[fringe] = 0

    out = a.copy()
    out[:,:,3] = alpha
    img = Image.fromarray(out.astype(np.uint8))

    # Trim to content bbox, 10px margin
    ys, xs = np.where(alpha > 0)
    y0, y1 = max(0, ys.min()-10), min(h-1, ys.max()+10)
    x0, x1 = max(0, xs.min()-10), min(w-1, xs.max()+10)
    img = img.crop((x0, y0, x1+1, y1+1))

    # Square-crop center, resize
    cw, ch = img.size
    s = min(cw, ch)
    img = img.crop(((cw-s)//2, (ch-s)//2, (cw+s)//2, (ch+s)//2))
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dst, optimize=True)
    print(f"OK {dst} {img.size}")

if __name__ == "__main__":
    main()
