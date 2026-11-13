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

Python 3.11 이 필요해요. 아래는 `backend/` 폴더에서 실행해요.

```bash
# 1) 설치 (uv 사용)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt -e .

# uv 가 없으면
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock pytest ruff
.venv/bin/python -m pip install -e . --no-deps

# 2) 샘플(합성) 데이터와 데이터 창고 만들기 (약 3초)
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

로컬 LLM 으로 실행하려면 Ollama 를 띄우고 모델을 받은 뒤 `--llm ollama` 를 붙여요.

```bash
ollama pull qwen3:4b
.venv/bin/python -m meomulmeong ask "성산읍 청년 인구 진단" --llm ollama
```

환경변수는 `.env.example` 을 `.env` 로 복사해 채워요. `.env` 는 저장소에 올리지 않아요.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `MEOMUL_DATA_MODE` | `synthetic` | `synthetic`(샘플) · `hub`(허브 수집본) · `center`(센터 추출본) |
| `MEOMUL_LLM_MODE` | `template` | `template`(LLM 없음) · `ollama`(로컬) · `anthropic`(클라우드, 선택) |
| `MEOMUL_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 서버 주소 |
| `MEOMUL_OLLAMA_MODEL` | `qwen3:4b` | 로컬 모델. 없으면 설치된 같은 계열 모델로 바꾸고 안내해요 |
| `MEOMUL_OLLAMA_EXPLAIN_MODEL` | (없음) | 해설만 다른 모델로 쓸 때 (예: `exaone3.5:7.8b`) |
| `MEOMUL_ANTHROPIC_MODEL` | `claude-opus-5-5` | 클라우드 모델 |
| `ANTHROPIC_API_KEY` | (없음) | 클라우드 모드에서만 필요 |
| `MEOMUL_HUB_PROJECT_KEY` | (없음) | 제주데이터허브 프로젝트 키 (수집할 때만) |
| `MEOMUL_HOME` / `MEOMUL_OUTPUTS` | 이 폴더 / `outputs/` | 설정·데이터 위치, 결과 저장 위치 |
| `MEOMUL_API_HOST` / `MEOMUL_API_PORT` | `127.0.0.1` / `8501` | 웹 API 서버 주소. 기본은 이 PC 안에서만 열려요 |
| `MEOMUL_CORS_ORIGINS` | 5173·3000 포트의 localhost | 개발할 때 React 개발 서버에서 API를 부를 수 있게 허용할 주소 (쉼표로 구분) |
| `MEOMUL_WEB_DIST` | `../frontend/dist` | 빌드한 React 화면 폴더. 있으면 같은 주소에서 화면도 함께 내줘요 |

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
│  └─ warehouse/           DuckDB 데이터 창고 (모드마다 파일 하나)
├─ meomulmeong/
│  ├─ settings.py  schemas.py  fmt.py  service.py  cli.py  progress.py(진행 알림)
│  ├─ api/         app(웹 API 서버, FastAPI). React 화면이 부르는 곳
│  ├─ data/        refs(장소 표준화) · catalog · warehouse(적재·읽기 전용 조회) · periods · synthetic · hub_client
│  ├─ tools/       common · stage1 · stage2 · stage3 · shared · output
│  ├─ agent/       parser(해석기) · stages(계획·실행) · verifier(검증기) · explainer(해설기) · orchestrator · memory · prompts/
│  ├─ llm/         base · ollama_provider · anthropic_provider · factory
│  └─ report/      builder · svg · templates/proposal.html.j2
├─ eval/           golden.yaml(60문항) · make_golden · expected(pandas 기대값 계산) · __main__
├─ tests/          pytest 241개
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

합성 데이터는 허브 API 응답과 같은 컬럼으로 만들어져 실데이터와 같은 적재 경로를 지나요. 읍면동마다 숨은 유형을 심어 두어서
세 단계가 끝까지 이어지는지 시험할 수 있어요. 실제 통계가 아니므로 화면과 제안서에 "샘플 데이터" 배지가 붙어요.

### 6.2 표준 테이블 (카탈로그)

| 테이블 | 허브 데이터 (ID) | 단위 | 단계 |
|---|---|---|---|
| `pop_kor_emd_daily` | 읍면동 단위 내국인 유동인구 (583) | 읍면동 × 일 × 성별 × 연령대 | 1 |
| `pop_for_long_emd_daily` | 읍면동 단위 외국인 장기체류 유동인구 (590) | 읍면동 × 일 × 국가 | 1 |
| `card_zone_dow_monthly` | 관광지 및 상업지구 요일별 카드 (608) | 5개 지구 × 월 × 요일 | 1·2 |
| `card_cn_area_monthly` | 중국인 관광객 지역, 업종별 카드 이용 (600) | 시군구 × 도심/읍면 × 테마 × 월 | 2 |
| `spend_tour_type_monthly` | 단체/개별 관광객 소비 (603) | 업종 × 내국인/중국인 × 단체/개별 × 월 | 2·3 |
| `foreign_visitors_monthly` | 국가별 입도객 현황 (582) 또는 파일 `외국인관광객현황_20251231` | 국적 12종 × 월 | 2·3 |
| `arrivals_purpose_monthly` | 방문목적별 입도객 현황 (580) | 방문목적 9종 × 월 | 3 |
| `bus_route_daily` | 일일 노선별 버스 이용자 정보 (614) | 노선 × 일 | 3 |

적재할 때 읍면동 이름을 행정동 코드로 통일하고(법정동·별칭 포함), 연령대는 10세 단위, 업종은 6개 테마로 맞춰요.
연결하지 못한 이름과 날짜 변환 실패는 `status` 의 `issues` 에 보고해요. 월 집계 테이블(`m_*`)과 수록 기간표(`meta_table`)도 함께 만들어요.

### 6.3 허브 수집

```bash
# .env 에 MEOMUL_HUB_PROJECT_KEY 를 넣은 뒤 (허브에서 데이터마다 '프로젝트 담기' 필요)
.venv/bin/python -m meomulmeong fetch-hub --start 20241101 --end 20261031
.venv/bin/python -m meomulmeong build-data --mode hub
```

받은 쪽은 `data/hub/_raw/` 에 남겨 두고, 다음 실행 때 없는 쪽부터 이어 받아요. API별 호출 상한(`--max-calls`, 기본 900)에 닿으면 멈추고 안내해요.
파일 데이터 `외국인관광객현황_20251231` 은 CSV 로 내려받아 `data/hub/foreign_visitors/` 에 넣으면 돼요 (세로형·가로형 모두 읽어요).

### 6.4 새 데이터 붙이기

`config/catalog/` 에 YAML 한 장을 추가하고 `build-data` 를 다시 실행해요. `select` 에 표준 컬럼별 변환식(DuckDB SQL)을 적어요.
센터 추출본은 `sources.center.file_glob` 로 파일 이름을 지정해요. 자세한 형식은 [config/catalog/README.md](config/catalog/README.md)에 있어요.

---

## 7. LLM 모드

| 모드 | 모델 | 쓰는 곳 | 비고 |
|---|---|---|---|
| `template` | 없음 | 규칙 파서 + SQL·문장 템플릿 | 외부 전송 0건, 완전 재현 |
| `ollama` | `qwen3:4b` (기본) | 불확실한 질문 해석, 쉬운 해설, 자유 질문 SQL | JSON 스키마 강제 출력. GPU 메모리 3.5GB 미만이면 `exaone3.5:2.4b` 로 자동 전환 |
| `anthropic` | `claude-opus-5-5` (기본) | 위와 같음 | 공식 SDK, 구조화 출력, 서버 측 거절 대체(`fallbacks="default"`). 전송 동의 뒤에만 사용 |

- `config/settings.yaml` 의 `llm.explain: false` 로 두면 해설은 항상 규칙 문장이고 LLM은 해석과 자유 질문에만 써요.
- `llm.template_only_intents` 에 적은 답 종류는 LLM 모드에서도 규칙 문장을 써요. 기본값은 추천 순위(`recommend`), 코스(`courses`), Stage 3 전체 계획(`plan`: 시나리오·노선·코스를 함께 보여 주는 답, 연계 실행의 Stage 3 포함)이에요.
  큰 모델을 쓸 때는 `plan` 을 빼고 10절의 측정을 다시 해 보세요.
- `llm.explain_budget_seconds`(기본 45초)를 넘기면 더 다시 쓰지 않고 템플릿 해설로 대체해요. 느린 PC에서 답 하나가 몇 분씩 걸리지 않게 하는 장치예요.
- 자유 질문(준비된 분석에 맞지 않는 조회)은 LLM이 SQL을 쓰고, "자유 질문 · SQL 검토 필요" 배지를 붙여요. 소형 모델에서는 정확도가 낮으니 실험 기능으로 봐 주세요.
- LLM을 쓸 수 없으면(서버 없음, 모델 없음, 인증 실패) 템플릿 모드로 내려가고 `status().llm_note` 에 이유를 적어요.

---

## 8. 웹 API (React 화면에서 쓰는 법)

```bash
.venv/bin/python -m meomulmeong serve                  # http://127.0.0.1:8501
.venv/bin/python -m meomulmeong serve --llm ollama --open   # 로컬 LLM 모드로 띄우고 브라우저 열기
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
| 503 | `warehouse_missing` | 데이터 창고가 없어요. `build-data` 를 먼저 실행해야 해요 (`/api/health` 의 `ready` 로 미리 알 수 있어요) |
| 409 | `warehouse_missing` | 바꾸려는 데이터 모드의 창고가 없어요 |
| 404 | `unknown_place` · `report_not_found` | 모르는 읍면동, 없는 제안서 |
| 400 | `nothing_to_report` | 제안서에 넣을 분석 결과가 아직 없어요 |

### 8.2 답(Answer)에 들어 있는 것

| 필드 | 화면에서 쓰는 곳 |
|---|---|
| `headline` · `explanation` | 한 줄 결론, 쉬운 해설 |
| `badges` | 샘플 데이터 / 유형 C / 가정 같은 배지 (`tone`: type · assumption · data · warn · info) |
| `charts` | 차트 사양: `kind`(line · bar · hbar), `x`, `series[{name, y}]`, `y_format`(num · pct · index · won) |
| `maps` | 지도 사양: `points[{name, lat, lon, category, role}]`, `lines`(코스), `legend` |
| `evidence` | 근거표: `columns`, `rows`, `formats`, `sql`(접어서 보여 줘요), `period` |
| `suggestions` | 규칙이 만든 제안: `rule_id`, `text`, `evidence_text` |
| `limits` · `notices` | 한계, 안내(자동 선택·템플릿 대체 등) |
| `next_questions` | 다음 질문 3개 (`kind`: next_stage · follow_up · report) |
| `verification.checks` | 검증 항목별 통과 여부 |
| `explained_by` · `llm_mode` · `llm_payload` | 해설을 누가 썼는지, LLM 모드, 전송 미리보기 |
| `steps` | 실행 기록 (도구, 걸린 시간, LLM 시도) |

### 8.3 진행 상황 받기 (SSE)

로컬 LLM 모드에서는 답 하나에 20초 안팎, 연계 실행은 1분 안팎이 걸려요. 스트리밍 경로를 쓰면 그동안 무엇을 하는지 보여 줄 수 있어요.

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
.venv/bin/python -m pytest -q              # 241개 (로컬 LLM 왕복 1개는 기본 제외), 약 15초. 임시 폴더에 합성 데이터를 새로 만들어 써요
.venv/bin/python -m pytest -m llm          # 로컬 Ollama 왕복 시험 (서버가 있을 때)
.venv/bin/python -m eval                   # 골든셋 60문항 (템플릿 모드)
.venv/bin/python -m eval --llm ollama      # 로컬 LLM 모드
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

응답 시간은 문항당 평균 0.05초 안팎, 연계 3단계는 0.1초 안팎이었어요. 로컬 LLM 모드의 측정값은 10절에 적었어요.

---

## 10. 로컬 LLM 측정 (개발 PC 기준)

개발 PC(RTX 2050 4GB, WSL2, Ollama 0.6.7)에서 `qwen3:4b` 로 잰 값이에요. 센터 PC(GTX 1060 6GB)에서 다시 재야 해요.
골든셋에서 구분마다 3문항씩 15문항을 돌렸어요 (`python -m eval --llm ollama --limit 3`, 2026-11-13, 샘플 데이터).

| 항목 | 값 |
|---|---:|
| 정답 | 15 / 15 |
| LLM에 해설을 맡긴 답 | 15건 |
| 검증을 통과해 채택 | 14건 (93%) |
| 첫 시도에 통과 | 13건 (87%) |
| 템플릿 해설로 대체 | 1건 |
| LLM 호출 | 16회, 중앙값 22.4초, 최대 32.3초 |
| 단일 질문 응답 (9문항) | 중앙값 22.8초, 최대 45.7초 |
| 연계 실행 Stage 1→2→3 (3문항) | 37~63초 |

구분별 정확도는 Stage 1·2·3, 연계, 인과 함정 모두 3문항 중 3문항이에요. 보고서는 `outputs/eval/eval_ollama_*.md` 에, 답마다의 해설과 시도 기록은 `outputs/runs/*.jsonl` 에 남아요.
프롬프트와 검증기를 조정하기 전 첫 측정에서는 해설 18건 중 16건 채택, 첫 시도 통과 12건, 연계 실행 65~262초였어요.

**읽는 법**

- 정답은 질문 해석(단계·의도·장소·기간), 유형·수치·규칙, 검증 통과 여부를 기대값과 견줘 채점해요. 수치는 SQL과 규칙이 만들어서 LLM 모드에서도 템플릿 모드와 같아요.
  해설 문장이 얼마나 읽기 좋은지는 채점하지 않아요. 그 부분은 아래 "해설 품질에서 본 것"에 따로 적었어요.
- 인과 함정 3문항과 Stage 3 전체 계획은 LLM을 부르지 않아요. 그래서 연계 실행은 Stage 1·2에서만 LLM을 불러요.
- 이 PC에서는 모델이 GPU 메모리에 다 올라가지 않아(`ollama ps` 기준 CPU 10% / GPU 90%) 호출 시간이 고르지 않았어요.
  측정하는 동안 같은 PC에서 다른 프로젝트의 개발 서버와 테스트가 돌고 있어서, 위 시간은 조금 길게 나왔을 수 있어요.
  CPU를 많이 쓰는 작업이 겹친 앞선 측정에서는 호출 한 번이 2분까지 늘어났어요.

**해설 품질에서 본 것**

- 채택된 해설 14건 가운데 Stage 1은 6건 중 5건이 초안의 앞 문장을 그대로 옮긴 것이었어요. Stage 2·3은 문장을 줄이거나 순서를 바꾼 정도였어요.
  더 짧아진 답은 있었지만, 템플릿 해설보다 뚜렷이 쉬워진 답은 없었어요.
- 다시 쓰게 한 1건: "주말 소비는 평일의 0.89배예요"에 누구의 소비인지가 빠져 숫자-지표 짝 검사에서 떨어졌고, 두 번째에 통과했어요.
- 템플릿으로 대체한 1건: 한 줄 결론을 그대로 되풀이한 답이었어요.
- 채택된 14건에 숫자나 대상이 틀린 문장은 없었어요. "늘어난 국적입니다"처럼 말투가 섞이거나 조사가 어색한 문장은 있었어요.
- 조정하는 동안의 앞선 측정에서는 검증을 통과한 문장 가운데 뜻이 바뀐 것이 있었어요. 예: "성산읍은 Stage 1에서 중국인 카드 소비가 늘어난 읍면동이에요."
  초안을 손봐서 최종 측정에서는 나오지 않았지만, 숫자가 없는 문장의 뜻 바뀜은 검증기가 잡지 못해요.
- 측정 뒤 화면에서 돌려 보다가 검증을 통과한 틀린 문장을 하나 더 봤어요: "주말에 비해 평일 소비가 0.89배예요" (방향이 뒤바뀜),
  "중국인 개별관광객이 가장 많아요" (근거에 없는 말). 앞의 것은 배율 방향 검사를 더해 막았고, 뒤의 것 같은 문장은 여전히 통과할 수 있어요.
- 그래서 4B 모델에서는 LLM 해설이 답마다 20초 안팎을 더 쓰고도 템플릿 해설보다 나아지지 않았어요. 기본값을 어떻게 둘지는 11절의 "팀에서 정할 것"에 적었어요.

**측정하면서 프롬프트와 검증기에 반영한 것**

- 프롬프트를 지시문으로 끝내면 모델이 시스템 지시문을 답으로 되받아 적었어요. 그래서 프롬프트는 근거 목록으로 끝내요.
  다시 쓰게 할 때의 고칠 점도 같은 이유로 맨 앞에 붙여요.
- "처음부터 끝까지"처럼 질문 꼴이 아닌 요청을 그대로 넘겨도 같은 일이 생겼어요. 연계 실행은 단계마다 물을 질문을 따로 만들어 넘겨요.
- 코스 목록이 들어가는 Stage 3 전체 계획은 "다른 코스는 환승이 필요해요"처럼 틀리게 옮기는 일이 잦았어요. 그래서 규칙 문장을 그대로 써요 (`llm.template_only_intents`).
- Stage 2 초안에 앞 단계를 잇는 문장을 넣으면 한 줄 결론과 섞어 "성산읍은 Stage 1에서 중국인 개별관광객을 먼저 볼 만해요" 같은 문장을 만들었어요. LLM에 주는 초안에서는 그 문장을 빼요.
- 한 줄 결론만 되풀이한 해설은 다시 쓰게 해도 나아지지 않고 1분 가까이 걸렸어요. 그래서 바로 템플릿 해설로 대체해요.
- 검증기에 더한 것: 나눠 쓰거나 붙여 쓴 큰 수 읽기("10만 493명", "24만명"), 초안에 없는 최상급 표현, 지역 단위 값을 읍면동 값처럼 쓴 문장, 가정을 밝히지 않은 "예상되는 수치" 같은 예측 표현.
- 검증기에서 푼 것: 지표 낱말이 없는 문장은 앞 문장의 주어를 이어받은 것으로 봐요. 맞는 문장을 떨어뜨려 다시 쓰게 하던 경우예요.

**다른 모델**

- `exaone3.5` 7.8B 는 이 PC의 GPU 메모리(4GB)에 올라가지 않아 너무 느렸고, 비교 측정을 끝내지 못했어요. 센터 PC(6GB)에서 다시 재 볼 만해요.
- Claude(클라우드) 모드는 가짜 서버로 요청 형식만 시험했어요. 실제 호출은 비용이 들어 하지 않았어요.

---

## 11. 확인이 필요한 것과 남은 일

**실데이터로 확인해야 하는 가정**

- [ ] 허브 유동인구 값의 단위: 하루 24개 시각 값의 합으로 보고 `sources.pop_scale = 1/24` 로 환산했어요. 다르면 `settings.yaml` 을 고치고 다시 적재해요.
- [ ] 허브 API의 쪽 매개변수(`number`, `limit`)와 응답 형식(`totCnt`, `hasMore`, `data`): 프로젝트 키가 없어 실제 호출로 확인하지 못했어요. 가짜 서버 테스트만 통과한 상태예요.
- [ ] 일 단위 데이터의 쿼터: 유동인구는 하루 약 690행이라 24개월이면 5천 쪽이 넘어요. `limit` 상향 가능 여부나 쿼터 증량을 허브에 확인해야 해요.
- [ ] 허브 카드 데이터의 수록 기간(2016-09~2018-12)이 유동인구·입도객과 겹치지 않아요. 실데이터 모드에서는 Stage 2 규칙이 "기간이 겹치지 않아 함께 볼 수 없음"으로 빠질 수 있어요.
- [ ] `외국인관광객현황_20251231` 파일의 실제 컬럼 구성.

**참조표**

- [ ] `ref_route.csv`, `ref_route_emd.csv` 는 샘플이에요. 허브 `버스 노선 기본 정보`(611)·`버스 정류소 기본 정보`(612)와 경유 정류소 자료로 다시 만들어야 해요.
- [ ] 카드 5개 지구와 읍면동의 연결(`ref_card_zone.csv`), 7권역 배정, 읍면동 좌표는 잠정값이에요.
- [ ] 행정동 경계 GeoJSON 이 없어요. 지금은 대략 좌표로 점 지도를 그려요. 구하면 API 로 내주는 경로를 더해야 해요.

**팀에서 정할 것**

- [ ] LLM 해설의 기본값: `qwen3:4b` 의 해설은 초안을 거의 그대로 옮기는 경우가 많고 답마다 20초 안팎이 더 걸려요 (10절).
      데모에서 `llm.explain: true`(기획서대로 LLM 해설 + 검증)로 둘지, `false`(규칙 문장 해설, LLM은 질문 해석과 자유 질문만)로 둘지 정해 주세요.

**구현**

- [x] React 화면(`frontend/`). 실행과 구성은 [../frontend/README.md](../frontend/README.md)에 있어요.
- [ ] Docker 에서 실데이터(허브 · 센터)를 쓰려면 `data/` 폴더와 데이터 창고를 볼륨으로 연결해야 해요. 지금 이미지는 샘플 데이터만 담고 있어요 (12절).
- [ ] `install.bat` / `run.bat`, 오프라인 설치 꾸러미(wheelhouse + 빌드한 화면). `run.bat` 은 Ollama 확인 뒤 `python -m meomulmeong serve --open` 을 부르면 돼요.
- [ ] 기획서 5.2·5.4절에는 화면 기술이 Streamlit 으로 적혀 있어요. React 웹으로 가므로 제출 전에 기획서 문구도 맞춰야 해요.
- [ ] 센터 모드: `4-11 유동인구 v02`, `3-02 버스 노선별 이용` 변환식은 명세서만 보고 썼어요. 실제 추출본으로 검증해야 해요. `1-08 카드 v02`(읍면동 × 업종 42개)는 아직 연결하지 않았어요.
- [ ] 반출 신청 패키지, PDF 제안서 (기획서의 탑재 후 확장 항목).
- [ ] `playbook.yaml` 규칙 12개는 초안이에요. 문구와 임계값을 팀에서 검토해 주세요.

---

## 12. Docker 로 띄우기 (선택)

센터 PC는 기획서대로 Docker 없이 실행해요. Docker 는 개발 PC나 데모 서버에서 한 번에 띄울 때 써요.
파일은 저장소 맨 위에 있어요: `Dockerfile`, `docker-compose.yml`, `docker-compose.local-llm.yml`, `.dockerignore`.

```bash
# 저장소 맨 위 폴더에서
docker compose up -d --build        # http://localhost:3000 (처음에는 이미지를 만들어요, 2~3분)
docker compose logs -f              # 로그
docker compose down                 # 내리기 (제안서와 실행 기록은 볼륨에 남아요)
docker compose down -v              # 볼륨까지 지우기
```

| 항목 | 내용 |
|---|---|
| 이미지 | `meomulmeong:local`, 약 630MB. 백엔드 + 빌드한 React 화면 + 샘플 데이터 창고. Node 는 빌드 단계에서만 써요 |
| 주소 | `127.0.0.1:3000` 으로만 열어요. 로그인 기능이 없어서 밖으로는 열지 않아요 |
| 실행 사용자 | 루트가 아닌 `meomul` (uid 10001) |
| 환경변수 | `backend/.env` 가 있으면 실행할 때 읽어 넘겨요. API 키는 이미지에 들어가지 않아요 |
| 결과물 | 제안서 · 실행 기록은 `meomulmeong_outputs` 볼륨(`/app/backend/outputs`)에 남아요 |
| 상태 확인 | 30초마다 `/api/health` 를 불러요 (`docker ps` 의 healthy) |

**이 PC의 Ollama(로컬 LLM)를 쓸 때** — Ollama 는 보통 `127.0.0.1` 에서만 들어서 일반 컨테이너에서는 닿지 않아요.
리눅스(WSL2 포함)에서는 겹침 파일로 호스트 네트워크를 같이 쓰게 하면 돼요. 이때도 서버는 `127.0.0.1:3000` 에서만 들어요.

```bash
docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up -d --build
```

Docker Desktop(Windows · macOS)에서는 겹침 파일을 쓰지 말고, Ollama 가 컨테이너에서 닿는 주소로 듣게 한 뒤 기본 파일만 쓰세요.
로컬 LLM에 닿지 못하면 화면이 이유를 알려 주고 템플릿 모드로 답해요.

**이미지에 넣지 않는 것** — `.dockerignore` 가 모두 빼고 필요한 것만 담아요. `.env`, 센터 · 허브 원자료, 데이터 창고, 실행 결과, xlsx · pdf 는 들어가지 않아요.
`tests/test_deploy_files.py` 가 이 규칙과 포트 범위를 확인해요.

---

## 13. 외부 서비스·오픈소스·AI 활용

- 외부 서비스 의존성: 로컬·템플릿 모드는 없음. 선택 기능으로 Anthropic API(클라우드 LLM), 제주데이터허브 Open API(데이터 갱신 때만).
- 오픈소스: DuckDB(MIT), pandas(BSD-3), NumPy(BSD-3), PyArrow(Apache-2.0), pydantic·pydantic-settings(MIT), PyYAML(MIT),
  Jinja2(BSD-3), httpx(BSD-3), FastAPI(MIT), Uvicorn(BSD-3), Starlette(BSD-3), Anthropic Python SDK(MIT), pytest(MIT), ruff(MIT),
  Ollama(MIT), Qwen3(Apache-2.0).
  EXAONE 3.5 는 비상업 조건이 붙은 별도 라이선스라 사용 전에 조건을 확인해야 해요. 버전은 `requirements.lock` 에 고정했어요.
- AI 활용: 이 백엔드 코드와 문서의 초안은 Claude Code(Anthropic Claude)로 작성했어요. 대회 규칙에 따라 최종 제출물에 사용 모델과 범위를 밝혀야 해요.
- 데이터 출처: 제주특별자치도, 제주데이터허브. 대회 제공 데이터 목록·명세서 xlsx 와 센터 추출본은 저장소에 올리지 않아요.
