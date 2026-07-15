#!/usr/bin/env python3
# =====================================================================
# [전체 기능 요약]
# 관제탑(천장/고정 시점) 웹캠 영상에서 YOLO로 대상(animal/kitty)을 탐지하고,
# ByteTrack으로 프레임 간 동일 개체를 추적(ID 유지)한 뒤,
# 호모그래피 행렬로 "픽셀 좌표 -> map 좌표(m)"를 변환하여 발행하는
# 시스템의 '눈(전역 인지)' 역할 노드.
# 로봇들은 이 노드가 주는 map 좌표만 믿고 움직인다 (온보드 탐지 없음).
#
# [발행 토픽 - Publish]
#   /world/animal_pose  (geometry_msgs/PoseStamped, frame_id='map', ~10Hz)
#       - 대상의 map 좌표. designator가 구독하여 플랭킹 goal 계산에 사용.
#   /undock_signal      (std_msgs/Bool, LATCHED)
#       - 최초 '확정' 탐지 시 True. robot_controller 2대가 구독하여
#         미션 시작(undock) 트리거로 사용. 0.5s 간격 10회 반복 발행.
#   /status_event       (std_msgs/String, JSON)
#       - TOWER_DETECTED / TOWER_LOST 이벤트 로그. 모니터링용.
#
# [구독 토픽 - Subscribe]
#   없음 (입력은 ROS 토픽이 아니라 OpenCV 웹캠 캡처).
#
# [외부 참조 - 파일/모델]
#   best_final.pt          : 커스텀 학습한 YOLO 가중치 (TARGET_CLASS 탐지)
#   ground_homography.npy  : calibrate_homography.py로 사전 계산한 3x3
#                            픽셀->map 변환 행렬 (지면 평면 가정)
#   bytetrack.yaml         : ultralytics 내장 ByteTrack 추적기 설정
#
# [데이터 흐름]
#   웹캠 프레임 -> YOLO+ByteTrack -> 락온 트랙 선택 -> bbox 하단중앙(발끝)
#   -> 호모그래피 변환 -> /world/animal_pose 발행
#   + 연속프레임 디바운스 -> 최초 확정 시 /undock_signal 발행
# =====================================================================
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'   # 사용할 GPU를 0번으로 고정

import json
from datetime import datetime

import cv2
cv2.setNumThreads(4)   # OpenCV 스레드 제한 (YOLO GPU 추론과 CPU 경합 방지)
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from std_msgs.msg import Bool, String
from ultralytics import YOLO


# =========================================================
# 설정
# =========================================================

CAMERA_INDEX = 2                     # /dev/video2 (관제탑 웹캠)

# 실행 시 CWD(작업 디렉토리)에 상관없이 항상 이 스크립트가 있는 디렉토리를
# 기준으로 모델/호모그래피 파일을 찾음 (ros2 run 등 CWD가 달라지는 실행 방식 대응).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_PKG_DIR, 'best.pt')               # 커스텀 YOLO 가중치
HOMOGRAPHY_PATH = os.path.join(_PKG_DIR, 'ground_homography.npy')  # 사전 캘리브레이션 결과

TARGET_CLASS = 'kitty'               # 추적 대상 클래스명 (모델 학습 시 라벨)
CONF_THRESHOLD = 0.30                # 낮게 설정: 모션블러로 conf가 떨어져도
                                     # 탐지 유지 (오탐은 추적+디바운스로 거름)
TRACKER_CONFIG = 'bytetrack.yaml'    # ByteTrack: 저신뢰 박스도 연관에 활용

# GPU 추론 설정
DEVICE = 0          # GPU 0번 사용. CPU로 강제하려면 'cpu'
INFER_IMGSZ = 416   # 추론 입력 크기 축소 -> 지연 감소 (실시간성 우선)

# 락온한 트랙을 이 프레임 수만큼 연속으로 놓치면 잠금 해제
# 10Hz 기준 15프레임 = 1.5초. 순간 가림으로 ID를 갈아타지 않게 하는 유예.
TRACK_UNLOCK_MISS_FRAMES = 15

# 탐지 확정/해제에 필요한 연속 프레임 수 (한 프레임 노이즈로 오작동 방지)
DETECTION_CONFIRM_FRAMES = 3   # 0.3초 연속 탐지 -> 확정 (undock 오발동 방지)
DETECTION_CLEAR_FRAMES = 5     # 0.5초 연속 미탐 -> 소실 (순간 가림 무시)

WORLD_POSE_TOPIC = '/world/animal_pose'
START_TOPIC = '/undock_signal'
STATUS_EVENT_TOPIC = '/status_event'
ROBOT_ID = 'TOWER'

PUBLISH_RATE_HZ = 10.0   # 프레임 처리(=발행) 주기. 추론 지연과 균형점.

# /undock_signal 구독자가 discovery 타이밍상 최초 발행분을 놓치는 경우 대비:
# 1회가 아니라 0.5초 간격 10회 반복 발행 (멀티PC DDS discovery 지연 대응)
START_SIGNAL_REPEAT_COUNT = 10
START_SIGNAL_REPEAT_INTERVAL_SEC = 0.5

# TRANSIENT_LOCAL(latched): 발행 후에 뜬(늦게 구독한) 노드도 마지막 값을
# 즉시 수신. 구독자 쪽 durability도 반드시 동일해야 매칭됨 (불일치 시 무수신).
LATCHED_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)


def now_str():
    """상태 이벤트 타임스탬프용 현재 시각 문자열."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class TowerWorldDetector(Node):
    def __init__(self):
        """초기화 순서: YOLO 로드+GPU 예열 -> 호모그래피 로드 -> 웹캠 오픈
        -> 퍼블리셔 3개 생성 -> 10Hz 처리 타이머 시작.
        [발행 생성] /world/animal_pose(depth10), /undock_signal(latched),
                    /status_event(depth10)
        [참조] MODEL_PATH, HOMOGRAPHY_PATH, CAMERA_INDEX"""
        super().__init__('tower_world_detector')

        self.model = YOLO(MODEL_PATH)
        if DEVICE != 'cpu':
            self.model.to(f'cuda:{DEVICE}')
            # 더미 추론 1회 = GPU 예열. 첫 실제 프레임에서 발생하는
            # CUDA 초기화/커널 컴파일 지연 스파이크(수 초)를 제거.
            _dummy = np.zeros((INFER_IMGSZ, INFER_IMGSZ, 3), dtype=np.uint8)
            self.model.predict(
                _dummy, device=DEVICE, imgsz=INFER_IMGSZ, verbose=False,
            )
            self.get_logger().info(f'YOLO GPU(cuda:{DEVICE}) 예열 완료')

        try:
            # 3x3 호모그래피 행렬: 지면 평면 위 점에 한해
            # 픽셀(u,v) -> map(x,y) 사영 변환
            self.H = np.load(HOMOGRAPHY_PATH)
            self.get_logger().info(f'호모그래피 로드 완료: {HOMOGRAPHY_PATH}')
        except FileNotFoundError:
            self.get_logger().error(
                f'{HOMOGRAPHY_PATH} 를 찾을 수 없습니다. '
                f'calibrate_homography.py 를 먼저 실행하세요.'
            )
            raise

        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self.cap.isOpened():
            self.get_logger().error(f'카메라 {CAMERA_INDEX}번을 열 수 없습니다.')
            raise RuntimeError('camera open failed')

        # --- 트랙 락온 상태 ---
        self.locked_track_id = None   # 현재 잠근 ByteTrack ID (None=미잠금)
        self.track_miss_count = 0     # 락온 트랙 연속 미발견 프레임 수

        # --- 탐지 확정 디바운스 상태 ---
        self.confirm_count = 0        # 연속 탐지 프레임 수
        self.miss_count = 0           # 연속 미탐 프레임 수
        self.detected_state = False   # 확정 탐지 상태 (이벤트 발행 기준)
        self.start_sent = False       # undock 신호를 이미 시작했는지 (1회성)
        self.start_repeat_remaining = 0
        self.start_repeat_timer = None

        self.world_pose_pub = self.create_publisher(
            PoseStamped, WORLD_POSE_TOPIC, 10,
        )
        self.start_pub = self.create_publisher(Bool, START_TOPIC, LATCHED_QOS)
        self.status_event_pub = self.create_publisher(
            String, STATUS_EVENT_TOPIC, 10,
        )

        # 10Hz 메인 루프 (캡처->추론->변환->발행이 전부 이 타이머에서 수행)
        self.timer = self.create_timer(
            1.0 / PUBLISH_RATE_HZ, self.process_frame,
        )

        self.get_logger().info('관제탑 world detector 가동 완료')
        self.get_logger().info(f'world pose 발행 토픽: {WORLD_POSE_TOPIC}')

    def _publish_start_signal(self):
        """[발행] /undock_signal=True 1회 발행 후 남은 반복 횟수 차감.
        [호출] 최초 확정 탐지 시 update_detection_state()가 직접 1회 +
               0.5s 반복 타이머(start_repeat_timer)가 나머지 호출.
        반복이 끝나면 스스로 타이머를 cancel한다.
        (반복 발행 = 멀티PC에서 늦게 discovery된 구독자 보호)"""
        start_msg = Bool()
        start_msg.data = True
        self.start_pub.publish(start_msg)
        self.start_repeat_remaining -= 1
        self.get_logger().info(
            f'/undock_signal 발행 (남은 반복: {self.start_repeat_remaining})'
        )

        if self.start_repeat_remaining <= 0 and self.start_repeat_timer is not None:
            self.start_repeat_timer.cancel()
            self.start_repeat_timer = None

    def publish_status_event(self, event, state):
        """[발행] /status_event 로 JSON 이벤트(robot_id/event/state/timestamp).
        [호출] update_detection_state()에서 TOWER_DETECTED/TOWER_LOST 시.
        모니터링/로그 수집용이며 제어 로직에는 영향 없음."""
        msg = String()
        msg.data = json.dumps({
            'robot_id': ROBOT_ID,
            'event': event,
            'state': state,
            'timestamp': now_str(),
        }, ensure_ascii=False)
        self.status_event_pub.publish(msg)
        self.get_logger().warn(f'{STATUS_EVENT_TOPIC}: {msg.data}')

    def pixel_to_world(self, u, v):
        """[역할] 호모그래피 H로 픽셀(u,v) -> map 평면(x,y) 사영 변환.
        동차좌표 [u,v,1]에 H를 곱한 뒤 w로 나눠 정규화(원근 보정).
        [전제] (u,v)가 '지면 위의 점'일 때만 유효 -> 호출부에서 반드시
        bbox 하단 중앙(발끝)을 넣어야 함. [호출] process_frame()"""
        pt = np.array([u, v, 1.0])
        world = self.H @ pt
        world /= world[2]
        return float(world[0]), float(world[1])

    def detect_and_track(self, frame):
        """[역할] YOLO+ByteTrack 추론 -> TARGET_CLASS 후보 수집 ->
        트랙 ID '락온' 정책으로 1개 후보 선택/유지.
        락온 정책:
          - 미잠금 상태: 최고 confidence 후보의 트랙 ID를 잠금
          - 잠금 상태: 같은 ID가 보이면 그 후보만 반환 (다른 후보 무시
            -> 오탐/다른 개체로 타겟이 튀는 것 방지)
          - 잠금 ID를 15프레임(1.5s) 연속 못 찾으면 잠금 해제 -> 재획득
        [반환] {'track_id', 'bbox', 'conf'} 또는 None
        [호출] process_frame() 매 프레임. [참조] self.model, TRACKER_CONFIG"""
        result = self.model.track(
            frame,
            conf=CONF_THRESHOLD,
            persist=True,            # 프레임 간 트랙 상태 유지 (ID 지속)
            tracker=TRACKER_CONFIG,  # ByteTrack
            device='cuda:0',
            imgsz=INFER_IMGSZ,
            verbose=False,
        )[0]

        candidates = []

        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls[0].item())
                name = str(result.names[class_id])

                if name.lower() != TARGET_CLASS.lower():
                    continue          # 대상 클래스만
                if box.id is None:
                    continue          # 트랙 ID 미부여 박스(연관 실패)는 제외

                track_id = int(box.id[0].item())
                confidence = float(box.conf[0].item())
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

                candidates.append({
                    'track_id': track_id,
                    'bbox': tuple(map(int, (x1, y1, x2, y2))),
                    'conf': confidence,
                })

        if not candidates:
            # 후보 자체가 없음 -> 미스 카운트 증가, 한도 초과 시 잠금 해제
            self.track_miss_count += 1
            if self.track_miss_count >= TRACK_UNLOCK_MISS_FRAMES:
                if self.locked_track_id is not None:
                    self.get_logger().warn(
                        f'트랙 ID {self.locked_track_id} 놓침. 잠금 해제.'
                    )
                self.locked_track_id = None
                self.track_miss_count = 0
            return None

        if self.locked_track_id is None:
            # 최초 락온: 최고 confidence 후보 선택
            selected = max(candidates, key=lambda item: item['conf'])
            self.locked_track_id = selected['track_id']
            self.track_miss_count = 0
            self.get_logger().warn(f'타겟 락온: ID {self.locked_track_id}')
            return selected

        for candidate in candidates:
            if candidate['track_id'] == self.locked_track_id:
                self.track_miss_count = 0
                return candidate      # 잠근 ID 유지

        # 후보는 있으나 잠근 ID가 아님 (다른 개체/오탐만 보임)
        self.track_miss_count += 1
        if self.track_miss_count >= TRACK_UNLOCK_MISS_FRAMES:
            self.get_logger().warn(
                f'트랙 ID {self.locked_track_id} 를 '
                f'{TRACK_UNLOCK_MISS_FRAMES}프레임 연속 못 찾음. 잠금 해제.'
            )
            self.locked_track_id = None
            self.track_miss_count = 0

        return None

    def update_detection_state(self, valid):
        """[역할] 연속 프레임 카운트 디바운스로 '확정 탐지' 상태 천이 판정.
          - 미확정 -> 3프레임 연속 탐지 -> 확정: TOWER_DETECTED 이벤트 +
            (최초 1회) /undock_signal 반복 발행 시작 = 미션 트리거
          - 확정 -> 5프레임 연속 미탐 -> 소실: TOWER_LOST 이벤트
        [발행] /status_event, /undock_signal(간접, _publish_start_signal)
        [호출] process_frame() 매 프레임 마지막에."""
        if valid:
            self.confirm_count += 1
            self.miss_count = 0

            if not self.detected_state and self.confirm_count >= DETECTION_CONFIRM_FRAMES:
                self.detected_state = True
                self.publish_status_event('TOWER_DETECTED', '감지')

                if not self.start_sent:
                    # 미션 시작 신호는 전체 런에서 딱 1번만 트리거
                    self.start_sent = True
                    self.start_repeat_remaining = START_SIGNAL_REPEAT_COUNT
                    self.get_logger().warn(
                        f'최초 확정 탐지. undock 신호 발행 시작 '
                        f'({START_SIGNAL_REPEAT_COUNT}회, '
                        f'{START_SIGNAL_REPEAT_INTERVAL_SEC}s 간격 반복).'
                    )
                    self._publish_start_signal()
                    self.start_repeat_timer = self.create_timer(
                        START_SIGNAL_REPEAT_INTERVAL_SEC,
                        self._publish_start_signal,
                    )
        else:
            self.confirm_count = 0
            self.miss_count += 1

            if self.detected_state and self.miss_count >= DETECTION_CLEAR_FRAMES:
                self.detected_state = False
                self.publish_status_event('TOWER_LOST', '소실')

    def process_frame(self):
        """[역할] 10Hz 메인 루프. 프레임 캡처 -> detect_and_track ->
        발끝(bbox 하단 중앙) 픽셀을 pixel_to_world로 변환 ->
        /world/animal_pose 발행 -> 디바운스 상태 갱신 -> 디버그 창 표시.
        [발행] /world/animal_pose (탐지된 프레임에만)
        [핵심] foot point = ((x1+x2)/2, y2). 중심점을 쓰면 몸통 높이가
        지면 평면 가정을 깨서 변환 좌표가 카메라 반대쪽으로 밀림."""
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().error('웹캠 프레임을 읽을 수 없습니다.')
            return

        detection = self.detect_and_track(frame)
        valid = detection is not None

        if valid:
            x1, y1, x2, y2 = detection['bbox']

            # bbox 하단 중앙 = 발이 지면에 닿는 지점.
            # 중심점(center)을 쓰면 몸통 높이 때문에 호모그래피 가정이 깨져
            # 오차가 커지므로 반드시 하단을 써야 함.
            foot_u = int((x1 + x2) / 2)
            foot_v = int(y2)

            world_x, world_y = self.pixel_to_world(foot_u, foot_v)

            # map 프레임 기준 pose로 발행 (orientation은 의미 없음 -> 항등)
            pose_msg = PoseStamped()
            pose_msg.header.frame_id = 'map'
            pose_msg.header.stamp = self.get_clock().now().to_msg()
            pose_msg.pose.position.x = world_x
            pose_msg.pose.position.y = world_y
            pose_msg.pose.position.z = 0.0
            pose_msg.pose.orientation.w = 1.0

            self.world_pose_pub.publish(pose_msg)

            # ---- 디버그 시각화 (제어와 무관, 운영 확인용) ----
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.circle(frame, (foot_u, foot_v), 5, (0, 255, 255), -1)

            label_bbox = (
                f'ID:{detection["track_id"]} '
                f'bbox=({x1},{y1})-({x2},{y2})'
            )
            label_world = (
                f'foot=({foot_u},{foot_v})px  '
                f'map=({world_x:.2f},{world_y:.2f})m'
            )

            cv2.putText(
                frame, label_bbox,
                (x1, max(20, y1 - 30)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2,
            )
            cv2.putText(
                frame, label_world,
                (x1, max(40, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2,
            )

        self.update_detection_state(valid)

        cv2.imshow('tower world detector', frame)
        cv2.waitKey(1)


def main():
    rclpy.init()
    node = TowerWorldDetector()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cap.release()
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
