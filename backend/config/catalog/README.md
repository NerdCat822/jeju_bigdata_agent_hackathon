# 카탈로그 (config/catalog)

YAML 한 장이 분석 테이블 하나예요. 새 데이터를 붙일 때는 이 폴더에 파일 하나를 추가하고 `python -m meomulmeong build-data` 를 다시 실행하면 돼요.

- `table`: DuckDB 테이블 이름 (표준 스키마)
- `columns`: 표준 컬럼과 설명. 에이전트가 테이블을 고르고 SQL을 쓸 때 이 설명을 읽어요
- `limits`: 이 데이터를 쓴 답에 항상 붙는 한계 문장
- `sources.hub`: 제주데이터허브 Open API 정보(`dataset_id`, `data_key`)와 원본 → 표준 컬럼 변환식
- `sources.center`: 센터 추출본 CSV(`file_glob`)의 변환식. `data/center/` 에 파일을 넣으면 허브 대신 이 자료를 써요
- `select`: `표준 컬럼: DuckDB SQL 식`. `std_date`, `std_month`, `std_age`, `std_sex`, `std_theme`, `std_user_type`, `std_route`, `std_nationality` 매크로를 쓸 수 있어요
- `place`: 원본의 시군구·읍면동 이름 컬럼. 지정하면 행정동 코드(`emd_cd`)를 자동으로 붙여요
- `aggregate`: 같은 키의 행을 합칠 때 쓰는 집계 (예: 법정동 여러 개가 한 행정동으로 모일 때)

합성(샘플) 데이터는 허브 API 응답과 같은 컬럼으로 만들어져 `sources.hub` 변환식을 그대로 통과해요.
