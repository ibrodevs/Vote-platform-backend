// Общая конфигурация сценариев k6.
//
// ЦЕЛЕВОЙ RPS ПАРАМЕТРИЗУЕМ. Ступени до 40k из ТЗ п.79 описаны в профилях
// и запускаются на настоящей инфраструктуре; на машине разработчика
// используется масштаб, который она выдерживает, — генератор нагрузки
// делит с приложением те же ядра и сам становится узким местом (ТЗ п.109).

export const BASE_URL = __ENV.BASE_URL || 'http://web:8000';

export const TARGET_RPS = Number(__ENV.TARGET_RPS || 200);
export const DURATION = __ENV.DURATION || '30s';
export const RAMP_UP = __ENV.RAMP_UP || '10s';
export const VUS = Number(__ENV.VUS || 50);
export const MAX_VUS = Number(__ENV.MAX_VUS || 300);

// Пороги из ТЗ п.85 и п.86. Заданы именно порогами k6: прогон,
// не уложившийся в них, обязан завершиться неуспехом, а не «в целом неплохо».
export const SLO = {
  cachedReadP95: Number(__ENV.SLO_CACHED_READ_MS || 250),
  authReadP95: Number(__ENV.SLO_AUTH_READ_MS || 300),
  voteP95: Number(__ENV.SLO_VOTE_MS || 500),
  // ТЗ п.86: неожиданные 5xx меньше 0.1%. Бизнес-ответы 4xx
  // (already_voted и т.п.) ошибками инфраструктуры не считаются.
  maxServerErrorRate: Number(__ENV.SLO_ERROR_RATE || 0.001),
};

// Данные готовит `manage.py export_loadtest_fixtures`
export function loadFixtures() {
  const path = __ENV.FIXTURES || '/fixtures/loadtest.json';
  return JSON.parse(open(path));
}

// Тело запроса и токены НИКОГДА не попадают в вывод k6:
// в теле POST /vote — выбор студента (ТЗ п.4).
export function authHeaders(token) {
  return { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
}

export const jsonHeaders = { headers: { 'Content-Type': 'application/json' } };


// Выборы группируются по вузу.
//
// ЗАЧЕМ ЭТО ОБЯЗАТЕЛЬНО: студент может голосовать только в выборах своего
// университета. Если брать студента и выборы независимо, подавляющее
// большинство запросов вернёт ineligible_student, и профиль будет мерить
// скорость отказов, а не голосования — притом выглядеть «успешным»,
// потому что 400 это не ошибка сервера.
export function indexElectionsByUniversity(fixtures) {
  const index = {};
  for (const election of fixtures.elections) {
    if (!election.candidates || election.candidates.length === 0) continue;
    (index[election.university_id] = index[election.university_id] || []).push(election);
  }
  return index;
}

// Студент, для которого есть выборы его вуза. Студенты без подходящих
// выборов пропускаются: иначе они дали бы те же ложные отказы.
export function pickEligible(fixtures, index, seed) {
  const students = fixtures.students;
  for (let attempt = 0; attempt < 20; attempt++) {
    const student = students[(seed + attempt * 7919) % students.length];
    const elections = index[student.university_id];
    if (elections && elections.length) {
      return { student, election: elections[seed % elections.length] };
    }
  }
  return null;
}
