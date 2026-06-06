# -*- coding: utf-8 -*-
"""
S-DoT 조도 → 시간대별 light_risk 전처리 (로컬 재현용)

기존 Colab 노트북(S_DoT_(조도)_전처리.ipynb)을 로컬에서 재현하되,
위험도 산출식만 '전역 min-max 정규화' → '법령 절대기준 앵커'로 교체.

  변경 전: light_risk = 1 - (lux - min) / (max - min)
  변경 후: light_risk = 1 - clip(lux, 0, 15) / 15
          (15 lux = 「보행자를 위한 도로 조명 기준」 표 4.2 P1 평균수평면조도)

이유: 0~23시 전체를 한 번에 min-max 정규화하면 분모가 대낮 직사광(최대 85,008 lux)에
      지배되어, 야간 조도(0~15 lux) 구간이 전부 risk≈1.0 으로 뭉쳐 변별력이 사라짐.
      법령 절대기준(15 lux=충분히 밝음)에 앵커링하면 야간 변별력이 회복됨.

사용법:
  .venv/bin/python db/preprocessing/sdot_light_preprocess.py
출력:
  db/preprocessing/light_hourly.csv   (DBeaver 로 sdot_light 테이블에 수동 적재)
"""
from pathlib import Path
import pandas as pd

# ---- 입력 경로 (원본 S-DoT 환경정보 + 기존 센서 위치 매핑) ----
RAW_ENV  = Path("/Users/jonghunpark/Downloads/스마트서울 도시데이터 센서(S-DoT) 환경정보.csv")
LOC_REF  = Path("/Users/jonghunpark/Downloads/light_hourly.csv")  # sensor_id→lat/lon 매핑 재사용
OUT_CSV  = Path(__file__).resolve().parent / "light_hourly.csv"

LUX_SAFE = 15.0  # 표 4.2 P1 평균수평면조도(lx) — '충분히 밝음(risk 0)' 앵커

def main():
    # 1) 원본 조도 로드 (필요한 3개 컬럼만)
    df = pd.read_csv(RAW_ENV, encoding="cp949",
                     usecols=["시리얼", "측정시간", "조도 평균(lux)"])
    df.columns = ["sensor_id", "time", "lux_avg"]

    # 2) 시간 파싱 → hour 추출
    df["time"] = pd.to_datetime(df["time"].str.replace("_", " "))
    df["hour"] = df["time"].dt.hour

    # 3) 결측 조도 제거
    df = df.dropna(subset=["lux_avg"])

    # 4) 센서×시간대 한 달 평균 조도
    hourly = (df.groupby(["sensor_id", "hour"])["lux_avg"]
                .mean().reset_index())

    # 5) 센서 위치(lat/lon) 매핑 — 기존 결과의 매핑 재사용 (위치 xlsx 불필요)
    loc = (pd.read_csv(LOC_REF)[["sensor_id", "lat", "lon"]]
             .drop_duplicates("sensor_id"))
    hourly = hourly.merge(loc, on="sensor_id", how="inner")  # 위치 알려진 센서만 (원본 파이프라인과 동일)

    # 6) 위험도 산출 (법령 절대기준 앵커)
    hourly["lux_norm"]   = hourly["lux_avg"].clip(lower=0, upper=LUX_SAFE) / LUX_SAFE  # 0~1 밝기
    hourly["light_risk"] = 1 - hourly["lux_norm"]

    # 7) 기존 테이블과 동일한 컬럼/순서로 저장 (드롭인 재적재)
    hourly = hourly[["sensor_id", "hour", "lat", "lon", "lux_avg", "lux_norm", "light_risk"]]
    hourly.to_csv(OUT_CSV, index=False)

    # ---- 요약 출력 ----
    n23 = hourly[hourly.hour == 23]["light_risk"]
    print(f"saved: {OUT_CSV}")
    print(f"rows: {len(hourly)} | sensors: {hourly.sensor_id.nunique()}")
    print(f"lux_avg max: {hourly.lux_avg.max():.1f}  (참고: 정규화 분모로 안 씀)")
    print(f"light_risk 전체 mean: {hourly.light_risk.mean():.3f}")
    print(f"야간(23시) light_risk  min/median/max: "
          f"{n23.min():.3f} / {n23.median():.3f} / {n23.max():.3f}")

if __name__ == "__main__":
    main()
