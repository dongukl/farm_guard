// 보고서 분석은 status_event의 최신 5단계를 기준으로 진행도와 누락 여부를 계산한다.
export const REPORT_STEPS = [
  {
    key: 'tower_detected_at',
    label: '감지',
    description: '경계 타워/웹캠이 유해동물 감지를 기록했습니다.'
  },
  {
    key: 'undock_at',
    label: '충전 도크 분리 및 출동',
    description: 'AMR이 충전 도크에서 분리되어 현장 출동을 시작했습니다.'
  },
  {
    key: 'herding_active_at',
    label: '퇴치 시작',
    description: 'AMR이 현장에서 퇴치 동작을 시작했습니다.'
  },
  {
    key: 'mission_complete_at',
    label: '야생동물 퇴치 완료 · 복귀 시작',
    description: '야생동물 퇴치가 완료되어 로봇이 대기 좌표 복귀를 시작했습니다.'
  },
  {
    key: 'dock_complete_at',
    label: '도킹 완료 및 충전 대기',
    description: 'AMR이 도킹을 마치고 충전 대기 상태로 전환됐습니다.'
  }
];

// 각 단계 사이의 시간 차이를 계산해서 다음 동작이 제때 이어졌는지 본다.
export const REPORT_TRANSITIONS = REPORT_STEPS.slice(0, -1).map((step, index) => ({
  fromKey: step.key,
  toKey: REPORT_STEPS[index + 1].key,
  fromLabel: step.label,
  toLabel: REPORT_STEPS[index + 1].label,
  label: `${step.label} -> ${REPORT_STEPS[index + 1].label}`
}));

export function parseReportDate(value) {
  // 저장된 ISO 문자열을 Date로 바꿔서 계산 가능한 값으로 만든다.
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDuration(ms) {
  // 음수는 순서 오류로 처리하고, 나머지는 사람이 읽기 쉬운 단위로 바꾼다.
  if (ms === null || ms === undefined) return '-';
  if (ms < 0) return '순서 오류';

  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}시간 ${minutes}분 ${seconds}초`;
  if (minutes > 0) return `${minutes}분 ${seconds}초`;
  return `${seconds}초`;
}

export function formatDurationCompact(ms) {
  // 표나 칩처럼 좁은 곳에 표시할 짧은 시간 포맷이다.
  if (ms === null || ms === undefined) return '-';
  if (ms < 0) return '오류';

  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function hasLaterCompletedStep(report, stepIndex) {
  // 뒤 단계가 먼저 기록된 경우 현재 단계가 누락됐다고 판단할 수 있다.
  return REPORT_STEPS.slice(stepIndex + 1).some((step) => parseReportDate(report?.[step.key]));
}

export function analyzeReport(report) {
  // 저장된 report snapshot 하나를 보고 정상/미완료/순서오류를 계산한다.
  const source = report || {};
  const steps = REPORT_STEPS.map((step, index) => {
    const occurredAt = parseReportDate(source[step.key]);
    const isMissingBeforeLaterStep = !occurredAt && hasLaterCompletedStep(source, index);

    return {
      ...step,
      index,
      occurredAt,
      rawValue: source[step.key] || null,
      status: occurredAt ? 'done' : isMissingBeforeLaterStep ? 'missing' : 'waiting'
    };
  });

  const transitions = REPORT_TRANSITIONS.map((transition) => {
    const fromAt = parseReportDate(source[transition.fromKey]);
    const toAt = parseReportDate(source[transition.toKey]);

    if (!fromAt && !toAt) {
      return { ...transition, status: 'not_started', durationMs: null };
    }

    if (!fromAt && toAt) {
      return { ...transition, status: 'invalid', durationMs: null };
    }

    if (fromAt && !toAt) {
      return { ...transition, status: 'waiting', durationMs: null };
    }

    const durationMs = toAt.getTime() - fromAt.getTime();
    return {
      ...transition,
      status: durationMs >= 0 ? 'done' : 'invalid',
      durationMs
    };
  });

  const completedSteps = steps.filter((step) => step.status === 'done').length;
  const hasIncident = completedSteps > 0;
  // missingSteps와 invalidTransitions가 분석 화면의 "점검 필요" 목록을 만든다.
  const missingSteps = steps.filter((step) => step.status === 'missing');
  const invalidTransitions = transitions.filter((transition) => transition.status === 'invalid');
  const allStepsDone = completedSteps === REPORT_STEPS.length;
  const isResolved = hasIncident && allStepsDone && missingSteps.length === 0 && invalidTransitions.length === 0;
  const firstStepAt = steps[0].occurredAt;
  const lastStepAt = steps[steps.length - 1].occurredAt;
  const totalDurationMs = firstStepAt && lastStepAt ? lastStepAt.getTime() - firstStepAt.getTime() : null;

  let status = 'standby';
  if (invalidTransitions.length > 0 || missingSteps.length > 0 || (totalDurationMs !== null && totalDurationMs < 0)) {
    status = 'invalid';
  } else if (isResolved) {
    status = 'resolved';
  } else if (hasIncident) {
    status = 'incomplete';
  }

  return {
    status,
    scenarioStatus: source.scenario_status || '대기',
    hasIncident,
    isResolved,
    needsAttention: status === 'invalid' || status === 'incomplete',
    completedSteps,
    totalSteps: REPORT_STEPS.length,
    missingSteps,
    invalidTransitions,
    steps,
    transitions,
    totalDurationMs: totalDurationMs !== null && totalDurationMs >= 0 ? totalDurationMs : null
  };
}

export function getReportStatusLabel(status, mode = 'saved') {
  // live 화면과 saved 화면에서 같은 판정 결과를 조금 다르게 표현한다.
  if (status === 'resolved') return '정상 완료';
  if (status === 'invalid') return '동작 이상';
  if (status === 'incomplete') return mode === 'live' ? '진행 중' : '점검 필요';
  return '대기';
}

export function getReportStatusClass(status) {
  // 판정 결과를 카드 색상 클래스와 연결한다.
  if (status === 'resolved') return 'success';
  if (status === 'invalid') return 'danger';
  if (status === 'incomplete') return 'warning';
  return 'neutral';
}

export function getIncidentDate(report, fallbackDate) {
  // 사건이 시작된 날짜를 우선 보고서의 첫 감지 시각에서 찾는다.
  return (
    parseReportDate(report?.tower_detected_at)
    || parseReportDate(fallbackDate)
    || null
  );
}

function makeEmptyBucket(label) {
  // 기간별 집계 버킷의 기본 모양이다.
  return {
    label,
    total: 0,
    resolved: 0,
    needsAttention: 0
  };
}

function addToBucket(bucket, analysis) {
  // resolved / needsAttention을 기간 집계에 누적한다.
  bucket.total += 1;
  if (analysis.isResolved) {
    bucket.resolved += 1;
  } else if (analysis.needsAttention) {
    bucket.needsAttention += 1;
  }
}

function buildGroupedStats(items, formatter) {
  // 연/월/일 기준으로 보고서를 묶어 차트용 통계를 만든다.
  const grouped = new Map();

  items.forEach((item) => {
    if (!item.incidentDate) return;

    const label = formatter(item.incidentDate);
    if (!grouped.has(label)) {
      grouped.set(label, makeEmptyBucket(label));
    }
    addToBucket(grouped.get(label), item.analysis);
  });

  return Array.from(grouped.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function average(values) {
  // 숫자 배열의 평균을 계산한다. 빈 배열이면 null로 둔다.
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function buildReportAnalytics(savedReports) {
  // 저장된 보고서 목록 전체를 분석용 보고서 + 집계값으로 바꾼다.
  const analyzedReports = (savedReports || []).map((savedReport) => {
    const report = savedReport.report || savedReport;
    const analysis = analyzeReport(report);
    return {
      ...savedReport,
      report,
      analysis,
      incidentDate: getIncidentDate(report, savedReport.created_at)
    };
  });

  const incidentReports = analyzedReports.filter((item) => item.analysis.hasIncident);
  const resolvedReports = incidentReports.filter((item) => item.analysis.isResolved);
  const attentionReports = incidentReports.filter((item) => item.analysis.needsAttention);
  const durationValues = resolvedReports
    .map((item) => item.analysis.totalDurationMs)
    .filter((value) => value !== null && value !== undefined);

  return {
    reports: analyzedReports,
    attentionReports,
    totals: {
      savedReports: analyzedReports.length,
      incidents: incidentReports.length,
      resolved: resolvedReports.length,
      needsAttention: attentionReports.length,
      averageResolutionMs: average(durationValues)
    },
    byYear: buildGroupedStats(
      incidentReports,
      (date) => `${date.getFullYear()}`
    ),
    byMonth: buildGroupedStats(
      incidentReports,
      (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    ),
    byDay: buildGroupedStats(
      incidentReports,
      (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    )
  };
}
