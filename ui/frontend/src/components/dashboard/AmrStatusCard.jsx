import { Bot } from 'lucide-react';
import StatusBadge from '../common/StatusBadge.jsx';
import { amrStatusClass, formatAmrStatusLabel } from '../../utils/status.js';
import { formatDateTime } from '../../utils/formatDate.js';

export default function AmrStatusCard({ robot }) {
  return (
    <article className="card status-card">
      <div className="card-title-row">
        <div>
          <p className="eyebrow">AMR Response Status</p>
          <h2>{robot?.name || 'AMR'}</h2>
        </div>
        <div className="status-card-icon">
          <Bot size={28} />
        </div>
      </div>
      <div className="metric-row">
        <span>상태</span>
        <StatusBadge
          label={formatAmrStatusLabel(robot)}
          tone={amrStatusClass(robot?.status)}
        />
      </div>
      <div className="metric-row">
        <span>감지 이벤트 시간</span>
        <strong>{formatDateTime(robot?.detected_at)}</strong>
      </div>
      <div className="metric-row">
        <span>최근 상태 수신 시간</span>
        <strong>{formatDateTime(robot?.updated_at)}</strong>
      </div>
    </article>
  );
}
