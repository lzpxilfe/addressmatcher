# -*- coding: utf-8 -*-
import requests
from typing import Optional, Dict, Any

def get_cadastral_polygon(lon: float, lat: float, api_key: str) -> Optional[Dict[str, Any]]:
    """
    국토교통부 브이월드 WFS API를 연동하여, 지정된 위경도 좌표(lon, lat)가 위치한 
    연속지적도(lp_pa_cbnd) 필지의 경계 다각형(GeoJSON Feature) 데이터를 가져옵니다.
    """
    if not api_key or api_key.strip() == "":
        return None
        
    url = "http://api.vworld.kr/req/wfs"
    
    # CQL 공간 필터: POINT(경도 위도) 좌표와 지적 경계(geom)가 만나는 필지 검색
    cql_filter = f"INTERSECTS(geom, POINT({lon} {lat}))"
    
    params = {
        "key": api_key.strip(),
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typename": "lp_pa_cbnd",
        "output": "application/json",
        "srsname": "EPSG:4326", # WGS84 위경도로 다각형 좌표 수신
        "cql_filter": cql_filter
    }
    
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200:
            data = response.json()
            features = data.get("features", [])
            if features and len(features) > 0:
                # 여러 필지가 겹치더라도 첫 번째 매칭되는 유효한 필지 feature 반환
                return features[0]
        return None
    except Exception as e:
        # QGIS 로그 메시지 등을 위해 호출 스택 전송
        raise RuntimeError(f"Vworld WFS API request failed: {e}")
