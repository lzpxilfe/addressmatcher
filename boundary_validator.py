import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import numpy as np

def validate_boundaries(
    geocoded_csv_path: str,
    polygon_shp_path: str,
    csv_id_col: str,
    shp_id_col: str,
    output_prefix: str
):
    """
    지오코딩된 주소 포인트와 기존 다각형 SHP 파일을 대조하여
    경계 밖에 위치한 포인트를 식별하고 보정 좌표를 산출합니다.
    """
    print(f"Loading geocoded CSV: {geocoded_csv_path}")
    df = pd.read_csv(geocoded_csv_path)
    
    # 유효한 좌표가 있는 행만 필터링
    valid_coord_mask = df['lon'].notna() & df['lat'].notna()
    valid_df = df[valid_coord_mask].copy()
    invalid_df = df[~valid_coord_mask].copy()
    
    if len(valid_df) == 0:
        raise ValueError("지오코딩된 좌표가 있는 유효한 행이 CSV에 없습니다.")
        
    print(f"Loading Polygon Shapefile: {polygon_shp_path}")
    poly_gdf = gpd.read_file(polygon_shp_path)
    
    # 1. Point GeoDataFrame 생성 (경위도 EPSG:4326 좌표계 기준)
    geometry = [Point(xy) for xy in zip(valid_df['lon'], valid_df['lat'])]
    point_gdf = gpd.GeoDataFrame(valid_df, geometry=geometry, crs="EPSG:4326")
    
    # 2. 좌표계(CRS) 일치화
    # 연산 속도 및 거리 측정(meter 단위)을 위해 Polygon의 CRS로 Point 데이터를 투영 변환합니다.
    target_crs = poly_gdf.crs
    if target_crs is None:
        print("[Warning] Polygon SHP에 CRS 정보가 없습니다. 기본적으로 EPSG:5179 (UTM-K)로 가정합니다.")
        poly_gdf.crs = "EPSG:5179"
        target_crs = "EPSG:5179"
        
    print(f"Reprojecting Point layer from EPSG:4326 to target CRS: {target_crs}")
    point_gdf = point_gdf.to_crs(target_crs)
    
    # 매칭 비교 결과 속성 초기화
    point_gdf['is_inside'] = False
    point_gdf['distance_m'] = 0.0
    point_gdf['corrected_lon'] = point_gdf['lon']
    point_gdf['corrected_lat'] = point_gdf['lat']
    point_gdf['validation_note'] = "NOT_COMPARED"
    
    # ID 속성 데이터 타입 일치 (문자열 또는 숫자)
    point_gdf[csv_id_col] = point_gdf[csv_id_col].astype(str)
    poly_gdf[shp_id_col] = poly_gdf[shp_id_col].astype(str)
    
    # Polygon 데이터 효율적인 딕셔너리 매핑 (ID별 geometry 검색)
    poly_dict = dict(zip(poly_gdf[shp_id_col], poly_gdf.geometry))
    
    # EPSG:4326으로 좌표를 출력하기 위해 투영 역산(reproject back)용 공간 프레임 복사본 준비
    corrected_geoms = []
    corrected_indices = []
    
    print("Performing Point-in-Polygon (PIP) checks...")
    for idx, row in point_gdf.iterrows():
        id_val = row[csv_id_col]
        pt_geom = row.geometry
        
        if id_val not in poly_dict:
            point_gdf.at[idx, 'validation_note'] = f"POLYGON_NOT_FOUND (ID: {id_val})"
            continue
            
        polygon = poly_dict[id_val]
        
        # Point-in-Polygon 검사
        is_inside = pt_geom.within(polygon)
        point_gdf.at[idx, 'is_inside'] = is_inside
        
        if is_inside:
            point_gdf.at[idx, 'validation_note'] = "OK"
            point_gdf.at[idx, 'distance_m'] = 0.0
        else:
            # 경계를 벗어남 (오류 발생)
            point_gdf.at[idx, 'validation_note'] = "OUTSIDE"
            # 최단 거리 계산 (미터 단위)
            dist = pt_geom.distance(polygon)
            point_gdf.at[idx, 'distance_m'] = dist
            
            # 보정 좌표 계산: representative_point()는 다각형의 안정한 '내부 점(Point on Surface)'을 보장함
            # 초승달 형태에서도 무조건 다각형 면 내부 영역의 점을 반환
            rep_pt = polygon.representative_point()
            
            # WGS84 좌표로 복원하기 위해 기하 데이터를 보관
            corrected_geoms.append(rep_pt)
            corrected_indices.append(idx)
            
    # 보정된 좌표를 WGS84(경위도)로 역변환하여 저장
    if corrected_geoms:
        temp_gdf = gpd.GeoDataFrame(geometry=corrected_geoms, crs=target_crs)
        temp_gdf_wgs84 = temp_gdf.to_crs("EPSG:4326")
        
        for i, idx in enumerate(corrected_indices):
            wgs_pt = temp_gdf_wgs84.geometry.iloc[i]
            point_gdf.at[idx, 'corrected_lon'] = wgs_pt.x
            point_gdf.at[idx, 'corrected_lat'] = wgs_pt.y
            print(f"[Correction] ID {point_gdf.at[idx, csv_id_col]}: 원래 좌표가 경계 밖({point_gdf.at[idx, 'distance_m']:.1f}m 이격)에 위치하여 Polygon 내부 점(Lon: {wgs_pt.x:.6f}, Lat: {wgs_pt.y:.6f})으로 보정 좌표 생성함.")
            
    # 3. 결과 저장
    # WGS84 위경도 좌표 레이어로 다시 투영 변환 후 공간 파일로 내보내기
    point_gdf_wgs84 = point_gdf.to_crs("EPSG:4326")
    
    # GeoJSON 및 Shapefile 출력 경로 정의
    geojson_out = f"{output_prefix}_results.geojson"
    csv_out = f"{output_prefix}_results.csv"
    
    # 공간 레이어 저장 (한글 인코딩 지원)
    # GeoJSON은 기본적으로 UTF-8로 저장됨
    point_gdf_wgs84.to_file(geojson_out, driver="GeoJSON")
    print(f"Saved Spatial output (GeoJSON) to: {geojson_out}")
    
    # 데이터프레임 형식으로 CSV 저장 (지오코딩 안 된 목록도 병합하여 저장)
    result_df = pd.DataFrame(point_gdf_wgs84.drop(columns='geometry'))
    if len(invalid_df) > 0:
        invalid_df['is_inside'] = False
        invalid_df['distance_m'] = -1.0
        invalid_df['corrected_lon'] = np.nan
        invalid_df['corrected_lat'] = np.nan
        invalid_df['validation_note'] = "GEOC_FAILED"
        result_df = pd.concat([result_df, invalid_df], ignore_index=True)
        
    result_df.to_csv(csv_out, index=False, encoding='utf-8-sig')
    print(f"Saved Tabular output (CSV) to: {csv_out}")
    
    # 요약 통계 출력
    total_checked = len(point_gdf)
    inside_count = point_gdf['is_inside'].sum()
    outside_count = total_checked - inside_count
    
    print("\n=== 검증 결과 요약 ===")
    print(f"총 검증 대상 (좌표 있음): {total_checked}건")
    print(f" - 정상 (경계 내부): {inside_count}건")
    print(f" - 오류 (경계 외부): {outside_count}건")
    if len(invalid_df) > 0:
        print(f"지오코딩 실패 항목: {len(invalid_df)}건")
    print("=======================\n")
    
    return result_df

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 6:
        print("Usage: python boundary_validator.py <geocoded_csv> <polygon_shp> <csv_id_column> <shp_id_column> <output_prefix>")
        print("Example: python boundary_validator.py geocoded.csv site_polygons.shp site_id id validation")
    else:
        validate_boundaries(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
