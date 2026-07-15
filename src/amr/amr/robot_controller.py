#!/usr/bin/env python3
"""
robot_controller.py (실행자)

designator.py 가 발행하는 /<ns>/flank_goal 을 받아 그대로
navigate_to_pose 에 전달하고, undock / 도킹 복귀(Dock)를 담당하는
로봇 1대 전용 노드. goal 좌표 계산은 하지 않는다.
undock/nav/dock 콜백과 백오프는 herding_coordinator_flangking.py 에서
그대로 이식했다.

SAFE_STOP 재출발 개선:
    designator가 발행하는 /<ns>/avoid_goal(PVO 조정 좌표, LOW에게만
    발행)을 저장해 두었다가, SAFE_STOP 해제 시 avoid_goal이 있고
    원래 flank_goal과 좌표가 다르면 그 회피 지점으로 먼저 이동
    (AVOIDING 상태)한 뒤, 도착 후 원래 flank_goal로 복귀한다.
    avoid_goal이 없으면(HIGH이거나 회피 미발행) 기존과 동일하게
    원래 goal로 바로 재출발한다.

주의: 두 PC에서 동시에 실행하므로 노드 이름 충돌 방지를 위해
반드시 -r __node:= 로 로봇별 이름을 다르게 지정할 것.

실행 예 (PC1, robot8):
    python3 robot_controller.py --ros-args \
        -r __node:=robot_controller_robot8 \
        -p robot_namespace:=robot8 -p peer_namespace:=robot11 \
        -p dock_x:=0.024 -p dock_y:=-4.6 -p dock_yaw:=-1.39633

실행 예 (PC2, robot11):
    python3 robot_controller.py --ros-args \
        -r __node:=robot_controller_robot11 \
        -p robot_namespace:=robot11 -p peer_namespace:=robot8 \
        -p dock_x:=-0.343 -p dock_y:=-0.0 -p dock_yaw:=0.0
"""
# =====================================================================
# [전체 기능 요약] robot_controller.py (실행자 = 로봇 1대 전용 '손발' 노드)
# designator가 계산한 goal을 받아 Nav2에 그대로 전달하고,
# 미션 시작(undock) / 종료 후 도킹 복귀(nav->dock)를 담당하는
# 상태머신 노드. goal 좌표 계산은 하지 않는다(판단은 designator).
# 두 PC에서 각각 1개씩 실행 (robot8용 / robot11용, 파라미터로 구분).
#
# [상태머신 전이도]
#   WAIT_SIGNAL --/undock_signal--> WAIT_UNDOCK --전송--> UNDOCKING
#     --성공--> READY_TO_NAV --goal전송--> NAVIGATING
#   NAVIGATING/AVOIDING --peer와 safe_dist 미만--> SAFE_STOP(goal 취소)
#   SAFE_STOP --yield_wait 후--> priority==HIGH: READY_TO_NAV(즉시 재출발)
#                            또는 LOW: dist>safe_dist+0.1 될 때까지 대기
#                            후 READY_TO_NAV(원래 goal)
#   (AVOIDING/avoid_goal 관련 필드는 남아있으나 현재 _check_safe_stop이
#    priority 기반으로 단순화되어 실제로 AVOIDING 상태로는 전이하지 않음)
#   (아무 상태) --/mission_complete--> RETURNING_DOCK --nav+dock--> DONE
#
# [발행 토픽 - Publish]
#   /<ns>/cmd_audio (irobot_create_msgs/AudioNoteVector)
#       - 활성 구간(undock 완료~복귀 전) 동안 삐뽀삐뽀 경고음 반복 발행
#   /status_event (String, JSON)
#       - UI용 상태 이벤트 (UNDOCK / HERDING_ACTIVE / MISSION_COMPLETE /
#         DOCK_COMPLETE 등)
#
# [구독 토픽 - Subscribe]
#   /undock_signal (Bool, LATCHED)      <- tower_world_detector: 미션 시작
#   /mission_complete (Bool, LATCHED)   <- designator: 도킹 복귀 트리거
#   /<ns>/flank_goal (PoseStamped, LATCHED)  <- designator: 주행 목표
#   /<ns>/avoid_goal (PoseStamped, LATCHED)  <- designator: SAFE_STOP 우회지점
#       (LOW에게만 발행. 저장은 하지만 현재 로직상 미사용)
#   /<ns>/priority (String, LATCHED)    <- designator: HIGH/LOW 우선순위
#   /<ns>/dock_status (DockStatus, BEST_EFFORT) <- Create3: 도킹 여부
#   /<ns>/amcl_pose (PoseWithCovarianceStamped) <- Nav2: 자기 위치 (x2:
#       저장용 + 1초 스로틀 로그용)
#   /<peer>/amcl_pose <- 상대 로봇 위치 (SAFE_STOP 거리 판정용)
#
# [액션 클라이언트 - Action]
#   /<ns>/undock (irobot_create_msgs/Undock)      : 도크에서 이탈
#   /<ns>/dock (irobot_create_msgs/Dock)          : 도크 진입
#   /<ns>/navigate_to_pose (nav2_msgs/NavigateToPose) : 지점 주행
#
# [참조 파라미터] robot_namespace, peer_namespace, dock_x/y/yaw(실측
#   도킹 복귀 좌표), safe_dist(designator와 동일 권장), yield_wait_sec
# =====================================================================

import json
import math
from datetime import datetime

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from builtin_interfaces.msg import Duration
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import Bool, String

from irobot_create_msgs.action import Undock
from irobot_create_msgs.action import Dock
from irobot_create_msgs.msg import AudioNote, AudioNoteVector, DockStatus


UNDOCK_SIGNAL_TOPIC = '/undock_signal'
MISSION_COMPLETE_TOPIC = '/mission_complete'
STATUS_EVENT_TOPIC = '/status_event'

# 복귀/도킹 실패 재시도 지수 백오프: 1->2->4->8->16초(캡), 최대 5회.
# 실패 직후 즉시 재시도하면 같은 원인(서버 미준비, 경로 막힘)으로
# 계속 실패하며 액션 서버에 부하만 줌 -> 대기시간을 지수적으로 늘림.
MAX_UNDOCK_ATTEMPTS = 5
UNDOCK_BACKOFF_BASE_SEC = 1.0
UNDOCK_BACKOFF_CAP_SEC = 16.0

# 삐뽀삐뽀 경고음 (undock 완료 후 ~ 도킹 복귀 전 활성 구간 동안 루프 재생)
BEEP_NOTES_HZ = [880, 440, 880, 440]   # 삐-뽀-삐-뽀 (A5/A4 옥타브 교차)
BEEP_NOTE_SEC = 0.3                    # 음 하나 길이
# 4음 = 1.2초. 재생이 끝난 직후 다음 세트를 보내도록 약간의 여유를 둠.
BEEP_PERIOD_SEC = 1.3

# tower_world_detector / designator 발행 QoS(TRANSIENT_LOCAL)와 반드시
# 일치해야 함. durability 불일치 시 DDS가 매칭 자체를 안 해서 무수신.
LATCHED_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)

# dock_status 등 퍼블리셔 QoS가 어떻든 최대한 호환되게 구독하기 위한
# 프로파일 (BEST_EFFORT 구독은 RELIABLE/BEST_EFFORT 발행 모두와 매칭됨)
COMPAT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class RobotController(Node):
    """로봇 한 대의 undock / 네비게이션 / 도킹 복귀 상태 머신."""

    WAIT_SIGNAL = 'WAIT_SIGNAL'      # undock 신호 대기
    WAIT_UNDOCK = 'WAIT_UNDOCK'      # undock 액션 서버 준비 대기 / 전송 시도
    UNDOCKING = 'UNDOCKING'          # undock 결과 대기
    READY_TO_NAV = 'READY_TO_NAV'    # goal 전송 가능 상태
    NAVIGATING = 'NAVIGATING'        # goal 수행 중
    SAFE_STOP = 'SAFE_STOP'          # 로봇 간 안전거리 미만 -> 일시 정지
    AVOIDING = 'AVOIDING'            # 회피 지점(avoid_goal)으로 우회 중
    RETURNING_DOCK = 'RETURNING_DOCK'  # 완료 후 도킹 복귀 중
    DONE = 'DONE'                    # 도킹 완료 (최종 상태)

    def __init__(self):
        """파라미터 로드 -> 상태 변수 초기화 -> 액션 클라이언트 3개 생성
        -> 오디오/상태이벤트 퍼블리셔 + 비프 타이머 -> 구독 9개 생성
        -> 0.5s 상태머신 타이머(_tick) 시작."""
        super().__init__('robot_controller')

        # [로봇별 값, --ros-args -p 로 반드시 덮어쓸 것: robot8/robot11 다름]
        self.declare_parameter('robot_namespace', 'robot8')
        self.declare_parameter('dock_x', 0.0248281)   # 실측 도킹 좌표 고정값 (robot8 기준)
        self.declare_parameter('dock_y', -4.7618)     # 실측 도킹 좌표 고정값 (robot8 기준)
        self.declare_parameter('dock_yaw', -1.39633)  # 실측 도킹 yaw 라디안 (robot8 기준)
        # [로봇별 값] robot8: peer=robot11 / robot11: peer=robot8
        self.declare_parameter('peer_namespace', 'robot11')
        self.declare_parameter('safe_dist', 0.5)       # designator와 동일 값 권장
        self.declare_parameter('yield_wait_sec', 0.1)  # SAFE_STOP 후 재출발 대기

        ns = str(self.get_parameter('robot_namespace').value).strip('/')
        self.robot_namespace = ns
        self.ns = f'/{ns}' if ns else ''
        self.tag = self.ns if self.ns else '(root)'
        self.dock_pose = (
            float(self.get_parameter('dock_x').value),
            float(self.get_parameter('dock_y').value),
            float(self.get_parameter('dock_yaw').value),
        )
        peer = str(self.get_parameter('peer_namespace').value).strip('/')
        self.safe_dist = float(self.get_parameter('safe_dist').value)
        self.yield_wait_sec = float(
            self.get_parameter('yield_wait_sec').value)

        # ---- 상태 변수 ----
        self.state = self.WAIT_SIGNAL
        self.current_xy = None            # 자기 amcl (x, y)
        self.peer_xy = None               # 상대 로봇 amcl (x, y)
        self._safe_stop_entered_ns = 0    # SAFE_STOP 진입 시각 (ns)
        self._nav_goal_handle = None      # 진행 중 nav goal 취소용 핸들
        self.is_docked = None             # dock_status 미수신이면 None
        self.latest_goal = None           # designator가 보낸 마지막 flank_goal
        self.latest_avoid_goal = None     # designator가 보낸 마지막 avoid_goal (LOW만 수신)
        self.priority = 'HIGH'            # designator로부터 수신, 기본값 HIGH
        self._sent_goal_xy = None         # 마지막 전송한 goal 좌표 (중복 전송 방지)
        self._nav_seq = 0                 # 최신 goal 판별용 시퀀스 (stale 콜백 무시)
        self.mission_complete = False

        self._dock_attempts = 0           # 복귀/도킹 실패 횟수 (백오프용)
        self._retry_after_ns = 0          # 다음 복귀 재시도 가능 시각 (ns)
        self._return_inflight = False     # 복귀/도킹 액션 진행 중 여부

        self._beeping = False             # 경고음 재생 중 여부 (로그 전환용)
        self._herding_active_sent = False  # HERDING_ACTIVE 이벤트 최초 1회 발행용

        # ---- 액션 클라이언트 (Create3 / Nav2) ----
        self.undock_client = ActionClient(self, Undock, f'{self.ns}/undock')
        self.dock_client = ActionClient(self, Dock, f'{self.ns}/dock')
        self.nav_client = ActionClient(
            self, NavigateToPose, f'{self.ns}/navigate_to_pose',
        )

        # ---- 발행: 경고음 ----
        self.audio_pub = self.create_publisher(
            AudioNoteVector, f'{self.ns}/cmd_audio', 10)
        self.beep_timer = self.create_timer(BEEP_PERIOD_SEC, self._beep_tick)

        # ---- 발행: 상태 이벤트 (UI) ----
        self.status_event_pub = self.create_publisher(
            String, STATUS_EVENT_TOPIC, 10)

        # ---- 구독 ----
        self.create_subscription(
            Bool, UNDOCK_SIGNAL_TOPIC, self._undock_signal_cb, LATCHED_QOS)
        self.create_subscription(
            Bool, MISSION_COMPLETE_TOPIC, self._mission_complete_cb,
            LATCHED_QOS)
        self.create_subscription(
            PoseStamped, f'{self.ns}/flank_goal', self._flank_goal_cb,
            LATCHED_QOS)
        self.create_subscription(
            PoseStamped, f'{self.ns}/avoid_goal', self._avoid_goal_cb,
            LATCHED_QOS)
        # 우선순위: designator가 판정한 HIGH/LOW 수신용 (SAFE_STOP 재출발 분기)
        self.create_subscription(
            String, f'{self.ns}/priority', self._priority_cb, LATCHED_QOS)
        self.create_subscription(
            DockStatus, f'{self.ns}/dock_status', self._dock_cb, COMPAT_QOS)
        # 자기 amcl: 위치 저장용
        self.create_subscription(
            PoseWithCovarianceStamped, f'{self.ns}/amcl_pose',
            lambda m: setattr(self, 'current_xy',
                              (m.pose.pose.position.x,
                               m.pose.pose.position.y)), 10)
        # 자기 amcl: 1초 스로틀 위치 로그용 (운영 확인)
        self.create_subscription(
            PoseWithCovarianceStamped, f'{self.ns}/amcl_pose',
            lambda m: self.get_logger().info(
                f'{self.tag}: 자기 위치 ({m.pose.pose.position.x:.2f}, '
                f'{m.pose.pose.position.y:.2f})',
                throttle_duration_sec=1.0), 10)
        # 상대 로봇 amcl: SAFE_STOP 거리 판정 입력
        self.create_subscription(
            PoseWithCovarianceStamped, f'/{peer}/amcl_pose',
            lambda m: setattr(self, 'peer_xy',
                              (m.pose.pose.position.x,
                               m.pose.pose.position.y)), 10)

        # 0.5s 상태머신 메인 루프
        self.timer = self.create_timer(0.5, self._tick)

        self.get_logger().info(
            f'robot_controller 가동. 대상: {self.tag}, '
            f'도킹 좌표: ({self.dock_pose[0]:.2f}, {self.dock_pose[1]:.2f})'
        )

    # ---------------- 상태 이벤트 발행 (UI용) ----------------

    def publish_status_event(self, event, state):
        """[역할] UI 알림용 상태 이벤트를 JSON으로 [발행] /status_event
        에 보내고 동일 내용을 warn 레벨로도 로그."""
        msg = String()
        msg.data = json.dumps({
            'robot_id': self.robot_namespace,
            'event': event,
            'state': state,
            'timestamp': now_str(),
        }, ensure_ascii=False)
        self.status_event_pub.publish(msg)
        self.get_logger().warn(f'{STATUS_EVENT_TOPIC}: {msg.data}')

    # ---------------- 경고음 (삐뽀삐뽀) ----------------

    def _beep_tick(self):
        """[역할] 1.3s 주기 타이머. 활성 구간(READY_TO_NAV/NAVIGATING/
        SAFE_STOP/AVOIDING = undock 완료 후 ~ 복귀 전) 동안
        [발행] /<ns>/cmd_audio 로 4음 경고음 세트를 반복 발행.
        상태가 구간을 벗어나면 발행을 멈춰 자연스럽게 소리가 꺼진다.
        로그는 시작/정지 전환 순간에만 1줄 (스팸 방지)."""
        active = self.state in (self.READY_TO_NAV, self.NAVIGATING,
                                self.SAFE_STOP, self.AVOIDING)
        if active != self._beeping:
            self._beeping = active
            self.get_logger().info(
                f'{self.tag}: 경고음 {"시작" if active else "정지"} '
                f'(state={self.state})')
        if not active:
            return
        msg = AudioNoteVector()
        msg.append = False   # 이전 큐를 대체 (누적 방지)
        note_nanosec = int(BEEP_NOTE_SEC * 1e9)
        msg.notes = [
            AudioNote(frequency=hz,
                      max_runtime=Duration(sec=0, nanosec=note_nanosec))
            for hz in BEEP_NOTES_HZ
        ]
        self.audio_pub.publish(msg)

    # ---------------- 콜백 ----------------

    def _dock_cb(self, msg: DockStatus):
        """[구독 콜백] /<ns>/dock_status: 물리적 도킹 여부 저장.
        try_undock()에서 '이미 언도킹 상태면 액션 생략' 판정에 사용."""
        self.is_docked = bool(msg.is_docked)

    def _undock_signal_cb(self, msg: Bool):
        """[구독 콜백] /undock_signal (tower가 최초 확정 탐지 시 발행):
        WAIT_SIGNAL 상태에서만 반응 -> WAIT_UNDOCK 전이 (미션 시작).
        latched+반복 발행이라 중복 수신되지만 상태 조건으로 1회만 유효."""
        if not msg.data or self.state != self.WAIT_SIGNAL:
            return
        self.get_logger().warn(f'{self.tag}: undock 신호 수신. 미션 시작.')
        self.state = self.WAIT_UNDOCK

    def _flank_goal_cb(self, msg: PoseStamped):
        """[구독 콜백] /<ns>/flank_goal (designator 발행):
        최신 goal 저장 + 주행 가능 상태(READY_TO_NAV/NAVIGATING)면 즉시
        전송 시도. NAVIGATING 중 새 goal이 오면 Nav2가 preempt(교체)함."""
        self.latest_goal = msg
        if self.state in (self.READY_TO_NAV, self.NAVIGATING):
            self.try_send_nav_goal()

    def _avoid_goal_cb(self, msg: PoseStamped):
        """[구독 콜백] /<ns>/avoid_goal (designator가 LOW에게만 발행):
        저장만 하고 즉시 반응하지 않음. 현재 _check_safe_stop은 priority
        기반으로 단순화되어 이 값을 실제 상태 전이에 쓰지 않는다
        (AVOIDING 상태로는 전이하지 않음)."""
        self.latest_avoid_goal = msg

    def _priority_cb(self, msg: String):
        """[구독 콜백] /<ns>/priority (designator 발행): HIGH/LOW 저장.
        SAFE_STOP 해제 시 HIGH는 즉시 재출발, LOW는 거리 확보까지 대기."""
        self.priority = msg.data

    def _mission_complete_cb(self, msg: Bool):
        """[구독 콜백] /mission_complete (designator 발행):
        플래그만 세우고 UI에 MISSION_COMPLETE 이벤트 발행. 실제
        RETURNING_DOCK 전이는 _tick이 처리 (비동기 콜백 경합을 피하려고
        상태 전환을 tick으로 일원화)."""
        if not msg.data or self.mission_complete:
            return
        self.mission_complete = True
        self.publish_status_event(
            'MISSION_COMPLETE', '야생동물 퇴치 완료. 로봇 대기 좌표로 복귀 시작')
        self.get_logger().warn(f'{self.tag}: 완료 신호 수신. 도킹 복귀 예정.')

    # ---------------- 메인 루프 ----------------

    def _tick(self):
        """[역할] 0.5s 상태머신 루프.
        1) mission_complete면 (시작 전/복귀 중/완료 제외) RETURNING_DOCK 전이
           - 매 tick 재확인: undock 결과 콜백 등과의 경합으로 상태가
             되돌아가는 경우를 방어. AVOIDING/SAFE_STOP 중이라도 즉시 대상.
        2) SAFE_STOP 판정/해제 (_check_safe_stop)
        3) 상태별 시도 함수 호출: WAIT_UNDOCK->try_undock,
           READY_TO_NAV/AVOIDING->try_send_nav_goal(전송 유실 재시도),
           RETURNING_DOCK->try_return_dock"""
        if (self.mission_complete and
                self.state not in (self.WAIT_SIGNAL, self.WAIT_UNDOCK,
                                   self.RETURNING_DOCK, self.DONE)):
            self.state = self.RETURNING_DOCK

        self._check_safe_stop()

        if self.state == self.WAIT_UNDOCK:
            self.try_undock()
        elif self.state in (self.READY_TO_NAV, self.AVOIDING):
            # AVOIDING 포함: 액션 서버 미준비 등으로 회피 goal 전송이
            # 미뤄진 경우 재시도. 이미 전송됐으면 _sent_goal_xy 중복
            # 방지로 즉시 반환되므로 부작용 없음.
            self.try_send_nav_goal()
        elif self.state == self.RETURNING_DOCK:
            self.try_return_dock()

    def _check_safe_stop(self):
        """[역할] 실행단 실시간 안전망. 자기/상대 amcl 거리로 판정.
        - 진입: NAVIGATING 또는 AVOIDING 중 거리 < safe_dist(0.5m)
          -> _nav_seq 증가(진행 중 goal의 늦은 결과 콜백 무시) +
             nav goal 취소 + SAFE_STOP 전이 + 진입 시각 기록
        - 해제: yield_wait_sec(0.1s) 경과 후,
          * priority == HIGH: 즉시 READY_TO_NAV 재출발
          * priority == LOW: dist가 safe_dist+0.1m을 넘어설 때까지 대기
            후 READY_TO_NAV 재출발 (거리 확보 전에는 정지 유지)
        - 시간이 아닌 '거리 확보' 기반 해제인 이유: 두 로봇이 동시에
          거리 조건만으로 재출발하면 다시 붙어 왕복 정지가 반복될 수
          있어, LOW가 물러나 거리를 벌린 뒤에야 재출발하게 함.
        [참조] current_xy, peer_xy, priority
        [호출] _tick() 매 주기."""
        if self.current_xy is None or self.peer_xy is None:
            return
        dist = math.hypot(self.current_xy[0] - self.peer_xy[0],
                          self.current_xy[1] - self.peer_xy[1])

        if (self.state in (self.NAVIGATING, self.AVOIDING)
                and dist < self.safe_dist):
            self._nav_seq += 1  # 진행 중 goal 결과 무시
            if self._nav_goal_handle is not None:
                self._nav_goal_handle.cancel_goal_async()
            self.state = self.SAFE_STOP
            self._safe_stop_entered_ns = self.get_clock().now().nanoseconds
            self.get_logger().warn(
                f'{self.tag}: 상대와 {dist:.2f}m (<{self.safe_dist}m). '
                f'안전 정지.')
            return

        if self.state != self.SAFE_STOP:
            return
        # 양쪽 동일 규칙: yield_wait_sec 경과 후 재출발.
        # (거리 조건으로 막으면 둘 다 근접 정지 시 데드락 -> PVO가 goal을
        #  분리해 두므로 재출발 후 서로 다른 방향으로 벌어짐)
        waited = (self.get_clock().now().nanoseconds
                  - self._safe_stop_entered_ns) * 1e-9
        if waited < self.yield_wait_sec:
            return
        self._sent_goal_xy = None  # 동일 좌표 재전송 허용
        if self.priority == 'HIGH':
            self.state = self.READY_TO_NAV
            self.get_logger().warn(
                f'{self.tag}: [HIGH] 안전 정지 해제. 즉시 재출발.')
            self.try_send_nav_goal()
        elif dist > self.safe_dist + 0.1:
            self.state = self.READY_TO_NAV
            self.get_logger().warn(
                f'{self.tag}: [LOW] 거리 확보됨. 재출발.')
            self.try_send_nav_goal()

    # ---------------- undock ----------------

    def try_undock(self):
        """[역할] WAIT_UNDOCK 상태에서 _tick이 주기 호출.
        - dock_status가 '이미 언도킹'이면 액션 생략 -> READY_TO_NAV
        - undock 액션 서버 준비 안 됐으면 대기 (5s 스로틀 경고)
        - 준비되면 UNDOCKING 전이 후 [액션] /<ns>/undock 전송."""
        if self.is_docked is False:
            self.get_logger().info(
                f'{self.tag}: 이미 undock 상태. undock 액션 생략.'
            )
            self.state = self.READY_TO_NAV
            return

        if not self.undock_client.server_is_ready():
            self.get_logger().warn(
                f'{self.tag}: undock 액션 서버 대기 중...',
                throttle_duration_sec=5.0,
            )
            return

        self.state = self.UNDOCKING
        self.get_logger().info(f'{self.tag}: undock 액션 전송')
        fut = self.undock_client.send_goal_async(Undock.Goal())
        fut.add_done_callback(self._undock_response_cb)

    def _undock_response_cb(self, fut):
        """[액션 콜백] undock goal 수락/거부 응답.
        거부 -> WAIT_UNDOCK 복귀 (다음 tick에 재시도).
        수락 -> 결과 콜백(_undock_result_cb) 등록."""
        goal_handle = fut.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error(
                f'{self.tag}: undock goal 거부됨. 재시도 예정.'
            )
            self.state = self.WAIT_UNDOCK
            return
        result_fut = goal_handle.get_result_async()
        result_fut.add_done_callback(self._undock_result_cb)

    def _undock_result_cb(self, fut):
        """[액션 콜백] undock 결과. result.is_docked로 성공 판정:
        여전히 docked -> 실패, WAIT_UNDOCK 재시도 /
        undocked -> READY_TO_NAV + UNDOCK 상태 이벤트 발행."""
        try:
            result = fut.result().result
            docked = bool(result.is_docked)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'{self.tag}: undock 결과 오류: {exc}')
            docked = False

        if docked:
            self.get_logger().error(
                f'{self.tag}: undock 실패(여전히 도킹 상태). 재시도.'
            )
            self.state = self.WAIT_UNDOCK
        else:
            self.get_logger().info(f'{self.tag}: undock 완료.')
            self.publish_status_event('UNDOCK', '충전 도크 분리및 출동')
            self.state = self.READY_TO_NAV

    # ---------------- 네비게이션 (designator goal 전달) ----------------

    def try_send_nav_goal(self):
        """[역할] 저장된 goal을 [액션] /<ns>/navigate_to_pose 로 전달.
        - goal 선택: AVOIDING이면 latest_avoid_goal, 아니면 latest_goal
          (현재 로직상 AVOIDING으로는 전이하지 않으므로 사실상 항상
          latest_goal)
        - 중복 방지: 마지막 전송 좌표(_sent_goal_xy)와 같으면 스킵
        - 전송 시 _nav_seq 증가 (이전 goal의 늦은 콜백 무시용) +
          AVOIDING이 아니면 NAVIGATING 전이 (AVOIDING은 상태 유지)
        [호출] _flank_goal_cb(즉시), _tick(재시도), _check_safe_stop(재출발),
               _nav_result_cb(AVOIDING 종료 후 복귀, 현재 미사용 경로)."""
        target = (self.latest_avoid_goal if self.state == self.AVOIDING
                  else self.latest_goal)
        if target is None:
            return
        gx = target.pose.position.x
        gy = target.pose.position.y
        if (self._sent_goal_xy is not None and
                abs(gx - self._sent_goal_xy[0]) < 1e-6 and
                abs(gy - self._sent_goal_xy[1]) < 1e-6):
            return
        if not self.nav_client.server_is_ready():
            self.get_logger().warn(
                f'{self.tag}: navigate_to_pose 액션 서버 대기 중...',
                throttle_duration_sec=5.0,
            )
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = target

        self._nav_seq += 1
        seq = self._nav_seq
        self._sent_goal_xy = (gx, gy)
        if self.state != self.AVOIDING:
            self.state = self.NAVIGATING

        self.get_logger().info(
            f'{self.tag}: nav goal 전송 -> ({gx:.2f}, {gy:.2f})'
        )
        fut = self.nav_client.send_goal_async(goal_msg)
        fut.add_done_callback(lambda f, s=seq: self._nav_response_cb(f, s))

    def _nav_response_cb(self, fut, seq):
        """[액션 콜백] nav goal 수락/거부 응답. seq가 최신일 때만 상태
        조작 (stale 응답 무시). 수락 시 goal handle 저장 -> SAFE_STOP에서
        cancel_goal_async()로 즉시 정지시키는 데 사용. 첫 수락 시 1회
        HERDING_ACTIVE 상태 이벤트 발행."""
        goal_handle = fut.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error(f'{self.tag}: nav goal 거부됨.')
            if seq == self._nav_seq:
                self.state = self.READY_TO_NAV
            return
        if seq == self._nav_seq:
            self._nav_goal_handle = goal_handle  # SAFE_STOP 취소용
        if not self._herding_active_sent:
            self._herding_active_sent = True
            self.publish_status_event('HERDING_ACTIVE', '야생동물 퇴치 수행')
        result_fut = goal_handle.get_result_async()
        result_fut.add_done_callback(lambda f, s=seq: self._nav_result_cb(f, s))

    def _nav_result_cb(self, fut, seq):
        """[액션 콜백] nav 종료 결과 처리.
        - seq != 최신이면 무시 (preempt/취소된 옛 goal의 결과)
        - AVOIDING 중 종료(현재 미도달 경로): 성공이면 avoid_goal 리셋,
          성공/실패 모두 READY_TO_NAV 거쳐 즉시 try_send_nav_goal
        - 일반(NAVIGATING) 종료: READY_TO_NAV 복귀 + _sent_goal_xy 리셋
          (같은 좌표 goal 재수신 시 재전송 허용). 성공/실패 모두 다음
          goal 갱신을 기다림 (실패해도 designator가 새 좌표를 줌)."""
        if seq != self._nav_seq:
            return
        status = fut.result().status
        if self.state == self.AVOIDING:
            # 회피 지점 nav 종료 -> 원래 flank_goal로 복귀
            if status == 4:  # STATUS_SUCCEEDED
                self.get_logger().warn(
                    f'{self.tag}: 회피 지점 도착. 원래 flank goal로 복귀.')
                self.latest_avoid_goal = None  # 다음 SAFE_STOP에서 새 회피 좌표 수신 대기
            else:
                self.get_logger().warn(
                    f'{self.tag}: 회피 nav 종료 status={status}. '
                    f'원래 goal로 복귀.')
            self.state = self.READY_TO_NAV
            self._sent_goal_xy = None
            self.try_send_nav_goal()
            return
        if status == 4:  # STATUS_SUCCEEDED
            self.get_logger().info(
                f'{self.tag}: goal 도착 (플랭크 지점).'
            )
        else:
            self.get_logger().warn(
                f'{self.tag}: nav 종료 status={status}. 좌표 갱신 시 재전송.'
            )
        self.state = self.READY_TO_NAV
        self._sent_goal_xy = None  # 종료 후 같은 goal 재수신 시 재전송 허용

    # ---------------- 도킹 복귀 (완료 후) ----------------

    def try_return_dock(self):
        """[역할] RETURNING_DOCK 상태에서 _tick이 주기 호출.
        가드 4단: 진행 중이면 스킵 / 5회 실패 시 중단 / 백오프 대기 중
        스킵 / nav 서버 미준비 스킵. 통과 시 실측 도킹 좌표(dock_pose)로
        [액션] navigate_to_pose 전송. _nav_seq 증가로 진행 중이던 플랭크
        goal 결과를 무효화(preempt)."""
        if self._return_inflight:
            return
        if self._dock_attempts >= MAX_UNDOCK_ATTEMPTS:
            self.get_logger().error(
                f'{self.tag}: 도킹 복귀 {MAX_UNDOCK_ATTEMPTS}회 연속 실패. 중단.',
                throttle_duration_sec=10.0,
            )
            return
        if self.get_clock().now().nanoseconds < self._retry_after_ns:
            return
        if not self.nav_client.server_is_ready():
            self.get_logger().warn(
                f'{self.tag}: navigate_to_pose 액션 서버 대기 중...',
                throttle_duration_sec=5.0,
            )
            return

        gx, gy, yaw = self.dock_pose
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = gx
        goal_msg.pose.pose.position.y = gy
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self._nav_seq += 1  # 진행 중이던 플랭크 goal 결과 무시(새 goal이 preempt)
        self._return_inflight = True
        self.get_logger().info(
            f'{self.tag}: 도킹 복귀 goal 전송 -> ({gx:.2f}, {gy:.2f})'
        )
        fut = self.nav_client.send_goal_async(goal_msg)
        fut.add_done_callback(self._return_nav_response_cb)

    def _return_nav_response_cb(self, fut):
        """[액션 콜백] 복귀 nav goal 수락/거부. 거부 -> 실패 등록(백오프)."""
        goal_handle = fut.result()
        if goal_handle is None or not goal_handle.accepted:
            self._register_dock_failure('도킹 복귀 goal 거부됨.')
            return
        goal_handle.get_result_async().add_done_callback(
            self._return_nav_result_cb)

    def _return_nav_result_cb(self, fut):
        """[액션 콜백] 복귀 nav 결과. 성공 시 [액션] /<ns>/dock 전송으로
        연쇄 (nav로 도크 근처까지 -> dock 액션이 IR 정밀 도킹 수행).
        nav 실패 또는 dock 서버 미준비 -> 실패 등록(백오프 재시도)."""
        status = fut.result().status
        if status != 4:  # STATUS_SUCCEEDED 아님
            self._register_dock_failure(f'도킹 복귀 nav 실패 status={status}.')
            return
        if not self.dock_client.server_is_ready():
            self._register_dock_failure('dock 액션 서버 미준비.')
            return
        self.get_logger().info(
            f'{self.tag}: 복귀 지점 도착. dock 액션 전송.'
        )
        fut2 = self.dock_client.send_goal_async(Dock.Goal())
        fut2.add_done_callback(self._dock_response_cb)

    def _dock_response_cb(self, fut):
        """[액션 콜백] dock goal 수락/거부. 거부 -> 실패 등록(백오프)."""
        goal_handle = fut.result()
        if goal_handle is None or not goal_handle.accepted:
            self._register_dock_failure('dock goal 거부됨.')
            return
        goal_handle.get_result_async().add_done_callback(self._dock_result_cb)

    def _dock_result_cb(self, fut):
        """[액션 콜백] dock 결과. is_docked=True -> DONE (미션 종료, 최종
        상태) + DOCK_COMPLETE 상태 이벤트 발행. 아니면 실패 등록 ->
        백오프 후 복귀 nav부터 재시도."""
        try:
            docked = bool(fut.result().result.is_docked)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'{self.tag}: dock 결과 오류: {exc}')
            docked = False
        if docked:
            self.state = self.DONE
            self.publish_status_event(
                'DOCK_COMPLETE',
                f'{self.robot_namespace} 도킹 완료 및 충전 대기 중')
            self.get_logger().info(f'{self.tag}: 도킹 완료. 미션 종료.')
        else:
            self._register_dock_failure('dock 실패(미도킹 상태).')

    def _register_dock_failure(self, msg):
        """[역할] 복귀/도킹 실패 1회 기록 + 지수 백오프 예약.
        대기시간 = min(1 * 2^(실패횟수-1), 16)초. inflight 해제로
        백오프 경과 후 try_return_dock이 다시 시도할 수 있게 함.
        [호출] 복귀 nav/dock 관련 콜백들의 모든 실패 경로."""
        self._dock_attempts += 1
        wait = min(
            UNDOCK_BACKOFF_BASE_SEC * (2 ** (self._dock_attempts - 1)),
            UNDOCK_BACKOFF_CAP_SEC,
        )
        self._retry_after_ns = (
            self.get_clock().now().nanoseconds + int(wait * 1e9)
        )
        self._return_inflight = False
        self.get_logger().error(
            f'{self.tag}: {msg} ({self._dock_attempts}/{MAX_UNDOCK_ATTEMPTS}, '
            f'{wait:.0f}s 후 재시도)'
        )


def main():
    rclpy.init()
    node = RobotController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
