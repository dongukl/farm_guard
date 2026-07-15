import CameraPanel from '../components/camera/CameraPanel.jsx';
import { CAMERAS } from '../config/cameras.js';

export default function CameraMonitorPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Camera Control</p>
          <h2>실시간 카메라 관제 화면</h2>
          <p>경계 웹캠의 YOLO 감지 영상, 장치 상태, 사건 녹화 흐름을 관제 패널에서 확인합니다.</p>
        </div>
      </div>

      <div className="camera-grid single-camera-grid">
        {CAMERAS.map((camera) => (
          <CameraPanel camera={camera} key={camera.id} />
        ))}
      </div>
    </div>
  );
}
