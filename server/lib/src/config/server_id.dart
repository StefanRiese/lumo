import 'dart:math';

import '../storage/app_database.dart';

/// Key in the `meta` table of the database.
const _metaKey = 'server_id';

final _valid = RegExp(r'^[A-Za-z0-9-]{8,64}$');

/// A random UUID (version 4).
String newServerId([Random? random]) {
  final r = random ?? Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

/// The identity of this server (a UUID that clients use instead of the
/// address, which can change and exist more than once: IPv4, IPv6, name).
///
/// `SERVER_ID` from the configuration wins (install.sh sets it, so that it
/// can announce the same id by mDNS); otherwise the id kept in the database,
/// created on first start.
String loadServerId(AppDatabase db, {String? configured}) {
  final fromConfig = configured?.trim();
  if (fromConfig != null && _valid.hasMatch(fromConfig)) return fromConfig;
  final stored = db.getMeta(_metaKey);
  if (stored != null && _valid.hasMatch(stored)) return stored;
  final id = newServerId();
  db.setMeta(_metaKey, id);
  return id;
}
