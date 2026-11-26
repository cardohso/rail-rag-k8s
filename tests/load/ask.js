// Load test for POST /ask, run inside the cluster by scripts/k6-run.sh.
// Env: TARGET (base URL), STAGES (JSON list of {duration, target} for ramping VUs),
//      THINK_MS (pause between a VU's requests, default 0), RUN_NAME (label for the summary).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const TARGET = __ENV.TARGET || 'http://rail-rag-api.rail.svc';
const STAGES = JSON.parse(__ENV.STAGES || '[{"duration":"30s","target":2}]');
const THINK = Number(__ENV.THINK_MS || 0) / 1000;

// In-scope questions: each passes the retrieval floor, so it costs the full three generator calls.
const QUESTIONS = [
  'What are the requirements for wheelchair spaces in a passenger train?',
  'How many wheelchair spaces must a unit longer than 205 metres have?',
  'What does the PRM TSI require for the width of doors?',
  'What are the requirements for emergency exits in railway tunnels?',
  'What does the SRT TSI say about fire safety of rolling stock in tunnels?',
  'What are the pass-by noise limits for freight wagons?',
  'What is the stationary noise limit for electric locomotives?',
  'What does the CCS TSI say about ETCS on-board equipment?',
  'What are the requirements for the train radio GSM-R?',
  'What does the energy TSI say about the mean useful voltage?',
  'What are the obligations of the railway undertaking for train composition?',
  'What does the Interoperability Directive say about authorisation for placing vehicles on the market?',
];

export const options = {
  scenarios: { load: { executor: 'ramping-vus', startVUs: 0, stages: STAGES, gracefulRampDown: '30s' } },
  // A new connection per request, so kube-proxy spreads requests over every pod, including pods
  // added by the autoscaler mid-run. With keep-alive, each VU stays pinned to the pod it first
  // reached and new pods would sit idle (docs/DESIGN.md D17).
  noConnectionReuse: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const answered = new Counter('ask_answered');
const refused = new Counter('ask_refused');

export default function () {
  const q = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const res = http.post(`${TARGET}/ask`, JSON.stringify({ question: q }), {
    headers: { 'Content-Type': 'application/json' },
    timeout: '30s',
    tags: { name: 'ask' },
  });
  const ok = check(res, { 'status is 200': (r) => r.status === 200 });
  if (!ok) {
    // One line per failure, kept in <run>.k6.log: status 0 with an error_code means the request
    // never got an HTTP answer (connect, reset or timeout), which Prometheus cannot see.
    console.warn('ASK_FAIL ' + JSON.stringify({
      t: new Date().toISOString(), vu: __VU, status: res.status, error: res.error,
      error_code: res.error_code, ms: Math.round(res.timings.duration),
    }));
  }
  if (ok) {
    if (res.json('refused')) refused.add(1); else answered.add(1);
  }
  if (THINK > 0) sleep(THINK);
}

export function handleSummary(data) {
  const out = { run: __ENV.RUN_NAME || 'unnamed', stages: STAGES, metrics: data.metrics };
  return { stdout: '\n===K6_SUMMARY_BEGIN===\n' + JSON.stringify(out) + '\n===K6_SUMMARY_END===\n' };
}
