"""여행 추천 리포트 생성기 (Trip Planner)

날짜를 입력받아 LLM으로 여행지를 추천받고, 그 도시의 맛집을 지도 API로 검색해
최종 여행 리포트(Markdown)를 생성하는 CLI 프로그램.

사용법:
    python trip_planner.py -date "2026-09-20"
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

sys.stdout.reconfigure(encoding="utf-8")  # cp949 터미널에서 이모지가 깨지지 않도록
sys.stderr.reconfigure(encoding="utf-8")  # argparse 오류 메시지가 stderr로 나간다

# SDK가 매 호출마다 찍는 AFC 안내가 진행 로그 중간에 끼어들어 화면을 어지럽힌다.
# 이 프로그램은 함수 호출(tool use)을 쓰지 않으므로 해당 안내는 의미가 없다.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# --- 설정 상수 ---------------------------------------------------------------
GEMINI_MODEL = "gemini-3.6-flash"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
RESULTS_DIR = "results"
RESTAURANT_COUNT = 5          # 맛집 검색 개수 (권장 5곳)
REQUEST_TIMEOUT = 10          # 초. Kakao 호출용
GEMINI_TIMEOUT_MS = 120000    # 밀리초(2분). 리포트 생성은 40초 이상 걸리기도 한다. 생략하면 서버 무응답 시 영원히 멈춘다
SERVER_RETRY = 3              # 503(모델 과부하) 재시도 횟수
SERVER_BACKOFF = 2            # 초. 재시도 간격(회차마다 배수로 증가)
TOTAL_STEPS = 6
KST = timezone(timedelta(hours=9))

# 1차 추천 JSON 스키마. API 레벨에서 필수 키와 타입을 강제한다.
RECOMMEND_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "recommended_city": {"type": "STRING"},
        "weather": {"type": "STRING"},
        "events": {"type": "ARRAY", "items": {"type": "STRING"}},
        "reason": {"type": "STRING"},
    },
    "required": ["recommended_city", "weather", "events", "reason"],
}


# --- 진행 로그 ---------------------------------------------------------------
def _width(text):
    """한글·이모지는 터미널에서 두 칸을 차지하므로 폭을 따로 센다."""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in text)


_pending = None  # 결과를 기다리는 중인 (단계, 라벨)


def _dots(label):
    return "." * max(2, 26 - _width(label))


def log_start(step, label):
    """호출 '전에' 라벨을 찍는다. 응답이 늦어도 멈춘 것처럼 보이지 않는다."""
    global _pending
    print(f"[{step}/{TOTAL_STEPS}] {label} {_dots(label)} ", end="", flush=True)
    _pending = (step, label)


def log_end(status):
    global _pending
    print(status)
    _pending = None


def log(step, label, status):
    log_start(step, label)
    log_end(status)


def log_detail(message):
    """진행 중인 줄이 있으면 닫았다가 다시 열어 준다."""
    global _pending
    keep = _pending
    if keep:
        print()
        _pending = None
    print(f"      → {message}")
    if keep:
        log_start(*keep)


def print_header(date_str):
    print("=" * 60)
    print("  🧳 여행 추천 리포트 생성기")
    print(f"  대상 날짜: {date_str}")
    print("=" * 60)


# --- CLI ---------------------------------------------------------------------
def valid_date(value):
    """argparse type= 검증 함수.

    ArgumentTypeError를 던지면 argparse가 사용법을 출력하고 종료(exit 2)한다.
    strptime을 쓰는 이유는 형식과 실재 여부를 동시에 거르기 때문이다.
    정규식만으로는 2026-13-45 같은 값이 통과한다.

    다만 strptime도 완전하지 않다. %m/%d는 0을 뺀 한 자리 표기를 허용해서
    '2026-9-20'이 그대로 통과한다. 그래서 파싱 결과를 다시 문자열로 만들어
    입력과 같은지 비교한다.
    """
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: {value!r} (예: 2026-09-20)")

    # strptime은 0을 뺀 표기도 받아들인다(2026-9-20 통과). 왕복 비교로 걸러낸다.
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError(
            f"날짜는 0을 채운 8자리로 써야 합니다: {value!r} → {parsed.isoformat()!r}")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(
        description="날짜를 받아 여행지를 추천하고 맛집을 검색해 리포트를 생성합니다.",
        epilog='예시: python trip_planner.py -date "2026-09-20"')
    parser.add_argument("-date", "--date", required=True, type=valid_date,
                        help="여행 날짜 (YYYY-MM-DD)")
    return parser.parse_args()


# --- 오류 기록 ---------------------------------------------------------------
def record_error(errors, stage, type_, message):
    """실패를 목록에 남긴다.

    message에 예외 객체를 통째로 넣지 않는다. 요청 URL이나 헤더가 딸려오면
    API 키가 결과 파일에 그대로 저장되어 커밋될 수 있다.
    """
    errors.append({"stage": stage, "type": type_, "message": str(message)[:200]})


# --- 설정 -------------------------------------------------------------------
def load_api_keys():
    """환경변수 또는 .env에서 키를 읽는다.

    load_dotenv()는 호출한 스크립트 파일의 위치를 기준으로 .env를 찾는다.
    이 파일은 프로젝트 폴더에 있으므로 같은 폴더의 .env가 잡힌다.
    """
    load_dotenv()
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    kakao_key = (os.getenv("KAKAO_REST_API_KEY") or "").strip()

    if not gemini_key:
        # Gemini가 없으면 추천도 리포트도 만들 수 없다 → 즉시 종료
        print()
        print("❌ GEMINI_API_KEY가 설정되지 않았습니다.")
        print()
        print("   설정 방법 (둘 중 하나):")
        print("   1) 프로젝트 폴더에 .env 파일을 만들고 아래 줄을 추가")
        print("        GEMINI_API_KEY=발급받은_키")
        print("   2) 현재 터미널 세션에만 적용")
        print('        PowerShell : $env:GEMINI_API_KEY="발급받은_키"')
        print('        bash       : export GEMINI_API_KEY="발급받은_키"')
        print()
        print("   키 발급: https://aistudio.google.com/apikey")
        sys.exit(1)

    return gemini_key, kakao_key


# --- LLM (Gemini) ------------------------------------------------------------
def call_gemini(client, prompt, as_json, schema=None):
    """Gemini를 호출해 텍스트를 돌려준다.

    503(모델 과부하)은 잠시 뒤 풀리는 일시적 오류라 짧게 재시도한다.
    이것은 전송 계층 재시도이며, JSON 파싱 실패에 대한 재시도(E3, 최대 1회)와는
    별개다. 둘 다 횟수가 고정되어 있어 무한 재시도가 되지 않는다.
    """
    config = {}
    if as_json:
        config["response_mime_type"] = "application/json"
        if schema:
            config["response_schema"] = schema

    last_error = None
    for attempt in range(SERVER_RETRY):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(**config),
            )
            return response.text
        except genai_errors.ServerError as exc:
            last_error = exc
            if attempt < SERVER_RETRY - 1:
                wait = SERVER_BACKOFF * (attempt + 1)
                # 조용히 기다리면 사용자는 프로그램이 멈춘 줄 안다
                log_detail(f"서버가 혼잡합니다(503). {wait}초 후 재시도 "
                           f"({attempt + 1}/{SERVER_RETRY - 1})")
                time.sleep(wait)
    raise last_error


def gemini_error_type(exc):
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return "auth"
    if code == 429:
        return "quota"
    return "api"


def build_recommend_prompt(date_str):
    """1차 추천 프롬프트.

    출력 형식을 예시 JSON으로 보여주지 않는다. 실측 결과, JSON 모드에서
    프롬프트에 예시 객체를 넣으면 모델이 예시를 먼저 출력하고 진짜 답을 이어 붙여
    JSON 객체가 두 개가 되는 일이 잦았다(완료 5건 중 4건 파싱 실패).
    구조는 RECOMMEND_SCHEMA가 강제하므로 프롬프트는 내용만 지시한다.
    """
    return f"""당신은 국내 여행 플래너입니다.
{date_str}에 국내 여행을 간다면 어디가 좋을지 한 곳을 추천하십시오.

- recommended_city: 국내 도시 한 곳의 이름만. 시/도 접미사 없이 간결하게.
- weather: 해당 시기의 일반적인 날씨를 한 문장으로 요약.
- events: 그 시기의 행사나 축제 이름을 1개 이상 3개 이하.
- reason: 추천 근거를 2~4문장으로.

확정된 사실이 아니면 해당 시기의 일반적인 정보로 작성해도 됩니다."""


def build_retry_prompt(date_str):
    """E3 재시도용. 필수 키만 최소한으로 다시 요구한다."""
    return f"""{date_str}에 갈 만한 국내 여행지 한 곳을 추천하십시오.
아래 네 가지만 간결하게 채우고, 부연 설명은 넣지 마십시오.

- recommended_city: 도시 이름 하나
- weather: 한 문장
- events: 행사명 1~3개
- reason: 두 문장 이내"""


def validate_recommendation(data):
    """필수 키와 타입을 검증한다.

    json.loads가 통과해도 events가 문자열 하나로 오거나 키가 빠질 수 있다.
    파싱 성공과 검증 성공은 다르므로 따로 확인한다.
    """
    if not isinstance(data, dict):
        return False
    for key in ("recommended_city", "weather", "reason"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            return False
    events = data.get("events")
    if not isinstance(events, list) or not events:
        return False
    return all(isinstance(item, str) for item in events)


def get_recommendation(client, date_str, errors):
    """1차 추천을 받아 파싱·검증한다. 실패하면 1회만 재시도한다."""
    attempts = [
        ("1차", build_recommend_prompt(date_str)),
        ("재시도", build_retry_prompt(date_str)),
    ]
    for label, prompt in attempts:
        try:
            raw = call_gemini(client, prompt, as_json=True, schema=RECOMMEND_SCHEMA)
        except Exception as exc:
            record_error(errors, "recommendation", gemini_error_type(exc), exc)
            print()
            print(f"❌ 여행지 추천 요청에 실패했습니다 ({label}).")
            print(f"   {str(exc)[:200]}")
            sys.exit(1)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            record_error(errors, "recommendation", "parse", exc)
            if label == "1차":
                log_detail("JSON 파싱 실패 → 형식을 단순화해 1회 재시도합니다")
            continue

        if not validate_recommendation(data):
            record_error(errors, "recommendation", "parse", "필수 키/타입 검증 실패")
            if label == "1차":
                log_detail("필수 키 검증 실패 → 1회 재시도합니다")
            continue

        data["events"] = [e.strip() for e in data["events"] if e.strip()][:3]
        return data

    # 재시도까지 실패. 도시 이름이 없으면 맛집 검색도 리포트도 만들 수 없다.
    print()
    print("❌ 추천 결과를 JSON으로 받지 못했습니다 (재시도 1회 포함).")
    print("   잠시 후 다시 실행해 주세요.")
    sys.exit(1)


# --- 지도/장소 (Kakao Local) --------------------------------------------------
def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_place(doc):
    """Kakao 응답을 우리 스키마로 변환한다.

    주의: x가 경도(lng), y가 위도(lat)이며 둘 다 문자열로 온다.
    화면 좌표 감각으로 x를 위도에 넣으면 지도에 엉뚱한 위치가 찍힌다.
    """
    return {
        "name": doc.get("place_name", ""),
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
        "category": doc.get("category_name", ""),
        "url": doc.get("place_url", ""),
        "lat": to_float(doc.get("y")),
        "lng": to_float(doc.get("x")),
    }


def search_restaurants(city, kakao_key, errors):
    """맛집을 검색한다. 어떤 실패든 빈 리스트를 돌려주고 프로그램은 계속된다."""
    if not kakao_key:
        record_error(errors, "kakao_search", "auth", "KAKAO_REST_API_KEY 미설정")
        log_end("⚠ 건너뜀 (KAKAO_REST_API_KEY 미설정)")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    try:
        response = requests.get(
            KAKAO_URL,
            headers={"Authorization": f"KakaoAK {kakao_key}"},
            params={"query": f"{city} 맛집",
                    "size": RESTAURANT_COUNT,
                    "category_group_code": "FD6"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        documents = response.json()["documents"]

    except requests.exceptions.Timeout:
        record_error(errors, "kakao_search", "network", f"{REQUEST_TIMEOUT}초 내 응답 없음")
        log_end("⚠ 실패 (응답 시간 초과)")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    except requests.exceptions.ConnectionError:
        record_error(errors, "kakao_search", "network", "네트워크 연결 실패")
        log_end("⚠ 실패 (네트워크 연결)")
        log_detail("인터넷 연결을 확인해 주세요. 리포트 생성은 계속합니다")
        return []

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code
        hints = {
            401: "KAKAO_REST_API_KEY 값과 헤더의 'KakaoAK ' 접두어를 확인하세요",
            403: "카카오 개발자 사이트에서 앱 플랫폼 등록과 API 사용 설정을 확인하세요",
            429: "일일 호출 한도를 초과했습니다. 내일 다시 시도하세요",
        }
        record_error(errors, "kakao_search",
                     {401: "auth", 403: "auth", 429: "quota"}.get(status, "api"),
                     f"HTTP {status}")
        log_end(f"⚠ 실패 (HTTP {status})")
        log_detail(hints.get(status, "카카오 서버 오류입니다. 잠시 후 다시 시도하세요"))
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    except (ValueError, KeyError) as exc:
        record_error(errors, "kakao_search", "parse", f"응답 형식이 예상과 다름: {exc}")
        log_end("⚠ 실패 (응답 파싱)")
        return []

    if not documents:
        record_error(errors, "kakao_search", "empty", f"'{city} 맛집' 검색 결과 0건")
        log_end("0건")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    restaurants = [normalize_place(doc) for doc in documents]
    log_end(f"완료 ({len(restaurants)}곳)")
    return restaurants


# --- 리포트 -------------------------------------------------------------------
def format_restaurants(restaurants):
    if not restaurants:
        return "데이터 없음 (맛집 정보를 가져오지 못했습니다)"
    lines = []
    for i, r in enumerate(restaurants, 1):
        lines.append(f"{i}. {r['name']} | {r['category']} | {r['address']} | {r['url']}")
    return "\n".join(lines)


def build_report_prompt(date_str, rec, restaurants):
    return f"""아래 데이터로 {date_str} 여행 리포트를 Markdown으로 작성하십시오.

[추천 정보]
- 추천 도시: {rec['recommended_city']}
- 날씨: {rec['weather']}
- 행사/축제: {', '.join(rec['events']) if rec['events'] else '없음'}
- 추천 이유: {rec['reason']}

[맛집 목록]
{format_restaurants(restaurants)}

제목은 정확히 아래 한 줄로 시작하십시오.
# 🧳 {rec['recommended_city']} 여행 리포트 ({date_str})

그 다음 아래 항목을 이 순서대로 포함하십시오.
1. 추천 지역과 추천 이유 요약
2. 날씨 요약
3. 행사·축제 목록
4. 맛집 리스트 (표로 정리. 데이터가 없으면 "데이터 없음"이라고만 쓰십시오)
5. 1일 일정 제안 (오전 / 오후 / 저녁)

주어진 데이터에 없는 정보를 지어내지 마십시오.
특히 맛집이 0건이면 가게 이름을 만들어내지 말고 "데이터 없음"이라고 쓰십시오.
전체를 한국어로 작성하고, 영어 단어를 섞지 마십시오.
Markdown 본문만 출력하고 코드블록으로 감싸지 마십시오."""


def build_fallback_report(date_str, rec, restaurants):
    """LLM 리포트 생성이 실패했을 때 저장된 데이터로 직접 만든다.

    리포트는 이 프로그램의 최종 산출물이다. LLM이 실패했다고 빈손으로 끝내면
    안 되므로, 이미 확보한 recommendation과 restaurants로 같은 항목을 채운다.
    """
    city = rec["recommended_city"]
    lines = [
        f"# 🧳 {city} 여행 리포트 ({date_str})",
        "",
        "> ⚠️ 리포트 생성 API 호출에 실패해, 수집된 데이터로 자동 구성한 리포트입니다.",
        "",
        "## 📍 추천 지역",
        "",
        f"**{city}** — {rec['reason']}",
        "",
        "## 🌤️ 날씨",
        "",
        rec["weather"],
        "",
        "## 🎪 행사 · 축제",
        "",
    ]
    lines += [f"- {e}" for e in rec["events"]] if rec["events"] else ["데이터 없음"]
    lines += ["", "## 🍽️ 맛집", ""]

    if restaurants:
        lines += ["| 이름 | 카테고리 | 주소 | 링크 |",
                  "|------|----------|------|------|"]
        for r in restaurants:
            link = f"[지도]({r['url']})" if r["url"] else "-"
            lines.append(f"| {r['name']} | {r['category']} | {r['address']} | {link} |")
    else:
        lines.append("데이터 없음")

    first = restaurants[0]["name"] if restaurants else "현지 식당"
    last = restaurants[-1]["name"] if restaurants else "현지 식당"
    lines += [
        "",
        "## 🗓️ 1일 일정 제안",
        "",
        f"- **오전** — {city} 도착 후 주요 명소를 둘러봅니다.",
        f"- **오후** — 점심은 {first}에서 해결하고, 행사·축제 일정을 확인해 방문합니다.",
        f"- **저녁** — {last}에서 저녁 식사 후 야경을 둘러보며 마무리합니다.",
        "",
    ]
    return "\n".join(lines)


def generate_report(client, date_str, rec, restaurants, errors):
    prompt = build_report_prompt(date_str, rec, restaurants)
    try:
        markdown = call_gemini(client, prompt, as_json=False)
        if markdown and markdown.strip():
            return markdown.strip()
        record_error(errors, "report", "api", "빈 응답")
    except Exception as exc:
        record_error(errors, "report", gemini_error_type(exc), exc)

    log_detail("리포트 생성 API 실패 → 수집된 데이터로 직접 작성합니다")
    return build_fallback_report(date_str, rec, restaurants)


def append_error_section(markdown, errors):
    """errors가 비어 있으면 절 자체를 생략한다."""
    if not errors:
        return markdown
    lines = [markdown.rstrip(), "", "## ⚠️ 오류 요약", ""]
    for e in errors:
        lines.append(f"- `[{e['stage']}]` ({e['type']}) {e['message']}")
    lines.append("")
    return "\n".join(lines)


# --- 저장 · 캐시 --------------------------------------------------------------
def ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def raw_path(date_str):
    return os.path.join(RESULTS_DIR, f"trip_{date_str}_raw.json")


def report_path(date_str):
    return os.path.join(RESULTS_DIR, f"trip_{date_str}_report.md")


def save_raw(payload, date_str):
    ensure_results_dir()
    # ensure_ascii=False가 없으면 한글이 \uXXXX로 저장되어 사람이 읽을 수 없다
    with open(raw_path(date_str), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def save_report(markdown, date_str):
    ensure_results_dir()
    with open(report_path(date_str), "w", encoding="utf-8") as f:
        f.write(markdown)


def load_cache(date_str):
    """같은 날짜의 원본 JSON이 있으면 읽어 온다 (보너스: 결과 캐싱).

    파일이 깨져 있으면 캐시를 무시하고 정상 경로로 진행한다. 캐시는 편의 기능이므로
    캐시 때문에 프로그램이 멈추면 안 된다.
    """
    path = raw_path(date_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not validate_recommendation(data.get("recommendation")):
        return None
    return data


# --- 메인 --------------------------------------------------------------------
def print_footer(date_str, errors):
    print("-" * 60)
    if errors:
        print(f"⚠️  오류 {len(errors)}건이 있었지만 리포트는 생성되었습니다.")
    else:
        print("✅ 완료했습니다.")
    print(f"   원본 데이터 : {raw_path(date_str)}")
    print(f"   최종 리포트 : {report_path(date_str)}")
    print("=" * 60)


def main():
    args = parse_args()
    date_str = args.date.isoformat()
    errors = []

    print_header(date_str)

    gemini_key, kakao_key = load_api_keys()
    ready = "Gemini, Kakao" if kakao_key else "Gemini"
    log(1, "API 키 확인", f"완료 ({ready})")
    if not kakao_key:
        log_detail("KAKAO_REST_API_KEY 미설정 — 맛집 검색을 건너뜁니다")

    client = genai.Client(
        api_key=gemini_key,
        # 타임아웃이 없으면 서버가 응답하지 않을 때 예외조차 없이 영원히 멈춘다
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )
    cached = load_cache(date_str)

    if cached:
        recommendation = cached["recommendation"]
        restaurants = cached.get("restaurants", [])
        errors.extend(cached.get("errors", []))
        log(2, "캐시 확인", "기존 결과 발견, API 호출을 건너뜁니다")
        log_detail(raw_path(date_str))
        log(3, "여행지 추천 요청", f"캐시 사용 → {recommendation['recommended_city']}")
        log(4, "맛집 검색", f"캐시 사용 ({len(restaurants)}곳)")
        log(5, "원본 데이터 저장", "건너뜀 (기존 파일 유지)")
    else:
        log(2, "캐시 확인", "없음, 새로 생성합니다")
        log_start(3, "여행지 추천 요청")
        recommendation = get_recommendation(client, date_str, errors)
        log_end(f"완료 → {recommendation['recommended_city']}")
        log_start(4, "맛집 검색")
        restaurants = search_restaurants(recommendation["recommended_city"], kakao_key, errors)
        save_raw({
            "input_date": date_str,
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "recommendation": recommendation,
            "restaurants": restaurants,
            "errors": errors,
        }, date_str)
        log(5, "원본 데이터 저장", "완료")

    log_start(6, "리포트 생성")
    markdown = generate_report(client, date_str, recommendation, restaurants, errors)
    save_report(append_error_section(markdown, errors), date_str)
    log_end("완료")

    print_footer(date_str, errors)


if __name__ == "__main__":
    main()
