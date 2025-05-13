import sys
import serial
import time
import threading
import os
import cv2
import numpy as np
import requests
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFrame, QComboBox, QSpinBox, QMessageBox, QDialog, QFormLayout, QTimeEdit,
    QFileDialog, QRadioButton, QTextEdit, QGroupBox, QDoubleSpinBox, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPixmap, QImage, QTextOption, QIcon
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
def get_resource_path(relative_path):
    """Получает абсолютный путь к ресурсу, работает для разработки и PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "fitodomik_config.json")
ICON_FILE = get_resource_path("67fb70c98d5b2.ico")
LOCAL_PATH = os.path.join(os.path.expanduser("~"), "FitoDomik_photos")
CAMERA_INDEX = 0
SAVE_LOCAL = True
if SAVE_LOCAL and not os.path.exists(LOCAL_PATH):
    os.makedirs(LOCAL_PATH)
class ArduinoReader(QThread):
    data_received = pyqtSignal(dict)
    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True
    def run(self):
        buffer = ""
        while self.running:
            try:
                if self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                    data = {}
                    if "Humidity" in line and "Temperature" in line:
                        try:
                            parts = line.split("Temperature:")
                            humidity_part = parts[0].strip()
                            temperature_part = parts[1].strip()
                            hum_value = humidity_part.split(":")[1].replace("%", "").strip()
                            data['humidity'] = float(hum_value)
                            temp_value = temperature_part.replace("°C", "").strip()
                            data['temperature'] = float(temp_value)
                        except Exception as e:
                            print(f"DEBUG: Ошибка при разборе строки с температурой и влажностью: {e}, строка: {line}")
                    elif "Temperature" in line and "Humidity" not in line:
                        try:
                            temp_str = line.split(":")[1].replace("C", "").replace("°", "").strip()
                            data['temperature'] = float(temp_str)
                        except Exception as e:
                            print(f"DEBUG: Ошибка при разборе температуры: {e}, строка: {line}")
                    elif "Humidity" in line and "Soil" not in line and "Temperature" not in line:
                        try:
                            hum_str = line.split(":")[1].replace("%", "").strip()
                            data['humidity'] = float(hum_str)
                        except Exception as e:
                            print(f"DEBUG: Ошибка при разборе влажности: {e}, строка: {line}")
                    elif "Soil moisture" in line:
                        try:
                            soil_str = line.split(":")[1].replace("%", "").strip()
                            data['soil'] = float(soil_str)
                        except Exception as e:
                            print(f"DEBUG: Ошибка при разборе влажности почвы: {e}, строка: {line}")
                    if data:
                        self.data_received.emit(data)
                self.msleep(200)
            except Exception as e:
                self.msleep(500)
    def stop(self):
        self.running = False
        self.wait()
class PlantPhotoThread(QThread):
    photo_taken_signal = pyqtSignal(np.ndarray, np.ndarray, dict)  
    log_signal = pyqtSignal(str)
    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.original_image = None
        self.detection_image = None
        self.color_percentages = {}
        self.detected_diseases = []
        self.detected_pests = []
    def run(self):
        try:
            self.log_signal.emit("📸 Делаем фото с камеры...")
            frame = self.take_photo()
            if frame is None:
                self.log_signal.emit("❌ Не удалось получить изображение с камеры")
                return
            self.original_image = frame.copy()
            height, width = frame.shape[:2]
            self.log_signal.emit("🔍 Анализируем изображение растения...")
            self.detect_plant(height, width)
            analysis = self.analyze_health()
            report_text = f"АНАЛИЗ СОСТОЯНИЯ РАСТЕНИЯ\nДата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nСОСТОЯНИЕ: {analysis['состояние']}\n\nРАСПРЕДЕЛЕНИЕ ЦВЕТОВ:\n{analysis['распределение цветов']}\n\nДЕТАЛИ АНАЛИЗА:\n{analysis['детали']}\n\nРЕКОМЕНДАЦИИ:\n{analysis['рекомендации']}\n"
            if SAVE_LOCAL:
                self.save_photo_locally(report_text)
                self.log_signal.emit("✅ Фото сохранено локально")
            self.photo_taken_signal.emit(self.original_image, self.detection_image, analysis)
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при выполнении фотографирования: {str(e)}")
    def take_photo(self):
        """Сделать фото с камеры"""
        try:
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                self.log_signal.emit("❌ Ошибка подключения камеры")
                return None
            ret, frame = cap.read()
            cap.release()
            if not ret:
                self.log_signal.emit("❌ Ошибка получения изображения с камеры")
                return None
            return frame
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при фотографировании: {str(e)}")
            return None
    def detect_plant(self, height, width):
        """Обнаружение растения на изображении"""
        LEAF_COLORS = {
            "healthy_green": {"lower": np.array([35, 30, 30]), "upper": np.array([85, 255, 255]), "name": "здоровый зеленый"},
            "yellow": {"lower": np.array([20, 30, 30]), "upper": np.array([35, 255, 255]), "name": "желтый"},
            "brown": {"lower": np.array([10, 30, 10]), "upper": np.array([20, 255, 255]), "name": "коричневый"},
            "light_green": {"lower": np.array([35, 30, 30]), "upper": np.array([85, 100, 255]), "name": "светло-зеленый"}
        }
        try:
            self.height = height
            self.width = width
            hsv = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2HSV)
            self.detection_image = self.original_image.copy()
            total_mask = np.zeros((self.height, self.width), dtype=np.uint8)
            for color_name, color_range in LEAF_COLORS.items():
                mask = cv2.inRange(hsv, color_range["lower"], color_range["upper"])
                kernel = np.ones((3,3), np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                total_mask = cv2.bitwise_or(total_mask, mask)
            contours, _ = cv2.findContours(total_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            filtered_contours = []
            for contour in contours:
                if cv2.contourArea(contour) > 100:
                    filtered_contours.append(contour)
            cv2.drawContours(self.detection_image, filtered_contours, -1, (0, 255, 0), 2)
            self.plant_mask = np.zeros_like(total_mask)
            cv2.drawContours(self.plant_mask, filtered_contours, -1, 255, -1)
            plant_pixels = np.count_nonzero(self.plant_mask)
            if plant_pixels > 0:
                for color_name, color_range in LEAF_COLORS.items():
                    mask = cv2.inRange(hsv, color_range["lower"], color_range["upper"])
                    color_pixels = cv2.countNonZero(cv2.bitwise_and(mask, self.plant_mask))
                    self.color_percentages[color_name] = (color_pixels / plant_pixels) * 100
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при обнаружении растения: {str(e)}")
    def analyze_health(self):
        """Анализ здоровья растения"""
        DISEASES_DB = {
            "yellow_leaves": {"name": "Хлороз", "description": "Пожелтение листьев", "causes": ["Недостаток железа", "Переувлажнение", "Недостаток азота"], "solutions": ["Добавить железосодержащие удобрения", "Уменьшить полив", "Внести азотные удобрения"]},
            "brown_spots": {"name": "Грибковое заболевание", "description": "Коричневые пятна на листьях", "causes": ["Грибковая инфекция", "Избыточная влажность", "Плохая вентиляция"], "solutions": ["Обработать фунгицидами", "Улучшить вентиляцию", "Удалить пораженные листья"]}
        }
        PESTS_DB = {
            "aphids": {"name": "Тля", "description": "Мелкие насекомые на листьях и стеблях", "damage": "Высасывают сок из растения, вызывают деформацию листьев", "solutions": ["Обработать инсектицидами", "Использовать мыльный раствор", "Привлечь естественных хищников"]},
            "thrips": {"name": "Трипсы", "description": "Мелкие удлиненные насекомые", "damage": "Повреждают листья и цветы, переносят вирусы", "solutions": ["Обработать инсектицидами", "Использовать синие липкие ловушки", "Удалять сорняки"]}
        }
        try:
            self.detected_diseases = []
            self.detected_pests = []
            if self.color_percentages.get("yellow", 0) > 10:
                self.detected_diseases.append(DISEASES_DB["yellow_leaves"])
            if self.color_percentages.get("brown", 0) > 5:
                self.detected_diseases.append(DISEASES_DB["brown_spots"])
            if self.color_percentages.get("brown", 0) > 5:
                if self.color_percentages.get("yellow", 0) > 15:
                    self.detected_pests.append(PESTS_DB["aphids"])
                elif self.color_percentages.get("brown", 0) > 10:
                    self.detected_pests.append(PESTS_DB["thrips"])
            status = "нормальное"
            details = []
            recommendations = []
            if self.color_percentages.get("yellow", 0) > 10:
                status = "требует внимания"
                details.append("Обнаружено значительное пожелтение листьев")
                recommendations.append("Проверьте режим полива")
                recommendations.append("Проверьте уровень освещенности")
            if self.color_percentages.get("brown", 0) > 5:
                status = "требует внимания"
                details.append("Обнаружены коричневые участки на листьях")
                recommendations.append("Проверьте на наличие заболеваний")
                recommendations.append("Удалите поврежденные листья")
            for disease in self.detected_diseases:
                details.append(f"{disease['name']}: {disease['description']}")
                recommendations.extend(disease['solutions'])
            for pest in self.detected_pests:
                details.append(f"{pest['name']}: {pest['description']}")
                recommendations.extend(pest['solutions'])
            if not details:
                recommendations.append("Поддерживайте текущий режим ухода")
            LEAF_COLORS = {
                "healthy_green": {"name": "здоровый зеленый"},
                "yellow": {"name": "желтый"},
                "brown": {"name": "коричневый"},
                "light_green": {"name": "светло-зеленый"}
            }
            return {
                "состояние": status,
                "распределение цветов": "; ".join([f"{LEAF_COLORS[k]['name']}: {v:.1f}%" for k, v in self.color_percentages.items() if v > 1]),
                "детали": "; ".join(details) if details else "отклонений не выявлено",
                "рекомендации": "; ".join(recommendations)
            }
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при анализе здоровья растения: {str(e)}")
            return {
                "состояние": "ошибка анализа",
                "распределение цветов": "",
                "детали": f"Ошибка при анализе: {str(e)}",
                "рекомендации": "Попробуйте повторить анализ"
            }
    def save_photo_locally(self, text="Анализ состояния растений"):
        """Сохранить фото локально"""
        if self.original_image is None or self.detection_image is None:
            self.log_signal.emit("❌ Нет изображений для сохранения")
            return False
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            orig_filename = os.path.join(LOCAL_PATH, f"greenhouse_photo_{timestamp}.jpg")
            analysis_filename = os.path.join(LOCAL_PATH, f"greenhouse_analysis_{timestamp}.jpg")
            report_filename = os.path.join(LOCAL_PATH, f"greenhouse_report_{timestamp}.txt")
            cv2.imwrite(orig_filename, self.original_image)
            cv2.imwrite(analysis_filename, self.detection_image)
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при сохранении файлов: {str(e)}")
            return False
class GraphWidget(QWidget):
    def __init__(self, title, color, label="", y_min=None, y_max=None, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(6, 5), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor('#232323')
        self.ax.set_facecolor('#2c2c2c')
        self.ax.grid(True, color='#444444', linestyle='--', linewidth=0.5)
        self.ax.spines['bottom'].set_color('#555555')
        self.ax.spines['top'].set_color('#555555') 
        self.ax.spines['right'].set_color('#555555')
        self.ax.spines['left'].set_color('#555555')
        self.ax.set_title(title, color='#ffffff', fontsize=14, fontweight='bold', pad=15)
        self.ax.tick_params(axis='x', colors='#aaaaaa', labelsize=9)
        self.ax.tick_params(axis='y', colors='#aaaaaa', labelsize=9)
        self.line_color = color
        self.label = label
        self.y_min = y_min
        self.y_max = y_max
        if y_min is not None and y_max is not None:
            self.ax.set_ylim(y_min, y_max)
        if label:
            self.ax.set_ylabel(label, color='#aaaaaa', fontsize=10)
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.data = []
        self.times = []
        self.max_points = 60
    def update_data(self, value):
        current_time = datetime.now()
        self.data.append(value)
        self.times.append(current_time)
        if len(self.data) > self.max_points:
            self.data.pop(0)
            self.times.pop(0)
        self.ax.clear()
        self.ax.plot(self.times, self.data, color=self.line_color, linewidth=2, 
                    marker='o', markersize=4, markerfacecolor=self.line_color)
        self.ax.set_facecolor('#2c2c2c')
        self.ax.grid(True, color='#444444', linestyle='--', linewidth=0.5)
        self.ax.spines['bottom'].set_color('#555555')
        self.ax.spines['top'].set_color('#555555') 
        self.ax.spines['right'].set_color('#555555')
        self.ax.spines['left'].set_color('#555555')
        if self.label:
            self.ax.set_title(self.ax.get_title(), color='#ffffff', fontsize=14, fontweight='bold', pad=15)
            self.ax.set_ylabel(self.label, color='#aaaaaa', fontsize=10)
        if self.y_min is not None and self.y_max is not None:
            self.ax.set_ylim(self.y_min, self.y_max)
        self.ax.tick_params(axis='x', colors='#aaaaaa', labelsize=9)
        self.ax.tick_params(axis='y', colors='#aaaaaa', labelsize=9)
        self.figure.autofmt_xdate(rotation=45)
        self.figure.tight_layout(pad=3.0)
        self.canvas.draw()
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ФитоДомик')
        app_icon = QIcon(ICON_FILE)
        self.setWindowIcon(app_icon)
        self.setStyleSheet("""
            QMainWindow { background-color: #181818; }
            QLabel { color: #fff; font-size: 15px; }
            QPushButton {
                background-color: #232323; color: #fff; border: none;
                padding: 14px 0; border-radius: 10px; font-size: 17px; font-weight: 500;
            }
            QPushButton:hover { background-color: #2e2e2e; }
            QComboBox, QSpinBox, QTimeEdit, QLineEdit {
                background-color: #232323; color: #fff; border: 1px solid #333; border-radius: 6px;
                font-size: 15px; padding: 4px 8px;
            }
            QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {
                background-color: #333; border: none; border-radius: 4px;
            }
            QTabWidget::pane { border: none; background: #181818; }
            QTabBar::tab { background: #232323; color: #aaa; padding: 10px 30px; border-radius: 8px; }
            QTabBar::tab:selected { background: #4CAF50; color: #fff; }
            QDialog { background-color: #181818; }
            QFormLayout { color: #fff; }
        """)
        self.serial_port = None
        self.arduino_thread = None
        self.photo_thread = None
        self.last_temp = 0
        self.last_hum = 0
        self.last_soil = 0
        self.camera_index = CAMERA_INDEX
        self.photo_mode = "Раз в день"
        self.photo_time1 = "13:00"
        self.photo_time2 = "16:00"
        self.photo_thread_active = False
        self.next_photo_time = 0
        self.setup_ui()
        self.load_settings()
        QTimer.singleShot(1000, self.auto_connect_arduino)
    def setup_ui(self):
        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        monitor_layout.setSpacing(15)
        cards = QHBoxLayout()
        self.temp_card = self.create_card('🌡️ Температура', '-- °C', '#ff5555')
        self.hum_card = self.create_card('💧 Влажность', '-- %', '#5555ff')
        self.soil_card = self.create_card('🌱 Почва', '-- %', '#55aa55')
        cards.addWidget(self.temp_card)
        cards.addWidget(self.hum_card)
        cards.addWidget(self.soil_card)
        monitor_layout.addLayout(cards)
        temp_container = QGroupBox("Температура")
        temp_container.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #ff5555;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        temp_layout = QVBoxLayout(temp_container)
        self.temp_graph = GraphWidget('', '#ff5555', 'Температура (°C)', 10, 40)
        temp_layout.addWidget(self.temp_graph)
        hum_container = QGroupBox("Влажность воздуха")
        hum_container.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #5555ff;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        hum_layout = QVBoxLayout(hum_container)
        self.hum_graph = GraphWidget('', '#5555ff', 'Влажность (%)', 0, 70)
        hum_layout.addWidget(self.hum_graph)
        soil_container = QGroupBox("Влажность почвы")
        soil_container.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #55aa55;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        soil_layout = QVBoxLayout(soil_container)
        self.soil_graph = GraphWidget('', '#55aa55', 'Почва (%)', 0, 100)
        soil_layout.addWidget(self.soil_graph)
        monitor_layout.addWidget(temp_container)
        monitor_layout.addWidget(hum_container)
        monitor_layout.addWidget(soil_container)
        monitor_layout.addStretch(1)
        tabs.addTab(monitor_tab, 'Мониторинг')
        plant_tab = QWidget()
        plant_layout = QVBoxLayout(plant_tab)
        image_group = QGroupBox("Состояние растения")
        image_group.setStyleSheet("QGroupBox { font-size: 18px; font-weight: bold; }")
        image_layout = QHBoxLayout()
        orig_image_layout = QVBoxLayout()
        orig_image_label = QLabel("Оригинальное изображение:")
        orig_image_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        orig_image_layout.addWidget(orig_image_label)
        self.image_label_orig = QLabel("Нет изображения")
        self.image_label_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label_orig.setMinimumHeight(200)
        self.image_label_orig.setStyleSheet("background-color: #232323; color: white; border: 1px solid #444; border-radius: 8px;")
        orig_image_layout.addWidget(self.image_label_orig)
        proc_image_layout = QVBoxLayout()
        proc_image_label = QLabel("Обработанное изображение:")
        proc_image_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        proc_image_layout.addWidget(proc_image_label)
        self.image_label = QLabel("Нет изображения")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(200)
        self.image_label.setStyleSheet("background-color: #232323; color: white; border: 1px solid #444; border-radius: 8px;")
        proc_image_layout.addWidget(self.image_label)
        image_layout.addLayout(orig_image_layout)
        image_layout.addLayout(proc_image_layout)
        image_group.setLayout(image_layout)
        plant_layout.addWidget(image_group)
        analysis_group = QGroupBox("Результаты анализа")
        analysis_group.setStyleSheet("QGroupBox { font-size: 18px; font-weight: bold; }")
        analysis_layout = QVBoxLayout()
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setMinimumHeight(100)
        self.analysis_text.setStyleSheet("font-size: 14px; background-color: #232323; color: white; border: 1px solid #444; border-radius: 8px;")
        self.analysis_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        analysis_layout.addWidget(self.analysis_text)
        analysis_group.setLayout(analysis_layout)
        plant_layout.addWidget(analysis_group)
        photo_layout = QHBoxLayout()
        self.take_photo_btn = QPushButton("СДЕЛАТЬ ФОТО РАСТЕНИЯ")
        self.take_photo_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                border-radius: 10px;
                padding: 15px;
                background-color: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background-color: #43A047;
            }
            QPushButton:pressed {
                background-color: #388E3C;
            }
        """)
        self.take_photo_btn.setMinimumHeight(50)
        self.take_photo_btn.clicked.connect(self.analyze_plant)
        photo_layout.addWidget(self.take_photo_btn)
        plant_layout.addLayout(photo_layout)
        tabs.addTab(plant_tab, "Анализ растений")
        settings_tab = QWidget()
        self.setup_tab = settings_tab
        self.setup_setup_tab()
        tabs.addTab(settings_tab, 'Настройки')
        system_tab = QWidget()
        system_layout = QVBoxLayout(system_tab)
        system_log_group = QGroupBox("Журнал")
        system_log_group.setStyleSheet("QGroupBox { font-size: 18px; font-weight: bold; }")
        system_log_layout = QVBoxLayout()
        self.system_log_text = QTextEdit()
        self.system_log_text.setReadOnly(True)
        self.system_log_text.setStyleSheet("font-size: 14px; background-color: #232323; color: white; border: 1px solid #444; border-radius: 8px;")
        system_log_layout.addWidget(self.system_log_text)
        system_log_group.setLayout(system_log_layout)
        system_layout.addWidget(system_log_group)
        tabs.addTab(system_tab, "Журнал")
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_cards)
        self.update_timer.start(1000)
        self.load_photo_settings()
    def create_card(self, title, value, color):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{ 
                background: linear-gradient(135deg, {color}80, {color}40); 
                border-radius: 12px; 
                border: 1px solid {color}60; 
            }}
            QLabel[valueLabel="true"] {{ color: {color}; }}
        """)
        layout = QVBoxLayout(card)
        label = QLabel(title)
        label.setStyleSheet("font-size: 16px; color: #eee; font-weight: bold;")
        value_label = QLabel(value)
        value_label.setProperty("valueLabel", "true")
        value_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        layout.addWidget(label)
        layout.addWidget(value_label)
        layout.addStretch(1)
        card.value_label = value_label
        return card
    def connect_arduino(self):
        port = self.port_combo.currentText()
        baud = 9600
        interval_minutes = self.baud_spin.value()
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            print(f"DEBUG: Соединение с Arduino на порту {port} со скоростью {baud}")
            self.serial_port = serial.Serial(port, baud, timeout=1)
            time.sleep(2)
            self.serial_port.reset_input_buffer()
            self.serial_port.write(b"PING\n")
            time.sleep(0.5)
            while self.serial_port.in_waiting:
                response = self.serial_port.readline().decode('utf-8', errors='replace').strip()
            self.arduino_thread = ArduinoReader(self.serial_port)
            self.arduino_thread.data_received.connect(self.handle_arduino_data)
            self.arduino_thread.start()
            self.sync_time()
            self.settings_interval_minutes = interval_minutes
            self.show_message(f'✅ Подключено к {port}', True)
            QTimer.singleShot(500, self.start_system_after_connect)
        except Exception as e:
            self.show_message(f'❌ Не удалось подключиться: {e}', False)
    def start_system_after_connect(self):
        """Запуск системы автоматически после подключения к Arduino"""
        if hasattr(self, 'photo_thread_active') and self.photo_thread_active:
            return
        self.log("\n=== АВТОМАТИЧЕСКИЙ ЗАПУСК СИСТЕМЫ ===")
        self.calculate_next_photo_time()
        self.photo_thread_active = True
        self.photo_thread_runner = threading.Thread(target=self.photo_thread_function, daemon=True)
        self.photo_thread_runner.start()
        self.log("✅ Система фотографирования активирована")
        QTimer.singleShot(500, self.run_setup_wizard)
        self.log("✅ Система успешно запущена!")
    def handle_arduino_data(self, data):
        if 'temperature' in data:
            self.last_temp = data['temperature']
            self.temp_graph.update_data(self.last_temp)
        if 'humidity' in data:
            self.last_hum = data['humidity']
            self.hum_graph.update_data(self.last_hum)
        if 'soil' in data:
            self.last_soil = data['soil']
            self.soil_graph.update_data(self.last_soil)
    def update_cards(self):
        self.temp_card.value_label.setText(f"{self.last_temp:.1f} °C")
        self.hum_card.value_label.setText(f"{self.last_hum:.1f} %")
        self.soil_card.value_label.setText(f"{self.last_soil:.1f} %")
    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{cmd}\n".encode())
            except Exception as e:
                self.show_message(f'Ошибка отправки: {e}', False)
    def sync_time(self):
        if self.serial_port and self.serial_port.is_open:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.send_command(f'TIME:{now}')
            time.sleep(0.5)
            while self.serial_port.in_waiting:
                response = self.serial_port.readline().decode('utf-8', errors='replace').strip()
            self.show_message('🕒 Время синхронизировано', True)
    def show_message(self, text, success=True):
        msg = QMessageBox(self)
        msg.setWindowTitle('Информация')
        msg.setText(text)
        msg.setIcon(QMessageBox.Icon.Information if success else QMessageBox.Icon.Critical)
        msg.setStyleSheet("""
            QMessageBox { background: #232323; color: #fff; font-size: 16px; }
            QPushButton { background: #4CAF50; color: #fff; border-radius: 8px; font-size: 15px; padding: 6px 18px; }
        """)
        msg.exec()
    def closeEvent(self, event):
        if self.arduino_thread:
            self.arduino_thread.stop()
        if self.photo_thread:
            if self.photo_thread.isRunning():
                self.photo_thread.wait()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        event.accept()
    def run_setup_wizard(self):
        dlg = SetupDialog(self)
        if dlg.exec():
            params = dlg.get_params()
            steps = [
                (f'SET:TEMP:{params["temp"]}', 'TEMP_OK'),
                (f'SET:TEMP_TOL:{params["temp_tol"]}', 'TEMP_TOL_OK'),
                (f'SET:SOIL:{params["soil"]}', 'SOIL_OK'),
                (f'SET:SOIL_TOL:{params["soil_tol"]}', 'SOIL_TOL_OK'),
                (f'SET:CURT_OPEN:{params["curt_open"]}', 'CURT_OPEN_OK'),
                (f'SET:CURT_CLOSE:{params["curt_close"]}', 'CURT_CLOSE_OK'),
                (f'SET:LAMP_ON:{params["lamp_on"]}', 'LAMP_ON_OK'),
                (f'SET:LAMP_OFF:{params["lamp_off"]}', 'LAMP_OFF_OK'),
            ]
            for cmd, reply in steps:
                ok = self.send_and_confirm(cmd, reply, timeout=6)
                if not ok:
                    self.show_message(f'❌ Ошибка при отправке {cmd}. Проверьте соединение и попробуйте снова.', False)
                    return
                time.sleep(0.3)
            self.show_message('✅ Все параметры успешно сохранены!', True)
    def send_and_confirm(self, cmd, expected_reply, timeout=6):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(f"{cmd}\n".encode())
            t0 = time.time()
            while time.time() - t0 < timeout:
                if self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                    if expected_reply in line:
                        return True
            self.show_message(f'⚠️ Не получено подтверждение для {cmd} (ждали "{expected_reply}")', False)
        return False
    def analyze_plant(self):
        """Фотографирует и анализирует растение"""
        global CAMERA_INDEX
        CAMERA_INDEX = self.camera_index_spin.value()
        self.camera_index = CAMERA_INDEX
        self.log("📸 Инициализация процесса фотографирования...")
        self.save_settings()
        self.photo_thread = PlantPhotoThread(self.camera_index)
        self.photo_thread.photo_taken_signal.connect(self.handle_photo_taken)
        self.photo_thread.log_signal.connect(self.log)
        self.photo_thread.start()
    def handle_photo_taken(self, original_image, detection_image, analysis):
        """Обрабатывает сигнал о сделанном фото и анализе"""
        height, width, channel = original_image.shape
        bytes_per_line = 3 * width
        q_img_orig = QImage(original_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        pixmap_orig = QPixmap.fromImage(q_img_orig)
        self.image_label_orig.setPixmap(pixmap_orig.scaled(
            self.image_label_orig.width(), self.image_label_orig.height(), 
            Qt.AspectRatioMode.KeepAspectRatio
        ))
        height, width, channel = detection_image.shape
        bytes_per_line = 3 * width
        q_img = QImage(detection_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(
            self.image_label.width(), self.image_label.height(), 
            Qt.AspectRatioMode.KeepAspectRatio
        ))
        self.analysis_text.clear()
        self.analysis_text.append(f"СОСТОЯНИЕ: {analysis['состояние']} | ЦВЕТА: {analysis['распределение цветов']}")
        self.analysis_text.append(f"ДЕТАЛИ: {analysis['детали']}")
        self.analysis_text.append(f"РЕКОМЕНДАЦИИ: {analysis['рекомендации']}")
        self.log("✅ Анализ растения успешно завершен")
    def test_camera(self):
        """Тестирование камеры"""
        global CAMERA_INDEX
        CAMERA_INDEX = self.camera_index_spin.value()
        self.camera_index = CAMERA_INDEX
        try:
            self.log("🔄 Тестирование камеры...")
            self.photo_thread = PlantPhotoThread(self.camera_index)
            self.photo_thread.log_signal.connect(self.log)
            self.photo_thread.photo_taken_signal.connect(self.handle_photo_taken)
            self.photo_thread.start()
            self.save_settings()
            self.show_message(f"✅ Камера с индексом {self.camera_index} успешно инициализирована", True)
        except Exception as e:
            self.log(f"❌ Ошибка при тестировании камеры: {str(e)}")
            self.show_message(f"❌ Ошибка инициализации камеры: {str(e)}", False)
    def log(self, message):
        """Добавляет сообщение в журнал событий"""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        formatted_message = f"{timestamp} {message}"
        if hasattr(self, 'system_log_text') and self.system_log_text is not None:
            self.system_log_text.append(formatted_message)
            self.system_log_text.verticalScrollBar().setValue(
                self.system_log_text.verticalScrollBar().maximum()
            )
    def save_settings(self):
        """Сохраняет настройки"""
        global CAMERA_INDEX
        try:
            settings = {
                'camera_index': self.camera_index,
                'port': self.port_combo.currentText(),
                'interval_minutes': self.baud_spin.value(),
                'photo_mode': self.photo_mode,
                'photo_time1': self.photo_time1,
                'photo_time2': self.photo_time2
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")
    def load_settings(self):
        """Загружает сохраненные настройки"""
        global CAMERA_INDEX
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    settings = json.load(f)
                    CAMERA_INDEX = settings.get('camera_index', 0)
                    self.camera_index = CAMERA_INDEX
                    if hasattr(self, 'camera_index_spin'):
                        self.camera_index_spin.setValue(self.camera_index)
                    if hasattr(self, 'port_combo'):
                        self.port_combo.setCurrentText(settings.get('port', 'COM10'))
                    if hasattr(self, 'baud_spin'):
                        self.baud_spin.setValue(settings.get('interval_minutes', 10))
                    if 'photo_mode' in settings:
                        self.photo_mode = settings.get('photo_mode', 'Раз в день')
                    if 'photo_time1' in settings:
                        self.photo_time1 = settings.get('photo_time1', '13:00')
                    if 'photo_time2' in settings:
                        self.photo_time2 = settings.get('photo_time2', '16:00')
                    QTimer.singleShot(100, self.update_ui_from_settings)
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
    def update_ui_from_settings(self):
        """Обновляет элементы интерфейса на основе загруженных настроек"""
        if hasattr(self, 'photo_interval_combo') and self.photo_interval_combo is not None:
            index = self.photo_interval_combo.findText(self.photo_mode)
            if index >= 0:
                self.photo_interval_combo.setCurrentIndex(index)
        if hasattr(self, 'photo_time1_edit') and self.photo_time1_edit is not None:
            self.photo_time1_edit.setText(self.photo_time1)
        if hasattr(self, 'photo_time2_edit') and self.photo_time2_edit is not None:
            self.photo_time2_edit.setText(self.photo_time2)
        if hasattr(self, 'photo_interval_combo'):
            self.update_photo_time_inputs()
    def update_photo_time_inputs(self):
        """Обновляет видимость полей ввода времени в зависимости от режима фотографирования"""
        if not hasattr(self, 'photo_interval_combo') or not hasattr(self, 'photo_time_container'):
            return
        current_mode = self.photo_interval_combo.currentText()
        if current_mode == "Каждые 10 минут (тест)":
            self.photo_time_container.setVisible(False)
        else:
            self.photo_time_container.setVisible(True)
            if hasattr(self, 'photo_time2_label'):
                self.photo_time2_label.setVisible(current_mode == "Два раза в день")
            if hasattr(self, 'photo_time2_edit'):
                self.photo_time2_edit.setVisible(current_mode == "Два раза в день")
    def save_photo_settings(self):
        """Сохраняет настройки фотографирования"""
        old_photo_mode = self.photo_mode
        old_photo_time1 = self.photo_time1
        old_photo_time2 = self.photo_time2
        self.photo_mode = self.photo_interval_combo.currentText()
        if self.photo_mode != "Каждые 10 минут (тест)":
            self.photo_time1 = self.photo_time1_edit.text().strip()
            if not self.is_valid_time_format(self.photo_time1):
                self.show_message("❌ Ошибка: Некорректный формат времени 1. Используйте формат ЧЧ:ММ", False)
                return
            if self.photo_mode == "Два раза в день":
                self.photo_time2 = self.photo_time2_edit.text().strip()
                if not self.is_valid_time_format(self.photo_time2):
                    self.show_message("❌ Ошибка: Некорректный формат времени 2. Используйте формат ЧЧ:ММ", False)
                    return
        self.save_settings()
        self.calculate_next_photo_time()
        message = "Настройки фотографирования сохранены: "
        if self.photo_mode == "Каждые 10 минут (тест)":
            message += self.photo_mode
        elif self.photo_mode == "Раз в день":
            message += f"{self.photo_mode} в {self.photo_time1}"
        else:  
            message += f"{self.photo_mode} в {self.photo_time1} и {self.photo_time2}"
        self.show_message(message, True)
        photo_settings_changed = (
            old_photo_mode != self.photo_mode or 
            old_photo_time1 != self.photo_time1 or 
            old_photo_time2 != self.photo_time2
        )
        if self.photo_thread_active and photo_settings_changed:
            self.restart_photo_thread()
    def is_valid_time_format(self, time_str):
        """Проверяет валидность формата времени ЧЧ:ММ"""
        try:
            if not time_str or len(time_str) < 3 or ":" not in time_str:
                return False
            hours, minutes = map(int, time_str.split(':'))
            return 0 <= hours < 24 and 0 <= minutes < 60
        except ValueError:
            return False
    def calculate_next_photo_time(self):
        """Вычисляет секунды с начала дня до следующего запланированного фото"""
        if self.photo_mode == "Каждые 10 минут (тест)":
            self.next_photo_time = 0
            return
        current_time = datetime.now()
        if self.photo_mode == "Раз в день":
            time_points = [self.photo_time1]
        else:
            time_points = [self.photo_time1, self.photo_time2]
        seconds_per_time = []
        for time_str in time_points:
            try:
                hours, minutes = map(int, time_str.split(':'))
                seconds = hours * 3600 + minutes * 60
                seconds_per_time.append(seconds)
            except ValueError:
                seconds_per_time.append(current_time.hour * 3600 + current_time.minute * 60)
        seconds_per_time.sort()
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        for seconds in seconds_per_time:
            if seconds > current_seconds:
                self.next_photo_time = seconds
                return
        self.next_photo_time = seconds_per_time[0]
    def restart_photo_thread(self):
        """Перезапускает поток фотографирования с новыми настройками"""
        self.photo_thread_active = False
        time.sleep(1)
        self.photo_thread_active = True
        self.photo_thread_runner = threading.Thread(target=self.photo_thread_function, daemon=True)
        self.photo_thread_runner.start()
    def photo_thread_function(self):
        """Функция для выполнения периодического фотографирования"""
        log_message = "🧵 Запущен поток периодического фотографирования: "
        if self.photo_mode == "Каждые 10 минут (тест)":
            log_message += f"режим = {self.photo_mode}"
        elif self.photo_mode == "Раз в день":
            log_message += f"режим = {self.photo_mode} в {self.photo_time1}"
        else:
            log_message += f"режим = {self.photo_mode} в {self.photo_time1} и {self.photo_time2}"
        self.log(log_message)
        self.calculate_next_photo_time()
        last_photo_time = time.time()
        current_day = datetime.now().day
        photos_taken_today = {}
        while self.photo_thread_active:
            try:
                current_time = time.time()
                now = datetime.now()
                if now.day != current_day:
                    current_day = now.day
                    photos_taken_today = {}
                    self.log(f"Новый день ({now.strftime('%Y-%m-%d')}). Сбрасываем информацию о сделанных фото.")
                if self.photo_mode == "Каждые 10 минут (тест)":
                    if current_time - last_photo_time >= 600:
                        self.log(f"Делаем тестовое фото (прошло {int((current_time - last_photo_time))} секунд)")
                        self.take_scheduled_photo()
                        last_photo_time = time.time()
                else:
                    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
                    time_points = []
                    time_names = {}
                    if self.photo_mode == "Раз в день":
                        try:
                            hours, minutes = map(int, self.photo_time1.split(':'))
                            seconds = hours * 3600 + minutes * 60
                            time_points.append(seconds)
                            time_names[seconds] = self.photo_time1
                        except ValueError:
                            self.log(f"❌ Ошибка формата времени 1: {self.photo_time1}")
                    else:
                        for idx, time_str in enumerate([self.photo_time1, self.photo_time2]):
                            try:
                                hours, minutes = map(int, time_str.split(':'))
                                seconds = hours * 3600 + minutes * 60
                                time_points.append(seconds)
                                time_names[seconds] = time_str
                            except ValueError:
                                self.log(f"❌ Ошибка формата времени {idx+1}: {time_str}")
                    time_points.sort()
                    for seconds in time_points:
                        time_key = time_names[seconds]
                        if time_key in photos_taken_today and photos_taken_today[time_key]:
                            continue
                        if abs(current_seconds - seconds) <= 30:
                            self.log(f"Наступило запланированное время для фото: {time_names[seconds]}")
                            self.take_scheduled_photo()
                            photos_taken_today[time_key] = True
                            break
                time.sleep(5)
            except Exception as e:
                self.log(f"❌ Ошибка в потоке фотографирования: {str(e)}")
                time.sleep(10)
    def take_scheduled_photo(self):
        """Делает фото по расписанию"""
        self.log("\n=== Выполнение запланированного фотографирования ===")
        self.analyze_plant()
    def stop_system(self):
        """Остановка системы"""
        if hasattr(self, 'sensor_thread') and self.sensor_thread:
            self.sensor_thread.stop()
        if hasattr(self, 'photo_thread_active'):
            self.photo_thread_active = False
            self.log("🔄 Поток фотографирования остановлен")
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.log("🛑 Система остановлена")
        self.show_message('🛑 Система остановлена', True)
    def check_connection(self):
        """Проверяет соединение с Arduino"""
        if not hasattr(self, 'serial_connection') or not self.serial_connection or not self.serial_connection.is_open:
            return False
        return True
    def load_photo_settings(self):
        """Загружает настройки фотографирования из сохраненных данных"""
        if hasattr(self, 'photo_interval_combo') and self.photo_interval_combo is not None:
            self.photo_interval_combo.setCurrentText(self.photo_mode)
        if hasattr(self, 'photo_time1_edit') and self.photo_time1_edit is not None:
            self.photo_time1_edit.setText(self.photo_time1)
        if hasattr(self, 'photo_time2_edit') and self.photo_time2_edit is not None:
            self.photo_time2_edit.setText(self.photo_time2)
        if hasattr(self, 'photo_interval_combo'):
            self.update_photo_time_inputs()
    def setup_setup_tab(self):
        layout = QVBoxLayout(self.setup_tab)
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel('COM порт:'))
        self.port_combo = QComboBox()
        self.port_combo.addItems([f'COM{i}' for i in range(1, 21)])
        self.port_combo.setCurrentText('COM10')
        self.port_combo.setStyleSheet("""
            QComboBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QComboBox::drop-down {
                width: 0;
                height: 0;
                border: 0;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #fff;
                selection-background-color: #444;
            }
        """)
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(QLabel('Интервал (мин):'))
        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1, 60)
        self.baud_spin.setSingleStep(1)
        self.baud_spin.setValue(10)
        self.baud_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        port_layout.addWidget(self.baud_spin)
        self.connect_btn = QPushButton('Подключиться к Arduino')
        self.connect_btn.clicked.connect(self.connect_arduino)
        port_layout.addWidget(self.connect_btn)
        layout.addLayout(port_layout)
        camera_group = QGroupBox("Настройки камеры")
        camera_group.setStyleSheet("QGroupBox { font-size: 18px; font-weight: bold; }")
        camera_layout = QFormLayout()
        self.camera_index_spin = QSpinBox()
        self.camera_index_spin.setRange(0, 10)
        self.camera_index_spin.setValue(CAMERA_INDEX)
        self.camera_index_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        camera_layout.addRow("Индекс камеры:", self.camera_index_spin)
        self.test_camera_btn = QPushButton("Проверить камеру")
        self.test_camera_btn.clicked.connect(self.test_camera)
        camera_layout.addRow("", self.test_camera_btn)
        camera_group.setLayout(camera_layout)
        layout.addWidget(camera_group)
        photo_group = QGroupBox("Настройки фотографирования")
        photo_group.setStyleSheet("QGroupBox { font-size: 18px; font-weight: bold; }")
        photo_layout = QFormLayout()
        self.photo_interval_combo = QComboBox()
        photo_modes = [
            "Раз в день", 
            "Два раза в день", 
            "Каждые 10 минут (тест)"
        ]
        for mode in photo_modes:
            self.photo_interval_combo.addItem(mode)
        self.photo_interval_combo.setCurrentText("Раз в день")
        self.photo_interval_combo.setStyleSheet("""
            QComboBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 180px;
            }
            QComboBox::drop-down {
                width: 0;
                height: 0;
                border: 0;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #fff;
                selection-background-color: #444;
            }
        """)
        photo_layout.addRow("Режим:", self.photo_interval_combo)
        self.photo_time_container = QWidget()
        time_layout = QVBoxLayout(self.photo_time_container)
        time_layout.setContentsMargins(0, 5, 0, 0)
        time1_layout = QHBoxLayout()
        self.photo_time1_label = QLabel("Время фото:")
        time1_layout.addWidget(self.photo_time1_label)
        self.photo_time1_edit = QLineEdit("13:00")
        self.photo_time1_edit.setPlaceholderText("ЧЧ:ММ")
        self.photo_time1_edit.setStyleSheet("""
            QLineEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
        """)
        time1_layout.addWidget(self.photo_time1_edit)
        time_layout.addLayout(time1_layout)
        time2_layout = QHBoxLayout()
        self.photo_time2_label = QLabel("Второе время:")
        time2_layout.addWidget(self.photo_time2_label)
        self.photo_time2_edit = QLineEdit("16:00")
        self.photo_time2_edit.setPlaceholderText("ЧЧ:ММ")
        self.photo_time2_edit.setStyleSheet("""
            QLineEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
        """)
        time2_layout.addWidget(self.photo_time2_edit)
        time_layout.addLayout(time2_layout)
        photo_layout.addRow("", self.photo_time_container)
        self.photo_interval_combo.currentIndexChanged.connect(self.update_photo_time_inputs)
        self.save_photo_settings_btn = QPushButton("Сохранить настройки фото")
        self.save_photo_settings_btn.clicked.connect(self.save_photo_settings)
        photo_layout.addRow("", self.save_photo_settings_btn)
        photo_group.setLayout(photo_layout)
        layout.addWidget(photo_group)
        self.sync_time_btn = QPushButton('Синхронизировать время')
        self.sync_time_btn.clicked.connect(self.sync_time)
        layout.addWidget(self.sync_time_btn)
        layout.addStretch(1)
    def auto_connect_arduino(self):
        """Автоматическое подключение к Arduino при запуске программы"""
        try:
            port = self.port_combo.currentText()
            interval_minutes = self.baud_spin.value()
            self.log(f"\n=== АВТОМАТИЧЕСКОЕ ПОДКЛЮЧЕНИЕ К ARDUINO ===")
            self.log(f"Попытка подключения к порту {port} с интервалом {interval_minutes} мин...")
            self.connect_arduino()
        except Exception as e:
            self.log(f"❌ Ошибка при автоподключении: {str(e)}")
class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('настройка ФитоДомика')
        self.setStyleSheet('background: #232323; color: #fff; font-size: 16px;')
        layout = QFormLayout(self)
        self.temp_spin = QSpinBox()
        self.temp_spin.setRange(10, 40)
        self.temp_spin.setValue(25)
        self.temp_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Целевая температура (°C):', self.temp_spin)
        self.temp_tol_spin = QSpinBox()
        self.temp_tol_spin.setRange(1, 6)
        self.temp_tol_spin.setValue(3)
        self.temp_tol_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Погрешность температуры (°C):', self.temp_tol_spin)
        self.soil_spin = QSpinBox()
        self.soil_spin.setRange(16, 100)
        self.soil_spin.setValue(50)
        self.soil_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Целевая влажность почвы (%):', self.soil_spin)
        self.soil_tol_spin = QSpinBox()
        self.soil_tol_spin.setRange(1, 10)
        self.soil_tol_spin.setValue(5)
        self.soil_tol_spin.setStyleSheet("""
            QSpinBox {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Погрешность влажности почвы (%):', self.soil_tol_spin)
        self.curt_open_time = QTimeEdit()
        self.curt_open_time.setDisplayFormat('HH:mm')
        self.curt_open_time.setTime(datetime.strptime('08:00', '%H:%M').time())
        self.curt_open_time.setStyleSheet("""
            QTimeEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QTimeEdit::up-button, QTimeEdit::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Время открытия штор:', self.curt_open_time)
        self.curt_close_time = QTimeEdit()
        self.curt_close_time.setDisplayFormat('HH:mm')
        self.curt_close_time.setTime(datetime.strptime('20:00', '%H:%M').time())
        self.curt_close_time.setStyleSheet("""
            QTimeEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QTimeEdit::up-button, QTimeEdit::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Время закрытия штор:', self.curt_close_time)
        self.lamp_on_time = QTimeEdit()
        self.lamp_on_time.setDisplayFormat('HH:mm')
        self.lamp_on_time.setTime(datetime.strptime('08:30', '%H:%M').time())
        self.lamp_on_time.setStyleSheet("""
            QTimeEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QTimeEdit::up-button, QTimeEdit::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Время включения лампы:', self.lamp_on_time)
        self.lamp_off_time = QTimeEdit()
        self.lamp_off_time.setDisplayFormat('HH:mm')
        self.lamp_off_time.setTime(datetime.strptime('21:00', '%H:%M').time())
        self.lamp_off_time.setStyleSheet("""
            QTimeEdit {
                background-color: #232323;
                color: #fff;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QTimeEdit::up-button, QTimeEdit::down-button {
                width: 0;
                height: 0;
                border: 0;
            }
        """)
        layout.addRow('Время выключения лампы:', self.lamp_off_time)
        self.save_btn = QPushButton('Сохранить настройки')
        self.save_btn.setStyleSheet('background: #4CAF50; color: #fff; font-size: 16px; border-radius: 8px; padding: 8px 24px;')
        self.save_btn.clicked.connect(self.accept)
        layout.addRow(self.save_btn)
    def get_params(self):
        def fmt(qt):
            return qt.toString('HH:mm')
        return {
            'temp': self.temp_spin.value(),
            'temp_tol': self.temp_tol_spin.value(),
            'soil': self.soil_spin.value(),
            'soil_tol': self.soil_tol_spin.value(),
            'curt_open': fmt(self.curt_open_time.time()),
            'curt_close': fmt(self.curt_close_time.time()),
            'lamp_on': fmt(self.lamp_on_time.time()),
            'lamp_off': fmt(self.lamp_off_time.time()),
        }
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app_icon = QIcon(ICON_FILE)
    app.setWindowIcon(app_icon)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 