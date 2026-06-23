import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, Point
from pyproj import Transformer

def generate_mock_data():
    print("Generating mock dataset for testing...")

    # 1. 주소 CSV 생성
    # SITE_001: 서울특별시 중구 세종대로 110 (서울시청)
    # SITE_002: 서울특별시 종로구 삼청로 37 (국립민속박물관)
    csv_data = {
        "site_id": ["SITE_001", "SITE_002"],
        "address": ["서울특별시 중구 세종대로 110", "서울특별시 종로구 삼청로 37"],
        "site_name": ["서울시청 유적지 (C자형 오류)", "국립민속박물관 유물산포지 (정상)"]
    }
    df = pd.DataFrame(csv_data)
    csv_path = "mock_addresses.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"Created mock CSV: {csv_path}")

    # 2. Shapefile (Polygon) 생성
    # 좌표 변환기 준비: WGS84 -> UTM-K (EPSG:5179)
    # 실제 카카오 API 지오코딩 결과로 예상되는 좌표를 UTM-K로 수동 계산하여 다각형을 그립니다.
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    # 서울시청 실제 카카오 API 지오코딩 좌표 (WGS84)
    # x (경도) = 126.977918, y (위도) = 37.566371
    seoul_city_hall_utmk = transformer.transform(126.977918, 37.566371)
    sh_x, sh_y = seoul_city_hall_utmk
    print(f"Seoul City Hall UTM-K: X={sh_x:.2f}, Y={sh_y:.2f}")

    # 국립민속박물관 실제 카카오 API 지오코딩 좌표 (WGS84)
    # x (경도) = 126.978890, y (위도) = 37.581675
    folk_museum_utmk = transformer.transform(126.978890, 37.581675)
    fm_x, fm_y = folk_museum_utmk
    print(f"Folk Museum UTM-K: X={fm_x:.2f}, Y={fm_y:.2f}")

    # SITE_001 (서울시청): C자형 다각형 만들기
    # 서울시청 좌표(sh_x, sh_y)가 C자형의 오목하게 들어간 빈 공간(안쪽 만)에 오도록 꼭짓점 설정
    # 중심 좌표에서 사방으로 100m 크기로 그리고, 가운데를 파내어 C자형을 만듭니다.
    c_poly = Polygon([
        (sh_x - 50, sh_y - 50),
        (sh_x + 50, sh_y - 50),
        (sh_x + 50, sh_y + 50),
        (sh_x - 50, sh_y + 50),
        (sh_x - 50, sh_y + 20),
        (sh_x + 20, sh_y + 20),
        (sh_x + 20, sh_y - 20),
        (sh_x - 50, sh_y - 20),
    ])
    
    # SITE_002 (국립민속박물관): 단순 사각형 다각형 만들기
    # 박물관 좌표(fm_x, fm_y)가 안전하게 내부에 들어가도록 설정
    rect_poly = Polygon([
        (fm_x - 40, fm_y - 40),
        (fm_x + 40, fm_y - 40),
        (fm_x + 40, fm_y + 40),
        (fm_x - 40, fm_y + 40)
    ])

    poly_gdf = gpd.GeoDataFrame({
        "id": ["SITE_001", "SITE_002"],
        "name": ["Seoul City Hall Polygon", "Folk Museum Polygon"],
        "geometry": [c_poly, rect_poly]
    }, crs="EPSG:5179")

    shp_path = "mock_polygons.shp"
    poly_gdf.to_file(shp_path, encoding="utf-8")
    print(f"Created mock Shapefile: {shp_path}")

    # 검증 목적의 주소 좌표 포함 여부 선행 출력
    p1 = Point(sh_x, sh_y)
    p2 = Point(fm_x, fm_y)
    print(f"\n[Mock Data Verification]")
    print(f" - SITE_001 Point in Polygon? {p1.within(c_poly)} (Expected: False - Out of Boundary)")
    print(f" - SITE_002 Point in Polygon? {p2.within(rect_poly)} (Expected: True - Inside)")

if __name__ == "__main__":
    generate_mock_data()
