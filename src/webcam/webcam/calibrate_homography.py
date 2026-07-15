#!/usr/bin/env python3
"""
관제탑 웹캠 -> map 좌표 호모그래피 캘리브레이션 도구

사용법:
    python3 calibrate_homography.py

절차:
    1. 웹캠 화면이 뜨면, 실제 바닥에서 map 좌표를 알고 있는 지점을
       화면에서 클릭합니다 (예: 울타리 모서리, 바닥에 표시해둔 테이프 등).
    2. 클릭할 때마다 터미널에 "이 지점의 map 좌표 (x y)를 입력하세요"가 뜨는데,
       공백으로 구분해서 실수로 입력합니다. 예: -1.42 -4.2
    3. 최소 4개, 권장 8~12개 이상 클릭합니다.
       - 측면/기울어진 각도로 촬영 중이면 원거리 쪽에 더 촘촘히 찍으세요.
       - 실제로 몰이가 일어나는 구역(울타리, 입구 근처)을 우선 배치하세요.
    4. 'c' 키를 누르면 지금까지 찍은 점으로 호모그래피를 계산해서
       ground_homography.npy 로 저장합니다.
    5. 'q' 키를 누르면 종료합니다 (저장 안 한 상태로 나가면 값이 사라집니다).
    6. 'u' 키를 누르면 마지막으로 찍은 점을 취소합니다.
"""

import os

import cv2
import numpy as np

CAMERA_INDEX = 2  # observer.py와 동일한 카메라 인덱스로 맞추세요

# CWD(작업 디렉토리)에 상관없이 항상 이 스크립트가 있는 디렉토리에 저장
# (tower_world_detector.py가 같은 디렉토리 기준으로 읽으므로 일치시켜야 함).
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'ground_homography.npy')

image_points = []
world_points = []


def mouse_callback(event, x, y, flags, param):
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    print(f'\n클릭한 픽셀 좌표: ({x}, {y})')
    raw = input('이 지점의 실제 map 좌표를 "x y" 형식으로 입력하세요: ')

    try:
        wx, wy = map(float, raw.strip().split())
    except ValueError:
        print('입력 형식이 잘못되었습니다. 이 점은 무시합니다.')
        return

    image_points.append((x, y))
    world_points.append((wx, wy))
    print(f'등록됨: 픽셀({x},{y}) -> map({wx},{wy})  [현재 총 {len(image_points)}개]')


def draw_overlay(frame):
    view = frame.copy()
    for i, (u, v) in enumerate(image_points):
        cv2.circle(view, (u, v), 6, (0, 0, 255), -1)
        cv2.putText(
            view, str(i + 1), (u + 8, v - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
        )
    cv2.putText(
        view,
        f'points: {len(image_points)}  [c]=compute  [u]=undo  [q]=quit',
        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
    )
    return view


def compute_and_save():
    if len(image_points) < 4:
        print(f'점이 {len(image_points)}개뿐입니다. 최소 4개 이상 필요합니다.')
        return

    img_pts = np.array(image_points, dtype=np.float32)
    world_pts = np.array(world_points, dtype=np.float32)

    H, mask = cv2.findHomography(img_pts, world_pts, method=0)

    if H is None:
        print('호모그래피 계산 실패. 점 배치를 다시 확인하세요 (일직선 배치 등은 실패 원인).')
        return

    # 재투영 오차 확인 (각 점이 실제로 얼마나 잘 맞는지)
    print('\n--- 재투영 오차 확인 ---')
    total_err = 0.0
    for (u, v), (wx, wy) in zip(image_points, world_points):
        pt = np.array([u, v, 1.0])
        proj = H @ pt
        proj /= proj[2]
        err = np.hypot(proj[0] - wx, proj[1] - wy)
        total_err += err
        print(f'  픽셀({u},{v}) -> 예측({proj[0]:.3f},{proj[1]:.3f}) '
              f'vs 실제({wx},{wy})  오차={err:.3f}m')

    print(f'평균 오차: {total_err / len(image_points):.3f}m')

    np.save(OUTPUT_PATH, H)
    print(f'\n호모그래피 저장 완료: {OUTPUT_PATH}')


def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print(f'카메라 {CAMERA_INDEX}번을 열 수 없습니다.')
        return

    window_name = 'homography calibration'
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    print('캘리브레이션을 시작합니다. 최소 4개, 권장 8개 이상의 기준점을 클릭하세요.')

    while True:
        ret, frame = cap.read()
        if not ret:
            print('프레임을 읽을 수 없습니다.')
            break

        view = draw_overlay(frame)
        cv2.imshow(window_name, view)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('c'):
            compute_and_save()
        elif key == ord('u'):
            if image_points:
                image_points.pop()
                world_points.pop()
                print('마지막 점 취소됨')

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
