# syntax=docker/dockerfile:1
# 머물멍을 이미지 하나로 만들어요: 백엔드(웹 API) + 빌드한 React 화면 + 샘플 데이터.
#
#   docker compose up -d --build      →  http://localhost:3000
#
# API 키나 .env, 센터·허브 원자료, 실행 결과는 이미지에 넣지 않아요 (.dockerignore 참고).

# ---------------------------------------------------------------- 1) 화면 빌드 (Node 는 여기서만 써요)
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 2) 실행 이미지
FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul \
    MEOMUL_HOME=/app/backend

# 제안서의 발급 시각과 실행 기록을 한국 시간으로 남기려고 시간대 자료를 넣어요.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.lock ./
RUN pip install -r requirements.lock

COPY backend/pyproject.toml backend/README.md ./
COPY backend/config ./config
COPY backend/data/ref ./data/ref
COPY backend/meomulmeong ./meomulmeong
COPY backend/eval ./eval
COPY --from=web /web/dist /app/frontend/dist

# 루트가 아닌 사용자로 실행해요. 샘플(합성) 데이터 창고는 이미지에 미리 만들어 둬요 (시드 고정이라 늘 같은 값이에요).
RUN useradd --create-home --uid 10001 meomul \
    && mkdir -p outputs \
    && chown -R meomul:meomul /app/backend
USER meomul
RUN python -m meomulmeong build-data --mode synthetic

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json,urllib.request,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=4))['ok'] else 1)"

ENTRYPOINT ["python", "-m", "meomulmeong"]
# 컨테이너 안에서는 모든 주소로 듣고, 밖으로 여는 범위는 docker-compose.yml 의 ports 가 정해요.
CMD ["serve", "--host", "0.0.0.0", "--port", "3000"]
