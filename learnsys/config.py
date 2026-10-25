"""学习记录器的可调参数。

打包成 exe 之后**这个文件在 exe 里面、改不着** ⇒ 想改的行为放
`D:/学习系统/设置.json`（第一次打开学习工作台会自己生成一份带说明的模板，填完重启就生效）。
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
import urllib.parse

FROZEN = bool(getattr(sys, "frozen", False))     # True = 正在打包好的 exe 里跑
ROOT = (pathlib.Path(sys.executable).resolve().parent if FROZEN
        else pathlib.Path(__file__).resolve().parent.parent)

# ---- 数据存哪 ----
# 优先级：环境变量 LEARNSYS_DATA_ROOT → 已有安装的 D:\学习系统（兼容旧数据）→ 用户目录\学习系统。
# v2 起记录统一进 learning.db；按天文件夹只放截图/录屏/报告这些产物。
def _data_root() -> pathlib.Path:
    env = os.environ.get("LEARNSYS_DATA_ROOT", "").strip()
    if env:
        return pathlib.Path(env).expanduser()
    legacy = pathlib.Path("D:/学习系统")
    if legacy.exists():
        return legacy
    return pathlib.Path.home() / "学习系统"


DATA_ROOT = _data_root()
UNIFIED_DB = True


# ---- 你能改的那几项：D:/学习系统/设置.json（程序只读它，不往里写）----
SETTINGS_FILE = DATA_ROOT / "设置.json"

SETTINGS_TEMPLATE = {
    "_说明": "学习工作台的设置。改完保存 → 重启学习工作台就生效；留空 = 用默认。",
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
    "_agent": "v2 主模型：Anthropic Messages 兼容服务。base_url 填到 /anthropic 或 /v1 都行；留空 = 用 ~/.claude/settings.json 里的 env。",
    "agent": {
        "base_url": "",
        "auth_token": "",
        "model": "",
        "fast_model": "",
        "max_tokens": 8192,
        "thinking": False,
        "speed": "balanced",
        "auto_route": "off",
        "_auto_route": "自动路由：off 关闭 / shadow 只记建议 / on 按建议切换。"
                       "只影响 balanced 档；手动 speed 与 routes 优先。",
        "strong_model": "",
        "_strong_model": "自动路由升级用的强模型；留空 = 用主模型并多开思考。",
        "_routes": "按任务换模型（可选）。键：explain/guide/quiz/quick/translate/analyze/review；"
                   "留空 = 全部走 speed 档。例：{\"translate\": \"deepseek-flash\"}",
        "routes": {},
        "_prices": "按模型覆盖单价（每 100 万 token）。没配的模型用上面的全局价。"
                   "例：{\"deepseek-v4-pro\": {\"input\": 1.0, \"output\": 2.0, \"cache_read\": 0.1}}",
        "prices": {},
        "_daily_cost_limit": "每日成本上限（0 = 不限）。达到后不再发起模型调用；"
                             "需要先填单价才有意义。",
        "daily_cost_limit": 0,
        "_daily_call_limit": "每日模型调用上限（0 = 不限）。按成功调用的次数算。",
        "daily_call_limit": 0,
    },
    "_vision": "可选：看图用的 OpenAI 兼容视觉模型（如智谱 GLM-4V-Flash）。留空 = 退回 OCR，只读图中文字。",
    "vision": {
        "base_url": "",
        "api_key": "",
        "model": "",
    },
    "api_base": "",
    "api_key": "",
    "api_model": "",
    "api_style": "",
    "hotkey": "",
    "_record_hotkey": "停止录像的全局快捷键（默认 ctrl+alt+s；录像时横栏会藏起来）",
    "record_hotkey": "",
    "system_prompt": "",
    "_system_prompt_text": "没框图、纯文字问的时候用的提示词（不填 = 用内置的）",
    "system_prompt_text": "",
    "_max_tokens": "答案最长多少 token（默认 1500，只防失控；调小会让答案写不完）",
    "max_tokens": 1500,
    "_记录": "点托盘里的「开始记录」，它会记下你在看哪个窗口 —— **只在你开始之后记，不全天**，"
             "数据只在本地。关掉下面这项就只记程序名、不记窗口标题（标题里可能有聊天对象、私人信息）",
    "record_window_title": True,
    "_backup_dir": "数据自动备份放哪儿（留空 = 数据目录旁的「学习系统备份」）。每周自动备一次，托盘里也能「立即备份数据」",
    "backup_dir": "",
    "_keep_days": "数据保留天数：超过这么多天的旧数据文件夹自动删除（0 = 永不删，默认）",
    "keep_days": 0,
    "_video": "录像：video_enabled 开关；video_fps 帧率（5–15，默认 10）；video_max_width 最长边（默认 1600）；"
              "video_dir 录像文件夹（留空 = 数据目录下的「录像」）；video_max_seconds 单段上限（默认 10800 秒）；"
              "video_max_bytes 单段大小上限（默认 8GB）",
    "video_enabled": True,
    "video_fps": 10,
    "video_max_width": 1600,
    "video_dir": "",
    "video_max_seconds": 10800,
    "video_max_bytes": 8589934592,
    "_workbench_on_start": "打开学习工作台时，是否自动弹出网页工作台窗口（false = 只出快捷栏，从托盘再打开）",
    "workbench_on_start": True,
    "_pwa_app_id": "可选：已安装 PWA 的 app-id。填了就用它打开工作台（任务栏有独立的「学习工作台」按钮）；留空 = Edge 应用窗口。",
    "pwa_app_id": "",
    "_cet6_dir": "六级精听目录（可选模块；留空 = 自动找仓库旁边的「六级精听」）。"
                 "目录里要有 工作台\\精听工作台.html 和 试卷\\",
    "cet6_dir": "",
    "_materials": "资料库批量导入：import_dirs 是允许扫描的目录列表（留空 = 不允许批量导入）；"
                  "obsidian_dir 只用于手动「导入 Obsidian」，默认不自动扫。只读，不移动原文件。",
    "materials": {
        "import_dirs": [],
        "obsidian_dir": "",
    },
    "_browser": "工作台浏览器（P20.2）：独立 profile 的 Edge/Chrome，只记录 URL/标题/域名。"
                "enabled=false 关闭功能；record=false 暂停记录；exclude_domains 不记录的域名；"
                "history_days 保留天数（1–365）；close_on_exit 工作台退出时关闭浏览器。",
    "browser": {
        "enabled": True,
        "record": True,
        "exclude_domains": [],
        "history_days": 30,
        "close_on_exit": True,
    },
    "_daily_goal_xp": "每日学习点目标（默认 100）。问答 10 / 转写 5 / 六级断点 8 / 专注 1 分钟 1 / 收藏 3",
    "daily_goal_xp": 100,
    "_名字": "学习台左上角怎么称呼你（留空 = 不显示名字）",
    "名字": "",
}


def load_settings() -> dict:
    """读设置文件；没有 / 读坏了都当「没设置」—— 绝不让它拦住启动。"""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


USER = load_settings()


def _user_int(key: str, default: int) -> int:
    """设置里那几项数字 —— 填坏了（空 / 不是数字）就用默认，别让它拦住启动。

    ⚠️ 填 **0 是有效值**（max_tokens 填 0 = 不设上限），不能拿 `or default` 兜 ——
    那会把 0 吃掉变默认。只认「没填 / 空串」才走默认。
    """
    raw = USER.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _user_bool(key: str, default: bool) -> bool:
    """设置里那几项开关 —— 没填就用默认。"""
    raw = USER.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "关", "否")


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


BROWSER_DEFAULTS = {
    "enabled": True,
    "record": True,
    "exclude_domains": [],
    "history_days": 30,
    "close_on_exit": True,
}


def _clean_domain(raw) -> str:
    """把 `https://Example.com/路径` / ` example.com ` 一律整成 `example.com`。"""
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        try:
            text = urllib.parse.urlsplit(text).hostname or ""
        except ValueError:
            return ""
    return text.strip(". ")


def browser_settings() -> dict:
    """读 `设置.json` 的 browser 块：默认值 + 类型清洗，读坏了不让启动失败。"""
    raw = load_settings().get("browser")
    raw = raw if isinstance(raw, dict) else {}

    def flag(key: str) -> bool:
        value = raw.get(key)
        if isinstance(value, bool):
            return value
        if value is None or str(value).strip() == "":
            return bool(BROWSER_DEFAULTS[key])
        return str(value).strip().lower() not in ("0", "false", "no", "off", "关", "否")

    try:
        days = int(str(raw.get("history_days") or BROWSER_DEFAULTS["history_days"]).strip())
    except (TypeError, ValueError):
        days = BROWSER_DEFAULTS["history_days"]
    domains = raw.get("exclude_domains")
    if not isinstance(domains, list):
        domains = []
    cleaned: list[str] = []
    for item in domains:
        domain = _clean_domain(item)
        if domain and domain not in cleaned:
            cleaned.append(domain)
    return {
        "enabled": flag("enabled"),
        "record": flag("record"),
        "exclude_domains": cleaned,
        "history_days": max(1, min(365, days)),
        "close_on_exit": flag("close_on_exit"),
    }


def update_browser_settings(**changes) -> dict:
    """只改 browser 块并原子写回 `设置.json`；返回清洗后的当前值。"""
    data = load_settings()
    if not data:
        data = json.loads(json.dumps(SETTINGS_TEMPLATE, ensure_ascii=False))
    block = data.get("browser")
    if not isinstance(block, dict):
        block = {}
    for key, value in changes.items():
        if key in BROWSER_DEFAULTS:
            block[key] = value
    data["browser"] = block
    target = pathlib.Path(SETTINGS_FILE)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, target)
    except OSError:
        pass                      # 设置写不进去也不拦功能，界面上会看到开关没变
    USER.clear()
    USER.update(data)
    return browser_settings()


def browser_profile_dir() -> pathlib.Path:
    return DATA_ROOT / "浏览器配置"


def browser_download_dir() -> pathlib.Path:
    return DATA_ROOT / "浏览器下载"


def day_dir(when=None) -> pathlib.Path:
    """那天的文件夹，例如 D:\学习系统\2026.10.2"""
    moment = when or datetime.datetime.now()
    return DATA_ROOT / f"{moment.year}.{moment.month}.{moment.day}"


def materials_dir() -> pathlib.Path:
    """资料库根目录：原文与回收站都在这下面（自动进备份）。"""
    return DATA_ROOT / "资料库"


def db_path_in(root) -> pathlib.Path:
    """指定数据目录下的统一库；测试和按 cfg.data_root 记账时用这一份。"""
    return pathlib.Path(root) / "learning.db"


def db_path(when=None) -> pathlib.Path:
    """统一库：所有日子的问答、转写、窗口、会话都在这里。

    `when` 参数保留只为兼容旧调用；v2 不再按天分库。
    按天的文件夹仍由 `day_dir()` 管，只放截图 / 录屏 / 报告。
    """
    return db_path_in(DATA_ROOT)


def cet6_dir_candidates() -> list[pathlib.Path]:
    """六级精听目录的候选位置：设置 → 环境变量 → 仓库同级 / 可选模块。

    开源仓库里不带真题音频，这个目录是**可选模块**：找不到时 `/cet6` 返回 404，
    不影响问答主功能。
    """
    cands: list[pathlib.Path] = []
    raw = str(USER.get("cet6_dir") or "").strip() or os.environ.get("LEARNSYS_CET6_DIR", "").strip()
    if raw:
        cands.append(pathlib.Path(raw).expanduser())
    if FROZEN:                                  # exe 在 dist/学习工作台/ 里
        cands.append(ROOT.parent.parent.parent / "六级精听")
    else:                                       # 源码在 D:\Desktop\learnsys
        cands.append(ROOT.parent / "六级精听")
    cands.append(ROOT / "cet6")                 # 也可以把可选模块放进仓库
    return cands


def cet6_dir() -> pathlib.Path:
    """六级精听根目录（含 `工作台\\精听工作台.html` 与 `试卷\\`）。"""
    cands = cet6_dir_candidates()
    for cand in cands:
        if (cand / "工作台" / "精听工作台.html").exists():
            return cand
    return cands[0]


def cet6_workbench() -> pathlib.Path:
    return cet6_dir() / "工作台" / "精听工作台.html"


def ask_tmp_dir() -> pathlib.Path:
    """那天的截图临时目录（问完即删）"""
    return day_dir() / "截图"


def ask_image_dir() -> pathlib.Path:
    """那天的「问答截图」归档目录 —— 有图提问的截图存这里，方便复盘"""
    return day_dir() / "问答截图"


SETTINGS_PATH = DATA_ROOT / "界面设置.json"   # 横栏的位置 / 收起状态
ICON_PATH = ROOT / "学习工作台.ico"          # 托盘 / 窗口 / favicon 的图标（首次启动自动生成）

# ---- 前台窗口 ----
WINDOW_SAMPLE_SECONDS = 1.0
# 「开始记录」之后要不要连窗口标题一起记。标题能认出「这节课在讲什么」，
# 但也可能带私人信息（聊天对象、银行页面）⇒ 介意就在 设置.json 里设成 false，只记程序名。
RECORD_WINDOW_TITLE = _user_bool("record_window_title", True)

# ---- 声音（系统回环）→ 本地转写 ----
CHUNK_SECONDS = 45.0        # 每攒多少秒的录音转一次
#   实测：一段越长上下文越足，但落库越晚。120s 段 = 222 字/分钟（准），25s 段遇到板书空档只剩 38 字/分钟。
#   45s 是折中：转写约 12s 追得上，落后约 1 分钟。想更实时就调小。
SILENCE_RMS = 0.003         # 响度低于这个就跳过：静音不花算力、不落库
MIN_CHUNK_SECONDS = 2.0     # 短于这个的碎块直接丢掉

def _model_dir() -> str:
    """whisper 模型目录：源码在 ROOT/models；打包后 exe 在 dist/学习工作台/ 里，
    往上两级找仓库根的 models（拷出去没有模型 ⇒ 用默认路径，转写会报「加载失败」）。"""
    for cand in (ROOT / "models" / "small", ROOT.parent.parent / "models" / "small"):
        if (cand / "model.bin").exists():
            return str(cand)
    return str(ROOT / "models" / "small")

ASR_MODEL_DIR = _model_dir()
ASR_DEVICE = "cpu"          # 想用显卡填 "cuda"（要先装 cuDNN/cuBLAS）
ASR_COMPUTE_TYPE = "int8"   # cuda 时改成 "float16"
ASR_LANGUAGE = "zh"
ASR_BEAM_SIZE = 5
ASR_VAD = True              # 静音切段；失败会自动退回 False
# ---- 问一问（框选屏幕 → 问 AI）----
# 下面带「设置.json」的几项都能在 D:/学习系统/设置.json 里改 —— 打包成 exe 后就靠它
ASK_HOTKEY = USER.get("hotkey") or "alt+q"   # 全局快捷键：修饰键(alt/ctrl/shift/win) + 主键
# 启动时自动弹出学习台窗口（Edge/Chrome 的应用模式）；不想每次都弹就设 false
WORKBENCH_ON_START = _user_bool("workbench_on_start", True)
# 已安装的 PWA app-id（如 ndclga…）：有的话打开工作台直接拉起它 —— 任务栏才有独立的
# 「学习工作台」按钮；留空 = 退回 Edge --app 窗口（会和普通 Edge 窗口分到一组）。
PWA_APP_ID = str(USER.get("pwa_app_id") or os.environ.get("LEARNSYS_PWA_APP_ID") or "").strip()
# ---- 录像（P23）：主屏 + 系统声音 → 标准 MP4 ----
VIDEO_ENABLED = _user_bool("video_enabled", True)
VIDEO_FPS = max(5, min(15, _user_int("video_fps", 10)))
VIDEO_MAX_WIDTH = max(640, min(2560, _user_int("video_max_width", 1600)))
VIDEO_MAX_SECONDS = max(600, _user_int("video_max_seconds", 3 * 3600))
VIDEO_MAX_BYTES = max(256 * 1024 * 1024, _user_int("video_max_bytes", 8 * 1024**3))
_raw_video_dir = str(USER.get("video_dir") or "").strip()
VIDEO_DIR = pathlib.Path(_raw_video_dir) if _raw_video_dir else (DATA_ROOT / "录像")
if not VIDEO_DIR.is_absolute():
    VIDEO_DIR = DATA_ROOT / VIDEO_DIR
# 录像开关/停止的全局快捷键：横栏会藏起来，靠它或托盘菜单停止
RECORD_HOTKEY = str(USER.get("record_hotkey") or "ctrl+alt+s")
ASK_TIMEOUT_SECONDS = 90.0      # 等 AI 回话的上限；超时就在横条里给中文提示，不装死
# 答案最长多少 token —— **只用来防失控，不能用来提速**：
# 实测 deepseek-flash 是推理模型，思考过程也吃这份配额（一次回答 240 token 里 117 个是推理），
# 设小了会「想完了没额度写正文」⇒ 答案直接是空的。默认 1500 够写一大段，**别往下调**。
ASK_MAX_TOKENS = _user_int("max_tokens", 1500)
ASK_HISTORY_TURNS = 3           # 追问时带给 AI 的前几轮问答（同一张图；换了图就清）

# 问谁：默认打本机 Codex 的中转口（一次 HTTP 约 1~3 秒、不用 key、但要 Codex 开着）；
# 在 设置.json 里填 api_base / api_key / api_model 就换成任何「OpenAI 兼容 + 能看图」的服务。
ASK_API_BASE = USER.get("api_base") or "http://127.0.0.1:57321/v1"
ASK_API_MODEL = USER.get("api_model") or "deepseek-flash"
ASK_API_KEY = USER.get("api_key") or ""
ASK_API_STYLE = USER.get("api_style") or ""   # "" = 自动（本机走 responses，别处走 chat）

# 让 AI 直接给答案、别倒思考过程、别堆 Markdown（负责人：「** 特别多、像整个思考过程」）
ASK_SYSTEM_PROMPT = USER.get("system_prompt") or (
    "你是屏幕问答助手。只根据用户提供的截图回答问题。"
    "回答要求：直接给出结论，简洁；用纯文本，不要 Markdown（禁止 **加粗**、#标题、>引用、- 列表符号）；"
    "不要输出思考过程、推理步骤、分析过程或「让我看看」这类铺垫；不要复述问题；"
    "除非用户要求详细展开，否则控制在 200 字以内（模型要想很久，答案越长等得越久）；"
    "如果截图里没有答案，就直说没看出来。"
)
# 没框图、纯文字问的时候用这条（框选是可选的）
ASK_SYSTEM_PROMPT_TEXT = USER.get("system_prompt_text") or (
    "你是学习问答助手，直接回答用户的问题。"
    "回答要求：直接给出结论，简洁；用纯文本，不要 Markdown（禁止 **加粗**、#标题、>引用、- 列表符号）；"
    "不要输出思考过程、推理步骤、分析过程或「让我看看」这类铺垫；不要复述问题；"
    "除非用户要求详细展开，否则控制在 200 字以内。"
)


def api_style() -> str:
    """按哪种协议说话：本机中转 = Responses；自己填的 = OpenAI 兼容 /chat/completions。

    填 `api_style` 只认 `chat` / `responses`（其它值当没填，自动判）——
    免得拼错一个字母就整个走错协议、报一堆看不懂的错。
    """
    style = str(ASK_API_STYLE or "").strip().lower()
    if style in ("chat", "responses"):
        return style
    host = (urllib.parse.urlsplit(ASK_API_BASE).hostname or "").lower()
    return "responses" if host in ("127.0.0.1", "localhost", "::1") else "chat"

# 顶部横条的尺寸
ASK_BAR_WIDTH_RATIO = 0.82        # 占屏幕宽度的比例
ASK_BAR_WIDTH_MAX = 1400          # 最宽不超过
ASK_BAR_TOP_GAP = 10              # 离屏幕顶端多远
ASK_BAR_ANSWER_MAX_RATIO = 0.62   # 答案区最高占屏幕高度的比例（再长就滚动）
ASK_BAR_ANSWER_DEFAULT_H = 420    # 答案面板默认高度（固定，拖底边才改）
ASK_BAR_ANSWER_MIN_H = 160        # 答案面板最矮拖到多少
ASK_BAR_PILL_WIDTH = 250          # 收起成一条小条后有多宽
ASK_BAR_ALWAYS_ON_TOP = False     # 不再强制置顶（负责人：挡别的界面）；横栏上「置顶」开关随时改

# 热词：当 initial_prompt 喂给模型，能显著压掉成体系的同音错
HOTWORDS = (
    "以下是中文计算机课程录音。常用术语：数据结构、线性表、顺序表、链表、单链表、双链表、"
    "栈、队列、循环队列、串、数组、广义表、树、二叉树、完全二叉树、满二叉树、遍历、前序、"
    "中序、后序、层序、线索二叉树、森林、哈夫曼树、图、顶点、边、邻接矩阵、邻接表、"
    "深度优先、广度优先、最小生成树、最短路径、拓扑排序、查找、折半查找、哈希表、"
    "排序、冒泡排序、快速排序、归并排序、堆、时间复杂度、空间复杂度、渐进、算法、绪论、"
    "抽象数据类型、数据项、数据元素、逻辑结构、存储结构、栈顶、栈底、队头、队尾。"
)
