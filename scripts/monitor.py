#!/usr/bin/env python3
"""
유튜브 거래처 채널 모니터
- channels.json 의 채널 RSS를 확인해 새 영상을 찾고
- Gemini API로 영상을 직접 분석(요약·언급 제품·평가·가격·영업 시사점)
- 결과를 data/ 에 저장하고 텔레그램으로 알림
외부 라이브러리 없이 파이썬 표준 라이브러리만 사용합니다.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VIDEOS = DATA / "videos"
KST = dt.timezone(dt.timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

CATEGORIES = ["CPU", "그래픽카드", "메인보드", "메모리", "SSD", "HDD", "파워", "케이스",
              "CPU쿨러", "케이스팬", "모니터", "키보드", "마우스", "헤드셋/오디오",
              "완제품PC", "노트북", "네트워크", "주변기기", "소프트웨어", "기타"]

CATEGORY_ALIASES = {
    "GPU": "그래픽카드", "VGA": "그래픽카드", "그래픽": "그래픽카드", "글카": "그래픽카드",
    "보드": "메인보드", "MAINBOARD": "메인보드", "MOTHERBOARD": "메인보드",
    "RAM": "메모리", "램": "메모리", "NVME": "SSD", "PSU": "파워", "파워서플라이": "파워",
    "쿨러": "CPU쿨러", "수냉쿨러": "CPU쿨러", "공랭쿨러": "CPU쿨러", "팬": "케이스팬",
    "완본체": "완제품PC", "모니터암": "주변기기",
}

DEFAULT_SETTINGS = {
    "gemini_model": "gemini-3.8-flash",
    "gemini_fallback_model": "gemini-flash-latest",
    "media_resolution": "MEDIA_RESOLUTION_LOW",
    "initial_backfill": 1,          # 채널 첫 등록 시 최근 몇 개 영상을 분석할지
    "max_per_run": 8,               # 한 번 실행에 분석할 최대 영상 수 (무료 한도 보호)
    "max_age_days": 14,             # 이보다 오래된 영상은 새로 발견돼도 건너뜀
    "skip_shorts": False,
    "max_attempts": 3,
    "our_company": "대원씨티에스",
    "our_brands": [],
}


# ───────────────────────── 공통 유틸 ─────────────────────────
def log(*a):
    print(dt.datetime.now(KST).strftime("[%H:%M:%S]"), *a, flush=True)


def now_iso():
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        log(f"⚠️ JSON 형식 오류: {path} ({e})")
        raise


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def http(url, data=None, headers=None, timeout=60, method=None):
    h = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()


def quote_url(u):
    return urllib.parse.quote(u, safe=":/?=&@%#+,;")


# ───────────────────────── 채널 / RSS ─────────────────────────
CID_RE = re.compile(r"(UC[\w-]{22})")


def resolve_channel_id(url):
    """@핸들, /channel/UC.., /c/.., /user/.., 영상 URL 등 어떤 형태든 채널 ID로 변환"""
    u = (url or "").strip()
    m = re.search(r"/channel/(UC[\w-]{22})", u) or re.fullmatch(r"(UC[\w-]{22})", u)
    if m:
        return m.group(1)
    if u.startswith("@"):
        u = "https://www.youtube.com/" + u
    elif not u.startswith("http"):
        u = "https://www.youtube.com/@" + u
    _, body, _ = http(quote_url(u))
    patterns = [
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
        r'<meta itemprop="(?:channelId|identifier)" content="(UC[\w-]{22})"',
        r'"externalId":"(UC[\w-]{22})"',
        r'"browseId":"(UC[\w-]{22})"',
        r'"channelId":"(UC[\w-]{22})"',
    ]
    for p in patterns:
        m = re.search(p, body)
        if m:
            return m.group(1)
    raise ValueError(f"채널 ID를 찾지 못했습니다: {url}")


def fetch_feed(channel_id):
    _, body, _ = http(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    return parse_feed(body)


def parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    title = (root.findtext("a:title", default="", namespaces=NS) or "").strip()
    entries = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        group = e.find("media:group", NS)
        desc = group.findtext("media:description", default="", namespaces=NS) if group is not None else ""
        entries.append({
            "id": vid,
            "title": (e.findtext("a:title", default="", namespaces=NS) or "").strip(),
            "published": e.findtext("a:published", default="", namespaces=NS),
            "channel_title": e.findtext("a:author/a:name", default=title, namespaces=NS),
            "description": desc or "",
        })
    entries.sort(key=lambda x: x["published"], reverse=True)
    return title, entries


def is_short(video_id):
    """/shorts/ID 가 /watch 로 리다이렉트되지 않으면 쇼츠로 판단"""
    try:
        _, _, final = http(f"https://www.youtube.com/shorts/{video_id}", timeout=20)
        return "/shorts/" in final
    except Exception:
        return False


# ───────────────────────── Gemini 분석 ─────────────────────────
def build_prompt(video, channel, settings):
    brands = brands_for_prompt(settings.get("our_brands"))
    return f"""당신은 PC 부품 유통사 '{settings.get('our_company', '')}'의 영업 담당자를 돕는 분석가입니다.
아래 유튜브 영상을 시청하고(음성·화면 자막·화면에 보이는 제품명/가격표 포함) 결과를 한국어 JSON으로만 답하세요.

[채널] {channel.get('name') or video.get('channel_title')}
[거래처 메모] {channel.get('memo') or '(없음)'}
[영상 제목] {video.get('title')}
[영상 설명 일부] {video.get('description', '')[:1500]}
[우리 회사 취급 브랜드] {brands}

규칙:
- 영상에 실제로 나온 내용만 쓰세요. 추측한 모델명·가격은 쓰지 마세요.
- brand는 공식 영문 표기로 통일하세요(예: '에이수스'→'ASUS', '리안리'→'Lian Li', '마이크로닉스'→'Micronics'). 한국 브랜드라 영문 표기가 없으면 한글 그대로.
- 제품은 가능한 한 정확한 모델명(예: 'RTX 5070 Ti', 'Ryzen 7 9800X3D', 'B850M')까지 적고, 모르면 시리즈명까지만 적으세요.
- category는 다음 중 하나: {', '.join(CATEGORIES)}
- timestamp는 처음 등장/집중 설명 시점 'mm:ss' 또는 'h:mm:ss' (모르면 빈 문자열)
- sentiment는 '긍정' | '중립' | '부정'
- price_mentioned는 영상에서 언급/표시된 가격을 원문 그대로(예: '89만원대', '$549'). 없으면 빈 문자열
- is_our_brand: 우리 회사 취급 브랜드에 해당하면 true (괄호 안은 같은 브랜드의 다른 표기)
- sales_insights: 이 거래처의 성격(메모)을 고려해, 우리 영업사원이 이 거래처에 제안·대화할 때 쓸 수 있는 구체적 포인트 2~4개
- 같은 제품을 여러 번 언급하면 하나로 합치세요. 제품 언급이 없으면 products는 빈 배열.

JSON 형식:
{{
  "summary": "핵심 내용 3~5문장",
  "video_type": "리뷰|비교/벤치마크|조립/견적|뉴스/루머|언박싱|튜토리얼|광고/협찬|기타",
  "sponsored": true/false,
  "key_points": ["핵심 포인트", "..."],
  "products": [
    {{"category": "", "brand": "", "model": "", "timestamp": "", "sentiment": "",
      "evaluation": "영상에서의 평가 한두 문장", "price_mentioned": "", "value_comment": "가성비/가격 관련 코멘트",
      "is_our_brand": false}}
  ],
  "sales_insights": ["..."],
  "trend_tags": ["짧은 트렌드 키워드", "..."]
}}"""


class GeminiError(Exception):
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


def call_gemini(model, api_key, video_url, prompt, media_resolution):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen_cfg = {"responseMimeType": "application/json", "temperature": 0.2}
    if media_resolution:
        gen_cfg["mediaResolution"] = media_resolution
    body = {
        "contents": [{"role": "user", "parts": [
            {"fileData": {"fileUri": video_url}},
            {"text": prompt},
        ]}],
        "generationConfig": gen_cfg,
    }
    try:
        _, text, _ = http(url, data=json.dumps(body).encode(), timeout=600, method="POST",
                          headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        retryable = e.code in (429, 500, 502, 503, 504)
        if "API key" in detail or e.code in (401, 403):
            retryable = False
        elif e.code == 400:
            retryable = True  # 예정된 프리미어/라이브 등은 나중에 재시도
        raise GeminiError(f"HTTP {e.code}: {detail}", retryable=retryable)
    resp = json.loads(text)
    cands = resp.get("candidates") or []
    if not cands:
        raise GeminiError(f"응답 없음: {json.dumps(resp.get('promptFeedback', resp), ensure_ascii=False)[:300]}")
    parts = cands[0].get("content", {}).get("parts", [])
    out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    usage = resp.get("usageMetadata", {})
    return parse_json_loose(out), usage


def parse_json_loose(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            return json.loads(m.group(0))
        raise GeminiError("JSON 파싱 실패: " + s[:200])


def analyze(video, channel, settings):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY 가 설정되지 않았습니다", retryable=False)
    url = f"https://www.youtube.com/watch?v={video['id']}"
    prompt = build_prompt(video, channel, settings)
    models = [settings["gemini_model"], settings.get("gemini_fallback_model")]
    last = None
    for model in [m for m in models if m]:
        for attempt in range(2):
            try:
                result, usage = call_gemini(model, api_key, url, prompt, settings.get("media_resolution"))
                return normalize(result), model, usage
            except GeminiError as e:
                last = e
                log(f"   Gemini 오류({model}, 시도 {attempt + 1}): {e}")
                if "404" in str(e) or "not found" in str(e).lower():
                    break  # 모델명 오류 → 대체 모델로
                if "429" in str(e):
                    time.sleep(30)
                else:
                    time.sleep(5)
    raise last or GeminiError("알 수 없는 오류")


def ts_to_sec(ts):
    if not ts:
        return None
    parts = [p for p in re.split(r"[:：]", str(ts).strip()) if p.strip().isdigit()]
    if not parts:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + int(p)
    return sec


def normalize(r):
    r = r if isinstance(r, dict) else {}
    prods = []
    for p in r.get("products") or []:
        if not isinstance(p, dict):
            continue
        cat = (p.get("category") or "기타").strip()
        cat = CATEGORY_ALIASES.get(cat.upper(), cat)
        if cat not in CATEGORIES:
            cat = "기타"
        prods.append({
            "category": cat,
            "brand": (p.get("brand") or "").strip(),
            "model": (p.get("model") or "").strip(),
            "timestamp": (p.get("timestamp") or "").strip(),
            "t": ts_to_sec(p.get("timestamp")),
            "sentiment": p.get("sentiment") if p.get("sentiment") in ("긍정", "중립", "부정") else "중립",
            "evaluation": (p.get("evaluation") or "").strip(),
            "price_mentioned": (p.get("price_mentioned") or "").strip(),
            "value_comment": (p.get("value_comment") or "").strip(),
            "is_our_brand": bool(p.get("is_our_brand")),
        })
    return {
        "summary": (r.get("summary") or "").strip(),
        "video_type": r.get("video_type") or "기타",
        "sponsored": bool(r.get("sponsored")),
        "key_points": [str(x) for x in (r.get("key_points") or [])][:8],
        "products": prods,
        "sales_insights": [str(x) for x in (r.get("sales_insights") or [])][:6],
        "trend_tags": [str(x) for x in (r.get("trend_tags") or [])][:8],
    }


def _norm(s):
    """대소문자·공백·기호 무시: 'Lian-Li' == 'lian li' == 'LIANLI'"""
    return re.sub(r"[\s\-_.·/&]+", "", str(s or "")).lower()


def brand_groups(brands):
    """our_brands 항목 → [[대표이름, 별칭...], ...]
    "Lian Li / 리안리" 처럼 '/' 로 구분하거나 ["Lian Li", "리안리"] 목록으로 적을 수 있음"""
    groups = []
    for b in brands or []:
        names = b if isinstance(b, list) else str(b).split("/")
        names = [n.strip() for n in names if n and str(n).strip()]
        if names:
            groups.append(names)
    return groups


def brands_for_prompt(brands):
    groups = brand_groups(brands)
    if not groups:
        return "(미지정)"
    return ", ".join(g[0] + (f"(={'/'.join(g[1:])})" if len(g) > 1 else "") for g in groups)


def mark_our_brands(record, brands):
    """AI 판단과 별개로 브랜드 목록과 직접 대조해 자사 취급 여부 보정 + 브랜드 표기 통일"""
    groups = brand_groups(brands)
    for p in record["products"]:
        b_norm = _norm(p["brand"])
        text = _norm(f"{p['brand']} {p['model']}")
        for g in groups:
            aliases = [_norm(n) for n in g if _norm(n)]
            # 2글자 이하 별칭은 오탐 방지를 위해 브랜드 칸과 정확히 같을 때만 인정
            hit = any((a == b_norm) or (len(a) > 2 and (a in text)) for a in aliases)
            if hit:
                p["is_our_brand"] = True
                if b_norm in aliases or not p["brand"]:
                    p["brand"] = g[0]  # 대표 이름으로 통일 → 트렌드 집계가 한글/영문으로 갈리지 않음
                break


# ───────────────────────── 텔레그램 ─────────────────────────
def tg_send(text):
    token = re.sub(r"^\s*<?\s*(bot)?|\s*>?\s*$", "", os.environ.get("TELEGRAM_BOT_TOKEN") or "")
    chat = re.sub(r"\s+", "", os.environ.get("TELEGRAM_CHAT_ID") or "")
    if not token or not chat:
        log("   (텔레그램 미설정 — 알림 생략)")
        return False
    ok = True
    for cid in [c.strip() for c in chat.split(",") if c.strip()]:
        body = urllib.parse.urlencode({
            "chat_id": cid, "text": text[:4000], "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }).encode()
        try:
            http(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30)
        except urllib.error.HTTPError as e:
            log("   텔레그램 오류:", e.code, e.read().decode()[:200])
            ok = False
    return ok


def e(s):
    return html.escape(str(s or ""), quote=False)


def tg_message(rec, site_url, manual=False):
    a = rec["analysis"]
    head = "🔍 수동 분석" if manual else "🆕 새 영상"
    lines = [f"{head} · <b>{e(rec['channel_name'])}</b>", f"<b>{e(rec['title'])}</b>", ""]
    if a.get("summary"):
        lines += [f"📝 {e(a['summary'])}", ""]
    prods = a.get("products") or []
    if prods:
        lines.append(f"🧩 <b>언급 제품 {len(prods)}개</b>")
        for p in prods[:8]:
            mark = "⭐" if p.get("is_our_brand") else "•"
            sent = {"긍정": "👍", "부정": "👎"}.get(p["sentiment"], "")
            price = f" ({e(p['price_mentioned'])})" if p.get("price_mentioned") else ""
            lines.append(f"{mark} [{e(p['category'])}] {e(p['brand'])} {e(p['model'])}{price} {sent}")
        if len(prods) > 8:
            lines.append(f"… 외 {len(prods) - 8}개")
        lines.append("")
    if a.get("sales_insights"):
        lines.append("💡 <b>영업 시사점</b>")
        lines += [f"- {e(s)}" for s in a["sales_insights"][:3]]
        lines.append("")
    links = [f'<a href="https://youtu.be/{rec["id"]}">▶ 영상</a>']
    if site_url:
        links.append(f'<a href="{site_url.rstrip("/")}/#v={rec["id"]}">📊 상세 분석</a>')
    lines.append("  |  ".join(links))
    return "\n".join(lines)


# ───────────────────────── 메인 ─────────────────────────
def site_url_default():
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        if name.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner.lower()}.github.io/"
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def store_record(v, ch, analysis, model, usage, short, index, manual=False):
    rec = {
        "id": v["id"],
        "title": v["title"],
        "channel_id": v.get("channel_id") or "",
        "channel_name": ch.get("name") or v.get("channel_name") or "",
        "published": v.get("published") or now_iso(),
        "analyzed_at": now_iso(),
        "is_short": short,
        "manual": manual,
        "model": model,
        "tokens": usage.get("totalTokenCount"),
        "analysis": analysis,
    }
    save_json(VIDEOS / f"{v['id']}.json", rec)
    index[:] = [r for r in index if r["id"] != rec["id"]]  # 재분석 시 기존 항목 교체
    index.insert(0, {
        "id": rec["id"], "title": rec["title"], "channel_id": rec["channel_id"],
        "channel_name": rec["channel_name"], "published": rec["published"],
        "analyzed_at": rec["analyzed_at"], "is_short": short, "manual": manual,
        "summary": analysis["summary"], "video_type": analysis["video_type"],
        "sponsored": analysis["sponsored"], "tags": analysis["trend_tags"],
        "products": [{k: p[k] for k in ("category", "brand", "model", "sentiment",
                                        "price_mentioned", "is_our_brand")}
                     for p in analysis["products"]],
    })
    return rec


# ───────────────────────── 수동 분석 (링크 직접 입력) ─────────────────────────
VID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/|/v/)([A-Za-z0-9_-]{11})")


def extract_video_ids(text):
    ids = []
    for tok in re.split(r"[\s,]+", text or ""):
        tok = tok.strip()
        if not tok:
            continue
        m = VID_RE.search(tok) or re.fullmatch(r"([A-Za-z0-9_-]{11})", tok)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def fetch_video_meta(vid):
    """영상 제목·채널·업로드일 조회 (oEmbed + 시청 페이지)"""
    meta = {"id": vid, "title": vid, "channel_name": "", "channel_id": "", "published": "", "description": ""}
    try:
        _, body, _ = http("https://www.youtube.com/oembed?format=json&url="
                          + urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}"), timeout=20)
        o = json.loads(body)
        meta.update(title=o.get("title") or vid, channel_name=o.get("author_name") or "")
    except Exception as ex:
        log(f"   (oEmbed 조회 실패: {ex})")
    try:
        _, page, _ = http(f"https://www.youtube.com/watch?v={vid}", timeout=30)
        m = re.search(r'"channelId":"(UC[\w-]{22})"', page) or re.search(r'itemprop="channelId" content="(UC[\w-]{22})"', page)
        if m:
            meta["channel_id"] = m.group(1)
        m = (re.search(r'<meta itemprop="(?:datePublished|uploadDate)" content="([^"]+)"', page)
             or re.search(r'"(?:publishDate|uploadDate)":"([^"]+)"', page))
        if m:
            d = m.group(1)
            d = d if "T" in d else d + "T00:00:00+09:00"
            try:
                d = dt.datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat()
            except ValueError:
                pass
            meta["published"] = d
        m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', page)
        if m:
            meta["description"] = json.loads('"' + m.group(1) + '"')[:1500]
    except Exception as ex:
        log(f"   (시청 페이지 조회 실패: {ex})")
    return meta


def run_manual(text):
    settings = {**DEFAULT_SETTINGS, **load_json(ROOT / "settings.json", {})}
    channels = load_json(ROOT / "channels.json", [])
    state = load_json(DATA / "state.json", {"resolved": {}, "channels": {}, "queue": []})
    index = load_json(DATA / "index.json", [])
    site = site_url_default()
    by_cid = {state["resolved"].get(c.get("url", "").strip()): c for c in channels}
    ids = extract_video_ids(text)
    if not ids:
        log("❌ 영상 링크를 찾지 못했습니다:", text)
        tg_send(f"⚠️ 수동 분석: 영상 링크를 인식하지 못했습니다.\n<code>{e(text[:200])}</code>")
        return 1
    fails = 0
    for vid in ids[:10]:
        v = fetch_video_meta(vid)
        ch = by_cid.get(v["channel_id"]) or {"name": v["channel_name"]}
        log(f"🔎 수동 분석: [{v['channel_name']}] {v['title']}")
        try:
            analysis, model, usage = analyze(v, ch, settings)
            mark_our_brands(analysis, settings.get("our_brands"))
        except GeminiError as ex:
            fails += 1
            log(f"   ⛔ 실패: {ex}")
            tg_send(f"⚠️ 수동 분석 실패\n{e(v['title'])}\n<code>{e(str(ex)[:200])}</code>\nhttps://youtu.be/{vid}")
            continue
        rec = store_record(v, ch, analysis, model, usage, is_short(vid), index, manual=True)
        tg_send(tg_message(rec, site, manual=True))
        log(f"   ✅ 완료 (제품 {len(analysis['products'])}개, 토큰 {usage.get('totalTokenCount')})")
    index.sort(key=lambda r: r["published"], reverse=True)
    save_json(DATA / "index.json", index)
    return 1 if fails == len(ids[:10]) else 0


def main():
    settings = {**DEFAULT_SETTINGS, **load_json(ROOT / "settings.json", {})}
    channels = [c for c in load_json(ROOT / "channels.json", []) if c.get("url") and c.get("enabled", True)]
    state = load_json(DATA / "state.json", {"resolved": {}, "channels": {}, "queue": []})
    index = load_json(DATA / "index.json", [])
    known = {r["id"] for r in index}
    site = site_url_default()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=settings["max_age_days"])
    status = {"last_run": now_iso(), "channels": [], "analyzed": 0, "errors": []}

    queue = {q["id"]: q for q in state.get("queue", [])}

    # 1) 채널별 새 영상 찾기
    for ch in channels:
        url = ch["url"].strip()
        st = {"name": ch.get("name") or url, "url": url, "ok": False}
        try:
            cid = state["resolved"].get(url) or resolve_channel_id(url)
            state["resolved"][url] = cid
            st["channel_id"] = cid
            title, entries = fetch_feed(cid)
            st.update(title=title, ok=True, latest=entries[0]["published"] if entries else None)
            cs = state["channels"].setdefault(cid, {"seen": [], "initialized": False})
            seen = set(cs["seen"])
            fresh = []
            if not cs["initialized"]:
                fresh = entries[: settings["initial_backfill"]]
                cs["initialized"] = True
                log(f"📺 {st['name']}: 첫 등록 — 최근 {len(fresh)}개만 분석, 나머지는 기준점으로 저장")
            else:
                for v in entries:
                    if v["id"] in seen or v["id"] in known:
                        continue
                    pub = dt.datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
                    if pub < cutoff:
                        continue
                    fresh.append(v)
            for v in fresh:
                if v["id"] not in known and v["id"] not in queue:
                    queue[v["id"]] = {**v, "channel_id": cid, "channel_name": ch.get("name") or title,
                                      "attempts": 0}
            cs["seen"] = list(dict.fromkeys([v["id"] for v in entries] + cs["seen"]))[:200]
            st["new"] = len(fresh)
            log(f"📺 {st['name']}: 새 영상 {len(fresh)}개")
        except Exception as ex:
            st["error"] = str(ex)[:200]
            log(f"❌ {st['name']}: {ex}")
        status["channels"].append(st)

    # 2) 분석 (오래된 것부터)
    by_cid = {}
    for ch in channels:
        cid = state["resolved"].get(ch["url"].strip())
        if cid:
            by_cid[cid] = ch
    todo = sorted(queue.values(), key=lambda x: x["published"])
    done = 0
    for v in todo:
        if done >= settings["max_per_run"]:
            log(f"⏸ 이번 실행 한도({settings['max_per_run']}개) 도달 — 나머지는 다음 실행에서 처리")
            break
        ch = by_cid.get(v["channel_id"], {"name": v["channel_name"]})
        log(f"🔎 분석: [{v['channel_name']}] {v['title']}")
        short = is_short(v["id"])
        if short and settings["skip_shorts"]:
            log("   쇼츠 — 건너뜀")
            queue.pop(v["id"], None)
            continue
        try:
            analysis, model, usage = analyze(v, ch, settings)
            mark_our_brands(analysis, settings.get("our_brands"))
        except GeminiError as ex:
            v["attempts"] += 1
            v["last_error"] = str(ex)[:300]
            status["errors"].append({"id": v["id"], "title": v["title"], "error": v["last_error"]})
            if not ex.retryable or v["attempts"] >= settings["max_attempts"]:
                log("   ⛔ 분석 포기")
                queue.pop(v["id"], None)
                tg_send(f"⚠️ 분석 실패: <b>{e(v['channel_name'])}</b>\n{e(v['title'])}\n"
                        f"<code>{e(v['last_error'][:200])}</code>\nhttps://youtu.be/{v['id']}")
            continue
        rec = store_record(v, ch, analysis, model, usage, short, index)
        known.add(v["id"])
        queue.pop(v["id"], None)
        done += 1
        status["analyzed"] += 1
        tg_send(tg_message(rec, site))
        log(f"   ✅ 완료 (제품 {len(analysis['products'])}개, 토큰 {usage.get('totalTokenCount')})")

    index.sort(key=lambda r: r["published"], reverse=True)
    state["queue"] = list(queue.values())
    status["queue"] = len(queue)
    save_json(DATA / "index.json", index)
    save_json(DATA / "state.json", state)
    save_json(DATA / "status.json", status)
    log(f"끝: 분석 {done}개, 대기 {len(queue)}개")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test-telegram":
        sys.exit(0 if tg_send("✅ 유튜브 트렌드 모니터 텔레그램 연결 테스트 성공!") else 1)
    manual = os.environ.get("VIDEO_URLS", "").strip()
    if manual:
        sys.exit(run_manual(manual))
    main()
