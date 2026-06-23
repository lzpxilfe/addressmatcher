import os
import csv
import requests
import time
from PyQt5.QtCore import Qt, QVariant, QCoreApplication
from PyQt5.QtWidgets import QAction, QMessageBox, QProgressDialog
from PyQt5.QtGui import QIcon, QColor

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, 
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsField, QgsFeatureRequest, QgsSymbol, QgsSingleSymbolRenderer,
    QgsSimpleMarkerSymbolLayerBase, QgsSettings, QgsMessageLog, Qgis
)

from .dialog import AddressMatcherDialog

class AddressMatcherPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None

    def initGui(self):
        # 8비트 아이콘 파일 경로
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            # 아이콘이 없을 경우 기본 스타일 아이콘 설정
            icon = QIcon()
        else:
            icon = QIcon(icon_path)
            
        self.action = QAction(
            icon, 
            "Address Matcher & Validator", 
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        
        # QGIS Vector 메뉴 아래에 추가
        self.iface.addVectorToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("Address Matcher & Validator", self.action)

    def unload(self):
        # QGIS 종료 또는 플러그인 비활성화 시 GUI 제거
        self.iface.removePluginVectorMenu("Address Matcher & Validator", self.action)
        self.iface.removeVectorToolBarIcon(self.action)

    def geocode_address(self, address, api_key):
        """
        카카오 API를 통해 단일 주소 지오코딩 수행 (Requests 활용)
        """
        if not address or address.strip() == "":
            return None, None, "EMPTY_ADDRESS"
            
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {api_key}"}
        params = {"query": address.strip()}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                documents = data.get("documents", [])
                if documents:
                    doc = documents[0]
                    lon = float(doc.get("x"))
                    lat = float(doc.get("y"))
                    match_type = doc.get("address_type", "UNKNOWN")
                    return lon, lat, match_type
                return None, None, "NO_MATCH"
            elif response.status_code == 401:
                return None, None, "UNAUTHORIZED"
            return None, None, f"HTTP_{response.status_code}"
        except Exception as e:
            return None, None, f"ERROR_{str(e)[:20]}"

    def run(self):
        dlg = AddressMatcherDialog(self.iface.mainWindow())
        if dlg.exec_():
            values = dlg.get_values()
            
            csv_path = values["csv_path"]
            address_col = values["address_col"]
            validation_enabled = values["validation_enabled"]
            csv_id_col = values["csv_id_col"]
            poly_layer = values["layer"]
            shp_id_col = values["shp_id_col"]
            api_key = values["api_key"]
            output_prefix = values["output_prefix"]
            
            # 사용자 설정을 QgsSettings에 저장 (하드코딩 방지 및 편의성 제공)
            settings = QgsSettings()
            settings.setValue("AddressMatcher/csv_path", csv_path)
            settings.setValue("AddressMatcher/address_col", address_col)
            settings.setValue("AddressMatcher/validation_enabled", "true" if validation_enabled else "false")
            settings.setValue("AddressMatcher/csv_id_col", csv_id_col)
            settings.setValue("AddressMatcher/shp_id_col", shp_id_col)
            settings.setValue("AddressMatcher/api_key", api_key)
            settings.setValue("AddressMatcher/output_prefix", output_prefix)
            
            # 1. CSV 로드 및 지오코딩 수행
            rows = []
            try:
                with open(csv_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        rows.append(dict(r))
            except Exception as e:
                QMessageBox.critical(self.iface.mainWindow(), "에러", f"CSV 파일을 읽는 중 오류가 발생했습니다:\n{e}")
                return
                
            total_rows = len(rows)
            success_count = 0
            
            # 1-1. 진행 경과 표시를 위한 QProgressDialog 설정
            progress = QProgressDialog("주소 지오코딩을 수행하고 있습니다...", "취소", 0, total_rows, self.iface.mainWindow())
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0) # 즉시 표시
            progress.setValue(0)
            
            for idx, row in enumerate(rows):
                # 사용자가 취소를 눌렀을 경우 작업 중단
                if progress.wasCanceled():
                    self.iface.messageBar().pushMessage("Address Matcher", "사용자에 의해 지오코딩 작업이 취소되었습니다.", level=1, duration=3)
                    progress.close()
                    return
                    
                addr = row.get(address_col, "")
                lon, lat, status = self.geocode_address(addr, api_key)
                
                row["lon"] = lon
                row["lat"] = lat
                row["geocode_status"] = status
                
                if lon is not None:
                    success_count += 1
                else:
                    # 지오코딩 실패한 경우 QGIS 로그 메시지 패널에 경고 작성
                    QgsMessageLog.logMessage(
                        f"주소 지오코딩 실패 - 주소: {addr}, 결과상태: {status}",
                        "AddressMatcher",
                        Qgis.Warning
                    )
                
                # 프로그레스바 상태 업데이트 및 QGIS UI 먹통 방지
                progress.setValue(idx + 1)
                QCoreApplication.processEvents()
                
                # API 호출 간 약간의 지연
                time.sleep(0.05)
                
            progress.close()
            self.iface.messageBar().pushMessage("Address Matcher", f"지오코딩 완료: {success_count}/{total_rows} 성공", level=0, duration=3)
            
            # WGS84 기준 좌표계 설정
            crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            
            # === 분기 A: 단순 지오코딩 점 생성 모드 ===
            if not validation_enabled:
                # 결과 CSV 저장
                csv_out_path = f"{output_prefix}_geocoded.csv"
                try:
                    if rows:
                        fieldnames = list(rows[0].keys())
                        with open(csv_out_path, 'w', encoding='utf-8-sig', newline='') as f:
                            writer = csv.DictWriter(f, fieldnames=fieldnames)
                            writer.writeheader()
                            writer.writerows(rows)
                    self.iface.messageBar().pushMessage("Address Matcher", f"결과 CSV 저장 완료: {csv_out_path}", level=0, duration=4)
                except Exception as e:
                    QMessageBox.critical(self.iface.mainWindow(), "에러", f"결과 CSV 저장 실패:\n{e}")
                
                # QGIS 메모리 레이어 생성 및 로드
                geocoded_layer = QgsVectorLayer("Point?crs=EPSG:4326", "지오코딩 위치 (Geocoded)", "memory")
                pr = geocoded_layer.dataProvider()
                pr.addAttributes([
                    QgsField("site_id", QVariant.String),
                    QgsField("address", QVariant.String),
                    QgsField("status", QVariant.String),
                    QgsField("lon", QVariant.Double),
                    QgsField("lat", QVariant.Double)
                ])
                geocoded_layer.updateFields()
                
                features = []
                for row in rows:
                    if row["lon"] is not None and row["lat"] is not None:
                        feat = QgsFeature()
                        feat.setFields(geocoded_layer.fields())
                        geom = QgsGeometry.fromPointXY(QgsPointXY(float(row["lon"]), float(row["lat"])))
                        feat.setGeometry(geom)
                        feat.setAttributes([
                            row.get(csv_id_col, ""), # ID 컬럼이 없거나 비활성이면 공백 가능
                            row.get(address_col, ""),
                            row.get("geocode_status", ""),
                            float(row["lon"]),
                            float(row["lat"])
                        ])
                        features.append(feat)
                
                pr.addFeatures(features)
                geocoded_layer.updateExtents()
                
                # 파란색 마커 스타일링
                symbol = QgsSymbol.defaultSymbol(geocoded_layer.geometryType())
                symbol.setColor(QColor("#3182CE"))
                symbol.setSize(3.5)
                geocoded_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
                
                # 프로젝트 로드 및 줌인
                QgsProject.instance().addMapLayer(geocoded_layer)
                canvas = self.iface.mapCanvas()
                if geocoded_layer.featureCount() > 0:
                    canvas.setExtent(geocoded_layer.extent())
                    canvas.refresh()
                    
                QMessageBox.information(
                    self.iface.mainWindow(), 
                    "작업 완료", 
                    f"지오코딩이 성공적으로 완료되었습니다.\n\n"
                    f"총 대상: {total_rows}건\n"
                    f" - 성공: {success_count}건\n"
                    f" - 실패: {total_rows - success_count}건\n\n"
                    f"QGIS 맵 캔버스에 [지오코딩 위치 (Geocoded)] 레이어가 로드되었습니다."
                )
                return
            
            # === 분기 B: 기존 공간 검증 모드 ===
            crs_target = poly_layer.crs()
            
            # 좌표 변환기 구축
            transform_to_target = QgsCoordinateTransform(crs_wgs84, crs_target, QgsProject.instance())
            transform_to_wgs84 = QgsCoordinateTransform(crs_target, crs_wgs84, QgsProject.instance())
            
            # 분석 결과 보관용 리스트
            valid_points = []
            error_points = []
            
            for row in rows:
                if row["lon"] is None or row["lat"] is None:
                    row["is_inside"] = "False"
                    row["distance_m"] = -1.0
                    row["corrected_lon"] = ""
                    row["corrected_lat"] = ""
                    row["validation_note"] = "GEOC_FAILED"
                    continue
                    
                csv_id_val = str(row.get(csv_id_col, ""))
                pt_wgs84 = QgsPointXY(row["lon"], row["lat"])
                
                try:
                    # 1. 포인트 투영 변환
                    pt_target = transform_to_target.transform(pt_wgs84)
                    pt_geom = QgsGeometry.fromPointXY(pt_target)
                except Exception as e:
                    row["is_inside"] = "False"
                    row["distance_m"] = -1.0
                    row["corrected_lon"] = ""
                    row["corrected_lat"] = ""
                    row["validation_note"] = f"TRANSFORM_ERR_{str(e)[:10]}"
                    continue
                
                # 2. 매칭되는 Polygon 피처 검색
                expr = f'"{shp_id_col}" = \'{csv_id_val}\''
                request = QgsFeatureRequest().setFilterExpression(expr)
                features = list(poly_layer.getFeatures(request))
                
                if not features:
                    row["is_inside"] = "False"
                    row["distance_m"] = -1.0
                    row["corrected_lon"] = row["lon"]
                    row["corrected_lat"] = row["lat"]
                    row["validation_note"] = "POLYGON_NOT_FOUND"
                    error_points.append(row)
                    continue
                    
                poly_feat = features[0]
                poly_geom = poly_feat.geometry()
                
                if poly_geom.isNull():
                    row["is_inside"] = "False"
                    row["distance_m"] = -1.0
                    row["corrected_lon"] = row["lon"]
                    row["corrected_lat"] = row["lat"]
                    row["validation_note"] = "NULL_GEOMETRY"
                    error_points.append(row)
                    continue
                
                # 3. Point-in-Polygon 검사 및 보정
                is_inside = pt_geom.within(poly_geom)
                
                if is_inside:
                    row["is_inside"] = "True"
                    row["distance_m"] = 0.0
                    row["corrected_lon"] = row["lon"]
                    row["corrected_lat"] = row["lat"]
                    row["validation_note"] = "OK"
                    valid_points.append(row)
                else:
                    row["is_inside"] = "False"
                    dist = pt_geom.distance(poly_geom)
                    row["distance_m"] = dist
                    
                    rep_geom = poly_geom.pointOnSurface()
                    rep_pt_target = rep_geom.asPoint()
                    rep_pt_wgs84 = transform_to_wgs84.transform(rep_pt_target)
                    
                    row["corrected_lon"] = rep_pt_wgs84.x()
                    row["corrected_lat"] = rep_pt_wgs84.y()
                    row["validation_note"] = "OUTSIDE"
                    error_points.append(row)
            
            # 3. CSV 파일 출력 저장
            csv_out_path = f"{output_prefix}_results.csv"
            try:
                if rows:
                    fieldnames = list(rows[0].keys())
                    with open(csv_out_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writerows(rows)
                self.iface.messageBar().pushMessage("Address Matcher", f"검증 결과 CSV 저장 완료: {csv_out_path}", level=0, duration=4)
            except Exception as e:
                QMessageBox.critical(self.iface.mainWindow(), "에러", f"결과 CSV 저장 실패:\n{e}")
                
            # 4. QGIS 지도화면에 포인트 메모리 레이어 로드
            # 4-1. 정상 레이어 추가
            valid_layer = QgsVectorLayer("Point?crs=EPSG:4326", "정상 위치 (OK)", "memory")
            self.add_points_to_layer(valid_layer, valid_points, is_valid_layer=True)
            
            # 4-2. 오류 레이어 추가
            error_layer = QgsVectorLayer("Point?crs=EPSG:4326", "경계 이탈 및 보정점 (OUTSIDE)", "memory")
            self.add_points_to_layer(error_layer, error_points, is_valid_layer=False)
            
            # 5. 스타일링 및 렌더러 적용
            self.style_valid_layer(valid_layer)
            self.style_error_layer(error_layer)
            
            # 프로젝트에 레이어 로드
            QgsProject.instance().addMapLayers([valid_layer, error_layer])
            
            # 생성된 포인트 레이어 범위로 자동 줌인 (Zoom to Layer)
            canvas = self.iface.mapCanvas()
            if len(error_points) > 0 and error_layer.featureCount() > 0:
                canvas.setExtent(error_layer.extent())
            elif len(valid_points) > 0 and valid_layer.featureCount() > 0:
                canvas.setExtent(valid_layer.extent())
            canvas.refresh()
            
            QMessageBox.information(
                self.iface.mainWindow(), 
                "작업 완료", 
                f"분석이 성공적으로 완료되었습니다.\n\n"
                f"총 대상: {total_rows}건\n"
                f" - 정상: {len(valid_points)}건\n"
                f" - 경계 이탈(오류): {len(error_points)}건\n\n"
                f"QGIS 맵 캔버스에 [정상 위치] 및 [경계 이탈] 2개의 레이어가 로드되었습니다."
            )

    def add_points_to_layer(self, layer, points_data, is_valid_layer):
        """
        임시 메모리 레이어에 포인트 피처들과 속성을 기입합니다.
        """
        pr = layer.dataProvider()
        
        # 필드 정의
        pr.addAttributes([
            QgsField("site_id", QVariant.String),
            QgsField("address", QVariant.String),
            QgsField("is_inside", QVariant.String),
            QgsField("distance_m", QVariant.Double),
            QgsField("orig_lon", QVariant.Double),
            QgsField("orig_lat", QVariant.Double),
            QgsField("corr_lon", QVariant.Double),
            QgsField("corr_lat", QVariant.Double),
            QgsField("note", QVariant.String)
        ])
        layer.updateFields()
        
        features = []
        for row in points_data:
            feat = QgsFeature()
            feat.setFields(layer.fields())
            
            # 기하학적 점 생성
            if is_valid_layer:
                # 정상은 원래 좌표
                geom = QgsGeometry.fromPointXY(QgsPointXY(float(row["lon"]), float(row["lat"])))
            else:
                # 오류는 보정된 내부 좌표에 피처를 생성
                if row["corrected_lon"] != "":
                    geom = QgsGeometry.fromPointXY(QgsPointXY(float(row["corrected_lon"]), float(row["corrected_lat"])))
                else:
                    # 지오코딩 실패 등은 원래 좌표 또는 스킵
                    continue
                    
            feat.setGeometry(geom)
            feat.setAttributes([
                row.get("site_id", ""),
                row.get("address", ""),
                row.get("is_inside", ""),
                float(row.get("distance_m", 0.0)),
                float(row.get("lon", 0.0)) if row.get("lon") else 0.0,
                float(row.get("lat", 0.0)) if row.get("lat") else 0.0,
                float(row.get("corrected_lon", 0.0)) if row.get("corrected_lon") else 0.0,
                float(row.get("corrected_lat", 0.0)) if row.get("corrected_lat") else 0.0,
                row.get("validation_note", "")
            ])
            features.append(feat)
            
        pr.addFeatures(features)
        layer.updateExtents()

    def style_valid_layer(self, layer):
        """정상 데이터: 녹색 원형 심볼 적용"""
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        symbol.setColor(Qt.green)
        symbol.setSize(3.0)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def style_error_layer(self, layer):
        """오류 데이터: 빨간색 X자 마커 적용하여 즉각 구별하도록 함"""
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        # 심볼 모양을 X 마커로 설정
        symbol_layer = symbol.symbolLayer(0)
        if hasattr(symbol_layer, 'setShape'):
            symbol_layer.setShape(QgsSimpleMarkerSymbolLayerBase.Cross)
        symbol.setColor(Qt.red)
        symbol.setSize(4.0)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
