#!/usr/bin/env python3
"""
designator.py (지정자)

웹캠(tower_world_detector)의 animal 좌표와 두 로봇의 amcl_pose를 받아
좌/우 플랭크 역할을 동적으로 배정하고, 호 플랭킹 goal 좌표를 계산해
/<ns>/flank_goal 토픽으로 발행하는 판단 전용 노드.
액션(undock/nav/dock) 실행은 robot_controller.py 가 담당한다.

발행:
    /robot8/flank_goal, /robot11/flank_goal (PoseStamped, latched)
    /robot8/avoid_goal, /robot11/avoid_goal (PoseStamped, latched)
        - PVO 조정이 실제로 발생한 tick에 LOW 로봇에게만 발행.
          robot_controller가 SAFE_STOP 재출발 시 우회 지점으로 사용.
    /mission_complete (Bool, latched) - 완료 확정 시 1회 True

실행 예 (PC1):
    python3 designator.py --ros-args \
        -p gate_x:=-1.59 -p gate_y:=-0.597 \
        -p fence_max_x:=0.54 -p fence_max_y:=0.68
"""

import math

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from std_msgs.msg import Bool, String


ANIMAL_POSE_TOPIC = '/world/animal_pose'
MISSION_COMPLETE_TOPIC = '/mission_complete'
ROBOTS = ['robot8', 'robot11']  # 지정자는 항상 두 로봇을 동시에 판단

# 늦게 뜬 구독자(robot_controller)도 마지막 값을 받도록 latched 발행
LATCHED_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)


def clamp(value, lo, hi):
    """value를 [lo, hi] 범위로 제한."""
    return min(max(value, lo), hi)


def ang_diff(a, b):
    """두 각도 차의 절댓값 (-pi~pi 래핑)."""
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


class Designator(Node):
    def __init__(self):
        super().__init__('designator')

        self.declare_parameter('gate_x', 0.374)
        self.declare_parameter('gate_y', -2.14)
        self.declare_parameter('flank_angle_deg', 75.0)
        self.declare_parameter('flank_radius', 0.5)
        self.declare_parameter('fence_min_x', -1.96)
        self.declare_parameter('fence_min_y', -5.17)
        self.declare_parameter('fence_max_x', 3.0)
        self.declare_parameter('fence_max_y', 1.0)
        self.declare_parameter('wall_margin', 0.3)
        self.declare_parameter('goal_update_threshold', 0.4)
        self.declare_parameter('exit_confirm_sec', 0.5)
        self.declare_parameter('swap_hysteresis_deg', 20.0)
        self.declare_parameter('safe_dist', 0.5)
        self.declare_parameter('predict_sec', 1.0)
        self.declare_parameter('robot_max_speed', 0.31)  # 터틀봇4 최대속도 m/s

        self.gate_xy = (
            float(self.get_parameter('gate_x').value),
            float(self.get_parameter('gate_y').value),
        )
        self.flank_angle_rad = math.radians(
            float(self.get_parameter('flank_angle_deg').value)
        )
        self.flank_radius = float(self.get_parameter('flank_radius').value)
        self.fence_bounds = (
            float(self.get_parameter('fence_min_x').value),
            float(self.get_parameter('fence_min_y').value),
            float(self.get_parameter('fence_max_x').value),
            float(self.get_parameter('fence_max_y').value),
        )
        self.wall_margin = float(self.get_parameter('wall_margin').value)
        self.goal_update_threshold = float(
            self.get_parameter('goal_update_threshold').value
        )
        self.exit_confirm_sec = float(
            self.get_parameter('exit_confirm_sec').value
        )
        self.swap_hyst_rad = math.radians(
            float(self.get_parameter('swap_hysteresis_deg').value)
        )
        self.safe_dist = float(self.get_parameter('safe_dist').value)
        self.predict_sec = float(self.get_parameter('predict_sec').value)
        self.robot_max_speed = float(
            self.get_parameter('robot_max_speed').value
        )

        self.animal_xy = None
        self.poses = {ns: None for ns in ROBOTS}            # 로봇별 amcl (x, y)
        self.last_goal_animal = {ns: None for ns in ROBOTS}  # 마지막 goal 시 animal 좌표
        self.last_goal_xy = {ns: None for ns in ROBOTS}      # 마지막 발행 goal 좌표 (PVO용)
        self.signs = None            # {ns: +1(왼쪽)/-1(오른쪽)}, 최초 배정 전 None
        self.pvo_high = 'robot8'     # animal에 더 가까운 로봇 (goal 유지)
        self.pvo_low = 'robot11'     # 더 먼 로봇 (충돌 시 회피)
        self.mission_complete = False
        self._outside_since = None   # animal 펜스 이탈 시작 시각 (디바운스)

        self.goal_pubs = {
            ns: self.create_publisher(
                PoseStamped, f'/{ns}/flank_goal', LATCHED_QOS)
            for ns in ROBOTS
        }
        # PVO 조정 발생 시 LOW 로봇에게만 실제 발행 (HIGH는 사용 안 함)
        self.avoid_pubs = {
            ns: self.create_publisher(
                PoseStamped, f'/{ns}/avoid_goal', LATCHED_QOS)
            for ns in ROBOTS
        }
        self.priority_pubs = {
            ns: self.create_publisher(
                String, f'/{ns}/priority', LATCHED_QOS)
            for ns in ROBOTS
        }
        self.complete_pub = self.create_publisher(
            Bool, MISSION_COMPLETE_TOPIC, LATCHED_QOS)

        self.create_subscription(
            PoseStamped, ANIMAL_POSE_TOPIC, self._animal_pose_cb, 10)
        for ns in ROBOTS:
            self.create_subscription(
                PoseWithCovarianceStamped, f'/{ns}/amcl_pose',
                lambda m, n=ns: self.poses.__setitem__(
                    n, (m.pose.pose.position.x, m.pose.pose.position.y)),
                10)

        self.timer = self.create_timer(0.5, self._tick)

        self.get_logger().info(
            f'designator 가동. 게이트: {self.gate_xy}, '
            f'플랭크: ±{math.degrees(self.flank_angle_rad):.0f}도 '
            f'{self.flank_radius}m, 스왑 히스테리시스: '
            f'{math.degrees(self.swap_hyst_rad):.0f}도'
        )

    def _animal_pose_cb(self, msg: PoseStamped):
        self.animal_xy = (msg.pose.position.x, msg.pose.position.y)

    # ---------------- 메인 루프 ----------------

    def _tick(self):
        if self.mission_complete or self.animal_xy is None:
            return

        if self._check_exit_complete():
            self.mission_complete = True
            msg = Bool()
            msg.data = True
            self.complete_pub.publish(msg)
            self.get_logger().warn(
                'animal 펜스 이탈 확정. /mission_complete 발행. goal 발행 중지.')
            return

        if all(self.poses[ns] is not None for ns in ROBOTS):
            self._update_assignment()
            d8 = math.hypot(self.poses['robot8'][0] - self.animal_xy[0],
                            self.poses['robot8'][1] - self.animal_xy[1])
            d11 = math.hypot(self.poses['robot11'][0] - self.animal_xy[0],
                             self.poses['robot11'][1] - self.animal_xy[1])
            if d8 != d11:  # 동일 거리면 기존 유지
                high = 'robot8' if d8 < d11 else 'robot11'
                if high != self.pvo_high:
                    self.pvo_high = high
                    self.pvo_low = 'robot11' if high == 'robot8' else 'robot8'
                    self.get_logger().info(
                        f'PVO 우선순위 변경: high={self.pvo_high} '
                        f'(animal에 더 가까움), low={self.pvo_low}')
        if self.signs is None:
            return  # 최초 배정 전 (amcl 미수신) -> goal 발행 보류
        self._publish_priorities()
        self._publish_goals()

    def _publish_priorities(self):
        for ns in ROBOTS:
            msg = String()
            msg.data = 'HIGH' if ns == self.pvo_high else 'LOW'
            self.priority_pubs[ns].publish(msg)

    def _update_assignment(self):
        """animal 기준 각도 비용이 낮은 좌우 배정 선택 (히스테리시스 적용)."""
        ax, ay = self.animal_xy
        phi = math.atan2(ay - self.gate_xy[1], ax - self.gate_xy[0])  # push_dir 각도
        ang = {
            ns: math.atan2(self.poses[ns][1] - ay, self.poses[ns][0] - ax)
            for ns in ROBOTS
        }

        def cost(s8):  # robot8에 s8, robot11에 -s8 배정 시 총 각도 차이
            return (ang_diff(ang['robot8'], phi + s8 * self.flank_angle_rad)
                    + ang_diff(ang['robot11'], phi - s8 * self.flank_angle_rad))

        if self.signs is None:
            s8 = 1 if cost(1) <= cost(-1) else -1
            self.get_logger().info(
                f'좌우 최초 배정: robot8={s8:+d}, robot11={-s8:+d}')
        else:
            s8 = self.signs['robot8']
            if cost(-s8) + self.swap_hyst_rad < cost(s8):
                s8 = -s8
                self.get_logger().info(
                    f'좌우 배정 스왑: robot8={s8:+d}, robot11={-s8:+d}')
        self.signs = {'robot8': s8, 'robot11': -s8}

    def compute_goal(self, sign):
        """게이트->animal 방향을 sign*flank_angle 회전시킨 플랭크 지점 계산+clamp."""
        ax, ay = self.animal_xy
        dx, dy = ax - self.gate_xy[0], ay - self.gate_xy[1]  # push_dir
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return None
        ux, uy = dx / dist, dy / dist

        theta = sign * self.flank_angle_rad
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        fx = ux * cos_t - uy * sin_t
        fy = ux * sin_t + uy * cos_t

        xmin, ymin, xmax, ymax = self.fence_bounds
        gx = clamp(ax + fx * self.flank_radius,
                   xmin + self.wall_margin, xmax - self.wall_margin)
        gy = clamp(ay + fy * self.flank_radius,
                   ymin + self.wall_margin, ymax - self.wall_margin)

        yaw = math.atan2(ay - gy, ax - gx)  # goal 지점에서 animal을 바라보게
        return gx, gy, yaw

    def _publish_goals(self):
        """animal이 임계값 이상 이동한 로봇에만 flank goal 재계산·발행."""
        for ns in ROBOTS:
            last = self.last_goal_animal[ns]
            if last is not None and not self._moved_enough(last):
                continue
            goal = self.compute_goal(self.signs[ns])
            if goal is None:
                continue
            gx, gy, yaw = goal
            adjusted = False
            if ns == self.pvo_low:
                agx, agy = self._adjust_goal_for_collision(gx, gy)
                if (agx, agy) != (gx, gy):
                    adjusted = True
                    gx, gy = agx, agy
                    yaw = math.atan2(self.animal_xy[1] - gy,
                                     self.animal_xy[0] - gx)
            msg = PoseStamped()
            msg.header.frame_id = 'map'
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.pose.position.x = gx
            msg.pose.position.y = gy
            msg.pose.orientation.z = math.sin(yaw / 2.0)
            msg.pose.orientation.w = math.cos(yaw / 2.0)
            self.goal_pubs[ns].publish(msg)
            if adjusted:
                self.avoid_pubs[ns].publish(msg)
                self.get_logger().info(
                    f'/{ns}: avoid goal 발행 -> ({gx:.2f}, {gy:.2f})')
            self.last_goal_animal[ns] = self.animal_xy
            self.last_goal_xy[ns] = (gx, gy)
            self.get_logger().info(
                f'/{ns}: flank goal 발행 -> ({gx:.2f}, {gy:.2f}), '
                f'sign={self.signs[ns]:+d}')

    def _adjust_goal_for_collision(self, gx, gy):
        """HIGH(animal 근접 로봇) 예측 위치에서 safe_dist 미만이면 LOW goal을 safe_dist+0.05까지 밀어냄."""
        p8 = self.poses[self.pvo_high]
        g8 = self.last_goal_xy[self.pvo_high]
        if p8 is None or g8 is None:
            return gx, gy
        dx, dy = g8[0] - p8[0], g8[1] - p8[1]
        d = math.hypot(dx, dy)
        if d > 1e-6:
            move = min(d, self.robot_max_speed * self.predict_sec)
            pred = (p8[0] + dx / d * move, p8[1] + dy / d * move)
        else:
            pred = p8
        vx, vy = gx - pred[0], gy - pred[1]
        dist = math.hypot(vx, vy)
        if dist >= self.safe_dist:
            return gx, gy
        if dist > 1e-6:
            ux, uy = vx / dist, vy / dist  # 예측점->goal 방향으로 밀어냄
        elif d > 1e-6:
            ux, uy = -dy / d, dx / d       # goal이 예측점과 겹침 -> 수직 방향
        else:
            ux, uy = 1.0, 0.0
        push = self.safe_dist + 0.05
        xmin, ymin, xmax, ymax = self.fence_bounds
        agx = clamp(pred[0] + ux * push,
                    xmin + self.wall_margin, xmax - self.wall_margin)
        agy = clamp(pred[1] + uy * push,
                    ymin + self.wall_margin, ymax - self.wall_margin)
        self.get_logger().info(
            f'/{self.pvo_low}: PVO goal 조정 ({gx:.2f},{gy:.2f}) -> '
            f'({agx:.2f},{agy:.2f})')
        return agx, agy

    def _check_exit_complete(self):
        """animal이 펜스(margin 미적용 원본 경계) 밖에서 exit_confirm_sec 이상 유지되면 True."""
        xmin, ymin, xmax, ymax = self.fence_bounds
        ax, ay = self.animal_xy
        if xmin <= ax <= xmax and ymin <= ay <= ymax:
            self._outside_since = None  # 펜스 안 재진입 -> 카운트 리셋
            return False
        now = self.get_clock().now()
        if self._outside_since is None:
            self._outside_since = now
            return False
        return (now - self._outside_since).nanoseconds * 1e-9 >= self.exit_confirm_sec

    def _moved_enough(self, ref_xy):
        return (
            math.hypot(
                self.animal_xy[0] - ref_xy[0],
                self.animal_xy[1] - ref_xy[1],
            ) > self.goal_update_threshold
        )


def main():
    rclpy.init()
    node = Designator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
