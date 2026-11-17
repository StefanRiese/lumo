import '../storage/portal_state.dart';
import 'notifier.dart';

/// A notification that was triggered, for the list in *Einstellungen →
/// Entwickler*.
class LoggedNotification {
  final DateTime time;
  final String title;
  final String message;

  /// Sent to ntfy; false when ntfy is not set up (the notification was only
  /// recorded).
  final bool delivered;

  const LoggedNotification({
    required this.time,
    required this.title,
    required this.message,
    required this.delivered,
  });

  factory LoggedNotification.fromJson(Map<String, Object?> j) =>
      LoggedNotification(
        time: DateTime.parse(j['time'] as String).toLocal(),
        title: j['title'] as String,
        message: j['message'] as String,
        delivered: j['delivered'] == true,
      );

  Map<String, Object?> toJson() => {
    'time': time.toUtc().toIso8601String(),
    'title': title,
    'message': message,
    'delivered': delivered,
  };
}

/// The notifications of one account from the last [retention], kept in the
/// database (so the list survives a restart).
class NotificationLog {
  /// How long entries are kept.
  static const retention = Duration(days: 7);

  /// At most this many are kept (a flood, e.g. after a long break).
  static const maxEntries = 200;

  static const _key = 'notifylog';

  final PortalState _state;
  final DateTime Function() _now;

  NotificationLog(this._state, {DateTime Function()? now})
    : _now = now ?? DateTime.now;

  List<LoggedNotification> _load() {
    final raw = _state.getJson(_key)?['entries'];
    if (raw is! List) return [];
    final cutoff = _now().subtract(retention);
    final result = <LoggedNotification>[];
    for (final e in raw) {
      try {
        final entry = LoggedNotification.fromJson(
          (e as Map).cast<String, Object?>(),
        );
        if (entry.time.isAfter(cutoff)) result.add(entry);
      } on Object {
        // an unreadable entry is dropped
      }
    }
    return result;
  }

  /// The entries of the last week, newest first.
  List<LoggedNotification> entries() => _load().reversed.toList();

  void record(AppNotification n, {required bool delivered}) {
    final kept = _load()
      ..add(
        LoggedNotification(
          time: _now(),
          title: n.title,
          message: n.message,
          delivered: delivered,
        ),
      );
    final start = kept.length > maxEntries ? kept.length - maxEntries : 0;
    _state.setJson(_key, {
      'entries': [for (final e in kept.skip(start)) e.toJson()],
    });
  }
}

/// Records every notification that goes through it, then hands it to [inner]
/// (ntfy). Without [inner] (ntfy not set up) the notification is only
/// recorded, so it still shows in the list.
class LoggingNotifier implements Notifier {
  final Notifier? inner;
  final NotificationLog log;

  LoggingNotifier(this.inner, this.log);

  @override
  String get description => inner?.description ?? 'ntfy ist nicht eingerichtet';

  @override
  Future<void> send(AppNotification notification) async {
    await inner?.send(notification);
    log.record(notification, delivered: inner != null);
  }
}
