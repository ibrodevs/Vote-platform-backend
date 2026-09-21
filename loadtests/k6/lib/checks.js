// Общие проверки ответов.
//
// Главное различие, которое здесь проводится: ошибка инфраструктуры против
// ожидаемого бизнес-ответа. ТЗ п.86 требует держать неожиданные 5xx ниже
// 0.1%, но 400 already_voted — это корректная работа системы, а не сбой,
// и смешивать их значило бы либо скрыть аварию, либо поднять ложную тревогу.

import { Counter, Rate, Trend } from 'k6/metrics';
import { check } from 'k6';

export const serverErrors = new Rate('server_errors');
export const businessRejections = new Counter('business_rejections');
export const votesAccepted = new Counter('votes_accepted');
export const votesAlreadyVoted = new Counter('votes_already_voted');
export const throttled = new Counter('throttled');
export const voteDuration = new Trend('vote_duration', true);

export function checkRead(response, name) {
  const ok = response.status === 200;
  serverErrors.add(response.status >= 500);
  check(response, { [`${name}: 200`]: () => ok });
  return ok;
}

export function classifyVote(response) {
  serverErrors.add(response.status >= 500);
  voteDuration.add(response.timings.duration);

  if (response.status === 200) {
    votesAccepted.add(1);
    return 'accepted';
  }
  if (response.status === 429) {
    // Троттлинг на нагрузочном прогоне означает, что забыли
    // RATE_LIMIT_ENABLED=False: измеряется троттлер, а не приложение
    throttled.add(1);
    return 'throttled';
  }
  if (response.status === 400) {
    // Разбирается только код ошибки, но НЕ тело запроса
    let code = 'unknown';
    try {
      code = response.json('error.code') || 'unknown';
    } catch (e) { /* тело не JSON */ }
    if (code === 'already_voted') {
      votesAlreadyVoted.add(1);
    } else {
      businessRejections.add(1);
    }
    return code;
  }
  return `http_${response.status}`;
}
