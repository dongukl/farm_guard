import { API_BASE_URL } from './env.js';

// 카메라 패널은 설정 배열만 바꿔도 같은 컴포넌트로 렌더링되도록 맞춘다.
export const CAMERAS = [
  {
    id: 'webcam',
    name: '경계 웹캠',
    kicker: 'BOUNDARY CAMERA',
    description: 'YOLO bbox 처리 영상과 사건 녹화 상태를 함께 보여주는 USB 웹캠',
    streamType: 'mjpeg',
    streamUrl: `${API_BASE_URL}/api/cameras/webcam/stream`,
    statusUrl: `${API_BASE_URL}/api/cameras/webcam/capture-status`,
    deviceOptionsUrl: `${API_BASE_URL}/api/cameras/webcam/device-options`,
    deviceUrl: `${API_BASE_URL}/api/cameras/webcam/device`
  },
];
