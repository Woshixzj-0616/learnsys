"""学习记录器的可调参数。

打包成 exe 之后**这个文件在 exe 里面、改不着** ⇒ 想改的行为放
`D:/学习系统/设置.json`（第一次打开问一问会自己生成一份带说明的模板，填完重启就生效）。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
import urllib.parse

FROZEN = bool(getattr(sys, "frozen", False))     # True = 正在打包好的 exe 里跑
ROOT = (pathlib.Path(sys.executable).resolve().parent if FROZEN
        else pathlib.Path(__file__).resolve().parent.parent)

# ---- 数据存哪：D 盘专用一个文件夹，按天分（如 2026.10.2）----
DATA_ROOT = pathlib.Path("D:/学习系统")


# ---- 你能改的那几项：D:/学习系统/设置.json（程序只读它，不往里写）----
SETTINGS_FILE = DATA_ROOT / "设置.json"

SETTINGS_TEMPLATE = {
    "_说明": "问一问的设置。改完保存 → 重启问一问就生效；留空 = 用默认。",
    "_默认": "什么都不填 = 走本机 Codex 的中转口（不用 key，但要把 Codex 开着）。",
    "_自己填key": {
        "怎么填": "任何「OpenAI 兼容 + 能看图」的服务都行，下面三个是例子；填 api_key 就别留 api_base / api_model。",
        "硅基流动": {"api_base": "https://api.siliconflow.cn/v1",
                     "api_model": "Qwen/Qwen2.5-VL-32B-Instruct", "api_key": "sk-xxx"},
        "智谱GLM": {"api_base": "https://open.bigmodel.cn/api/paas/v4",
                    "api_model": "glm-4v-plus", "api_key": "xxx"},
        "通义千问": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                     "api_model": "qwen-vl-max", "api_key": "sk-xxx"},
    },
    "api_base": "",
    "api_key": "",
    "api_model": "",
    "api_style": "",
    "hotkey": "",
}


def load_settings() -> dict:
    """读设置文件；没有 / 读坏了都当「没设置」—— 绝不让它拦住启动。"""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


USER = load_settings()


def ensure_settings_file() -> pathlib.Path:
    """第一次打开就把模板摆在这儿 —— 免得找不到该去哪儿填 key。"""
    if not SETTINGS_FILE.exists():
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(SETTINGS_TEMPLATE, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass
    return SETTINGS_FILE


def day_dir(when=None) -> pathlib.Path:
    """那天的文件夹，例如 D:\学习系统\2026.10.2"""
    moment = when or datetime.datetime.now()
    return DATA_ROOT / f"{moment.year}.{moment.month}.{moment.day}"


def db_path(when=None) -> pathlib.Path:
    """那天的库（一天一份；删一天 = 删一个文件夹）"""
    return day_dir(when) / "learnsys.db"


def ask_tmp_dir() -> pathlib.Path:
    """那天的截图临时目录（问完即删）"""
    return day_dir() / "截图"


SETTINGS_PATH = DATA_ROOT / "界面设置.json"   # 横栏的位置 / 收起状态
ICON_PATH = ROOT / "问一问.ico"              # 托盘 / 窗口 / 任务栏的图标（首次启动自动生成）

# ---- 前台窗口 ----
WINDOW_SAMPLE_SECONDS = 1.0

# ---- 声音（系统回环）→ 本地转写 ----
CHUNK_SECONDS = 45.0        # 每攒多少秒的录音转一次
#   实测：一段越长上下文越足，但落库越晚。120s 段 = 222 字/分钟（准），25s 段遇到板书空档只剩 38 字/分钟。
#   45s 是折中：转写约 12s 追得上，落后约 1 分钟。想更实时就调小。
SILENCE_RMS = 0.003         # 响度低于这个就跳过：静音不花算力、不落库
MIN_CHUNK_SECONDS = 2.0     # 短于这个的碎块直接丢掉
ASR_MODEL_DIR = str(ROOT / "models" / "small")
ASR_DEVICE = "cpu"          # 想用显卡填 "cuda"（要先装 cuDNN/cuBLAS）
ASR_COMPUTE_TYPE = "int8"   # cuda 时改成 "float16"
ASR_LANGUAGE = "zh"
ASR_BEAM_SIZE = 5
ASR_VAD = True              # 静音切段；失败会自动退回 False
# ---- 问一问（框选屏幕 → 问 AI）----
# 下面带「设置.json」的几项都能在 D:/学习系统/设置.json 里改 —— 打包成 exe 后就靠它
ASK_HOTKEY = USER.get("hotkey") or "alt+q"   # 全局快捷键：修饰键(alt/ctrl/shift/win) + 主键
ASK_TIMEOUT_SECONDS = 90.0      # 等 AI 回话的上限；超时就在横条里给中文提示，不装死
ASK_KEEP_IMAGES = False         # False = 截图问完即删，不留盘

# 问谁：默认打本机 Codex 的中转口（一次 HTTP 约 1~3 秒、不用 key、但要 Codex 开着）；
# 在 设置.json 里填 api_base / api_key / api_model 就换成任何「OpenAI 兼容 + 能看图」的服务。
ASK_API_BASE = USER.get("api_base") or "http://127.0.0.1:57321/v1"
ASK_API_MODEL = USER.get("api_model") or "deepseek-flash"
ASK_API_KEY = USER.get("api_key") or ""
ASK_API_STYLE = USER.get("api_style") or ""   # "" = 自动（本机走 responses，别处走 chat）


def api_style() -> str:
    """按哪种协议说话：本机中转 = Responses；自己填的 = OpenAI 兼容 /chat/completions。"""
    if ASK_API_STYLE:
        return str(ASK_API_STYLE).strip().lower()
    host = (urllib.parse.urlsplit(ASK_API_BASE).hostname or "").lower()
    return "responses" if host in ("127.0.0.1", "localhost", "::1") else "chat"

# 顶部横条的尺寸
ASK_BAR_WIDTH_RATIO = 0.82        # 占屏幕宽度的比例
ASK_BAR_WIDTH_MAX = 1400          # 最宽不超过
ASK_BAR_TOP_GAP = 10              # 离屏幕顶端多远
ASK_BAR_ANSWER_MAX_RATIO = 0.62   # 答案区最高占屏幕高度的比例（再长就滚动）
ASK_BAR_PILL_WIDTH = 250          # 收起成一条小条后有多宽
ASK_BAR_ALWAYS_ON_TOP = True      # 横条常驻在屏幕最上方

# 热词：当 initial_prompt 喂给模型，能显著压掉成体系的同音错
HOTWORDS = (
    "以下是中文计算机课程录音。常用术语：数据结构、线性表、顺序表、链表、单链表、双链表、"
    "栈、队列、循环队列、串、数组、广义表、树、二叉树、完全二叉树、满二叉树、遍历、前序、"
    "中序、后序、层序、线索二叉树、森林、哈夫曼树、图、顶点、边、邻接矩阵、邻接表、"
    "深度优先、广度优先、最小生成树、最短路径、拓扑排序、查找、折半查找、哈希表、"
    "排序、冒泡排序、快速排序、归并排序、堆、时间复杂度、空间复杂度、渐进、算法、绪论、"
    "抽象数据类型、数据项、数据元素、逻辑结构、存储结构、栈顶、栈底、队头、队尾。"
)
