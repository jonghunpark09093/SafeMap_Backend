from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import requests
import psycopg2
from dotenv import load_dotenv

# ==========================================
# ⚙️ 1. 기본 환경 세팅
# ==========================================
load_dotenv(override=True) # .env 금고 열기

app = FastAPI()

# CORS 방어벽 해제 (프론트엔드와 통신하기 위함)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 📦 2. 데이터 규격 (프론트엔드와의 약속)
# ==========================================
class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    persona: str     

class Coordinate(BaseModel):
    lat: float
    lng: float

class RouteResponse(BaseModel):
    status: str              
    total_distance: float    
    total_danger_score: int  
    path: List[Coordinate]   

# ==========================================
# 🛠️ 3. 핵심 도구 (DB 및 외부 API 연결 함수)
# ==========================================

# 🐘 DB 연결 함수
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return None

# 🗺️ Tmap API 호출 함수
def get_tmap_pedestrian_route(start_lat: float, start_lng: float, end_lat: float, end_lng: float):
    url = "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1"
    headers = {
        "accept": "application/json",
        "appKey": os.getenv("TMAP_APP_KEY") 
    }
    payload = {
        "startX": start_lng,
        "startY": start_lat,
        "endX": end_lng,
        "endY": end_lat,
        "reqCoordType": "WGS84GEO", 
        "resCoordType": "WGS84GEO",
        "startName": "출발지",      
        "endName": "도착지"
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Tmap 에러 발생: {response.status_code}")
        return None

# ==========================================
# 🧠 4. 비즈니스 로직 (안전도 계산 알고리즘)
# ==========================================

def calculate_safety_score(tmap_data, db_conn):
    """
    Tmap이 준 경로를 따라가며 반경 50m 이내의 CCTV 개수를 세고 위험도를 계산합니다.
    """
    # 1. Tmap 데이터에서 총 거리 추출 (Tmap JSON의 특징)
    total_distance = 0
    if 'features' in tmap_data and len(tmap_data['features']) > 0:
        total_distance = tmap_data['features'][0]['properties'].get('totalDistance', 0)

    # 2. 길(LineString)의 좌표들만 뽑아서 프론트엔드용 리스트로 만들기
    path_coords = []
    for feature in tmap_data['features']:
        if feature['geometry']['type'] == 'LineString':
            for coord in feature['geometry']['coordinates']:
                # Tmap은 [경도(lng), 위도(lat)] 순서로 줍니다.
                path_coords.append({"lat": coord[1], "lng": coord[0]})

    if not path_coords:
        return None

    # 3. DB 엔진(PostGIS)을 활용해 경로 주변 CCTV 탐색
    cursor = db_conn.cursor()
    total_cctv_count = 0

    for pt in path_coords:
        lon, lat = pt["lng"], pt["lat"]
        # ST_DistanceSphere: 지구 둥근 표면을 고려한 미터(m) 단위 거리 계산 마법의 함수!
        query = """
            SELECT COUNT(*)
            FROM cctv_cameras
            WHERE ST_DistanceSphere(
                ST_MakePoint(longitude, latitude),
                ST_MakePoint(%s, %s)
            ) <= 50;
        """
        cursor.execute(query, (lon, lat))
        total_cctv_count += cursor.fetchone()[0]

    cursor.close()

    # 4. 알고리즘 산출 (CCTV 1개당 위험도 3점 하락)
    danger_score = 100 - (total_cctv_count * 3)
    if danger_score < 0:
        danger_score = 0 

    return {
        "distance": total_distance,
        "danger_score": danger_score,
        "path": path_coords
    }

# 페르소나 적용 함수 (추후 확장용으로 남겨둠)
def get_cost_query_by_persona(persona: str):
    if persona == "여성1인가구":
        return "distance + (danger_score * 3.0)" 
    elif persona == "보행약자":
        return "distance + (danger_score * 1.5)"
    else:
        return "distance + danger_score"
    

# ==========================================
# 🚀 5. API 엔드포인트 (프론트엔드 연결부)
# ==========================================

@app.get("/")
def read_root():
    return {"message": "맥북에서 띄운 첫 안전 지도 서버가 무사히 켜졌습니다!"}

@app.get("/db-test")
def test_db_connection_endpoint():
    # 우리가 방금 만든 cctv_cameras 테이블이 잘 있는지 테스트하도록 수정했습니다.
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("DB 연결 실패")
            
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM cctv_cameras;")
        cctv_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return {
            "status": "DB 연결 대성공! 🐘", 
            "message": f"현재 DB에 {cctv_count} 개의 CCTV 데이터가 장전되어 있습니다."
        }
    except Exception as e:
        return {"status": "DB 연결 실패...", "error": str(e)}

# 🌟 최종 메인 API (여기서 모든 함수가 합체됩니다!)
@app.post("/api/route", response_model=RouteResponse)
def get_safe_route(request: RouteRequest):
    
    # 방어벽: 서울 좌표 검사
    if not (37.4 < request.start_lat < 37.7) or not (126.7 < request.start_lng < 127.2):
        raise HTTPException(status_code=400, detail="지원하지 않는 지역입니다. 서울 내에서만 출발/도착이 가능합니다.")
        
    # STEP 1. DB 연결
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="데이터베이스에 연결할 수 없습니다.")

    # STEP 2. Tmap 길 찾기 요청
    tmap_data = get_tmap_pedestrian_route(
        start_lat=request.start_lat,
        start_lng=request.start_lng,
        end_lat=request.end_lat,
        end_lng=request.end_lng
    )

    if not tmap_data:
        conn.close() # 에러 나도 DB 문은 닫아주는 센스!
        raise HTTPException(status_code=500, detail="Tmap에서 경로를 가져오지 못했습니다.")

    # STEP 3. 안전 알고리즘 실행 (DB 조회)
    result = calculate_safety_score(tmap_data, conn)
    
    # 다 썼으면 DB 문 닫기
    conn.close()

    if not result:
        raise HTTPException(status_code=500, detail="경로 데이터 분석에 실패했습니다.")

    # STEP 4. 프론트엔드에 최종 결과 반환
    return RouteResponse(
        status="success",
        total_distance=result["distance"],
        total_danger_score=result["danger_score"],  
        path=result["path"]
    )