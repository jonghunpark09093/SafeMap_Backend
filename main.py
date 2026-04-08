from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2  # 👈 파이썬아, 아까 설치한 배달부 좀 불러와! (이 줄이 핵심입니다)
from pydantic import BaseModel #👈 데이터 모델을 정의하기 위한 도구
from typing import List  # 👈 리스트 형태를 명시하기 위한 도구


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#=============== 데이터 규격 ==================
# 1. 프론트엔드가 우리엥게 보낼 주문서(Request) 양식 정의.
class RouteRequest(BaseModel):
    start_lat: float # 출발지 위도
    start_lng: float # 출발지 경도
    end_lat: float   # 도착지 위도
    end_lng: float   # 도착지 경도
    persona: str     # 사용자 유형( "여성1인가구", "보행약자")

# 2. 우리가 프론트엔드에게 줄 '지도 좌표 한 개' 모양 정의.
class Coordinate(BaseModel):
    lat: float
    lng: float

#3. 우리가 프론트엔드에게 줄 '최종 결과물(Response)' 모양 정의.
class RouteResponse(BaseModel):
    status: str              # 상태 (성공/실패)
    total_distance: float    # 총 이동 거리 (m)
    total_danger_score: int  # 총 위험도 점수
    path: List[Coordinate]   # 지도 위에 그릴 최적 경로 묶음 (좌표 리스트)

# ============길 찾기 알고리즘 (현재는 가짜 데이터를 반환하는 뼈대)============
def calculate_safe_route_mock(start_lat, start_lng, end_lat, end_lng, persona):
    print(f"[{persona} 모드] DB에서 {start_lat, start_lng}에서 {end_lat, end_lng}까지의 안전한 경로 계산 중...")
   
    # 실제 알고리즘이 들어갈 자리. 지금은 가짜 데이터를 반환하기.
    fake_path = [
            {"lat": start_lat, "lng": start_lng},           # 출발지
            {"lat": start_lat + 0.001, "lng": start_lng + 0.001}, # 중간 지점 1
            {"lat": start_lat + 0.002, "lng": start_lng - 0.001}, # 중간 지점 2
            {"lat": end_lat, "lng": end_lng}                    # 도착지    
        ]
    
    return {
        "distance": 450.5,
        "danger_score": 12,
        "path": fake_path
    }

# 🧠 페르소나별 맞춤형 가중치(비용) 계산 공식 뱉어주는 함수
def get_cost_query_by_persona(persona: str):
    """
    이 함수는 DB에게 '어떤 기준으로 길의 비용(cost)을 계산할지'
    SQL 수식을 만들어서 던져주는 역할을 합니다.
    """
    
    if persona == "여성1인가구":
        # 야간 안전이 최우선: 거리가 좀 멀어도 가로등이 많고 CCTV가 있는 곳을 선호
        # cost = 실제거리 + (어두움 페널티 * 3배) + (CCTV 없음 페널티 * 2배)
        return "distance + (danger_score * 3.0)" 
        
    elif persona == "보행약자":
        # 물리적 편안함이 최우선: 거리가 멀어도 경사가 없고 턱이 없는 곳을 선호
        # 나중에 CSV에 slope(경사도) 컬럼이 추가되면 이렇게 씁니다.
        # return "distance + (slope_score * 5.0)"
        return "distance + (danger_score * 1.5)"
        
    else:
        # 기본 모드 (최단 거리 위주, 위험도는 살짝만 반영)
        return "distance + danger_score"
    
#=================  API 엔드포인트 =================  
@app.get("/")
def read_root():
    return {"message": "맥북에서 띄운 첫 안전 지도 서버가 무사히 켜졌습니다!"}

@app.get("/db-test")
def test_db_connection():
    try:
        # DB(냉장고) 문 열기 
        conn = psycopg2.connect(
            host="localhost",
            port="5433",            dbname="postgres" ,
            user="postgres",
            password="whdgnspark28@"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM nodes;")
        node_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM links;")
        link_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return {
            "status": "DB 연결 대성공! 데이터 확인 완료 🎉", 
            "total_nodes": f"{node_count} 개의 교차로가 있습니다.",
            "total_links": f"{link_count} 개의 길이 있습니다."
        }
        
    except Exception as e:
        return {"status": "DB 연결 실패...", "error": str(e)}

# 프론트엔드가 길 찾기를 요청할 API 주소.
@app.post("/api/route", response_model=RouteResponse)   
def get_safe_route(request: RouteRequest):

        # 1. 방금 만든 알고리즘 뼈대 함수에 프론트엔드가 준 데이터를 집어넣기.
        result = calculate_safe_route_mock(
            start_lat=request.start_lat,
            start_lng=request.start_lng,
            end_lat=request.end_lat,
            end_lng=request.end_lng,
            persona=request.persona
        )

        # 2. 약속한 RouteResponse 모양에 맞게 데이터를 가공해서 프론트엔드에게 돌려주기.
        return RouteResponse(
            status="success",
            total_distance=result["distance"],
            total_danger_score=result["danger_score"],  
            path=result["path"]
        )


