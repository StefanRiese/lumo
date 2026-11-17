import 'dart:convert';

import 'package:lumo_server/lumo_server.dart';
import 'package:shelf/shelf.dart';
import 'package:test/test.dart';

final _hash = PasswordHasher.hash('richtig123', iterations: 1000);

void main() {
  group('LogBuffer.classify', () {
    LogLevel level(String m, [bool error = false]) =>
        LogBuffer.classify(m, error);

    test('the error stream is error', () {
      expect(level('Cannot listen: port in use', true), LogLevel.error);
    });

    test('requests are debug, server errors are error', () {
      expect(
        level('  0:00:00.001000 GET     [200] /api/timetable'),
        LogLevel.debug,
      );
      expect(
        level('  0:00:00.001000 POST    [401] /api/auth/login'),
        LogLevel.debug,
      );
      expect(
        level('  0:00:00.001000 GET     [500] /api/timetable'),
        LogLevel.error,
      );
    });

    test('errors, failures and the rest', () {
      expect(level('sync error: boom'), LogLevel.error);
      expect(level('Unhandled exception'), LogLevel.error);
      expect(level('Update check failed: offline'), LogLevel.warning);
      expect(level('Cannot process /x/restart: denied'), LogLevel.warning);
      expect(level('Listening on http://0.0.0.0:8080'), LogLevel.info);
      expect(level('[1] notify grades: Neue Note'), LogLevel.info);
    });
  });

  group('LogBuffer', () {
    test('keeps the newest lines and strips the timestamp', () {
      final b = LogBuffer(capacity: 3);
      for (var i = 1; i <= 5; i++) {
        b.add('2026-11-17T08:0$i:00.000 line $i', false);
      }
      expect(b.length, 3);
      final all = b.query();
      expect([for (final e in all) e.message], ['line 5', 'line 4', 'line 3']);
      expect(all.first.time, DateTime.parse('2026-11-17T08:05:00.000'));
      expect(all.first.id, 5);
    });

    test('a line without timestamp gets the current time', () {
      final b = LogBuffer(now: () => DateTime(2026, 11, 17, 9));
      b.add('plain', false);
      expect(b.query().single.time, DateTime(2026, 11, 17, 9));
      expect(b.query().single.message, 'plain');
    });

    test('filters by level, text and limit', () {
      final b = LogBuffer()
        ..add('2026-11-17T08:00:00 Listening on :8080', false)
        ..add('2026-11-17T08:00:01 Update check failed: x', false)
        ..add('2026-11-17T08:00:02 sync error: Boom\nstack line', false)
        ..add('2026-11-17T08:00:03   0:00:00.001 GET     [200] /api/x', false);
      expect(
        [
          for (final e in b.query(levels: {LogLevel.warning, LogLevel.error}))
            e.level,
        ],
        [LogLevel.error, LogLevel.warning],
      );
      expect(
        b.query(levels: {LogLevel.debug}).single.message,
        contains('/api/x'),
      );
      expect(b.query(search: 'BOOM').single.message, contains('stack line'));
      expect(b.query(limit: 2), hasLength(2));
    });
  });

  group('GET /api/logs', () {
    late LogBuffer logs;
    late Handler handler;

    setUp(() {
      logs = LogBuffer()
        ..add('2026-11-17T08:00:00 Listening on :8080', false)
        ..add('2026-11-17T08:00:01 Update check failed: x', false)
        ..add('2026-11-17T08:00:02 Unhandled error: y', true);
      handler = Api(passwordHash: _hash, logs: logs).handler;
    });

    Future<Response> get(String path, {String? cookie}) => Future.value(
      handler(
        Request(
          'GET',
          Uri.parse('http://localhost$path'),
          headers: {'cookie': ?cookie},
        ),
      ),
    );

    Future<String> login() async {
      final r = await handler(
        Request(
          'POST',
          Uri.parse('http://localhost/api/auth/login'),
          body: jsonEncode({'password': 'richtig123'}),
          headers: {'content-type': 'application/json'},
        ),
      );
      return r.headers['set-cookie']!.split(';').first;
    }

    test('needs a login', () async {
      expect((await get('/api/logs')).statusCode, 401);
    });

    test('lists the newest first and filters', () async {
      final cookie = await login();
      var r = await get('/api/logs', cookie: cookie);
      var b = jsonDecode(await r.readAsString()) as Map;
      expect(
        [for (final e in b['data'] as List) (e as Map)['level']],
        ['error', 'warning', 'info'],
      );
      expect(b['capacity'], 1000);

      r = await get('/api/logs?level=warning,error&limit=1', cookie: cookie);
      b = jsonDecode(await r.readAsString()) as Map;
      expect((b['data'] as List).single['message'], 'Unhandled error: y');

      r = await get('/api/logs?suche=listening', cookie: cookie);
      b = jsonDecode(await r.readAsString()) as Map;
      expect((b['data'] as List).single['level'], 'info');
    });

    test('rejects an unknown level and a bad limit', () async {
      final cookie = await login();
      for (final q in ['level=trace', 'limit=0', 'limit=5000', 'limit=x0']) {
        expect(
          (await get('/api/logs?$q', cookie: cookie)).statusCode,
          400,
          reason: q,
        );
      }
    });
  });
}
