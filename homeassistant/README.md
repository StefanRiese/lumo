# Lumo for Home Assistant

A custom integration that shows the data of a [Lumo](../README.md) server in Home Assistant:
substitutions, homework, next lessons, school calendar, school meals (Caseda), and – if you want
it – grades. It talks to the [REST API](../docs/API.md) of your own Lumo server; it never contacts
the Schulportal itself, so it adds no load there and needs no Schulportal password.

- One **device per child**, plus one device for the server (diagnostics).
- Changes arrive **live** over the server's event stream; a 15-minute poll is the fallback.
- German and English texts.
- Tested with Home Assistant 2026.2; needs a Lumo server you can reach from it.

## Installation

**With HACS:** *HACS → ⋮ → Custom repositories*, add `https://github.com/StefanRiese/lumo` as
type *Integration*, install *Lumo* and restart Home Assistant.

**Manually:** copy the folder `custom_components/lumo` of the repository into the
`custom_components` folder of your Home Assistant configuration and restart Home Assistant.

Then add the integration under *Settings → Devices & services → Add integration → Lumo*.

```sh
# example for a Home Assistant OS / container with the config in /config
cp -r custom_components/lumo /config/custom_components/
```

## Setup

1. **Host, port, HTTPS and password** – the address of the Lumo server (e.g. `lumo.local`, port
   `8080`) and the password of its *web UI*. It is **not** the Schulportal password.
2. **Children** – choose which children of the server appear in Home Assistant (skipped if the
   server has only one).

If the web password changes later, Home Assistant asks for the new one (*Repair* / re-authenticate).
*Reconfigure* changes host, port or password, but only for the same server.

### Options

*Settings → Devices & services → Lumo → Configure*

| Option | Default | |
|---|---|---|
| Children | all chosen at setup | Children that appear in Home Assistant. |
| Load grades | **off** | Creates the grades sensor and fetches grades. Grades are personal data – see [Privacy](#privacy). |
| Allow marking homework as done | **off** | Lets the homework to-do list tick items off. This **writes to the real Schulportal**. |

Saving the options reloads the integration.

## Entities

Entity ids contain the name of the child, e.g. `sensor.lumo_max_substitutions_today`. Areas the
portal account does not have (the server reports them as disabled) get no entities.

### Per child

| Entity | State | Attributes |
|---|---|---|
| Substitutions today / tomorrow (`sensor`) | number of entries | `published` (the portal has published that day), `entries`, `notices`, `date` |
| Cancellation today / tomorrow (`binary_sensor`) | on if a lesson is cancelled („Entfall“, „Fällt aus“) | `cancelled` (the entries) |
| Open homework (`sensor`) | number of open tasks | `homework`: course, date, topic, description |
| Homework (`todo`) | open items | description; ticking needs the option above |
| Next lesson (`sensor`, timestamp) | start of the next lesson | `subject`, `room`, `teacher`, `end` |
| First lesson tomorrow (`sensor`, timestamp) | start of the first lesson tomorrow, none on a free day | `subject`, `room`, `teacher`, `end` |
| School calendar (`calendar`) | next or current event | – |
| Meal balance, Meal today (`sensor`) | balance in EUR / ordered dish | `line`, `allergens`, `price` – only if Caseda is set up for the child |
| Grades (`sensor`) | number of grades | `courses` – only with the option *Load grades* |
| Refresh now (`button`) | – | Starts a sync of the child's data on the server |
| Schulportal / Caseda / WebUntis connection (`binary_sensor`, diagnostic) | on if the server reaches the service | `state`, `detail`, `last_success`, `failures` |

Every data entity also has `fetched_at` and `stale` (`true`: the server could not refresh from the
portal, the data may be old).

Notes:

- „Substitutions today“ counts the entries of the plan **after the server's permanent filter**
  (own classes), exactly like the web UI. A day the portal has not published shows `0` with
  `published: false`.
- The lessons come from the **regular timetable** (A/B weeks are handled); substitutions are not
  applied to them.
- „Today“ and the lesson sensors are recomputed every minute, so they roll over at midnight
  without new data.

### Server device

*Update available* (with `installed_version`, `latest_version`, `release_url`) and the connection
of the services the server reports (notifications via ntfy, update server).

## Event `lumo_new_item`

Fired on the event bus when the server's data brings something new:

| `kind` | When | Fields besides `account_id`, `account_name` |
|---|---|---|
| `substitution` | a new or changed entry in the plan (another room counts as new) | `date`, `period`, `type`, `subject`, `teacher`, `substitute`, `room`, `className`, `note`, … (only non-empty) |
| `homework` | new **open** homework | `course`, `date`, `topic`, `description` |
| `grade` | a new grade, only with *Load grades* | `course`, `name`, `date`, `mark` |

Nothing is fired for what was already there at startup or reload. At most 25 events per update.

```yaml
automation:
  - alias: Max: announce cancellations
    triggers:
      - trigger: event
        event_type: lumo_new_item
        event_data:
          kind: substitution
          account_name: Max
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.type in ['Entfall', 'Fällt aus'] }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Entfall {{ trigger.event.data.date }}"
          message: >
            {{ trigger.event.data.period }}. Stunde {{ trigger.event.data.subject }}
            entfällt ({{ trigger.event.data.className }}).
```

```yaml
automation:
  - alias: Max: first lesson tomorrow
    triggers:
      - trigger: time
        at: "20:00:00"
    conditions:
      - condition: template
        value_template: "{{ has_value('sensor.lumo_max_first_lesson_tomorrow') }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            Tomorrow the first lesson is
            {{ state_attr('sensor.lumo_max_first_lesson_tomorrow', 'subject') }} at
            {{ as_timestamp(states('sensor.lumo_max_first_lesson_tomorrow'))
               | timestamp_custom('%H:%M') }}.
```

## Dashboard example

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Max
    entities:
      - sensor.lumo_max_substitutions_today
      - sensor.lumo_max_substitutions_tomorrow
      - sensor.lumo_max_next_lesson
      - binary_sensor.lumo_max_cancellation_today
  - type: markdown
    title: Homework
    content: >
      {% for h in state_attr('sensor.lumo_max_open_homework', 'homework') or [] %}
      - **{{ h.course }}**: {{ h.topic }}
      {% endfor %}
  - type: todo-list
    entity: todo.lumo_max_homework
```

## Privacy

- The integration reads the server's cache and never asks the Schulportal itself.
- Substitutions, homework and – if enabled – grades are personal data of a child. Home Assistant
  keeps entity states in its database (the *recorder*) and the event bus feeds automations and
  logs. The large lists (`entries`, `homework`, `courses`, …) are excluded from the recorder; the
  **numbers** and the event contents are not. Exclude the entities in the `recorder:` configuration
  if that matters to you.
- **Grades are off by default**, nothing about grades is fetched or fired until you switch the
  option on.
- **Marking homework as done is off by default.** With the option on, ticking an item in Home
  Assistant changes the data in the real Schulportal.
- The password of the Lumo web UI is stored in Home Assistant's config entry. Use a password that
  you use nowhere else.

## Troubleshooting

| Message | Meaning |
|---|---|
| The server is not reachable | Check host, port and HTTPS; from the Home Assistant host: `curl http://<host>:8080/healthz` |
| Wrong password | The *web UI* password, not the Schulportal password. |
| Too many failed logins | The server blocks a client after 5 wrong passwords within 15 minutes. |
| The Lumo server is not set up yet | Finish the setup in the server's web UI first. |
| Entities are unavailable / `stale: true` | The server cannot reach the Schulportal; see *Einstellungen → Entwickler* in the Lumo web UI. |

Debug logging: `logger: logs: custom_components.lumo: debug`.

## Development

Python 3.13 and the test harness of Home Assistant:

```sh
cd homeassistant
pip install -r requirements_test.txt
ruff check . ../custom_components && ruff format --check . ../custom_components
pytest -q
```

The tests run against a fake Lumo server with invented data (`tests/fake_server.py`). To try the
integration without a school account, start the mock server of the repository
(`node dev/mock-server.mjs`, password `demo`, `MOCK_CHILDREN=1` for a second child) and add
`127.0.0.1:8090` in Home Assistant.

Layout of `custom_components/lumo/`: `api.py` (client, event stream), `coordinator.py` (data, live updates, `lumo_new_item`),
`changes.py` (what is new), `timetable.py` (lessons on concrete days), `config_flow.py`, and one
module per platform.
