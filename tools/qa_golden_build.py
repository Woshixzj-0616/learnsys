"""生成 P35.0 问答 golden set（50 条）。

数据源：2026-10-24 ~ 2026-11-23 的真实问答（`asks` / `conversations`）。
本脚本只写 `docs/golden/qa-golden-50.json`，不连模型、不写学习数据。
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter


def case(id, category, question, *, source_ask_ids=None, source_run_id=None,
         conversation_id=None, turns=None, fact_groups=None, must_not=None,
         tools_any=None, citation="none", source="model", max_turns=1, notes="",
         manual_review=False):
    item = {"id": id, "category": category, "question": question}
    if source_ask_ids:
        item["source_ask_ids"] = source_ask_ids
    if source_run_id:
        item["source_run_id"] = source_run_id
    if conversation_id:
        item["conversation_id"] = conversation_id
    if turns:
        item["turns"] = turns
    if manual_review:
        item["manual_review"] = True
    item["expected"] = {
        "fact_groups": fact_groups or [],
        "must_not": must_not or [],
        "tools_any": tools_any or [],
        "citation": citation,
        "source": source,
        "max_turns": max_turns,
    }
    if notes:
        item["notes"] = notes
    return item


CASES = [
    # ---------- 事实题 12 ----------
    case("fact-cpp-pair-header", "事实题", "c++ pair定义在哪个头", source_ask_ids=[696],
         fact_groups=[["utility", "<utility>"]], citation="none", source="model"),
    case("fact-cpp-intmax-header", "事实题", "INT_MAX是定义在哪里", source_ask_ids=[697],
         fact_groups=[["climits", "limits.h"]], citation="none", source="model"),
    case("fact-cpp-emplace-header", "事实题", "emplace定义在哪个头", source_ask_ids=[699],
         fact_groups=[["成员", "member", "容器"], ["vector", "map", "set"]],
         citation="none", source="model",
         notes="要点：没有独立的 emplace 头，是容器成员。"),
    case("fact-cpp-stack-empty", "事实题", "stack的empty是怎么返回的", source_ask_ids=[707],
         fact_groups=[["bool", "true", "false"], ["size", "empty", "top"]],
         citation="none", source="model"),
    case("fact-net-rsync-algo", "事实题", "rsync的算法是什么", source_ask_ids=[678],
         fact_groups=[["滚动", "rolling"], ["弱校验", "强校验", "checksum"]],
         citation="none", source="model"),
    case("fact-net-mtu-1472", "事实题", "为什么我的mtu只有1472，28B的头开销在哪", source_ask_ids=[265],
         fact_groups=[["28"], ["20"], ["8"]], citation="none", source="model"),
    case("fact-algo-block-plus1", "事实题", "为什么这个分块查找平均查找长度里面还要加1", source_ask_ids=[269],
         fact_groups=[["块间", "索引表"], ["折半", "判定树", "log"]],
         citation="none", source="model"),
    case("fact-algo-quicksort-worst", "事实题",
         "请用三句话解释：为什么快速排序最坏是 O(n^2)，以及怎样避免。",
         source_run_id=79,
         fact_groups=[["有序", "逆序", "已排序"], ["随机", "三数取中", "median"]],
         citation="none", source="model",
         notes="唯一一次 v4-pro 运行的题，用作强模型对照。"),
    case("fact-net-tcp-fin", "事实题", "客户端在tcp连接发送FIN时ack会置为0吗", source_ask_ids=[342],
         fact_groups=[["FIN"], ["ACK"], ["序号", "序列号"]],
         must_not=["ACK 置 0", "ack 会置为 0", "ACK 标志变成 0"],
         citation="none", source="model"),
    case("fact-net-nginx-80-8080", "事实题",
         "为什么我nginx设置两个server一个是80一个是8080，给的html不一样，但是在本机浏览器看是一个html",
         source_ask_ids=[295],
         fact_groups=[["端口", "port"], ["默认", "default", "Host", "server_name"]],
         citation="none", source="model"),
    case("fact-english-8", "事实题", "8分的英语翻译是什么水平，六级里面多少分", source_ask_ids=[271],
         fact_groups=[["7-9", "7–9", "7~9"], ["710", "106.5", "55", "60"]],
         citation="none", source="model"),
    case("fact-net-tcp-handshake", "事实题", "用一句话解释 TCP 三次握手", source_ask_ids=[653],
         fact_groups=[["SYN", "初始序号", "seq"], ["ACK", "确认", "双向通道"]],
         citation="none", source="model"),

    # ---------- 多轮纠错 10 ----------
    case("multi-cpp-emplace", "多轮纠错",
         "res.emplace(poi[minpoi], min) 报错；res 是 vector<pair<char,int>>。错在哪？",
         source_ask_ids=[701, 702, 703, 704, 705],
         turns=["res.emplace(poi[minpoi], min);我这个报错了，其中minpoi，和min是int，poi是vector<char>,res是vector<char,int>",
                "vector<pair<char, int>>res;",
                "（贴出完整代码）",
                "就是emplace有问题，你听不懂吗",
                "那emplace要怎么写"],
         fact_groups=[["第一个参数", "位置参数", "迭代器", "const_iterator"],
                      ["emplace_back", "插入位置", "C++11"]],
         citation="none", source="model", max_turns=3,
         notes="正确事实：vector 有 emplace(pos, args...)，第一个参数是位置迭代器；用户只传了 (char,int)，所以编译失败。前两轮可能说错，第 3 轮 run_code 后应纠正。"),
    case("multi-rsync-locate", "多轮纠错", "rsync 是怎么定位错误的？",
         conversation_id=144,
         turns=["那怎么定位错误",
                "我想问你是怎么定位错误的",
                "我说的是rsync是怎么定位错误的",
                "那你不是说他会窗口移动吗，这个不就是定位错误的",
                "是有错的块才会定位错误吗",
                "他难道不会识别文件中是哪个地方改动了吗"],
         fact_groups=[["滑动窗口", "滚动", "rolling", "块"],
                      ["字节", "行", "diff", "不输出", "不告诉", "第几行",
                       "第几字节", "行号", "位置"]],
         citation="none", source="model", max_turns=2, manual_review=True,
         notes="正确口径：滑动窗口定位的是块级差异；rsync 不输出字节/行位置。基线/试点看第几轮才收敛，目标 ≤2。"),
    case("multi-rsync-window", "多轮纠错", "rsync 的滚动窗口和块匹配到底是什么关系？",
         conversation_id=145,
         turns=["和我说说rsync", "和我说说内部算法", "不是有滚动窗口的机制吗", "你和我整体说说",
                "接收端只是按块给强弱校验，发送端怎么能通过L的窗口匹配",
                "会不会出现块数新旧分割不相等的情况",
                "窗口强弱校验都对上会发生什么",
                "发送端重发的块应该会出现块大小不等的情况吧"],
         fact_groups=[["滚动", "窗口"], ["块", "L"]],
         citation="none", source="model", max_turns=2,
         notes="内容基本正确，但连续 38 条消息才收敛；检查是否在第 2 轮就给出整体框架。"),
    case("multi-quicksearch-key", "多轮纠错",
         "快速查找/快速排序里，key 的位置被分区移动了怎么办？",
         source_ask_ids=[655, 656, 657, 658, 659, 660, 661],
         turns=["这题咋做",
                "你这样还不如直接顺序查找呢",
                "那不会在排的过程把值移动了吗",
                "你直接给我代码",
                "你这样要是把key的位置移动了怎么办",
                "我说的是我们要找的key",
                "我说的是他本来是在原来位置上，但是因为我们的排序而变了位置"],
         fact_groups=[["原位置", "位置", "下标"],
                      ["移动", "变", "保留", "排下标", "pos", "原数组"]],
         citation="none", source="model", max_turns=7, manual_review=True,
         notes="完整题链：655–658 是上下文，659–661 是纠正。看是否在上下文中解决 key 指代；正确口径是「排数据本身会移位置，排下标/带 pos 可保留」。"),
    case("multi-siege-admin", "多轮纠错",
         "老师给的 siege 命令访问 Admin.jsp 一直 404，怎么排查？",
         conversation_id=70,
         turns=["Admin.jsp是什么，我的老师给我这个命令让我输入，这个不是siege自己提供的吗",
                "但是这个文件我根本没有写过，我也不会写啊",
                "但是我的是虚拟机不是靶机",
                "我都和你说了没有，你听不懂吗"],
         fact_groups=[["没有 Admin.jsp", "文件不存在", "靶机"], ["老师", "部署包", "地址"]],
         citation="none", source="model", max_turns=2, manual_review=True,
         notes="核心失败：用户已排除本机文件，仍重复建议 ls/docker/ss；关键词容易误判，必须人工复核。"),
    case("multi-logic-or", "多轮纠错", "&(|(f),f) 里的 | 到底是什么意思？",
         conversation_id=119,
         turns=["或运算还能只对一个表达式做吗", "&(|(f),f)这个表达式的|不就是这样",
                "什么意思，所以|（f）是什么意思", "这是逻辑或，你是不是搞错了",
                "就是一个|，这到底是什么意思"],
         fact_groups=[["二元", "两个操作数"], ["||", "逻辑或"]],
         citation="none", source="model", max_turns=3, manual_review=True,
         notes="核心失败：没有先确认是宏/前缀表达式还是普通运算符，连续要求贴原文。"),
    case("multi-block-plus1", "多轮纠错",
         "分块查找的平均查找长度里，块间那部分的 +1 为什么存在？",
         source_ask_ids=[269, 270],
         turns=["为什么这个分块查找平均查找长度里面还要加1",
                "你还是没回答为什么在快间加一"],
         fact_groups=[["块间", "索引表"], ["折半", "判定树", "log"]],
         citation="none", source="model", max_turns=1, manual_review=True,
         notes="人工复核：269 已提到块间，但用户仍认为没答到；检查是否答到 +1 的来源。"),
    case("multi-curl-missing", "多轮纠错", "服务器上没有 curl 命令，怎么办？",
         source_ask_ids=[555], turns=["我说的是没有curl这个命令"],
         fact_groups=[["安装", "install", "apt", "yum", "dnf", "apk"], ["curl"]],
         citation="none", source="model", max_turns=1),
    case("multi-server-ip", "多轮纠错",
         "DHCP Request 为什么不直接单播给服务器 IP，而要广播？",
         source_ask_ids=[255], turns=["我说的是给他服务器的ip地址"],
         fact_groups=[["广播", "broadcast"], ["单播", "unicast"],
                      ["server identifier", "服务器标识"]],
         citation="none", source="model", max_turns=1),
    case("multi-rsync-block-size", "多轮纠错",
         "发送端重发的块会出现块大小不等的情况吗？",
         source_ask_ids=[695],
         turns=["发送端重发的块应该会出现块大小不等的情况吧"],
         fact_groups=[["字面量", "literal"], ["块长", "L"]],
         citation="none", source="model", max_turns=1),

    # ---------- 本地资料 / 学习数据 10 ----------
    case("local-wrong-items", "本地数据", "我最近错了哪些题？",
         tools_any=["recent_wrong_items"], citation="wrong", source="local"),
    case("local-due-reviews", "本地数据", "今天有哪些到期要复习的？",
         tools_any=["due_reviews"], citation="none", source="local"),
    case("local-mastery", "本地数据", "我最弱的知识点是什么？",
         tools_any=["get_mastery"], citation="none", source="local",
         notes="样本不足时必须直说样本不足。"),
    case("local-train-summary", "本地数据", "我的写作/翻译练得怎么样？",
         tools_any=["get_train_summary"], citation="none", source="local"),
    case("local-today", "本地数据", "我今天学了什么？",
         tools_any=["today_summary"], citation="none", source="local"),
    case("local-materials-tcp", "本地数据", "课件里 TCP 三次握手是怎么讲的？",
         tools_any=["search_materials"], citation="material", source="local"),
    case("local-materials-rsync", "本地数据", "资料库里关于 rsync 的内容有哪些？",
         tools_any=["search_materials"], citation="material", source="local",
         notes="如果资料库没有，必须直说没有，不能编造资料名/页码。"),
    case("local-records-python", "本地数据", "我之前问过什么关于 Python 的问题？",
         tools_any=["search_records"], citation="conversation", source="local"),
    case("local-local-file", "本地数据", "我电脑上那份计算机网络 PDF 在哪？",
         tools_any=["search_local_files"], citation="none", source="local",
         notes="白名单外读取要确认；找不到就直说。"),
    case("local-vocab", "本地数据", "我生词本里有哪些词？",
         tools_any=["list_vocab"], citation="none", source="local",
         notes="P35.0 基线时是能力缺口（没有 list_vocab）；P35.1 已补，当前期望工具为 list_vocab。"),

    # ---------- 英语批改 7 ----------
    case("english-reunion-translation", "英语批改",
         "年夜饭的菜名也常带有吉祥的含义，例如鱼象征年年有余。给我译文",
         source_ask_ids=[631],
         fact_groups=[["auspicious", "吉祥"], ["symbol", "象征"],
                      ["surplus", "abundance", "有余"]],
         citation="none", source="model"),
    case("english-fish-correction", "英语批改",
         "The reunion dinner's dishes often have a happy meaning, for example, fish is symbol of abundance year after year.",
         conversation_id=146,
         fact_groups=[["a symbol of"], ["auspicious", "carry"]],
         citation="none", source="model"),
    case("english-fireworks", "英语批改",
         "Recently, some cities was restricted with burning fireworks and firecrackers, but the reunion habit is never changed.",
         source_ask_ids=[709],
         fact_groups=[["were"], ["restricted", "banned"], ["tradition", "habit"]],
         citation="none", source="model"),
    case("english-student-translation", "英语批改",
         "Despite the long distance to go home, people make their best efforts to go back and stay up late to see the old year out with their family.",
         source_ask_ids=[633],
         fact_groups=[["journey home", "distance home"],
                      ["every effort", "best efforts"],
                      ["see out", "see the old year out"]],
         citation="none", source="model"),
    case("english-abstract", "英语批改", "abstract 的意思是什么？",
         fact_groups=[["抽象"], ["摘要", "abstract"]],
         citation="none", source="model"),
    case("english-directory", "英语批改", "目录的英文", source_ask_ids=[388],
         fact_groups=[["directory"], ["dir"]], citation="none", source="model"),
    case("english-ls", "英语批改", "ls是什么英文缩写", source_ask_ids=[391],
         fact_groups=[["list"], ["列出", "目录"]], citation="none", source="model"),

    # ---------- 代码调试 7 ----------
    case("code-prefix-expr", "代码调试", "前缀算术表达式求值：贴代码问哪里错。",
         source_ask_ids=[457, 455, 454, 452], fact_groups=[["前缀"], ["栈"], ["输出", "用例"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-subip", "代码调试", "subip 字符串处理代码：贴代码问哪里错。",
         source_ask_ids=[634, 635], fact_groups=[["subip", "字符串"], ["越界", "长度", "bug"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-infix-stack", "代码调试", "基于栈的中缀表达式求值：贴代码问哪里错。",
         source_ask_ids=[201, 195], fact_groups=[["中缀", "表达式"], ["栈"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-quicksearch", "代码调试", "快速查找/快速排序代码：贴代码问哪里错。",
         source_ask_ids=[655, 657, 658], fact_groups=[["Partition", "分区"], ["key", "查找"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-bf", "代码调试", "基于 BF 算法的网络入侵检测：贴代码问哪里错。",
         source_ask_ids=[628], fact_groups=[["BF", "暴力"], ["匹配"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-pattern", "代码调试", "模式匹配算法：贴代码问哪里错。",
         source_ask_ids=[638, 637], fact_groups=[["模式匹配", "KMP", "next"], ["前缀", "字符串"]],
         tools_any=["run_code"], citation="none", source="local+model"),
    case("code-structG", "代码调试", "struct G / int** 数组代码：贴代码问哪里错。",
         source_ask_ids=[205], fact_groups=[["int**", "二维"], ["delete", "释放", "越界"]],
         tools_any=["run_code"], citation="none", source="local+model"),

    # ---------- 补足 4 条 ----------
    case("fact-rsync-fullname", "事实题", "rsync全名", source_ask_ids=[623],
         fact_groups=[["remote", "远程"], ["sync", "同步"]], citation="none", source="model"),
    case("fact-nginx-restart", "事实题", "nginx怎么重启", source_ask_ids=[292],
         fact_groups=[["reload"], ["systemctl", "restart", "nginx -s"]],
         citation="none", source="model"),
    case("multi-cert-L", "多轮纠错", "我说的是证书签名里面的 L 是什么",
         source_ask_ids=[591], turns=["我说的是证书签名里面的L是什么"],
         fact_groups=[["长度", "Length"], ["ASN.1", "DER", "TLV", "签名"]],
         citation="none", source="model", max_turns=1,
         notes="问题本身歧义；合格行为是先给候选解释并要求原句，不是硬编一个答案。"),
    case("local-cet6-context", "本地数据", "我刚才循环的那句是什么？",
         tools_any=["get_cet6_context"], citation="none", source="local",
         notes="没有上下文快照时应要求用户从精听页唤起，而不是编造句子。"),
]


def main() -> None:
    payload = {
        "version": 1,
        "updated_at": "2026-11-24",
        "note": ("P35.0 问答 golden set。题目来自 2026-10-24~2026-11-23 的真实问答；"
                 "baseline 用历史答案回溯评分，不新调模型。合成题（无 source_ask_ids）留给在线评测。"),
        "scoring": {
            "fact_groups": "每组至少命中一个词才算该组通过；所有组通过才算事实通过。",
            "must_not": "答案里出现任一字符串即判失败。",
            "tools_any": "trace/工具轨迹里出现任一工具即算用对；回溯基线从 agent_runs 取。",
            "citation": "material=需带资料 id/页码；wrong=需带错题 #；conversation=需带问答时间；web=需带 URL；none=不要求。",
            "max_turns": "多轮从第 1 轮开始数，直到事实通过；超过即失败。",
            "manual": "关键词只做初筛，歧义题必须人工复核。",
        },
        "cases": CASES,
    }
    path = pathlib.Path(__file__).resolve().parent.parent / "docs" / "golden" / "qa-golden-50.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已写", path, "用例", len(CASES))
    print(dict(Counter(item["category"] for item in CASES)))
    ids = [item["id"] for item in CASES]
    dup = sorted({item for item in ids if ids.count(item) > 1})
    print("重复 id:", "、".join(dup) if dup else "无")


if __name__ == "__main__":
    main()
