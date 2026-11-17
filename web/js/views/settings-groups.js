// The groups of the settings page: one flat block per topic (heading, fields).
// Controls register with the form (settings-form.js); saving is done once by
// the page. Buttons in here only run actions (login test, update).

import { api, ApiError, errorMessage } from '../api.js';
import { h, empty } from '../dom.js';
import { age, numericDate, sameDay, time } from '../format.js';
import { accounts } from '../accounts.js';
import {
  autoColor, autoSubjectOf, getCourseOverrides, getCourses, getSubjectColors, getSubjects,
} from '../colors.js';
import { planValues, sortClasses } from '../substitution-filter.js';
import { SCHEMES, getScheme, setScheme } from '../scheme.js';
import { releaseNotes, waitForNewVersion } from '../update.js';
import { checkbox, field, input, messageArea, randomTopic, schoolPicker } from './forms.js';
import { bindCheck, bindText, stable } from './settings-form.js';

const byName = (a, b) => a.localeCompare(b, 'de');

/** A group: heading, optional hint, one card with the fields. */
export function group(id, titleText, hint, ...content) {
  return h('section', { class: 'settings-group', id },
    h('h2', { class: 'group-title' }, titleText),
    hint ? h('p', { class: 'hint' }, hint) : null,
    h('div', { class: 'card settings-form' }, content));
}

/** Label for a part of a group (not a heading: the hierarchy stays flat). */
const partLabel = (text, id) => h('div', { class: 'part-label', id }, text);

// --- Vertretungen (own class, filters) ---------------------------------------------

/**
 * The permanent filter of the substitution plan (stored on the server; applies to
 * Vertretungen, Heute and notifications).
 */
export function substitutionsGroup({ form, saved, plan }) {
  const parts = [];

  if (plan) {
    const filter = {
      classes: [...(saved?.classes ?? [])],
      showUnassigned: saved?.showUnassigned === true,
      hiddenTypes: [...(saved?.hiddenTypes ?? [])],
      hiddenNotices: [...(saved?.hiddenNotices ?? [])],
    };
    form.add('personal', 'substitutionFilter', () => stable(filter));
    const values = planValues(plan);

    // One class for now; a list saved earlier stays selectable as it is.
    const savedKey = filter.classes.join(', ');
    const classOptions = sortClasses([...new Set([...values.classes, ...(filter.classes.length === 1 ? filter.classes : [])])]);
    const classSelect = h('select', {
      id: 'sub-class', class: 'input class-select',
      onchange: (e) => {
        const val = e.target.value;
        filter.classes = val === '' ? [] : val === savedKey ? [...(saved?.classes ?? [])] : [val];
        renderAll();
      },
    },
    h('option', { value: '' }, 'Alle Klassen (ganzer Plan)'),
    filter.classes.length > 1 ? h('option', { value: savedKey, selected: true }, savedKey) : null,
    classOptions.map((c) => h('option', { value: c, selected: filter.classes.length === 1 && filter.classes[0] === c }, c)));

    const unassigned = h('input', {
      type: 'checkbox', id: 'sub-unassigned',
      onchange: (e) => {
        filter.showUnassigned = e.target.checked;
        renderAll();
      },
    });
    const typeChips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Ausgeblendete Arten' });
    const noticeChips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Ausgeblendete Hinweise' });
    const chips = (container, all, hidden) => container.replaceChildren(...all.map((t) => h('button', {
      type: 'button', class: 'chip pick', 'aria-pressed': String(hidden.includes(t)),
      onclick: () => {
        const i = hidden.indexOf(t);
        if (i >= 0) hidden.splice(i, 1); else hidden.push(t);
        renderAll();
      },
    }, t)));
    const renderAll = () => {
      chips(typeChips, [...new Set([...values.types, ...filter.hiddenTypes])].sort(byName), filter.hiddenTypes);
      chips(noticeChips, [...new Set([...values.notices, ...filter.hiddenNotices])].sort(byName), filter.hiddenNotices);
      unassigned.checked = filter.showUnassigned;
      unassigned.disabled = filter.classes.length === 0;
      form.touch();
    };
    renderAll();

    parts.push(
      h('div', { class: 'field' },
        h('label', { for: 'sub-class' }, 'Meine Klasse'),
        classSelect,
        h('span', { class: 'field-hint' },
          values.classes.length
            ? 'Vertretungen, Heute und Benachrichtigungen zeigen dann nur diese Klasse.'
            : 'Im aktuellen Plan stehen keine Klassen – die Auswahl füllt sich, sobald Vertretungen eingetragen sind.')),
      h('label', { class: 'check', for: 'sub-unassigned' }, unassigned,
        'Einträge ohne Klasse anzeigen (z. B. Pausenaufsicht, Betreuung)'),
      h('div', { class: 'field' },
        h('span', { class: 'field-label' }, 'Diese Arten ausblenden'),
        values.types.length || filter.hiddenTypes.length
          ? typeChips
          : h('span', { class: 'muted' }, 'Im aktuellen Plan stehen keine Arten.')),
      h('div', { class: 'field' },
        h('span', { class: 'field-label' }, 'Diese Hinweise ausblenden'),
        values.notices.length || filter.hiddenNotices.length
          ? noticeChips
          : h('span', { class: 'muted' }, 'Im aktuellen Plan stehen keine Hinweise.'),
        h('span', { class: 'field-hint' }, 'Hinweise wie „Allgemein“ stehen über den Vertretungen eines Tages.')),
    );
  }

  return group('vertretungsplan', 'Vertretungen',
    'Gilt auf allen Geräten, für das Kind dieses Reiters.', parts);
}

// --- Kalender (hidden entries) ----------------------------------------------------------------

/**
 * Calendar entries to hide by (part of) their title, e.g. the week markers „A-Woche“ and
 * „B-Woche“. Stored on the server like the substitution filter; [titles] are the titles of
 * the current calendar, offered while typing.
 */
export function calendarGroup({ form, saved, titles }) {
  const filter = { hiddenTitles: [...(saved?.hiddenTitles ?? [])] };
  form.add('personal', 'calendarFilter', () => stable(filter));

  const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Ausgeblendete Termine' });
  const text = input({ id: 'cal-hide-title', maxlength: '60', list: 'cal-hide-suggestions', placeholder: 'z. B. A-Woche' });
  const suggestions = h('datalist', { id: 'cal-hide-suggestions' },
    [...new Set(titles)].sort(byName).map((t) => h('option', { value: t })));
  const render = () => {
    chips.replaceChildren(...filter.hiddenTitles.map((t) => h('button', {
      type: 'button', class: 'chip pick', 'aria-pressed': 'true', title: 'Wieder anzeigen',
      onclick: () => {
        filter.hiddenTitles.splice(filter.hiddenTitles.indexOf(t), 1);
        render();
      },
    }, t)));
    form.touch();
  };
  const add = () => {
    const value = text.value.trim();
    if (!value) return;
    if (!filter.hiddenTitles.some((t) => t.toLowerCase() === value.toLowerCase()) && filter.hiddenTitles.length < 30) {
      filter.hiddenTitles.push(value);
    }
    text.value = '';
    render();
  };
  text.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault(); // Enter adds the term; it must not save the page
    add();
  });
  render();

  return group('kalender', 'Kalender',
    'Gilt auf allen Geräten, für das Kind dieses Reiters.',
    h('div', { class: 'field' },
      h('label', { for: 'cal-hide-title' }, 'Termine ausblenden, deren Titel enthält'),
      h('div', { class: 'inline-fields' }, text, suggestions,
        h('button', { type: 'button', class: 'button', onclick: add }, 'Hinzufügen')),
      h('span', { class: 'field-hint' },
        'Groß- und Kleinschreibung egal, z. B. „A-Woche“ und „B-Woche“. Ein Klick auf einen Begriff zeigt die Termine wieder an.')),
    chips);
}

// --- Schulessen ---------------------------------------------------------------------------

/** The balance warning of the school meals page (all children). The logins are part of each child. */
export function mealsGroup({ form, v }) {
  const warning = bindText(form, 'CASEDA_BALANCE_WARNING', input({
    type: 'text', inputmode: 'decimal', value: v.CASEDA_BALANCE_WARNING ?? '10,00',
    class: 'input narrow', pattern: '[0-9]+([,.][0-9]{1,2})?',
  }));
  return group('schulessen-hinweis', 'Schulessen',
    'Das Schulessen (Guthaben und bestellte Mahlzeiten) wird bei jedem Kind eingerichtet, im Reiter des Kindes. Bestellt wird weiterhin bei Caseda.',
    field('Hinweis bei Guthaben unter … €', warning, 'Gilt für alle Kinder.'));
}

// --- Fächer & Farben -----------------------------------------------------------------------

/** Subject colors and the course ↔ timetable subject assignment (staged until saved). */
export function colorsGroup({ form }) {
  const local = { subjectColors: getSubjectColors(), courseSubjects: getCourseOverrides() };
  form.add('personal', 'subjectColors', () => stable(local.subjectColors));
  form.add('personal', 'courseSubjects', () => stable(local.courseSubjects));

  const subjectOf = (c) => (c.id in local.courseSubjects ? local.courseSubjects[c.id] || null : autoSubjectOf(c.id));
  const keyOf = (c) => subjectOf(c) ?? c.name.trim();
  const colorOf = (key) => local.subjectColors[key] ?? autoColor(key);

  const list = h('ul', { class: 'color-list' });
  const resetAll = h('button', { class: 'button small', type: 'button' }, 'Alles automatisch');
  let counter = 0;

  const change = (fn) => {
    fn();
    renderList();
    form.touch();
  };

  const colorInput = (key, label) => {
    const id = `color-${++counter}`;
    return [id, h('input', {
      type: 'color', id, value: colorOf(key), 'aria-label': `Farbe für ${label}`,
      onchange: (e) => change(() => {
        local.subjectColors[key] = e.target.value;
      }),
    })];
  };
  const resetButton = (key) => (key in local.subjectColors
    ? h('button', {
      class: 'button small', type: 'button', title: `Automatische Farbe (${autoColor(key)})`,
      onclick: () => change(() => {
        delete local.subjectColors[key];
      }),
    }, 'Zurücksetzen')
    : h('span', { class: 'muted color-mode' }, 'automatisch'));

  const subjectSelect = (course) => {
    const auto = autoSubjectOf(course.id);
    const current = course.id in local.courseSubjects ? local.courseSubjects[course.id] : '__auto';
    const options = [
      ['__auto', `automatisch${auto ? ` (${auto})` : ' (keins gefunden)'}`],
      ...getSubjects().sort(byName).map((s) => [s, s]),
      ['', 'kein Stundenplan-Fach'],
    ];
    return h('select', {
      class: 'subject-select', 'aria-label': `Stundenplan-Fach für ${course.name}`,
      onchange: (e) => change(() => {
        if (e.target.value === '__auto') delete local.courseSubjects[course.id];
        else local.courseSubjects[course.id] = e.target.value;
      }),
    }, options.map(([value, label]) => h('option', { value, selected: value === current }, label)));
  };

  function renderList() {
    const courses = getCourses().sort((a, b) => byName(a.name, b.name));
    const mapped = new Set(courses.map(subjectOf).filter(Boolean));
    const unmapped = getSubjects().filter((s) => !mapped.has(s)).sort(byName);
    resetAll.hidden = Object.keys(local.subjectColors).length === 0 && Object.keys(local.courseSubjects).length === 0;

    const rows = courses.map((c) => {
      const key = keyOf(c);
      const [id, picker] = colorInput(key, c.name);
      return h('li', { class: 'color-row', style: { '--subject': colorOf(key) } },
        picker,
        h('div', { class: 'color-name' },
          h('label', { for: id }, c.name),
          h('div', { class: 'color-sub' }, 'Stundenplan: ', subjectSelect(c))),
        resetButton(key));
    });
    for (const s of unmapped) {
      const [id, picker] = colorInput(s, s);
      rows.push(h('li', { class: 'color-row', style: { '--subject': colorOf(s) } },
        picker,
        h('div', { class: 'color-name' },
          h('label', { for: id }, s),
          h('div', { class: 'color-sub muted' }, 'nur im Stundenplan, keinem Kurs zugeordnet')),
        resetButton(s)));
    }
    list.replaceChildren(...rows);
  }
  resetAll.addEventListener('click', () => change(() => {
    local.subjectColors = {};
    local.courseSubjects = {};
  }));
  renderList();

  const hasData = getCourses().length > 0 || getSubjects().length > 0;
  return group('farben', 'Fächer & Farben',
    'Jeder Kurs nutzt die Farbe seines Stundenplan-Fachs, damit Stundenplan, Fächer, Hausaufgaben und Noten gleich aussehen. Die Zuordnung zum Stundenplan-Kürzel wird automatisch erkannt und kann hier korrigiert werden. Gilt auf allen Geräten.',
    hasData ? [h('div', { class: 'button-row' }, resetAll), list] : empty('Keine Fächer gefunden.'));
}

// --- Benachrichtigungen (ntfy) -------------------------------------------------------------

export function notifyGroup({ form, v, secrets }) {
  const kinds = new Set(String(v.NOTIFY).split(',').filter(Boolean));
  const url = bindText(form, 'NTFY_URL', input({ type: 'url', value: v.NTFY_URL ?? 'https://ntfy.sh' }));
  const topic = bindText(form, 'NTFY_TOPIC', input({
    id: 'ntfy-topic', value: v.NTFY_TOPIC ?? '', pattern: '[-_A-Za-z0-9]{1,64}', placeholder: 'leer = keine Benachrichtigungen',
  }));
  const token = bindText(form, 'NTFY_TOKEN', input({
    type: 'password', autocomplete: 'off', placeholder: secrets.NTFY_TOKEN ? 'unverändert' : 'optional',
  }), { secret: true });
  const appUrl = bindText(form, 'APP_URL', input({ type: 'url', value: v.APP_URL ?? '', placeholder: 'z. B. http://192.168.1.50:8080' }));
  const checks = {
    substitutions: checkbox('Vertretungen', kinds.has('substitutions')),
    homework: checkbox('Hausaufgaben', kinds.has('homework')),
    grades: checkbox('Noten', kinds.has('grades')),
    errors: checkbox('Fehler beim Abgleich', kinds.has('errors')),
  };
  form.add('server', 'NOTIFY', () => Object.entries(checks).filter(([, c]) => c.box.checked).map(([k]) => k).join(','));
  const values = bindCheck(form, 'NOTIFY_GRADE_VALUES', checkbox('Note in der Benachrichtigung anzeigen', v.NOTIFY_GRADE_VALUES));
  const generate = h('button', {
    type: 'button', class: 'button small',
    onclick: () => {
      topic.value = randomTopic();
      form.touch();
    },
  }, 'Zufälliges Thema');

  return group('benachrichtigungen', 'Benachrichtigungen',
    'Push-Nachrichten aufs Handy mit der App ntfy: dort das gleiche Thema abonnieren. Auf ntfy.sh kann jeder mitlesen, der das Thema kennt – daher einen langen Zufallsnamen verwenden.',
    field('Server', url),
    h('div', { class: 'field' },
      h('label', { for: 'ntfy-topic' }, 'Thema'),
      h('div', { class: 'inline-fields' }, topic, generate)),
    field('Zugangstoken', token, secrets.NTFY_TOKEN ? 'Leer lassen, um das gespeicherte Token zu behalten.' : 'Nur für geschützte Themen nötig.'),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Benachrichtigen bei'),
      h('div', { class: 'inline-fields' }, Object.values(checks).map((c) => c.el)),
      h('span', { class: 'field-hint' }, 'Fehler beim Abgleich: eine Meldung, wenn ein Bereich dreimal hintereinander nicht geladen werden konnte, zum Beispiel weil das Schulportal seine Seiten geändert hat.')),
    values.el,
    field('Adresse der Web-Oberfläche', appUrl, 'Für Links in den Benachrichtigungen.'),
    h('p', { class: 'muted' }, h('a', { href: '/benachrichtigungen' }, 'Status und Testnachricht')));
}

// --- Abgleich -------------------------------------------------------------------------------

const TASKS = {
  substitutions: 'Vertretungen',
  homework: 'Hausaufgaben',
  lessons: 'Noten & Kursseiten',
  calendar: 'Kalender',
  timetable: 'Stundenplan',
  account: 'Konto',
  untis: 'WebUntis',
  meals: 'Schulessen',
};

export function syncGroup({ form, v, sync }) {
  const enabled = bindCheck(form, 'SYNC', checkbox('Daten im Hintergrund aktuell halten', v.SYNC));
  const fast = bindText(form, 'POLL_INTERVAL_MINUTES', input({ type: 'number', min: '5', max: '1440', value: v.POLL_INTERVAL_MINUTES, class: 'input narrow' }));
  const slow = bindText(form, 'GRADES_INTERVAL_MINUTES', input({ type: 'number', min: '30', max: '1440', value: v.GRADES_INTERVAL_MINUTES, class: 'input narrow' }));
  const calendar = bindText(form, 'CALENDAR_INTERVAL_MINUTES', input({ type: 'number', min: '15', max: '10080', value: v.CALENDAR_INTERVAL_MINUTES, class: 'input narrow' }));
  const timetable = bindText(form, 'TIMETABLE_INTERVAL_MINUTES', input({ type: 'number', min: '60', max: '10080', value: v.TIMETABLE_INTERVAL_MINUTES, class: 'input narrow' }));
  const meals = bindText(form, 'MEALS_INTERVAL_MINUTES', input({ type: 'number', min: '30', max: '10080', value: v.MEALS_INTERVAL_MINUTES, class: 'input narrow' }));
  const [fromHour, toHour] = String(v.ACTIVE_HOURS).split('-');
  const from = input({ type: 'number', min: '0', max: '23', value: fromHour, class: 'input narrow', 'aria-label': 'Von (Uhr)' });
  const to = input({ type: 'number', min: '1', max: '24', value: toHour, class: 'input narrow', 'aria-label': 'Bis (Uhr)' });
  form.add('server', 'ACTIVE_HOURS', () => `${from.value}-${to.value}`);

  const status = sync?.tasks ? h('dl', { class: 'facts sync-status' },
    Object.entries(TASKS).filter(([key]) => key in sync.tasks).map(([key, label]) => {
      const t = sync.tasks[key] ?? {};
      return [h('dt', null, label), h('dd', null,
        t.lastError ? h('span', { class: 'error-text' }, t.lastError, t.lastSuccess ? ` (zuletzt erfolgreich ${age(t.lastSuccess)})` : '')
          : t.lastSuccess ? `aktualisiert ${age(t.lastSuccess)}` : h('span', { class: 'muted' }, 'noch nicht'))];
    })) : null;

  return group('abgleich', 'Abgleich',
    'Der Server lädt die Daten regelmäßig, damit die Seiten sofort angezeigt werden. Kursseiten (Noten, alle Hausaufgaben) brauchen eine Anfrage pro Kurs und werden seltener geladen.',
    enabled.el,
    field('Vertretungen, Hausaufgaben und WebUntis alle … Minuten', fast, 'Mindestens 5.'),
    field('Noten und Kursseiten alle … Minuten', slow, 'Mindestens 30.'),
    field('Kalender alle … Minuten', calendar, 'Mindestens 15.'),
    field('Stundenplan und Konto alle … Minuten', timetable, 'Mindestens 60.'),
    field('Schulessen alle … Minuten', meals, 'Mindestens 30. Nur mit Caseda.'),
    h('div', { class: 'field' },
      h('span', { class: 'field-label' }, 'Nur zwischen'),
      h('div', { class: 'inline-fields' }, from, h('span', null, 'und'), to, h('span', null, 'Uhr'))),
    status ? h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Stand'), status) : null);
}

// --- Web-Oberfläche: Passwort, Netzwerk ------------------------------------------------------

export function accessGroup({ form, v, desktop }) {
  // New password: only used when something is typed.
  const current = input({ type: 'password', autocomplete: 'current-password' });
  const next = input({ type: 'password', autocomplete: 'new-password', minlength: '8' });
  const repeat = input({ type: 'password', autocomplete: 'new-password', minlength: '8' });
  form.add('password', 'appPassword', () => (current.value || next.value || repeat.value ? 'typed' : ''), { secret: true });
  form.validate(() => {
    if (!(current.value || next.value || repeat.value)) return null;
    if (!current.value) return 'Zum Ändern des Passworts bitte das aktuelle Passwort eingeben.';
    if (next.value.length < 8) return 'Das neue Passwort muss mindestens 8 Zeichen haben.';
    if (next.value !== repeat.value) return 'Die beiden neuen Passwörter stimmen nicht überein.';
    return null;
  });
  form.extra(() => (next.value ? { appPassword: next.value, currentPassword: current.value } : {}));
  form.onSaved(() => {
    for (const i of [current, next, repeat]) i.value = '';
  });

  const ttl = bindText(form, 'SESSION_TTL_DAYS', input({ type: 'number', min: '1', max: '3650', value: v.SESSION_TTL_DAYS, class: 'input narrow' }));

  const local = v.HOST === '127.0.0.1' || v.HOST === 'localhost' || v.HOST === '::1';
  const name = 'host-mode';
  const onlyHere = h('input', { type: 'radio', name, value: 'local', checked: local });
  const lan = h('input', { type: 'radio', name, value: 'lan', checked: !local });
  form.add('server', 'HOST', () => (onlyHere.checked ? '127.0.0.1' : '0.0.0.0'));
  const port = bindText(form, 'PORT', input({ type: 'number', min: '1024', max: '65535', value: v.PORT, class: 'input narrow' }));
  const secure = bindCheck(form, 'COOKIE_SECURE', checkbox('Nur über HTTPS (hinter einem Reverse-Proxy mit HTTPS)', v.COOKIE_SECURE));
  const proxy = bindCheck(form, 'TRUST_PROXY', checkbox('Hinter einem Reverse-Proxy (X-Forwarded-For auswerten)', v.TRUST_PROXY));
  const open = desktop ? bindCheck(form, 'OPEN_BROWSER', checkbox('Beim Start im Browser öffnen', v.OPEN_BROWSER)) : null;

  return group('netzwerk', 'Web-Oberfläche',
    'Passwort, Anmeldedauer und Erreichbarkeit. Netzwerk-Einstellungen gelten erst nach einem Neustart des Servers.',
    partLabel('Passwort ändern', 'passwort'),
    field('Aktuelles Passwort', current),
    field('Neues Passwort', next, 'Mindestens 8 Zeichen. Danach werden alle anderen Geräte abgemeldet.'),
    field('Neues Passwort wiederholen', repeat),
    partLabel('Zugang'),
    field('Anmeldung gültig für … Tage', ttl),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Erreichbar'),
      h('label', { class: 'check' }, onlyHere, 'Nur auf diesem Gerät'),
      h('label', { class: 'check' }, lan, 'Auch von anderen Geräten im Netzwerk (z. B. Handy)')),
    field('Port', port, 'Ab 1024. Ports darunter (z. B. 80) darf der Server unter Linux nicht öffnen und startet dann nicht mehr.'),
    secure.el,
    proxy.el,
    open?.el,
    partLabel('Farbschema'),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Farben dieses Geräts'),
      SCHEMES.map((s) => h('label', { class: 'check' },
        h('input', {
          type: 'radio', name: 'scheme', value: s.id, checked: getScheme() === s.id,
          onchange: () => setScheme(s.id),
        }), s.label)),
      h('small', { class: 'field-hint' }, 'Hell oder dunkel schaltet der Knopf oben in der Leiste um (sonst folgt es dem Gerät). Gilt nur für dieses Gerät, sofort ohne Speichern.')),
    partLabel('Abmelden'),
    h('p', { class: 'hint' }, 'Meldet nur dieses Gerät ab.'),
    h('div', null, h('button', {
      type: 'button', class: 'button',
      onclick: () => window.dispatchEvent(new Event('lumo:logout')),
    }, 'Abmelden')));
}

// --- Update ---------------------------------------------------------------------------------

/** Version, release notes and installing an update; [form] disables installing with unsaved changes. */
export function updateGroup({ form, v, status }) {
  const body = h('div', { class: 'stack' });
  const msg = messageArea();
  const check = h('button', { type: 'button', class: 'button' }, 'Nach Updates suchen');
  const install = h('button', { type: 'button', class: 'button primary' }, 'Jetzt aktualisieren');
  const auto = bindCheck(form, 'UPDATE_CHECK', checkbox('Automatisch nach Updates suchen (alle 12 Stunden)', v.UPDATE_CHECK));
  const unsavedHint = h('p', { class: 'hint', hidden: true }, 'Bitte zuerst die Änderungen speichern: nach dem Update wird die Seite neu geladen.');
  let canInstall = false;

  const version = (tag) => (tag ? tag.replace(/^v/, '') : '–');
  const sync = () => {
    const dirty = form.dirty();
    install.disabled = dirty;
    unsavedHint.hidden = !(dirty && canInstall);
  };
  form.onChange(sync);

  const show = (s) => {
    const facts = h('dl', { class: 'facts' },
      h('dt', null, 'Installiert'), h('dd', null, s.current ? version(s.current) : 'Entwicklungsversion'),
      h('dt', null, 'Aktuell'), h('dd', null, s.latest
        ? [version(s.latest), s.url ? [' · ', h('a', { href: s.url, target: '_blank', rel: 'noopener' }, 'Release auf GitHub')] : '']
        : 'unbekannt'),
      h('dt', null, 'Geprüft'), h('dd', null, s.checkedAt ? age(s.checkedAt) : 'noch nicht',
        s.checkError ? h('span', { class: 'error-text' }, ` – ${s.checkError}`) : ''));
    const parts = [facts];
    if (s.available) {
      parts.push(h('div', { class: 'notice' }, h('strong', null, `Version ${version(s.latest)} ist verfügbar`),
        releaseNotes(s.notes)));
      if (s.mode === 'manual') {
        parts.push(h('p', { class: 'hint' },
          'Diese Installation kann nicht aus der Web-Oberfläche aktualisiert werden. Auf dem Server: ',
          h('code', null, 'bash /opt/lumo/deploy/install.sh'),
          ' – oder die neue Version von GitHub laden.'));
      } else if (s.mode === 'systemd') {
        parts.push(h('p', { class: 'hint' },
          'Der Server lädt die neue Version, prüft sie und startet neu (etwa eine Minute). Die vorige Version bleibt für ',
          h('code', null, 'install.sh --rollback'), ' erhalten.'));
      } else {
        parts.push(h('p', { class: 'hint' }, 'Die App lädt die neue Version, prüft sie und startet neu.'));
      }
    } else if (s.latest && s.current) {
      parts.push(h('p', { class: 'muted' }, 'Diese Version ist aktuell.'));
    }
    if (s.phase === 'failed' && s.error) parts.push(h('div', { class: 'error' }, s.error));
    body.replaceChildren(...parts);
    canInstall = Boolean(s.canInstall);
    install.hidden = !canInstall;
    sync();
  };
  show(status);

  check.addEventListener('click', async () => {
    check.disabled = true;
    msg.clear();
    try {
      show(await api('/api/update/check', { method: 'POST' }));
    } catch (err) {
      msg.error(err);
    } finally {
      check.disabled = false;
    }
  });

  install.addEventListener('click', async () => {
    install.disabled = check.disabled = true;
    msg.ok('Update wird geladen …');
    try {
      await api('/api/update/install', { method: 'POST' });
      await waitForNewVersion(status.current, (text) => msg.ok(text));
    } catch (err) {
      msg.error(err instanceof ApiError ? err : new ApiError(0, 'update_failed', err.message));
      install.disabled = check.disabled = false;
      try {
        show(await api('/api/update'));
      } catch {
        // server not reachable
      }
    }
  });

  return group('update', status.available ? 'Update verfügbar' : 'Update', null,
    body, unsavedHint, auto.el, msg.el,
    h('div', { class: 'button-row' }, install, check),
    h('p', { class: 'muted' }, 'Lumo ist freie Software unter der GPL-3.0. ',
      h('a', { href: 'https://github.com/StefanRiese/lumo', target: '_blank', rel: 'noopener' }, 'Quellcode'),
      ' · ',
      h('a', { href: 'https://github.com/StefanRiese/lumo/blob/main/LICENSE', target: '_blank', rel: 'noopener' }, 'Lizenz'),
      ' · ',
      h('a', { href: '/THIRD-PARTY-LICENSES.txt', target: '_blank', rel: 'noopener' }, 'Lizenzen der Bibliotheken')));
}

// --- Neustart ---------------------------------------------------------------------------------

/**
 * Asks the server to restart and reloads the page when it is back. [msg] shows the progress.
 * @param {{form?: {dirty: () => boolean}, button: HTMLButtonElement, msg: ReturnType<typeof messageArea>}} options
 */
export async function restartServer({ form, button, msg }) {
  const unsaved = form?.dirty() ? '\n\nUngespeicherte Änderungen auf dieser Seite gehen verloren.' : '';
  if (!confirm(`Den Server jetzt neu starten? Die Seite ist kurz nicht erreichbar und lädt sich danach von selbst neu.${unsaved}`)) return;
  button.disabled = true;
  try {
    await api('/api/restart', { method: 'POST' });
  } catch (err) {
    button.disabled = false;
    msg.error(err);
    return;
  }
  msg.ok('Der Server startet neu …');
  // Wait until it has gone away and is back (a restart takes a few seconds).
  await new Promise((resolve) => setTimeout(resolve, 2500));
  const until = Date.now() + 90e3;
  while (Date.now() < until) {
    try {
      const res = await fetch('/healthz', { cache: 'no-store' });
      if (res.ok) {
        location.reload();
        return;
      }
    } catch {
      // not reachable yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  button.disabled = false;
  msg.error(new ApiError(0, 'network', 'Der Server antwortet noch nicht. Bitte die Seite später neu laden und gegebenenfalls das Protokoll prüfen.'));
}

// --- Entwickler (server log) ---------------------------------------------------------------

const LOG_LEVELS = [['error', 'Fehler'], ['warning', 'Warnung'], ['info', 'Info'], ['debug', 'Debug']];

/**
 * The recent log lines of the server, newest first, filtered by level and text. Nothing here is
 * saved with the page: the list only reads (GET /api/logs, the server keeps the last 1000 lines).
 * Returns the three groups (Abgleich, Benachrichtigungen, Log) and `load()`, which the page calls
 * whenever the tab is shown.
 */
export function developerGroup() {
  const shown = new Set(['error', 'warning', 'info']); // debug = the HTTP requests: off by default
  const list = h('div', { class: 'log-list', role: 'log', 'aria-live': 'off', tabindex: '0', 'aria-label': 'Server-Protokoll' });
  const info = h('span', { class: 'muted log-info' });
  const overview = h('div', { class: 'sync-overview' });
  const sentList = h('div', { class: 'sent-list' });
  const search = input({ type: 'search', placeholder: 'Im Protokoll suchen …', 'aria-label': 'Im Protokoll suchen', maxlength: '60' });
  let timer = null;
  let token = 0;

  const loadLog = async () => {
    const mine = ++token;
    const params = new URLSearchParams({ level: [...shown].join(','), limit: '300' });
    if (search.value.trim()) params.set('suche', search.value.trim());
    try {
      const { data } = await api(`/api/logs?${params}`);
      if (mine !== token) return; // a newer request is on its way
      info.textContent = data.length === 1 ? '1 Eintrag' : `${data.length} Einträge`;
      list.replaceChildren(...(data.length ? data.map(logEntry) : [h('div', { class: 'muted' }, 'Keine Einträge für diese Auswahl.')]));
    } catch (err) {
      if (mine !== token) return;
      info.textContent = '';
      list.replaceChildren(h('div', { class: 'error-text' }, errorMessage(err)));
    }
  };
  /** Everything on the tab: sync state, notifications and log. */
  const load = () => {
    loadOverview(overview);
    loadSent(sentList);
    return loadLog();
  };

  const chips = LOG_LEVELS.map(([key, label]) => {
    const chip = h('button', {
      type: 'button', class: ['chip', 'pick', 'log-chip', `log-${key}`], 'aria-pressed': String(shown.has(key)),
      onclick: () => {
        if (shown.has(key)) shown.delete(key); else shown.add(key);
        chip.setAttribute('aria-pressed', String(shown.has(key)));
        loadLog();
      },
    }, label);
    return chip;
  });
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(loadLog, 250);
  });

  // The ids are prefixed: Allgemein has groups called "abgleich" and "benachrichtigungen" too.
  const els = [
    group('entwickler-abgleich', 'Abgleich',
      'Wann die Daten zuletzt vom Schulportal geholt wurden, wann es zuletzt geklappt hat und was fehlgeschlagen ist.',
      overview),
    group('entwickler-benachrichtigungen', 'Benachrichtigungen',
      'Was in den letzten 7 Tagen an Benachrichtigungen ausgelöst wurde. Ohne eingerichtetes ntfy steht „nicht gesendet“ dabei.',
      sentList),
    group('entwickler-log', 'Log',
      'Das Protokoll des Servers (die letzten 1000 Zeilen seit dem Start). Debug zeigt die Anfragen an den Server.',
      h('div', { class: 'field' },
        h('span', { class: 'field-label' }, 'Zeigen'),
        h('div', { class: 'chips', role: 'group', 'aria-label': 'Stufen' }, chips)),
      h('div', { class: 'inline-fields' }, search,
        h('button', { type: 'button', class: 'button', onclick: loadLog }, 'Aktualisieren'), info),
      list),
  ];
  return { els, load };
}

/** When a sync run happened: "um 14:05" today, else date and time; "–" if never. */
function when(iso) {
  if (!iso) return '–';
  const d = new Date(iso);
  return sameDay(d, new Date()) ? `um ${time(d)}` : `${numericDate(d)} ${time(d)}`;
}

/** Fills [box] with the state of the background sync of every child: per area when it ran, when it worked, what failed. */
async function loadOverview(box) {
  const results = await Promise.all(accounts.map(async (a) => [a, await api(`/api/accounts/${a.id}/sync`).catch(() => null)]));
  box.replaceChildren(...results.map(([account, sync]) => h('div', { class: 'sync-account' },
    accounts.length > 1 ? h('strong', null, account.name) : null,
    syncTable(sync))));
}

/**
 * The notifications of the last 7 days of all children, newest first – also those that were only
 * recorded because ntfy is not set up ("nicht gesendet").
 */
async function loadSent(box) {
  const results = await Promise.all(accounts.map(async (a) => {
    const r = await api(`/api/accounts/${a.id}/notifications/log`).catch(() => null);
    return r ? r.data.map((e) => ({ ...e, account: a.name })) : null;
  }));
  if (results.every((r) => r === null)) {
    box.replaceChildren(h('p', { class: 'muted' }, 'Die Benachrichtigungen konnten nicht geladen werden.'));
    return;
  }
  const entries = results.flat().filter(Boolean).sort((a, b) => b.time.localeCompare(a.time));
  if (entries.length === 0) {
    box.replaceChildren(h('p', { class: 'muted' }, 'In den letzten 7 Tagen wurde keine Benachrichtigung ausgelöst.'));
    return;
  }
  box.replaceChildren(h('ul', { class: 'sent-items' }, entries.map((e) => h('li', { class: 'sent-item' },
    h('time', { datetime: e.time, class: 'log-time' }, when(e.time)),
    h('div', { class: 'sent-text' },
      h('strong', null, accounts.length > 1 ? `${e.account}: ${e.title}` : e.title),
      e.message ? h('div', { class: 'muted' }, e.message) : null),
    e.delivered
      ? h('span', { class: 'badge badge-ok' }, 'gesendet')
      : h('span', { class: 'badge badge-warn', title: 'ntfy ist nicht eingerichtet: die Benachrichtigung wurde nur hier aufgeführt.' }, 'nicht gesendet')))));
}

function syncTable(sync) {
  if (!sync) return h('p', { class: 'muted' }, 'Der Stand des Abgleichs konnte nicht geladen werden.');
  if (!sync.enabled) return h('p', { class: 'muted' }, 'Der Abgleich im Hintergrund ist ausgeschaltet: die Daten werden beim Öffnen der Seiten geholt.');
  const rows = Object.entries(TASKS).filter(([key]) => key in (sync.tasks ?? {})).map(([key, label]) => {
    const t = sync.tasks[key] ?? {};
    const failing = t.failures > 0;
    return h('tr', { class: failing && 'sync-failing' },
      h('th', { scope: 'row' }, label),
      h('td', null, when(t.lastRun)),
      h('td', null, when(t.lastSuccess)),
      h('td', null, failing
        ? h('span', { class: 'error-text' }, `${t.lastError ?? 'Fehler'} (${t.failures}× in Folge)`)
        : t.lastRun ? h('span', { class: 'badge badge-ok' }, 'OK') : h('span', { class: 'muted' }, 'noch nicht')),
      h('td', null, when(t.nextRun)));
  });
  return h('div', { class: 'sync-scroll' },
    h('table', { class: 'sync-table' },
      h('thead', null, h('tr', null, ['Bereich', 'Letzter Lauf', 'Zuletzt erfolgreich', 'Status', 'Nächster Lauf'].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', null, rows)));
}

function logEntry(e) {
  const [, label] = LOG_LEVELS.find(([key]) => key === e.level) ?? LOG_LEVELS[2];
  const when = new Date(e.time);
  return h('div', { class: ['log-entry', `log-${e.level}`] },
    h('time', { datetime: e.time, class: 'log-time' }, when.toLocaleTimeString('de-DE'), ' ',
      h('span', { class: 'log-date' }, when.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }))),
    h('span', { class: 'badge log-badge' }, label),
    h('span', { class: 'log-message' }, e.message));
}

/** Restart button; null where the server cannot restart itself (e.g. started by hand). */
export function restartGroup({ form, server }) {
  if (!server.canRestart) return null;
  const msg = messageArea();
  const button = h('button', { type: 'button', class: 'button' }, 'Server neu starten');
  button.addEventListener('click', () => restartServer({ form, button, msg }));
  return group('neustart', 'Neustart',
    'Startet den Server neu, zum Beispiel damit geänderte Netzwerk-Einstellungen gelten oder nach einem Fehler. Die Daten bleiben erhalten.',
    h('div', { class: 'button-row' }, button),
    msg.el);
}
