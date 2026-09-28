/* Unit tests for the team to-do lists' pure helpers ($lib/tasks.js).

   Run:  cd ui && npm test

   Every date is built with local Date methods, so the expectations hold in
   any TZ. NOW is Wednesday 30 Sep 2026, 09:30 local. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  localDay, addDays, weekStart, dueState, dueLabel, splitDone, liveOrder,
  focusTasks, boardColumns, fromLine, propertyHref, toAnnounce, inboxMessage, parseTs, doneLabel
} from '../src/lib/tasks.js';

const NOW = new Date(2026, 8, 30, 9, 30);
const TODAY = localDay(NOW);
const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
const task = (o) => ({ id: 1, user_id: 1, created_by: 1, title: 't', status: 'open', due_date: null, priority: 2, ...o });

test('localDay and addDays walk the calendar', () => {
  assert.equal(TODAY, '2026-09-30');
  assert.equal(addDays(TODAY, 1), '2026-10-01');
  assert.equal(addDays('2026-03-01', -1), '2026-02-28');
});

test('weekStart is local Monday midnight', () => {
  const ws = weekStart(NOW);
  assert.equal(ws.getDay(), 1);
  assert.equal(localDay(ws), '2026-09-28');
  assert.equal(localDay(weekStart(new Date(2026, 9, 4, 23))), '2026-09-28'); // Sunday → the Monday before
});

test('parseTs reads both server formats as UTC', () => {
  assert.equal(parseTs('2026-09-28T10:00:00Z').toISOString(), '2026-09-28T10:00:00.000Z');
  assert.equal(parseTs('2026-09-28 10:00:00').toISOString(), '2026-09-28T10:00:00.000Z');
  assert.equal(parseTs(null), null);
  assert.equal(parseTs('nonsense'), null);
});

test('dueState and dueLabel', () => {
  assert.equal(dueState(task({ due_date: '2026-09-29' }), TODAY), 'overdue');
  assert.equal(dueState(task({ due_date: TODAY }), TODAY), 'today');
  assert.equal(dueState(task({ due_date: '2026-10-01' }), TODAY), 'tomorrow');
  assert.equal(dueState(task({ due_date: '2026-10-09' }), TODAY), 'later');
  assert.equal(dueState(task({ due_date: '2026-09-01', status: 'done' }), TODAY), null);
  assert.equal(dueState(task({}), TODAY), null);
  assert.equal(dueLabel(task({ due_date: '2026-09-29' }), TODAY), 'Overdue · since yesterday');
  assert.equal(dueLabel(task({ due_date: '2026-09-25' }), TODAY), 'Overdue · 5 days');
  assert.equal(dueLabel(task({ due_date: TODAY }), TODAY), 'Due today');
  assert.equal(dueLabel(task({ due_date: '2026-10-02' }), TODAY), 'Due Fri 2 Oct');
  assert.equal(dueLabel(task({ due_date: '2026-10-20' }), TODAY), 'Due 20 Oct');
});

test('splitDone buckets by the local week, newest first', () => {
  const mon = new Date(2026, 8, 28, 8);   // this Monday 08:00 local
  const sun = new Date(2026, 8, 27, 20);  // last Sunday 20:00 local
  const tue = new Date(2026, 8, 29, 12);
  const tasks = [
    task({ id: 1, status: 'done', done_at: iso(mon) }),
    task({ id: 2, status: 'done', done_at: iso(sun) }),
    task({ id: 3, status: 'done', done_at: iso(tue) }),
    task({ id: 4, status: 'open' })
  ];
  const { thisWeek, earlier } = splitDone(tasks, NOW);
  assert.deepEqual(thisWeek.map((t) => t.id), [3, 1]);
  assert.deepEqual(earlier.map((t) => t.id), [2]);
});

test('liveOrder: in progress, overdue, today, then by date and priority', () => {
  const tasks = [
    task({ id: 1, due_date: '2026-10-05' }),
    task({ id: 2, due_date: TODAY }),
    task({ id: 3, status: 'in_progress' }),
    task({ id: 4, due_date: '2026-09-20' }),
    task({ id: 5 }),
    task({ id: 6, due_date: '2026-10-05', priority: 1 }),
    task({ id: 7, status: 'done' })
  ];
  assert.deepEqual(liveOrder(tasks, TODAY).map((t) => t.id), [3, 4, 2, 6, 1, 5]);
});

test('focusTasks keeps what needs doing now, plus anything new', () => {
  const tasks = [
    task({ id: 1, due_date: '2026-10-05' }),
    task({ id: 2, due_date: TODAY }),
    task({ id: 3, status: 'in_progress' }),
    task({ id: 4, due_date: '2026-09-20' }),
    task({ id: 5, new: true }),
    task({ id: 6 })
  ];
  assert.deepEqual(focusTasks(tasks, TODAY).map((t) => t.id), [3, 4, 2, 5]);
});

test('boardColumns splits a person into open / in progress / done this week', () => {
  const tasks = [
    task({ id: 1 }), task({ id: 2, status: 'in_progress' }),
    task({ id: 3, status: 'done', done_at: iso(new Date(2026, 8, 29, 9)) }),
    task({ id: 4, status: 'done', done_at: iso(new Date(2026, 8, 20, 9)) })
  ];
  const c = boardColumns(tasks, NOW);
  assert.deepEqual(c.open.map((t) => t.id), [1]);
  assert.deepEqual(c.in_progress.map((t) => t.id), [2]);
  assert.deepEqual(c.doneWeek.map((t) => t.id), [3]);
});

test('fromLine names who assigned it', () => {
  assert.equal(fromLine(task({ created_by: 1, user_id: 1 }), 1), '');
  assert.equal(fromLine(task({ created_by: 2, user_id: 1, created_by_name: 'Daniel' }), 1), 'from Daniel');
  assert.equal(fromLine(task({ created_by: 2, user_id: 3, created_by_name: 'Daniel' }), 2), 'from you');
});

test('propertyHref prefers the property page when it exists', () => {
  const p = { group_id: '42', listing_key: 'p24:123' };
  assert.equal(propertyHref(p, true), '/property/p24%3A123');
  assert.equal(propertyHref(p, false), '/leads/properties/42');
  assert.equal(propertyHref({ group_id: '42' }, true), '/leads/properties/42');
  assert.equal(propertyHref(null, true), null);
});

test('toAnnounce and inboxMessage', () => {
  const inbox = { tasks: [
    { id: 9, title: 'Call Blair Rd', created_by_name: 'Daniel' },
    { id: 7, title: 'Send film', created_by_name: 'Dylan' },
    { id: 5, title: 'Old', created_by_name: 'Daniel' }
  ] };
  assert.deepEqual(toAnnounce(inbox, 6).map((t) => t.id), [9, 7]);
  assert.deepEqual(toAnnounce(inbox, 9), []);
  assert.equal(inboxMessage(toAnnounce(inbox, 7)), 'Daniel gave you a task: Call Blair Rd');
  assert.equal(inboxMessage(toAnnounce(inbox, 0)), '3 new tasks from Daniel and Dylan');
  assert.equal(inboxMessage([]), '');
});

test('doneLabel reads in the viewer clock', () => {
  assert.equal(doneLabel(iso(new Date(2026, 8, 30, 8, 5)), NOW), '08:05');
  assert.equal(doneLabel(iso(new Date(2026, 8, 29, 18)), NOW), 'Yesterday');
  assert.equal(doneLabel(iso(new Date(2026, 8, 26, 18)), NOW), 'Sat');
  assert.equal(doneLabel(iso(new Date(2026, 8, 12, 18)), NOW), '12 Sep');
  assert.equal(doneLabel(null, NOW), '');
});
