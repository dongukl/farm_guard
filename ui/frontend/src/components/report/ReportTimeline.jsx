import { formatDateTime } from '../../utils/formatDate.js';
import { REPORT_STEPS } from '../../utils/reportAnalysis.js';

const LABELS = REPORT_STEPS.map((step) => ({
  key: step.key,
  title: `${step.label} 시간`,
  description: step.description
}));

export default function ReportTimeline({ report }) {
  // 각 단계의 timestamp만 읽어서 시간 순서가 한눈에 보이도록 렌더링한다.
  return (
    <div className="timeline">
      {LABELS.map(({ key, title, description }, index) => {
        const isDone = Boolean(report?.[key]);

        return (
          <div className={isDone ? 'timeline-item done' : 'timeline-item pending'} key={key}>
            <div className={isDone ? 'timeline-dot done' : 'timeline-dot'}>{index + 1}</div>
            <div className="timeline-content">
              <div className="timeline-heading">
                <h3>{title}</h3>
                <span className={isDone ? 'timeline-pill done' : 'timeline-pill pending'}>
                  {isDone ? '기록 완료' : '대기'}
                </span>
              </div>
              <p>{description}</p>
              <strong>{formatDateTime(report?.[key]) || '아직 기록되지 않았습니다.'}</strong>
            </div>
          </div>
        );
      })}
    </div>
  );
}
