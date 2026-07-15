import { AlertTriangle, CheckCircle2, Clock3, TimerReset } from 'lucide-react';
import { formatDateTime } from '../../utils/formatDate.js';
import {
  analyzeReport,
  formatDuration,
  getReportStatusClass,
  getReportStatusLabel
} from '../../utils/reportAnalysis.js';

function StepStatusBadge({ status }) {
  // 각 단계가 정상 기록인지, 누락인지, 아직 대기인지 눈으로 바로 보여준다.
  if (status === 'done') {
    return <span className="status-badge success">정상 기록</span>;
  }
  if (status === 'missing') {
    return <span className="status-badge danger">단계 누락</span>;
  }
  return <span className="status-badge neutral">대기</span>;
}

function TransitionStatusBadge({ status }) {
  // 앞 단계와 다음 단계 사이 시간 차이가 정상인지 판정하는 배지다.
  if (status === 'done') {
    return <span className="status-badge success">정상 진행</span>;
  }
  if (status === 'invalid') {
    return <span className="status-badge danger">순서 오류</span>;
  }
  if (status === 'waiting') {
    return <span className="status-badge warning">다음 동작 대기</span>;
  }
  return <span className="status-badge neutral">미시작</span>;
}

export default function ReportOperationSummary({ report, mode = 'live' }) {
  // report snapshot을 분석 유틸에 넘겨서 점검 필요 여부와 단계 상태를 계산한다.
  const analysis = analyzeReport(report);
  const statusClass = getReportStatusClass(analysis.status);
  const statusLabel = getReportStatusLabel(analysis.status, mode);
  const attentionCount = analysis.missingSteps.length + analysis.invalidTransitions.length;

  return (
    <div className="report-operation">
      <div className="report-decision-grid">
        <div className={`decision-card ${statusClass}`}>
          <span>전체 동작 판정</span>
          <strong>{statusLabel}</strong>
          <p>{analysis.scenarioStatus}</p>
        </div>
        <div className="decision-card">
          <span>완료 단계</span>
          <strong>{analysis.completedSteps}/{analysis.totalSteps}</strong>
          <p>감지부터 복귀까지 기록된 단계 수</p>
        </div>
        <div className="decision-card">
          <span>전체 대응 시간</span>
          <strong>{formatDuration(analysis.totalDurationMs)}</strong>
          <p>감지 이벤트부터 도킹 완료까지</p>
        </div>
        <div className={attentionCount > 0 ? 'decision-card danger' : 'decision-card success'}>
          <span>점검 필요 항목</span>
          <strong>{attentionCount}건</strong>
          <p>{attentionCount > 0 ? '누락 또는 순서 오류가 있습니다.' : '기록된 흐름이 정상입니다.'}</p>
        </div>
      </div>

      <section className="report-section">
        <div className="section-heading-row">
          <div>
            <h2>동작별 기록 상태</h2>
            <p className="helper-text">각 동작이 발생했는지와 기록 시간이 정상적으로 남았는지 확인합니다.</p>
          </div>
          {analysis.isResolved ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
        </div>

        <div className="operation-step-grid">
          {analysis.steps.map((step) => (
            <div className="operation-step-card" key={step.key}>
              <div className="operation-step-index">{step.index + 1}</div>
              <div>
                <div className="operation-step-title">
                  <strong>{step.label}</strong>
                  <StepStatusBadge status={step.status} />
                </div>
                <p>{step.description}</p>
                <time>{formatDateTime(step.rawValue)}</time>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="report-section">
        <div className="section-heading-row">
          <div>
            <h2>다음 동작까지 소요 시간</h2>
            <p className="helper-text">앞 단계가 완료된 뒤 다음 단계가 기록되기까지 걸린 시간을 계산합니다.</p>
          </div>
          <Clock3 size={22} />
        </div>

        <div className="transition-list">
          {analysis.transitions.map((transition) => (
            <div className="transition-row" key={transition.label}>
              <div className="transition-title">
                <TimerReset size={18} />
                <div>
                  <strong>{transition.label}</strong>
                  <span>{transition.fromLabel} 이후 {transition.toLabel}까지</span>
                </div>
              </div>
              <div className="transition-result">
                <strong>{formatDuration(transition.durationMs)}</strong>
                <TransitionStatusBadge status={transition.status} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
