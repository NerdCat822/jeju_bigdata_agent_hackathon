# 데이터 카탈로그 요약 (조사일 2026-11-06)

> **읽기 전에** — 이 문서는 2026-11-06 조사 기록이에요. 본문이 가리키는 "README §…"는 그때의 작업 문서를 말하고, 그 문서는 저장소에 올리지 않았어요. 지금 구현은 [backend/README.md](../backend/README.md)를 보세요.

이 문서는 README §2.1·§4.6의 근거 자료입니다. 출처는 제주데이터허브 공개 API(`/api/ndapTable/list`, `/api/data/view`)와 센터 메뉴에서 내려받은 「데이터 명세서 v13(2026-11-04)」입니다.
**명세서 xlsx와 DAKER 제공 「제주데이터허브 데이터 목록_20261105.xlsx」는 저장소에 넣지 않습니다**(재배포 금지). 필요한 사람은 각자 내려받습니다.

- 센터 명세서: https://jejudatahub.net/center/data → "데이터 명세서 다운로드" (`/document/데이터명세서_kr.xlsx`)
- 허브 상세페이지: `https://jejudatahub.net/data/view/data/{CATEGORY}/{id}` (예: `.../ENVIRONMENT/579`)

---

## 1. 제주빅데이터센터 전용 테이블 (73건)

공통 사항
- 모든 테이블에 파티션 컬럼 `pt_year`, `pt_month`(STRING) 존재 → 센터 SQL 검색 시 조건으로 사용. DuckDB 적재 시에도 그대로 유지(월 단위 필터 가속).
- "반출 불가" 테이블은 **분석·시각화 등 가공 형태로만 반출 가능**(명세서 설명문). 원자료 행 단위 반출 금지.
- 센터는 "사용자 인가형 폐쇄적 분석환경"(허브 FAQ). 운영 평일 9:00~18:00, 분석실 예약 필요, 결과물은 "데이터 반출 신청"으로 반출.

### 1.1 경제 (32) — 반출 불가(가공형태만)

| No | 테이블 | 영문 테이블명 | 제공처 | 기간·단위(명세서) |
|---|---|---|---|---|
| 1-01 | 내국인 카드 이용 현황 | tb_card_korean_usage | BC카드 | 2016-09 ~ 2018-12 |
| 1-02 | 내국인 카드 이용 금액(관광업종) | tb_card_korean_usage_market | BC카드 | 2016-09 ~ 2017-11 |
| 1-03 | 내국인 카드 이용 금액(관광테마) | tb_card_korean_usage_theme | BC카드 | 2016-09 ~ 2018-12 |
| 1-04 | 중국인 카드 이용 현황 | tb_card_chinese_usage | BC카드 | 2016-09 ~ 2018-12 |
| 1-05 | 중국인 카드 이용 금액(관광업종) | tb_card_chinese_usage_market | BC카드 | 2016-09 ~ 2017-11 |
| 1-06 | 중국인 카드 이용 금액(관광테마) | tb_card_chinese_usage_theme | BC카드 | 2016-09 ~ 2018-12 |
| 1-07 | 카드 이용 현황(읍면동)_v01 | tb_card_usage_emd | BC카드 | **2017-01 ~ 2025-06**, 월 |
| 1-08 | 카드 이용 현황(읍면동)_v02 | tb_card_usage_emd_new | BC카드 | **2023-08 ~ 현재**, 월 (권역 컬럼 추가) |
| 1-09 | 카드 이용 현황(1km격자) | tb_card_usage_grid_1k | BC카드 | 월 |
| 1-10 | 카드 이용 현황(500m격자) | tb_card_usage_grid_500m | BC카드 | 월 |
| 1-11 | 카드 이용 현황(요일별)_v01 | tb_card_usage_week | BC카드 | 월×요일 |
| 1-12 | 카드 이용 현황(요일별)_v02 | tb_card_usage_week_new | BC카드 | 월×요일 |
| 1-13 | 카드 이용 현황(시간대)_v01 | tb_card_usage_time | BC카드 | 월×시간대 |
| 1-14 | 카드 이용 현황(시간대)_v02 | tb_card_usage_time_new | BC카드 | 월×시간대 |
| 1-15 | 카드 이용 현황(골프장)_v01 | tb_card_usage_golf | BC카드 | 월 |
| 1-16 | 카드 이용 현황(골프장)_v02 | tb_card_usage_golf_new | BC카드 | 월 |
| 1-17 | 제주도 내 업종별 매장 수 | tb_card_biz_store_count | BC카드 | 2017-01 ~ 현재, 월 |
| 1-18 | 외식업 포스 이용 현황 | tb_pos_food_usage | 나이스지니데이터 | 월 |
| 1-19 | 외식업 포스 이용 현황(읍면동) | tb_pos_food_usage_emd | 나이스지니데이터 | 월 |
| 1-20 | 외식업 포스 이용 현황(500m격자) | tb_pos_food_usage_grid | 나이스지니데이터 | 월 |
| 1-21 | 외식업 포스 고객 이용 현황 | tb_pos_food_user_usage | 나이스지니데이터 | 월 |
| 1-22 | 외식업 포스 고객 이용 현황(읍면동) | tb_pos_food_user_usage_emd | 나이스지니데이터 | 월 |
| 1-23 | 외식업 포스 고객 이용 현황(500m격자) | tb_pos_food_user_usage_grid | 나이스지니데이터 | 월 |
| 1-24 | 외식업 포스 메뉴 이용 현황(읍면동) | tb_pos_food_menu_usage_emd | 나이스지니데이터 | 샘플값 2018-11 ~ 2020-12, 월 |
| 1-25 | 외식업 포스 메뉴 이용 현황(500m격자) | tb_pos_food_menu_usage_grid | 나이스지니데이터 | 월 |
| 1-26 | 외식업 포스 메뉴 매출(대분류) | tb_pos_food_menu_large_sales | 나이스지니데이터 | 월 |
| 1-27 | 외식업 포스 메뉴 매출(중분류) | tb_pos_food_menu_mid_sales | 나이스지니데이터 | 월 |
| 1-28 | 외식업 포스 메뉴 매출(소분류) | tb_pos_food_menu_small_sales | 나이스지니데이터 | 월 |
| 1-29 | 외식업 포스 메뉴 매출(세분류) | tb_pos_food_menu_sub_sales | 나이스지니데이터 | 월 |
| 1-30 | 온라인 카드 이용 현황(제주도민) | tb_card_online_usage_resident | BC카드 | 2020-01 ~, 월 |
| 1-31 | 온라인 카드 이용 현황(제주기업) | tb_card_online_usage_business | BC카드 | 2020-01 ~, 월 |
| 1-32 | 탐나는전 이용 현황 | tb_local_currency | 탐나는전 | 2023-01-04 ~, 월(비정기) |
| 참고표1 | 업종코드표(42개) | - | 나이스지니데이터 | **반출 가능** |
| 참고표2 | 메뉴코드표(대·중·소·세분류) | - | 나이스지니데이터 | **반출 가능** |

### 1.2 기업 (8) — 한국기업데이터, 반출 불가(식별정보 포함 → 집계만)

| No | 테이블 | 영문 테이블명 | 비고 |
|---|---|---|---|
| 2-01 | 거래처정보_구매 | tb_corporation_transaction_buy | |
| 2-02 | 거래처정보_판매 | tb_corporation_transaction_sale | |
| 2-03 | 기업정보 | tb_corporation_enterprise_info | |
| 2-04 | 신용정보 | tb_corporation_credit_info | |
| 2-05 | 재무정보_결산 | tb_corporation_finance_statement | |
| 2-06 | 재무정보_분기 | tb_corporation_finance_quarter | |
| 2-07 | 재무정보_직원수 | tb_corporation_finance_employee | |
| 2-08 | 휴폐업 | tb_corporation_closed_enterprise | 2021-05-07 기준 스냅샷, 기업명·사업자번호 포함 |

### 1.3 교통 (10) — 반출 가능

| No | 테이블 | 영문 테이블명 | 제공처 | 단위 |
|---|---|---|---|---|
| 3-01 | 버스 노선 정보 | tb_bus_route | 티머니 | 마스터 |
| 3-02 | 버스 노선별 이용 현황 | tb_bus_route_usage | 티머니 | 일×시간대×노선×승하차유형×이용자구분 |
| 3-03 | 버스 정류소 정보 | tb_bus_station | 티머니 | 마스터(좌표) |
| 3-04 | 버스 정류소별 이용 현황 | tb_bus_station_usage | 티머니 | 일×시간대×정류소×승·환승·하차×이용자구분 |
| 3-05 | 버스 승객별 이용 현황 | tb_bus_user_usage | 티머니 | |
| 3-06 | 버스 카드 승하차 정보 | tb_bus_card_bts | 티머니 | 승하차 태그 단위 |
| 3-07 | 도로 구간 정보 | tb_its_link | 교통정보센터 | 마스터 |
| 3-08 | 도로 노드 정보 | tb_its_node | 교통정보센터 | 마스터 |
| 3-09 | 일일 교통량 정보 | tb_its_traffic_daily | 교통정보센터 | 일×링크 |
| 3-10 | 일/시간대별 교통량 정보 | tb_its_traffic_hourly | 교통정보센터 | 일×시간×링크 |

### 1.4 통신 (15) — 와이파이 가능 / 유동인구 불가

| No | 테이블 | 영문 테이블명 | 제공처 | 반출 | 비고 |
|---|---|---|---|---|---|
| 4-01 | 와이파이 AP 현황(고정형, 최신) | tb_wifi_fixed_ap_info_auto_updatable | 제주도 | 가능 | |
| 4-02 | 와이파이 AP 현황(고정형, 과거) | - | 제주도 | 가능 | |
| 4-03 | 와이파이 AP 현황(이동형) | tb_wifi_movable_ap_info_auto_updatable | 제주도 | 가능 | |
| 4-04 | 와이파이 이용 현황 | tb_wifi_usage | 제주도 | 가능 | |
| 4-05 | 와이파이 AP별 이용 현황 | tb_wifi_ap_acct_log | 제주도 | 가능 | 2020-10-01 ~ 일별, 국적·방문유형·AP 위치 |
| 4-06 | 와이파이 일별 이용자 현황 | tb_wifi_user_daily | 제주도 | 가능 | |
| 4-07 | 내국인 유동인구(50m격자) | tb_population_korean_grid | SKT·KT | 불가 | |
| 4-08 | 장기체류 외국인 유동인구(50m격자) | tb_population_foreign_l_grid | SKT·KT | 불가 | |
| 4-09 | 단기체류 외국인 유동인구(50m격자) | tb_population_foreign_t_grid | SKT·KT | 불가 | |
| 4-10 | 내국인 유동인구(읍면동)_v01 | tb_population_korean_emd | SKT | 불가 | 과거 구간(샘플 2017) |
| 4-11 | 내국인 유동인구(읍면동)_v02 | tb_population_korean_emd_new | SKT·KT | 불가 | **2025-05-01 ~ 현재**, 일×시간×행정동 |
| 4-12 | 장기체류 외국인 유동인구(읍면동)_v01 | tb_population_foreign_l_emd | SKT | 불가 | |
| 4-13 | 장기체류 외국인 유동인구(읍면동)_v02 | tb_population_foreign_l_emd_new | SKT·KT | 불가 | |
| 4-14 | 단기체류 외국인 유동인구(읍면동)_v01 | tb_population_foreign_t_emd | SKT | 불가 | |
| 4-15 | 단기체류 외국인 유동인구(읍면동)_v02 | tb_population_foreign_t_emd_new | SKT·KT | 불가 | |

### 1.5 환경 (6) — 반출 가능

| No | 테이블 | 영문 테이블명 | 제공처 | 단위 |
|---|---|---|---|---|
| 5-01 | 날씨 관측소 정보 | tb_weather_observatory | 농업기술원 | 마스터(좌표) |
| 5-02 | 일일 날씨 정보 | tb_weather_daily | 제주도 | 2014-01 ~ 일별 누적 |
| 5-03 | 종량제봉투판매실적 | tb_waste_bag_sales_info | 제주도 | |
| 5-04 | 대형폐기물 현황_제주시 | tb_waste_large_jejusi | 제주도 | |
| 5-05 | 음식물쓰레기 배출현황_제주시 | tb_waste_food_jejusi | 환경관리공단 | 2016-01-01 ~ 일별, 배출지·태그 단위 |
| 5-06 | 음식물쓰레기 배출현황_서귀포 | tb_waste_food_seogipo | 환경관리공단 | 일별 |

---

## 2. 핵심 테이블 컬럼 요약 (레시피 설계용)

### 1-08 카드 이용 현황(읍면동)_v02 — 레시피① 핵심
`base_year_month`(YYYYMM) · `pt_year` · `pt_month` · `dstrct_se`(7개 권역: 제주시 동부/중부(동)/중부(서)/서부, 서귀포시 동부/중부/서부) · `city`(제주시/서귀포시) · `area_type`(도심/읍면) · `bjd`(법정동 73) · `biz_cd`/`biz_nm`(42업종) · `user_type`(내국인/법인/제주도민/중국/일본/동남아/기타외국) · `tour_type`(도민/개별/단체/NA) · `age`(10~70, NA) · `sex`(남성/여성/알수없음) · `user_cnt` · `use_cnt` · `use_amt`
→ v01(1-07)은 동일 구조에서 `dstrct_se`만 없음, 2017-01~2025-06. 장기 추세는 v01, 최신·권역 교차는 v02.

### 1-17 제주도 내 업종별 매장 수
`base_year_month` · `city` · `owner_gb`(내국인 개인/제주도민 개인/법인/외국인/NA) · `biz_cd`/`biz_nm` · `store_cnt`
→ 1-08과 (연월, 시군구, 업종)으로 조인해 "매장당 매출" 산출. 읍면동 단위 매장 수는 없음(시군구 단위) — 한계 명시.

### 1-24 외식업 포스 메뉴 이용 현황(읍면동) — 스트레치 레시피④
`base_year_month` · `city_cd`/`city_nm` · `bjd_cd`(법정동 8자리)/`bjd_nm` · `menu_large/mid/small/sub_cd·nm`(메뉴코드표) · `store_sale_amt`(점포당매출액) · `store_sale_cnt`(점포당판매건수) · `unit_price`(판매단가)

### 1-30 온라인 카드 이용 현황(제주도민)
`base_year_month` · `city` · `area_type` · `goods_large/medium/small_type` · `goods_code` · `goods_attribute` · `day_of_week` · `age` · `sex` · `job` · `family_type`(가구생애주기) · `user_count` · `usage_count` · `usage_amount`
→ 도정 현안 "온라인 상품 매출" 대응 가능.

### 1-32 탐나는전 이용 현황
`base_ymd`(YYYYMMDD) · `zip_code` · `card_cd`/`card_nm`(BC·국민·먹깨비·삼성·직승인·코나) · `biz_cd`/`biz_nm` · `induty`(표준업종변환) · `amount` · `cnt` · `emd`(읍면동) · `mrkt_nm`(**전통시장명**)
→ 도정 현안 "전통시장·상점가 실태" 대응. `emd`가 읍면동 텍스트라 표준화 필요.

### 2-08 휴폐업 (집계만 사용)
`base_date`(2021-05-07) · `kedcd` · `ent_nm` · `biz_num` · `establish_biz_date` · `closed_biz`(여/부) · `closed_biz_date`
→ 식별정보(기업명·사업자번호). 지역·업종별 폐업 비율로만 집계. 주소 컬럼이 없어 읍면동 매핑은 2-03 기업정보와 결합 필요(센터에서 확인).

### 3-02 버스 노선별 이용 현황 / 3-04 정류소별 이용 현황 — 레시피③
`base_date` · `day_of_week` · `base_hour`(00~23) · `bus_route_id`/`bus_route_name` 또는 `bus_station_id`/`bus_station_name` · `get_on_off_type`(승차/환승/하차) · `user_category`(어린이/청소년/일반/경로/장애 일반·동반/유공 일반·동반/기타) · `pay_type`(카드) · `user_count`
→ 정류소 좌표는 3-03. 현금 승차 미포함, 배차 횟수 없음 → "수요" 지표로만 해석(한계 명시).

### 4-05 와이파이 AP별 이용 현황
`base_date` · `user_id`(해시) · `mac_address`(해시) · `upload`/`download`/`session_time` · `nationality`(246) · `province`(17 시도) · `gender` · `age` · `visit_type`(거주/업무/관광/국제회의·인센티브/기타) · `ap_type` · `ap_category` · `ap_place`/`ap_place_detail` · `ap_latitude`/`ap_longitude` · `ap_address_detail`
→ 개인 단위 로그. 반출 가능이지만 집계해서만 사용.

### 4-11 내국인 유동인구(읍면동)_v02 — 레시피② 핵심
`base_date` · `time`(01~24) · `dstrct_se`(7권역) · `emd_cd`(행정동 8자리, 43개) · `emd_nm`(예: 제주시 한림읍) · `sex` · `age`(SKT 5세 단위 `1014`…`7000` / KT 10세 단위 `00`…`80`) · `resd_pop_cnt`(거주) · `work_pop_cnt`(근무) · `visit_pop_cnt`(방문) · `resd`(거주지: 제주/그외)
→ 수치 컬럼이 STRING(소수) → DOUBLE 캐스팅. 통신사별 연령 체계가 달라 10세 단위로 통일.

### 5-02 일일 날씨 정보
`base_date` · `observatory_code`(3자리) · `average/lowest/highest_temperature`(+time) · `daily_rainfall` · `maximum_wind_speed`(+time, direction) · `average_wind_speed`
→ 5-01 관측소 좌표로 읍면동 최근접 매핑. 강수일(≥1mm)·폭염일 플래그 파생.

### 5-05 음식물쓰레기 배출현황_제주시
`base_date` · `waster_grp`(배출지명) · `tag_gno` · `em_g`(g) · `discount_yn` · `em_amt` · `pay_type` · `device_no`
→ 태그 단위 로그. 배출지 단위 집계로 "실거주 활동" 보조 지표(스트레치).

---

## 3. 조인 키·참조 테이블 (직접 제작 필요)

| 참조 | 용도 | 출처(공개) |
|---|---|---|
| 법정동(73) ↔ 행정동(43) 매핑 | 카드·POS(법정동) × 유동인구(행정동) | 행정안전부 법정동코드·행정동 매핑 자료(공공데이터포털), 제주도 행정구역 현황 |
| 7개 권역(`dstrct_se`) ↔ 행정동 | 권역 집계·비교 | 1-08/4-11 명세서 참고표에서 추출 |
| 행정동 경계 GeoJSON | 지도, 정류소·AP 좌표 → 행정동 | 통계지리정보서비스(SGIS) 또는 공공데이터포털 행정동 경계 |
| 업종 사전(42 업종 + 동의어) | "카페", "치킨" 등 일상어 → 업종코드 | 참고표1(반출 가능) + 자체 동의어 |
| 메뉴코드표 | 스트레치 레시피④ | 참고표2(반출 가능) |
| 관측소(5-01) ↔ 행정동 | 날씨 결합 | 관측소 좌표 최근접 |
| 캘린더(요일·주말·공휴일) | 리듬 분석 | 자체 생성 |

---

## 4. 제주데이터허브 공개 데이터 (공개 데모·개발용)

**API 사용 방식**: 허브 로그인 → 데이터 상세페이지 "프로젝트 담기" → 마이페이지 프로젝트의 **프로젝트 키** 확인 → 호출
`https://open.jejudatahub.net/api/proxy/{dataKey}/{projectKey}?{param}={value}`
(dataKey·요청변수·응답변수는 상세페이지와 기술문서(hwp)에 있음. 쿼터 1,000, 단위는 확인 필요)

| ID | 데이터 | 분류 | 기간 | 갱신 | 형태 | 요청변수(확인된 것) | 응답(확인된 것) |
|---|---|---|---|---|---|---|---|
| 583 | 읍면동 단위 내국인 유동인구 | 인구·생활 | 2017 ~ | 일 | API | 기술문서 확인 | baseDate, city, emd, gender, ageGroup, resdPop, workPop, visitPop |
| 579 | 일별 기상 정보 | 환경·재난 | 2014 ~ | 일 | API | searchDate(YYYYMMDD, 필수), observatoryName | observatoryName, baseDate, average/lowest/highestTemperature(+Time), dailyRainfall, maximumWindSpeed(+Time, Direction), averageWindSpeed |
| 597 | 내국인 관광객 지역·업종·성별·연령대별 카드 이용 | 소비·경제 | 2016-09 ~ 2018-12 | - | API | startDate/endDate(YYYYMM, 필수), sido, sigungu, cityGubun(도심/읍면), marketType(교통·기타·소매·쇼핑·숙박·유흥·전체·문화/레져·식음료), userType(내국인관광객/제주도민), ageGroup, gender | sido, sigungu, cityGubun, marketType, userType, ageGroup, gender, dtYearMonth, userCount … |
| 580 | 방문목적별 입도객 현황 | 인구·생활 | 2018-01 ~ 2025-07 | - | API+CSV | 기술문서 확인 | 연월, 방문 목적(개별여행/부분패키지/패키지…), 유입자 수 |
| 520 | 제주도 방문 내국인 유동인구 추이 | 인구·생활 | 2018-01 ~ 2025-04 | - | CSV(1.6MB) | - | base_year_month, sex, age_range, time_range, visit_population_count |
| 20 | 제주관광공사 제주방문관광객 통계 | 관광·여행 | 2018 ~ | 연 | 파일 | - | 권역·국가별 외국인 관광객 수 |
| 618 | 제주 공공와이파이 AP 정보 | 관광·여행 | 2020-09 ~ | 일 | API | - | AP 위치·장소·행정구역 |
| 517 | 서귀포시 클린하우스 현황 | 환경·재난 | 2020 ~ | 연 | API | - | 설치 위치 |
| 472 | 제주특별자치도 풍력발전현황 | 환경·재난 | 2020 ~ | 연 | API | - | (참고) |
| 981 | 제주 채소류 재배 현황 | 농축수산 | 2021 | - | 파일 | - | (참고) |

허브 카테고리별 건수(2026-11-06): 관광·여행 433, 보건·복지 198, 교육·행정 134, 소비·경제 116, 환경·재난 115, 교통·안전 103, 농축수산 94, 인구·생활 66 (총 1,259).

허브 API 응답 필드명은 camelCase(예: `visitPop`), 센터 테이블은 snake_case(예: `visit_pop_cnt`) → 카탈로그 YAML에 두 표기를 모두 매핑해 **같은 레시피 SQL이 양쪽에서 동작**하도록 설계.

---

## 5. 허브 백엔드 엔드포인트 메모 (수집 스크립트용, 인증 불필요 확인분)

| 엔드포인트 | 내용 |
|---|---|
| `GET https://jejudatahub.net/api/ndapTable/list` | 센터 테이블 목록 73건(id, category, title, tableName, returnAbleYn) |
| `GET https://jejudatahub.net/api/data/view?id={id}` | 허브 데이터 상세(dataApi.url, dataApiElements 요청·응답변수, 파일 정보, csvData 미리보기) |
| `GET https://jejudatahub.net/api/data/top10Popular` | 인기 데이터 10건 |
| `GET https://jejudatahub.net/api/data/categoryCount` | 카테고리별 건수 |
| `GET https://jejudatahub.net/api/community/faq` | FAQ 13건(센터 이용·반출 절차 포함) |
| `GET https://jejudatahub.net/api/data?...` | 목록 검색은 파라미터 조합에 따라 500 반환 → 로그인 세션 필요 추정 |

`www.` 호스트는 308로 `jejudatahub.net`에 리다이렉트되므로 리다이렉트 추종 필요. 실제 데이터 호출은 반드시 공식 프록시(`open.jejudatahub.net`)와 프로젝트 키로.
