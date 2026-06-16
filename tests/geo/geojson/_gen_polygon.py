"""沿三省合并外轮廓控制点等距插值，生成 200 顶点的 polygon GeoJSON。"""
import json
import math

# 甘肃 / 陕西 / 青海 合并区域外轮廓的近似控制点（顺时针，[经度, 纬度]）
# 北缘(西->东) -> 东缘(北->南) -> 南缘(东->西) -> 西缘(南->北)
control = [
    # 北缘：青海西北 -> 河西走廊北缘 -> 甘肃东北 -> 陕北
    (90.5, 38.8), (92.5, 39.5), (93.0, 42.0), (95.5, 42.8), (98.5, 42.6),
    (100.5, 42.7), (102.5, 42.3), (103.8, 41.2), (106.0, 39.4), (108.0, 39.5),
    (110.2, 39.6),
    # 东缘：陕西东部沿黄河南下
    (110.6, 38.0), (110.5, 36.5), (110.4, 35.0), (111.0, 34.5), (110.5, 33.5),
    (110.6, 32.7), (109.8, 31.8),
    # 南缘：陕南 -> 陇南 -> 青海南部(果洛/玉树) -> 可可西里
    (108.0, 32.5), (106.0, 32.7), (104.0, 32.9), (102.0, 33.5), (100.5, 33.8),
    (99.0, 33.2), (97.5, 32.3), (95.5, 33.0), (93.5, 32.5), (91.0, 32.0),
    (89.6, 33.0),
    # 西缘：青海西部北上
    (89.5, 35.0), (90.0, 37.0), (90.2, 38.5),
]

def interpolate(pts, n):
    """沿闭合折线周长等距取 n 个点。"""
    ring = pts + [pts[0]]
    seg = []
    total = 0.0
    for a, b in zip(ring, ring[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        seg.append(d)
        total += d
    step = total / n
    out = []
    target = 0.0
    si, acc = 0, 0.0
    for _ in range(n):
        while si < len(seg) and acc + seg[si] < target:
            acc += seg[si]
            si += 1
        if si >= len(seg):
            break
        a, b = ring[si], ring[si + 1]
        t = (target - acc) / seg[si] if seg[si] else 0.0
        lng = round(a[0] + (b[0] - a[0]) * t, 4)
        lat = round(a[1] + (b[1] - a[1]) * t, 4)
        out.append([lng, lat])
        target += step
    return out

verts = interpolate(control, 200)
verts.append(verts[0])  # 闭合环：首尾相同

geojson = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "甘陕青三省覆盖范围", "vertices": 200},
        "geometry": {"type": "Polygon", "coordinates": [verts]},
    }],
}

with open("polygon_3provinces.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print(f"生成完成：{len(verts) - 1} 个顶点 (+1 闭合点) -> polygon_3provinces.geojson")
