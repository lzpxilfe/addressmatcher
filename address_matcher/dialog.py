import os
import csv
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QFileDialog, 
    QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QWidget, QFrame, QCheckBox, QComboBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerType, QgsMapLayerProxyModel, QgsSettings

class AddressMatcherDialog(QDialog):
    def __init__(self, parent=None):
        super(AddressMatcherDialog, self).__init__(parent)
        self.setWindowTitle("Address Matcher & Validator")
        self.resize(520, 520)
        
        # QgsSettings 불러오기
        self.settings = QgsSettings()
        
        # 메인 세련된 스타일시트 적용
        self.setStyleSheet("""
            QDialog {
                background-color: #F7FAFC;
            }
            QLabel {
                font-family: "Segoe UI", "Malgun Gothic", sans-serif;
                color: #2D3748;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E0;
                border-radius: 5px;
                padding: 6px 10px;
                color: #2D3748;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #3182CE;
                background-color: #F7FAFC;
            }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E0;
                border-radius: 5px;
                padding: 5px 10px;
                color: #2D3748;
                font-size: 12px;
                min-height: 28px;
            }
            QComboBox:focus {
                border: 1px solid #3182CE;
            }
            QgsMapLayerComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E0;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 12px;
                min-height: 28px;
            }
            QgsMapLayerComboBox:focus {
                border: 1px solid #3182CE;
            }
            QPushButton {
                background-color: #EDF2F7;
                border: 1px solid #CBD5E0;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
                color: #4A5568;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
                border: 1px solid #A0AEC0;
            }
            QCheckBox {
                spacing: 8px;
                font-weight: bold;
                color: #2D3748;
            }
        """)
        
        # 메인 레이아웃 (여백 없음)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. 상단 그라디언트 헤더 배너 패널
        self.header_panel = QFrame()
        self.header_panel.setObjectName("HeaderPanel")
        self.header_panel.setFixedHeight(90)
        self.header_panel.setStyleSheet("""
            QFrame#HeaderPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1A365D, stop:1 #2B6CB0);
                border-bottom: 2px solid #2B6CB0;
            }
        """)
        
        header_layout = QVBoxLayout(self.header_panel)
        header_layout.setContentsMargins(20, 15, 20, 15)
        header_layout.setSpacing(4)
        
        title_label = QLabel("Address Matcher & Validator")
        title_font = QFont("Segoe UI", 16, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #FFFFFF;")
        
        subtitle_label = QLabel("한국 주소 CSV 지오코딩 및 유적 Polygon 경계 이탈 검증/자동 보정 도구")
        subtitle_font = QFont("Segoe UI", 9)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet("color: #E2E8F0;")
        
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        
        self.main_layout.addWidget(self.header_panel)
        
        # 2. 메인 폼 컨텐츠 패널
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(24, 18, 24, 18)
        self.content_layout.setSpacing(14)
        
        self.form_layout = QFormLayout()
        self.form_layout.setVerticalSpacing(10)
        self.form_layout.setHorizontalSpacing(15)
        
        # 2-1. CSV 파일 선택
        self.csv_layout = QHBoxLayout()
        self.csv_layout.setSpacing(6)
        self.csv_path_edit = QLineEdit()
        self.csv_path_edit.setPlaceholderText("검증할 주소 CSV 파일을 선택하세요.")
        self.csv_path_edit.textChanged.connect(self.on_csv_path_changed)
        
        self.csv_browse_btn = QPushButton("찾아보기")
        self.csv_browse_btn.clicked.connect(self.browse_csv)
        self.csv_layout.addWidget(self.csv_path_edit)
        self.csv_layout.addWidget(self.csv_browse_btn)
        
        self.form_layout.addRow(self.create_label("주소 CSV 파일:"), self.csv_layout)
        
        # 2-2. 주소 컬럼명 (QLineEdit -> QComboBox로 변경)
        self.address_col_combo = QComboBox()
        self.address_col_combo.setEditable(True)
        self.address_col_combo.setPlaceholderText("CSV를 로드하면 열 목록이 표시됩니다.")
        self.form_layout.addRow(self.create_label("주소 컬럼명 (CSV):"), self.address_col_combo)
        
        # 구분선
        self.line = QFrame()
        self.line.setFrameShape(QFrame.HLine)
        self.line.setFrameShadow(QFrame.Sunken)
        self.line.setStyleSheet("background-color: #E2E8F0; max-height: 1px; margin: 5px 0;")
        self.form_layout.addRow(self.line)
        
        # 2-3. 공간 경계 검증 체크박스 추가
        self.validation_checkbox = QCheckBox("유적 경계 검증 및 보정 수행 (Polygon 대조)")
        saved_val_checked = self.settings.value("AddressMatcher/validation_enabled", "true") == "true"
        self.validation_checkbox.setChecked(saved_val_checked)
        self.validation_checkbox.toggled.connect(self.toggle_validation_fields)
        self.form_layout.addRow("", self.validation_checkbox)
        
        # 2-4. CSV 매칭 ID 컬럼명 (QComboBox)
        self.csv_id_col_combo = QComboBox()
        self.csv_id_col_combo.setEditable(True)
        self.csv_id_col_combo.setPlaceholderText("CSV를 로드하면 열 목록이 표시됩니다.")
        self.form_layout.addRow(self.create_label("매칭 ID 컬럼명 (CSV):", "csv_id"), self.csv_id_col_combo)
        
        # 2-5. Polygon 레이어 선택
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.form_layout.addRow(self.create_label("비교 Polygon 레이어:", "layer"), self.layer_combo)
        
        # 2-6. Polygon ID 필드명
        saved_shp_id_col = self.settings.value("AddressMatcher/shp_id_col", "id")
        self.shp_id_col_edit = QLineEdit(saved_shp_id_col)
        self.shp_id_col_edit.setPlaceholderText("예: id, SITE_CODE 등")
        self.form_layout.addRow(self.create_label("매칭 ID 필드명 (SHP):", "shp_id"), self.shp_id_col_edit)
        
        # 구분선 2
        self.line2 = QFrame()
        self.line2.setFrameShape(QFrame.HLine)
        self.line2.setFrameShadow(QFrame.Sunken)
        self.line2.setStyleSheet("background-color: #E2E8F0; max-height: 1px; margin: 5px 0;")
        self.form_layout.addRow(self.line2)
        
        # 2-7. Kakao API Key
        saved_api_key = self.settings.value("AddressMatcher/api_key", "")
        if not saved_api_key:
            saved_api_key = "965ffae72ca50570426f717a4c282e08"
        self.api_key_edit = QLineEdit(saved_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.form_layout.addRow(self.create_label("Kakao REST API Key:"), self.api_key_edit)
        
        # 2-8. 출력 파일 경로 접두사
        self.output_layout = QHBoxLayout()
        self.output_layout.setSpacing(6)
        self.output_edit = QLineEdit()
        self.output_browse_btn = QPushButton("저장위치")
        self.output_browse_btn.clicked.connect(self.browse_output)
        self.output_layout.addWidget(self.output_edit)
        self.output_layout.addWidget(self.output_browse_btn)
        self.form_layout.addRow(self.create_label("출력 경로 prefix:"), self.output_layout)
        
        self.content_layout.addLayout(self.form_layout)
        
        # 3. 하단 세련된 버튼 영역
        self.button_layout = QHBoxLayout()
        self.button_layout.setContentsMargins(0, 5, 0, 0)
        self.button_layout.setSpacing(12)
        
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #E2E8F0;
                border: none;
                border-radius: 6px;
                color: #4A5568;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #CBD5E0;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.ok_btn = QPushButton("분석 및 보정 시작")
        self.ok_btn.setFixedHeight(36)
        self.ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182CE;
                border: none;
                border-radius: 6px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2B6CB0;
            }
            QPushButton:pressed {
                background-color: #2C5282;
            }
        """)
        self.ok_btn.clicked.connect(self.validate_and_accept)
        
        self.button_layout.addWidget(self.cancel_btn, 1)
        self.button_layout.addWidget(self.ok_btn, 2)
        
        self.content_layout.addLayout(self.button_layout)
        self.main_layout.addWidget(self.content_widget)
        
        # 초기 출력 경로 기본 설정
        default_dir = os.path.expanduser("~")
        saved_output_prefix = self.settings.value("AddressMatcher/output_prefix", os.path.join(default_dir, "validation_output"))
        self.output_edit.setText(saved_output_prefix)
        
        # CSV 로드 초기값 처리
        saved_csv = self.settings.value("AddressMatcher/csv_path", "")
        if saved_csv and os.path.exists(saved_csv):
            self.csv_path_edit.setText(saved_csv)
            
        # 첫 화면에 필드 활성화 상태 반영
        self.toggle_validation_fields(self.validation_checkbox.isChecked())

    def create_label(self, text, object_name=None):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; color: #4A5568; font-size: 11px;")
        if object_name:
            label.setObjectName(f"lbl_{object_name}")
        return label

    def toggle_validation_fields(self, enabled):
        """체크박스 상태에 따라 공간 검증 관련 필드를 켜거나 끕니다."""
        # QFormLayout에서 라벨 및 입력 컴포넌트들을 비활성화 처리
        self.csv_id_col_combo.setEnabled(enabled)
        self.layer_combo.setEnabled(enabled)
        self.shp_id_col_edit.setEnabled(enabled)
        
        # 글씨 색상 조정 피드백
        opacity_style = "color: #2D3748;" if enabled else "color: #A0AEC0;"
        lbl_csv_id = self.findChild(QLabel, "lbl_csv_id")
        lbl_layer = self.findChild(QLabel, "lbl_layer")
        lbl_shp_id = self.findChild(QLabel, "lbl_shp_id")
        
        for lbl in [lbl_csv_id, lbl_layer, lbl_shp_id]:
            if lbl:
                lbl.setStyleSheet(f"font-weight: bold; font-size: 11px; {opacity_style}")

    def on_csv_path_changed(self, file_path):
        """CSV 경로가 바뀌면 파일을 신속하게 파싱하여 콤보박스에 컬럼을 주입합니다."""
        if not file_path or not os.path.exists(file_path):
            self.address_col_combo.clear()
            self.csv_id_col_combo.clear()
            return
            
        headers = self.read_csv_headers(file_path)
        if not headers:
            return
            
        # 콤보박스 아이템 주입
        self.address_col_combo.clear()
        self.address_col_combo.addItems(headers)
        self.csv_id_col_combo.clear()
        self.csv_id_col_combo.addItems(headers)
        
        # 1. 주소 컬럼명 똑똑하게 매칭하여 기본값 설정
        saved_addr_col = self.settings.value("AddressMatcher/address_col", "address")
        addr_match_idx = self.find_best_header_match(headers, saved_addr_col, ["주소", "소재지", "address", "road_addr", "지번주소", "도로명"])
        if addr_match_idx >= 0:
            self.address_col_combo.setCurrentIndex(addr_match_idx)
            
        # 2. ID 컬럼명 똑똑하게 매칭하여 기본값 설정
        saved_csv_id_col = self.settings.value("AddressMatcher/csv_id_col", "site_id")
        id_match_idx = self.find_best_header_match(headers, saved_csv_id_col, ["site_id", "id", "유적id", "고유번호", "유적번호", "번호", "code"])
        if id_match_idx >= 0:
            self.csv_id_col_combo.setCurrentIndex(id_match_idx)

    def read_csv_headers(self, csv_path):
        """인코딩 예외 처리를 동반하여 CSV의 헤더를 안전하게 한 줄만 읽습니다."""
        encodings = ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']
        for enc in encodings:
            try:
                with open(csv_path, 'r', encoding=enc) as f:
                    reader = csv.reader(f)
                    headers = next(reader)
                    # 빈 열 이름 제거 및 공백 트림
                    headers = [h.strip() for h in headers if h and h.strip() != ""]
                    if headers:
                        return headers
            except Exception:
                continue
        return None

    def find_best_header_match(self, headers, saved_val, candidates):
        """저장된 값이 있으면 최우선으로 매핑하고, 없으면 주소/ID 후보 키워드로 유사 검색합니다."""
        # 1단계: 저장된 설정값과 완벽히 일치하는 헤더
        if saved_val in headers:
            return headers.index(saved_val)
            
        # 2단계: 후보 키워드 매칭
        for cand in candidates:
            for idx, h in enumerate(headers):
                if cand.lower() in h.lower():
                    return idx
        return 0 if headers else -1

    def browse_csv(self):
        filename, _ = QFileDialog.getOpenFileName(self, "주소 CSV 파일 선택", self.csv_path_edit.text(), "CSV Files (*.csv)")
        if filename:
            self.csv_path_edit.setText(filename)
            base_dir = os.path.dirname(filename)
            base_name = os.path.splitext(os.path.basename(filename))[0]
            self.output_edit.setText(os.path.join(base_dir, f"{base_name}_validated"))

    def browse_output(self):
        filename, _ = QFileDialog.getSaveFileName(self, "출력 파일 경로 지정 (확장자 제외)", self.output_edit.text(), "All Files (*)")
        if filename:
            self.output_edit.setText(filename)

    def validate_and_accept(self):
        if not self.csv_path_edit.text() or not os.path.exists(self.csv_path_edit.text()):
            QMessageBox.warning(self, "입력 오류", "유효한 주소 CSV 파일을 선택해 주세요.")
            return
        if not self.address_col_combo.currentText():
            QMessageBox.warning(self, "입력 오류", "주소 컬럼명을 지정해 주세요.")
            return
        if not self.api_key_edit.text():
            QMessageBox.warning(self, "입력 오류", "카카오 API REST Key를 입력해 주세요.")
            return
        if not self.output_edit.text():
            QMessageBox.warning(self, "입력 오류", "결과 출력 경로 prefix를 지정해 주세요.")
            return
            
        # 경계 검증 모드가 켜진 경우에만 폴리곤 관련 항목 필수값 체크
        if self.validation_checkbox.isChecked():
            if not self.csv_id_col_combo.currentText():
                QMessageBox.warning(self, "입력 오류", "CSV ID 컬럼명을 지정해 주세요.")
                return
            if not self.layer_combo.currentLayer():
                QMessageBox.warning(self, "입력 오류", "비교 대상이 되는 QGIS Polygon 레이어를 선택해 주세요.")
                return
            if not self.shp_id_col_edit.text():
                QMessageBox.warning(self, "입력 오류", "SHP ID 필드명을 입력해 주세요.")
                return
                
        self.accept()

    def get_values(self):
        return {
            "csv_path": self.csv_path_edit.text(),
            "address_col": self.address_col_combo.currentText(),
            "validation_enabled": self.validation_checkbox.isChecked(),
            "csv_id_col": self.csv_id_col_combo.currentText() if self.validation_checkbox.isChecked() else "",
            "layer": self.layer_combo.currentLayer() if self.validation_checkbox.isChecked() else None,
            "shp_id_col": self.shp_id_col_edit.text() if self.validation_checkbox.isChecked() else "",
            "api_key": self.api_key_edit.text(),
            "output_prefix": self.output_edit.text()
        }
