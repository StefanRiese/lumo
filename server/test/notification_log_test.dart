import 'dart:convert';

import 'package:lumo_server/lumo_server.dart';
import 'package:shelf/shelf.dart';
import 'package:test/test.dart';

import 'notify_test.dart' show RecordingNotifier;
import 'support/fake_gateway.dart';

final _hash = PasswordHasher.hash('richtig123', iterations: 1000);

const _n = AppNotification(title: 'Neue Hausaufgabe', message: 'Mathe: S. 99');

void main() {
  late AppDatabase db;
  late DateTime clock;
  late NotificationLog log;

  setUp(() {
    clock = DateTime(2026, 11, 17, 12);
    db = AppDatabase.inMemory();
    log = NotificationLog(db, now: () => clock);
  });

  tearDown(() => db.close());

  group('NotificationLog', () {
    test('lists the newest first', () {
      log.record(_n, delivered: true);
      clock = clock.add(const Duration(minutes: 5));
      log.record(
        const AppNotification(title: 'Zweite', message: 'x'),
        delivered: false,
      );
      final all = log.entries();
      expect([for (final e in all) e.title], ['Zweite', 'Neue Hausaufgabe']);
      expect([for (final e in all) e.delivered], [false, true]);
      expect(all.last.message, 'Mathe: S. 99');
      expect(all.last.time, DateTime(2026, 11, 17, 12));
    });

    test('keeps only the last 7 days', () {
      log.record(_n, delivered: true);
      clock = clock.add(const Duration(days: 6, hours: 23));
      expect(log.entries(), hasLength(1));
      clock = clock.add(const Duration(hours: 2));
      expect(log.entries(), isEmpty);
      log.record(
        const AppNotification(title: 'Neu', message: 'y'),
        delivered: true,
      );
      expect(log.entries().single.title, 'Neu');
    });

    test('keeps at most ${NotificationLog.maxEntries} entries', () {
      for (var i = 0; i < NotificationLog.maxEntries + 5; i++) {
        log.record(AppNotification(title: 'N$i', message: ''), delivered: true);
      }
      final all = log.entries();
      expect(all, hasLength(NotificationLog.maxEntries));
      expect(all.first.title, 'N${NotificationLog.maxEntries + 4}');
      expect(all.last.title, 'N5');
    });

    test('survives a new instance and ignores damaged entries', () {
      log.record(_n, delivered: true);
      db.setJson('notifylog', {
        'entries': [
          ...((db.getJson('notifylog')!['entries']) as List),
          {'title': 'ohne Zeit'},
          'kaputt',
        ],
      });
      expect(
        NotificationLog(db, now: () => clock).entries().single.title,
        'Neue Hausaufgabe',
      );
    });

    test('each account has its own list', () {
      final other = NotificationLog(ScopedState(db, '@x/'), now: () => clock);
      log.record(_n, delivered: true);
      expect(other.entries(), isEmpty);
    });
  });

  group('LoggingNotifier', () {
    test('records what was sent', () async {
      final inner = RecordingNotifier();
      final notifier = LoggingNotifier(inner, log);
      await notifier.send(_n);
      expect(inner.sent, [_n]);
      expect(log.entries().single.delivered, isTrue);
    });

    test('records without ntfy, delivered = false', () async {
      final notifier = LoggingNotifier(null, log);
      expect(notifier.description, contains('nicht eingerichtet'));
      await notifier.send(_n);
      expect(log.entries().single.delivered, isFalse);
    });

    test('a failed delivery is not recorded', () async {
      final inner = RecordingNotifier()..failNext = 1;
      final notifier = LoggingNotifier(inner, log);
      await expectLater(notifier.send(_n), throwsA(isA<NotifyException>()));
      expect(log.entries(), isEmpty);
      await notifier.send(_n);
      expect(log.entries(), hasLength(1));
    });
  });

  group('Poller without ntfy', () {
    test('notifications are recorded, not delivered', () async {
      final gw = FakeGateway();
      final service = SphService(gw, now: () => clock);
      final sync = SyncService(
        service: service,
        cache: Api.createCache(now: () => clock),
        db: db,
        config: const SyncConfig(pause: Duration.zero),
        now: () => clock,
      );
      final poller = Poller(
        sync: sync,
        db: db,
        delivers: false,
        notifier: LoggingNotifier(null, log),
        now: () => clock,
      );
      addTearDown(() async {
        await sync.stop();
        await service.dispose();
      });

      await poller.runNow(); // baseline
      expect(log.entries(), isEmpty);
      gw.lessonsData.first.currentEntry!.homework!.description = 'Neu: S. 99';
      expect(await poller.runNow([WatchKind.homework]), 1);
      final entry = log.entries().single;
      expect(entry.message, contains('S. 99'));
      expect(entry.delivered, isFalse);
      expect(await poller.runNow([WatchKind.homework]), 0, reason: 'seen');
    });
  });

  group('GET /api/notifications/log', () {
    Handler handler({bool withLog = true, Poller? poller}) => (Api(
      passwordHash: _hash,
      poller: poller,
    )..notificationLog = withLog ? log : null).handler;

    Future<String> login(Handler h) async {
      final r = await h(
        Request(
          'POST',
          Uri.parse('http://localhost/api/auth/login'),
          body: jsonEncode({'password': 'richtig123'}),
          headers: {'content-type': 'application/json'},
        ),
      );
      return r.headers['set-cookie']!.split(';').first;
    }

    Future<Map<String, Object?>> get(
      Handler h,
      String path,
      String cookie,
    ) async {
      final r = await h(
        Request(
          'GET',
          Uri.parse('http://localhost$path'),
          headers: {'cookie': cookie},
        ),
      );
      return jsonDecode(await r.readAsString()) as Map<String, Object?>;
    }

    test('needs a login', () async {
      final r = await handler()(
        Request('GET', Uri.parse('http://localhost/api/notifications/log')),
      );
      expect(r.statusCode, 401);
    });

    test('lists the last week, newest first', () async {
      log.record(_n, delivered: false);
      final h = handler();
      final body = await get(h, '/api/notifications/log', await login(h));
      expect(body['days'], 7);
      final entry = (body['data'] as List).single as Map;
      expect(entry['title'], 'Neue Hausaufgabe');
      expect(entry['delivered'], isFalse);
      expect(
        entry['time'],
        '2026-11-17T11:00:00.000Z'.isEmpty ? '' : isA<String>(),
      );
    });

    test('empty without a log', () async {
      final h = handler(withLog: false);
      final body = await get(h, '/api/notifications/log', await login(h));
      expect(body['data'], isEmpty);
    });

    test('a recording-only poller counts as notifications off', () async {
      final gw = FakeGateway();
      final service = SphService(gw);
      final sync = SyncService(
        service: service,
        cache: Api.createCache(),
        db: db,
      );
      addTearDown(() async {
        await sync.stop();
        await service.dispose();
      });
      final poller = Poller(
        sync: sync,
        db: db,
        delivers: false,
        notifier: LoggingNotifier(null, log),
      );
      final h = handler(poller: poller);
      final cookie = await login(h);
      expect((await get(h, '/api/notifications', cookie))['enabled'], isFalse);
      final r = await h(
        Request(
          'POST',
          Uri.parse('http://localhost/api/notifications/test'),
          headers: {'cookie': cookie},
        ),
      );
      expect(r.statusCode, 409);
    });
  });
}
