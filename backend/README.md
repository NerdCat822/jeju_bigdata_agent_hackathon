# 머물멍 백엔드

**머물멍 (Jeju Town Vitality Agent)** 의 에이전트 코어예요. 읍면동 하나를 두고 세 질문에 차례로 답해요.

| 단계 | 질문 | 산출물 |
|---|---|---|
| Stage 1 청년이 머무는 동네 | 어디서 청년이 빠지고, 어디는 버티는가 | 읍면동 활력 유형 A~D, 유사 읍면 3곳, 추천 순위 |
| Stage 2 빈자리를 누가 채우나 | 빈자리를 채우는 소비는 어디·언제·무엇에 오는가 | 타깃 관광객, 테마·요일 프로필, 규칙 기반 제안 |
| Stage 3 어떻게 오게 하나 | 감편 조건에서 수요는 어떻게 변하고, 어떤 노선·코스로 오는가 | 수요 시나리오, 관광 민감 노선, 거점→동네 코스 |

숫자는 SQL이, 제안 후보는 규칙이 만들고, LLM은 질문 해석과 쉬운 해설만 맡아요. 한 줄 결론도 규칙이 만든 문장을 그대로 써요.
화면은 React 웹이에요. 화면 코드는 [../frontend/](../frontend/README.md)에 있고, 이 백엔드가 여는 웹 API(`python -m meomulmeong serve`, 8절)를 불러 써요.

기획서: [../머물멍_AI_Agent_기획서.pdf](../머물멍_AI_Agent_기획서.pdf)

---

## 1. 빠른 시작

Python 3.11 과 PostgreSQL 이 필요해요. 아래는 `backend/` 폴더에서 실행해요.

```bash
# 0) 데이터 창고(PostgreSQL) 띄우기. 저장소 맨 위의 docker-compose.yml 에 들어 있어요 (127.0.0.1:5434)
docker compose -f ../docker-compose.yml up -d db

# 1) 설치 (uv 사용)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt -e .

# uv 가 없으면
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock pytest ruff
.venv/bin/python -m pip install -e . --no-deps

# 2) 샘플(합성) 데이터를 만들어 PostgreSQL 에 넣기 (약 25초)
.venv/bin/python -m meomulmeong build-data

# 3) 질문하기 (LLM 없이 동작하는 템플릿 모드)
.venv/bin/python -m meomulmeong ask "성산읍 청년 인구 왜 줄었어?"
.venv/bin/python -m meomulmeong ask "성산읍에 누가 올까?" -v          # 근거표와 SQL까지 보기
.venv/bin/python -m meomulmeong chain 성산읍 --report                  # Stage 1→2→3 + 최종 제안서(HTML)
.venv/bin/python -m meomulmeong status                                 # 데이터·LLM 상태

# 4) 웹 API 서버 띄우기 (React 화면이 붙는 곳)
.venv/bin/python -m meomulmeong serve                                  # http://127.0.0.1:8501 , API 문서는 /docs
```

Windows 에서는 `.venv/bin/python` 대신 `.venv\Scripts\python` 을 써요.

Docker 없이 따로 설치한 PostgreSQL 을 쓰려면 `.env` 에 `MEOMUL_PG_HOST`, `MEOMUL_PG_PORT`, `MEOMUL_PG_DB`, `MEOMUL_PG_USER`,
`MEOMUL_PG_PASSWORD` 를 넣어요. 데이터베이스와 사용자는 미리 만들어 두고, 사용자에게 스키마를 만들 권한을 줘요.

클라우드 LLM(Claude)으로 실행하려면 `.env` 에 `ANTHROPIC_API_KEY` 를 넣고 `--llm anthropic` 을 붙여요.
명령줄에서는 `--yes-cloud` 로 전송에 동의해야 LLM에 보내요. 동의하지 않으면 규칙 문장으로 답해요.

```bash
.venv/bin/python -m meomulmeong ask "성산읍 청년 인구 진단" --llm anthropic --yes-cloud
```

환경변수는 `.env.example` 을 `.env` 로 복사해 채워요. `.env` 는 저장소에 올리지 않아요.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `MEOMUL_DATA_MODE` | `synthetic` | `synthetic`(샘플) · `hub`(허브 수집본) · `center`(센터 추출본) |
| `MEOMUL_LLM_MODE` | `template` | `template`(LLM 없음, 화면에는 '기본 (AI 없이)') · `anthropic`(클라우드 Claude, 선택) |
| `MEOMUL_ANTHROPIC_MODEL` | `claude-opus-5-5` | 클라우드 모델 |
| `ANTHROPIC_API_KEY` | (없음) | 클라우드 모드에서만 필요 |
| `MEOMUL_HUB_PROJECT_KEY` | (없음) | 제주데이터허브 프로젝트 키 (수집할 때만) |
| `MEOMUL_HOME` / `MEOMUL_OUTPUTS` | 이 폴더 / `outputs/` | 설정·데이터 위치, 결과 저장 위치 |
| `MEOMUL_API_HOST` / `MEOMUL_API_PORT` | `127.0.0.1` / `8501` | 웹 API 서버 주소. 기본은 이 PC 안에서만 열려요 |
| `MEOMUL_CORS_ORIGINS` | 5173·3000 포트의 localhost | 개발할 때 React 개발 서버에서 API를 부를 수 있게 허용할 주소 (쉼표로 구분) |
| `MEOMUL_WEB_DIST` | `../frontend/dist` | 빌드한 React 화면 폴더. 있으면 같은 주소에서 화면도 함께 내줘요 |
| `MEOMUL_LOCK_MODES` | `false` | `true` 면 데이터·AI 설명 방식을 바꾸는 API(`POST /api/modes`)를 403 으로 막고, 화면은 지금 모드를 읽기 전용으로 보여 줘요. 여러 사람이 같은 주소를 쓰는 배포본용 (모드는 서버 전체에 걸려요) |
| `NAVER_CLOUD_PLATFORM_CLIENT_ID` / `NAVER_CLOUD_PLATFORM_CLIENT_SECRET` | (없음) | 네이버 클라우드 Maps (선택). 있으면 화면의 지도를 네이버 지도로 그리고(Dynamic Map), 지도에서 누른 곳·주소로 읍면동 찾기(Reverse Geocoding·Geocoding), 코스의 자동차 도로 경로·거리·시간(Directions 5), 제안서 위치 지도(Static Map)를 써요. Secret 은 서버 밖으로 내보내지 않아요. `MEOMUL_NAVER_MAP_CLIENT_ID` / `_SECRET` 으로 써도 돼요. Dynamic Map 은 NCP 콘솔에 등록한 웹 주소에서만 열려요 |
| `MEOMUL_NAVER_MAPS` | `true` | `false` 면 키가 있어도 네이버 지도를 쓰지 않아요 (인터넷이 없는 센터 PC). 지도를 못 불러오면 화면은 기본 지도로 바꿔 그려요 |
| `MEOMUL_API_DOCS` | `true` | `false` 면 `/docs` · `/redoc` · `/openapi.json` 을 열지 않아요. 공개 주소에 둘 때 꺼요 |

`.env` 에 값을 비워 둔 항목은 기본값을 써요.

---

## 2. 폴더 구조

```
backend/
├─ config/
│  ├─ settings.yaml        분석 임계값 (τ ±3%, 최소 인구 100명, 월 일수 20일, 탄력성 ε …)
│  ├─ playbook.yaml        Stage 2 제안 규칙 12개 (코드 없이 수정)
│  ├─ export_rules.yaml    반출 게이트 규칙 (최소 셀 크기, 식별 컬럼)
│  └─ catalog/*.yaml       테이블 설명 파일 (YAML 한 장 = 테이블 하나)
├─ data/
│  ├─ ref/                 참조표 CSV (읍면동 43개, 지구, 테마, 거점, 노선, 방문목적, 국적)
│  ├─ synthetic/ hub/ center/   원본 (합성 · 허브 수집본 · 센터 추출본), 저장소에 올리지 않음
│  └─ export/              export-csv 로 내보낸 CSV, 저장소에 올리지 않음 (다른 PC 로 옮겨 build-data 로 다시 올릴 수 있어요)
│                          (데이터 창고는 파일이 아니라 PostgreSQL 에 있어요. 모드마다 스키마 하나)
├─ meomulmeong/
│  ├─ settings.py  schemas.py  fmt.py  service.py  cli.py  progress.py(진행 알림)
│  ├─ api/         app(웹 API 서버, FastAPI). React 화면이 부르는 곳
│  ├─ data/        refs(장소 표준화) · catalog · warehouse(적재·읽기 전용 조회) · periods · synthetic · hub_client
│  ├─ tools/       common · stage1 · stage2 · stage3 · shared · output
│  ├─ agent/       parser(해석기) · stages(계획·실행) · verifier(검증기) · explainer(해설기) · orchestrator · memory · prompts/
│  ├─ llm/         base · anthropic_provider · factory
│  └─ report/      builder · svg · templates/proposal.html.j2
├─ eval/           golden.yaml(60문항) · make_golden · expected(pandas 기대값 계산) · __main__
├─ tests/          pytest 254개
└─ outputs/        제안서(reports/) · 실행 기록(runs/*.jsonl) · 평가 보고서(eval/)
```

---

## 3. 동작 흐름

```
질문 ─▶ 해석기 ─▶ 확인 카드 ─▶ 계획·실행 ─▶ 검증기 ─▶ 해설기 ─▶ 답 · 제안서
        규칙 파서     이렇게       레시피 선택      숫자·인과     템플릿 또는
        (+LLM)       이해했어요    도구(SQL) 실행   참조·가정     LLM(검증 통과분만)
```

1. **해석기** — 규칙 파서가 단계·의도·장소·연령·기간·테마·가정치를 뽑아요. 장소는 참조표로 표준화해요(법환동 → 대륜동).
   규칙으로 확신하지 못한 질문만 LLM(JSON 스키마 강제)에 넘기고, LLM이 낸 장소도 참조표에 없으면 버려요.
2. **확인 카드** — `ConfirmCard.chips` 로 장소·연령·기간·가정을 보여 주고, 읍면동이 빠졌으면 `runnable=False` 로 알려요.
3. **계획·실행** — 단계별 레시피가 도구를 순서대로 불러요. Stage 2·3은 앞 단계 산출물(유형 → 타깃 관광객)이 없으면 먼저 실행해요.
4. **검증기** — 아래 5절의 장치로 문장을 검사해요. LLM 해설이 떨어지면 고칠 점을 알려 주고 최대 2회 다시 쓰게 한 뒤, 그래도 떨어지면 템플릿 해설로 대체해요.
   다시 쓰는 데 걸린 시간이 한도(기본 45초)를 넘겨도 템플릿 해설로 대체해요.
5. **해설기** — 템플릿 해설은 지표만으로 만드는 고정 문장이에요. LLM 모드에서는 이 초안과 지표를 주고 3문장 이내로 다듬게 해요.
   한 줄 결론, 원인을 묻는 질문의 답, 목록이 들어가는 답(추천 순위, 코스, 코스까지 보여 주는 Stage 3 전체 계획)은 LLM 모드에서도 규칙 문장을 그대로 써요.
   연계 실행에서는 "처음부터 끝까지" 대신 단계마다 물을 질문을 따로 만들어 LLM에 넘겨요.
6. **답** — `Answer`: 한 줄 결론, 해설, 배지, 차트·지도 사양, 근거표(+SQL), 제안, 한계, 다음 질문 3개, 검증 결과, 실행 기록.

연계 실행(`chain`)은 이 흐름을 Stage 1 → 2 → 3 으로 세 번 돌리고 제안서를 만들어요.

---

## 4. 도구

| 구분 | 도구 | 기능 |
|---|---|---|
| 공통 | `resolve_place` `search_catalog` `run_sql` | 장소 표준화, 테이블 검색, 읽기 전용 SQL(SELECT 한 문장, 허용 테이블, 행 수·시간 제한) |
| Stage 1 | `s1_trend` `s1_classify` `s1_peers` `s1_zone` | 청년 거주·근무·방문 추이와 지표 7종, 유형 분류·추천 순위, 유사 읍면, 지구 묶음 진단 |
| Stage 2 | `s2_shift` `s2_playbook` | 중국인 테마별 소비·단체/개별 인당 배율·요일·국적 분석, 규칙 12개로 제안 후보 생성 |
| Stage 3 | `s3_forecast` `s3_route_beta` `s3_courses` | 수요 기준선·시나리오(ε 0.5/1.0/1.5), 노선 관광 민감도 β, 직행·환승 1회 코스와 접근성 공백 |
| 출력 | `make_chart` `make_map` `build_report` `export_check` | 차트·지도 사양, 최종 제안서(HTML), 반출 규칙 검사 |

지표 산식과 분류 규칙은 기획서 4.4 와 같아요. 모든 근거표에 실행한 SQL이 붙어요.

---

## 5. 판단의 안전장치

| 장치 | 막는 문제 | 구현 |
|---|---|---|
| 숫자 대조 | 해설 속 숫자와 근거 불일치 | 문장의 모든 숫자를 지표·근거표 값과 대조 (반올림 허용, "10만 493명"처럼 나눠 쓴 수는 합쳐서 대조) |
| 숫자-지표 짝 | 맞는 숫자를 다른 지표의 값처럼 씀 | 숫자가 가리키는 지표의 낱말이 같은 문장에 있어야 함 |
| 초안 충실도 | 숫자를 초안과 다른 대상에 붙임, 근거 없는 순위·평가, 뒤바뀐 배율 | 초안에서 그 숫자와 함께 쓰인 대상(내국인·중국인·테마·지명)만 허용. "가장 빠른 코스" 같은 최상급 표현은 초안·지표 이름·규칙 제안에 있을 때만 허용. Stage 2의 지역 단위 값을 읍면동 값처럼 쓴 문장, 배율의 방향을 뒤바꾼 문장("주말에 비해 평일 소비가 0.89배")도 차단 |
| 인과 표현 가드 | "관광객 때문에 청년이 떠났다" | 때문·원인·탓·초래 등을 탐지. 뒤에 유보 표현이 있을 때만 허용. 원인 질문은 정해진 문장으로만 답함 |
| 예측·추측 가드 | "올 거예요", "가능성이 있어요", "예상되는 수치" | 단정적 예측과 추측 표현 차단 (가정을 밝힌 시나리오 문장은 허용) |
| 형식 검사 | 지시문·입력을 되받아 적음, 한 줄 결론만 되풀이 | LLM 해설이 입력 표지를 담거나 480자를 넘으면 다시 쓰게 함. 한 줄 결론만 되풀이하면 바로 템플릿 해설로 대체 |
| 참조 대조 | 없는 노선·읍면동 | 노선 번호와 지명을 참조표·근거와 대조 |
| 제안 근거 | 근거 없는 제안 | 제안은 `playbook.yaml` 규칙만 만들고, 규칙 ID와 근거 지표를 함께 표시 |
| 기간 확인 | 기간이 다른 데이터 혼합 | 함께 쓰는 지표의 기간이 겹치지 않으면 규칙을 적용하지 않고 "함께 볼 수 없음" |
| 작은 표본 | 인구가 적은 곳의 변화율 과장 | 기준 인구 100명 미만은 배지로 표시하고 추천·자동 선택에서 제외 |
| 가정치 표시 | 시나리오를 예측으로 오인 | 가정 배지, ε 0.5/1.0/1.5 민감도 표, "가정" 문구 필수 |
| 반출 게이트 | 원자료·소집단 노출 | LLM에는 집계 지표만 전달. 식별 컬럼 금지, 센터 모드에서 최소 셀 미만 가림 |

클라우드 모드에서는 `Answer.llm_payload` 로 전송 내용을 미리 보여 주고, `svc.set_cloud_consent(session_id, True)` 로 동의한 뒤에만 보내요.

---

## 6. 데이터

### 6.1 데이터 모드

| 모드 | 원본 위치 | 만드는 법 | 배지 |
|---|---|---|---|
| `synthetic` | `data/synthetic/` | `build-data` 가 시드 고정 합성 데이터를 만들어요 (2023-11~2026-10, 시드 20261119) | 샘플 데이터 |
| `hub` | `data/hub/` | `fetch-hub` 로 허브 Open API 를 받은 뒤 `build-data --mode hub` | 실데이터 |
| `center` | `data/center/` | 센터 추출 CSV 를 넣고 `build-data --mode center` (센터 자료가 없는 테이블은 허브 자료를 써요) | 센터 데이터 |

`build-data` 는 원본을 읽어 PostgreSQL 에 넣어요. 데이터 모드마다 스키마 하나를 쓰고, 그 안에 데이터 종류마다 테이블 하나를 만들어요.

| 스키마 안의 것 | 내용 |
|---|---|
| 표준 테이블 8개 | `pop_kor_emd_daily`, `pop_for_long_emd_daily`, `bus_route_daily`, `arrivals_purpose_monthly`, `foreign_visitors_monthly`, `card_cn_area_monthly`, `card_zone_dow_monthly`, `spend_tour_type_monthly` |
| 월 집계 테이블 3개 | `m_pop_kor_emd_month`, `m_pop_for_long_emd_month`, `m_bus_route_month` |
| 참조표 `ref_*` | 읍면동, 지구, 테마, 거점, 노선, 방문목적, 국적, 요일 달력 |
| `meta_*` | 테이블별 수록 기간과 행 수, 적재 때 빠진 행, 만든 시각 |

새 스키마를 다 만든 뒤 한 번에 바꿔치기해서, 만드는 동안에도 기존 데이터로 답할 수 있어요. 분석할 때는 읽기 전용으로만 붙어요.
받은 자료를 파일로 보고 싶으면 `python -m meomulmeong export-csv --mode hub` 로 `data/export/hub/` 에 CSV 를 내보내요.
허브 · 센터 자료는 재배포할 수 없어서 이 폴더는 저장소에 올리지 않아요.

내보낸 CSV 는 다른 PC 로 창고를 옮길 때도 써요. `data/export/hub/` 폴더를 그 PC 의 같은 자리에 그대로 복사하고
`build-data --mode hub` 를 실행하면, 수집본(`data/hub/<폴더>/`)이 없는 테이블은 `data/export/hub/<테이블>.csv` 에서 변환 없이 올려요.
수집본이 있으면 수집본을 먼저 써요. 월 집계 테이블(`m_*.csv`)은 읽지 않고 올린 표에서 다시 계산해요. 허브 API 를 다시 부르지 않아도 돼요.

합성 데이터는 허브 API 응답과 같은 컬럼으로 만들어져 실데이터와 같은 적재 경로를 지나요. 읍면동마다 숨은 유형을 심어 두어서
세 단계가 끝까지 이어지는지 시험할 수 있어요. 실제 통계가 아니므로 화면과 제안서에 "샘플 데이터" 배지가 붙어요.

### 6.2 표준 테이블 (카탈로그)

| 테이블 | 허브 데이터 (ID) | 단위 | 단계 |
|---|---|---|---|
| `pop_kor_emd_daily` | 읍면동 단위 내국인 유동인구 (583) | 읍면동 × 일 × 성별 × 연령대 | 1 |
| `pop_for_long_emd_daily` | 읍면동 단위 외국인 장기체류 유동인구 (590) | 읍면동 × 일 × 국가 | 1 |
| `card_zone_dow_monthly` | 관광지 및 상업지구 요일별 카드 (608) | 5개 지구 × 월 × 요일 | 1·2 |
| `card_cn_area_monthly` | 업종별 성별 카드 이용 정보 (1048, 파일을 `data/hub/card_biz/`에), 없으면 중국인 관광객 지역, 업종별 카드 이용 (600) | 1048은 제주 전체 × 테마 × 월, 600은 시군구 × 도심/읍면 × 테마 × 월 | 2 |
| `spend_tour_type_monthly` | 단체/개별 관광객 소비 (603) | 업종 × 내국인/중국인 × 단체/개별 × 월 | 2·3 |
| `foreign_visitors_monthly` | 국가별 입도객 현황 (582) 또는 파일 `외국인관광객현황_20251231` | 국적 12종 × 월 | 2·3 |
| `arrivals_purpose_monthly` | 방문목적별 입도객 현황 (580) | 방문목적 9종 × 월 | 3 |
| `bus_route_daily` | 일일 노선별 버스 이용자 정보 (614) | 노선 × 일 | 3 |

적재할 때 읍면동 이름을 행정동 코드로 통일하고(법정동·별칭 포함), 연령대는 10세 단위, 업종은 6개 테마로 맞춰요.
연결하지 못한 이름과 날짜 변환 실패는 `status` 의 `issues` 에 보고해요. 월 집계 테이블(`m_*`)과 수록 기간표(`meta_table`)도 함께 만들어요.

### 6.3 허브 수집

```bash
# .env 에 MEOMUL_HUB_PROJECT_KEY 를 넣은 뒤 (허브에서 데이터마다 '프로젝트 담기' 필요)
# 월 단위 5종은 전 기간을 한 번에 받아요
.venv/bin/python -m meomulmeong fetch-hub --table arrivals_purpose_monthly --table foreign_visitors_monthly \
    --table card_cn_area_monthly --table card_zone_dow_monthly --table spend_tour_type_monthly
# 일 단위 유동인구는 비교할 24개월을, 달마다 나흘만 받아요 (쿼터 절약)
.venv/bin/python -m meomulmeong fetch-hub --table pop_kor_emd_daily --table pop_for_long_emd_daily \
    --start 20240901 --end 20260831 --days 1,9,17,25
# 버스는 입도객 자료와 겹치는 12개월을, 달마다 이틀만 받아요
.venv/bin/python -m meomulmeong fetch-hub --table bus_route_daily --start 20240801 --end 20250731 --days 9,25
.venv/bin/python -m meomulmeong build-data --mode hub
```

받은 쪽은 `data/hub/_raw/` 에 남겨 두고, 다음 실행 때 없는 쪽부터 이어 받아요. API별 호출 상한(`--max-calls`, 기본 900)에 닿으면 멈추고 안내해요.

실제 호출로 확인한 것 (2026-11-16)

| 항목 | 내용 |
|---|---|
| 응답 형식 | `{"totCnt": N, "hasMore": true, "data": [...]}`. 컬럼 이름은 카탈로그 변환식과 8종 모두 같아요 |
| 쪽 나누기 | `number`(1부터), `limit`. `limit` 은 100이 상한이고 더 크게 주면 실패해요 |
| 불안정 | 허브 프록시가 요청 두 번에 한 번꼴로 502(가끔 403)를 돌려줘요. 수집기는 한 쪽에 10번까지 다시 보내요 |
| 쿼터 | API별 하루 1,000건이고 실패한 요청도 세요. 차면 403 과 "Today's quota is full" 이 와요. 수집기는 멈추고 다음 날 이어 받으라고 알려요 |
| 하루 행 수 | 내국인 유동인구 688행, 외국인 장기체류 600행 안팎, 버스 노선별 2천 행 안팎 |
| 최신 자료 | 일 단위 3종은 2026-08 까지, 입도객 2종은 2025-07 까지, 카드 3종은 2016~2018년 |

일 단위 자료를 다 받으면 쿼터(API별 하루 1,000건)로 며칠이 걸려요. 그래서 `--days` 로 달마다 며칠만 받고, 분석은 받은 날의 하루 평균으로 해요.
허브 모드에서는 "한 달에 며칠 이상 있어야 지표에 넣는다"는 기준을 `analysis.min_month_days_hub`(기본 2일)로 따로 둬요.
파일 데이터 `외국인관광객현황_20251231` 은 CSV 로 내려받아 `data/hub/foreign_visitors/` 에 넣으면 돼요 (세로형·가로형 모두 읽어요).

### 6.4 새 데이터 붙이기

`config/catalog/` 에 YAML 한 장을 추가하고 `build-data` 를 다시 실행해요. `select` 에 표준 컬럼별 변환식(PostgreSQL SQL)을 적어요.
센터 추출본은 `sources.center.file_glob` 로 파일 이름을 지정해요. 자세한 형식은 [config/catalog/README.md](config/catalog/README.md)에 있어요.

---

## 7. LLM 모드

| 모드 | 모델 | 쓰는 곳 | 비고 |
|---|---|---|---|
| `template` (기본) | 없음 | 규칙 파서 + SQL·문장 템플릿 | 외부 전송 0건, 완전 재현 |
| `anthropic` | `claude-opus-5-5` | 불확실한 질문 해석, 쉬운 해설, 자유 질문 SQL | 공식 SDK, 구조화 출력, 서버 측 거절 대체(`fallbacks="default"`). 집계 지표만 보내고, 전송 동의 뒤에만 써요 |

로컬 LLM(Ollama · Qwen3)은 쓰지 않아요 (2026-11-13 팀 결정). 그래서 인터넷이 없는 센터 PC에서는 템플릿 모드로만 돌아가요.

- `config/settings.yaml` 의 `llm.explain: false` 로 두면 해설은 항상 규칙 문장이고 LLM은 해석과 자유 질문에만 써요.
- `llm.template_only_intents` 에 적은 답 종류는 LLM 모드에서도 규칙 문장을 써요. 기본값은 추천 순위(`recommend`), 코스(`courses`), Stage 3 전체 계획(`plan`: 시나리오·노선·코스를 함께 보여 주는 답, 연계 실행의 Stage 3 포함)이에요.
  Claude 에게 `plan` 해설도 맡기려면 목록에서 빼고 10절처럼 실제 호출로 다시 확인해 보세요.
- `llm.explain_budget_seconds`(기본 45초)를 넘기면 더 다시 쓰지 않고 템플릿 해설로 대체해요. 답 하나가 몇 분씩 걸리지 않게 하는 장치예요.
- 자유 질문(준비된 분석에 맞지 않는 조회)은 LLM이 SQL을 쓰고, "자유 질문 · SQL 검토 필요" 배지를 붙여요. LLM이 쓴 SQL이라 실험 기능으로 봐 주세요.
- LLM을 쓸 수 없으면(API 키 없음, 인증 실패, 인터넷 연결 없음) 템플릿 모드로 내려가고 `status().llm_note` 에 이유를 적어요.

---

## 8. 웹 API (React 화면에서 쓰는 법)

```bash
.venv/bin/python -m meomulmeong serve                  # http://127.0.0.1:8501
.venv/bin/python -m meomulmeong serve --llm anthropic --open   # 클라우드 LLM 모드로 띄우고 브라우저 열기
```

API 문서는 `/docs`, 명세는 `/openapi.json` 에 있어요. 화면 쪽 타입(`frontend/src/api/schema.d.ts`)은 이 명세에서 만들어요.

```bash
cd ../frontend && npm run gen:api      # 백엔드 모델을 바꾼 뒤에 실행해요
```

명세 사본(`frontend/src/api/openapi.json`)이 실제 명세와 다르면 백엔드 테스트 하나가 실패해서 알려 줘요.

### 8.1 화면 흐름과 호출

| 화면 | 호출 | 받는 것 |
|---|---|---|
| 첫 화면 | `GET /api/bootstrap` | 상태(데이터 배지, LLM 모드, 수록 기간), 읍면동 43곳(좌표), 단계별 추천 질문, 선택지(테마·거점·유형 범례·가정 기본값) |
| 질문 입력 | `POST /api/understand` `{question, session_id?}` | `{session_id, card}`. `card.chips` 가 "이렇게 이해했어요" 칩이에요 |
| 카드 수정 | `POST /api/confirm` `{query}` | 고친 해석으로 다시 만든 카드 (실행하지 않아요) |
| 실행 | `POST /api/run` `{query, session_id}` | `{session_id, answer}` |
| 바로 실행 | `POST /api/ask` `{question, session_id?}` | `kind` 가 `answer` 면 `answer`, `chain` 이면 `chain` 과 `report_url` |
| 처음부터 끝까지 | `POST /api/chain` `{place, with_report?}` | Stage 1~3 답 3개와 `report_url` |
| 진행 상황 보이기 | `POST /api/run/stream` · `/api/ask/stream` · `/api/chain/stream` | 위 셋과 같은 입력. 진행 알림과 답을 SSE 로 받아요 (8.3) |
| 제안서 | `POST /api/reports` `{session_id, place?}` 뒤 `GET /api/reports/{filename}` | HTML. `?download=true` 를 붙이면 파일로 받아요 |
| 모드 전환 | `POST /api/modes` `{data_mode?, llm_mode?}` | 바뀐 상태. 데이터 모드를 바꾸면 대화 맥락은 새로 시작해요 |
| 전송 동의 | `POST /api/sessions/{session_id}/cloud-consent` `{consent}` | 클라우드 모드에서 `answer.llm_payload` 를 미리 보여 준 뒤에 켜요 |
| 상태 | `GET /api/health` · `/api/status` · `/api/places` · `/api/options` | 준비 여부, 상태, 읍면동, 선택지 |

- **세션**: 요청에 `session_id` 를 넣지 않으면 새로 만들어 돌려줘요. 같은 값을 계속 넣으면 "거기 30대만?" 같은 후속 질문과 단계 연계가 이어져요.
  세션은 서버 메모리에만 있어서 서버를 다시 띄우면 사라져요.
- **카드 수정**: `card.query` 에서 바꿀 값만 고쳐 `/api/run` 에 보내면 돼요. 장소는 `place_name` 만 새 이름으로 바꾸면 서버가 코드를 다시 찾아요.
  참조표에 없는 장소·테마·거점과 범위를 벗어난 값은 서버가 버려요.
- **한 번에 하나**: 분석은 한 번에 하나씩 실행해요. 앞 요청이 끝날 때까지 다음 요청은 기다려요.
- **오류**: `{"detail": {"code": "...", "message": "..."}}` 모양이에요. `message` 는 화면에 그대로 보여 줄 수 있는 문장이에요.
  입력 형식 오류(422)는 FastAPI 기본 모양이에요. 분석을 못 한 경우는 오류가 아니라 `answer.ok = false` 와 `answer.message` 로 와요.

| 상태 코드 | code | 뜻 |
|---|---|---|
| 503 | `warehouse_missing` | 데이터 창고가 없거나 PostgreSQL 에 붙지 못했어요. `docker compose up -d db` 와 `build-data` 를 먼저 실행해야 해요 (`/api/health` 의 `ready` 로 미리 알 수 있어요) |
| 409 | `warehouse_missing` | 바꾸려는 데이터 모드의 창고가 없어요 |
| 404 | `unknown_place` · `report_not_found` | 모르는 읍면동, 없는 제안서 |
| 400 | `nothing_to_report` | 제안서에 넣을 분석 결과가 아직 없어요 |

### 8.2 답(Answer)에 들어 있는 것

| 필드 | 화면에서 쓰는 곳 |
|---|---|
| `headline` · `explanation` | 한 줄 결론, 쉬운 해설 |
| `badges` | 샘플 데이터 / 유형 C / 가정 같은 배지 (`tone`: type · assumption · data · warn · info) |
| `charts` | 차트 사양: `kind`(line · bar · hbar), `x`, `series[{name, y}]`, `y_format`(num · pct · index · won), `highlight`(화면에서 강조할 가로축 항목) |
| `maps` | 지도 사양: `points[{name, lat, lon, category, role}]`, `lines`(코스), `legend` |
| `evidence` | 근거표: `columns`, `rows`, `formats`, `sql`(접어서 보여 줘요), `period` |
| `suggestions` | 규칙이 만든 제안: `rule_id`, `text`, `evidence_text` |
| `limits` · `notices` | 한계, 안내(자동 선택·템플릿 대체 등) |
| `next_questions` | 다음 질문 3개 (`kind`: next_stage · follow_up · report) |
| `verification.checks` | 검증 항목별 통과 여부 |
| `explained_by` · `llm_mode` · `llm_payload` | 해설을 누가 썼는지, LLM 모드, 전송 미리보기 |
| `steps` | 실행 기록 (도구, 걸린 시간, LLM 시도) |

### 8.3 진행 상황 받기 (SSE)

클라우드 LLM 모드에서는 답 하나에 3~9초가 걸려요 (10절). 스트리밍 경로를 쓰면 그동안 무엇을 하는지 보여 줄 수 있어요.

| event | data |
|---|---|
| `progress` | `{kind: "start"}` · `{kind: "stage", stage, title, place}` · `{kind: "tool", tool, label, ok, seconds}` · `{kind: "llm", purpose, label, attempt}` · `{kind: "llm_result", attempt, ok, note}` |
| `answer` | 답(Answer) 하나. 연계 실행은 단계가 끝날 때마다 한 번씩 와요 |
| `done` | `{session_id, kind, elapsed}`. 연계 실행은 `place_name`, `report_url` 도 와요 |
| `error` | `{code, message}` |

```ts
const res = await fetch("/api/ask/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question, session_id }),
});
const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
let buf = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += value;
  let cut: number;
  while ((cut = buf.indexOf("\n\n")) >= 0) {
    const block = buf.slice(0, cut);
    buf = buf.slice(cut + 2);
    const event = /^event: (.*)$/m.exec(block)![1];
    const data = JSON.parse(/^data: (.*)$/m.exec(block)![1]);
    if (event === "progress") showProgress(data);      // data.label: "청년 인구 추이 계산", "쉬운 해설 쓰기" …
    else if (event === "answer") renderAnswer(data);
    else if (event === "done") finish(data);
    else if (event === "error") showError(data.message);
  }
}
```

### 8.4 개발할 때와 센터 PC에 올릴 때

- **개발**: React 개발 서버(Vite 기본 5173 포트)에서 `http://127.0.0.1:8501/api/...` 를 바로 부를 수 있어요. 5173·3000 포트는 허용해 두었어요.
  개발 서버의 프록시로 `/api` 를 8501 로 넘겨도 돼요.
- **센터 PC**: `frontend` 폴더에서 `npm run build` 로 만든 `frontend/dist` 가 있으면 `serve` 가 같은 주소에서 화면도 함께 내줘요. 센터 PC에는 Node 가 없어도 돼요.
- **오프라인 주의**: 센터 PC는 인터넷이 안 돼요. 글꼴·아이콘·차트 라이브러리를 CDN 에서 불러오면 안 되고 빌드 결과물에 넣어야 해요.
  지도 타일 서버도 쓸 수 없어서 지도는 좌표 점이나 로컬 GeoJSON 으로 그려야 해요. `/docs` 화면도 CDN 을 써서 오프라인에서는 열리지 않아요.
- **접속 범위**: 로그인 기능이 없어요. 기본값(127.0.0.1)은 이 PC 안에서만 열려요. `--host 0.0.0.0` 은 믿을 수 있는 망에서만 쓰세요.

### 8.5 Python 에서 직접 쓰기

```python
from meomulmeong.service import AgentService

svc = AgentService.create()                      # .env 의 데이터·LLM 모드를 읽어요
sid = svc.agent.session().id                     # 대화 하나 = 세션 하나
card = svc.understand("성산읍 청년 인구 왜 줄었어?", sid)   # 확인 카드
answer = svc.run(card.query, sid)                # 답 (pydantic 모델, answer.model_dump_json() 으로 직렬화)
chain = svc.run_chain("성산읍", sid, with_report=True)      # 처음부터 끝까지 → chain.answers, chain.report_path
```

---

## 9. 테스트와 평가

```bash
.venv/bin/python -m pytest -q              # 254개 (실제 Claude 호출 1개는 기본 제외), 약 1분. PostgreSQL 이 떠 있어야 해요.
                                           # 테스트 전용 스키마(mt…)에 합성 데이터를 새로 넣고 끝나면 지워요. 개발용 스키마는 건드리지 않아요
.venv/bin/python -m pytest -m cloud        # 실제 Claude API 왕복 시험 (API 키 필요, 요금이 나가요)
.venv/bin/python -m eval                   # 골든셋 60문항 (템플릿 모드)
.venv/bin/python -m eval --llm anthropic   # 클라우드 LLM 모드 (요금이 나가요)
.venv/bin/python -m eval.make_golden       # 기대값 다시 만들기 (같은 시드면 같은 파일)
```

골든셋 기대값은 에이전트의 SQL과 다른 경로(`eval/expected.py`, pandas 로 원본 Parquet 를 직접 계산)로 만들어요.

**템플릿 모드 결과 (2026-11-13, 샘플 데이터)**

| 구분 | 문항 | 정확도 | 목표 |
|---|---:|---:|---:|
| Stage 1 | 20 | 100% | 95% |
| Stage 2 | 15 | 100% | 90% |
| Stage 3 | 15 | 100% | 90% |
| 연계 | 5 | 100% | 80% |
| 인과 함정 | 5 | 100% | 100% |

응답 시간은 문항당 평균 0.05초 안팎, 연계 3단계는 0.1초 안팎이었어요. 클라우드 LLM 모드의 확인 결과는 10절에 적었어요.

---

## 10. 클라우드 LLM 확인 (Claude)

`claude-opus-5-5` 로 실제 질문 다섯 개를 돌려 확인했어요 (2026-11-13, 샘플 데이터, 전송 동의 상태).
질문은 Stage 1 진단, Stage 2 타깃, Stage 3 감편 시나리오, 지명을 줄여 쓴 질문("애월 쪽 젊은 사람들 요즘 어때?"), 자유 질문(버스 노선 상위 5개)이에요.

| 항목 | 처음 | 검증기를 고친 뒤 |
|---|---:|---:|
| 정답 (해석·수치) | 5 / 5 | 5 / 5 |
| LLM 해설 채택 | 4건 | 5건 |
| 첫 시도에 검증 통과 | 1건 | 5건 |
| 템플릿 해설로 대체 | 1건 | 0건 |
| LLM 호출 | 12회 | 7회 |
| 답 하나에 걸린 시간 | 3.0~15.4초 | 2.3~8.7초 |
| 보낸 · 받은 토큰 | 24,326 · 2,260 | 14,033 · 1,252 |

**처음에 걸린 이유** — Claude 의 해설은 틀린 곳이 없었는데, 검증기가 맞는 문장을 떨어뜨렸어요.

- "성산읍에 사는 20·30대는 … 1,589명" → 검증기가 "사는"을 거주인구로 알아보지 못했어요.
- "성산읍 거주인구 가운데 20·30대 비중은 17.5%" → 비중의 정의를 풀어 쓴 "거주"를 다른 대상으로 봤어요.
- "국내선 좌석이 10% 줄고" → "좌석"을 국내선 공급으로 알아보지 못했어요.

그래서 지표를 가리키는 낱말에 "사는 · 살고"(거주), "좌석 · 국내선"(공급)을 더하고, 비중 · 정주비의 정의를 풀어 쓸 때 나오는 낱말은 같은 대상으로 보게 했어요.
낱말을 넓혀도 다른 지표에 숫자를 붙이면 여전히 걸러요 (`tests/test_verifier.py`).

**함께 고친 것**

- 자유 질문의 조회 결과에서 큰 정수에 천 단위 쉼표를 붙여 넘겨요. 전에는 모델이 "9730808명"처럼 그대로 옮겨 적었어요.
- 정주비에 정의를 붙였어요: "정주비 (거주 ÷ 거주·근무·방문 합)". 정의가 없을 때는 모델이 뜻을 짐작해 풀어 썼어요.

**설계에 남아 있는 것** — 소형 로컬 모델로 시험하던 때 만든 장치예요. Claude 에서도 그대로 둬요.

- 프롬프트는 근거 목록으로 끝내고, 다시 쓰게 할 때의 고칠 점은 맨 앞에 붙여요.
- 연계 실행은 단계마다 물을 질문을 따로 만들어 넘겨요.
- 한 줄 결론만 되풀이한 해설은 다시 쓰게 하지 않고 바로 템플릿 해설로 바꿔요.
- 목록이 들어가는 답(추천 순위, 코스, Stage 3 전체 계획)은 규칙 문장을 써요 (`llm.template_only_intents`).
- 검증기가 잡지 못하는 것: 숫자가 없는 문장의 뜻 바뀜, "가장 많아요"처럼 근거 없이 덧붙인 평가 가운데 최상급 낱말이 없는 것.

골든셋 15문항 같은 큰 측정은 요금이 나가서 아직 하지 않았어요 (`python -m eval --llm anthropic --limit 3`).

---

## 11. 확인이 필요한 것과 남은 일

**실데이터로 확인해야 하는 가정**

- [x] 허브 유동인구 값의 단위: 하루 24개 시각 값의 합이 맞아요. 24로 나눈 읍면동 거주인구가 주민등록 인구의 75~100% 수준이에요 (2026-11-16 확인, 제주 전체 약 49만 명).
- [x] 허브 API의 쪽 매개변수(`number`, `limit` 100 상한)와 응답 형식(`totCnt`, `hasMore`, `data`): 2026-11-16 실제 호출로 확인했어요 (6.3절).
- [ ] 일 단위 데이터의 쿼터: 다 받으면 며칠이 걸려서 달마다 며칠만 받아요 (`--days`). 더 촘촘히 받으려면 쿼터 증량을 허브에 문의해야 해요.
- [ ] 허브 카드 데이터의 수록 기간(2016-09~2018-12)이 유동인구·입도객과 겹치지 않아요. 실데이터 모드에서는 Stage 2 규칙이 "기간이 겹치지 않아 함께 볼 수 없음"으로 빠질 수 있어요.
- [ ] `외국인관광객현황_20251231` 파일의 실제 컬럼 구성.

**참조표**

- [ ] `ref_route.csv`, `ref_route_emd.csv` 는 샘플이에요. 허브 `버스 노선 기본 정보`(611)·`버스 정류소 기본 정보`(612)와 경유 정류소 자료로 다시 만들어야 해요.
- [ ] 카드 5개 지구와 읍면동의 연결(`ref_card_zone.csv`), 7권역 배정, 읍면동 좌표는 잠정값이에요.
- [ ] 행정동 경계 GeoJSON 이 없어요. 지금은 대략 좌표로 점 지도를 그려요. 구하면 API 로 내주는 경로를 더해야 해요.

**팀에서 정할 것**

- [ ] 센터 PC는 인터넷이 없어 클라우드 LLM을 쓸 수 없어요. 로컬 LLM을 쓰지 않기로 해서 센터에서는 템플릿 모드로만 돌아가요.
      기획서 PDF 는 이에 맞춰 고쳤어요 (2026-11-13). 발표 자료를 만들 때도 같은 기준으로 써 주세요.

**구현**

- [x] React 화면(`frontend/`). 실행과 구성은 [../frontend/README.md](../frontend/README.md)에 있어요.
- [x] 데이터 창고를 DuckDB 파일에서 PostgreSQL 로 옮겼어요 (2026-11-16). 골든셋 60문항과 허브 실데이터 답의 숫자가 옮기기 전과 같은 것을 확인했어요.
- [x] Docker 에서 허브 실데이터 쓰기: `build-data --mode hub` 가 같은 PostgreSQL 에 넣으므로 화면에서 바로 고를 수 있어요 (12절). 센터 데이터는 센터 PC 에서만 쓸 수 있어요.
- [ ] `install.bat` / `run.bat`, 오프라인 설치 꾸러미(wheelhouse + 빌드한 화면). `run.bat` 은 `python -m meomulmeong serve --prepare --open` 을 부르면 돼요.
      데이터 창고는 센터 PC 에 설치된 PostgreSQL 을 써요. `.env` 의 `MEOMUL_PG_*` 에 접속 정보를 넣고, 그 사용자에게 스키마를 만들 권한이 있어야 해요.
- [x] 기획서 PDF 의 Streamlit · 로컬 LLM 문구를 React 웹 · 템플릿 + Claude 로 고쳤어요 (2026-11-13).
- [x] 기획서 PDF 의 DuckDB 표기 네 군데(6쪽 흐름도와 데이터 상자, 11쪽 기술 표, 13쪽 오픈소스)를 PostgreSQL 로 고쳤어요 (2026-11-16).
- [x] 기획서 12쪽 설치 항목에서 "오프라인 패키지로 pip 설치"와 "Docker·WSL 불필요" 문구를 지웠어요 (2026-11-16). `install.bat` → `run.bat` 만 남아요.
- [ ] 센터 모드: `4-11 유동인구 v02`, `3-02 버스 노선별 이용` 변환식은 명세서만 보고 썼어요. 실제 추출본으로 검증해야 해요. `1-08 카드 v02`(읍면동 × 업종 42개)는 아직 연결하지 않았어요.
- [ ] 반출 신청 패키지, PDF 제안서 (기획서의 탑재 후 확장 항목).
- [ ] `playbook.yaml` 규칙 12개는 초안이에요. 문구와 임계값을 팀에서 검토해 주세요.

---

## 12. Docker 로 띄우기 (선택)

센터 PC는 Docker 없이 실행하고, 데이터 창고는 센터 PC 에 설치된 PostgreSQL 을 써요. Docker 는 개발 PC나 데모 서버에서 한 번에 띄울 때 써요.
파일은 저장소 맨 위에 있어요: `Dockerfile`, `docker-compose.yml`, `.dockerignore`.

```bash
# 저장소 맨 위 폴더에서
docker compose up -d --build        # http://localhost:3000 (처음에는 이미지를 만들고 샘플 데이터를 넣어요, 3~4분)
docker compose up -d db             # 데이터 창고(PostgreSQL)만 띄우기
docker compose logs -f              # 로그
docker compose down                 # 내리기 (데이터, 제안서, 실행 기록은 볼륨에 남아요)
docker compose down -v              # 볼륨까지 지우기 (넣어 둔 데이터도 지워져요)
```

| 항목 | 내용 |
|---|---|
| 앱 | 이미지 `jeju-meomulmeong:0.1.0`(약 510MB), 컨테이너 `jeju-meomulmeong-app`. 백엔드 + 빌드한 React 화면. Node 는 빌드 단계에서만 써요 |
| 데이터 창고 | 이미지 `postgres:17-alpine`, 컨테이너 `jeju-meomulmeong-db`. `127.0.0.1:5434` 로만 열어요. 데이터는 `jeju-meomulmeong_pgdata` 볼륨에 남아요 |
| 처음 뜰 때 | 앱이 샘플 데이터 스키마가 없으면 합성 데이터를 만들어 PostgreSQL 에 넣어요 (`serve --prepare`, 약 25초). 다음부터는 바로 떠요 |
| 창고 암호 | 이 PC 안에서만 여는 개발 · 시연용 기본값이에요. 바꾸려면 처음 띄우기 전에 `MEOMUL_PG_PASSWORD` 를 셸 환경변수와 `backend/.env` 에 같은 값으로 넣어요 |
| 주소 | `127.0.0.1:3000` 으로만 열어요. 로그인 기능이 없어서 밖으로는 열지 않아요 |
| 실행 사용자 | 루트가 아닌 `meomul` (uid 10001) |
| 환경변수 | `backend/.env` 가 있으면 실행할 때 읽어 넘겨요. API 키는 이미지에 들어가지 않아요 |
| 결과물 | 제안서 · 실행 기록은 `jeju-meomulmeong_outputs` 볼륨(`/app/backend/outputs`)에 남아요 |
| 상태 확인 | 30초마다 `/api/health` 를 불러요 (`docker ps` 의 healthy) |

**클라우드 LLM(Claude)을 쓸 때** — `backend/.env` 에 `ANTHROPIC_API_KEY` 를 넣고 다시 띄우면 화면의 LLM 모드에서 클라우드를 고를 수 있어요.
키는 실행할 때만 컨테이너에 넘기고 이미지에는 들어가지 않아요. 컨테이너가 인터넷에 닿아야 해요.

**허브 실데이터로 띄울 때** — 6.3절대로 받아 `build-data --mode hub` 를 실행하면 같은 PostgreSQL 의 `hub` 스키마에 들어가요.
컨테이너를 다시 만들 필요 없이 화면의 데이터 모드에서 "실데이터"를 고르면 돼요.

```bash
cd backend && .venv/bin/python -m meomulmeong build-data --mode hub
```

이 PC 에 Python 을 따로 설치하지 않았으면 컨테이너로 실행해도 돼요. 허브 자료는 이미지에 없으니 실행할 때만 폴더를 붙여요.
수집본이면 `data/hub`, 다른 PC 에서 내보낸 표(6.1절)이면 `data/export/hub` 를 붙여요.

```bash
docker compose run --rm -v ./backend/data/export/hub:/app/backend/data/export/hub:ro app build-data --mode hub
```

**이미지에 넣지 않는 것** — `.dockerignore` 가 모두 빼고 필요한 것만 담아요. `.env`, 센터 · 허브 원자료, CSV 내보내기, 실행 결과, xlsx · pdf 는 들어가지 않아요.
`tests/test_deploy_files.py` 가 이 규칙과 포트 범위를 확인해요.

---

## 13. 외부 서비스·오픈소스·AI 활용

- 외부 서비스 의존성: 템플릿 모드는 없음. 선택 기능으로 Anthropic API(클라우드 LLM), 제주데이터허브 Open API(데이터 갱신 때만).
- 오픈소스: PostgreSQL(PostgreSQL License), psycopg(LGPL-3.0), pandas(BSD-3), NumPy(BSD-3), PyArrow(Apache-2.0), pydantic·pydantic-settings(MIT), PyYAML(MIT),
  Jinja2(BSD-3), httpx(BSD-3), FastAPI(MIT), Uvicorn(BSD-3), Starlette(BSD-3), Anthropic Python SDK(MIT), pytest(MIT), ruff(MIT).
  버전은 `requirements.lock` 에 고정했어요.
- AI 활용: 이 백엔드 코드와 문서의 초안은 Claude Code(Anthropic Claude)로 작성했어요. 대회 규칙에 따라 최종 제출물에 사용 모델과 범위를 밝혀야 해요.
- 데이터 출처: 제주특별자치도, 제주데이터허브. 대회 제공 데이터 목록·명세서 xlsx 와 센터 추출본은 저장소에 올리지 않아요.
