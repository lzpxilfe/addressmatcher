import os
import time
import requests
import re
import pandas as pd
from typing import Optional, Tuple, Dict, Any

def clean_address_text(address: str) -> str:
    """
    주소 텍스트 끝에 붙는 '외 X필지', '일원' 등의 지적도상의 불필요한 단어를 지우고,
    산 지번의 띄어쓰기를 규격화하는 정형화(Cleansing) 전처리 함수
    """
    if not address or not isinstance(address, str):
        return ""
        
    addr = address.strip()
    
    # 1. 괄호로 묶인 부가 정보 제거 (예: "(동천동)", "[일부]")
    addr = re.sub(r"\([^)]*\)", "", addr)
    addr = re.sub(r"\[[^\]]*\]", "", addr)
    
    # 2. 주소 끝부분의 수식용 기호 및 텍스트 제거
    # '외 X필지', '외 필지', '일원', '일대', '주변', '부근', '번지 일원' 등
    patterns_to_remove = [
        r"\s*외\s*\d+\s*필지.*",
        r"\s*외\s*필지.*",
        r"\s*일원.*",
        r"\s*일대.*",
        r"\s*주변.*",
        r"\s*부근.*",
        r"\s*번지\s*일원.*",
        r"\s*번지.*" # 단독 번지 글자 제거 (숫자는 보존)
    ]
    for pattern in patterns_to_remove:
        addr = re.sub(pattern, "", addr)
        
    # 3. '산20'과 '산 20' 공백 규격화 (카카오 로컬 API 대응성 제고)
    addr = re.sub(r"산\s*(\d+)", r"산 \1", addr)
    
    # 4. 여러 개의 공백을 단일 공백으로 치환
    addr = re.sub(r"\s+", " ", addr).strip()
    
    return addr

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

    def geocode_with_fallback(self, address: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        주소 정제 후 지오코딩 실패 시 본번지 검색, 리/동 중심점 검색으로 
        단계별 축소(Fallback) 검색을 수행하여 최종 지오코딩 실패율을 낮춥니다.
        """
        # [1단계] 정제된 정밀 주소로 1차 검색
        cleaned_addr = clean_address_text(address)
        lon, lat, match_type = self.geocode(cleaned_addr)
        if lon is not None:
            return lon, lat, match_type
            
        # [2단계] 가지번 제거 후 본번지 검색 (예: 123-45 ➔ 123, 산 23-4 ➔ 산 23)
        # 지번 뒷부분의 하이픈과 가지번호 제거
        fallback_addr = None
        if re.search(r"(\s+\d+)-\d+$", cleaned_addr):
            fallback_addr = re.sub(r"(\s+\d+)-\d+$", r"\1", cleaned_addr)
        elif re.search(r"(\s+산\s*\d+)-\d+$", cleaned_addr):
            fallback_addr = re.sub(r"(\s+산\s*\d+)-\d+$", r"\1", cleaned_addr)
            
        if fallback_addr and fallback_addr != cleaned_addr:
            lon, lat, match_type = self.geocode(fallback_addr)
            if lon is not None:
                return lon, lat, "FALLBACK_MAIN_JIBUN"
                
        # [3단계] 지번 전체 제거 후 동/리 중심점 검색 (예: 경주시 내남면 용장리 123 ➔ 경주시 내남면 용장리)
        # 주소 문자열에서 공백과 숫자(번지)가 시작되는 부분부터 문자열 끝까지 제거
        fallback_town = re.sub(r"(\s+산)?\s+\d+.*$", "", cleaned_addr).strip()
        
        if fallback_town and fallback_town != cleaned_addr:
            lon, lat, match_type = self.geocode(fallback_town)
            if lon is not None:
                return lon, lat, "FALLBACK_TOWN"
                
        return None, None, "FAIL"

def geocode_csv(
    input_csv_path: str,
    output_csv_path: str,
    address_column: str,
    api_key: str,
    delay_sec: float = 0.1
) -> pd.DataFrame:
    """
    주소 CSV 파일을 읽어 다단계 Fallback 지오코딩을 수행하고, 결과를 CSV로 저장합니다.
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
    print(f"Starting geocoding with fallback for {total_rows} rows...")

    for idx, row in df.iterrows():
        address = row[address_column]
        lon, lat, match_type = geocoder.geocode_with_fallback(address)
        
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
    import sys
    
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

