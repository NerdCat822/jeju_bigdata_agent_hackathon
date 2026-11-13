# 머물멍 화면 (React)

**머물멍 (Jeju Town Vitality Agent)** 의 웹 화면이에요. 백엔드가 여는 웹 API([../backend/README.md](../backend/README.md) 8절)를 불러서
질문 → 확인 카드 → 한 줄 결론 → 차트·지도 → 근거표 → 한계 → 다음 단계 순서로 보여 줘요.

화면 구성은 기획서 5.3절의 예시 화면을 따랐고, 마스코트 그림은 기획서에 실린 것을 썼어요.

---

## 1. 실행

Node 20.19 이상이 필요해요. 백엔드를 먼저 준비해요 ([../backend/README.md](../backend/README.md) 1절).

### 개발할 때

```bash
# 터미널 1: 백엔드 (http://127.0.0.1:8501)
cd backend && .venv/bin/python -m meomulmeong serve

# 터미널 2: 화면 개발 서버 (http://localhost:5173)
cd frontend && npm install && npm run dev
```

개발 서버는 `/api` 요청을 백엔드(8501)로 넘겨요. 백엔드 주소가 다르면 `MEOMUL_API=http://127.0.0.1:9000 npm run dev` 처럼 바꿔요.

### 한 주소로 띄울 때 (센터 PC)

```bash
cd frontend && npm install && npm run build      # dist/ 에 빌드 결과물이 생겨요
cd ../backend && .venv/bin/python -m meomulmeong serve --open
```

백엔드는 `frontend/dist` 가 있으면 같은 주소(http://127.0.0.1:8501)에서 화면도 함께 내줘요. 그래서 센터 PC에는 Node 가 없어도 돼요.
빌드는 인터넷이 되는 PC에서 하고, `dist/` 폴더만 옮기면 돼요.

| 명령 | 하는 일 |
|---|---|
| `npm run dev` | 개발 서버 |
| `npm run build` | 타입 검사 뒤 `dist/` 에 빌드 |
| `npm test` | 테스트 69개 (Vitest + Testing Library) |
| `npm run lint` | 린트 (oxlint) |
| `npm run typecheck` | 타입 검사만 |
| `npm run gen:api` | 백엔드 OpenAPI 명세에서 `src/api/schema.d.ts` 다시 만들기 |

---

## 2. 화면 구성

| 영역 | 내용 |
|---|---|
| 왼쪽 메뉴 | 데이터 모드(샘플 · 실데이터 · 센터), LLM 모드, 지금 보는 읍면동과 유형 표식, 단계 1 · 2 · 3, 최종 제안서, 지난 질문, "처음부터 끝까지" |
| 위쪽 | 지금 쓰는 데이터 배지와 LLM 모드 (항상 보여요), 질문 입력창, 이어서 물어볼 질문 칩 |
| 첫 화면 | 단계별 추천 질문, 읍면동 지도(43곳)에서 고르기 |
| 확인 카드 | "이렇게 이해했어요" 칩. "고치기"로 장소 · 연령 · 기간 · 테마 · 가정값을 바꾸고 "다시 실행" |
| 진행 상황 | 답을 만드는 동안 도구 실행과 LLM 해설 시도를 한 줄씩 보여 줘요 |
| 답 | 한 줄 결론 → 쉬운 해설 → 제안 후보 → 차트 · 지도 → 근거표 · SQL(접힘) → 한계(접힘) → 검증 결과 · 실행 기록(접힘) → 다음 질문 |
| 연계 실행 | Stage 1 · 2 · 3 의 답을 차례로 쌓고, 끝에 최종 제안서 열기 · 내려받기 |

동작 규칙

- **직접 쓴 질문**은 확인 카드를 먼저 보여 주고 "실행"을 눌러야 계산해요. 추천 질문 칩, 다음 질문 단추, 단계 단추, 지도에서 고른 곳은 바로 실행해요.
- **장소를 고칠 때**는 이름만 바꿔 보내요. 코드는 서버가 참조표에서 다시 찾아요.
- **분석은 한 번에 하나**예요. 실행 중에는 새 질문과 단추를 잠가요.
- **세션**은 서버가 준 번호를 이어 써요. "거기 30대만?" 같은 후속 질문이 이어져요. 데이터 모드를 바꾸면 새로 시작해요.
- **클라우드 LLM**은 보낼 내용(집계 지표)을 "전송 미리보기"로 보여 주고, 동의 단추를 누른 뒤에만 보내요.

---

## 3. 폴더 구조

```
frontend/
├─ index.html  vite.config.ts  package.json
├─ public/favicon.png
└─ src/
   ├─ main.tsx  App.tsx  styles.css
   ├─ api/         client(호출 · SSE) · types · schema.d.ts(자동 생성) · openapi.json(명세 사본)
   ├─ state/       agent(화면 상태와 동작: 질문 하나 = Turn 하나)
   ├─ components/  Sidebar · AskBar · ConfirmCard · ProgressList · TurnView · AnswerView · EvidencePanel · VerificationPanel · Home · DataInfo · Toast · Icon · TypeMark
   │  └─ viz/      ChartCard · LineChart · BarChart · BarList · JejuMap · MapCard · Tooltip · palette
   ├─ lib/         format(숫자 표기) · scale(축 눈금) · sse(스트림 풀기) · geo(지도 좌표 · 윤곽 · 점 벌리기) · useSize
   ├─ assets/      마스코트 그림 4장
   └─ test/        setup · fixtures(실제 API 응답에서 뽑은 예시)
```

실행 의존성은 React, React DOM, Pretendard(글꼴), lucide-react(아이콘)예요. 차트와 지도는 SVG 로 직접 그려요.

---

## 4. 오프라인 규칙 (센터 PC)

센터 PC는 인터넷이 안 돼요. 그래서 아래를 지켜요.

- 글꼴, 아이콘, 스크립트를 **CDN 에서 불러오지 않아요.** 글꼴(Pretendard 가변 글꼴, 약 2MB)과 아이콘(lucide)은 빌드 결과물에 함께 담겨요.
- **지도 타일 서버를 쓰지 않아요.** 본섬의 대략 윤곽 위에 읍면동을 점으로 찍어요. 행정동 경계 GeoJSON 을 구하면 `JejuMap` 에 붙일 수 있어요.
- 새 라이브러리를 더할 때는 빌드 결과물에 다 담기는지 확인해요. 실제 브라우저로 띄워 봤을 때 바깥 주소로 나가는 요청은 0건이었어요.

---

## 5. 화면 디자인과 차트 · 지도 기준

### 디자인 방향

| 항목 | 정한 것 |
|---|---|
| 성격 | 차분하고, 근거를 따지고, 조금 다정한 |
| 바탕 | 제주 마을 지도와 행정 보고서. 흰 종이 바탕에 먹색 글자, 귤색은 한 점만 |
| 색 | 바탕 · 면 · 선 · 글자는 중립 회색 한 줄기(`--page` `--surface` `--raised` `--text` `--text-2` `--text-3` `--line`)예요. 귤색(`--accent`)은 앞으로 가는 단추, 고른 것, 차트의 주인공에만 써요 |
| 글자 | Pretendard. 굵기는 400 과 500 만 쓰고(상표와 유형 표식만 600), 위계는 크기와 색으로 나눠요 |
| 간격 | 4px 격자. 모서리는 꼬리표 6 · 단추 8 · 카드 12 · 큰 판 16 |
| 아이콘 | lucide 한 벌, 16px, 선 굵기 1.5. 글자와 같은 색이에요 |
| 유형 표식 | 유형 A~D 를 나타내는 작은 동그라미(`TypeMark`). 지도, 한 줄 결론, 근거표, 왼쪽 메뉴에서 똑같이 써요 |
| 움직임 | 답이 나올 때 한 번 떠오르는 것과 진행 표시만 있어요. 움직임 줄이기 설정을 따라요 |

색이나 간격을 더할 때는 `styles.css` 맨 위의 변수에서 골라요. 새 색을 직접 적지 않아요.

### 차트와 지도

| 기준 | 적용 |
|---|---|
| 주인공만 강조색 | 차트마다 귤색은 하나예요. 선 차트는 첫 계열, 막대 목록은 백엔드가 `ChartSpec.highlight` 로 알려 준 항목만 귤색이고 나머지는 회색이에요 |
| 색 없이도 읽히게 | 회색 계열은 밝기가 서로 달라요. 유형 색(A~D)은 구분 검사를 통과한 값이고, 지도와 표는 색과 함께 유형 글자를 써요 |
| 차트 종류 | 추이는 선, 항목 비교(계열 하나)는 막대 목록, 계열이 둘 이상인 비교는 세로 막대예요 |
| 축은 하나 | 단위가 다른 값은 한 그림에 겹치지 않아요. 선 차트는 지수(첫 달 = 100)로 맞춘 값을 받아 그려요 |
| 막대는 0 에서 | 막대는 항상 0 에서 자라요. 음수와 양수가 섞이면 0 자리를 표시해요 |
| 값 읽기 | 선 차트는 포인터나 화살표 키로 달을 고르면 모든 계열 값을 보여 줘요. 막대 목록은 줄마다 값을 적어요. 지도의 점은 Tab 키로 옮겨 읽을 수 있어요 |
| 표로 보기 | 선 차트와 세로 막대에는 "표로 보기"가 있어요. 막대 목록은 값이 이미 적혀 있어 따로 두지 않았어요 |
| 근거표 | 지금 보는 읍면동의 행과 유형 판정에서 충족한 행은 바탕을 한 단계 올려 표시해요 |
| 숫자 표기 | 백엔드 제안서와 같은 규칙이에요 (변화율 +6.8%, 금액 1.97억 · 1,401만) |

지도의 한계: 읍면동 위치는 대략 좌표이고, 섬 윤곽은 위치를 가늠하기 위한 밑그림이에요. 좌표가 몰린 도심의 동은 겹치지 않게 조금 벌려 그려요.
추자면은 본도에서 멀어 왼쪽 위에 따로 놓아요.

---

## 6. API 타입 맞추기

`src/api/schema.d.ts` 는 백엔드의 OpenAPI 명세에서 만든 파일이에요. 직접 고치지 않아요.

```bash
npm run gen:api     # 백엔드 모델을 바꾼 뒤에 실행해요 (backend/.venv 가 필요해요)
```

백엔드 테스트(`test_frontend_openapi_snapshot_is_current`)가 `src/api/openapi.json` 과 실제 명세가 같은지 확인해요.
백엔드 모델만 바꾸고 타입을 다시 만들지 않으면 그 테스트가 실패해요.

---

## 7. 테스트

```bash
npm test
```

| 파일 | 확인하는 것 |
|---|---|
| `lib/lib.test.ts` | 숫자 표기, 축 눈금, SSE 풀기, 지도 좌표와 점 벌리기 |
| `api/client.test.ts` | 요청 모양, 오류 문장 전달, 스트림이 조각나서 와도 풀리는지 |
| `state/agent.test.ts` | 확인 카드에서 멈추기, 바로 실행, 연계 실행, 카드 고치기, 단계 이동, 모드 전환, 오류 처리 |
| `components/components.test.tsx` | 답 · 근거표 · 차트 · 지도 · 확인 카드 · 진행 상황 |
| `App.test.tsx` | 첫 화면에서 답까지, 지난 질문, 제안서, 연결 실패 안내 |

테스트의 예시 응답(`src/test/fixtures/*.json`)은 실제 백엔드(샘플 데이터, 템플릿 모드)에서 뽑은 값이에요.

---

## 8. 남은 일

- [ ] 행정동 경계 GeoJSON 이 생기면 지도를 경계 지도로 바꾸기
- [ ] 클라우드 LLM 모드의 전송 미리보기와 동의 흐름을 실제 키로 확인하기 (API 키가 아직 없어 가짜 응답으로만 시험했어요)
- [ ] 센터 PC(Windows)에서 Pretendard 글꼴이 뜨는지, 글자 줄바꿈과 지도 이름표 겹침이 없는지 확인하기
- [ ] 어두운 화면 모드는 만들지 않았어요

오픈소스: React(MIT), Pretendard(OFL-1.1), Lucide(ISC), Vite(MIT), TypeScript(Apache-2.0), Vitest(MIT), Testing Library(MIT), jsdom(MIT), oxlint(MIT), openapi-typescript(MIT).

화면 다듬기는 unslop 스킬(Damir Sokolovsky, CC BY 4.0)의 점검 순서를 따랐어요.
