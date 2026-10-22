# -*- coding: utf-8 -*-
import json, os
OUT = r'D:\cet6_tool\校对'

papers = {
"2023年12月大学英语6级真题听力（第一套）": {
  "checked_at": "2026-10-22",
  "revision": 1,
  "note": "按可可英语 2023 年 12 月六级听力第 1 套原文逐段校对；文本以线上原文为线索、以音频为准。拼写风格（recognise/recognize、twenty/20 等）不改。",
  "sources": [
    "https://m.kekenet.com/cet6/202403/687121.shtml",
    "https://m.kekenet.com/cet6/202403/687123.shtml",
    "https://m.kekenet.com/cet6/202403/687124.shtml",
    "https://m.kekenet.com/cet6/202403/687125.shtml",
    "https://m.kekenet.com/cet6/202403/687126.shtml",
    "https://m.kekenet.com/cet6/202403/687127.shtml",
    "https://m.kekenet.com/cet6/202403/687129.shtml"
  ],
  "items": {
    "Conversation 1": {
      "18": "You could have been suffering from stress for twenty years without knowing it."
    },
    "Conversation 2": {
      "3": "John, you stunned fans by leaving the sport at just twenty-five.",
      "19": "I went to university and I studied public health and learned about the seriousness of the obesity epidemic, particularly among kids and adolescents in poor communities."
    },
    "Passage 2": {
      "8": "If you shake your fist at the sky and say why can't it stay the same, that's not going to do very much good."
    },
    "Recording 2": {
      "15": "But those researchers concede that's probably in the distant future."
    }
  }
},
"2023年12月大学英语6级真题听力（第二套）": {
  "checked_at": "2026-10-22",
  "revision": 1,
  "note": "按可可英语 2023 年 12 月六级听力第 2 套原文逐段校对；文本以线上原文为线索、以音频为准。只改明确错词、重复词和人名拼写。",
  "sources": [
    "https://m.kekenet.com/cet6/202403/687130.shtml",
    "https://m.kekenet.com/cet6/202403/687131.shtml",
    "https://m.kekenet.com/cet6/202403/687132.shtml",
    "https://m.kekenet.com/cet6/202403/687133.shtml",
    "https://m.kekenet.com/cet6/202403/687134.shtml",
    "https://m.kekenet.com/cet6/202403/687135.shtml",
    "https://m.kekenet.com/cet6/202403/687136.shtml"
  ],
  "items": {
    "Passage 2": {
      "4": "In 2017, Derek Loftis of the Virginia Institute of Marine Science started a project called Catch the King.",
      "7": "Loftis' mission is to know where the water goes before it goes there.",
      "12": "So, in 2017, Loftis and colleagues set up a group of 28 internet-connected water-level sensors throughout the flood risk community of Norfolk, Virginia."
    },
    "Recording 2": {
      "8": "In fact, some of the companies are now exploring a leather substitute and a silk replacement made from mushrooms.",
      "16": "New Look, one of the first reputable store chains to use the vegan trademark, prices ballet shoes at £7.99 and a vegan laptop handbag at £29.99, comparable with its other products. This signifies a change."
    }
  }
},
"英语六级强化刷题卷一": {
  "checked_at": "2026-10-22",
  "revision": 1,
  "note": "拼装卷。经逐单元比对，7 个单元均取自 2021 年 12 月六级听力第 1 套（其中 Recording 3 为同一讲座的后半段）。文本以线上原文为线索、以音频为准。",
  "sources": [
    {"unit": "Conversation 1", "url": "https://m.kekenet.com/cet6/202202/652837.shtml"},
    {"unit": "Conversation 2", "url": "https://m.kekenet.com/cet6/202202/652839.shtml"},
    {"unit": "Passage 1", "url": "https://m.kekenet.com/cet6/202202/652841.shtml"},
    {"unit": "Passage 2", "url": "https://m.kekenet.com/cet6/202202/652843.shtml"},
    {"unit": "Recording 1", "url": "https://m.kekenet.com/cet6/202202/652844.shtml"},
    {"unit": "Recording 2", "url": "https://m.kekenet.com/cet6/202202/652895.shtml"},
    {"unit": "Recording 3", "url": "https://m.kekenet.com/cet6/202202/652896.shtml"}
  ],
  "items": {
    "Conversation 1": {
      "10": "To make things worse, I managed to fall right in front of four girls from the ninth grade, so I was utterly humiliated."
    },
    "Conversation 2": {
      "4": "I'm so excited to talk about my latest book, which was published last month."
    },
    "Passage 1": {
      "4": "Flashback to 1915, when a bottle of Coca-Cola cost just a nickel.",
      "9": "Workers at the Root Glass Company got the request and began flipping through the encyclopedia at the local library, landing on cocoa seed.",
      "14": "Americans mostly consume Coke out of aluminum or plastic today, but the glass bottle remains a symbol of America that's readily recognized around the world."
    },
    "Recording 2": {
      "8": "Rather than getting material things, children need parents' devoted attention."
    }
  }
},
"英语六级强化刷题卷二": {
  "checked_at": "2026-10-22",
  "revision": 1,
  "note": "拼装卷。经逐单元比对，7 个单元均取自 2021 年 12 月六级听力第 2 套。文本以线上原文为线索、以音频为准；线上明显笔误（sills、wild、simple 等）未采纳。",
  "sources": [
    {"unit": "Conversation 1", "url": "https://m.kekenet.com/cet6/202202/652898.shtml"},
    {"unit": "Conversation 2", "url": "https://m.kekenet.com/cet6/202202/652899.shtml"},
    {"unit": "Passage 1", "url": "https://m.kekenet.com/cet6/202202/652901.shtml"},
    {"unit": "Passage 2", "url": "https://m.kekenet.com/cet6/202202/652900.shtml"},
    {"unit": "Recording 1", "url": "https://m.kekenet.com/cet6/202202/652916.shtml"},
    {"unit": "Recording 2", "url": "https://m.kekenet.com/cet6/202202/652917.shtml"},
    {"unit": "Recording 3", "url": "https://m.kekenet.com/cet6/202202/652918.shtml"}
  ],
  "items": {
    "Recording 1": {
      "1": "While it has long been a practice in Asian countries, many people in Western countries have yet to embrace the no-shoes-in-house rule.",
      "14": "These can dent and scratch your floor and if you live in an apartment building, removing your noisy shoes is the polite thing to do out of consideration for your downstairs neighbors.",
      "18": "And if people aren't yet convinced by my arguments, I can give one final reason: the dust and toxic chemicals you bring into your house via your shoes can deteriorate the air quality in your home.",
      "21": "By kicking off your shoes before you enter the home, you are denying entry to these harmful chemicals."
    },
    "Passage 2": {
      "7": "This is to teach children a lesson at the end of the programme."
    }
  }
}
}

import re
def safe_stem(name):
    return re.sub(r'[\/:*?"<>|]+','_',name).strip()
for title,data in papers.items():
    data = {"paper": title, **data}
    path = os.path.join(OUT, safe_stem(title)+'.json')
    with open(path,'w',encoding='utf-8',newline='\n') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print('写出',path,len(data['items']),'单元/',
          sum(len(v) for v in data['items'].values()),'句')
