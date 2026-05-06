# ==========================================
# 1. 패키지 가져오기
# ==========================================
import os
import json
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ==========================================
# 2. 환경 변수 및 데이터베이스 설정
# ==========================================
load_dotenv(override=True)

# FastAPI 앱 생성 및 CORS 설정
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLAlchemy DB 엔진 (pgRouting 전용)
db_url = URL.create(
    drivername="postgresql",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    database=os.getenv("DB_NAME")
)
engine = create_engine(db_url)

# ==========================================
# 3. 데이터 모델 정의
# ==========================================
class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    persona: str     

# ==========================================
# 4. API 엔드포인트
# ==========================================
@app.get("/")
def read_root():
    return {"message": "SafeMap 서버 구동 중"}

# 자체 구축 DB 기반 안전 경로 탐색 API (pgRouting + GeoJSON 반환)
@app.post("/api/routes/safe-path")
def get_safe_path(request: RouteRequest):
    try:
        # 출발지/도착지 인접 노드를 탐색하고, total_cost 기반 다익스트라 알고리즘 실행 후 GeoJSON으로 반환
        query = text("""
            WITH start_node AS (
                SELECT id FROM road_links_vertices_pgr
                ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:start_lng, :start_lat), 4326) LIMIT 1
            ),
            end_node AS (
                SELECT id FROM road_links_vertices_pgr
                ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:end_lng, :end_lat), 4326) LIMIT 1
            )
            SELECT  
                ST_AsGeoJSON(ST_LineMerge(ST_Union(r.geometry))) AS route_geojson,
                SUM(r.length) AS total_distance
            FROM pgr_dijkstra(
                'SELECT id, source, target, total_cost AS cost FROM road_links',
                (SELECT id FROM start_node),
                (SELECT id FROM end_node),
                directed := false
            ) AS p
            JOIN road_links AS r ON p.edge = r.id
            WHERE p.edge > 0;
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query, {
                "start_lng": request.start_lng, 
                "start_lat": request.start_lat,
                "end_lng": request.end_lng, 
                "end_lat": request.end_lat
            }).fetchone()
            
        if not result or not result[0]:
            raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")

            # 4. 프론트엔드가 바로 그릴 수 있도록 'Feature' 껍데기를 씌워서 반환
        return {
            "status": "success", 
            "message": "경로 탐색 완료", 
            "total_distance_meters": round(result[1], 2),
            "geojson": {
                "type": "Feature",
                "properties": {
                    "name": "Safe Route",
                    "distance": round(result[1], 2)
                },
                "geometry": json.loads(result[0])
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"경로 탐색 오류: {str(e)}")