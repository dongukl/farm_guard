# 팜가드봇 UI 웹서비스

이 폴더는 팜가드봇 관제 웹서비스입니다.

- `frontend/`: React + Vite 화면
- `backend/`: FastAPI API 서버

이 문서는 "깨끗한 PC"에서도 그대로 따라 실행할 수 있게 작성했습니다.
즉, `python`, `pip`, `venv`, `node`, `npm`이 아직 없는 환경도 포함합니다.

중요한 전제는 다음과 같습니다.

- 웹페이지 확인만 목적이면 웹캠과 ROS2 없이도 실행할 수 있습니다.
- USB 웹캠 실시간 스트리밍은 Linux 환경을 권장합니다.
- 현재 UI는 AMR 카메라 영상을 사용하지 않습니다.
- AMR 관련해서는 `status_event` 상태 이벤트만 사용합니다.

## 폴더 구조

```text
ui/
├── frontend/   # React + Vite 관제 화면
└── backend/    # FastAPI API 서버
```

## 기본 화면

1. 로그인 화면
   - 아이디: `admin`
   - 비밀번호: `1234`
2. 지자체 관리 화면
   - 웹캠 상태: 감지 / 감지 안됨
   - AMR 현재 상태: 감지 / 충전 도크 분리 및 출동 / 퇴치 시작 / 퇴치 완료 후 복귀 시작 / 도킹 완료 및 충전 대기
   - 최근 상태 이벤트 시간
3. 실시간 카메라 관제 화면
   - YOLO bbox 처리된 USB 웹캠 1개만 표시
4. 통합 보고서 화면
   - TOWER_DETECTED 시간
   - UNDOCK 시간
   - HERDING_ACTIVE 시간
   - MISSION_COMPLETE 시간
   - DOCK_COMPLETE 시간
   - 다음 동작까지 걸린 시간
   - 전체 동작 정상/진행/점검 필요 여부
   - DOCK_COMPLETE 시 현재 보고서를 SQLite에 자동 저장
   - 감지부터 도킹 완료까지 YOLO 처리 영상을 `backend/recordings/YYMMDD_HHMMSS.mp4`로 저장
5. 저장된 보고서 화면
   - 저장된 통합 보고서 목록 조회
   - 저장된 보고서 이름 수정
   - 선택한 보고서의 단계별 동작 상태와 소요 시간 확인
   - 선택한 보고서의 사건 영상 경로 확인 및 영상 재생
   - 선택한 보고서를 현재 통합 보고서 상태로 불러오기
6. 보고서 분석 화면
   - 연도별 사건 처리 현황
   - 월별 사건 처리 현황
   - 일별 사건 처리 현황
   - 해결 완료/점검 필요 보고서 집계

## 지원 환경

### 최소 권장 버전

| 항목 | 권장 버전 | 이유 |
| --- | --- | --- |
| Python | 3.10 이상 | 백엔드 문법과 가상환경 사용 |
| Node.js | 20 LTS 이상 | Vite/React 개발 서버 실행 |
| npm | Node.js 설치 시 함께 설치 | 프론트엔드 의존성 설치 |

### 운영체제별 권장도

- Ubuntu/Debian: 권장
- macOS: 웹페이지 확인 가능, USB 웹캠/ROS는 별도 확인 필요
- Windows: 웹페이지 확인 가능, USB 웹캠/ROS는 별도 확인 필요

`/dev/video*` 장치 경로와 ROS2 실사용은 Linux 기준 설명이 가장 정확합니다.

## 1. 처음 한 번만 해야 하는 설치

아래에서 자신의 운영체제에 맞는 항목만 실행하면 됩니다.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv curl git ffmpeg
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

설치 확인:

```bash
python3 --version
python3 -m pip --version
node -v
npm -v
```

### macOS

Homebrew가 없다면 먼저 설치합니다.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

그 다음 Python과 Node.js를 설치합니다.

```bash
brew install python@3.11 node
```

설치 확인:

```bash
python3 --version
python3 -m pip --version
node -v
npm -v
```

### Windows 10 / 11

PowerShell을 관리자 권한으로 열고 실행합니다.

```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS.LTS
```

설치 후 PowerShell을 새로 열고 확인합니다.

```powershell
python --version
python -m pip --version
node -v
npm -v
```

## 2. 프로젝트 압축 해제 또는 복사

이 저장소를 복사하거나 압축을 풀었다고 가정합니다.

최종적으로 아래 경로에 와 있어야 합니다.

```text
farmguard_bot/ui
```

## 3. 백엔드 준비

### Linux / macOS

```bash
cd farmguard_bot/ui/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Windows PowerShell

```powershell
cd farmguard_bot/ui/backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

참고:

- `pip` 명령이 안 잡히면 항상 `python -m pip ...` 형태를 사용하면 됩니다.
- 가상환경을 다시 켤 때는 `backend` 폴더에서 활성화 명령만 다시 실행하면 됩니다.

## 4. 프론트엔드 준비

### Linux / macOS

```bash
cd farmguard_bot/ui/frontend
npm install
```

### Windows PowerShell

```powershell
cd farmguard_bot/ui/frontend
npm install
```

## 5. 가장 안전한 실행 방법: 하드웨어 없이 웹페이지만 확인

다른 PC에서 "일단 화면이 열려야 한다"가 목적이면 이 방법을 먼저 권장합니다.

이 모드는 다음을 비활성화합니다.

- USB 웹캠 캡처
- AMR ROS bridge

즉, 카메라 장치와 ROS2가 없어도 로그인/대시보드/보고서/분석 화면을 확인할 수 있습니다.

### 터미널 1: Backend

#### Linux / macOS

```bash
cd farmguard_bot/ui/backend
source .venv/bin/activate
FARMGUARD_ENABLE_WEBCAM_CAPTURE=0 \
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
python -m uvicorn main:app --reload --port 8000
```

#### Windows PowerShell

```powershell
cd farmguard_bot/ui/backend
.\.venv\Scripts\Activate.ps1
$env:FARMGUARD_ENABLE_WEBCAM_CAPTURE="0"
$env:FARMGUARD_ENABLE_AMR_ROS_BRIDGE="0"
python -m uvicorn main:app --reload --port 8000
```

### 터미널 2: Frontend

#### Linux / macOS

```bash
cd farmguard_bot/ui/frontend
npm run dev
```

#### Windows PowerShell

```powershell
cd farmguard_bot/ui/frontend
npm run dev
```

브라우저 접속:

```text
http://localhost:5173
```

로그인:

```text
id: admin
pw: 1234
```

## 6. USB 웹캠까지 포함해서 실행

웹캠 실시간 영상까지 확인하려면 백엔드를 웹캠 캡처 활성화 상태로 실행해야 합니다.

현재 프로젝트는 Linux에서의 USB 웹캠 사용을 기준으로 설명합니다.

### 장치 확인

```bash
ls /dev/video*
```

### 실행

```bash
cd farmguard_bot/ui/backend
source .venv/bin/activate
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
python -m uvicorn main:app --reload --port 8000
```

기본 장치는 OpenCV의 `0`번 카메라입니다.

다른 장치를 쓰려면:

```bash
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
FARMGUARD_WEBCAM_DEVICE=/dev/video0 \
python -m uvicorn main:app --reload --port 8000
```

여러 PC에서 같은 USB 웹캠을 안정적으로 잡으려면 `/dev/video0`보다 `/dev/v4l/by-id/...` 경로를 권장합니다.

```bash
ls -l /dev/v4l/by-id/
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
FARMGUARD_WEBCAM_DEVICE=/dev/v4l/by-id/usb-카메라_이름-video-index0 \
python -m uvicorn main:app --reload --port 8000
```

YOLO 없이 raw OpenCV 화면만 확인하려면:

```bash
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
FARMGUARD_ENABLE_YOLO_WEBCAM=0 \
python -m uvicorn main:app --reload --port 8000
```

## 7. 저장 보고서와 사건 영상

보고서는 기본적으로 아래 파일에 저장됩니다.

```text
backend/reports.sqlite3
```

사건 영상은 기본적으로 아래 경로에 저장됩니다.

```text
backend/recordings/YYMMDD_HHMMSS.mp4
```

보고서 이벤트는 다음 값들을 기준으로 진행됩니다.

```text
TOWER_DETECTED
UNDOCK
HERDING_ACTIVE
MISSION_COMPLETE
DOCK_COMPLETE
```

`DOCK_COMPLETE`가 들어오면 보고서가 자동 저장됩니다.

저장된 보고서 영상은 다음 API로 재생됩니다.

```text
GET /api/reports/{report_id}/video
```

저장 위치를 바꾸려면 백엔드 실행 전에 환경변수를 지정합니다.

```bash
FARMGUARD_REPORT_DB=/path/to/reports.sqlite3
FARMGUARD_WEBCAM_RECORDING_DIR=/path/to/recordings
```

## 8. AMR ROS2 상태 이벤트 연동

현재 UI는 AMR 카메라 영상을 사용하지 않습니다.
대신 AMR 상태/이벤트는 `/status_event` 토픽으로 받을 수 있습니다.

기본 토픽:

```text
/status_event    std_msgs/msg/String
```

토픽 이름이 다르면:

```bash
FARMGUARD_STATUS_EVENT_TOPIC=/status_event \
python -m uvicorn main:app --reload --port 8000
```

예시 발행:

```bash
ros2 topic pub /status_event std_msgs/msg/String \
  "{data: '{\"robot_id\":\"AMR1\", \"event\":\"UNDOCK\", \"status\":\"충전 도크 분리 및 출동\", \"timestamp\":\"2026-07-09 18:20:10\"}'}"
```

AMR ROS bridge 상태 확인 API:

```text
GET /api/amr/ros-status
```

## 9. 자주 발생하는 문제

### `python: command not found` 또는 `python3: command not found`

Python이 설치되지 않은 상태입니다.
위의 "처음 한 번만 해야 하는 설치" 섹션부터 다시 진행하세요.

### `pip: command not found`

다음 둘 중 하나입니다.

- Python 자체가 설치되지 않음
- 가상환경이 활성화되지 않음

우선 아래처럼 확인하세요.

```bash
python3 --version
python3 -m pip --version
```

그리고 pip는 가능하면 아래처럼 실행하세요.

```bash
python -m pip install -r requirements.txt
```

### `No module named venv`

Ubuntu/Debian에서는 `python3-venv`가 없는 경우입니다.

```bash
sudo apt install -y python3-venv
```

### `node: command not found` 또는 `npm: command not found`

Node.js/npm이 설치되지 않은 상태입니다.
위의 운영체제별 설치 섹션대로 먼저 설치하세요.

설치 후 새 터미널을 열고 확인하세요.

```bash
node -v
npm -v
```

### `Error: listen EADDRINUSE` 또는 포트 충돌

이미 같은 포트를 쓰는 프로세스가 떠 있는 상태입니다.

- 백엔드: `8000`
- 프론트엔드: `5173`

기존 프로세스를 종료하거나 다른 포트로 실행하세요.

### 카메라 페이지에 아래 문구가 보임

```text
FARMGUARD_ENABLE_WEBCAM_CAPTURE=0 설정으로 웹캠 캡처가 비활성화됐습니다.
```

이건 오류가 아니라 "웹캠을 끈 모드"로 백엔드를 실행했다는 뜻입니다.
웹캠 화면이 필요하면 6번 섹션의 웹캠 활성화 실행 방법으로 다시 띄우면 됩니다.

### 웹캠이 열리지 않음

Linux에서 아래를 확인하세요.

```bash
ls /dev/video*
```

장치가 없으면:

- USB 연결 상태 확인
- 다른 프로그램이 카메라를 점유 중인지 확인
- 사용자 권한 확인

### OpenCV / YOLO가 느림

CPU 환경에서는 첫 구동이 느릴 수 있습니다.
화면 확인만 목적이면 아래처럼 YOLO를 끄고 테스트할 수 있습니다.

```bash
FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 \
FARMGUARD_ENABLE_YOLO_WEBCAM=0 \
python -m uvicorn main:app --reload --port 8000
```

## 10. 가장 빠른 체크리스트

처음 실행할 때는 아래 순서가 가장 안전합니다.

1. Python, pip, venv, Node.js, npm 설치
2. `backend`에서 가상환경 생성 후 `pip install -r requirements.txt`
3. `frontend`에서 `npm install`
4. 먼저 "하드웨어 없이 웹페이지만 확인" 모드로 실행
5. 화면이 정상 열리면 그 다음에 웹캠/ROS를 순서대로 붙이기

이 순서를 따르면 "어느 단계에서 막혔는지"를 구분하기 쉽습니다.
