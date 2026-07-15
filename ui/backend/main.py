import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="유해 짐승 퇴치 로봇 관제 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    # DB에 저장되는 모든 시간은 UTC ISO 문자열로 통일한다.
    # 프론트에서는 Date 객체로 파싱한 뒤 ko-KR 형식으로 표시한다.
    return datetime.now(timezone.utc).isoformat()


# 통합 보고서에서 "완료 단계"로 계산할 시간 필드 목록이다.
# status_event의 최신 계약은 5단계이므로 보고서/진행도 계산도 이 순서를 기준으로 맞춘다.
REPORT_TIME_FIELDS = (
    "tower_detected_at",
    "undock_at",
    "herding_active_at",
    "mission_complete_at",
    "dock_complete_at",
)

# 기존 6단계 구조로 저장된 보고서도 새 5단계 UI에서 읽을 수 있게 레거시 필드를 같이 기억한다.
LEGACY_REPORT_TIME_FIELDS = (
    "webcam_detected_at",
    "amr_undock_at",
    "amr_patrol_start_at",
    "amr_object_detected_at",
    "amr_deterrence_done_at",
    "amr_return_done_at",
)

REPORT_TIME_FIELD_CANDIDATES = {
    "tower_detected_at": ("tower_detected_at", "webcam_detected_at"),
    "undock_at": ("undock_at", "amr_undock_at", "amr_patrol_start_at"),
    "herding_active_at": ("herding_active_at", "amr_object_detected_at"),
    "mission_complete_at": ("mission_complete_at", "amr_deterrence_done_at"),
    "dock_complete_at": ("dock_complete_at", "amr_return_done_at"),
}

REPORT_VIDEO_FIELDS = ("video_path",)

# scenario_status까지 포함한 보고서 전체 필드 목록이다.
# DB에 저장된 JSON이 깨졌거나 누락됐을 때 각 컬럼 값으로 복구하기 위한 fallback에 사용한다.
REPORT_FIELDS = ("scenario_status", *REPORT_TIME_FIELDS, *REPORT_VIDEO_FIELDS)
ROW_REPORT_FIELDS = ("scenario_status", *REPORT_TIME_FIELDS, *LEGACY_REPORT_TIME_FIELDS, *REPORT_VIDEO_FIELDS)

# 기본 저장 위치는 backend/reports.sqlite3이다.
# FARMGUARD_REPORT_DB 환경 변수를 주면 운영/시연 환경에서 DB 파일 위치만 바꿀 수 있다.
DB_PATH = Path(os.getenv("FARMGUARD_REPORT_DB", Path(__file__).with_name("reports.sqlite3")))

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# USB 웹캠은 ROS 토픽을 거치지 않고 OpenCV가 직접 /dev/video* 장치를 읽는다.
# 기본값은 0번 장치이며, 프론트에서 런타임에 다른 번호로 바꿀 수 있다.
DEFAULT_WEBCAM_VIDEO_DEVICE = os.getenv("FARMGUARD_WEBCAM_DEVICE", "0")
ENABLE_WEBCAM_CAPTURE = os.getenv("FARMGUARD_ENABLE_WEBCAM_CAPTURE", "1") != "0"
WEBCAM_FRAME_WIDTH = int(os.getenv("FARMGUARD_WEBCAM_WIDTH", "640"))
WEBCAM_FRAME_HEIGHT = int(os.getenv("FARMGUARD_WEBCAM_HEIGHT", "480"))
WEBCAM_CAPTURE_FPS = float(os.getenv("FARMGUARD_WEBCAM_FPS", "15"))
WEBCAM_JPEG_QUALITY = int(os.getenv("FARMGUARD_WEBCAM_JPEG_QUALITY", "85"))
WEBCAM_DEVICE_OPTION_COUNT = int(os.getenv("FARMGUARD_WEBCAM_DEVICE_OPTION_COUNT", "6"))
WEBCAM_LATEST_FRAME_PATH = Path(
    os.getenv("FARMGUARD_WEBCAM_FRAME_PATH", Path(__file__).with_name("latest_webcam.jpg"))
)
ENABLE_YOLO_WEBCAM = os.getenv("FARMGUARD_ENABLE_YOLO_WEBCAM", "1") != "0"
YOLO_MODEL_PATH = os.getenv("FARMGUARD_YOLO_MODEL", "yolo11n.pt")
YOLO_DEVICE = os.getenv("FARMGUARD_YOLO_DEVICE", "cpu")
YOLO_IMAGE_SIZE = int(os.getenv("FARMGUARD_YOLO_IMAGE_SIZE", "640"))
YOLO_CONFIDENCE = float(os.getenv("FARMGUARD_YOLO_CONFIDENCE", "0.25"))
YOLO_IOU = float(os.getenv("FARMGUARD_YOLO_IOU", "0.45"))
YOLO_USE_HALF = os.getenv("FARMGUARD_YOLO_HALF", "0") == "1"
WEBCAM_RECORDING_DIR = Path(
    os.getenv("FARMGUARD_WEBCAM_RECORDING_DIR", Path(__file__).with_name("recordings"))
)
WEBCAM_RECORDING_FPS = float(os.getenv("FARMGUARD_WEBCAM_RECORDING_FPS", str(WEBCAM_CAPTURE_FPS)))

# 프론트엔드 빌드 산출물은 backend/main.py 기준의 sibling 디렉터리에서 찾는다.
# 빌드가 없으면 이 경로는 비어 있을 수 있으니, 아래 fallback 라우트에서 존재 여부를 확인한다.
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / "index.html"

# AMR은 ROS2 토픽을 표준 입력으로 사용한다. 상태 이벤트는 status_event 토픽의
# std_msgs/String JSON payload를 기본 계약으로 둔다.
ENABLE_AMR_ROS_BRIDGE = os.getenv("FARMGUARD_ENABLE_AMR_ROS_BRIDGE", "1") != "0"
AMR_STATUS_TOPIC = os.getenv("FARMGUARD_STATUS_EVENT_TOPIC") or os.getenv(
    "FARMGUARD_AMR_STATUS_TOPIC",
    "/status_event",
)
# AMR 카메라 토픽 기본값은 로봇별로 다를 수 있어서 이름별로 분리해서 둔다.
# 환경변수만 바꾸면 같은 백엔드 코드로 다른 장치 구성을 붙일 수 있다.
AMR_CAMERA_CONFIG = {
    "amr1": {
        "name": "AMR1",
        "topic": os.getenv("FARMGUARD_AMR1_IMAGE_TOPIC", "/robot8/oakd/rgb/image_raw/compressed"),
    },
    "amr2": {
        "name": "AMR2",
        "topic": os.getenv("FARMGUARD_AMR2_IMAGE_TOPIC", "/robot11/oakd/rgb/image_raw/compressed"),
    },
}


# INITIAL_STATE는 서비스가 시작될 때 만드는 live state의 초기값이다.
# 아래 state 딕셔너리는 이후 이벤트에 따라 계속 갱신되는 현재 관제 스냅샷이다.
INITIAL_STATE: Dict[str, Any] = {
    "webcam": {
        "id": "webcam",
        "name": "밭 경계선 웹캠",
        "status": "not_detected",  # detected, not_detected
        "detected_at": None,
    },
    "amr": {
        "id": "amr1",
        "name": "AMR1",
        "status": "dock_complete",  # tower_detected, undock, herding_active, mission_complete, dock_complete
        "detected_at": None,
        "updated_at": None,
        "battery": 87,
    },
    "report": {
        "scenario_status": "대기",
        "tower_detected_at": None,
        "undock_at": None,
        "herding_active_at": None,
        "mission_complete_at": None,
        "dock_complete_at": None,
        "video_path": None,
    },
}

state: Dict[str, Any] = {
    "webcam": dict(INITIAL_STATE["webcam"]),
    "amr": dict(INITIAL_STATE["amr"]),
    "report": dict(INITIAL_STATE["report"]),
}

# OpenCV 캡처 스레드에서 받은 최신 JPEG 프레임을 저장하는 메모리 버퍼이다.
# <img> 스트리밍은 이 버퍼를 읽고, 디버깅/요청사항 대응을 위해 최신 JPEG 파일도 같이 갱신한다.
latest_webcam_frame: Dict[str, Any] = {
    "bytes": None,
    "content_type": "image/jpeg",
    "format": None,
    "updated_at": None,
    "size": 0,
    "width": None,
    "height": None,
    "sequence": 0,
}
webcam_frame_condition = threading.Condition()
webcam_shutdown_event = threading.Event()
webcam_control_lock = threading.Lock()
webcam_video_device = DEFAULT_WEBCAM_VIDEO_DEVICE
webcam_capture = None
webcam_capture_error = None
amr_ros_bridge = None
amr_ros_error = None
amr_ros_shutdown_event = threading.Event()


def create_frame_buffer():
    # 웹캠과 AMR 카메라는 같은 형태의 최신 프레임 버퍼를 사용한다.
    # stream endpoint는 이 버퍼를 읽기만 하고, 실제 캡처/ROS 수신은 별도 스레드가 담당한다.
    return {
        "bytes": None,
        "content_type": "image/jpeg",
        "format": None,
        "updated_at": None,
        "size": 0,
        "sequence": 0,
    }


amr_camera_frames = {camera_id: create_frame_buffer() for camera_id in AMR_CAMERA_CONFIG}
amr_camera_conditions = {camera_id: threading.Condition() for camera_id in AMR_CAMERA_CONFIG}
report_auto_save_lock = threading.Lock()
last_auto_saved_dock_complete_at = None
last_auto_saved_report = None
report_auto_save_error = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ReportSaveRequest(BaseModel):
    # title은 사용자가 입력한 보고서 이름이다.
    # 비워서 보내면 save_report에서 현재 시간 기반 기본 제목을 만들어 저장한다.
    title: str | None = None

    # report는 프론트가 저장 시점에 보고 있던 통합 보고서 데이터이다.
    # 값이 없으면 백엔드 메모리에 있는 현재 state["report"]를 저장한다.
    report: Dict[str, Any] | None = None


class ReportTitleUpdateRequest(BaseModel):
    title: str


class WebcamDeviceRequest(BaseModel):
    device: str


def get_db_connection():
    # SQLite는 파일 DB이므로 부모 폴더가 없으면 연결 전에 만들어야 한다.
    # 기본 경로는 backend 폴더라 보통 이미 존재하지만, 환경변수로 다른 경로를 줄 수 있다.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)

    # sqlite3.Row를 쓰면 row["title"]처럼 컬럼명으로 읽을 수 있어
    # SELECT 결과를 dict 형태의 API 응답으로 바꾸기 쉽다.
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_connection():
    # 각 API 요청마다 짧게 연결을 열고 닫는다.
    # 현재 규모에서는 connection pool 없이 SQLite 표준 연결만으로 충분하다.
    connection = get_db_connection()
    try:
        yield connection

        # SELECT만 한 경우에도 commit은 무해하고, INSERT/DDL은 여기서 확정된다.
        connection.commit()
    finally:
        # FastAPI 서버가 오래 떠 있어도 파일 핸들이 누적되지 않도록 명시적으로 닫는다.
        connection.close()


def init_db():
    # 서버 import 시 한 번 호출되어 저장 테이블을 보장한다.
    # 이미 테이블이 있으면 IF NOT EXISTS 때문에 기존 데이터는 유지된다.
    with db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                scenario_status TEXT NOT NULL,
                -- 아래 시간 컬럼들은 목록 화면에서 빠르게 요약하거나 정렬/검색을 확장할 때 쓰기 쉽다.
                tower_detected_at TEXT,
                undock_at TEXT,
                herding_active_at TEXT,
                mission_complete_at TEXT,
                dock_complete_at TEXT,
                video_path TEXT,
                -- report_json에는 통합 보고서 원본 payload 전체를 저장한다.
                -- 컬럼이 늘어났을 때도 JSON만 확장하면 기존 API 형태를 비교적 쉽게 유지할 수 있다.
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saved_reports_created_at
            ON saved_reports(created_at DESC)
            """
        )

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(saved_reports)").fetchall()
        }
        for column_name in (*REPORT_TIME_FIELDS, *REPORT_VIDEO_FIELDS):
            if column_name not in columns:
                connection.execute(f"ALTER TABLE saved_reports ADD COLUMN {column_name} TEXT")


def build_scenario_status_label(event_name: str, robot_name: str | None = None) -> str:
    labels = {
        "tower_detected": "감지",
        "undock": "충전 도크 분리 및 출동",
        "herding_active": "퇴치 시작",
        "mission_complete": "야생동물 퇴치 완료. 로봇 대기 좌표로 복귀 시작",
    }
    if event_name == "dock_complete":
        return f"{robot_name} 도킹 완료 및 충전 대기 중" if robot_name else "도킹 완료 및 충전 대기 중"
    return labels.get(event_name, "대기")


def derive_report_scenario_status(report: Dict[str, Any]) -> str:
    for field_name in reversed(REPORT_TIME_FIELDS):
        if report.get(field_name):
            return build_scenario_status_label(field_name.removesuffix("_at"))
    return "대기"


def normalize_report_scenario_status(value: Any) -> str | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    if raw_value == "대기":
        return "대기"

    event_name = normalize_scenario_event(raw_value)
    if event_name:
        return build_scenario_status_label(event_name)

    status_value = normalize_amr_status(raw_value)
    if status_value:
        return build_scenario_status_label(status_value)

    return None


def normalize_report(report: Dict[str, Any] | None) -> Dict[str, Any]:
    # 저장/조회/복원 전에 보고서 모양을 항상 같은 형태로 맞춘다.
    # 이렇게 해두면 프론트가 오래된 저장 데이터를 받아도 필드 누락으로 깨지지 않는다.
    source = report or {}
    raw_status = str(source.get("scenario_status") or "").strip()
    normalized = {
        "scenario_status": normalize_report_scenario_status(raw_status) or raw_status or "대기",
    }

    # 시간 필드는 아직 발생하지 않은 이벤트라면 None으로 통일한다.
    # 빈 문자열을 그대로 두면 프론트에서 "값이 있다"고 오해할 수 있다.
    for field, candidates in REPORT_TIME_FIELD_CANDIDATES.items():
        normalized[field] = next((source.get(candidate) for candidate in candidates if source.get(candidate)), None)
    normalized["video_path"] = source.get("video_path") or None

    if normalized["scenario_status"] == "대기":
        normalized["scenario_status"] = derive_report_scenario_status(normalized)
    return normalized


def report_video_file_exists(video_path: str | None) -> bool:
    if not video_path:
        return False

    try:
        resolve_report_video_file(video_path)
    except HTTPException:
        return False
    return True


def row_to_report(row: sqlite3.Row) -> Dict[str, Any]:
    # 최신 저장 데이터는 report_json을 기준으로 응답을 만든다.
    # report_json은 저장 시점의 보고서 전체 구조를 보존하는 원본에 가깝다.
    try:
        report = json.loads(row["report_json"])
    except (TypeError, json.JSONDecodeError):
        # 혹시 JSON이 손상됐거나 과거 버전 데이터가 들어와도
        # 개별 컬럼으로 최소한의 보고서 화면은 복원할 수 있게 한다.
        report = {field: row[field] for field in ROW_REPORT_FIELDS if field in row.keys()}

    report = normalize_report(report)
    if not report.get("video_path"):
        try:
            report["video_path"] = row["video_path"] or None
        except (KeyError, IndexError):
            report["video_path"] = None

    # 저장 목록에서 "3/5" 같은 진행도 배지를 보여주기 위한 값이다.
    # scenario_status는 단계 완료 여부가 아니므로 시간 필드만 계산한다.
    completed_steps = sum(1 for field in REPORT_TIME_FIELDS if report.get(field))
    video_path = report.get("video_path")
    video_file_exists = report_video_file_exists(video_path)

    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_steps": completed_steps,
        "report": report,
        "has_video": video_file_exists,
        "video_filename": Path(video_path).name if video_path else None,
        "video_url": f"/api/reports/{row['id']}/video" if video_file_exists else None,

        # 목록 화면에서 중첩 객체를 열지 않고도 바로 요약값을 쓰기 쉽도록
        # report 내부 필드도 최상위에 한 번 더 펼쳐서 내려준다.
        **report,
    }


def fetch_saved_report_row(report_id: int) -> sqlite3.Row:
    # 상세 조회와 복원 API가 같은 조회/404 처리를 쓰도록 공통 함수로 뺐다.
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM saved_reports WHERE id = ?",
            (report_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="saved report not found")

    return row


def build_default_report_title(report: Dict[str, Any], timestamp: str) -> str:
    # 사용자가 제목을 따로 안 넣으면 현재 상황과 시각을 기준으로 기본 제목을 만든다.
    status = report.get("scenario_status") if report.get("scenario_status") != "대기" else "통합 보고서"
    return f"{status} {timestamp}"


def save_report_to_db(report: Dict[str, Any] | None, title: str | None = None, timestamp: str | None = None):
    timestamp = timestamp or now_iso()
    normalized_report = normalize_report(report or state["report"])
    report_title = (title or "").strip() or build_default_report_title(normalized_report, timestamp)
    report_json = json.dumps(normalized_report, ensure_ascii=False)

    # 저장 시점의 보고서는 원본 JSON과 검색용 개별 컬럼을 함께 저장한다.
    # JSON은 복원성과 호환성을 위해, 개별 컬럼은 목록 검색과 정렬을 위해 둔다.
    with db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO saved_reports (
                title,
                scenario_status,
                tower_detected_at,
                undock_at,
                herding_active_at,
                mission_complete_at,
                dock_complete_at,
                video_path,
                report_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_title,
                normalized_report["scenario_status"],
                normalized_report["tower_detected_at"],
                normalized_report["undock_at"],
                normalized_report["herding_active_at"],
                normalized_report["mission_complete_at"],
                normalized_report["dock_complete_at"],
                normalized_report["video_path"],
                report_json,
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute(
            "SELECT * FROM saved_reports WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return row_to_report(row)


def auto_save_report_if_dock_complete():
    global last_auto_saved_dock_complete_at, last_auto_saved_report, report_auto_save_error

    dock_complete_at = state["report"].get("dock_complete_at")
    if not dock_complete_at:
        return None

    with report_auto_save_lock:
        if last_auto_saved_dock_complete_at == dock_complete_at:
            return None

        try:
            saved_report = save_report_to_db(state["report"], timestamp=dock_complete_at)
        except Exception as exc:
            report_auto_save_error = str(exc)
            return None

        last_auto_saved_dock_complete_at = dock_complete_at
        last_auto_saved_report = saved_report
        report_auto_save_error = None
        return saved_report


def update_saved_report_title(report_id: int, title: str):
    normalized_title = (title or "").strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="report title is required")

    timestamp = now_iso()
    # 제목 수정은 메타데이터 변경이므로 updated_at만 갱신한다.
    with db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE saved_reports
            SET title = ?, updated_at = ?
            WHERE id = ?
            """,
            (normalized_title, timestamp, report_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="saved report not found")

        row = connection.execute(
            "SELECT * FROM saved_reports WHERE id = ?",
            (report_id,),
        ).fetchone()

    return row_to_report(row)


def resolve_report_video_file(video_path: str | None) -> Path:
    if not video_path:
        raise HTTPException(status_code=404, detail="saved report video path not found")

    recording_root = WEBCAM_RECORDING_DIR.resolve()
    raw_path = Path(video_path).expanduser()
    candidates = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append((Path(__file__).resolve().parent / raw_path))
        candidates.append((recording_root / raw_path))

    # 이전 PC의 절대경로나 "recordings/foo.mp4" 같은 레거시 상대경로가 DB에 남아 있어도
    # 현재 recordings 폴더에 같은 파일명이 있으면 재생할 수 있게 한다.
    if raw_path.name:
        candidates.append(recording_root / raw_path.name)

    checked_paths = set()
    for candidate in candidates:
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            continue
        if resolved_candidate in checked_paths:
            continue
        checked_paths.add(resolved_candidate)

        try:
            resolved_candidate.relative_to(recording_root)
        except ValueError:
            continue

        if resolved_candidate.is_file():
            return resolved_candidate

    raise HTTPException(status_code=404, detail="saved report video file not found")


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header:
        return None
    if not range_header.startswith("bytes="):
        return None

    range_value = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in range_value:
        return None

    start_value, end_value = range_value.split("-", 1)
    try:
        if start_value:
            start = int(start_value)
            end = int(end_value) if end_value else file_size - 1
        else:
            suffix_length = int(end_value)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as exc:
        raise HTTPException(
            status_code=416,
            detail="invalid range",
            headers={"Content-Range": f"bytes */{file_size}"},
        ) from exc

    end = min(end, file_size - 1)
    if start < 0 or start > end or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail="range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    return start, end


def iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def browser_video_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}.browser.mp4")


def ensure_browser_playable_video(video_path: Path) -> Path:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return video_path

    output_path = browser_video_path(video_path)
    if output_path.is_file() and output_path.stat().st_mtime >= video_path.stat().st_mtime:
        return output_path

    temp_path = output_path.with_suffix(".tmp.mp4")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return video_path

    if completed.returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size <= 0:
        temp_path.unlink(missing_ok=True)
        return video_path

    temp_path.replace(output_path)
    return output_path


def apply_report_to_live_state(report: Dict[str, Any]):
    # "저장된 보고서 불러오기"는 DB 값을 단순히 화면에 표시하는 것이 아니라
    # 현재 /api/report, /api/status가 반환하는 메모리 상태를 저장 당시 상태로 되돌린다.
    stop_incident_video_recording()
    state["report"] = normalize_report(report)

    # 웹캠은 타워 감지 시간이 있고 아직 도킹 완료가 끝나지 않았으면 감지 상태로 본다.
    # 도킹 완료 보고서는 상황이 종료된 것이므로 not_detected로 돌린다.
    state["webcam"]["detected_at"] = state["report"]["tower_detected_at"]
    state["webcam"]["status"] = (
        "detected"
        if state["report"]["tower_detected_at"] and not state["report"]["dock_complete_at"]
        else "not_detected"
    )

    # AMR 상태는 보고서의 가장 뒤쪽 이벤트를 기준으로 역산한다.
    state["amr"]["detected_at"] = state["report"]["tower_detected_at"]
    if state["report"]["dock_complete_at"]:
        state["amr"]["status"] = "dock_complete"
    elif state["report"]["mission_complete_at"]:
        state["amr"]["status"] = "mission_complete"
    elif state["report"]["herding_active_at"]:
        state["amr"]["status"] = "herding_active"
    elif state["report"]["undock_at"]:
        state["amr"]["status"] = "undock"
    elif state["report"]["tower_detected_at"]:
        state["amr"]["status"] = "tower_detected"
    else:
        state["amr"]["status"] = "dock_complete"

    state["amr"]["updated_at"] = next(
        (state["report"][field_name] for field_name in reversed(REPORT_TIME_FIELDS) if state["report"].get(field_name)),
        None,
    )


# 외부 상태 문자열을 내부 AMR 상태 코드로 접는 별칭표다.
# dashboard 배지와 보고서 역산은 모두 이 표준 코드만 본다.
AMR_STATUS_ALIASES = {
    "idle": "dock_complete",
    "ready": "dock_complete",
    "docked": "dock_complete",
    "standby": "dock_complete",
    "대기": "dock_complete",
    "dock_complete": "dock_complete",
    "tower_detected": "tower_detected",
    "detected": "tower_detected",
    "감지": "tower_detected",
    "undock": "undock",
    "patrol": "undock",
    "patrolling": "undock",
    "순찰": "undock",
    "순찰중": "undock",
    "순찰 중": "undock",
    "herding_active": "herding_active",
    "object_detected": "herding_active",
    "물체감지": "herding_active",
    "물체 감지": "herding_active",
    "퇴치 시작": "herding_active",
    "mission_complete": "mission_complete",
    "deterrence": "mission_complete",
    "deterrence_done": "mission_complete",
    "퇴치": "mission_complete",
    "퇴치완료": "mission_complete",
    "퇴치 완료": "mission_complete",
    "return": "dock_complete",
    "return_done": "dock_complete",
}

# 보고서 단계의 표준 이벤트 이름이다.
# status_event의 최신 계약은 5단계 흐름이며 이 집합 안의 이름만 허용한다.
SCENARIO_EVENT_NAMES = {
    "tower_detected",
    "undock",
    "herding_active",
    "mission_complete",
    "dock_complete",
}

# 장치/팀마다 다르게 보낼 수 있는 이벤트 표기를 표준 이름으로 바꾼다.
# 예: DOCK_COMPLETE, RETURN_DONE -> dock_complete
SCENARIO_EVENT_ALIASES = {
    "TOWER_DETECTED": "tower_detected",
    "WEBCAM_DETECTED": "tower_detected",
    "WEB_CAM_DETECTED": "tower_detected",
    "UNDOCK": "undock",
    "AMR_UNDOCK": "undock",
    "AMR_UNDOCKED": "undock",
    "AMR_PATROL_START": "undock",
    "AMR_PATROL_STARTED": "undock",
    "PATROL_START": "undock",
    "PATROL_STARTED": "undock",
    "HERDING_ACTIVE": "herding_active",
    "AMR_OBJECT_DETECTED": "herding_active",
    "AMR_DETECTED": "herding_active",
    "MISSION_COMPLETE": "mission_complete",
    "AMR_DETERRENCE_DONE": "mission_complete",
    "AMR_DETERRENCE_COMPLETED": "mission_complete",
    "DETERRENCE_DONE": "mission_complete",
    "DETERRENCE_COMPLETED": "mission_complete",
    "DOCK_COMPLETE": "dock_complete",
    "AMR_RETURN_DONE": "dock_complete",
    "AMR_RETURN_COMPLETED": "dock_complete",
    "RETURN_DONE": "dock_complete",
    "RETURN_COMPLETED": "dock_complete",
    "웹캠 멧돼지 감지": "tower_detected",
    "AMR undock": "undock",
    "AMR 순찰 시작": "undock",
    "AMR 물체 감지": "herding_active",
    "AMR 퇴치 완료": "mission_complete",
    "AMR 복귀 완료": "dock_complete",
}


def normalize_amr_status(value: Any) -> str | None:
    # 상태 문자열은 장치마다 표기가 흔들릴 수 있으므로 내부 코드로 맞춘다.
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None

    if "도킹 완료" in normalized or "충전 대기" in normalized or "dock_complete" in normalized:
        return "dock_complete"
    if "복귀 시작" in normalized or "mission_complete" in normalized:
        return "mission_complete"
    if "퇴치 시작" in normalized or "herding_active" in normalized:
        return "herding_active"
    if "도크 분리" in normalized or "출동" in normalized or "undock" in normalized:
        return "undock"
    if normalized == "감지" or "tower_detected" in normalized:
        return "tower_detected"

    return AMR_STATUS_ALIASES.get(normalized)


def normalize_scenario_event(value: Any) -> str | None:
    # 외부 입력은 대소문자와 표기 흔들림이 있을 수 있으므로 내부 표준 이름으로 바꾼다.
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    normalized_name = raw_value.lower().replace("-", "_").replace(" ", "_")
    if normalized_name in SCENARIO_EVENT_NAMES:
        return normalized_name

    normalized_alias = normalized_name.upper()
    aliased = SCENARIO_EVENT_ALIASES.get(normalized_alias)
    if aliased:
        return aliased

    if "도킹 완료" in raw_value or "충전 대기" in raw_value:
        return "dock_complete"
    if "복귀 완료" in raw_value:
        return "dock_complete"
    if "복귀 시작" in raw_value or "MISSION_COMPLETE" in raw_value:
        return "mission_complete"
    if "퇴치 완료" in raw_value:
        return "mission_complete"
    if "퇴치 시작" in raw_value or "HERDING_ACTIVE" in raw_value:
        return "herding_active"
    if "물체 감지" in raw_value:
        return "herding_active"
    if "도크 분리" in raw_value or "출동" in raw_value or "UNDOCK" in raw_value:
        return "undock"
    if "순찰 시작" in raw_value:
        return "undock"
    if "웹캠" in raw_value and "감지" in raw_value:
        return "tower_detected"
    if raw_value.strip() == "감지":
        return "tower_detected"

    return None


def parse_amr_status_message(raw_value: str) -> Dict[str, Any]:
    # std_msgs/String.data 안에 JSON이 들어오면 그대로 파싱하고, 아니면 status 문자열로 본다.
    stripped = (raw_value or "").strip()
    if not stripped:
        return {}

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return {"status": stripped}

    return payload if isinstance(payload, dict) else {"status": stripped}


def clear_auto_save_tracking():
    # DOCK_COMPLETE 자동 저장은 같은 완료 시각에 대해 한 번만 실행되도록 추적한다.
    global last_auto_saved_dock_complete_at, last_auto_saved_report, report_auto_save_error

    last_auto_saved_dock_complete_at = None
    last_auto_saved_report = None
    report_auto_save_error = None


def reset_live_report_for_new_scenario():
    # 이전 시나리오가 끝난 뒤 새 감지가 오면 live report를 초기 상태로 되돌린다.
    stop_incident_video_recording()
    state["report"] = dict(INITIAL_STATE["report"])
    state["webcam"]["status"] = "not_detected"
    state["webcam"]["detected_at"] = None
    state["amr"]["status"] = "dock_complete"
    state["amr"]["detected_at"] = None
    clear_auto_save_tracking()


def record_report_time_once(field_name: str, timestamp: str) -> bool:
    # 같은 단계가 중복으로 들어와도 최초 시간만 남기기 위한 방어 로직이다.
    if state["report"].get(field_name):
        return False

    state["report"][field_name] = timestamp
    return True


def apply_scenario_event(event_name: str, timestamp: str | None = None):
    # 5단계 이벤트는 여기서 하나씩 보고서 시간 필드와 화면 상태로 반영된다.
    event_name = normalize_scenario_event(event_name)
    if not event_name:
        return state

    timestamp = timestamp or now_iso()

    if event_name == "tower_detected":
        if state["report"].get("dock_complete_at"):
            reset_live_report_for_new_scenario()

        state["webcam"]["status"] = "detected"
        state["amr"]["status"] = "tower_detected"
        if record_report_time_once("tower_detected_at", timestamp):
            state["webcam"]["detected_at"] = timestamp
            state["amr"]["detected_at"] = timestamp
            start_incident_video_recording()
        else:
            state["webcam"]["detected_at"] = state["report"]["tower_detected_at"]
            state["amr"]["detected_at"] = state["report"]["tower_detected_at"]
        state["report"]["scenario_status"] = build_scenario_status_label("tower_detected")

    elif event_name == "undock":
        state["amr"]["status"] = "undock"
        record_report_time_once("undock_at", timestamp)
        state["report"]["scenario_status"] = build_scenario_status_label("undock")

    elif event_name == "herding_active":
        state["amr"]["status"] = "herding_active"
        record_report_time_once("herding_active_at", timestamp)
        state["report"]["scenario_status"] = build_scenario_status_label("herding_active")

    elif event_name == "mission_complete":
        state["amr"]["status"] = "mission_complete"
        record_report_time_once("mission_complete_at", timestamp)
        state["report"]["scenario_status"] = build_scenario_status_label("mission_complete")

    elif event_name == "dock_complete":
        state["amr"]["status"] = "dock_complete"
        state["webcam"]["status"] = "not_detected"
        dock_complete_recorded = record_report_time_once("dock_complete_at", timestamp)
        stop_incident_video_recording()
        state["report"]["scenario_status"] = build_scenario_status_label("dock_complete", state["amr"].get("name"))
        if dock_complete_recorded:
            auto_save_report_if_dock_complete()

    if event_name != "tower_detected":
        state["amr"]["updated_at"] = timestamp

    return state


def infer_report_event_from_amr_status(status_value: str, previous_status: str | None) -> str | None:
    # status/state만 들어온 경우에도 보고서 단계로 역추론할 수 있게 만든다.
    if status_value == "tower_detected" and previous_status != "tower_detected" and not state["report"]["tower_detected_at"]:
        return "tower_detected"
    if status_value == "undock" and previous_status != "undock" and not state["report"]["undock_at"]:
        return "undock"
    if (
        status_value == "herding_active"
        and previous_status != "herding_active"
        and not state["report"]["herding_active_at"]
    ):
        return "herding_active"
    if (
        status_value == "mission_complete"
        and previous_status != "mission_complete"
        and not state["report"]["mission_complete_at"]
    ):
        return "mission_complete"
    if (
        status_value == "dock_complete"
        and previous_status not in (None, "dock_complete")
        and not state["report"]["dock_complete_at"]
    ):
        return "dock_complete"
    return None


def apply_amr_status_payload(payload: Dict[str, Any]):
    timestamp = payload.get("timestamp") or payload.get("updated_at") or now_iso()
    previous_status = state["amr"].get("status")

    robot_id = payload.get("robot_id") or payload.get("id")
    if robot_id:
        state["amr"]["id"] = str(robot_id)
        state["amr"]["name"] = str(payload.get("name") or str(robot_id).upper())
    elif payload.get("name"):
        state["amr"]["name"] = str(payload["name"])

    if payload.get("battery") is not None:
        try:
            state["amr"]["battery"] = int(float(payload["battery"]))
        except (TypeError, ValueError):
            pass

    # event는 5단계 보고서 흐름의 기준이고, state/status는 보조 상태로 본다.
    raw_status = payload.get("status") or payload.get("state")
    event_name = normalize_scenario_event(payload.get("event") or payload.get("event_name"))
    if not event_name:
        event_name = normalize_scenario_event(raw_status)

    status_value = normalize_amr_status(raw_status)

    if event_name:
        apply_scenario_event(str(event_name), timestamp)
    elif status_value:
        inferred_event = infer_report_event_from_amr_status(status_value, previous_status)
        if inferred_event:
            apply_scenario_event(inferred_event, timestamp)
        else:
            state["amr"]["status"] = status_value

    if status_value and not event_name:
        state["amr"]["status"] = status_value
        if status_value == "tower_detected":
            state["amr"]["detected_at"] = payload.get("detected_at") or timestamp
        if status_value == "dock_complete":
            state["webcam"]["status"] = "not_detected"

    state["amr"]["updated_at"] = timestamp
    return state["amr"]


def image_content_type(format_value: str | None) -> str:
    normalized = (format_value or "").lower()
    if "png" in normalized:
        return "image/png"
    return "image/jpeg"


def update_latest_webcam_frame(
    frame_bytes: bytes,
    format_value: str | None,
    width: int | None = None,
    height: int | None = None,
):
    # 캡처 스레드에서 들어온 최신 압축 이미지를 메모리 버퍼와 파일에 동시에 반영한다.
    # 파일은 backend/latest_webcam.jpg를 계속 덮어쓰므로 VSCode나 다른 도구에서도 최신 프레임을 확인할 수 있다.
    content_type = image_content_type(format_value)
    timestamp = now_iso()

    with webcam_frame_condition:
        latest_webcam_frame["bytes"] = frame_bytes
        latest_webcam_frame["content_type"] = content_type
        latest_webcam_frame["format"] = format_value
        latest_webcam_frame["updated_at"] = timestamp
        latest_webcam_frame["size"] = len(frame_bytes)
        latest_webcam_frame["width"] = width
        latest_webcam_frame["height"] = height
        latest_webcam_frame["sequence"] += 1
        webcam_frame_condition.notify_all()

    if content_type == "image/jpeg":
        WEBCAM_LATEST_FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEBCAM_LATEST_FRAME_PATH.write_bytes(frame_bytes)


def clear_latest_webcam_frame():
    with webcam_frame_condition:
        latest_webcam_frame["bytes"] = None
        latest_webcam_frame["content_type"] = "image/jpeg"
        latest_webcam_frame["format"] = None
        latest_webcam_frame["updated_at"] = None
        latest_webcam_frame["size"] = 0
        latest_webcam_frame["width"] = None
        latest_webcam_frame["height"] = None
        latest_webcam_frame["sequence"] += 1
        webcam_frame_condition.notify_all()


def parse_video_device(device: str):
    stripped = device.strip()
    if stripped.isdigit():
        return int(stripped)
    return stripped


class IncidentVideoRecorder:
    # YOLO bbox가 그려진 웹캠 프레임을 사건 단위 mp4 파일로 저장한다.
    # 파일명은 YYMMDD_HHMMSS.mp4 형식이며, 같은 초에 사건이 겹치면 뒤에 일련번호를 붙인다.
    def __init__(self, output_dir: Path, fps: float):
        self.output_dir = output_dir
        self.fps = max(1.0, fps)
        self.lock = threading.Lock()
        self.active = False
        self.path = None
        self.writer = None
        self.frame_size = None
        self.frame_count = 0
        self.started_at = None
        self.stopped_at = None
        self.error = None

    def _build_output_path(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename_stem = datetime.now().strftime("%y%m%d_%H%M%S")
        candidate = self.output_dir / f"{filename_stem}.mp4"
        suffix = 1

        while candidate.exists():
            candidate = self.output_dir / f"{filename_stem}_{suffix}.mp4"
            suffix += 1

        return candidate

    def start(self) -> str:
        with self.lock:
            if self.active and self.path:
                return str(self.path)

            self.active = True
            self.path = self._build_output_path()
            self.writer = None
            self.frame_size = None
            self.frame_count = 0
            self.started_at = now_iso()
            self.stopped_at = None
            self.error = None
            return str(self.path)

    def write(self, frame):
        with self.lock:
            if not self.active or self.path is None or frame is None:
                return

            try:
                import cv2

                height, width = frame.shape[:2]
                if width <= 0 or height <= 0:
                    return

                if self.writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    self.frame_size = (width, height)
                    self.writer = cv2.VideoWriter(str(self.path), fourcc, self.fps, self.frame_size)
                    if not self.writer.isOpened():
                        self.writer = None
                        raise RuntimeError(f"영상 파일을 열 수 없습니다: {self.path}")

                if self.frame_size and (width, height) != self.frame_size:
                    frame = cv2.resize(frame, self.frame_size)

                self.writer.write(frame)
                self.frame_count += 1
            except Exception as exc:
                self.error = str(exc)

    def stop(self) -> str | None:
        with self.lock:
            if not self.active:
                return str(self.path) if self.path else None

            if self.writer is not None:
                self.writer.release()
                self.writer = None

            self.active = False
            self.stopped_at = now_iso()
            return str(self.path) if self.path else None

    def status(self) -> Dict[str, Any]:
        with self.lock:
            path = str(self.path) if self.path else None
            return {
                "active": self.active,
                "path": path,
                "filename": Path(path).name if path else None,
                "frame_count": self.frame_count,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "fps": self.fps,
                "error": self.error,
                "exists": bool(path and Path(path).is_file()),
            }


incident_video_recorder = IncidentVideoRecorder(WEBCAM_RECORDING_DIR, WEBCAM_RECORDING_FPS)


def start_incident_video_recording():
    video_path = incident_video_recorder.start()
    state["report"]["video_path"] = video_path
    return video_path


def write_incident_video_frame(frame):
    incident_video_recorder.write(frame)


def stop_incident_video_recording():
    video_path = incident_video_recorder.stop()
    if video_path:
        state["report"]["video_path"] = video_path
    return video_path


class OpenCvWebcamCapture:
    # FastAPI 프로세스 안에서 USB 웹캠을 직접 읽는 캡처 루프이다.
    # OpenCV가 없거나 장치를 열 수 없어도 서버는 계속 실행되고, status API에 오류만 노출된다.
    def __init__(self, device: str):
        self.device = device
        self.thread = None
        self.cv2 = None
        self.capture = None
        self.error = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self):
        try:
            import cv2
        except Exception as exc:  # pragma: no cover - OpenCV 미설치 환경에서도 서버는 살아야 한다.
            raise RuntimeError(
                "OpenCV Python 패키지(cv2)를 import할 수 없습니다. "
                "backend 가상환경에서 `pip install -r requirements.txt`를 실행하세요."
            ) from exc

        self.cv2 = cv2
        self.capture = self._open_capture()

        if not self.capture or not self.capture.isOpened():
            raise RuntimeError(
                f"웹캠 장치 {self.device!r}를 열 수 없습니다. "
                "USB 연결, /dev/video* 경로, video 그룹 권한을 확인하세요."
            )

        if WEBCAM_FRAME_WIDTH > 0:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, WEBCAM_FRAME_WIDTH)
        if WEBCAM_FRAME_HEIGHT > 0:
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, WEBCAM_FRAME_HEIGHT)
        if WEBCAM_CAPTURE_FPS > 0:
            self.capture.set(cv2.CAP_PROP_FPS, WEBCAM_CAPTURE_FPS)

        self.thread = threading.Thread(target=self._capture_loop, name="farmguard-webcam-capture", daemon=True)
        self.thread.start()
        self._started = True

    def _open_capture(self):
        device = parse_video_device(self.device)
        backend = getattr(self.cv2, "CAP_V4L2", 0) if os.name == "posix" else 0
        capture = self.cv2.VideoCapture(device, backend) if backend else self.cv2.VideoCapture(device)
        if capture.isOpened():
            return capture

        capture.release()
        return self.cv2.VideoCapture(device)

    def _capture_loop(self):
        encode_options = [int(self.cv2.IMWRITE_JPEG_QUALITY), max(1, min(100, WEBCAM_JPEG_QUALITY))]
        frame_interval = 1 / max(1, WEBCAM_CAPTURE_FPS)

        while not self._stop_event.is_set() and not webcam_shutdown_event.is_set():
            started_at = time.monotonic()
            ok, frame = self.capture.read()

            if not ok or frame is None:
                self.error = "웹캠 프레임을 읽지 못했습니다."
                time.sleep(0.2)
                continue

            ok, encoded = self.cv2.imencode(".jpg", frame, encode_options)
            if not ok:
                self.error = "웹캠 프레임을 JPEG로 인코딩하지 못했습니다."
                time.sleep(0.2)
                continue

            self.error = None
            update_latest_webcam_frame(encoded.tobytes(), "jpeg", width, height)
            write_incident_video_frame(frame)

            elapsed = time.monotonic() - started_at
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

    def stop(self):
        if not self._started:
            return

        self._stop_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        if self.capture:
            self.capture.release()

        self._started = False


def load_yolo_webcam_tools():
    # backend를 ui/backend에서 실행해도 repo root의 yolo 패키지를 import할 수 있게 경로를 보강한다.
    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from yolo.yolo_webcam_usb_select import YoloWebcam, parse_camera_source

    return YoloWebcam, parse_camera_source


class YoloOpenCvWebcamCapture:
    # yolo/yolo_webcam_usb_select.py의 멀티프로세스 YOLO 웹캠 파이프라인을 FastAPI 스트림으로 연결한다.
    # 결과 프레임은 bbox가 그려진 annotated_frame이며, UI와 사건 녹화가 모두 이 프레임을 사용한다.
    def __init__(self, device: str):
        self.device = device
        self.thread = None
        self.cv2 = None
        self.yolo_webcam = None
        self.error = None
        self._stop_event = threading.Event()
        self._started = False
        self.camera_source = None
        self.detections = []
        self.inference_ms = None
        self.end_to_end_ms = None
        self.status_messages = []

    def start(self):
        try:
            import cv2
        except Exception as exc:  # pragma: no cover - OpenCV 미설치 환경에서도 서버는 살아야 한다.
            raise RuntimeError(
                "OpenCV Python 패키지(cv2)를 import할 수 없습니다. "
                "backend 가상환경에서 `pip install -r requirements.txt`를 실행하세요."
            ) from exc

        YoloWebcam, parse_camera_source = load_yolo_webcam_tools()
        self.cv2 = cv2
        self.camera_source = parse_camera_source(self.device)
        self.yolo_webcam = YoloWebcam(
            model_path=YOLO_MODEL_PATH,
            camera_source=self.camera_source,
            device=YOLO_DEVICE,
            width=WEBCAM_FRAME_WIDTH,
            height=WEBCAM_FRAME_HEIGHT,
            camera_fps=int(max(1, WEBCAM_CAPTURE_FPS)),
            image_size=YOLO_IMAGE_SIZE,
            confidence=YOLO_CONFIDENCE,
            iou=YOLO_IOU,
            use_half=YOLO_USE_HALF,
        )
        self.yolo_webcam.start()

        self.thread = threading.Thread(target=self._result_loop, name="farmguard-yolo-webcam", daemon=True)
        self.thread.start()
        self._started = True

    def _remember_status_messages(self):
        if not self.yolo_webcam:
            return

        for level, worker_name, message in self.yolo_webcam.read_status():
            status_message = {
                "level": level,
                "worker": worker_name,
                "message": message,
                "received_at": now_iso(),
            }
            self.status_messages.append(status_message)
            self.status_messages = self.status_messages[-20:]

            if level == "ERROR":
                self.error = f"{worker_name}: {message}"

    def _draw_runtime_overlay(self, frame, result: Dict[str, Any]):
        detections = result.get("detections") or []
        info_text = (
            f"frame={result.get('frame_id', '-')}  "
            f"det={len(detections)}  "
            f"inference={float(result.get('inference_ms') or 0):.1f}ms  "
            f"total={float(result.get('end_to_end_ms') or 0):.1f}ms"
        )
        self.cv2.putText(
            frame,
            info_text,
            (10, 30),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            self.cv2.LINE_AA,
        )
        return frame

    def _result_loop(self):
        encode_options = [int(self.cv2.IMWRITE_JPEG_QUALITY), max(1, min(100, WEBCAM_JPEG_QUALITY))]

        try:
            while not self._stop_event.is_set() and not webcam_shutdown_event.is_set():
                self._remember_status_messages()

                if self.yolo_webcam and not self.yolo_webcam.is_running():
                    if not self.error:
                        self.error = "YOLO 웹캠 워커가 중지됐습니다."
                    time.sleep(0.2)
                    continue

                result = self.yolo_webcam.read(timeout=0.1) if self.yolo_webcam else None
                if result is None:
                    continue

                frame = result["annotated_frame"]
                frame = self._draw_runtime_overlay(frame, result)
                self.detections = result.get("detections") or []
                self.inference_ms = result.get("inference_ms")
                self.end_to_end_ms = result.get("end_to_end_ms")

                ok, encoded = self.cv2.imencode(".jpg", frame, encode_options)
                if not ok:
                    self.error = "YOLO 처리 프레임을 JPEG로 인코딩하지 못했습니다."
                    time.sleep(0.2)
                    continue

                self.error = None
                height, width = frame.shape[:2]
                update_latest_webcam_frame(encoded.tobytes(), "jpeg", width, height)
                write_incident_video_frame(frame)
        except Exception as exc:
            self.error = str(exc)

    def status_payload(self):
        return {
            "mode": "yolo",
            "model_path": YOLO_MODEL_PATH,
            "yolo_device": YOLO_DEVICE,
            "camera_source": str(self.camera_source if self.camera_source is not None else self.device),
            "confidence": YOLO_CONFIDENCE,
            "iou": YOLO_IOU,
            "image_size": YOLO_IMAGE_SIZE,
            "detection_count": len(self.detections),
            "detections": self.detections,
            "inference_ms": self.inference_ms,
            "end_to_end_ms": self.end_to_end_ms,
            "status_messages": self.status_messages[-5:],
        }

    def stop(self):
        if not self._started:
            return

        self._stop_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        if self.yolo_webcam:
            self.yolo_webcam.stop()

        self._started = False


class SharedFrameFileWebcamCapture:
    # /dev/video*는 한 프로세스만 열 수 있어서, 이미 다른 프로세스(예: tower_world_detector.py)가
    # 카메라를 점유 중일 때는 그 프로세스가 남기는 최신 JPEG 파일을 읽어서 스트리밍한다.
    # device 문자열은 "file:<경로>" 형식이다.
    def __init__(self, device: str):
        self.device = device
        self.path = Path(device[len("file:"):])
        self.thread = None
        self.error = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self):
        self.thread = threading.Thread(
            target=self._poll_loop, name="farmguard-shared-frame-webcam", daemon=True,
        )
        self.thread.start()
        self._started = True

    def _poll_loop(self):
        import cv2
        import numpy as np

        interval = 1 / max(1, WEBCAM_CAPTURE_FPS)
        last_mtime = None

        while not self._stop_event.is_set() and not webcam_shutdown_event.is_set():
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                self.error = f"공유 프레임 파일을 찾을 수 없습니다: {self.path}"
                time.sleep(interval)
                continue

            if mtime == last_mtime:
                time.sleep(interval)
                continue

            try:
                data = self.path.read_bytes()
            except OSError as exc:
                self.error = str(exc)
                time.sleep(interval)
                continue

            if not data:
                time.sleep(interval)
                continue

            last_mtime = mtime
            self.error = None
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                height, width = frame.shape[:2]
                update_latest_webcam_frame(data, "jpeg", width, height)
            else:
                update_latest_webcam_frame(data, "jpeg")

            if frame is not None:
                write_incident_video_frame(frame)

            time.sleep(interval)

    def stop(self):
        if not self._started:
            return

        self._stop_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        self._started = False


def normalize_webcam_device(device: str) -> str:
    normalized = str(device or "").strip()
    if not normalized:
        raise ValueError("웹캠 장치 번호를 선택하세요.")
    return normalized


def list_webcam_device_options():
    options = []
    for index in range(max(1, WEBCAM_DEVICE_OPTION_COUNT)):
        path = Path(f"/dev/video{index}")
        options.append(
            {
                "value": str(index),
                "label": f"{index}번",
                "path": str(path),
                "available": path.exists(),
            }
        )
    if webcam_video_device not in {option["value"] for option in options}:
        underlying_path = (
            webcam_video_device[len("file:"):]
            if webcam_video_device.startswith("file:")
            else webcam_video_device
        )
        options.insert(
            0,
            {
                "value": webcam_video_device,
                "label": webcam_video_device,
                "path": underlying_path,
                "available": Path(underlying_path).exists(),
            },
        )
    return options


def start_webcam_capture():
    global webcam_capture, webcam_capture_error

    if not ENABLE_WEBCAM_CAPTURE:
        webcam_capture_error = "FARMGUARD_ENABLE_WEBCAM_CAPTURE=0 설정으로 웹캠 캡처가 비활성화됐습니다."
        return

    try:
        # 서버 시작 시 USB 웹캠을 바로 열고 캡처 스레드를 띄운다.
        # "file:<경로>"면 카메라를 직접 열지 않고, 다른 프로세스가 남긴 공유 프레임 파일을 읽는다.
        webcam_shutdown_event.clear()
        if webcam_video_device.startswith("file:"):
            capture_class = SharedFrameFileWebcamCapture
        else:
            capture_class = YoloOpenCvWebcamCapture if ENABLE_YOLO_WEBCAM else OpenCvWebcamCapture
        webcam_capture = capture_class(webcam_video_device)
        webcam_capture.start()
        webcam_capture_error = None
    except Exception as exc:
        webcam_capture = None
        webcam_capture_error = str(exc)


def stop_webcam_capture():
    global webcam_capture

    if webcam_capture:
        # 종료 시에는 스레드와 디바이스를 명시적으로 닫아 다음 실행을 깨끗하게 만든다.
        webcam_capture.stop()
        webcam_capture = None

    with webcam_frame_condition:
        webcam_shutdown_event.set()
        webcam_frame_condition.notify_all()


def change_webcam_device(device: str):
    global webcam_capture, webcam_capture_error, webcam_video_device

    next_device = normalize_webcam_device(device)

    with webcam_control_lock:
        # 장치 변경은 기존 캡처를 멈춘 뒤 새 장치를 다시 여는 순서로 처리한다.
        if webcam_capture:
            webcam_capture.stop()
            webcam_capture = None

        webcam_video_device = next_device
        webcam_capture_error = None
        clear_latest_webcam_frame()
        start_webcam_capture()

    return webcam_capture_status_payload()


def webcam_mjpeg_stream():
    # <img src=".../stream">에서 바로 볼 수 있는 multipart MJPEG 응답을 만든다.
    # 새 웹캠 캡처 프레임이 들어올 때마다 최신 JPEG를 한 파트씩 브라우저에 밀어준다.
    last_sequence = -1

    while not webcam_shutdown_event.is_set():
        with webcam_frame_condition:
            webcam_frame_condition.wait_for(
                lambda: (
                    webcam_shutdown_event.is_set()
                    or (
                        latest_webcam_frame["bytes"] is not None
                        and latest_webcam_frame["sequence"] != last_sequence
                    )
                ),
                timeout=2,
            )

            if webcam_shutdown_event.is_set():
                break

            if latest_webcam_frame["bytes"] is None:
                continue

            frame_bytes = latest_webcam_frame["bytes"]
            content_type = latest_webcam_frame["content_type"]
            last_sequence = latest_webcam_frame["sequence"]

        yield (
            b"--frame\r\n"
            + f"Content-Type: {content_type}\r\n".encode()
            + f"Content-Length: {len(frame_bytes)}\r\n".encode()
            + b"Cache-Control: no-cache\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )


def update_amr_camera_frame(camera_id: str, frame_bytes: bytes, format_value: str | None):
    # ROS 토픽에서 들어온 압축 프레임을 카메라별 버퍼에 저장한다.
    if camera_id not in amr_camera_frames:
        return

    content_type = image_content_type(format_value)
    timestamp = now_iso()
    frame_buffer = amr_camera_frames[camera_id]

    with amr_camera_conditions[camera_id]:
        frame_buffer["bytes"] = frame_bytes
        frame_buffer["content_type"] = content_type
        frame_buffer["format"] = format_value
        frame_buffer["updated_at"] = timestamp
        frame_buffer["size"] = len(frame_bytes)
        frame_buffer["sequence"] += 1
        amr_camera_conditions[camera_id].notify_all()


def amr_mjpeg_stream(camera_id: str):
    # AMR 카메라도 웹캠과 같은 multipart MJPEG 형식으로 브라우저에 전달한다.
    if camera_id not in amr_camera_frames:
        raise HTTPException(status_code=404, detail="unknown AMR camera")

    last_sequence = -1
    frame_buffer = amr_camera_frames[camera_id]
    condition = amr_camera_conditions[camera_id]

    while not amr_ros_shutdown_event.is_set():
        with condition:
            condition.wait_for(
                lambda: (
                    amr_ros_shutdown_event.is_set()
                    or (
                        frame_buffer["bytes"] is not None
                        and frame_buffer["sequence"] != last_sequence
                    )
                ),
                timeout=2,
            )

            if amr_ros_shutdown_event.is_set():
                break

            if frame_buffer["bytes"] is None:
                continue

            frame_bytes = frame_buffer["bytes"]
            content_type = frame_buffer["content_type"]
            last_sequence = frame_buffer["sequence"]

        yield (
            b"--frame\r\n"
            + f"Content-Type: {content_type}\r\n".encode()
            + f"Content-Length: {len(frame_bytes)}\r\n".encode()
            + b"Cache-Control: no-cache\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )


class RosAmrBridge:
    # ROS bridge는 AMR 카메라 토픽과 상태 토픽을 백엔드 프로세스 안에서 직접 구독한다.
    # 별도 rosbridge_server를 두지 않는 이유는 현재 규모에서는 Python 한 프로세스가 가장 단순하기 때문이다.
    def __init__(self, camera_config: Dict[str, Dict[str, str]], status_topic: str):
        self.camera_config = camera_config
        self.status_topic = status_topic
        self.thread = None
        self.node = None
        self.rclpy = None
        self._started = False
        self._owns_rclpy_context = False

    def start(self):
        try:
            import rclpy
            from sensor_msgs.msg import CompressedImage
            from std_msgs.msg import String
        except Exception as exc:  # pragma: no cover - ROS2 미설치 환경에서도 서버는 살아야 한다.
            raise RuntimeError(
                "ROS2 Python 패키지(rclpy, sensor_msgs, std_msgs)를 import할 수 없습니다. "
                "AMR 토픽 연동이 필요하면 ROS2 setup.bash를 source 한 뒤 백엔드를 실행하세요."
            ) from exc

        self.rclpy = rclpy

        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_rclpy_context = True

        self.node = rclpy.create_node("farmguard_amr_ros_bridge")

        for camera_id, config in self.camera_config.items():
            # 카메라별 CompressedImage 토픽을 같은 콜백 패턴으로 구독한다.
            self.node.create_subscription(
                CompressedImage,
                config["topic"],
                lambda message, current_id=camera_id: self._on_camera_image(current_id, message),
                10,
            )

        # 상태 토픽은 JSON 문자열 payload를 받아 시나리오 이벤트로 반영한다.
        self.node.create_subscription(String, self.status_topic, self._on_status, 10)

        self.thread = threading.Thread(target=self._spin, name="farmguard-amr-ros-spin", daemon=True)
        self.thread.start()
        self._started = True

    def _on_camera_image(self, camera_id: str, message):
        # 압축 프레임 바이트를 카메라별 최신 프레임 버퍼에 그대로 저장한다.
        update_amr_camera_frame(camera_id, bytes(message.data), getattr(message, "format", None))

    def _on_status(self, message):
        # status_event payload는 JSON 문자열이므로 파싱 후 보고서 이벤트로 변환한다.
        payload = parse_amr_status_message(getattr(message, "data", ""))
        apply_amr_status_payload(payload)

    def _spin(self):
        # ROS spin은 별도 스레드에서 돌려야 FastAPI 요청 처리와 충돌하지 않는다.
        while not amr_ros_shutdown_event.is_set():
            try:
                self.rclpy.spin_once(self.node, timeout_sec=0.2)
            except Exception:
                if amr_ros_shutdown_event.is_set():
                    break
                raise

    def stop(self):
        if not self._started:
            return

        # 종료 시에는 ROS node, spin thread, rclpy context를 순서대로 정리한다.
        amr_ros_shutdown_event.set()

        if self.thread:
            self.thread.join(timeout=2)

        if self.node:
            self.node.destroy_node()

        if self._owns_rclpy_context and self.rclpy and self.rclpy.ok():
            self.rclpy.shutdown()

        self._started = False


# AMR ROS bridge는 서버 시작 시 같이 올리고, 토픽 수신과 상태 반영을 담당한다.
def start_amr_ros_bridge():
    global amr_ros_bridge, amr_ros_error

    if not ENABLE_AMR_ROS_BRIDGE:
        amr_ros_error = "FARMGUARD_ENABLE_AMR_ROS_BRIDGE=0 설정으로 AMR ROS bridge가 비활성화됐습니다."
        return

    try:
        # 서버 시작 시 ROS2 환경이 준비돼 있으면 카메라/상태 브리지를 함께 올린다.
        amr_ros_shutdown_event.clear()
        amr_ros_bridge = RosAmrBridge(AMR_CAMERA_CONFIG, AMR_STATUS_TOPIC)
        amr_ros_bridge.start()
        amr_ros_error = None
    except Exception as exc:
        amr_ros_bridge = None
        amr_ros_error = str(exc)


# 종료 시에는 브리지를 멈추고 대기 중인 stream generator를 깨운다.
def stop_amr_ros_bridge():
    if amr_ros_bridge:
        # 브리지 종료 후 condition을 깨워 stream generator가 빠져나가게 한다.
        amr_ros_bridge.stop()

    amr_ros_shutdown_event.set()

    for condition in amr_camera_conditions.values():
        with condition:
            condition.notify_all()


init_db()


@app.on_event("startup")
def on_startup():
    # 서버 시작과 동시에 웹캠 캡처와 ROS 브리지를 함께 준비한다.
    start_webcam_capture()
    start_amr_ros_bridge()


@app.on_event("shutdown")
def on_shutdown():
    # 종료 시에는 카메라와 ROS 리소스를 모두 정리한다.
    stop_incident_video_recording()
    stop_amr_ros_bridge()
    stop_webcam_capture()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/login")
def login(payload: LoginRequest):
    # 시연용 로그인은 admin/1234만 허용하고 demo-token을 반환한다.
    if payload.username == "admin" and payload.password == "1234":
        return {"success": True, "token": "demo-token"}
    return {"success": False, "message": "invalid credentials"}


@app.get("/api/status")
def get_status():
    # 대시보드와 카드 UI는 이 live snapshot 전체를 읽는다.
    return state


@app.get("/api/report")
def get_report():
    # 통합 보고서 화면은 보고서 부분만 따로 폴링한다.
    return state["report"]


@app.get("/api/reports")
def list_saved_reports():
    # 저장된 보고서 목록은 최신 저장 건이 위로 오도록 정렬한다.
    # created_at이 같은 경우 id DESC를 추가해 항상 안정적인 순서를 만든다.
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM saved_reports ORDER BY created_at DESC, id DESC",
        ).fetchall()
    return [row_to_report(row) for row in rows]


@app.post("/api/reports")
def save_report(payload: ReportSaveRequest):
    # 저장 버튼은 현재 화면의 report snapshot을 DB에 남긴다.
    return save_report_to_db(payload.report or state["report"], payload.title)


@app.get("/api/reports/{report_id}")
def get_saved_report(report_id: int):
    # 저장된 단일 보고서를 상세 화면에서 보여주기 위한 API이다.
    return row_to_report(fetch_saved_report_row(report_id))


@app.get("/api/reports/{report_id}/video")
def get_saved_report_video(report_id: int, request: Request):
    # DB에는 로컬 파일 경로를 저장하고, 브라우저 재생은 Range 지원 스트림으로 중계한다.
    saved_report = row_to_report(fetch_saved_report_row(report_id))
    video_file = ensure_browser_playable_video(resolve_report_video_file(saved_report.get("video_path")))
    file_size = video_file.stat().st_size
    requested_range = parse_range_header(request.headers.get("range"), file_size)
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-cache",
        "Content-Disposition": f'inline; filename="{video_file.name}"',
    }

    if requested_range:
        start, end = requested_range
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            iter_file_range(video_file, start, end),
            status_code=206,
            media_type="video/mp4",
            headers=headers,
        )

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        iter_file_range(video_file, 0, file_size - 1),
        media_type="video/mp4",
        headers=headers,
    )


@app.patch("/api/reports/{report_id}/title")
def rename_saved_report(report_id: int, payload: ReportTitleUpdateRequest):
    # 제목 수정은 보고서 본문이 아니라 메타데이터만 바꾸는 작업이다.
    return update_saved_report_title(report_id, payload.title)


@app.post("/api/reports/{report_id}/restore")
def restore_saved_report(report_id: int):
    # 선택한 저장 보고서를 현재 live state에 반영한다.
    # 이후 /api/report를 폴링하는 통합 보고서 화면도 복원된 값을 보게 된다.
    saved_report = row_to_report(fetch_saved_report_row(report_id))
    apply_report_to_live_state(saved_report["report"])
    return {
        "restored": True,
        "saved_report": saved_report,
        "report": state["report"],
    }


@app.post("/api/simulate/reset")
def reset_scenario():
    # mock 시나리오를 처음 상태로 되돌려 다시 재현할 수 있게 한다.
    stop_incident_video_recording()
    state["webcam"] = dict(INITIAL_STATE["webcam"])
    state["amr"] = dict(INITIAL_STATE["amr"])
    state["report"] = dict(INITIAL_STATE["report"])
    clear_auto_save_tracking()
    return state


@app.post("/api/simulate/{event_name}")
def simulate_event(event_name: str):
    # mock 이벤트 버튼용 엔드포인트다. 실제 운영 환경에서는 ROS 이벤트가 이 자리를 대체한다.
    normalized_event = normalize_scenario_event(event_name)
    if not normalized_event:
        raise HTTPException(status_code=400, detail="unknown scenario event")

    return apply_scenario_event(normalized_event)


@app.get("/api/cameras/{camera_id}/snapshot")
def camera_snapshot(camera_id: str):
    # 현재 UI는 stream을 사용하지만, snapshot은 가벼운 점검/호환용 응답으로 남겨둔다.
    names = {
        "webcam": "WebCam - Field Boundary",
        "amr1": "AMR1 Front Camera",
        "amr2": "AMR2 Front Camera",
    }
    label = names.get(camera_id, camera_id)
    current_time = datetime.now().strftime("%H:%M:%S")

    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600">
      <defs>
        <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stop-color="#111827"/>
          <stop offset="1" stop-color="#1f2937"/>
        </linearGradient>
      </defs>
      <rect width="960" height="600" fill="url(#bg)"/>
      <rect x="56" y="70" width="848" height="430" rx="26" fill="#0b1220" stroke="#334155" stroke-width="3"/>
      <line x1="120" y1="390" x2="840" y2="390" stroke="#facc15" stroke-width="8" stroke-dasharray="22 14"/>
      <text x="80" y="118" fill="#93c5fd" font-size="34" font-family="Arial" font-weight="700">{label}</text>
      <text x="80" y="166" fill="#cbd5e1" font-size="24" font-family="Arial">Mock camera frame · {current_time}</text>
      <text x="116" y="372" fill="#fde68a" font-size="22" font-family="Arial" font-weight="700">Virtual boundary line</text>
      <circle cx="760" cy="155" r="14" fill="#ef4444"/>
      <text x="785" y="164" fill="#ffffff" font-size="22" font-family="Arial" font-weight="700">LIVE</text>
    </svg>
    """
    return Response(content=svg, media_type="image/svg+xml")


def amr_camera_status_payload(camera_id: str):
    # AMR 카메라의 브리지 상태와 최신 프레임 정보를 화면 상태 카드에 넘긴다.
    if camera_id not in AMR_CAMERA_CONFIG:
        raise HTTPException(status_code=404, detail="unknown AMR camera")

    frame_buffer = amr_camera_frames[camera_id]
    return {
        "camera_id": camera_id,
        "topic": AMR_CAMERA_CONFIG[camera_id]["topic"],
        "enabled": ENABLE_AMR_ROS_BRIDGE,
        "bridge_running": amr_ros_bridge is not None and amr_ros_error is None,
        "error": amr_ros_error,
        "latest_frame_at": frame_buffer["updated_at"],
        "latest_frame_size": frame_buffer["size"],
        "latest_frame_format": frame_buffer["format"],
        "latest_frame_content_type": frame_buffer["content_type"],
    }


@app.get("/api/cameras/{camera_id}/frame")
def amr_camera_latest_frame(camera_id: str):
    if camera_id == "webcam":
        return webcam_latest_frame()

    if camera_id not in AMR_CAMERA_CONFIG:
        raise HTTPException(status_code=404, detail="unknown AMR camera")

    frame_buffer = amr_camera_frames[camera_id]
    if frame_buffer["bytes"] is None:
        raise HTTPException(status_code=503, detail=f"{camera_id} frame is not available yet")

    return Response(
        content=frame_buffer["bytes"],
        media_type=frame_buffer["content_type"],
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
    )


@app.get("/api/cameras/{camera_id}/stream")
def amr_camera_stream(camera_id: str):
    if camera_id == "webcam":
        return webcam_stream()

    if camera_id not in AMR_CAMERA_CONFIG:
        raise HTTPException(status_code=404, detail="unknown AMR camera")

    # AMR도 웹캠과 같은 방식으로 MJPEG를 내보내면 프론트는 동일한 렌더링 방식만 쓰면 된다.
    return StreamingResponse(
        amr_mjpeg_stream(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/cameras/{camera_id}/ros-status")
def amr_camera_ros_status(camera_id: str):
    if camera_id == "webcam":
        return webcam_capture_status_payload()

    return amr_camera_status_payload(camera_id)


@app.get("/api/amr/ros-status")
def amr_ros_status():
    # 운영/디버그 화면이 전체 브리지 상태를 한 번에 확인하도록 제공하는 진단 API다.
    return {
        "enabled": ENABLE_AMR_ROS_BRIDGE,
        "bridge_running": amr_ros_bridge is not None and amr_ros_error is None,
        "error": amr_ros_error,
        "status_topic": AMR_STATUS_TOPIC,
        "camera_topics": {
            camera_id: config["topic"]
            for camera_id, config in AMR_CAMERA_CONFIG.items()
        },
        "latest_camera_frames": {
            camera_id: {
                "latest_frame_at": frame["updated_at"],
                "latest_frame_size": frame["size"],
                "latest_frame_format": frame["format"],
            }
            for camera_id, frame in amr_camera_frames.items()
        },
        "amr": state["amr"],
    }


@app.get("/api/cameras/webcam/frame")
def webcam_latest_frame():
    # 최신 OpenCV 캡처 프레임 1장을 JPEG 응답으로 반환한다.
    # 단일 프레임 진단/미리보기용이며 실시간 관제 화면은 /stream endpoint를 사용한다.
    with webcam_frame_condition:
        frame_bytes = latest_webcam_frame["bytes"]
        content_type = latest_webcam_frame["content_type"]

    if frame_bytes is None:
        raise HTTPException(status_code=503, detail="webcam frame is not available yet")

    return Response(
        content=frame_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
    )


@app.get("/api/cameras/webcam/stream")
def webcam_stream():
    # <img> 태그가 바로 재생할 수 있는 MJPEG 스트림이다.
    # OpenCV 캡처 스레드의 최신 프레임이 들어올 때마다 multipart frame을 전송한다.
    return StreamingResponse(
        webcam_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


def webcam_capture_status_payload():
    # 웹캠 selector와 상태 배지를 위한 진단 응답이다.
    with webcam_frame_condition:
        capture_error = webcam_capture_error or (webcam_capture.error if webcam_capture else None)
        frame_info = {
            "device": webcam_video_device,
            "enabled": ENABLE_WEBCAM_CAPTURE,
            "capture_running": webcam_capture is not None and capture_error is None,
            "error": capture_error,
            "mode": "yolo" if ENABLE_YOLO_WEBCAM else "opencv",
            "latest_frame_at": latest_webcam_frame["updated_at"],
            "latest_frame_size": latest_webcam_frame["size"],
            "latest_frame_width": latest_webcam_frame["width"],
            "latest_frame_height": latest_webcam_frame["height"],
            "latest_frame_format": latest_webcam_frame["format"],
            "latest_frame_content_type": latest_webcam_frame["content_type"],
            "saved_frame_path": str(WEBCAM_LATEST_FRAME_PATH),
            "width": WEBCAM_FRAME_WIDTH,
            "height": WEBCAM_FRAME_HEIGHT,
            "fps": WEBCAM_CAPTURE_FPS,
            "recording": incident_video_recorder.status(),
        }
    if webcam_capture and hasattr(webcam_capture, "status_payload"):
        frame_info.update(webcam_capture.status_payload())
    return frame_info


@app.get("/api/cameras/webcam/capture-status")
def webcam_capture_status():
    return webcam_capture_status_payload()


@app.get("/api/cameras/webcam/device-options")
def webcam_device_options():
    return {
        "selected": webcam_video_device,
        "devices": list_webcam_device_options(),
    }


@app.post("/api/cameras/webcam/device")
def set_webcam_device(payload: WebcamDeviceRequest):
    try:
        return change_webcam_device(payload.device)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/cameras/webcam/ros-status")
def webcam_ros_status():
    # 이전 프론트/문서와의 호환용 alias이다. 웹캠은 이제 ROS 토픽이 아니라 OpenCV 캡처를 사용한다.
    return webcam_capture_status_payload()


@app.get("/", include_in_schema=False)
def frontend_root():
    # 루트 경로는 프론트엔드 SPA 진입점으로 돌린다.
    if not FRONTEND_INDEX_PATH.exists():
        raise HTTPException(status_code=404, detail="frontend build not found")
    return FileResponse(FRONTEND_INDEX_PATH)


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa_fallback(full_path: str):
    # API와 기존 FastAPI 내장 경로가 아닌 요청은 프론트엔드 SPA로 보낸다.
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")

    if not FRONTEND_DIST_DIR.exists() or not FRONTEND_INDEX_PATH.exists():
        raise HTTPException(status_code=404, detail="frontend build not found")

    candidate_path = FRONTEND_DIST_DIR / full_path
    if candidate_path.is_file():
        return FileResponse(candidate_path)

    if candidate_path.suffix:
        raise HTTPException(status_code=404, detail="not found")

    return FileResponse(FRONTEND_INDEX_PATH)
