import os
import json
import re
from typing import List, Dict
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv(override=True)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_url = URL.create(
    drivername="postgresql",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    database=os.getenv("DB_NAME")
)
engine = create_engine(db_url)

class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    persona: str
    request_hour: int 

def clean_text(text_data: str) -> str:
    if not text_data: return ""
    text_data = text_data.replace('\n', ' ').replace('\r', ' ')
    text_data = re.sub(r'[.,\s]+$', '', text_data)
    return re.sub(r'\s+', ' ', text_data).strip()

@app.post("/api/routes/safe-path")
def get_safe_path(request: RouteRequest):
    weights = {
        "general": {"sec": 1.0, "led": 1.0, "sdot": 1.0, "slp": 1.0, "civ": 1.0, "flow": 1.0},
        "women":   {"sec": 2.5, "led": 1.5, "sdot": 2.2, "slp": 1.0, "civ": 1.2, "flow": 1.8},
        "senior":  {"sec": 1.0, "led": 1.2, "sdot": 1.2, "slp": 5.0, "civ": 1.5, "flow": 1.0}
    }
    w = weights.get(request.persona.lower(), weights["general"])

    try:
        query = text("""
        WITH start_node AS (
            SELECT id FROM road_links_vertices_pgr
            ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:start_lng, :start_lat), 4326) LIMIT 1
        ),
        end_node AS (
            SELECT id FROM road_links_vertices_pgr
            ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:end_lng, :end_lat), 4326) LIMIT 1
        ),
        path_edges AS (
            SELECT p.edge, r.geometry, r.security_risk_score, r.led_risk_score, r.slope_risk_score, r.civil_risk_score, r.flow_risk_score, r.length,
                   COALESCE(s.light_risk, 0.5) AS sdot_risk_score
            FROM pgr_dijkstra(
                'SELECT r.id, r.source, r.target, 
                    (r.length * (1 + 
                        r.security_risk_score * :w_sec + 
                        r.led_risk_score * :w_led + 
                        COALESCE(s.light_risk, 0.5) * :w_sdot + 
                        r.slope_risk_score * :w_slp +
                        r.civil_risk_score * :w_civ +
                        r.flow_risk_score * :w_flow 
                    )) AS cost 
                 FROM road_links r
                 LEFT JOIN sdot_light s ON r.nearest_sdot_id = s.sensor_id AND s.hour = :req_hour',
                (SELECT id FROM start_node),
                (SELECT id FROM end_node),
                directed := false
            ) AS p
            JOIN road_links AS r ON p.edge = r.id
            LEFT JOIN sdot_light s ON r.nearest_sdot_id = s.sensor_id AND s.hour = :req_hour
            WHERE p.edge > 0
        ),
        nearby_risks AS (
            SELECT DISTINCT c.category, c.contents, ST_Y(c.geometry::geometry) AS lat, ST_X(c.geometry::geometry) AS lng
            FROM civil_risk_points c
            JOIN path_edges e ON ST_DWithin(c.geometry::geography, e.geometry::geography, 20)
        )
        SELECT 
            ST_AsGeoJSON(ST_LineMerge(ST_Union(e.geometry))) AS route_geojson,
            SUM(e.length) AS total_distance,
            COALESCE(SUM(e.security_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_sec,
            COALESCE(SUM(e.led_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_led,
            COALESCE(SUM(e.sdot_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_sdot,
            COALESCE(SUM(e.slope_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_slp,
            COALESCE(SUM(e.civil_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_civ,
            COALESCE(SUM(e.flow_risk_score * e.length) / NULLIF(SUM(e.length), 0), 0) AS avg_flow, -- ⭐️ 추출!
            (SELECT COALESCE(json_agg(json_build_object('type', category, 'detail', contents, 'lat', lat, 'lng', lng)), '[]') FROM nearby_risks) AS detected_points
        FROM path_edges e;
        """)

        with engine.connect() as conn:
            result = conn.execute(query, {
                "start_lng": request.start_lng, "start_lat": request.start_lat,
                "end_lng": request.end_lng, "end_lat": request.end_lat,
                "req_hour": request.request_hour,
                "w_sec": w["sec"], "w_led": w["led"], "w_sdot": w["sdot"], "w_slp": w["slp"], "w_civ": w["civ"],
                "w_flow": w["flow"] # 파라미터 바인딩 추가
            }).fetchone()

        if not result or not result[0]:
            raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")

        # 데이터 파싱
        dist = round(result[1], 2)
        # avg_flow 까지 6개의 위험도 추출
        avg_sec, avg_led, avg_sdot, avg_slp, avg_civ, avg_flow = [round(v, 3) for v in result[2:8]]
        markers = [ {**m, "detail": clean_text(m['detail']), "type": clean_text(m['type'])} for m in (result[8] or []) ]

        # 인사이트 생성 로직
        insights = []
        headers = {"women": "✅ [여성 안심]", "senior": "✅ [노약자 맞춤]", "general": "✅ [일반 추천]"}
        insights.append(headers.get(request.persona.lower(), headers["general"]))

        light_msg = ""
        if avg_led <= 0.3: light_msg += "가로등이 촘촘하게 설치되어 있으며, "
        else: light_msg += "가로등 배치가 다소 드문 구간이 포함되어 있으며, "

        if avg_sdot <= 0.3: light_msg += f"{request.request_hour}시 현재 실제 측정 조도가 매우 밝습니다."
        else: light_msg += f"{request.request_hour}시 현재 센서 조도가 다소 낮아 보행 시 주의가 필요합니다."
        insights.append(light_msg)

        if avg_sec <= 0.4: insights.append("CCTV 밀집 구역을 우선 경유합니다.")
        if avg_slp >= 0.6: insights.append("경사가 급한 오르막/계단 구간이 있으니 참고 바랍니다.")
        
        if avg_flow <= 0.4:
            insights.append("주변 유동 인구가 적절히 확보되어 야간에도 고립감이 덜한 경로입니다.")
        elif avg_flow >= 0.7:
            insights.append("인적이 상대적으로 드문 구간이 일부 포함되어 있습니다.")

        if markers:
            risk_types = list(set([m['type'] for m in markers]))
            insights.append(f"실시간으로 감지된 '{', '.join(risk_types[:2])}' 등의 요소를 알고리즘에 반영하였습니다.")

        return {
            "status": "success",
            "persona_applied": request.persona,
            "request_hour": request.request_hour,
            "total_distance_meters": dist,
            "route_analysis": {
                "summary": " ".join(insights),
                "scores": {
                    "infrastructure_led": avg_led,
                    "realtime_sdot_light": avg_sdot,
                    "security_cctv": avg_sec,
                    "slope": avg_slp,
                    "civil_complaint": avg_civ,
                    "floating_population": avg_flow 
                },
                "markers": markers
            },
            "geojson": {"type": "Feature", "geometry": json.loads(result[0])}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

        