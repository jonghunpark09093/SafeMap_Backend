"""
경사도(slope) 재계산 - 분석가 ipynb의 get_height() transpose 버그 수정판.
- 고도 포인트(N3P_F002.shp, EPSG:5174)로 LinearNDInterpolator 구성 (그리드/transpose 미사용)
- DB road_links 지오메트리(EPSG:4326)를 5174로 투영해 끝점 고도차로 경사각(도) 계산
- DB는 쓰지 않고 결과만 검증/저장 (--write 옵션 시에만 UPDATE)
"""
import os, sys
import numpy as np
import geopandas as gpd
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from shapely import wkb
from pyproj import Transformer
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv(override=True)
HERE = os.path.dirname(os.path.abspath(__file__))
SHP = os.path.join(HERE, "data", "N3P_F002.shp")
ELEV_CRS = "EPSG:5174"  # Korean 1985 Modified Central Belt (prj 기준)

def engine():
    return create_engine(URL.create("postgresql",
        username=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), database=os.getenv("DB_NAME")))

def slope_to_risk(deg):
    # ipynb 색상구간(<4,<7,<10,>=10) → 4단계 위험도
    if deg < 4:   return 0.0
    if deg < 7:   return 0.3
    if deg < 10:  return 0.7
    return 1.0

def main():
    write = "--write" in sys.argv

    print("[1] 고도 포인트 로드:", SHP)
    elev = gpd.read_file(SHP)
    elev = elev.set_crs(ELEV_CRS, allow_override=True)
    pts = np.array([(g.x, g.y) for g in elev.geometry])
    hgt = elev["HEIGHT"].astype(float).values
    ok = ~np.isnan(hgt)
    pts, hgt = pts[ok], hgt[ok]
    print(f"    points={len(pts)}  height min/med/max = {hgt.min():.1f}/{np.median(hgt):.1f}/{hgt.max():.1f}")

    print("[2] 보간기 구성 (LinearNDInterpolator + Nearest 폴백)")
    lin = LinearNDInterpolator(pts, hgt)
    nrst = NearestNDInterpolator(pts, hgt)
    def z_at(xs, ys):
        z = lin(xs, ys)
        m = np.isnan(z)
        if m.any():
            z[m] = nrst(xs[m], ys[m])
        return z

    print("[3] road_links 로드")
    eng = engine()
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT id, ST_AsBinary(geometry) AS g, length FROM road_links")).fetchall()
    ids = [r[0] for r in rows]
    geoms = [wkb.loads(bytes(r[1])) for r in rows]
    lengths = np.array([r[2] for r in rows], float)
    print(f"    links={len(ids)}")

    print("[4] 끝점 투영(4326→5174) + 고도차 → 경사각")
    tf = Transformer.from_crs("EPSG:4326", ELEV_CRS, always_xy=True)
    x1 = np.empty(len(geoms)); y1 = np.empty(len(geoms))
    x2 = np.empty(len(geoms)); y2 = np.empty(len(geoms))
    for i, g in enumerate(geoms):
        cs = list(g.coords)
        x1[i], y1[i] = cs[0][0], cs[0][1]
        x2[i], y2[i] = cs[-1][0], cs[-1][1]
    X1, Y1 = tf.transform(x1, y1)
    X2, Y2 = tf.transform(x2, y2)
    z1 = z_at(np.array(X1), np.array(Y1))
    z2 = z_at(np.array(X2), np.array(Y2))
    planar = np.hypot(np.array(X2)-np.array(X1), np.array(Y2)-np.array(Y1))
    planar = np.where(planar < 1.0, 1.0, planar)  # 0길이 보호
    slope_deg = np.degrees(np.arctan(np.abs(z2 - z1) / planar))
    slope_deg = np.clip(np.nan_to_num(slope_deg, nan=0.0), 0, 60)
    risk = np.array([slope_to_risk(s) for s in slope_deg])

    print(f"    slope deg: min/med/p90/max = {slope_deg.min():.1f}/{np.median(slope_deg):.1f}/{np.percentile(slope_deg,90):.1f}/{slope_deg.max():.1f}")
    print(f"    risk 분포: " + ", ".join(f"{v}:{int((risk==v).sum())}" for v in [0.0,0.3,0.7,1.0]))

    print("[5] 검증 — 지역별 평균 경사 (부암동>광화문 이어야 정상)")
    areas = {
        "광화문광장(평지)": (126.9768, 37.5759),
        "종로3가(평지)":   (126.9919, 37.5704),
        "삼청동(언덕)":     (126.9817, 37.5836),
        "인왕산 누상동(언덕)": (126.9614, 37.5806),
        "부암동(급경사)":    (126.9656, 37.5928),
    }
    mids = np.array([list(g.interpolate(0.5, normalized=True).coords)[0] for g in geoms])
    MX, MY = tf.transform(mids[:,0], mids[:,1])
    MX, MY = np.array(MX), np.array(MY)
    for name, (lng, lat) in areas.items():
        cx, cy = tf.transform(lng, lat)
        d = np.hypot(MX-cx, MY-cy)
        sel = d < 150
        if sel.sum() == 0:
            print(f"    {name:18} (구간 없음)"); continue
        print(f"    {name:18} n={int(sel.sum()):>3}  avg={slope_deg[sel].mean():5.1f}  med={np.median(slope_deg[sel]):4.1f}  max={slope_deg[sel].max():4.1f}")

    np.savez(os.path.join(HERE, "slope_result.npz"), ids=np.array(ids), slope=slope_deg, risk=risk)
    print("[6] 결과 저장 → slope_result.npz")

    if write:
        print("[7] DB UPDATE 중...")
        with eng.begin() as c:
            c.execute(text("""
                UPDATE road_links AS r SET slope = d.slope, slope_risk_score = d.risk
                FROM (SELECT unnest(:ids) AS id, unnest(:sl) AS slope, unnest(:rk) AS risk) d
                WHERE r.id = d.id
            """), {"ids": ids, "sl": slope_deg.tolist(), "rk": risk.tolist()})
        print("    완료.")
    else:
        print("[7] (검증 모드 — DB 미변경. 반영하려면 --write)")

if __name__ == "__main__":
    main()
