import 'dart:io';

import 'package:lumo_server/lumo_server.dart';
import 'package:test/test.dart';

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('lumo_id'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('a new id is a version 4 UUID', () {
    expect(
      newServerId(),
      matches(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ),
      ),
    );
  });

  test('the id is created once and kept in the database', () {
    var db = AppDatabase.open('${dir.path}/t.db');
    final id = loadServerId(db);
    expect(loadServerId(db), id);
    db.close();
    db = AppDatabase.open('${dir.path}/t.db');
    expect(loadServerId(db), id);
    db.close();
  });

  test('SERVER_ID from the configuration wins; a bad one is ignored', () {
    final db = AppDatabase.open('${dir.path}/t.db');
    final own = loadServerId(db);
    expect(loadServerId(db, configured: 'abcd1234-aaaa'), 'abcd1234-aaaa');
    expect(loadServerId(db, configured: 'no good!'), own);
    expect(loadServerId(db, configured: ''), own);
    db.close();
  });
}
