import sys
import time
import mss
import base64
import json
import io
import os
import asyncio
import threading
import math
import keyboard
import pygame
import edge_tts
from PIL import Image
from openai import OpenAI
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QPixmap

# ================= 配置区 =================
# ⚠️ 替换成你真实的智谱 API Key（保留双引号）
api_key = "YOUR_API_KEY"
client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")

# ================= 核心逻辑 =================

# 1. 异步语音合成 + 后台静默播放（防弹窗）
async def generate_voice(text):
    try:
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await communicate.save("alert.mp3")
    except Exception as e:
        print(f"语音生成失败: {e}")

def play_voice_alert(text):
    def play_task():
        try:
            # 生成音频
            asyncio.run(generate_voice(text))
            
            # 初始化并静默播放
            pygame.mixer.init()
            pygame.mixer.music.load("alert.mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            pygame.mixer.quit()
        except Exception as e:
            print(f"语音播放失败: {e}")
    
    # 使用守护线程，防止卡死主界面
    threading.Thread(target=play_task, daemon=True).start()

# 2. 规则引擎
def check_rules(state_json_text):
    try:
        clean_json = state_json_text.replace("```json", "").replace("```", "").strip()
        state = json.loads(clean_json)
        hp = int(state.get("hp", 100) or 100)
        gold = int(state.get("gold", 0) or 0)
        
        alerts = []
        # ⚠️ 测试时如果想容易触发，可以把下面的 30 改成 100，50 改成 0
        if hp < 30 and gold > 50:
            alerts.append("警告！血量极其危险，且囤积了大量金币，请立刻D牌提升战力！")
        elif hp < 15:
            alerts.append("警告！生命值见底，即将被淘汰，请立即寻找保命手段！")
        return alerts
    except Exception as e:
        print(f"规则解析失败: {e}")
        return []

# 3. 截图、压缩与视觉识别
def capture_and_analyze():
    # 截图
    with mss.mss() as sct:
        sct_img = sct.grab(sct.monitors[1])
        mss.tools.to_png(sct_img.rgb, sct_img.size, output="temp_full.png")
    
    # 压缩（防止400报错）
    img = Image.open("temp_full.png")
    ratio = 800 / float(img.size[0])
    new_size = tuple([int(x * ratio) for x in img.size])
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    # 视觉识别
    try:
        response = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "这是一张游戏截图。请分析画面，识别当前血量、金币、等级、当前阶段。请严格以JSON格式返回，包含字段：hp, gold, level, stage。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
            ]}]
        )
        state_json = response.choices[0].message.content
    except Exception as e:
        return f"识别失败: {e}", ""

    # 战术决策（RAG）
    try:
        kb_data = "[]"
        if os.path.exists("knowledge_base.json"):
            with open("knowledge_base.json", "r", encoding="utf-8") as f:
                kb_data = f.read()
        prompt = f"玩家状态：{state_json}\n知识库：{kb_data}\n请作为金铲铲教练给出下一步战术建议（限50字内）。"
        res = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        strategy = res.choices[0].message.content
    except Exception as e:
        strategy = f"战术分析失败: {e}"

    # 规则引擎触发语音
    alerts = check_rules(state_json)
    final_alert = ""
    if alerts:
        final_alert = alerts[0]
        play_voice_alert(final_alert)

    return strategy, final_alert

# ================= 桌面宠物 UI =================
class AnalysisWorker(QThread):
    finished = pyqtSignal(str, str)
    def run(self):
        strategy, alert = capture_and_analyze()
        self.finished.emit(strategy, alert)

class PetWindow(QWidget):
    update_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.initUI()
        self.update_signal.connect(self.update_ui)
        self.oldPos = self.pos()
        
        # 注册全局快捷键 F8
        keyboard.add_hotkey('F8', self.trigger_analysis)
        print("✅ 悬浮窗已启动！按 F8 触发截图分析。")

    def initUI(self):
        # 窗口置顶、无边框、透明背景
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 气泡
        self.bubble = QLabel("按 F8 呼叫我~")
        self.bubble.setStyleSheet("""
            background-color: rgba(255, 255, 255, 200); 
            color: black; 
            border-radius: 10px; 
            padding: 8px; 
            font-family: 'Microsoft YaHei'; 
            font-size: 14px;
            border: 2px solid #4CAF50;
        """)
        self.bubble.setWordWrap(True)
        self.bubble.setFixedWidth(200)
        self.bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 静态图加载
        self.avatar = QLabel()
        pixmap = QPixmap("avatar.png")
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(150, Qt.TransformationMode.SmoothTransformation)
            self.avatar.setPixmap(pixmap)
        else:
            self.avatar.setText("🤖")
            self.avatar.setStyleSheet("font-size: 80px;")
        
        layout.addWidget(self.bubble, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.avatar, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)
        
        # 屏幕居中初始位置
        screen = QApplication.primaryScreen().geometry()
        self.base_x = (screen.width() - 300) // 2
        self.base_y = (screen.height() - 300) // 2
        self.move(self.base_x, self.base_y)

        # 飞翔/漂浮特效
        self.float_timer = QTimer(self)
        self.float_timer.timeout.connect(self.float_effect)
        self.float_timer.start(50)
        self.float_phase = 0

    def float_effect(self):
        self.float_phase += 0.1
        offset_y = int(math.sin(self.float_phase) * 15)
        offset_x = int(math.cos(self.float_phase * 0.5) * 8)
        self.move(self.base_x + offset_x, self.base_y + offset_y)

    def trigger_analysis(self):
        self.bubble.setText("正在分析局势...")
        self.worker = AnalysisWorker()
        self.worker.finished.connect(self.update_ui)
        self.worker.start()

    def update_ui(self, strategy, alert):
        text = alert if alert else strategy
        if len(text) > 80:
            text = text[:77] + "..."
        self.bubble.setText(text)

    # 拖动窗口
    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()
    def mouseMoveEvent(self, event):
        delta = event.globalPosition().toPoint() - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()
        # 拖动后重置基础位置，防止漂浮重置回中心
        self.base_x = self.x()
        self.base_y = self.y()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    pet = PetWindow()
    pet.show()
    sys.exit(app.exec())