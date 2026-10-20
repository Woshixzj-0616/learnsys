// 网工训练场：按 TCP/IP 分层组织训练卡；开练 = 记一条事件 + 把题目送进问一问。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const TRACKS = [
  {
    id: "addr", index: "01", name: "地址与子网", legend: "基础中的基础：算得出来，才看得懂拓扑。",
    cards: [
      {
        id: "cidr", title: "CIDR 速算", level: "基础",
        desc: "/24、/26、/28 各能装多少台主机？30 秒内反应出来。",
        points: ["可用主机 = 2^(32-前缀) − 2", "/25 = 128 地址 / 126 主机；/26 = 64 / 62；/27 = 32 / 30", "网络地址与广播地址不能分给主机"],
        prompt: "我是网络工程专业大二学生，正在练 CIDR 速算。请先用一句话讲清「前缀长度 → 地址数 → 可用主机数」的关系，然后连续出 10 道小题（给一个前缀或地址/掩码，问我网络地址、广播地址、可用主机数）。每次只出一题，等我回答后再批改并解释。",
      },
      {
        id: "subnet", title: "子网划分", level: "基础",
        desc: "192.168.10.0/24 切成 4 个等长子网，写出每个的网段和广播地址。",
        points: ["借 2 位 → 4 个子网，块大小 64", "子网边界看「块大小」而不是十进制直觉", "每个子网的第一个地址是网络号，最后一个是广播"],
        prompt: "我是网络工程专业大二学生。请先讲「借位划子网」的块大小法，然后出题：把 192.168.10.0/24 划成 4 个等长子网，让我写出每个子网的网络地址、可用范围和广播地址。一次只问一个子网，等我答完再批改。",
      },
      {
        id: "summarize", title: "路由汇总", level: "进阶",
        desc: "把四条明细路由压成一条汇总，找出最长公共前缀。",
        points: ["汇总 = 二进制最长公共前缀", "先对齐前缀，再数相同位数", "汇总过宽会把不属于自己的流量吸进来"],
        prompt: "我是网络工程专业大二学生。请讲清「路由汇总 = 最长公共前缀」的方法，然后给我 4 条明细路由（例如 172.16.0.0/24 到 172.16.3.0/24），让我算汇总路由。先让我自己算，再批改并说明汇总过宽的代价。",
      },
    ],
  },
  {
    id: "l2", index: "02", name: "二层交换", legend: "交换机只看 MAC，但 MAC 表怎么来的要说得清。",
    cards: [
      {
        id: "mac-table", title: "MAC 地址表", level: "基础",
        desc: "为什么第一次 ping 会泛洪，第二次就直送？",
        points: ["源 MAC 学习：从哪个口来就记哪个口", "目的 MAC 未知 → 泛洪；已知 → 单播转发", "表项有老化时间，默认常见 300 秒"],
        prompt: "我是网络工程专业大二学生。请用一个两台交换机、四台主机的拓扑，讲清 MAC 地址表如何学习、泛洪和老化；然后出一道「第一次 ping 和第二次 ping 路径有什么不同」的判断题，等我回答后批改。",
      },
      {
        id: "vlan", title: "VLAN 与 Trunk", level: "进阶",
        desc: "Access 口和 Trunk 口的区别，802.1Q 标签加在哪。",
        points: ["Access：一个口属于一个 VLAN，通常不打标签", "Trunk：多个 VLAN 共用一条链路，靠 802.1Q tag 区分", "Native VLAN 的帧不打标签，两侧必须一致"],
        prompt: "我是网络工程专业大二学生。请讲清 Access 口、Trunk 口和 802.1Q 标签的关系，然后给我一个「两台交换机 + 两个 VLAN + 一条 Trunk」的场景，问我某个帧从 PC 发出后到对端 PC 的标签变化过程，等我回答后批改。",
      },
      {
        id: "stp", title: "STP 选举", level: "进阶",
        desc: "根桥、根端口、指定端口、阻塞端口，按什么顺序选？",
        points: ["先选根桥：桥 ID 最小（优先级 + MAC）", "每个非根交换机选一个根端口：到根桥开销最小", "每条网段选一个指定端口；剩下的阻塞"],
        prompt: "我是网络工程专业大二学生。请讲清 STP 的选举顺序（根桥 → 根端口 → 指定端口 → 阻塞），然后画一个三台交换机的环，让我判断每台交换机的端口角色。一次只问一台，等我答完再批改。",
      },
    ],
  },
  {
    id: "l3", index: "03", name: "三层路由", legend: "路由表不是清单，是「最长匹配」的决策表。",
    cards: [
      {
        id: "route-table", title: "路由表阅读", level: "基础",
        desc: "目的地址同时命中两条路由，走哪条？",
        points: ["先看目的网络，命中多条取最长前缀", "前缀相同再比管理距离 / 度量", "默认路由 0.0.0.0/0 是最后兜底"],
        prompt: "我是网络工程专业大二学生。请讲清路由表「最长前缀匹配」和「管理距离/度量」的先后顺序，然后给我一张小型路由表和一个目的 IP，让我判断走哪条路由。一次一题，等我答完再批改。",
      },
      {
        id: "ospf", title: "OSPF 邻居", level: "进阶",
        desc: "为什么两台路由器直连却卡在 ExStart？",
        points: ["Hello 里关键字段：Router ID、Area、Hello/Dead、网络类型、认证", "卡 ExStart 常见 MTU 不一致", "DR/BDR 只在广播型网络选举"],
        prompt: "我是网络工程专业大二学生。请讲清 OSPF 邻居建立的主要状态和常见卡住原因（Hello、MTU、Area、认证），然后给我三个故障现象，让我判断最可能卡在哪个阶段。等我答完再批改。",
      },
      {
        id: "static-default", title: "静态与默认路由", level: "基础",
        desc: "默认路由、浮动静态路由、回程路由分别解决什么？",
        points: ["默认路由 0.0.0.0/0 指向出口", "浮动静态用更大的管理距离做备份", "只有去程没有回程 = 单向通，ping 仍失败"],
        prompt: "我是网络工程专业大二学生。请讲清默认路由、浮动静态路由和回程路由的区别，然后给我一个「主链路断了要自动切备用」的小场景，让我写出配置思路。等我答完再批改。",
      },
    ],
  },
  {
    id: "tcp", index: "04", name: "TCP/IP 传输", legend: "抓包看到的每一个标志位，都有状态机在背后。",
    cards: [
      {
        id: "handshake", title: "三次握手 / 四次挥手", level: "基础",
        desc: "SYN、SYN-ACK、ACK 分别在确认什么？TIME_WAIT 为什么存在？",
        points: ["三次握手同步双方初始序列号", "四次挥手因为 TCP 全双工，两个方向分别关", "TIME_WAIT 等 2MSL，保证旧报文消散"],
        prompt: "我是网络工程专业大二学生。请讲清 TCP 三次握手和四次挥手每一步在确认什么，以及 TIME_WAIT 存在的原因；然后出一道「抓包里少了哪个包会导致什么状态」的题，等我回答后批改。",
      },
      {
        id: "congestion", title: "拥塞控制", level: "进阶",
        desc: "慢启动、拥塞避免、快重传、快恢复，各在什么信号下切换？",
        points: ["慢启动：cwnd 指数增长", "到 ssthresh 后转拥塞避免：线性增长", "三个重复 ACK = 快重传；超时 = 回到慢启动"],
        prompt: "我是网络工程专业大二学生。请讲清 TCP 拥塞控制的四个阶段和切换信号，然后给我一段 cwnd 随时间变化的描述，让我判断发生了超时还是三个重复 ACK。等我答完再批改。",
      },
      {
        id: "nat", title: "NAT 与端口复用", level: "进阶",
        desc: "一个公网 IP 怎么同时服务几十台内网主机？",
        points: ["NAT 改写源/目的 IP；NAPT 再加端口", "五元组唯一标识一条连接", "NAT 表项有老化时间，长连接要保活"],
        prompt: "我是网络工程专业大二学生。请讲清 NAT 和 NAPT 的区别、五元组如何区分连接，然后给我一个「内网两台主机同时访问同一公网服务器 443」的场景，问我 NAT 表里会有几条映射、各自五元组是什么。等我答完再批改。",
      },
    ],
  },
  {
    id: "app", index: "05", name: "应用协议", legend: "网页打不开，先分清是 DNS、TCP 还是 TLS。",
    cards: [
      {
        id: "dns", title: "DNS 解析链路", level: "基础",
        desc: "递归查询和迭代查询，谁在替谁跑腿？",
        points: ["客户端 → 本地 DNS 通常是递归", "本地 DNS → 根/顶级/权威 通常是迭代", "A/AAAA/CNAME/MX/NS 记录各管什么"],
        prompt: "我是网络工程专业大二学生。请讲清 DNS 递归查询和迭代查询的区别，以及根、顶级、权威服务器的分工；然后给我一个「浏览器输入域名到拿到 IP」的链路，让我标出每一步是谁问谁。等我答完再批改。",
      },
      {
        id: "tls", title: "HTTPS 与 TLS", level: "进阶",
        desc: "证书链验证什么？SNI 为什么能让一个 IP 服务多个站点？",
        points: ["证书链：站点证书 → 中间 CA → 根 CA", "验证域名、有效期、签名、吊销状态", "SNI 在 ClientHello 里明文携带域名"],
        prompt: "我是网络工程专业大二学生。请讲清 TLS 握手里证书链验证的内容，以及 SNI 的作用；然后出一道「证书域名不匹配 / 证书过期 / 中间证书缺失分别会看到什么现象」的题，等我回答后批改。",
      },
      {
        id: "proxy", title: "正向 / 反向代理", level: "进阶",
        desc: "抓包抓在代理前还是代理后，看到的东西完全不同。",
        points: ["正向代理代表客户端；反向代理代表服务器", "反向代理常做 TLS 终止、负载均衡、缓存", "抓包位置决定你看到明文还是密文"],
        prompt: "我是网络工程专业大二学生。请讲清正向代理和反向代理的区别，以及 TLS 终止后抓包能看到什么；然后给我一个「浏览器 → 反向代理 → 后端」的链路，问我三个位置分别能抓到什么。等我答完再批改。",
      },
    ],
  },
  {
    id: "tools", index: "06", name: "排障工具", legend: "先把「哪一层断了」定位出来，再谈命令。",
    cards: [
      {
        id: "ping", title: "ping / traceroute", level: "基础",
        desc: "TTL 怎么被用来画路径？为什么中间节点可能不回应？",
        points: ["ping 用 ICMP Echo Request/Reply 测 RTT", "traceroute 逐跳增加 TTL，靠 Time Exceeded 定位", "防火墙可能丢弃 ICMP，但不代表 TCP 不通"],
        prompt: "我是网络工程专业大二学生。请讲清 ping 和 traceroute 的原理（ICMP、TTL），然后给我一个「ping 不通但网页能开」的现象，让我列出至少三种可能原因并说明怎么验证。等我答完再批改。",
      },
      {
        id: "sockets", title: "ss / netstat 看连接", level: "进阶",
        desc: "TIME_WAIT 很多是问题吗？CLOSE_WAIT 堆积说明什么？",
        points: ["TIME_WAIT 是主动关闭方的正常状态", "CLOSE_WAIT 堆积 = 应用没调 close()", "ss -tanp 能看状态、队列和进程"],
        prompt: "我是网络工程专业大二学生。请讲清 ss/netstat 里 LISTEN、ESTABLISHED、TIME_WAIT、CLOSE_WAIT 的含义，然后给我两个现象（TIME_WAIT 很多 / CLOSE_WAIT 很多），让我判断哪个更可能是应用 bug、怎么查。等我答完再批改。",
      },
      {
        id: "tcpdump", title: "tcpdump / Wireshark 过滤器", level: "进阶",
        desc: "只抓 443 端口、只看某台主机、只抓 SYN，过滤器怎么写？",
        points: ["BPF：host / port / tcp[tcpflags] & tcp-syn != 0", "抓包点决定能否看到 NAT 前后地址", "先窄后宽：先用最少条件定位，再放宽"],
        prompt: "我是网络工程专业大二学生。请讲清 tcpdump 的 BPF 过滤语法和常见抓包点，然后给我三个抓包需求（只看某主机的 443、只看 SYN、排除 SSH），让我写过滤器。等我答完再批改。",
      },
    ],
  },
];

const ALL_CARDS = TRACKS.flatMap((track) => track.cards.map((card) => ({ ...card, track: track.id })));
let doneTitles = new Set();
let doneToday = 0;

export async function mount(ctx) {
  ctx.setSub("子网、路由、抓包 —— 每天练一格，题目直接送进问一问");
  ctx.setActions('<a class="btn" href="#/plugins">插件中心</a>');
  const data = await api.get("/api/events?module=netlab&limit=200").catch(() => ({ items: [] }));
  const items = Array.isArray(data.items) ? data.items : [];
  const today = new Date().toISOString().slice(0, 10);
  doneTitles = new Set(items.map((item) => item.title).filter(Boolean));
  doneToday = new Set(items
    .filter((item) => String(item.ts || "").slice(0, 10) === today)
    .map((item) => item.title)).size;
  render();
  document.getElementById("random-drill").addEventListener("click", () => {
    const pool = ALL_CARDS.filter((card) => !doneTitles.has(card.title));
    const pick = (pool.length ? pool : ALL_CARDS)[Math.floor(Math.random() * (pool.length || ALL_CARDS.length))];
    startDrill(pick);
  });
}

function render() {
  const total = ALL_CARDS.length;
  const done = ALL_CARDS.filter((card) => doneTitles.has(card.title)).length;
  document.getElementById("netlab-count").textContent = `${done} / ${total}`;
  document.getElementById("netlab-fill").style.width = `${Math.round(done * 100 / total)}%`;
  document.getElementById("netlab-today").textContent = `今天完成 ${doneToday} 格`;

  const root = document.getElementById("netlab-tracks");
  root.innerHTML = TRACKS.map((track) => {
    const doneCount = track.cards.filter((card) => doneTitles.has(card.title)).length;
    return `<section class="netlab-track">
      <header class="netlab-track-head">
        <span class="track-index">${escapeHtml(track.index)}</span>
        <div><h3>${escapeHtml(track.name)}</h3><p>${escapeHtml(track.legend)}</p></div>
        <span class="track-count">${doneCount}/${track.cards.length}</span>
      </header>
      <div class="drill-grid">${track.cards.map((card) => drillCard(card, doneTitles.has(card.title))).join("")}</div>
    </section>`;
  }).join("");

  root.querySelectorAll("[data-drill]").forEach((node) => {
    node.addEventListener("click", () => {
      const card = ALL_CARDS.find((item) => item.id === node.dataset.drill);
      if (card) startDrill(card);
    });
  });
  root.querySelectorAll("[data-preview]").forEach((node) => {
    node.addEventListener("click", () => {
      const body = root.querySelector(`[data-points="${node.dataset.preview}"]`);
      if (body) body.hidden = !body.hidden;
    });
  });
}

function drillCard(card, done) {
  return `<article class="drill-card${done ? " done" : ""}">
    <div class="drill-top">
      <span class="drill-level">${escapeHtml(card.level)}</span>
      <span class="drill-state">${done ? "✓ 已练" : "未开始"}</span>
    </div>
    <h4>${escapeHtml(card.title)}</h4>
    <p>${escapeHtml(card.desc)}</p>
    <div class="drill-actions">
      <button class="btn btn-primary" type="button" data-drill="${escapeHtml(card.id)}">开练</button>
      <button class="btn" type="button" data-preview="${escapeHtml(card.id)}">先看要点</button>
    </div>
    <div class="drill-points" data-points="${escapeHtml(card.id)}" hidden>
      <ul>${card.points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>
    </div>
  </article>`;
}

function startDrill(card) {
  const param = encodeURIComponent(card.prompt);
  const firstTime = !doneTitles.has(card.title);
  if (firstTime) {
    // 只记第一次完成；再练可以，但进度不重复 +1。记录失败不拦着练。
    api.post("/api/events", {
      module: "netlab", kind: "drill", title: card.title,
      meta: { card: card.id, track: card.track },
    }).catch(() => {});
    doneTitles.add(card.title);
    doneToday += 1;
    render();
  }
  location.hash = `#/ask?prompt=${param}`;
}
