# 시스템 구조 설계 이유 및 구현 분석

이 문서는 `docs/system-architecture.drawio`를 기준으로 시스템을 처음 접속하는 순간부터 저장된 보고서와 분석 화면까지의 흐름대로 설명합니다.
코드리뷰에서 바로 설명할 수 있도록 "왜 이 구조인지", "어디에 구현돼 있는지", "다른 선택지는 왜 쓰지 않았는지"를 함께 적었습니다.

## 1. 그림을 읽는 순서

drawio는 왼쪽에서 오른쪽으로, 그리고 위에서 아래로 읽으면 됩니다.

1. 사용자가 브라우저로 서비스에 접속합니다.
2. 로그인에 성공하면 지자체 관리 화면이 기본 진입점이 됩니다.
3. 공통 사이드바는 로그인 후 항상 표시되고, 그 안에서 다른 화면으로 이동합니다.
4. 백엔드는 상태 스냅샷을 유지하고, 프론트는 API로 그 스냅샷을 읽습니다.
5. 장치/ROS 입력은 카메라 프레임과 상태 이벤트를 백엔드에 넣습니다.
6. SQLite에는 저장이 필요한 보고서만 남깁니다.

이 구조의 핵심은 `실시간 상태`와 `저장 데이터`를 분리하는 것입니다.

| 영역 | 무엇을 담는가 | 저장 위치 |
| --- | --- | --- |
| 실시간 상태 | 웹캠 상태, AMR 상태, 현재 보고서 진행 상황 | 백엔드 메모리 |
| 스트리밍 데이터 | 웹캠 JPEG, AMR CompressedImage 기반 프레임 | 백엔드 메모리 버퍼 |
| 영속 데이터 | 저장된 보고서, 제목 수정 이력, 생성/수정 시각 | SQLite |

## 2. 접속과 로그인

첫 진입은 로그인 화면입니다. 로그인 성공 후에는 지자체 관리 화면으로 이동합니다.

```text
브라우저 접속
  ↓
로그인 화면
  ↓
POST /api/login
  ↓
인증 성공
  ↓
지자체 관리 화면 기본 진입
```

이 흐름을 둔 이유는, 실제 관제 서비스에서도 사용자가 먼저 인증을 거친 뒤 내부 화면으로 들어가야 하기 때문입니다.
현재는 운영 인증이 아니라 시연용 `admin / 1234`를 사용하지만, 화면 구조와 API 경계는 나중에 JWT나 세션 인증으로 바꿔도 유지되게 설계했습니다.

## 3. 지자체 관리 화면과 공통 사이드바

지자체 관리 화면은 메인 대시보드 역할을 합니다.
여기서 중요한 점은, 이 화면이 "다른 화면으로만 이동하는 중간 화면"이 아니라는 것입니다.
실제로는 로그인 후 기본 진입 페이지이고, 왼쪽 공통 사이드바로 카메라 관제, 통합 보고서, 저장된 보고서, 보고서 분석으로 계속 이동할 수 있습니다.

이 화면이 먼저 보이도록 한 이유는 다음과 같습니다.

| 이유 | 설명 |
| --- | --- |
| 운영 시작점 | 관제자는 로그인 후 가장 먼저 현재 상태를 봐야 합니다. |
| 상태 요약 | 웹캠 감지 여부와 AMR 상태를 한 번에 봐야 합니다. |
| 화면 이동 허브 | 사이드바가 공통이므로 다른 기능으로 이동하기 쉽습니다. |

지자체 관리 화면은 코드상으로도 공통 상태를 보여주는 곳입니다.
실시간 상태는 `GET /api/status`, 보고서 상태는 `GET /api/report`로 읽습니다.

## 4. 왜 API를 쓰는가

API를 쓴 이유는 브라우저가 ROS 토픽, USB 장치, SQLite를 직접 다루지 않게 하기 위해서입니다.
프론트는 HTTP만 알면 되고, 백엔드는 장치와 데이터 저장 방식을 숨깁니다.

API를 나누는 기준은 "데이터의 성격"입니다.

| API 묶음 | 역할 |
| --- | --- |
| 로그인 API | 브라우저가 접근 권한을 얻는 진입점 |
| 상태 조회 API | 현재 관제 상태를 스냅샷으로 읽음 |
| 카메라 스트림 API | 웹캠과 AMR 이미지를 브라우저용 스트림으로 전달 |
| 보고서 API | 저장, 조회, 수정, 복원 |

이렇게 해두면 ROS 토픽 이름이 바뀌거나 카메라 장치가 바뀌어도 프론트 코드는 거의 건드리지 않고 백엔드만 바꾸면 됩니다.

## 5. 왜 FastAPI인가

백엔드는 Python 기반 FastAPI로 구현했습니다. 이유는 단순합니다.

| 이유 | 설명 |
| --- | --- |
| Python 생태계와 잘 맞음 | ROS2, OpenCV, JSON, SQLite가 모두 Python과 맞습니다. |
| 라우트 정의가 간단함 | `@app.get`, `@app.post`로 API를 빠르게 구성할 수 있습니다. |
| 요청 검증이 쉬움 | Pydantic 모델로 로그인/보고서 저장 요청을 명확히 표현할 수 있습니다. |
| 문서화가 쉽음 | API 계약을 코드와 함께 설명하기 좋습니다. |
| 작은 서비스에 적합함 | 현재 규모에서는 Django처럼 큰 구조가 필요하지 않습니다. |

즉, FastAPI는 이 프로젝트의 "장치/상태/보고서"를 빠르게 연결하기에 맞는 선택입니다.

## 6. 왜 React + Vite인가

프론트엔드는 React + Vite로 구성했습니다.

| 이유 | 설명 |
| --- | --- |
| 화면이 여러 개임 | 로그인, 대시보드, 카메라, 보고서, 분석, 저장 보고서가 분리돼 있습니다. |
| 공통 레이아웃이 있음 | 사이드바와 공통 상태 카드가 모든 내부 화면에 붙습니다. |
| 상태 변화가 잦음 | 상태 스냅샷이 자주 바뀌므로 컴포넌트 재렌더링이 자연스럽습니다. |
| 개발 속도가 빠름 | Vite는 dev server가 가볍고 반응이 빠릅니다. |

React 쪽에서는 API 호출을 화면 코드와 분리해 두었습니다.
`frontend/src/api/client.js`가 fetch 공통 로직을 담당하고, `frontend/src/api/statusApi.js`가 의미 있는 서비스 함수로 감싸고 있습니다.
이 구조는 화면 코드가 백엔드 URL 문자열에 직접 묶이지 않게 하기 위한 것입니다.

## 7. 상태 스냅샷이란 무엇인가

여기서 스냅샷은 이미지 스냅샷이 아니라 "현재 시점의 관제 상태 묶음"입니다.

백엔드는 다음 세 덩어리를 메모리에 유지합니다.

```text
state["webcam"]
state["amr"]
state["report"]
```

이걸 하나의 스냅샷으로 묶는 이유는, 화면이 같은 시점의 상태를 함께 읽어야 하기 때문입니다.
웹캠만 최신이고 AMR 상태는 이전 값인 식으로 화면이 갈라지면 운영자가 잘못 읽을 수 있습니다.

스냅샷은 다음 장점이 있습니다.

1. 화면이 일관됩니다.
2. 보고서 저장 시점이 명확해집니다.
3. REST API 하나로 현재 상태를 읽을 수 있습니다.
4. ROS 이벤트와 UI를 연결하기 쉽습니다.

`GET /api/status`는 이 스냅샷 전체를 반환하고, `GET /api/report`는 그중 보고서 부분만 따로 반환합니다.

## 8. 카메라 흐름

카메라는 두 갈래입니다.

### 8.1 USB 웹캠

웹캠은 OpenCV가 `/dev/video*` 장치를 직접 읽습니다.
캡처 스레드가 프레임을 주기적으로 읽고 JPEG로 인코딩한 뒤, 최신 프레임을 메모리 버퍼에 넣습니다.

프레임 주기는 `FARMGUARD_WEBCAM_FPS`로 제어하고, 기본값은 15fps입니다.
즉, 대략 0.066초 간격으로 프레임을 읽도록 맞춰집니다.

흐름은 다음과 같습니다.

```text
USB 웹캠
  ↓ OpenCV 캡처 스레드
프레임 읽기
  ↓ cv2.imencode(".jpg")
JPEG 바이트 생성
  ↓ 메모리 버퍼 저장
  ↓ /api/cameras/webcam/stream
브라우저 MJPEG 표시
```

이 구조를 둔 이유는 브라우저가 `/dev/video*`를 직접 읽지 못하기 때문입니다.
브라우저는 HTTP 스트림만 잘 받으면 되도록 백엔드가 MJPEG로 중계합니다.

### 8.2 AMR 카메라

AMR 카메라는 ROS2 토픽 `sensor_msgs/msg/CompressedImage`를 그대로 받습니다.
백엔드가 ROS bridge 역할을 하며, 카메라 토픽에서 받은 압축 이미지를 그대로 프레임 버퍼에 저장하고 MJPEG로 내보냅니다.

흐름은 다음과 같습니다.

```text
ROS2 CompressedImage topic
  ↓ rclpy subscription
프레임 바이트 수신
  ↓ 메모리 버퍼 저장
  ↓ /api/cameras/amr1/stream, /api/cameras/amr2/stream
브라우저 MJPEG 표시
```

왜 이렇게 했는지 보면, 프론트는 카메라의 내부 형식을 몰라도 됩니다.
웹캠이든 ROS 토픽이든 프론트는 같은 `streamUrl`만 바라보면 됩니다.

### 8.3 왜 MJPEG인가

MJPEG를 쓴 이유는 브라우저 호환성과 구현 단순성입니다.

| 방식 | 장점 | 이 프로젝트에서의 판단 |
| --- | --- | --- |
| MJPEG | `<img>`로 바로 표시 가능, 구현 단순 | 현재 구조에 가장 잘 맞음 |
| WebRTC | 지연이 낮고 상호작용이 좋음 | 나중에 필요하면 검토 가능 |
| RTSP 직접 노출 | 장치에 가깝지만 브라우저 친화적이지 않음 | 프론트가 복잡해짐 |

지금은 운영 초기가 아니라 관제 UI 검증 단계이므로 MJPEG가 적절합니다.

### 8.4 왜 async가 아닌가

카메라 수집은 `async def`가 아니라 백그라운드 스레드와 condition 변수로 처리합니다.
이유는 간단합니다.

1. OpenCV 캡처와 ROS spin은 원래 블로킹 성격이 강합니다.
2. HTTP 응답은 이미 준비된 최신 프레임만 읽으면 됩니다.
3. `StreamingResponse`는 generator로 충분합니다.

즉, 비동기 웹서버 기능보다 "백그라운드 수집 + 스트리밍 응답"이 더 단순하고 안정적입니다.

## 9. 통합 보고서 흐름

통합 보고서는 6단계 이벤트를 추적합니다.

1. `WEBCAM_DETECTED`
2. `AMR_UNDOCKED`
3. `PATROL_STARTED`
4. `AMR_OBJECT_DETECTED`
5. `DETERRENCE_DONE`
6. `RETURN_DONE`

코드에서는 `apply_scenario_event()`가 이 이벤트들을 받아서 각 단계의 타임스탬프를 한 번만 기록합니다.
이벤트별로 `scenario_status`도 갱신합니다.

```text
이벤트 수신
  ↓
apply_scenario_event()
  ↓
state["report"]의 *_at 필드 갱신
  ↓
현재 상태와 진행 상태 갱신
```

`RETURN_DONE`이 들어오면 보고서가 종료된 것으로 보고 자동 저장이 걸립니다.
중복 저장을 막기 위해 마지막 저장 시각을 추적합니다.

통합 보고서 화면은 `GET /api/report`를 주기적으로 읽어서 현재 보고서를 보여줍니다.
그래서 사용자는 이벤트가 들어오는 즉시 타임라인 변화를 확인할 수 있습니다.

## 10. 저장된 보고서 흐름

저장된 보고서는 통합 보고서의 스냅샷을 SQLite에 남긴 결과입니다.

```text
현재 보고서
  ↓ POST /api/reports
normalize_report()
  ↓
saved_reports INSERT
  ↓
목록 화면 / 상세 화면에서 재조회
```

목록 화면에서는 `GET /api/reports`로 최신순 목록을 읽고, 상세 화면에서는 `GET /api/reports/{id}`로 단일 보고서를 다시 읽습니다.
이중 구조를 둔 이유는 목록과 상세의 책임이 다르기 때문입니다.

- 목록은 빠르게 스캔해야 합니다.
- 상세는 원본 보고서를 정확히 보여줘야 합니다.

제목 수정은 `PATCH /api/reports/{id}/title`로 처리하고, 복원은 `POST /api/reports/{id}/restore`로 처리합니다.
복원은 단순 조회가 아니라 live state를 저장 당시 상태로 되돌립니다.
이렇게 해야 보고서 화면과 다른 내부 화면이 같은 상태를 기준으로 움직입니다.

## 11. 보고서 분석 흐름

보고서 분석 화면은 저장된 보고서를 집계해서 보여줍니다.
여기서 중요한 건 단순 총합이 아니라 "점검 필요" 보고서를 따로 보는 것입니다.

점검 필요 항목은 다음과 같이 생각합니다.

| 항목 | 의미 |
| --- | --- |
| 단계 누락 | 6단계 중 어느 하나라도 비어 있음 |
| 미완료 | 마지막 복귀 완료가 없음 |
| 순서 오류 | 시간 순서가 자연스럽지 않음 |

이 분석은 저장된 `report_json`과 개별 시간 컬럼을 바탕으로 계산합니다.
즉, 저장된 원본 보고서를 읽어 후처리하는 구조입니다.

## 12. 데이터베이스 구조

SQLite의 기본 파일은 `backend/reports.sqlite3`입니다.
현재 테이블은 `saved_reports` 하나입니다.

```text
id
title
scenario_status
webcam_detected_at
amr_undock_at
amr_patrol_start_at
amr_object_detected_at
amr_deterrence_done_at
amr_return_done_at
report_json
created_at
updated_at
```

### 12.1 왜 단일 테이블인가

지금 저장 대상은 "완료된 통합 보고서" 하나뿐이기 때문입니다.
그래서 보고서를 잘게 나누기보다, 한 테이블에 원본과 요약값을 같이 두는 편이 단순합니다.

### 12.2 `report_json`은 어디에 쓰이나

`report_json`은 저장 당시 통합 보고서 원본을 그대로 보관합니다.
이 값이 있으면 미래에 필드가 늘어나도 원본 구조를 유지하기 쉽습니다.
반대로 개별 컬럼은 목록 검색, 정렬, 필터링을 쉽게 만들어 줍니다.

즉, `report_json`은 복원성과 호환성을 위한 원본이고, 개별 컬럼은 조회 편의성을 위한 인덱싱 재료입니다.

### 12.3 `created_at`과 `updated_at`의 차이

| 컬럼 | 의미 | 실제 사용 |
| --- | --- | --- |
| `created_at` | 보고서가 처음 저장된 시각 | 목록 정렬 기준 |
| `updated_at` | 보고서 제목이나 메타가 마지막으로 바뀐 시각 | 제목 수정 시 갱신 |

현재 구현에서는 저장할 때 둘 다 같은 값으로 시작합니다.
이후 제목 수정이 있으면 `updated_at`만 바뀝니다.

### 12.4 왜 JSON과 컬럼을 같이 저장하나

둘 중 하나만 쓰면 다른 쪽의 장점을 잃습니다.

| 방식 | 장점 | 단점 |
| --- | --- | --- |
| JSON만 저장 | 유연함 | 검색/정렬이 불편함 |
| 컬럼만 저장 | 검색이 쉬움 | 구조가 바뀔 때 취약함 |
| JSON + 컬럼 병행 | 둘의 장점을 함께 가짐 | 약간 중복됨 |

현재 프로젝트는 보고서 구조가 자주 바뀌지 않지만, 향후 필드 추가 가능성이 있으므로 병행 저장이 안전합니다.

## 13. ROS bridge는 어떻게 동작하나

이 프로젝트는 별도의 `rosbridge_server`를 쓰지 않고, 백엔드 내부에서 `rclpy`로 직접 구독합니다.

### 13.1 상태 토픽

상태 토픽은 `std_msgs/msg/String` 안에 JSON 문자열을 넣는 방식입니다.
예상 payload는 다음과 같습니다.

```text
data: '{"robot_id": "AMR1", "event": "PATROL_STARTED", "state": "순찰", "timestamp": "2026-07-09 18:20:10"}'
```

백엔드는 이 문자열을 파싱해서 다음 순서로 처리합니다.

1. `event`를 우선 확인합니다.
2. `event`가 없으면 `state`를 보조로 봅니다.
3. 이벤트 이름을 6단계 시나리오 이름으로 정규화합니다.
4. `state["amr"]`와 `state["report"]`를 같이 갱신합니다.

### 13.2 카메라 토픽

AMR 카메라는 다음 토픽을 받습니다.

```text
/robot8/oakd/rgb/image_raw/compressed
/robot11/oakd/rgb/image_raw/compressed
```

이 토픽들은 `CompressedImage` 형태이므로 백엔드는 받은 바이트를 그대로 프레임 버퍼에 넣고 스트림으로 중계합니다.

### 13.3 왜 ROS bridge를 직접 붙였나

이 방식의 장점은 단순성입니다.

| 장점 | 설명 |
| --- | --- |
| 프론트 단순화 | 프론트는 ROS를 몰라도 됩니다. |
| 상태 일관성 | 상태와 보고서를 같은 Python 프로세스에서 갱신합니다. |
| 배포 단순성 | 브리지 서버를 따로 띄우지 않아도 됩니다. |
| 디버깅 용이 | 백엔드 로그만 보면 카메라와 상태를 함께 추적할 수 있습니다. |

운영 규모가 커지면 별도 메시지 브로커나 서비스 분리를 고려할 수 있지만, 현재 단계에서는 직접 구독이 더 실용적입니다.

## 14. 코드 기준으로 봐야 할 파일

| 파일 | 역할 |
| --- | --- |
| `backend/main.py` | 상태 스냅샷, ROS bridge, 카메라 스트리밍, SQLite 저장, API 라우트 |
| `frontend/src/api/client.js` | 공통 HTTP 요청 래퍼 |
| `frontend/src/api/statusApi.js` | 상태/보고서/복원 API 함수 |
| `frontend/src/config/cameras.js` | 카메라 스트림 URL과 상태 URL 정의 |
| `docs/system-architecture.drawio` | 전체 흐름의 시각적 기준 |

## 15. 코드리뷰에서 실제로 물어볼 법한 질문

### 이미 질문했던 내용

| 질문 | 답변 핵심 |
| --- | --- |
| 왜 API를 쓰는가 | 브라우저와 장치/ROS/DB를 분리하려고 |
| 왜 FastAPI인가 | Python ROS2/OpenCV/SQLite와 잘 맞고 API 구현이 간단해서 |
| 왜 React인가 | 여러 화면과 공통 사이드바를 컴포넌트로 나누기 좋아서 |
| 스냅샷이 무엇인가 | 현재 시점의 `webcam`, `amr`, `report` 상태 묶음 |
| 왜 스냅샷으로 묶나 | 화면 일관성과 보고서 저장 시점을 맞추기 위해서 |
| 왜 `report_json`이 필요한가 | 원본 구조 보존과 미래 호환성 때문 |
| `created_at`과 `updated_at` 차이는 무엇인가 | 저장 시점과 마지막 수정 시점이 다르기 때문 |
| ROS 토픽은 어떻게 받나 | `rclpy`로 직접 구독하고 JSON 문자열을 파싱해서 |
| 카메라 API는 비동기인가 | `async def`보다 백그라운드 스레드 + `StreamingResponse`를 쓴다 |
| 카메라 스트리밍은 왜 MJPEG인가 | 브라우저 호환성과 구현 단순성 때문 |
| 프레임은 몇 초마다 읽나 | 기본 15fps라서 약 0.066초 간격으로 읽는다 |

### 추가로 물어볼 법한 내용

| 질문 | 답변 방향 |
| --- | --- |
| 왜 WebSocket이 아니라 polling인가 | 현재는 상태 변화 빈도가 낮고 구현이 단순해야 해서 |
| 왜 live state를 DB에 바로 저장하지 않는가 | 실시간 상태는 빠르게 바뀌고, 저장이 필요한 건 보고서이기 때문 |
| 왜 restore가 live state를 바꾸는가 | 시연과 보고서 재확인 흐름을 단순하게 만들기 위해서 |
| 왜 SQLite인가 | 단일 서버, 로컬 시연, 영속 저장에 충분해서 |
| 나중에 DB를 바꾸기 쉬운가 | 저장 API와 조회 API를 분리해 두어서 비교적 쉽다 |
| 토픽 이름이 바뀌면 어떻게 하나 | 환경변수 `FARMGUARD_*_TOPIC`만 바꾸면 된다 |
| 카메라 장치가 바뀌면 어떻게 하나 | `FARMGUARD_WEBCAM_DEVICE`로 바꾸면 된다 |
| 실시간 상태와 저장 보고서가 왜 같이 있나 | 현재 상태를 보여주면서 저장 가능한 형태로 남겨야 해서 |
| 배터리 상태는 왜 안 보이나 | 현재 drawio와 상태 스냅샷 기준으로 수집하지 않기 때문 |

## 16. 코드리뷰에서 설명하는 순서

코드리뷰에서는 다음 순서로 말하면 흐름이 끊기지 않습니다.

```text
1. 로그인 후 지자체 관리 화면이 기본 진입점입니다.
2. 공통 사이드바가 항상 떠 있고, 여기서 다른 화면으로 이동합니다.
3. 상태 스냅샷은 백엔드 메모리에 있고 프론트는 /api/status로 읽습니다.
4. 웹캠은 OpenCV가 읽고 JPEG로 바꾼 뒤 MJPEG로 보냅니다.
5. AMR 카메라는 ROS CompressedImage를 받아 같은 방식으로 중계합니다.
6. AMR 상태 토픽은 JSON 문자열을 파싱해 6단계 이벤트로 반영합니다.
7. RETURN_DONE에서 보고서가 자동 저장됩니다.
8. 저장된 보고서는 SQLite에서 조회, 수정, 복원할 수 있습니다.
9. 보고서 분석은 저장된 스냅샷을 바탕으로 점검 필요 항목을 분리합니다.
```

### 16.1 `Ctrl+F` 검색 키워드

아래 표는 코드리뷰 중에 "이 구현이 어디 있나요?"라는 질문을 받았을 때 바로 찾을 수 있도록 만든 검색표입니다.
각 행은 파일에서 먼저 찾을 키워드와, 그 키워드가 실제로 들어 있는 주요 위치를 같이 적었습니다.

| 순서 | 설명 | 주요 파일 | `Ctrl+F` 키워드 |
| --- | --- | --- | --- |
| 1 | 로그인 진입과 내부 화면 보호 | `frontend/src/App.jsx`, `backend/main.py` | `ProtectedRoute`, `isLoggedIn`, `/login`, `@app.post("/api/login")`, `demo-token` |
| 2 | 지자체 관리 화면과 공통 사이드바 | `frontend/src/components/layout/Layout.jsx`, `frontend/src/components/layout/Sidebar.jsx`, `frontend/src/pages/MunicipalDashboardPage.jsx`, `backend/main.py` | `Layout`, `Sidebar`, `Outlet`, `fetchSystemStatus`, `fetchReport`, `@app.get("/api/status")`, `@app.get("/api/report")` |
| 3 | 웹캠 캡처와 MJPEG 스트리밍 | `backend/main.py`, `frontend/src/config/cameras.js` | `OpenCvWebcamCapture`, `_capture_loop`, `update_latest_webcam_frame`, `webcam_mjpeg_stream`, `webcam_stream`, `WEBCAM_CAPTURE_FPS`, `StreamingResponse`, `webcam` |
| 4 | AMR 카메라 ROS 구독과 스트리밍 | `backend/main.py`, `frontend/src/config/cameras.js` | `RosAmrBridge`, `CompressedImage`, `update_amr_camera_frame`, `amr_mjpeg_stream`, `amr_camera_stream`, `AMR_CAMERA_CONFIG`, `/robot8/oakd/rgb/image_raw/compressed`, `/robot11/oakd/rgb/image_raw/compressed` |
| 5 | AMR 상태 이벤트 반영과 6단계 보고서 | `backend/main.py`, `frontend/src/pages/MunicipalDashboardPage.jsx`, `frontend/src/api/statusApi.js` | `parse_amr_status_message`, `normalize_scenario_event`, `apply_amr_status_payload`, `apply_scenario_event`, `SCENARIO_EVENT_ALIASES`, `simulateEvent`, `resetScenario`, `record_report_time_once` |
| 6 | 통합 보고서 실시간 폴링 | `frontend/src/pages/IntegratedReportPage.jsx`, `frontend/src/hooks/usePolling.js`, `backend/main.py`, `frontend/src/components/report/ReportOperationSummary.jsx`, `frontend/src/components/report/ReportTimeline.jsx` | `usePolling`, `fetchReport`, `ReportOperationSummary`, `ReportTimeline`, `mode="live"`, `@app.get("/api/report")` |
| 7 | `RETURN_DONE` 자동 저장 | `backend/main.py` | `RETURN_DONE`, `amr_return_done_at`, `auto_save_report_if_return_done`, `save_report_to_db`, `last_auto_saved_return_done_at`, `report_auto_save_lock` |
| 8 | 저장된 보고서 목록/상세/이름 수정/복원 | `backend/main.py`, `frontend/src/pages/SavedReportsPage.jsx`, `frontend/src/api/statusApi.js` | `list_saved_reports`, `get_saved_report`, `update_saved_report_title`, `restore_saved_report`, `row_to_report`, `apply_report_to_live_state`, `fetchSavedReports`, `fetchSavedReport`, `updateSavedReportTitle`, `restoreSavedReport` |
| 9 | 보고서 분석과 점검 필요 판정 | `frontend/src/pages/ReportAnalyticsPage.jsx`, `frontend/src/utils/reportAnalysis.js`, `backend/main.py` | `buildReportAnalytics`, `analyzeReport`, `REPORT_STEPS`, `REPORT_TRANSITIONS`, `missingSteps`, `invalidTransitions`, `needsAttention`, `report_json`, `created_at`, `updated_at` |

## 17. 결론

이 구조는 현재 요구사항인 관제 화면, 실시간 카메라, 6단계 이벤트 추적, 저장 보고서, 분석 화면을 단순하게 만족시키면서도, 나중에 실제 ROS2/카메라/DB/인증으로 확장할 수 있도록 만들어졌습니다.

핵심은 다음 세 가지입니다.

```text
React + Vite
  - 여러 화면과 공통 사이드바를 가진 SPA에 적합

FastAPI
  - Python ROS2/OpenCV/SQLite와 자연스럽게 연결

SQLite
  - 저장된 보고서를 별도 서버 없이 영속화
```

즉, 이 프로젝트는 "화면은 React", "상태와 장치는 FastAPI", "기록은 SQLite"로 나누는 것이 가장 실용적입니다.

## 18. 코드리뷰순서

| 순서 | 설명할 내용 | 파일 | 함수 / 키워드 | 다음으로 이어지는 이유 |
| --- | --- | --- | --- | --- |
| 1 | 로그인 후 내부 화면으로 들어가는 진입점 | `frontend/src/App.jsx` | `ProtectedRoute`, `<Routes>`, `/login`, `/dashboard`, `/report` | 로그인 성공 여부에 따라 어떤 화면이 열리는지 먼저 보여줘야 한다 |
| 2 | 공통 사이드바가 항상 유지되는 구조 | `frontend/src/components/layout/Layout.jsx`, `frontend/src/components/layout/Sidebar.jsx` | `Layout`, `Sidebar`, `Outlet` | 지자체 관리 화면이 기본 화면이지만, 실제로는 사이드바로 화면을 계속 바꿀 수 있다 |
| 3 | 지자체 관리 화면이 live snapshot을 읽는 방식 | `frontend/src/pages/MunicipalDashboardPage.jsx`, `frontend/src/hooks/usePolling.js`, `frontend/src/api/statusApi.js` | `usePolling(fetchSystemStatus, 1000)`, `fetchSystemStatus()`, `resetScenario()` | 프론트가 백엔드 상태를 직접 계산하지 않고 `/api/status`를 읽기 때문이다 |
| 4 | 백엔드가 현재 상태를 묶어서 주는 지점 | `backend/main.py` | `get_status()`, `state`, `apply_amr_status_payload`, `camera_snapshot()`, `normalize_report()` | 화면은 결국 이 스냅샷을 기준으로 갱신되므로 백엔드 응답 구조를 설명해야 한다 |
| 5 | 웹캠과 AMR 카메라를 같은 UI로 보여주는 방식 | `frontend/src/pages/CameraMonitorPage.jsx`, `frontend/src/components/camera/CameraPanel.jsx`, `frontend/src/config/cameras.js` | `CAMERAS`, `CameraPanel`, `loadStatus()`, `loadDeviceOptions()`, `handleDeviceChange()` | 장치가 여러 개여도 하나의 패널 로직으로 처리한다는 점을 보여준다 |
| 6 | 실제 영상 스트리밍이 만들어지는 백엔드 구조 | `backend/main.py` | `OpenCvWebcamCapture`, `webcam_mjpeg_stream()`, `update_latest_webcam_frame()`, `RosAmrBridge`, `amr_mjpeg_stream()` | 웹캠은 OpenCV, AMR 카메라는 ROS bridge로 받지만 브라우저에는 둘 다 스트리밍으로 보낸다 |
| 7 | 통합 보고서 화면이 실시간으로 갱신되는 구조 | `frontend/src/pages/IntegratedReportPage.jsx`, `frontend/src/components/report/ReportOperationSummary.jsx` | `usePolling(fetchReport, 1000)`, `fetchReport()`, `ReportOperationSummary` | 보고서는 live state를 그대로 보여주는 화면이므로 이벤트가 쌓이는 과정을 설명하기 좋다 |
| 8 | 이벤트가 들어오면 상태 스냅샷이 어떻게 바뀌는지 | `backend/main.py` | `parse_amr_status_message()`, `normalize_scenario_event()`, `apply_amr_status_payload()`, `apply_scenario_event()`, `infer_report_event_from_amr_status()`, `RosAmrBridge._on_status()` | `status_event` JSON이 6단계 이벤트로 바뀌는 핵심 로직이기 때문이다 |
| 9 | 복귀 완료 시 보고서가 자동 저장되는 이유 | `backend/main.py` | `auto_save_report_if_return_done()`, `save_report_to_db()`, `record_report_time_once()`, `RETURN_DONE` | 수동 저장이 아니라 동작 완료 시점에 저장되므로 시연 흐름이 단순해진다 |
| 10 | 저장된 보고서를 다시 보고 이름을 수정하는 흐름 | `frontend/src/pages/SavedReportsPage.jsx`, `frontend/src/api/statusApi.js` | `fetchSavedReports()`, `fetchSavedReport()`, `updateSavedReportTitle()`, `restoreSavedReport()` | 저장된 데이터를 다시 불러오고 복원하는 기능이 데이터베이스와 연결되는 지점이다 |
| 11 | 저장된 보고서를 기준으로 분석하는 흐름 | `frontend/src/pages/ReportAnalyticsPage.jsx`, `frontend/src/utils/reportAnalysis.js` | `buildReportAnalytics()`, `analyzeReport()`, `REPORT_STEPS`, `REPORT_TRANSITIONS` | 누락, 미완료, 순서오류 같은 점검 항목이 어디서 나오는지 마지막에 설명한다 |

### 18.1 발표할 때의 실제 말하기 순서

아래처럼 말하면 흐름이 끊기지 않습니다.

1. `App.jsx`에서 로그인과 내부 화면을 분리하고, 로그인 후에는 `Layout`으로 들어가게 합니다.
2. `Layout` 안에는 항상 `Sidebar`가 있고, `Outlet`으로 화면만 바뀝니다.
3. 지자체 관리 화면은 `usePolling(fetchSystemStatus, 1000)`으로 `/api/status`를 읽어서 현재 상태를 보여줍니다.
4. 카메라 화면은 `CAMERAS` 설정을 기준으로 웹캠, AMR1, AMR2를 같은 `CameraPanel`로 그립니다.
5. 백엔드에서는 웹캠은 OpenCV로, AMR 카메라는 ROS bridge로 받아서 MJPEG로 보냅니다.
6. AMR 상태 토픽은 `parse_amr_status_message()`와 `apply_amr_status_payload()`를 거쳐 6단계 이벤트로 바뀝니다.
7. `RETURN_DONE`이 되면 `auto_save_report_if_return_done()`가 `save_report_to_db()`를 호출해서 SQLite에 저장합니다.
8. 저장된 보고서는 `SavedReportsPage.jsx`에서 수정하거나 `restoreSavedReport()`로 다시 불러올 수 있습니다.
9. 마지막으로 `ReportAnalyticsPage.jsx`와 `buildReportAnalytics()`가 누락, 미완료, 순서오류를 점검 항목으로 분리합니다.

### 18.2 코드리뷰에서 바로 찾을 키워드

이 순서대로 설명하다가 "코드가 어디 있나요?"라는 질문을 받으면 아래 키워드로 바로 찾으면 됩니다.

| 설명 | 검색 키워드 |
| --- | --- |
| 로그인과 내부 화면 보호 | `ProtectedRoute`, `isLoggedIn`, `/login`, `demo-token` |
| 기본 진입 화면과 사이드바 | `Layout`, `Sidebar`, `Outlet`, `dashboard` |
| 실시간 상태 조회 | `usePolling`, `fetchSystemStatus`, `/api/status`, `state` |
| 웹캠 스트리밍 | `OpenCvWebcamCapture`, `webcam_mjpeg_stream`, `StreamingResponse` |
| AMR 카메라 스트리밍 | `RosAmrBridge`, `amr_mjpeg_stream`, `CompressedImage` |
| 이벤트 반영 | `parse_amr_status_message`, `apply_amr_status_payload`, `apply_scenario_event` |
| 자동 저장 | `RETURN_DONE`, `auto_save_report_if_return_done`, `save_report_to_db` |
| 저장 보고서 관리 | `fetchSavedReports`, `fetchSavedReport`, `updateSavedReportTitle`, `restoreSavedReport` |
| 분석 화면 | `buildReportAnalytics`, `analyzeReport`, `REPORT_STEPS`, `REPORT_TRANSITIONS` |

### 18.3 한 문장 요약

이 프로젝트는 `App.jsx`에서 화면을 열고, `Layout`과 `Sidebar`로 이동을 유지한 뒤, `usePolling`으로 상태를 읽고, `main.py`가 그 상태를 만들고 저장하며, 마지막에 분석 화면이 그 저장된 데이터를 해석하는 순서로 동작합니다.
