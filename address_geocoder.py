import os
import time
import requests
import pandas as pd
from typing import Optional, Tuple, Dict, Any

class KakaoGeocoder:
    """
    Kakao Local API를 이용하여 주소를 위경도 좌표로 변환하는 클래스
    """
    API_URL = "https://dapi.kakao.com/v2/local/search/address.json"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"KakaoAK {self.api_key}"
        }

    def geocode(self, address: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        주소를 입력받아 (경도, 위도, 매칭방식) 튜플을 반환합니다.
        실패 시 (None, None, "FAIL")을 반환합니다.
        """
        if not address or not isinstance(address, str) or address.strip() == "":
            return None, None, "EMPTY_ADDRESS"

        params = {"query": address.strip()}
        
        # API 호출 및 재시도 로직
        for attempt in range(3):
            try:
                response = requests.get(self.API_URL, headers=self.headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    documents = data.get("documents", [])
                    if documents:
                        # 첫 번째 검색 결과 매칭
                        doc = documents[0]
                        lon = float(doc.get("x"))
                        lat = float(doc.get("y"))
                        match_type = doc.get("address_type", "UNKNOWN")
                        return lon, lat, match_type
                    else:
                        return None, None, "NO_MATCH"
                elif response.status_code == 401:
                    print("[Error] Kakao API Unauthorized: API 키가 만료되었거나 올바르지 않습니다.")
                    return None, None, "UNAUTHORIZED"
                elif response.status_code == 429:
                    print(f"[Warning] Rate limited. Retrying... (Attempt {attempt + 1}/3)")
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Warning] HTTP {response.status_code} received. Retrying...")
                    time.sleep(1)
            except requests.RequestException as e:
                print(f"[Warning] Network error occurred: {e}. Retrying...")
                time.sleep(2)
        
        return None, None, "NETWORK_ERROR"

def geocode_csv(
    input_csv_path: str,
    output_csv_path: str,
    address_column: str,
    api_key: str,
    delay_sec: float = 0.1
) -> pd.DataFrame:
    """
    주소 CSV 파일을 읽어 지오코딩을 수행하고, 위경도 좌표 컬럼을 추가하여 새 CSV로 저장합니다.
    """
    print(f"Reading CSV file: {input_csv_path}")
    df = pd.read_csv(input_csv_path)

    if address_column not in df.columns:
        raise ValueError(f"CSV 파일에 '{address_column}' 컬럼이 존재하지 않습니다. 존재하는 컬럼: {list(df.columns)}")

    geocoder = KakaoGeocoder(api_key)
    
    longitudes = []
    latitudes = []
    match_types = []

    total_rows = len(df)
    print(f"Starting geocoding for {total_rows} rows...")

    for idx, row in df.iterrows():
        address = row[address_column]
        lon, lat, match_type = geocoder.geocode(address)
        
        longitudes.append(lon)
        latitudes.append(lat)
        match_types.append(match_type)
        
        if (idx + 1) % 10 == 0 or (idx + 1) == total_rows:
            print(f"Progress: {idx + 1}/{total_rows} rows processed.")
        
        # API 과도한 호출 방지 지연
        if delay_sec > 0:
            time.sleep(delay_sec)

    df['lon'] = longitudes
    df['lat'] = latitudes
    df['geocode_status'] = match_types

    # 결과 저장
    df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"Geocoding completed. Saved result to: {output_csv_path}")
    
    success_count = df['lon'].notna().sum()
    print(f"Success: {success_count}/{total_rows} ({success_count/total_rows*100:.1f}%)")
    
    return df

if __name__ == "__main__":
    # 간단한 단독 실행 테스트용
    import sys
    
    # 기본 테스트 키 설정
    DEFAULT_API_KEY = "965ffae72ca50570426f717a4c282e08"
    
    if len(sys.argv) < 4:
        print("Usage: python address_geocoder.py <input_csv> <output_csv> <address_column> [api_key]")
        print("Example: python address_geocoder.py addresses.csv geocoded.csv 주소")
    else:
        in_csv = sys.argv[1]
        out_csv = sys.argv[2]
        addr_col = sys.argv[3]
        api_key = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_API_KEY
        
        geocode_csv(in_csv, out_csv, addr_col, api_key)
