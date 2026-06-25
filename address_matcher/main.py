import os
import csv
import requests
import time
import re
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
            icon = QIcon()
        else:
            icon = QIcon(icon_path)
            
        self.action = QAction(
            icon, 
            "Address Matcher & Validator", 
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        
        self.iface.addVectorToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("Address Matcher & Validator", self.action)

    def unload(self):
        self.iface.removePluginVectorMenu("Address Matcher & Validator", self.action)
        self.iface.removeVectorToolBarIcon(self.action)

    def clean_address_text(self, address):
        """
        주소 끝에 붙는 불필요한 지적 수식어('외 X필지', '일원' 등)를 지우고 산 지번 공백을 맞추는 전처리 함수
        """
        if not address or not isinstance(address, str):
            return ""
        addr = address.strip()
        addr = re.sub(r"\([^)]*\)", "", addr)
        addr = re.sub(r"\[[^\]]*\]", "", addr)
        
        patterns = [
            r"\s*외\s*\d+\s*필지.*",
            r"\s*외\s*필지.*",
            r"\s*일원.*",
            r"\s*일대.*",
            r"\s*주변.*",
            r"\s*부근.*",
            r"\s*번지\s*일원.*",
            r"\s*번지.*"
        ]
        for pat in patterns:
            addr = re.sub(pat, "", addr)
            
        addr = re.sub(r"산\s*(\d+)", r"산 \1", addr)
        return re.sub(r"\s+", " ", addr).strip()

    def _request_geocode(self, url, headers, query_addr):
        """실제 HTTP 요청을 날리는 지오코딩 헬퍼 메서드"""
        params = {"query": query_addr.strip()}
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
        except Exception as e:
            return None, None, f"ERR_{str(e)[:10]}"

    def geocode_address(self, address, api_key):
        """
        지적도상 특이 지번 오류를 정정하기 위해 정규식 정제 및
        다단계 Fallback 지오코딩(정제주소 -> 본번지 -> 행정동 중심점)을 수행합니다.
        """
        if not address or address.strip() == "":
            return None, None, "EMPTY_ADDRESS"
            
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {api_key}"}
        
        cleaned = self.clean_address_text(address)
        lon, lat, status = self._request_geocode(url, headers, cleaned)
        if lon is not None:
            return lon, lat, status
            
        fallback_addr = None
        if re.search(r"(\s+\d+)-\d+$", cleaned):
            fallback_addr = re.sub(r"(\s+\d+)-\d+$", r"\1", cleaned)
        elif re.search(r"(\s+산\s*\d+)-\d+$", cleaned):
            fallback_addr = re.sub(r"(\s+산\s*\d+)-\d+$", r"\1", cleaned)
            
        if fallback_addr and fallback_addr != cleaned:
            lon, lat, status = self._request_geocode(url, headers, fallback_addr)
            if lon is not None:
                return lon, lat, "FALLBACK_MAIN_JIBUN"
                
        fallback_town = re.sub(r"(\s+산)?\s+\d+.*$", "", cleaned).strip()
        if fallback_town and fallback_town != cleaned:
            lon, lat, status = self._request_geocode(url, headers, fallback_town)
            if lon is not None:
                return lon, lat, "FALLBACK_TOWN"
                
        return None, None, "FAIL"

    def run(self):
        dlg = AddressMatcherDialog(self.iface.mainWindow())
        if dlg.exec_():
            values = dlg.get_values()
            
            # 폴리곤 대표점 생성 전용 모드 (CSV/지오코딩 없이 SHP -> Point 변환)
            if values.get("polygon_rep_point_mode"):
                self.run_polygon_representative_point(values)
                return
            
            csv_path = values["csv_path"]
            address_col = values["address_col"]
            validation_enabled = values["validation_enabled"]
            csv_id_col = values["csv_id_col"]
            poly_layer = values["layer"]
            shp_id_col = values["shp_id_col"]
            api_key = values["api_key"]
            output_prefix = values["output_prefix"]
            
            settings = QgsSettings()
            settings.setValue("AddressMatcher/csv_path", csv_path)
            settings.setValue("AddressMatcher/address_col", address_col)
            settings.setValue("AddressMatcher/validation_enabled", "true" if validation_enabled else "false")
            settings.setValue("AddressMatcher/csv_id_col", csv_id_col)
            settings.setValue("AddressMatcher/shp_id_col", shp_id_col)
            settings.setValue("AddressMatcher/api_key", api_key)
            settings.setValue("AddressMatcher/output_prefix", output_prefix)
            
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
            
            progress = QProgressDialog("주소 지오코딩을 수행하고 있습니다...", "취소", 0, total_rows, self.iface.mainWindow())
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            
            for idx, row in enumerate(rows):
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
                    QgsMessageLog.logMessage(
                        f"주소 지오코딩 실패 - 주소: {addr}, 결과상태: {status}",
                        "AddressMatcher",
                        Qgis.Warning
                    )
                
                progress.setLabelText(f"주소 지오코딩을 수행하고 있습니다... ({idx+1}/{total_rows})")
                progress.setValue(idx + 1)
                QCoreApplication.processEvents()
                time.sleep(0.05)
                
            progress.close()
            self.iface.messageBar().pushMessage("Address Matcher", f"지오코딩 완료: {success_count}/{total_rows} 성공", level=0, duration=3)
            
            crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            
            # === 분기 A: 단순 지오코딩 점 생성 모드 ===
            if not validation_enabled:
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
                            row.get(csv_id_col, ""),
                            row.get(address_col, ""),
                            row.get("geocode_status", ""),
                            float(row["lon"]),
                            float(row["lat"])
                        ])
                        features.append(feat)
                
                pr.addFeatures(features)
                geocoded_layer.updateExtents()
                
                symbol = QgsSymbol.defaultSymbol(geocoded_layer.geometryType())
                symbol.setColor(QColor("#3182CE"))
                symbol.setSize(3.5)
                geocoded_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
                
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
            
            # === 분기 B: 공간 검증 모드 ===
            crs_target = poly_layer.crs()
            transform_to_target = QgsCoordinateTransform(crs_wgs84, crs_target, QgsProject.instance())
            transform_to_wgs84 = QgsCoordinateTransform(crs_target, crs_wgs84, QgsProject.instance())
            
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
                    pt_target = transform_to_target.transform(pt_wgs84)
                    pt_geom = QgsGeometry.fromPointXY(pt_target)
                except Exception as e:
                    row["is_inside"] = "False"
                    row["distance_m"] = -1.0
                    row["corrected_lon"] = ""
                    row["corrected_lat"] = ""
                    row["validation_note"] = f"TRANSFORM_ERR_{str(e)[:10]}"
                    continue
                
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
                    
                    # pointOnSurface(): 초승달형/오목 폴리곤에서도 반드시 면 내부에 있는 점을 반환
                    rep_geom = poly_geom.pointOnSurface()
                    rep_pt_target = rep_geom.asPoint()
                    rep_pt_wgs84 = transform_to_wgs84.transform(rep_pt_target)
                    
                    row["corrected_lon"] = rep_pt_wgs84.x()
                    row["corrected_lat"] = rep_pt_wgs84.y()
                    row["validation_note"] = "OUTSIDE"
                    error_points.append(row)
            
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
                
            valid_layer = QgsVectorLayer("Point?crs=EPSG:4326", "정상 위치 (OK)", "memory")
            self.add_points_to_layer(valid_layer, valid_points, is_valid_layer=True)
            
            error_layer = QgsVectorLayer("Point?crs=EPSG:4326", "경계 이탈 및 보정점 (OUTSIDE)", "memory")
            self.add_points_to_layer(error_layer, error_points, is_valid_layer=False)
            
            self.style_valid_layer(valid_layer)
            self.style_error_layer(error_layer)
            
            QgsProject.instance().addMapLayers([valid_layer, error_layer])
            
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

    def run_polygon_representative_point(self, values):
        """
        Polygon SHP 레이어의 각 피처에 대해 pointOnSurface()로 대표점을 계산하여
        새 포인트 레이어로 출력합니다.

        핵심 알고리즘: QgsGeometry.pointOnSurface()
        - GEOS 라이브러리의 'Point On Surface' 알고리즘을 내부적으로 사용합니다.
        - 볼록/오목 구분 없이 항상 폴리곤 면 위에 위치하는 점을 보장합니다.
        - centroid(무게 중심)와 달리 초승달형·도넛형·ㄷ자형 등 오목 폴리곤에서
          외부로 빠져나가는 일이 없습니다.
        - 거대한 필지에서 뻗어나온 조각이 있어도, 그 조각 자체의 면 위에 점이 찍힙니다.
        """
        poly_layer = values.get("rep_point_layer")
        if poly_layer is None or not poly_layer.isValid():
            QMessageBox.warning(self.iface.mainWindow(), "입력 오류", "유효한 Polygon 레이어를 선택해 주세요.")
            return

        output_prefix = values.get("output_prefix", "")

        crs_source = poly_layer.crs()
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_to_wgs84 = QgsCoordinateTransform(crs_source, crs_wgs84, QgsProject.instance())

        # 출력 포인트 메모리 레이어 생성 (WGS84)
        out_layer = QgsVectorLayer("Point?crs=EPSG:4326", "폴리곤 대표점 (pointOnSurface)", "memory")
        pr = out_layer.dataProvider()

        # 원본 폴리곤 레이어의 모든 필드를 상속 + 대표점 좌표 필드 추가
        source_fields = poly_layer.fields()
        pr.addAttributes(source_fields.toList() + [
            QgsField("rep_lon", QVariant.Double),
            QgsField("rep_lat", QVariant.Double),
            QgsField("geom_type", QVariant.String),
        ])
        out_layer.updateFields()

        total = poly_layer.featureCount()
        progress = QProgressDialog(
            "폴리곤 대표점 계산 중...", "취소", 0, total, self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        added = 0
        skipped = 0

        for idx, poly_feat in enumerate(poly_layer.getFeatures()):
            if progress.wasCanceled():
                self.iface.messageBar().pushMessage(
                    "Address Matcher", "사용자에 의해 작업이 취소되었습니다.", level=1, duration=3
                )
                progress.close()
                return

            poly_geom = poly_feat.geometry()

            if poly_geom is None or poly_geom.isNull() or poly_geom.isEmpty():
                skipped += 1
                progress.setValue(idx + 1)
                QCoreApplication.processEvents()
                continue

            # 핵심: pointOnSurface() 호출
            # 초승달형·오목 폴리곤에서도 실제 면이 존재하는 곳 위에 점을 반환합니다.
            rep_geom_src = poly_geom.pointOnSurface()

            if rep_geom_src.isNull():
                skipped += 1
                progress.setValue(idx + 1)
                QCoreApplication.processEvents()
                continue

            rep_pt_src = rep_geom_src.asPoint()

            try:
                rep_pt_wgs84 = transform_to_wgs84.transform(rep_pt_src)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"대표점 좌표 변환 실패 (FID={poly_feat.id()}): {e}",
                    "AddressMatcher", Qgis.Warning
                )
                skipped += 1
                progress.setValue(idx + 1)
                QCoreApplication.processEvents()
                continue

            rep_geom_wgs84 = QgsGeometry.fromPointXY(rep_pt_wgs84)
            geom_type_str = "MultiPolygon" if poly_geom.isMultipart() else "Polygon"

            out_feat = QgsFeature()
            out_feat.setFields(out_layer.fields())
            out_feat.setGeometry(rep_geom_wgs84)

            attrs = poly_feat.attributes() + [
                rep_pt_wgs84.x(),
                rep_pt_wgs84.y(),
                geom_type_str,
            ]
            out_feat.setAttributes(attrs)
            pr.addFeatures([out_feat])
            added += 1

            progress.setLabelText(f"폴리곤 대표점 계산 중... ({idx+1}/{total})")
            progress.setValue(idx + 1)
            QCoreApplication.processEvents()

        progress.close()
        out_layer.updateExtents()

        # 스타일링: 보라색 다이아몬드 마커
        symbol = QgsSymbol.defaultSymbol(out_layer.geometryType())
        symbol_layer_obj = symbol.symbolLayer(0)
        if hasattr(symbol_layer_obj, "setShape"):
            symbol_layer_obj.setShape(QgsSimpleMarkerSymbolLayerBase.Diamond)
        symbol.setColor(QColor("#805AD5"))
        symbol.setSize(4.5)
        out_layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        QgsProject.instance().addMapLayer(out_layer)

        canvas = self.iface.mapCanvas()
        if out_layer.featureCount() > 0:
            canvas.setExtent(out_layer.extent())
            canvas.refresh()

        # 결과 CSV 저장 (선택)
        if output_prefix:
            csv_out_path = f"{output_prefix}_rep_points.csv"
            try:
                fieldnames = [f.name() for f in out_layer.fields()]
                with open(csv_out_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for feat in out_layer.getFeatures():
                        row = dict(zip(fieldnames, feat.attributes()))
                        writer.writerow(row)
                self.iface.messageBar().pushMessage(
                    "Address Matcher", f"대표점 CSV 저장: {csv_out_path}", level=0, duration=4
                )
            except Exception as e:
                QgsMessageLog.logMessage(f"대표점 CSV 저장 실패: {e}", "AddressMatcher", Qgis.Warning)

        QMessageBox.information(
            self.iface.mainWindow(),
            "작업 완료",
            f"폴리곤 대표점 생성이 완료되었습니다.\n\n"
            f"총 폴리곤: {total}건\n"
            f" - 대표점 생성 성공: {added}건\n"
            f" - 건너뜀(빈 지오메트리 등): {skipped}건\n\n"
            f"[폴리곤 대표점 (pointOnSurface)] 레이어가 QGIS에 로드되었습니다.\n\n"
            f"※ 초승달형, 오목형 폴리곤도 반드시 실제 면 안에 점이 찍힙니다."
        )

    def add_points_to_layer(self, layer, points_data, is_valid_layer):
        """임시 메모리 레이어에 포인트 피처들과 속성을 기입합니다."""
        pr = layer.dataProvider()
        
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
            
            if is_valid_layer:
                geom = QgsGeometry.fromPointXY(QgsPointXY(float(row["lon"]), float(row["lat"])))
            else:
                if row["corrected_lon"] != "":
                    geom = QgsGeometry.fromPointXY(QgsPointXY(float(row["corrected_lon"]), float(row["corrected_lat"])))
                else:
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
        symbol_layer = symbol.symbolLayer(0)
        if hasattr(symbol_layer, 'setShape'):
            symbol_layer.setShape(QgsSimpleMarkerSymbolLayerBase.Cross)
        symbol.setColor(Qt.red)
        symbol.setSize(4.0)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
