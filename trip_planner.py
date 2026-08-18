"""여행 추천 리포트 생성기 (Trip Planner)

날짜를 입력받아 LLM으로 여행지를 추천받고, 그 도시의 맛집을 지도 API로 검색해
최종 여행 리포트(Markdown)를 생성하는 CLI 프로그램.

사용법:
    python trip_planner.py -date "2026-09-20"
"""
import argparse
import difflib
import json
import logging
import os
import re
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
DEFAULT_PLACE_PROVIDER = "kakao"   # 환경변수 PLACE_PROVIDER로 교체 가능
RESULTS_DIR = "results"
RESTAURANT_COUNT = 5          # 맛집 검색 개수 (권장 5곳)
REQUEST_TIMEOUT = 10          # 초. Kakao 호출용
GEMINI_TIMEOUT_MS = 120000    # 밀리초(2분). 리포트 생성은 40초 이상 걸리기도 한다. 생략하면 서버 무응답 시 영원히 멈춘다
SERVER_RETRY = 3              # 503(모델 과부하) 재시도 횟수
SERVER_BACKOFF = 2            # 초. 재시도 간격(회차마다 배수로 증가)
TOTAL_STEPS = 6
CITY_MATCH_CUTOFF = 0.8       # 도시명 오타 보정의 자모 유사도 기준
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
    """Gemini 키를 환경변수 또는 .env에서 읽는다.

    장소 검색 제공자의 자격증명은 제공자 어댑터가 스스로 관리한다
    (PlaceProvider.credentials). 제공자마다 필요한 키 개수와 이름이 다르기 때문이다.
    Kakao는 REST 키 1개, Naver는 Client ID/Secret 2개를 쓴다.

    load_dotenv()는 호출한 스크립트 파일의 위치를 기준으로 .env를 찾는다.
    이 파일은 프로젝트 폴더에 있으므로 같은 폴더의 .env가 잡힌다.
    """
    load_dotenv()
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()

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

    return gemini_key


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

        # LLM은 같은 도시를 '제주', '제주도', '경주 (경상북도)' 등으로 다르게 답한다.
        # 이 값이 그대로 장소 검색 질의어가 되므로 표준명으로 다듬는다.
        raw_city = data["recommended_city"]
        city, notes = normalize_city(raw_city)
        data["recommended_city"] = city
        if city != raw_city:
            data["recommended_city_raw"] = raw_city   # 무엇이 바뀌었는지 결과에 남긴다
            data["normalization"] = notes
        return data

    # 재시도까지 실패. 도시 이름이 없으면 맛집 검색도 리포트도 만들 수 없다.
    print()
    print("❌ 추천 결과를 JSON으로 받지 못했습니다 (재시도 1회 포함).")
    print("   잠시 후 다시 실행해 주세요.")
    sys.exit(1)


# --- 도시명 정규화 -------------------------------------------------------------
# LLM은 같은 도시를 '제주', '제주도', '제주특별자치도', '제주 (제주도)' 등으로 다르게 답한다.
# 이 값이 그대로 장소 검색 질의어가 되므로, 검색에 넣기 전에 표준명으로 다듬는다.

# 표준명 직접 매핑. 접미사 제거만으로 처리되지 않는 것들을 여기서 먼저 거른다.
CITY_ALIASES = {
    "제주도": "제주", "제주특별자치도": "제주", "제주시": "제주",
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종",
    "강원특별자치도": "강원", "전북특별자치도": "전주",
}

# 접미사는 '가장 긴 것부터' 검사한다. '특별자치도'를 '도'보다 먼저 봐야 한다.
ADMIN_SUFFIXES = ("특별자치도", "특별자치시", "특별시", "광역시",
                  "자치시", "자치도", "시", "군", "구", "도")

# 근사 매칭(오타 보정)의 기준이 되는 국내 주요 여행지.
KNOWN_CITIES = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "제주", "서귀포", "강릉", "속초", "동해", "삼척", "양양", "평창", "춘천", "원주",
    "경주", "안동", "포항", "울진", "영덕", "문경", "상주", "구미",
    "전주", "군산", "남원", "여수", "순천", "목포", "광양", "담양", "보성",
    "통영", "거제", "남해", "진주", "김해", "양산", "밀양",
    "충주", "제천", "단양", "청주", "공주", "부여", "보령", "태안", "서산",
    "가평", "양평", "파주", "수원", "인제", "정선", "홍천", "태백",
]


def _jamo(text):
    """한글 음절을 초성·중성·종성으로 분해한다.

    '강릉'과 '갱릉'은 글자 단위로 보면 2자 중 1자만 같아 유사도가 0.5에 그친다.
    자모로 풀면 ㄱㅏㅇㄹㅡㅇ / ㄱㅐㅇㄹㅡㅇ 로 6개 중 5개가 같아 0.83이 되어
    오타를 잡아낼 수 있다. 한글 두 글자 이름이 많아 이 처리가 필요하다.
    """
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171:
            out.append(chr(0x1100 + code // 588))
            out.append(chr(0x1161 + (code % 588) // 28))
            tail = code % 28
            if tail:
                out.append(chr(0x11A7 + tail))
        else:
            out.append(ch)
    return "".join(out)


def _closest_known_city(name):
    """자모 유사도로 가장 가까운 표준 도시명을 찾는다. 없으면 None."""
    target = _jamo(name)
    best, best_score = None, 0.0
    for city in KNOWN_CITIES:
        score = difflib.SequenceMatcher(None, target, _jamo(city)).ratio()
        if score > best_score:
            best, best_score = city, score
    return best if best_score >= CITY_MATCH_CUTOFF else None


def normalize_city(raw):
    """LLM이 준 도시명을 검색용 표준명으로 정규화한다.

    (정규화된 이름, 무엇을 했는지 설명 목록)을 돌려준다.
    설명 목록은 로그와 결과 JSON에 남겨, 무엇이 왜 바뀌었는지 추적할 수 있게 한다.
    """
    notes = []
    name = (raw or "").strip().strip("\"'")

    # 1) 괄호와 그 내용 제거 — '경주 (경상북도)' 처럼 부연이 붙어 오는 경우
    without_paren = re.sub(r"[（(\[][^）)\]]*[）)\]]", "", name).strip()
    if without_paren != name:
        notes.append("괄호 제거")
        name = without_paren

    # 2) 내부 공백 정리 — '강 릉' 같은 경우
    collapsed = re.sub(r"\s+", "", name)
    if collapsed != name:
        notes.append("공백 제거")
        name = collapsed

    if not name:
        return raw, ["정규화 실패 — 원본 유지"]

    # 3) 표준명 직접 매핑
    if name in CITY_ALIASES:
        mapped = CITY_ALIASES[name]
        notes.append(f"표준명 매핑 → '{mapped}'")
        return mapped, notes

    # 4) 이미 표준 도시명이면 접미사를 떼지 않는다.
    #    '대구'에서 '구'를 떼면 '대'가 되어 버린다.
    if name in KNOWN_CITIES:
        return name, notes

    # 5) 행정 접미사 제거 (한 번만, 결과가 두 글자 이상일 때만)
    for suffix in ADMIN_SUFFIXES:
        if name.endswith(suffix) and len(name) - len(suffix) >= 2:
            stripped = name[: -len(suffix)]
            notes.append(f"접미사 '{suffix}' 제거")
            name = stripped
            break

    if name in CITY_ALIASES:
        mapped = CITY_ALIASES[name]
        notes.append(f"표준명 매핑 → '{mapped}'")
        return mapped, notes
    if name in KNOWN_CITIES:
        return name, notes

    # 6) 오타 보정 — 자모 유사도로 가장 가까운 표준 도시명을 찾는다
    guess = _closest_known_city(name)
    if guess and guess != name:
        notes.append(f"오타 보정 '{name}' → '{guess}'")
        return guess, notes

    # 알려진 도시가 아니어도 검색은 시도한다. 목록에 없는 여행지일 수 있다.
    return name, notes


# --- 지도/장소 제공자 어댑터 ---------------------------------------------------
# 제공자를 갈아끼울 수 있도록 어댑터로 분리했다.
# 공통 흐름(요청·타임아웃·HTTP 오류 분기·0건 처리·로그)은 search_restaurants()가 맡고,
# 제공자마다 다른 부분만 어댑터가 담당한다. 새 제공자를 붙이려면
# PlaceProvider를 상속해 아래 훅을 채우고 PLACE_PROVIDERS에 등록하면 된다.

def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def strip_tags(text):
    """검색어 강조용 <b> 같은 태그를 제거한다 (Naver 응답의 title에 섞여 온다)."""
    return re.sub(r"<[^>]+>", "", text or "")


class PlaceProvider:
    """지도/장소 검색 제공자 인터페이스.

    구현해야 하는 것은 다섯 가지다.
      required_env      : 필요한 환경변수 이름들
      build_request     : 검색 요청의 URL·헤더·파라미터
      extract_documents : 응답 본문에서 결과 목록을 꺼내는 방법
      normalize         : 제공자 응답 1건을 공통 스키마로 변환
      hint              : HTTP 오류 코드별 점검 안내 (제공자마다 원인이 다르다)
    """

    name = ""
    label = ""
    required_env = ()

    def credentials(self):
        """필요한 환경변수를 모아 온다. 하나라도 비어 있으면 None."""
        values = {key: (os.getenv(key) or "").strip() for key in self.required_env}
        return values if all(values.values()) else None

    def missing_env(self):
        return [k for k in self.required_env if not (os.getenv(k) or "").strip()]

    def build_request(self, city, count, creds):
        raise NotImplementedError

    def extract_documents(self, payload):
        raise NotImplementedError

    def normalize(self, doc):
        raise NotImplementedError

    def hint(self, status):
        return "제공자 서버 오류입니다. 잠시 후 다시 시도하세요"


class KakaoPlaceProvider(PlaceProvider):
    """Kakao Local 키워드 검색.

    응답의 x가 경도(lng), y가 위도(lat)이며 둘 다 문자열로 온다.
    화면 좌표 감각으로 x를 위도에 넣으면 지도에 엉뚱한 위치가 찍힌다.
    """

    name = "kakao"
    label = "Kakao Local"
    required_env = ("KAKAO_REST_API_KEY",)
    URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

    def build_request(self, city, count, creds):
        return {
            "url": self.URL,
            "headers": {"Authorization": f"KakaoAK {creds['KAKAO_REST_API_KEY']}"},
            "params": {"query": f"{city} 맛집",
                       "size": count,
                       "category_group_code": "FD6"},   # 음식점으로 한정
        }

    def extract_documents(self, payload):
        return payload["documents"]

    def normalize(self, doc):
        return {
            "name": doc.get("place_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "category": doc.get("category_name", ""),
            "url": doc.get("place_url", ""),
            "lat": to_float(doc.get("y")),
            "lng": to_float(doc.get("x")),
        }

    def hint(self, status):
        return {
            401: "KAKAO_REST_API_KEY 값과 헤더의 'KakaoAK ' 접두어를 확인하세요",
            403: "카카오 개발자 사이트에서 앱 플랫폼 등록과 API 사용 설정을 확인하세요",
            429: "일일 호출 한도를 초과했습니다. 내일 다시 시도하세요",
        }.get(status, super().hint(status))


class NaverPlaceProvider(PlaceProvider):
    """Naver 지역 검색.

    ⚠️ 실제 자격증명이 없어 호출 검증을 하지 못했다.
    아래 두 가지는 Naver 응답의 알려진 특징이며, 키를 발급받으면 먼저 확인할 것.
      - title에 검색어 강조용 <b> 태그가 섞여 온다 → strip_tags()로 제거
      - mapx/mapy가 정수로 오며 경위도에 10^7을 곱한 값이다 → 나눠서 환산
        (계정·버전에 따라 좌표계가 다를 수 있으므로 첫 호출에서 값을 눈으로 확인할 것)
    """

    name = "naver"
    label = "Naver Local Search"
    required_env = ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
    URL = "https://openapi.naver.com/v1/search/local.json"
    COORD_SCALE = 10 ** 7

    def build_request(self, city, count, creds):
        return {
            "url": self.URL,
            "headers": {"X-Naver-Client-Id": creds["NAVER_CLIENT_ID"],
                        "X-Naver-Client-Secret": creds["NAVER_CLIENT_SECRET"]},
            "params": {"query": f"{city} 맛집", "display": count, "sort": "random"},
        }

    def extract_documents(self, payload):
        return payload["items"]

    def _coord(self, value):
        number = to_float(value)
        if number is None:
            return None
        # 경위도면 소수점 값(127.0), 10^7 배수면 큰 정수(1270000000)로 온다
        return number / self.COORD_SCALE if abs(number) > 1000 else number

    def normalize(self, doc):
        return {
            "name": strip_tags(doc.get("title", "")),
            "address": doc.get("roadAddress") or doc.get("address", ""),
            "category": doc.get("category", ""),
            "url": doc.get("link", ""),
            "lat": self._coord(doc.get("mapy")),
            "lng": self._coord(doc.get("mapx")),
        }

    def hint(self, status):
        return {
            401: "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 값과 헤더 이름 철자를 확인하세요",
            403: "네이버 개발자센터에서 해당 앱의 검색 API 사용 설정을 확인하세요",
            429: "일일 호출 한도를 초과했습니다. 내일 다시 시도하세요",
        }.get(status, super().hint(status))


PLACE_PROVIDERS = {
    KakaoPlaceProvider.name: KakaoPlaceProvider,
    NaverPlaceProvider.name: NaverPlaceProvider,
}


def get_place_provider(name=None):
    """팩토리. 환경변수 PLACE_PROVIDER로 제공자를 갈아끼운다 (기본: kakao)."""
    key = (name or os.getenv("PLACE_PROVIDER") or DEFAULT_PLACE_PROVIDER).strip().lower()
    provider_class = PLACE_PROVIDERS.get(key)
    if provider_class is None:
        print()
        print(f"❌ 알 수 없는 장소 검색 제공자입니다: {key!r}")
        print(f"   사용 가능: {', '.join(sorted(PLACE_PROVIDERS))}")
        print("   환경변수 PLACE_PROVIDER 값을 확인하세요.")
        sys.exit(1)
    return provider_class()


def search_restaurants(city, provider, errors, count=None):
    """맛집을 검색한다. 어떤 실패든 빈 리스트를 돌려주고 프로그램은 계속된다.

    제공자에 따라 달라지는 부분은 전부 provider 어댑터가 담당하므로,
    이 함수는 제공자가 바뀌어도 그대로다.
    """
    count = count or RESTAURANT_COUNT
    stage = f"{provider.name}_search"
    creds = provider.credentials()

    if creds is None:
        missing = ", ".join(provider.missing_env())
        record_error(errors, stage, "auth", f"{missing} 미설정")
        log_end(f"⚠ 건너뜀 ({missing} 미설정)")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    request = provider.build_request(city, count, creds)
    try:
        response = requests.get(
            request["url"],
            headers=request["headers"],
            params=request["params"],
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        documents = provider.extract_documents(response.json())

    except requests.exceptions.Timeout:
        record_error(errors, stage, "network", f"{REQUEST_TIMEOUT}초 내 응답 없음")
        log_end("⚠ 실패 (응답 시간 초과)")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    except requests.exceptions.ConnectionError:
        record_error(errors, stage, "network", "네트워크 연결 실패")
        log_end("⚠ 실패 (네트워크 연결)")
        log_detail("인터넷 연결을 확인해 주세요. 리포트 생성은 계속합니다")
        return []

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code
        record_error(errors, stage,
                     {401: "auth", 403: "auth", 429: "quota"}.get(status, "api"),
                     f"HTTP {status}")
        log_end(f"⚠ 실패 (HTTP {status})")
        log_detail(provider.hint(status))
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    except (ValueError, KeyError) as exc:
        record_error(errors, stage, "parse", f"응답 형식이 예상과 다름: {exc}")
        log_end("⚠ 실패 (응답 파싱)")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    if not documents:
        record_error(errors, stage, "empty", f"'{city} 맛집' 검색 결과 0건")
        log_end("0건")
        log_detail("맛집은 '데이터 없음'으로 리포트에 표기됩니다")
        return []

    restaurants = [provider.normalize(doc) for doc in documents]
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

    gemini_key = load_api_keys()
    provider = get_place_provider()
    ready = f"Gemini, {provider.label}" if provider.credentials() else "Gemini"
    log(1, "API 키 확인", f"완료 ({ready})")
    if not provider.credentials():
        missing = ", ".join(provider.missing_env())
        log_detail(f"{missing} 미설정 — 맛집 검색을 건너뜁니다")

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
        if recommendation.get("recommended_city_raw"):
            log_detail("도시명 정규화: "
                       f"'{recommendation['recommended_city_raw']}' → "
                       f"'{recommendation['recommended_city']}' "
                       f"({', '.join(recommendation['normalization'])})")
        log_start(4, f"맛집 검색 ({provider.label})")
        restaurants = search_restaurants(recommendation["recommended_city"], provider, errors)
        save_raw({
            "input_date": date_str,
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "place_provider": provider.name,
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
