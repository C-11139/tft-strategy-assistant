import streamlit as st
import time
import mss
import base64
import json
import io
import os
import asyncio
from PIL import Image
from openai import OpenAI
import edge_tts

# ================= 配置区 =================
# ⚠️ 替换成你真实的智谱 API Key（保留双引号）
api_key = "YOUR_API_KEY"
client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")

# ================= 核心逻辑与Agent规则引擎 =================

# 1. 主动响应：异步语音播报
async def speak_text(text):
    try:
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await communicate.save("alert.mp3")
        # Windows下调用系统默认播放器播放
        os.system("start alert.mp3")
    except Exception as e:
        print(f"语音播放失败: {e}")

def play_voice_alert(text):
    # 兼容Streamlit环境的异步执行
    try:
        asyncio.run(speak_text(text))
    except Exception as e:
        print(f"异步运行失败: {e}")

# 2. 规则引擎：判断是否触发警报
def check_rules(state_json_text):
    try:
        # 剔除大模型可能自带的 markdown json 标记
        clean_json = state_json_text.replace("```json", "").replace("```", "").strip()
        state = json.loads(clean_json)
        
        hp = int(state.get("hp", 100) or 100)
        gold = int(state.get("gold", 0) or 0)
        
        alerts = []
        # 触发条件
        if hp < 30 and gold > 50:
            alerts.append("警告！血量极其危险，且囤积了大量金币，请立刻D牌提升战力！")
        elif hp < 15:
            alerts.append("警告！生命值见底，即将被淘汰，请立即寻找保命手段！")
        return alerts
    except Exception as e:
        print(f"规则解析失败: {e}")
        return []

# 3. 屏幕捕获与图像压缩（防观察者悖论、防API报错）
def capture_screen():
    st.warning("⚠️ 请在 5 秒内立刻将游戏画面切换到前台！不要看网页！")
    time.sleep(5)
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        mss.tools.to_png(sct_img.rgb, sct_img.size, output="temp_full.png")
        
    img = Image.open("temp_full.png")
    max_size = 800 # 压缩到宽度800，极大降低体积
    ratio = max_size / float(img.size[0])
    new_size = tuple([int(x * ratio) for x in img.size])
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return img_base64

# 4. 多模态视觉识别
def analyze_image(base64_image):
    prompt = "这是一张游戏截图。请分析画面，识别当前血量、金币、等级、当前阶段。请严格以JSON格式返回，包含字段：hp, gold, level, stage。"
    try:
        response = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
            ]}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"视觉识别失败: {str(e)}"

# 5. 战术决策（RAG检索增强）
def get_strategy(game_state_text):
    kb_data = "[]"
    try:
        with open("knowledge_base.json", "r", encoding="utf-8") as f:
            kb_data = f.read()
    except Exception:
        pass

    prompt = f"""
    你是一个顶级《金铲铲之战》教练。当前玩家的游戏状态如下：
    {game_state_text}
    这是当前版本的强势阵容知识库：
    {kb_data}
    请根据玩家当前处境，结合知识库，给出下一步最合理的战术建议。
    要求严格分为三段输出：
    【当前局势】客观分析
    【核心建议】明确的指令
    【操作细节】具体买什么卡，做什么装备
    """
    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"战术分析失败: {str(e)}"

# ================= UI 界面 =================
st.set_page_config(page_title="TFT AI 实时教练", layout="wide")
st.title("🎮 金铲铲 AI 实时战术助手 (Agent 版)")

st.sidebar.header("操作面板")
st.sidebar.write("点击下方按钮，AI 将截取当前屏幕并给出实时战术建议。")
st.sidebar.warning("⚠️ 请确保游戏画面在屏幕前台。")
start_btn = st.sidebar.button("▶ 开始/更新战术分析")

col1, col2 = st.columns([1, 1])

if start_btn:
    with st.spinner('正在截图并呼叫 AI 教练...'):
        # 1. 截图与压缩
        img_base64 = capture_screen()
        with col1:
            st.subheader("📸 实时画面")
            st.image("temp_full.png", use_container_width=True)
        
        # 2. 视觉识别
        state_json = analyze_image(img_base64)
        
        # 3. 规则引擎与主动语音播报（Agent核心）
        alerts = check_rules(state_json)
        if alerts:
            st.error(f"🚨 紧急战术警报：{alerts[0]}")
            play_voice_alert(alerts[0])
            
        with col2:
            st.subheader("🧠 AI 识别状态")
            st.code(state_json, language="json")
            
        # 4. 战术决策
        st.markdown("---")
        st.subheader("🎯 教练战术指导")
        strategy = get_strategy(state_json)
        st.info(strategy)
else:
    st.info("👈 请在左侧点击【开始/更新战术分析】。")