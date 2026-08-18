# 📄 여행 추천 리포트 생성기 PRD & 7일 실행 계획

> `-date`로 받은 날짜에 대해 **LLM으로 여행지를 추천받고 → 그 도시의 맛집을 지도 API로 검색해 →
> 최종 여행 리포트(Markdown)를 생성하는** Python CLI 프로그램 개발 계획서

| 항목 | 내용 |
|------|------|
| 문서 버전 | v1 (2026-08-18) |
| 과제 | 2026년 AI활용학습 A1-2 |
| 작성자 | 김재민 |
| 이전 과제 | `../AI활용학습_A1_1` (Prompt Manager) |

---

## 0. 확정 사항 (착수 전 결정)

과제 요구사항은 제공자를 "택1"로 열어두었습니다. 아래는 **확정된 선택과 그 근거**입니다.
이 선택에 따라 인증 헤더·응답 필드·파싱 코드가 전부 달라지므로 착수 전에 고정합니다.

| 결정 항목 | 확정 | 근거 |
|-----------|------|------|
| LLM API | **Google Gemini** | 무료 티어로 과제 수행이 가능하고, `response_mime_type="application/json"`으로 **JSON 출력을 API 레벨에서 강제**할 수 있어 요구사항 3의 "JSON으로 파싱 가능한 텍스트"를 프롬프트에만 의존하지 않아도 됨 |
| 지도/장소 API | **Kakao Local** (키워드 검색) | REST 키 1개를 헤더에 넣는 단순한 인증이고, 응답에 `place_name`·`category_name`·`place_url`·`x`/`y`(WGS84 경위도)가 그대로 있어 **요구사항 4의 최소 필드를 좌표 변환 없이 충족** |
| 보너스 | **결과 캐싱만 채택** | 복수 지역은 미채택 → `recommended_city`는 **단수 문자열**로 유지 |
| 파일 구성 | `trip_planner.py` **단일 파일** | 과제의 초점이 아키텍처가 아니라 API 연동이므로, 리뷰·제출이 쉬운 단일 파일 유지 (A1-1과 동일 방침) |

> ⚠️ **복수 지역 보너스를 나중에 추가하지 않기로 했으므로** `recommended_city`(단수)로 스키마를 확정합니다.
> 만약 진행 중 마음이 바뀌면 스키마·저장 파일·리포트 구조를 함께 고쳐야 하므로 Day 3 이전에 결정해야 합니다.

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 이름 | Trip Planner (여행 추천 리포트 생성기) |
| 목적 | 날짜 하나를 입력받아 → LLM 추천 → 장소 검색 → 리포트까지 자동 생성하는 CLI 프로그램 |
| 환경 | Python 3.10+ / 외부 라이브러리 사용 (`google-genai`, `requests`, `python-dotenv`) |
| 학습 목표 | REST API 요청·응답 구조, LLM 출력의 구조화(JSON) 및 체이닝, 외부 API 오류 처리, 키 관리 |
| 실행 형태 | 터미널 CLI (웹 UI 없음) |
| 산출물 | `results/*.json` (원본 데이터), `results/*.md` (최종 리포트), `README.md` |

### A1-1과 달라지는 점

| 항목 | A1-1 (Prompt Manager) | A1-2 (Trip Planner) |
|------|----------------------|---------------------|
| 입력 방식 | 대화형 메뉴 (`input()` 루프) | **CLI 인자 1회 실행** (`argparse`) |
| 외부 라이브러리 | 미사용 (표준 라이브러리만) | **사용** (HTTP·SDK·dotenv) |
| 실패 지점 | 사용자 입력 오류만 | **네트워크·인증·쿼터·파싱** — 내가 통제할 수 없는 실패 |
| 핵심 난이도 | 자료구조 설계 | **부분 실패를 안고도 끝까지 진행하기** |

> A1-1에서는 "잘못된 입력에 안내 메시지"가 예외 처리의 전부였습니다.
> 이번에는 **외부 서비스가 죽어도 프로그램은 결과를 내야 합니다.** 이것이 이 과제의 중심입니다.

### 실제 환경 확인 결과

| 항목 | 상태 |
|------|------|
| Python | `3.14.6` ✅ (3.10 이상 충족 — A1-1에서 확인) |
| Git | `2.55.0` ✅ |
| 작업 폴더 | `AI활용학습_A1_2` (현재 비어 있음) |
| Git 저장소 | ❌ 아직 `git init` 안 됨 → Day 1 |
| Gemini API 키 | ⬜ 발급 필요 → Day 1 |
| Kakao REST 키 | ⬜ 발급 필요 → Day 1 |

---

## 2. 요구사항 추적표 (과제 요건 ↔ 대응 계획)

제출 직전 이 표만 보고 자체 채점할 수 있게 만든 표입니다.

### 2.1 산출물

| 과제 요건 | 대응 위치 | 완료 |
|-----------|-----------|------|
| CLI 기반 Python 프로그램 | `trip_planner.py` §4 | [ ] |
| `-date "YYYY-MM-DD"` 필수 옵션 | §4.1 | [ ] |
| 진행 로그 + 결과 저장 경로 안내 출력 | §10 | [ ] |
| `results/` 폴더에 원본 JSON 1개 이상 | §6.3 | [ ] |
| 원본 JSON에 1차 추천 + 맛집 결과 포함 | §6.3 | [ ] |
| 최종 여행 리포트 Markdown 1개 | §11 | [ ] |
| README (개요·실행·키 설정·결과 확인) | Day 6 | [ ] |
| README에 키 유출 주의사항 | §8 | [ ] |

### 2.2 기능 요구사항

| # | 과제 요건 | 대응 위치 | 완료 |
|---|-----------|-----------|------|
| 1 | `argparse`로 CLI 실행 | §4.1 | [ ] |
| 1 | 날짜 형식 오류 → **사용법 출력 후 종료** | §4.2 / E1 | [ ] |
| 2 | LLM API 택1 (Gemini) | §5.1 | [ ] |
| 2 | 지도 API 택1 (Kakao Local) | §5.2 | [ ] |
| 3 | 입력 `date` → 1차 추천 JSON 생성 | §5.1 | [ ] |
| 3 | `recommended_city` (string) | §6.1 | [ ] |
| 3 | `weather` (string) | §6.1 | [ ] |
| 3 | `events` (array of string, 1~3) | §6.1 | [ ] |
| 3 | `reason` (string, 2~4문장) | §6.1 | [ ] |
| 4 | `recommended_city`를 입력으로 맛집 5곳 검색 | §5.2 | [ ] |
| 4 | 맛집 필드 `name`/`address`/`category`/`url`/좌표 | §6.2 | [ ] |
| 4 | **검색 0건이어도 중단하지 않고 리포트로 진행** | E5 | [ ] |
| 5 | 1차 JSON + 맛집 목록 → 최종 리포트 Markdown | §5.3 | [ ] |
| 5 | 리포트에 추천 지역 + 추천 이유 | §11 | [ ] |
| 5 | 리포트에 날씨 요약 | §11 | [ ] |
| 5 | 리포트에 행사/축제 목록 | §11 | [ ] |
| 5 | 리포트에 맛집 리스트 (0건이면 "데이터 없음") | §11 | [ ] |
| 5 | 리포트에 1일 일정(오전/오후/저녁) | §11 | [ ] |
| 6 | `try-except`로 호출/파싱 오류 처리 | §7 | [ ] |
| 6 | 키 미설정 → 즉시 종료 + 설정 방법 안내 | E2 | [ ] |
| 6 | 지도 API 실패 → 맛집 "데이터 없음" + 리포트는 계속 | E6~E9 | [ ] |
| 6 | LLM JSON 파싱 실패 → **재시도 최대 1회** | E3 | [ ] |
| 6 | 내부 오류 목록 관리 (`errors`, 빈 리스트 가능) | §6.3 | [ ] |
| 7 | 키를 코드에 직접 쓰지 않음 | §8 | [ ] |
| 7 | 환경변수 또는 `.env`에서 읽기 | §8 | [ ] |
| 7 | 제출물(README/로그/결과)에 키 미노출 | §8 | [ ] |
| 8 | `results/` 폴더 생성 후 날짜 기준 저장 | §6.4 | [ ] |
| 8 | 원본 JSON에 1차 추천 + 맛집 + `errors` | §6.3 | [ ] |
| 8 | 최종 리포트 `.md` 저장 | §6.4 | [ ] |
| 보너스 | 같은 `-date` 재실행 시 캐시 사용 | §9 | [ ] |

---

## 3. 시스템 구조

### 3.1 처리 흐름

```
  $ python trip_planner.py -date "2026-09-20"
        │
        ▼
  [0] 날짜 검증 ────────── 실패 → 사용법 출력 후 종료 (exit 2)
        │
        ▼
  [1] API 키 로드 ──────── 미설정 → 설정 안내 후 종료 (exit 1)
        │
        ▼
  [2] 캐시 확인 ────────── 있음 → [3][4] 건너뛰고 [5]로  (보너스)
        │ 없음
        ▼
  [3] Gemini ─ 1차 추천 ── 파싱 실패 → 1회 재시도 → 또 실패 시 종료 (exit 1)
        │  { recommended_city, weather, events[], reason }
        ▼
  [4] Kakao ─ 맛집 검색 ── 실패/0건 → restaurants=[] + errors 기록 후 계속 ⭐
        │  [ { name, address, category, url, lat, lng } × 5 ]
        ▼
  [5] 원본 JSON 저장 ───── results/trip_2026-09-20_raw.json
        │
        ▼
  [6] Gemini ─ 리포트 ──── 실패 → 로컬 템플릿으로 대체 생성
        │
        ▼
  [7] 리포트 저장 + 경로 안내 ── results/trip_2026-09-20_report.md
```

**⭐ 표시가 이 과제의 핵심입니다.** [4]가 실패해도 [5][6][7]은 반드시 실행됩니다.

### 3.2 함수 목록

**규약: 모든 API 호출 함수는 `errors` 리스트를 인자로 받아 실패를 기록한다.**
(리스트는 가변 객체라 함수 안에서 `append`하면 호출한 쪽에 반영됨 — A1-1과 동일한 규약)

```python
# --- CLI ---
def valid_date(s):                          # argparse type= 검증 함수
def parse_args():                           # argparse 구성 및 파싱

# --- 설정 ---
def load_api_keys():                        # .env/환경변수에서 키 로드, 없으면 종료

# --- LLM (Gemini) ---
def build_recommend_prompt(date_str):       # 1차 추천 프롬프트 생성
def build_retry_prompt(date_str):           # 재시도용 축약 프롬프트 (필수 키만)
def call_gemini(client, prompt, as_json):   # 공통 호출부 (JSON 모드 on/off)
def get_recommendation(client, date_str, errors)   # 파싱+검증+1회 재시도
def validate_recommendation(data):          # 필수 키/타입 검증 → bool

# --- 지도 (Kakao) ---
def search_restaurants(city, key, errors, size=5)  # 키워드 검색
def normalize_place(doc):                   # Kakao 응답 → 공통 스키마 변환

# --- 리포트 ---
def build_report_prompt(recommendation, restaurants)
def generate_report(client, recommendation, restaurants, errors)
def build_fallback_report(recommendation, restaurants, errors)  # LLM 실패 시 로컬 생성

# --- 저장 ---
def ensure_results_dir()
def raw_path(date_str) / report_path(date_str)
def save_raw(payload, date_str)
def save_report(markdown, date_str)
def load_cache(date_str)                    # 보너스

# --- 로그 ---
def log(step, message)                      # [1/6] 형식 진행 로그

def main()
```

### 3.3 파일 구조

```
AI활용학습_A1_2/
├── trip_planner.py          # 프로그램 본체 (단일 파일)
├── requirements.txt         # google-genai, requests, python-dotenv
├── .env                     # 실제 키 — ❌ 커밋 금지
├── .env.example             # 키 이름만 있는 견본 — ✅ 커밋
├── .gitignore
├── README.md
├── trip_planner_PRD.md      # 이 문서
├── results/                 # 실행 결과 (커밋 여부는 §8 참고)
│   ├── trip_2026-09-20_raw.json
│   └── trip_2026-09-20_report.md
└── docs/screenshots/        # 제출용 스크린샷
```

---

## 4. CLI 명세

### 4.1 인자

| 인자 | 필수 | 형식 | 설명 |
|------|:---:|------|------|
| `-date` | ✅ | `YYYY-MM-DD` | 여행 날짜 |

```bash
python trip_planner.py -date "2026-09-20"
```

> **왜 `--date`가 아니라 `-date`인가** — 과제 요구사항이 `-date`로 명시했기 때문입니다.
> argparse는 하이픈 1개 + 여러 글자 형태의 옵션도 지원합니다.
> 익숙한 `--date`도 함께 쓰고 싶으면 `add_argument("-date", "--date", ...)`로 별칭을 줄 수 있습니다.
> (둘 다 `args.date`로 들어옵니다)

### 4.2 날짜 검증

**검증은 `argparse`의 `type=` 함수에서 합니다.** 직접 `if`로 검사하지 않습니다.

```python
def valid_date(value):
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
```

> ⚠️ **초안의 오류를 실행해 보고 발견했습니다.** 처음에는 `strptime` 하나면 충분하다고
> 적었지만, **파이썬의 `%m`·`%d`는 0을 뺀 한 자리 표기도 받아들입니다.**
> 그래서 `2026-9-20`이 그대로 통과해 API 호출까지 진행됐습니다.
> 파싱 결과를 다시 문자열로 만들어(`isoformat()`) 입력과 비교해야 막힙니다.

`ArgumentTypeError`를 던지면 argparse가 **사용법(usage)을 자동 출력하고 exit code 2로 종료**합니다.
과제 요건 "형식이 올바르지 않으면 사용법을 출력하고 종료"가 이 한 가지로 충족됩니다.

`strptime`을 쓰는 이유는 형식과 실재 여부를 **동시에** 걸러내기 때문입니다.
정규식(`\d{4}-\d{2}-\d{2}`)만 쓰면 `2026-13-45` 같은 값이 통과합니다.

> 💡 **`sys.stderr`도 UTF-8로 고정해야 합니다.** argparse는 오류 메시지를 **stdout이 아니라
> stderr로** 출력합니다. `sys.stdout`만 재설정하면 cp949 터미널에서 날짜 오류 안내가
> 깨져 나옵니다. 실제로 겪고 고쳤습니다.

| 입력 | 결과 |
|------|------|
| `2026-09-20` | ✅ 통과 |
| `2026-9-20` | ❌ 왕복 비교에서 차단 (**`strptime`만으로는 통과함** — 위 경고 참고) |
| `2026/09/20` | ❌ 구분자 불일치 |
| `2026-13-01` | ❌ 13월 없음 |
| `2026-02-30` | ❌ 존재하지 않는 날 |
| (인자 생략) | ❌ argparse가 `required` 위반으로 사용법 출력 |

---

## 5. 외부 API 명세

### 5.0 REST API 기초 (과제 목표 대응)

| 개념 | 내용 |
|------|------|
| **요청(Request)** | 메서드 + URL + 헤더 + (본문). 이 프로그램은 `Authorization` 헤더로 인증합니다. |
| **응답(Response)** | 상태 코드 + 헤더 + 본문(JSON). 상태 코드로 성공/실패를 먼저 판정합니다. |
| **GET** | 자원을 **조회**. 파라미터가 URL 쿼리스트링에 붙고, 본문이 없습니다. → Kakao 맛집 검색 |
| **POST** | 자원을 **생성/처리 요청**. 데이터를 **본문(body)에 담아** 보냅니다. → Gemini 생성 요청 |

> **왜 검색은 GET이고 생성은 POST인가** — GET은 URL에 모든 정보가 담겨 같은 URL이면 같은 결과를
> 기대할 수 있고(캐시 가능), 길이 제한이 있습니다. 프롬프트처럼 길고 매번 결과가 달라지는 입력은
> URL에 실을 수 없으므로 본문에 담는 POST를 씁니다.
> (Gemini는 SDK가 POST를 감싸고 있어 코드에 직접 드러나지 않습니다)

### 5.1 Gemini — 1차 추천

| 항목 | 값 |
|------|-----|
| SDK | `google-genai` (`from google import genai`) |
| 모델 | `gemini-3.6-flash` |
| 스키마 강제 | `response_schema=RECOMMEND_SCHEMA` |
| 환경변수 | `GEMINI_API_KEY` |
| 출력 강제 | `response_mime_type="application/json"` |

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)
response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
    config=types.GenerateContentConfig(response_mime_type="application/json"),
)
data = json.loads(response.text)
```

> ✅ **모델 확정: `gemini-3.6-flash` (2026-08-18 실측)**
>
> 선택 과정에서 두 번 걸렸습니다.
>
> | 후보 | 결과 |
> |------|------|
> | `gemini-3.5-flash` | 호출은 되지만 **무료 한도가 하루 20회**라 개발 중 금방 소진 |
> | `gemini-2.5-flash` | `models.list`에는 보이지만 호출 시 **404** — "no longer available to new users" |
> | **`gemini-3.6-flash`** | ✅ 정상 동작. 위 404 응답이 직접 지목한 대체 모델 |
>
> ⚠️ **`models.list`에 있다고 호출 가능한 것이 아닙니다.** 목록에는 계정이 쓸 수 없는
> 모델도 함께 나옵니다. 실제 호출을 한 번 해봐야 확인됩니다.
>
> ⚠️ **무료 한도는 모델별로 따로 잡힙니다** (`GenerateRequestsPerDayPerProjectPerModel`).
> 한 모델이 429로 막혀도 다른 모델은 쓸 수 있습니다. 전체 실행 1회에 Gemini를
> **2회**(추천 + 리포트) 호출하므로, 하루 20회면 약 10회 실행분입니다.
> **캐싱(§9)이 보너스가 아니라 사실상 필수인 이유입니다.**
>
> 재확인이 필요하면 아래로 목록을 다시 뽑을 수 있습니다. **키 인증 확인을 겸합니다.**
>
> ```bash
> curl -s -H "x-goog-api-key: $GEMINI_API_KEY" "https://generativelanguage.googleapis.com/v1beta/models" | grep -o '"name": "models/[^"]*"'
> ```
>
> `401`/`403`이면 키 문제입니다.
> (키를 URL 쿼리스트링이 아니라 `x-goog-api-key` 헤더로 보내는 이유는, 쿼리스트링에 담으면
> 셸 히스토리·서버 접근 로그·프록시 로그에 키가 평문으로 남기 때문입니다)
>
> ⚠️ **아직 확인 안 된 것 — SDK 패키지.** 구형 `google-generativeai`(`import google.generativeai as genai`)와
> 신형 `google-genai`(`from google import genai`)는 **호출 방식이 다릅니다.**
> 이 문서는 신형 기준으로 작성했습니다.

**프롬프트 설계 원칙 (실측으로 개정됨)**

> ⚠️ **초안의 원칙 1번은 틀렸습니다.** 처음에는 "출력 형식을 예시 JSON으로 보여준다"로
> 적었는데, 실제로 재보니 **그게 실패 원인이었습니다.**
>
> | 프롬프트 | 결과 |
> |----------|------|
> | 예시 JSON 블록 **포함** | 완료 5건 중 **4건 파싱 실패** |
> | 예시 없이 **산문으로만** 지시 | 10건 중 **0건 실패** |
>
> 실패 형태가 두 가지였습니다.
> - `Extra data: line 10 column 1` — **프롬프트의 예시 객체를 먼저 출력하고 그 뒤에
>   진짜 답을 이어 붙여** JSON 객체가 두 개가 됨
> - `Expecting ',' delimiter: line 8` — `reason` 문자열 중간이 깨짐
>
> **`response_mime_type="application/json"`은 "JSON 하나만"을 보장하지 않습니다.**
> 형식은 `response_schema`에 맡기고, 프롬프트는 내용만 지시합니다.

1. **예시 JSON 블록을 넣지 않는다.** 구조는 `response_schema`가 강제한다.
2. 각 키에 **무엇을 담을지**를 산문으로 지시한다 (`events`는 행사명 1~3개).
3. 국내 여행지로 한정한다 — 다음 단계가 국내 장소 검색 API이기 때문.
4. 재시도용 프롬프트(§E3)는 **더 짧게** 만든다. 같은 프롬프트로 다시 물으면 같은 실패가 반복된다.

```
당신은 국내 여행 플래너입니다.
{date} 날짜에 국내 여행을 간다면 어디가 좋을지 한 곳을 추천하고,
아래 JSON 형식으로만 답하십시오. 코드블록이나 설명 문장 없이 JSON만 출력합니다.

{
  "recommended_city": "도시명 (예: 제주, 강릉)",
  "weather": "해당 시기의 일반적인 날씨 요약 한 문장",
  "events": ["행사 또는 축제명", "..."],
  "reason": "추천 근거 2~4문장"
}

규칙:
- recommended_city는 국내 도시 한 곳의 이름만. 시/도 접미사 없이 간결하게.
- events는 문자열 배열이며 1개 이상 3개 이하.
- 확정된 사실이 아니면 일반적인 시기 정보로 작성해도 됩니다.
```

> **왜 "정확도"를 요구하지 않는가** — 과제 명세가 실제 날씨·행사의 정확도를 평가하지 않는다고
> 명시했습니다. 목표는 **출력이 구조화되어 다음 단계의 입력으로 연결되는 것**입니다.
> 그래서 프롬프트도 정확성보다 **형식 준수**에 지면을 씁니다.

### 5.2 Kakao Local — 맛집 검색

| 항목 | 값 |
|------|-----|
| 메서드 | `GET` |
| URL | `https://dapi.kakao.com/v2/local/search/keyword.json` |
| 인증 헤더 | `Authorization: KakaoAK {REST_API_KEY}` |
| 환경변수 | `KAKAO_REST_API_KEY` |

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| `query` | `"{city} 맛집"` | 검색 키워드 |
| `size` | `5` | 결과 개수 (권장 5곳, 최대 15) |
| `category_group_code` | `FD6` | 음식점으로 한정 (`CE7`은 카페) |

```python
resp = requests.get(
    "https://dapi.kakao.com/v2/local/search/keyword.json",
    headers={"Authorization": f"KakaoAK {kakao_key}"},
    params={"query": f"{city} 맛집", "size": 5, "category_group_code": "FD6"},
    timeout=10,
)
resp.raise_for_status()
documents = resp.json()["documents"]
```

> **`timeout`을 반드시 지정합니다.** 생략하면 서버가 응답하지 않을 때 프로그램이
> 무한정 멈춥니다. 예외조차 발생하지 않으므로 사용자는 원인을 알 수 없습니다.

**응답 필드 → 공통 스키마 변환** (`normalize_place()`)

| Kakao 응답 | 우리 스키마 | 비고 |
|-----------|------------|------|
| `place_name` | `name` | |
| `road_address_name` \|\| `address_name` | `address` | 도로명 우선, 없으면 지번 |
| `category_name` | `category` | 예: `"음식점 > 한식 > 육류,고기"` |
| `place_url` | `url` | 카카오맵 상세 페이지 |
| `x` | `lng` | **경도**. 문자열로 오므로 `float()` 변환 |
| `y` | `lat` | **위도**. 문자열로 오므로 `float()` 변환 |

> ✅ **실제 응답으로 검증 완료 (2026-08-18)** — `query="강릉 맛집"`, `category_group_code=FD6`으로
> 호출한 결과 위 표의 필드가 전부 그대로 존재했습니다. 총 검색 건수 4,189건.
>
> ```
> place_name        = '강릉 ○○코다리찜'
> road_address_name = '강원특별자치도 강릉시 초당순두부길 96'
> address_name      = '강원특별자치도 강릉시 초당동 12-3'
> category_name     = '음식점 > 한식 > 코다리요리'
> place_url         = 'http://place.map.kakao.com/25754890'
> x                 = '128.91609322357172'   ← 경도, 문자열
> y                 = '37.79104417963563'    ← 위도, 문자열
> ```
>
> 강릉의 실제 좌표가 북위 37.8 / 동경 128.9이므로 **`x`=경도, `y`=위도가 맞습니다.**
> 두 값이 **따옴표로 감싸인 문자열**인 것도 확인했습니다 → `float()` 변환 필수.
> `distance`는 중심 좌표를 안 넘기면 빈 문자열(`''`)로 옵니다.

> ⚠️ **`x`가 경도(lng), `y`가 위도(lat)입니다.** 화면 좌표 감각으로 `x=lat`이라고 넣기 쉬운데,
> 그러면 지도에 찍었을 때 엉뚱한 곳(적도 근처 바다)이 나옵니다.
> 또 두 값 모두 **문자열**로 오므로 숫자로 쓰려면 `float()`가 필요합니다.

**상태 코드별 대응**

| 코드 | 의미 | 점검 사항 |
|:---:|------|-----------|
| `401` | 인증 실패 | 키 값 오타, **`KakaoAK ` 접두어 누락**, 헤더명 오타 |
| `403` | 권한 없음 | 앱 설정에서 해당 API 활성화 여부, 플랫폼(도메인/IP) 등록 |
| `429` | 쿼터 초과 | 일일 한도 소진 → 다음 날 재시도 |
| `5xx` | 서버 오류 | 카카오 측 문제 → 재시도 |

### 5.3 Gemini — 최종 리포트

1차 추천 JSON + 맛집 목록을 **문자열로 만들어 프롬프트에 넣고**, Markdown 텍스트를 받습니다.
이번에는 JSON이 아니므로 `response_mime_type`을 **지정하지 않습니다.**

```
아래 데이터로 여행 리포트를 Markdown으로 작성하십시오.

[추천 정보]
{recommendation을 보기 좋게 편 문자열}

[맛집 목록]
{restaurants 목록 또는 "데이터 없음"}

포함할 항목:
1. 추천 지역과 추천 이유 요약
2. 날씨 요약
3. 행사·축제 목록
4. 맛집 리스트 (데이터가 없으면 "데이터 없음"이라고 명시)
5. 1일 일정 제안 (오전 / 오후 / 저녁)

없는 정보를 지어내지 마십시오. 맛집이 0건이면 0건이라고 쓰십시오.
```

> **"지어내지 마십시오"를 명시하는 이유** — 맛집이 0건일 때 LLM은 그럴듯한 가게 이름을
> 만들어냅니다. 그러면 리포트에는 식당이 있는데 원본 JSON에는 없는 **모순된 제출물**이 됩니다.

---

## 6. 데이터 구조

### 6.1 1차 추천 JSON 스키마

```json
{
  "recommended_city": "강릉",
  "weather": "9월 하순의 강릉은 맑고 선선하며 일교차가 큽니다.",
  "events": ["강릉커피축제", "정동진 해맞이 축제"],
  "reason": "여름 성수기가 지나 해변이 한산합니다. ..."
}
```

| 키 | 타입 | 검증 규칙 |
|----|------|-----------|
| `recommended_city` | string | 공백 제거 후 비어 있지 않을 것 |
| `weather` | string | 비어 있지 않을 것 |
| `events` | array of string | 리스트이고 원소가 전부 문자열. 1~3개 (초과 시 앞 3개만 사용) |
| `reason` | string | 비어 있지 않을 것 |

> **"파싱 성공 = 검증 성공"이 아닙니다.** `json.loads`가 통과해도 `events`가 문자열
> 하나로 왔거나 키 이름이 다를 수 있습니다. `validate_recommendation()`으로 **키 존재와
> 타입을 따로 확인**하고, 실패하면 파싱 실패와 **동일하게** E3의 1회 재시도로 넘깁니다.

### 6.2 맛집 아이템 스키마

```json
{
  "name": "초당순두부",
  "address": "강원특별자치도 강릉시 초당순두부길 77",
  "category": "음식점 > 한식 > 두부요리",
  "url": "http://place.map.kakao.com/00000000",
  "lat": 37.7912,
  "lng": 128.9101
}
```

### 6.3 원본 데이터 JSON (저장 파일)

```json
{
  "input_date": "2026-09-20",
  "generated_at": "2026-08-18T14:32:10+09:00",
  "recommendation": { "...6.1과 동일..." },
  "restaurants": [ "...6.2 아이템 0~5개..." ],
  "errors": []
}
```

**`errors` 아이템 형식**

```json
{ "stage": "kakao_search", "type": "auth", "message": "401 Unauthorized" }
```

| `stage` | `type` 후보 |
|---------|------------|
| `recommendation` | `parse` / `network` / `api` |
| `kakao_search` | `auth` / `quota` / `network` / `parse` / `empty` |
| `report` | `network` / `api` |

> ⚠️ **`message`에 API 키가 섞이지 않게 합니다.** 예외 객체를 그대로 문자열로 만들면
> 요청 URL이나 헤더가 딸려올 수 있고, 그 파일은 그대로 커밋됩니다. §8 참고.

### 6.4 파일명 규칙

| 파일 | 경로 |
|------|------|
| 원본 데이터 | `results/trip_{date}_raw.json` |
| 최종 리포트 | `results/trip_{date}_report.md` |

**`{date}`는 `-date`로 받은 여행 날짜입니다 (프로그램을 실행한 날짜가 아닙니다).**

> **왜 실행 날짜가 아닌가** — 보너스인 캐싱이 "같은 `-date`로 재실행하면 저장된 JSON을
> 재사용"하는 기능입니다. 파일명이 실행 날짜로 붙으면 같은 `-date`를 다음 날 다시 돌렸을 때
> 캐시를 **찾지 못합니다.** 실행 시각은 파일명 대신 JSON 안의 `generated_at`에 남깁니다.

---

## 7. 예외 처리 명세

**분류 원칙: 실패를 두 종류로 나눕니다.**

| 구분 | 정의 | 처리 |
|------|------|------|
| **치명적 (Fatal)** | 이후 단계의 **입력이 사라지는** 실패 | 안내 출력 후 즉시 종료 |
| **부분 실패 (Degraded)** | 결과의 **일부만** 비는 실패 | `errors`에 기록하고 **계속 진행** |

> 맛집 검색이 실패해도 리포트는 만들 수 있습니다(맛집 = 데이터 없음).
> 하지만 1차 추천이 실패하면 **검색할 도시 자체가 없으므로** 진행할 수 없습니다.
> 이 차이가 아래 표의 "처리" 열을 결정합니다.

| ID | 상황 | 구분 | 처리 |
|----|------|:----:|------|
| E1 | 날짜 형식 오류 / `-date` 누락 | Fatal | argparse가 **사용법 출력 + exit 2** (§4.2) |
| E2 | `GEMINI_API_KEY` 미설정 | Fatal | 설정 방법 안내 출력 후 **exit 1** |
| E3 | 1차 추천 JSON 파싱 실패 **또는 스키마 검증 실패** | 재시도 | **필수 키만 출력하도록 프롬프트를 축약해 1회 재시도.** 2회째도 실패하면 exit 1 |
| E4 | Gemini 호출 자체 실패 (네트워크/인증) | Fatal | 원인 안내 후 exit 1 |
| E4-a | Gemini `503 UNAVAILABLE` (모델 과부하) | 재시도 | **3회까지 2·4초 간격으로 재시도.** 일시적 오류라 잠시 뒤 대개 풀림 |
| E4-b | Gemini `429 RESOURCE_EXHAUSTED` (무료 한도 초과) | Fatal | 한도 소진 안내 후 exit 1. 재시도해도 그날은 풀리지 않음 |
| E5 | Kakao 검색 결과 **0건** | Degraded | `restaurants=[]`, `errors`에 `type:"empty"` 기록, **리포트 계속** |
| E6 | Kakao `401`/`403` | Degraded | 키·헤더·플랫폼 설정 점검 안내 출력, `restaurants=[]`, **리포트 계속** |
| E7 | Kakao `429` (쿼터) | Degraded | 한도 초과 안내, `restaurants=[]`, **리포트 계속** |
| E8 | Kakao 네트워크 오류 / 타임아웃 | Degraded | `restaurants=[]`, **리포트 계속** |
| E9 | Kakao 응답 JSON 파싱 실패 / `documents` 키 없음 | Degraded | `restaurants=[]`, **리포트 계속** |
| E10 | 최종 리포트 생성 실패 | Degraded | **로컬 템플릿으로 리포트 생성** (`build_fallback_report()`) |
| E11 | `KAKAO_REST_API_KEY` 미설정 | Degraded | 맛집 단계를 건너뛰고 `errors` 기록 후 계속 |

> **E11을 Fatal로 하지 않는 이유** — 과제 요건 6이 "지도/장소 API 실패 시 맛집 섹션을
> 데이터 없음 처리하고 리포트 생성은 계속"이라고 명시했습니다. 키가 없는 것도 그 API를
> 쓸 수 없는 상황이므로 같은 정책을 적용합니다. 반면 `GEMINI_API_KEY`가 없으면
> 1차 추천도 리포트도 만들 수 없어 프로그램이 할 일이 남지 않으므로 E2는 Fatal입니다.

> **E4-a의 재시도가 "무한 재시도 금지"에 걸리지 않는 이유** — 과제 제약이 금지한 것은
> **JSON 파싱 실패에 대한 재요청**이며 그것은 E3에서 정확히 1회로 묶여 있습니다.
> E4-a는 전송 계층에서 서버가 "지금 붐빈다"고 답한 경우로 성격이 다르고,
> 횟수가 3회로 고정되어 있어 무한 루프가 되지 않습니다.
> 실측에서 `gemini-3.6-flash` 이전 모델은 8건 중 7건이 503으로 실패할 만큼 잦았습니다.

> **E10의 대체 생성** — 리포트는 이 프로그램의 최종 산출물입니다. LLM이 실패했다고
> 빈손으로 끝내면 요건 "최종 리포트 Markdown 1개"가 깨집니다. 이미 `recommendation`과
> `restaurants`를 손에 쥐고 있으므로 f-string으로 같은 항목을 채운 Markdown을 만들 수 있습니다.

### 예외를 잡는 범위

```python
# ❌ 너무 넓다 — 오타(NameError)까지 삼켜서 디버깅이 불가능해진다
try:
    ...
except Exception:
    pass

# ✅ 예상한 예외를 종류별로 구분한다
try:
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    documents = resp.json()["documents"]
except requests.exceptions.Timeout:          # E8
except requests.exceptions.ConnectionError:  # E8
except requests.exceptions.HTTPError as e:   # E6/E7 — 상태 코드로 분기
except (ValueError, KeyError):               # E9 — JSON 파싱 / 키 없음
```

---

## 8. 보안 — API 키 관리

### 8.1 왜 코드에 쓰지 않는가

| 이유 | 설명 |
|------|------|
| 공유 사고 방지 | 저장소를 공개하거나 코드를 남에게 보내는 순간 키가 함께 나갑니다. |
| 교체 용이 | 키를 갱신할 때 코드를 고치고 다시 커밋할 필요가 없습니다. |
| 과금 사고 예방 | 유출된 키로 제3자가 쿼터를 소진하면 비용과 한도가 내 계정에 청구됩니다. |

> ⚠️ **한 번 커밋된 키는 파일에서 지워도 남습니다.** Git은 이력을 보존하므로
> 이전 커밋을 되짚으면 그대로 보입니다. 실수로 커밋했다면 **파일 수정이 아니라
> 키 재발급(폐기)** 이 정답입니다.

### 8.2 키 목록

| 환경변수 | 용도 | 없을 때 |
|----------|------|---------|
| `GEMINI_API_KEY` | Gemini 호출 | **즉시 종료** (E2) |
| `KAKAO_REST_API_KEY` | Kakao Local 호출 | 맛집 건너뛰고 계속 (E11) |

### 8.3 설정 방법 (README에도 동일 수록)

`.env` 파일 (권장):

```
GEMINI_API_KEY=여기에_발급받은_키
KAKAO_REST_API_KEY=여기에_발급받은_키
```

```python
from dotenv import load_dotenv
load_dotenv()                      # .env를 환경변수로 로드
key = os.getenv("GEMINI_API_KEY")  # 없으면 None
```

환경변수로 직접(현재 세션에만 적용):

```bash
export GEMINI_API_KEY="YOUR_KEY"
```

```powershell
$env:GEMINI_API_KEY="YOUR_KEY"
```

### 8.4 유출 방지 점검 항목

- [ ] `.gitignore`에 **`.env`** 가 있는가
- [ ] `.env.example`에는 **키 이름만** 있고 값이 비어 있는가
- [ ] 코드에 키 문자열 리터럴이 없는가 (`grep -rn "AIza\|KakaoAK " --include=*.py`)
- [ ] **진행 로그에 헤더나 전체 URL을 출력하지 않는가** ← 가장 흔한 실수
- [ ] `errors[].message`에 예외 원문을 통째로 넣지 않는가 (§6.3)
- [ ] **스크린샷에 터미널 환경변수나 `.env` 내용이 찍히지 않았는가**
- [ ] README의 키 설정 예시가 `YOUR_KEY` 자리표시자인가

> **로그 출력 시 원칙**: 키는 아예 출력하지 않습니다.
> 굳이 확인이 필요하면 `key[:4] + "***"` 처럼 앞 4글자만 남깁니다.

---

## 9. 캐싱 (보너스)

같은 `-date`로 다시 실행하면 **API를 호출하지 않고** 저장된 원본 JSON으로 리포트만 다시 만듭니다.

```
results/trip_{date}_raw.json 존재?
   ├─ 예 → 읽어서 recommendation / restaurants 복원 → [6] 리포트 생성으로 점프
   └─ 아니오 → [3] Gemini부터 정상 수행
```

| 항목 | 결정 |
|------|------|
| 캐시 키 | `-date` 값 (파일명, §6.4) |
| 유효 기간 | 없음 (파일이 있으면 무조건 사용) |
| 무시하는 법 | `results/trip_{date}_raw.json` 파일을 지우고 재실행 |
| 캐시 파일이 깨졌을 때 | 파싱 실패 시 캐시를 **무시하고** 정상 경로로 진행 (중단하지 않음) |

**로그에 캐시 사용 여부를 반드시 표시합니다.** 안 그러면 코드를 고쳤는데 결과가 그대로여서
"왜 안 바뀌지"로 시간을 버립니다.

```
[2/6] 캐시 확인 → 기존 결과 발견, API 호출을 건너뜁니다 (results/trip_2026-09-20_raw.json)
```

> **왜 유효 기간을 두지 않는가** — 이 프로그램의 1차 추천은 "해당 시기의 일반적인 정보"이지
> 실시간 데이터가 아닙니다. 하루 지났다고 무효가 되는 성질이 아니므로 만료를 두면
> 코드만 복잡해지고 얻는 게 없습니다.

---

## 10. 화면 설계 — 진행 로그

과제 요건: "진행 로그 + 결과 저장 경로 안내".

```
============================================================
  🧳 여행 추천 리포트 생성기
  대상 날짜: 2026-09-20
============================================================
[1/6] API 키 확인 ......... 완료 (Gemini, Kakao)
[2/6] 캐시 확인 ........... 없음, 새로 생성합니다
[3/6] 여행지 추천 요청 .... 완료 → 강릉
[4/6] 맛집 검색 ........... 완료 (5곳)
[5/6] 원본 데이터 저장 .... 완료
[6/6] 리포트 생성 ......... 완료
------------------------------------------------------------
✅ 완료했습니다.
   원본 데이터 : results/trip_2026-09-20_raw.json
   최종 리포트 : results/trip_2026-09-20_report.md
============================================================
```

**부분 실패했을 때** (맛집 검색만 실패):

```
[4/6] 맛집 검색 ........... ⚠ 실패 (401 인증 오류)
      → 맛집은 "데이터 없음"으로 리포트에 표기됩니다.
      → 점검: KAKAO_REST_API_KEY 값, 헤더의 'KakaoAK ' 접두어, 앱 플랫폼 설정
...
------------------------------------------------------------
⚠️ 1건의 오류가 있었지만 리포트는 생성되었습니다.
```

> **실패해도 마지막 줄은 항상 저장 경로입니다.** 사용자가 "그래서 결과가 어디 있지?"를
> 스크롤해서 찾게 만들면 안 됩니다.

---

## 11. 리포트 Markdown 구조

```markdown
# 🧳 강릉 여행 리포트 (2026-09-20)

## 📍 추천 지역
**강릉** — 추천 이유 요약

## 🌤️ 날씨
9월 하순의 강릉은 ...

## 🎪 행사 · 축제
- 강릉커피축제
- 정동진 해맞이 축제

## 🍽️ 맛집
| 이름 | 카테고리 | 주소 | 링크 |
|------|----------|------|------|
| 초당순두부 | 한식 > 두부요리 | 강원특별자치도 강릉시 ... | [지도](...) |

## 🗓️ 1일 일정 제안
- **오전** — ...
- **오후** — ...
- **저녁** — ...

## ⚠️ 오류 요약
- [kakao_search] 401 인증 오류로 맛집을 가져오지 못했습니다.
```

| 절 | 조건 |
|----|------|
| 맛집 | 0건이면 표 대신 `데이터 없음`을 출력 |
| 오류 요약 | `errors`가 **비어 있으면 절 자체를 생략** |

---

## 12. 7일 실행 계획

> 시작일은 오늘(2026-08-18 화)로 잡았습니다. 제출 기한이 다르면 이 표를 조정하십시오.

### Day 1 — 8/18(화) 환경 세팅 & 키 발급

- [x] `git init`, `.gitignore` 작성 (**`.env` 반드시 포함**)
- [x] Google AI Studio에서 **Gemini API 키 발급**
- [x] Kakao Developers에서 앱 생성 → **REST API 키 발급** (플랫폼 설정 확인)
- [x] `.env` 작성 + `.env.example` 작성
- [ ] `requirements.txt` — `google-genai`, `requests`, `python-dotenv`
- [ ] `pip install -r requirements.txt`
- [ ] `load_api_keys()` 구현 → **키를 지우고 실행해 종료 안내가 나오는지 확인** (E2)

> ✅ **두 API 모두 실호출 확인 완료 (2026-08-18)** — Gemini `models.list` 200,
> Kakao 키워드 검색 200. 키 발급·인증 관련 리스크는 해소됐습니다.

### Day 2 — 8/19(수) CLI + 1차 추천

- [ ] `argparse` 구성, `valid_date()` 검증 (§4.2)
- [ ] 잘못된 날짜 5종 테스트 (T1~T5)
- [x] ~~모델명 확인~~ → `gemini-3.6-flash` 확정 (§5.1)
- [ ] Gemini **SDK 설치 방식** 확인 — `pip install google-genai` 후 import 경로 확인
- [ ] `get_recommendation()` 1차 버전 — 호출 + `json.loads`
- [ ] 응답을 그대로 출력해 형식 확인

### Day 3 — 8/20(목) 검증 & 재시도

- [ ] `validate_recommendation()` — 키·타입 검증 (§6.1)
- [ ] E3 재시도 로직 — **최대 1회** (무한 재시도 금지)
- [ ] 재시도 경로 검증: 프롬프트를 일부러 망가뜨려 재시도가 도는지 확인
- [ ] `errors` 리스트 구조 확정 및 기록 시작

### Day 4 — 8/21(금) 맛집 검색 ⭐ 가장 실패가 많은 날

- [ ] `search_restaurants()` — GET + `Authorization` 헤더 + `timeout`
- [ ] `normalize_place()` — **`x`=lng, `y`=lat, `float()` 변환** 주의 (§5.2)
- [ ] E5~E9 예외 분기 구현
- [ ] **일부러 키를 틀리게 넣어 401 경로 확인** (T7)
- [ ] **존재하지 않는 도시명으로 0건 경로 확인** (T8)

### Day 5 — 8/22(토) 리포트 & 저장

- [ ] `ensure_results_dir()`, `save_raw()`, `save_report()`
- [ ] `generate_report()` + `build_fallback_report()` (E10)
- [ ] 진행 로그 출력 정리 (§10)
- [ ] `ensure_ascii=False`, `indent=2`로 JSON 저장 (한글이 `\uXXXX`로 깨지지 않게)

### Day 6 — 8/23(일) 캐싱 & 문서화

- [ ] 캐싱 구현 (§9) — 캐시 사용 여부를 로그에 표시
- [ ] `README.md` 작성 — 개요 / 실행 방법 / **키 설정 방법** / 결과물 확인 방법 / 키 주의사항
- [ ] 스크린샷 촬영 (§13.2)
- [ ] **§8.4 유출 점검 항목 전체 확인**

### Day 7 — 8/24(월) 검증 & 마무리

- [ ] §13.1 테스트 시나리오 T1~T12 전부 실행
- [ ] `results/` 산출물 최종 확인
- [ ] 커밋 정리 및 push
- [ ] 제출물 체크리스트(§14) 확인

---

## 13. 검증

### 13.1 수동 테스트 시나리오

> ✅ **T1~T12 전부 통과 (2026-08-18 실행 확인)**

| ID | 시나리오 | 기대 결과 | 결과 |
|----|----------|-----------|:----:|
| T1 | `-date` 없이 실행 | 사용법 출력 + 종료 | ✅ |
| T2 | `-date "2026-9-20"` | 형식 오류 안내 + 사용법 + 종료 | ✅ |
| T3 | `-date "2026/09/20"` | 형식 오류 안내 + 종료 | ✅ |
| T4 | `-date "2026-13-01"` | 형식 오류 안내 + 종료 | ✅ |
| T5 | `-date "2026-09-20"` (정상) | 전 과정 수행 + 두 파일 생성 | ✅ |
| T6 | `GEMINI_API_KEY`를 지우고 실행 | 설정 방법 안내 + 즉시 종료 (E2) | ✅ |
| T7 | `KAKAO_REST_API_KEY`를 틀린 값으로 설정 | 401 안내 + **맛집 "데이터 없음"으로 리포트 생성 완료** (E6) | ✅ |
| T8 | 검색 0건이 나오는 도시로 강제 실행 | 중단 없이 "데이터 없음" 리포트 (E5) | ✅ |
| T9 | 네트워크를 끊고 실행 | 타임아웃 처리, 프로그램이 멈추지 않음 (E8) | ✅ |
| T10 | 같은 `-date`로 재실행 | **캐시 사용 로그** 출력, API 미호출 (§9) | ✅ |
| T11 | `results/*_raw.json`을 지우고 재실행 | 정상 경로로 재수행 | ✅ |
| T12 | 생성된 JSON에 `errors` 키 존재 확인 | 성공 시에도 `"errors": []`로 존재 | ✅ |

> **T7이 이 과제에서 가장 중요한 테스트입니다.** 요구사항 6의 "지도 API 실패 시에도 리포트
> 생성은 계속"을 직접 증명합니다. 스크린샷으로 남기십시오.

### 13.2 스크린샷 계획

| 파일명 | 내용 |
|--------|------|
| `01_env.png` | Python 버전 + 패키지 설치 결과 |
| `02_help.png` | 날짜 형식 오류 시 사용법 출력 (T2) |
| `03_run_success.png` | 정상 실행 전체 로그 (T5) |
| `04_results_dir.png` | `results/` 폴더에 생성된 두 파일 |
| `05_report.png` | 최종 리포트 Markdown 렌더링 화면 |
| `06_error_kakao.png` | **맛집 실패 후에도 리포트가 생성된 로그** (T7) |
| `07_no_key.png` | 키 미설정 시 안내 (T6) |
| `08_cache.png` | 캐시 사용 로그 (T10) |

> ⚠️ **촬영 전에 터미널 스크롤에 `.env` 내용이나 `export`/`$env:` 명령이
> 남아 있지 않은지 확인하십시오.** 새 터미널을 열고 촬영하는 것이 안전합니다.

---

## 14. 제출물 체크리스트

- [ ] `trip_planner.py` — `argparse`, `-date` 필수, 날짜 검증
- [ ] Gemini 연동 (1차 추천 JSON + 최종 리포트)
- [ ] Kakao Local 연동 (맛집 5곳)
- [ ] `results/` 원본 JSON — `recommendation` + `restaurants` + `errors` 포함
- [ ] `results/` 최종 리포트 `.md` — 6개 항목 전부 포함
- [ ] **맛집 0건/실패 시에도 리포트가 생성되는가** ← 요건 4·6의 핵심
- [ ] **LLM 파싱 재시도가 최대 1회인가** (무한 루프 없음)
- [ ] `try-except`로 네트워크·인증·파싱 오류 분리 처리
- [x] `.env` 사용 + `.gitignore`에 포함
- [ ] **코드·README·로그·결과 파일·스크린샷 어디에도 실제 키가 없는가** (§8.4)
- [ ] `README.md` — 개요 / 실행 방법 / 키 설정 / 결과 확인 / 키 주의사항
- [ ] (보너스) 캐싱 동작 확인

---

## 15. 커밋 메시지 컨벤션

A1-1과 동일하게 유지합니다.

| 접두어 | 용도 |
|--------|------|
| `feat:` | 새 기능 추가 |
| `fix:` | 버그 수정 |
| `docs:` | 문서 수정 |
| `refactor:` | 리팩토링 (동작 변화 없음) |
| `style:` | 출력 포맷 등 |
| `chore:` | 설정/기타 |
| `merge:` | 브랜치 병합 |

**예시**: `feat: Kakao Local 맛집 검색 및 응답 정규화 구현`

> 이번 과제 명세에는 커밋 개수·Git 명령어 요건이 **없습니다.** 위 컨벤션과 브랜치
> 병합 시 `--no-ff` 규칙은 A1-1에서 이어지는 **작업 관례**이지 채점 요건이 아닙니다.

---

## 16. 과제 목표 대응 — "설명할 수 있어야 한다"

제출 후 구두로 설명할 수 있어야 하는 4가지입니다. 각 항목이 코드 어디에 드러나는지 적었습니다.

| 목표 | 근거 위치 | 한 줄 답안 |
|------|-----------|-----------|
| REST API 요청/응답 구조와 GET/POST 차이 | §5.0, §5.2 | GET은 조회이고 파라미터가 URL에 붙으며, POST는 데이터를 본문에 담아 보낸다. 맛집 검색은 GET, LLM 생성은 POST다. |
| LLM 출력의 구조화(JSON)와 다음 단계 연결 | §5.1 → §5.2 | `recommended_city` 하나를 뽑아내려고 JSON을 강제한다. 자유 문장이면 도시 이름을 코드로 꺼낼 수 없어 다음 API에 넣지 못한다. |
| 대표 오류와 대응 원칙 | §7 | 인증(401/403)·쿼터(429)·네트워크(타임아웃)·파싱(JSON) 네 가지. **이후 단계의 입력이 사라지면 중단하고, 결과 일부만 비면 계속 진행한다.** |
| `.env`/환경변수로 키를 관리하는 이유 | §8.1 | 공유 시 유출 방지, 키 교체 시 코드 수정 불필요, 과금 사고 예방. 한 번 커밋된 키는 이력에 남으므로 재발급이 유일한 해결책이다. |

---

## 17. 리스크 & 대응

| 리스크 | 대응 |
|--------|------|
| ~~Gemini 모델명이 문서와 다름~~ | ✅ **해소** — `gemini-3.6-flash`로 확정. `models.list`에 있어도 404가 날 수 있음 (§5.1) |
| ~~Gemini SDK 패키지명이 문서와 다름~~ | ✅ **해소** — `google-genai 2.18.1`, `from google import genai` 동작 확인 |
| **Gemini 무료 한도 하루 20회 소진** | 실행 1회당 Gemini 2회 호출 → 하루 약 10회. **캐싱(§9) 필수.** 막히면 다른 flash 모델로 교체 (한도는 모델별) |
| ~~LLM이 JSON을 코드블록으로 감싸 반환~~ | ✅ **해소** — 예시 블록 제거 + `response_schema` 적용 후 실패 0건 (§5.1) |
| ~~Kakao 앱 플랫폼 미등록으로 403~~ | ✅ **해소** — 실제 호출 200 확인 (2026-08-18) |
| ~~Gemini 503 과부하~~ | ✅ **대응** — 3회 백오프 재시도 (E4-a) |
| ~~API 키 발급 지연~~ | ✅ **해소** — Gemini·Kakao 두 키 모두 발급 및 인증 확인 완료 |
| **`strptime`이 `2026-9-20`을 통과시킴** | ✅ **해소** — `isoformat()` 왕복 비교 추가 (§4.2) |
| **argparse 오류가 콘솔에서 깨짐** | ✅ **해소** — `sys.stderr`도 UTF-8로 고정 (§4.2) |
| **`x`/`y`를 위경도로 뒤집어 저장** | §5.2 표대로 `x`=lng, `y`=lat (실측 검증됨). 문자열로 오므로 `float()` 변환 필수 |
| 맛집 0건인데 LLM이 가게를 지어냄 | 리포트 프롬프트에 "지어내지 말 것" 명시 (§5.3), 원본 JSON과 대조 검증 |
| **파싱 재시도가 무한 루프** | 재시도 카운터를 명시적으로 1로 제한. 과제 제약에 "무한 재시도 금지" 명시됨 |
| 한글이 JSON에 `\uXXXX`로 저장됨 | `json.dump(..., ensure_ascii=False, indent=2)` |
| 콘솔 이모지 `UnicodeEncodeError` | A1-1과 동일하게 `sys.stdout.reconfigure(encoding="utf-8")` |
| **`.env`를 실수로 커밋** | Day 1에 `.gitignore` 먼저 작성. 커밋됐다면 파일 수정이 아니라 **키 재발급** |
| 스크린샷에 키가 찍힘 | 새 터미널에서 촬영 (§13.2) |
| `results/` 커밋 여부 | 결과물 제출이 요건이므로 **커밋함**. 단 키가 섞이지 않았는지 §6.3 확인 후 |

---

## 부록 A. 프로그램 뼈대 (Day 2 시작점)

```python
"""여행 추천 리포트 생성기 (Trip Planner)
날짜를 입력받아 LLM 추천 → 맛집 검색 → 여행 리포트를 생성하는 CLI 프로그램
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RESULTS_DIR = "results"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
GEMINI_MODEL = "gemini-3.6-flash"   # 정확한 ID는 models.list로 확인 (§5.1)
RESTAURANT_COUNT = 5
REQUEST_TIMEOUT = 10


def valid_date(s):
    """argparse type= 검증 함수. 형식이 틀리면 argparse가 사용법을 출력하고 종료한다."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"날짜 형식이 올바르지 않습니다: {s!r} (예: 2026-09-20)")


def parse_args():
    parser = argparse.ArgumentParser(
        description="날짜를 받아 여행지를 추천하고 맛집을 검색해 리포트를 생성합니다.")
    parser.add_argument("-date", "--date", required=True, type=valid_date,
                        help="여행 날짜 (YYYY-MM-DD)")
    return parser.parse_args()


def main():
    args = parse_args()
    date_str = args.date.isoformat()
    errors = []            # 실패를 모아두는 리스트 — 모든 단계에 인자로 전달
    # ...


if __name__ == "__main__":
    main()
```

---

## 부록 B. 설정 파일

**`.gitignore`**

```
.env
__pycache__/
*.py[cod]
venv/
.venv/
.vscode/
.claude/
Thumbs.db
desktop.ini
```

**`.env.example`** (값 없이 키 이름만 — 커밋해도 안전)

```
GEMINI_API_KEY=
KAKAO_REST_API_KEY=
```

**`requirements.txt`**

```
google-genai
requests
python-dotenv
```

---

*2026년 AI활용학습 A1-2 과제 계획서 — 작성자: 김재민*
