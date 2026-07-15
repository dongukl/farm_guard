import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, CheckCircle2, Database, FileText, RefreshCcw, Timer } from 'lucide-react';
import { fetchSavedReports } from '../api/statusApi.js';
import { formatDateTime } from '../utils/formatDate.js';
import {
  buildReportAnalytics,
  formatDurationCompact,
  getReportStatusClass,
  getReportStatusLabel
} from '../utils/reportAnalysis.js';

function MetricCard({ icon: Icon, label, value, hint, tone = 'neutral' }) {
  return (
    <div className={`analytics-metric ${tone}`}>
      <div className="analytics-metric-icon">
        <Icon size={20} />
      </div>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{hint}</p>
    </div>
  );
}

const CHART_PERIODS = [
  { id: 'year', label: '연도별' },
  { id: 'month', label: '월별' },
  { id: 'day', label: '일별' }
];

function buildYAxisScale(rawMax) {
  const baseMax = Math.max(1, rawMax);

  if (baseMax <= 4) {
    return {
      max: baseMax,
      ticks: Array.from({ length: baseMax + 1 }, (_, index) => baseMax - index)
    };
  }

  const step = Math.ceil(baseMax / 4);
  const max = step * 4;

  return {
    max,
    ticks: [max, max - step, max - step * 2, max - step * 3, 0]
  };
}

function PeriodBarChart({ title, description, data, emptyText }) {
  const maxValue = Math.max(
    ...data.flatMap((item) => [item.resolved, item.needsAttention]),
    0
  );
  const yAxis = buildYAxisScale(maxValue);

  return (
    <article className="card analytics-chart-card">
      <div className="card-title-row">
        <div>
          <h2>{title}</h2>
          <p className="helper-text">{description}</p>
        </div>
      </div>

      {data.length === 0 && (
        <div className="empty-state">
          <strong>{emptyText}</strong>
          <span>통합 보고서를 저장하면 이 영역에 그래프가 표시됩니다.</span>
        </div>
      )}

      <div className="bar-chart-legend">
        <span className="legend-dot resolved">해결 완료</span>
        <span className="legend-dot attention">점검 필요</span>
      </div>

      {data.length > 0 && (
        <div className="axis-chart">
          <div className="y-axis-title">사건 수</div>
          <div className="y-axis">
            {yAxis.ticks.map((tick) => (
              <span key={tick}>{tick}</span>
            ))}
          </div>
          <div className="axis-plot">
            <div className="grid-lines" aria-hidden="true">
              {yAxis.ticks.map((tick) => (
                <span key={tick} />
              ))}
            </div>

            <div className="period-bar-chart">
              {data.map((item) => {
                const resolvedHeight = item.resolved > 0 ? Math.max((item.resolved / yAxis.max) * 100, 4) : 0;
                const attentionHeight = item.needsAttention > 0 ? Math.max((item.needsAttention / yAxis.max) * 100, 4) : 0;

                return (
                  <div className="period-bar-group" key={item.label}>
                    <div className="period-bars" aria-label={`${item.label} 해결 ${item.resolved}건 점검 ${item.needsAttention}건`}>
                      <div className="period-bar resolved" style={{ height: `${resolvedHeight}%` }}>
                        {item.resolved > 0 && <span>{item.resolved}</span>}
                      </div>
                      <div className="period-bar attention" style={{ height: `${attentionHeight}%` }}>
                        {item.needsAttention > 0 && <span>{item.needsAttention}</span>}
                      </div>
                    </div>
                    <div className="period-bar-label">
                      <strong>{item.label}</strong>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="x-axis-title">기간</div>
          </div>
        </div>
      )}
    </article>
  );
}

export default function ReportAnalyticsPage() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [chartPeriod, setChartPeriod] = useState('month');

  const loadReports = useCallback(async () => {
    // 저장된 보고서 전체를 읽어 와서 분석 유틸이 다시 집계할 수 있게 한다.
    setLoading(true);
    setError('');

    try {
      const list = await fetchSavedReports();
      setReports(list);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 페이지 진입 시 한 번 목록을 읽고, 새로고침 버튼도 같은 함수를 쓴다.
    loadReports();
  }, [loadReports]);

  // buildReportAnalytics는 저장 보고서를 연/월/일 집계와 점검 필요 목록으로 바꾼다.
  const analytics = useMemo(() => buildReportAnalytics(reports), [reports]);
  const dailyData = analytics.byDay.slice(-20);
  const monthlyData = analytics.byMonth.slice(-12);
  const attentionReports = analytics.attentionReports.slice(0, 8);
  const chartOptions = {
    year: {
      title: '연도별 사건 처리 현황',
      description: '각 연도에 해결 완료와 점검 필요 사건이 얼마나 있었는지 비교합니다.',
      data: analytics.byYear,
      emptyText: '연도별 집계할 사건이 없습니다.'
    },
    month: {
      title: '월별 사건 처리 현황',
      description: '최근 12개 월의 해결 완료와 점검 필요 사건 수를 한 그래프에서 확인합니다.',
      data: monthlyData,
      emptyText: '월별 집계할 사건이 없습니다.'
    },
    day: {
      title: '일별 사건 처리 현황',
      description: '최근 20개 일자의 해결 완료와 점검 필요 사건 수를 상세하게 확인합니다.',
      data: dailyData,
      emptyText: '일별 집계할 사건이 없습니다.'
    }
  };
  const activeChart = chartOptions[chartPeriod];

  if (loading) return <div className="card">보고서 분석 데이터를 불러오는 중입니다.</div>;

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Report Analytics</p>
          <h2>보고서 분석 화면</h2>
          <p>저장된 통합 보고서를 기준으로 사건 수, 해결 여부, 점검 필요 흐름을 집계합니다.</p>
        </div>
        <div className="button-row">
          <button className="secondary-button icon-button-text" onClick={loadReports} disabled={loading}>
            <RefreshCcw size={16} />
            새로고침
          </button>
          <Link className="secondary-button link-button" to="/report">
            <FileText size={16} />
            통합 보고서
          </Link>
        </div>
      </div>

      {error && <div className="card error-box">분석 데이터 조회 실패: {error}</div>}

      <div className="analytics-metric-grid">
        <MetricCard
          icon={Database}
          label="저장 보고서"
          value={`${analytics.totals.savedReports}건`}
          hint="SQLite에 저장된 전체 보고서"
        />
        <MetricCard
          icon={Activity}
          label="감지 사건"
          value={`${analytics.totals.incidents}건`}
          hint="웹캠 또는 AMR 이벤트가 기록된 보고서"
          tone="info"
        />
        <MetricCard
          icon={CheckCircle2}
          label="해결 완료"
          value={`${analytics.totals.resolved}건`}
          hint="감지부터 복귀까지 모든 단계가 정상 기록"
          tone="success"
        />
        <MetricCard
          icon={AlertTriangle}
          label="점검 필요"
          value={`${analytics.totals.needsAttention}건`}
          hint="단계 누락, 미완료 또는 순서 오류"
          tone={analytics.totals.needsAttention > 0 ? 'danger' : 'success'}
        />
        <MetricCard
          icon={Timer}
          label="평균 해결 시간"
          value={formatDurationCompact(analytics.totals.averageResolutionMs)}
          hint="정상 완료된 사건 기준"
        />
      </div>

      <article className="analytics-period-panel">
        <div className="segmented-control" role="tablist" aria-label="그래프 기간 선택">
          {CHART_PERIODS.map((period) => (
            <button
              aria-selected={chartPeriod === period.id}
              className={chartPeriod === period.id ? 'active' : ''}
              key={period.id}
              onClick={() => setChartPeriod(period.id)}
              role="tab"
              type="button"
            >
              {period.label}
            </button>
          ))}
        </div>

        <PeriodBarChart
          title={activeChart.title}
          description={activeChart.description}
          data={activeChart.data}
          emptyText={activeChart.emptyText}
        />
      </article>

      <article className="card">
        <div className="card-title-row">
          <div>
            <h2>점검 필요 보고서</h2>
            <p className="helper-text">저장된 보고서 중 단계 누락, 미완료, 순서 오류가 있는 항목입니다.</p>
          </div>
        </div>

        {attentionReports.length === 0 ? (
          <div className="empty-state">
            <strong>점검 필요 보고서가 없습니다.</strong>
            <span>현재 저장된 사건은 모두 정상 완료됐거나 아직 사건으로 집계되지 않았습니다.</span>
          </div>
        ) : (
          <div className="attention-table">
            {attentionReports.map((item) => (
              <div className="attention-row" key={item.id}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{formatDateTime(item.created_at)}</span>
                </div>
                <span className={`status-badge ${getReportStatusClass(item.analysis.status)}`}>
                  {getReportStatusLabel(item.analysis.status, 'saved')}
                </span>
                <Link className="secondary-button small link-button" to="/saved-reports">
                  상세 확인
                </Link>
              </div>
            ))}
          </div>
        )}
      </article>
    </div>
  );
}
