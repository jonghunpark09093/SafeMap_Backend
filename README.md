# SafeMap_Backend

공공 민원 빅데이터 기반 지역 안전 지도 및 안심 경로 서비스 - 백엔드 API

## 프로젝트 개요
기존 최단 거리 중심의 길 찾기에서 벗어나, CCTV, 가로등, 경사도 등 다양한 안전 데이터를 융합하여 보행자에게 가장 안전한 우회 경로를 계산하고 제공하는 자체 구축 내비게이션 엔진입니다.

## 기술 스택
* 프레임워크: FastAPI (Python 3.8+)
* 데이터베이스: PostgreSQL 16 + PostGIS
* 경로 탐색 엔진: pgRouting
* 패키지 관리: pip

---

## 로컬 실행 방법

### 1. 레포지토리 클론
```bash
git clone [https://github.com/본인계정/SafeMap_BE.git](https://github.com/본인계정/SafeMap_Backend.git)
cd SafeMap_Backend
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정
루트 폴더에 `.env` 파일 생성 후 아래 내용 입력
```text
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=본인DB비밀번호
DB_NAME=safemap_db
```

### 4. 데이터베이스 세팅 (최초 1회)
로컬 PostgreSQL에 `safemap_db` 데이터베이스를 생성하고, 레포지토리에 포함된 `safemap_dump.sql` 파일을 Import 하여 공간 데이터와 테이블을 복원합니다.
```bash
# 터미널 복원 명령어 (경로 및 포트는 본인 환경에 맞게 수정)
pg_dump -U postgres -d safemap_db -f safemap_dump.sql
```

### 5. 개발 서버 실행
```bash
uvicorn main:app --reload
```
브라우저에서 `http://localhost:8000/docs` 접속 시 Swagger UI를 통해 API 테스트가 가능합니다.

---

## 주요 API 엔드포인트

### POST /api/routes/safe-path
출발지와 도착지 위경도를 입력받아 다익스트라(Dijkstra) 알고리즘 기반 최적의 안전 경로를 탐색하여 반환합니다.

**Request (Client -> Server)**
```json
{
  "start_lat": 37.5701,
  "start_lng": 126.9830,
  "end_lat": 37.5764,
  "end_lng": 126.9854,
  "persona": "일반"
}
```

**Response (Server -> Client)**
지도에 렌더링 가능한 Feature 형태의 GeoJSON 데이터를 반환합니다.
```json
{
  "status": "success",
  "message": "경로 탐색 완료",
  "total_distance_meters": 1250.5,
  "geojson": {
    "type": "Feature",
    "properties": {
      "name": "Safe Route",
      "distance": 1250.5
    },
    "geometry": {
      "type": "LineString",
      "coordinates": [
        [126.9830, 37.5701],
        [126.9835, 37.5705]
      ]
    }
  }
}
```

---

## 커밋 메시지 규칙
* feat: 새로운 기능 추가
* fix: 버그 수정
* style: 코드 포맷팅, 주석 변경
* refactor: 코드 리팩토링
* chore: 설정, 패키지 변경
* docs: 문서 수정
