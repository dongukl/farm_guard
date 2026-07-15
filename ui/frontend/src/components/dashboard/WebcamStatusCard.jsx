import { Video } from 'lucide-react';
import StatusBadge from '../common/StatusBadge.jsx';
import { WEBCAM_STATUS_LABEL, webcamStatusClass } from '../../utils/status.js';
import { formatDateTime } from '../../utils/formatDate.js';

export default function WebcamStatusCard({ webcam }) {
  return (
    <article className="card status-card">
      <div className="card-title-row">
        <div>
          <p className="eyebrow">Field Camera Status</p>
          <h2>{webcam?.name || '밭 경계선 웹캠'}</h2>
        </div>
        <div className="status-card-icon">
          <Video size={28} />
        </div>
      </div>
      <div className="metric-row">
        <span>감지 상태</span>
        <StatusBadge
          label={WEBCAM_STATUS_LABEL[webcam?.status] || '-'}
          tone={webcamStatusClass(webcam?.status)}
        />
      </div>
      <div className="metric-row">
        <span>마지막 감지 시간</span>
        <strong>{formatDateTime(webcam?.detected_at)}</strong>
      </div>
      <p className="helper-text">밭 경계선 영상에서 YOLO가 유해동물 침입 여부를 판정하고 관제 카드 상태를 갱신합니다.</p>
    </article>
  );
}
