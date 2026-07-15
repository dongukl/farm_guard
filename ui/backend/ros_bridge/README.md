# ROS2 Bridge 연동 위치

현재 zip은 UI 화면과 mock API 중심으로 구성되어 있습니다.
실제 프로젝트에 ROS2를 연결할 때 이 폴더에 bridge node를 추가하면 됩니다.

예상 연동 토픽:

```text
/vision/webcam/detected
/amr1/status
/amr1/event_time
/amr1/command
/amr2/status
/amr2/event_time
/amr2/command
```

권장 흐름:

1. YOLO 노드가 멧돼지 경계선 침입을 감지
2. ROS2 topic 발행
3. bridge node가 topic 수신
4. FastAPI `/api/simulate/webcam_detected` 또는 별도 API 호출
5. 웹 대시보드 상태 갱신
