# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

**Trip Planner (여행 추천 리포트 생성기)** — 2026년 AI활용학습 A1-2 과제 (작성자: 김재민).

`-date "YYYY-MM-DD"`를 받아 **Gemini로 여행지를 추천받고 → 그 도시의 맛집을 Kakao Local로
검색해 → 최종 여행 리포트(Markdown)를 생성하는** Python CLI 프로그램입니다.

**상세 명세는 [trip_planner_PRD.md](trip_planner_PRD.md)에 있습니다.** 스키마·예외 처리 정책·
프롬프트 설계·테스트 시나리오가 전부 거기 있으므로, 작업 전에 해당 절을 먼저 읽으십시오.

## 확정된 결정 (되돌리지 말 것)

| 항목 | 확정 | PRD |
|------|------|-----|
| LLM | Google Gemini **`gemini-3.6-flash`** (`google-genai` 2.18.1) | §5.1 |
| 지도/장소 | **어댑터 구조** — 기본 `kakao`, `PLACE_PROVIDER`로 교체 (`naver` 구현됨) | §5.2 |
| 보너스 | **캐싱만** 채택 — `recommended_city`는 **단수 문자열** | §0, §9 |
| 파일 구성 | `trip_planner.py` 단일 파일 | §0 |

## 이 과제의 핵심 규칙

- **부분 실패해도 리포트는 반드시 생성한다.** 맛집 검색이 실패하거나 0건이어도 중단하지 않고
  "데이터 없음"으로 표기한 뒤 리포트까지 진행합니다. 반대로 1차 추천 실패는 후속 단계의
  입력(도시명)이 사라지므로 종료합니다. Fatal / Degraded 구분은 PRD §7 표를 따르십시오.
- **LLM JSON 재시도는 최대 1회.** 과제 제약에 무한 재시도 금지가 명시돼 있습니다.
- **파싱 성공 ≠ 검증 성공.** `json.loads`가 통과해도 키·타입을 따로 검증하고,
  실패하면 파싱 실패와 동일하게 1회 재시도로 처리합니다. (PRD §6.1)
- **Kakao 응답의 `x`는 경도(lng), `y`는 위도(lat)이고 둘 다 문자열입니다.** 뒤집거나
  `float()` 변환을 빠뜨리기 쉬운 지점입니다. (PRD §5.2)
- **결과 파일명은 실행 날짜가 아니라 `-date` 값으로 붙입니다.** 캐시가 이 파일명을
  키로 쓰기 때문입니다. 실행 시각은 JSON 안의 `generated_at`에 남깁니다. (PRD §6.4)
- 모든 API 호출 함수는 `errors` 리스트를 인자로 받아 실패를 기록합니다.
  리스트가 가변이라 `append`하면 호출한 쪽에 반영되므로 `return`이 필요 없습니다.

## 보안 (필수 요건)

- API 키를 코드·README·로그·결과 파일·스크린샷 어디에도 넣지 않습니다. `.env` + `python-dotenv`.
- **진행 로그에 요청 헤더나 전체 URL을 출력하지 마십시오.** 가장 흔한 유출 경로입니다.
- `errors[].message`에 예외 원문을 통째로 넣지 마십시오 — 요청 정보가 딸려와 커밋됩니다.
- 키가 커밋되면 파일 수정으로 해결되지 않습니다. **재발급이 유일한 조치입니다.**
- 점검 항목 전체는 PRD §8.4.

## 실행

```bash
pip install -r requirements.txt
```

```bash
python trip_planner.py -date "2026-09-20"
```

산출물은 `results/trip_{-date값}_raw.json` 과 `results/trip_{-date값}_report.md` 입니다.
파일명은 실행 날짜가 아니라 `-date` 값으로 붙습니다 (캐시가 이 이름을 키로 씁니다).

## 작업 관례 (A1-1에서 이어짐)

이번 과제 명세에는 Git 요건이 **없습니다.** 아래는 채점 요건이 아니라 관례입니다.

- 모든 산출물(README, 커밋 메시지, 주석, docstring)은 **한국어**로 작성합니다.
- 커밋 메시지는 `type: 한국어 설명` (`feat`/`fix`/`docs`/`chore`/`refactor`/`style`/`merge`).
  기능 단위로 커밋합니다.
- 브랜치 병합은 `--no-ff` — fast-forward로 붙으면 브랜치 기록이 그래프에서 사라집니다.
- README는 기능 표 + 실행 화면 스크린샷 + **"설계 결정 (왜 이렇게 만들었는가)"** 절로 구성합니다.
  대안을 표로 나열하고 각각의 문제점을 적은 뒤 채택안을 표시하는 형식입니다.
  기준선은 `../AI활용학습_A1_1/README.md`입니다.
- 스크린샷은 `docs/screenshots/NN_이름.png`로 번호를 붙입니다. (계획: PRD §13.2)
- 콘솔 이모지 출력을 위해 `sys.stdout.reconfigure(encoding="utf-8")`를 파일 상단에 둡니다.
  없으면 cp949 터미널에서 `UnicodeEncodeError`로 중단됩니다.
- A1-1과 달리 **외부 라이브러리를 사용합니다** (`google-genai`, `requests`, `python-dotenv`).

## 구조 (평가 피드백 반영)

- **장소 검색은 어댑터로 분리되어 있다.** 제공자별로 다른 것은 `build_request` /
  `extract_documents` / `normalize` / `hint` / `credentials` 다섯 훅뿐이고, 타임아웃·HTTP 오류
  분기·0건 처리·로그는 `search_restaurants()`에 공통으로 있다. **새 제공자를 붙일 때
  `search_restaurants()`를 고치지 말 것.** `PlaceProvider`를 상속하고 `PLACE_PROVIDERS`에 등록한다.
- **`NaverPlaceProvider`는 실호출 검증이 안 됐다.** 자격증명이 없어 합성 응답으로 정규화만
  확인했다. 좌표(`mapx`/`mapy`) 스케일은 계정·버전에 따라 다를 수 있으니 첫 호출에서 확인할 것.
- **`recommended_city`는 검색에 쓰기 전에 `normalize_city()`를 거친다.** 괄호 제거 →
  공백 제거 → 표준명 매핑 → 접미사 제거 → 자모 유사도 오타 보정 순서다.
  **순서를 바꾸지 말 것** — 표준 도시명 확인이 접미사 제거보다 앞에 있어야 `대구`가 `대`가 되지 않는다.

## 측정으로 확정된 것 (되돌리지 말 것)

아래는 전부 실제로 호출해 보고 확인한 사실입니다. "개선"이라며 되돌리지 마십시오.

- **1차 추천 프롬프트에 예시 JSON 블록을 넣지 않는다.** 넣으면 모델이 예시를 먼저 출력하고
  진짜 답을 이어 붙여 JSON 객체가 두 개가 됩니다. 실측 실패율: 예시 포함 5건 중 4건 실패,
  예시 없이 산문 지시 10건 중 0건 실패. 구조는 `RECOMMEND_SCHEMA`가 강제합니다.
- **`response_mime_type="application/json"`은 "JSON 하나만"을 보장하지 않는다.**
- **날짜 검증에 `isoformat()` 왕복 비교가 필요하다.** `strptime`의 `%m`/`%d`는 0을 뺀
  한 자리 표기를 허용해서 `2026-9-20`이 그냥 통과합니다.
- **`sys.stderr`도 UTF-8로 고정해야 한다.** argparse 오류는 stderr로 나가므로,
  stdout만 재설정하면 cp949 터미널에서 날짜 오류 안내가 깨집니다.
- **Kakao `x`=경도, `y`=위도이고 둘 다 문자열이다.** 안동 응답 `x=128.72 / y=36.56`으로 확인.
- **`models.list`에 있어도 호출 가능한 모델이 아니다.** `gemini-2.5-flash`는 목록에 나오지만
  호출하면 `404 — no longer available to new users`가 납니다.
- **Gemini 무료 한도는 모델별 하루 20회.** 전체 실행 1회에 2번 호출하므로 하루 약 10회분입니다.
  막히면 다른 flash 계열로 모델만 바꾸면 됩니다 (한도가 모델별로 따로 잡힘).

## 테스트

테스트 프레임워크는 없습니다. PRD §13.1의 **T1~T12를 직접 실행**해 확인하며, 전부 통과한
상태입니다. 코드를 고쳤으면 최소한 T5(정상)와 T7(Kakao 키를 틀리게 넣고도 리포트 생성)은
다시 돌리십시오. **T7이 과제의 핵심 요건을 증명하는 테스트입니다.**

API 호출 없이 확인 가능한 것: T1~T4(날짜 검증), T6(키 미설정), T8~T9(모듈 직접 호출), T11(캐시).
