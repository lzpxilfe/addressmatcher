# 🗺️ Address Matcher & Validator (v0.1.0)

한국 주소를 정밀 지오코딩하여 점(Point) 심볼 데이터로 변환하고, 기존의 유적/유물산포지 구역(Polygon) 데이터와 대조 검증하여 경계 밖으로 이탈한 대표 소재지 좌표를 자동으로 보정해주는 **QGIS 플러그인** 및 **독립형 파이썬 스크립트 도구**입니다.

---

## ✨ 주요 기능

* **📍 한국 주소 정밀 지오코딩**:
  * 카카오 로컬 API를 연동하여 입력 주소 CSV를 고해상도 위경도 좌표(WGS84, EPSG:4326)로 변환합니다.
* **📂 CSV 헤더 자동 분석 (UX 개선)**:
  * CSV 파일을 로드하는 즉시 인코딩(UTF-8, CP949, EUC-KR)을 자동 감지하고, 첫 행의 컬럼명을 읽어와 드롭다운 선택 리스트에 자동으로 채워줍니다.
* **🔍 공간 경계 검증 (PIP 검사)**:
  * 생성된 주소 점들이 지정한 유적 다각형(Polygon) 경계 내에 실제로 존재하는지 대조 연산합니다.
* **🛠️ 경계 이탈 대표점 자동 보정**:
  * 초승달 모양(C-shape) 등의 이유로 기하학적 중심점(Centroid)이 구역 바깥 빈 공간에 떨어진 경우를 감지하여, 해당 다각형 내부의 가장 안정한 대표점(Point on Surface)으로 보정 좌표를 자동 산출합니다.
* **⚙️ 다목적 모드 전환 (체크박스 토글)**:
  * `[단순 점 생성]` 모드와 `[공간 경계 검증]` 모드를 체크박스 하나로 손쉽게 토글하여 사용할 수 있습니다.
* **🖥️ QGIS 반응형 UI & 자동 줌**:
  * 지오코딩 중 QGIS가 응답 없음(프리징)으로 멈추는 문제를 방지하기 위해 비동기 프로그레스바 및 작업 취소 기능을 지원합니다.
  * 연산 완료 시 정상 점(초록색)과 이탈 점(빨간색 X자) 레이어가 자동 생성되며 해당 구역으로 맵 캔버스가 자동 줌인됩니다.
* **💾 사용자 설정 자동 백업**:
  * QGIS 환경설정 저장소(`QgsSettings`)를 통해 이전에 성공한 카카오 API Key 및 필드 설정값들을 PC에 자동 복원하여 매번 재입력하는 번거로움을 최소화합니다.

---

## 🚀 설치 및 사용법

### 🔌 QGIS 플러그인 적용
QGIS 플러그인 로컬 경로에 `address_matcher` 폴더를 통째로 배치한 후 QGIS를 재시작하여 플러그인 관리자에서 활성화합니다.
* **경로**: `C:\Users\<사용자명>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\address_matcher`

### 🐍 독립형 파이썬 스크립트 구동
QGIS 없이 독립형 콘솔 환경에서 연산하려면 다음 라이브러리를 설치 후 실행합니다.
```bash
pip install -r requirements.txt

# 1. 지오코딩 수행
python address_geocoder.py <인풋_CSV> <아웃풋_CSV> <주소컬럼명> <API키>

# 2. 다각형 경계 검증 및 보정 좌표 산출
python boundary_validator.py <지오코딩된_CSV> <폴리곤_SHP> <CSV_ID컬럼> <SHP_ID필드> <출력접두사>
```

## Citation

이 저장소가 연구, 수업, 현장 업무에 도움이 되었다면 GitHub의 **Cite this repository** 버튼으로 인용해 주세요.

[![Cite this repository](https://img.shields.io/badge/Cite_this-repository-2ea44f?logo=github)](https://github.com/lzpxilfe/addressmatcher)
[![Star this repository](https://img.shields.io/github/stars/lzpxilfe/addressmatcher?style=social)](https://github.com/lzpxilfe/addressmatcher)

인용 메타데이터는 [CITATION.cff](CITATION.cff)에 보관합니다.

