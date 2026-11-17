import 'dart:collection';

/// Severity of a log entry.
enum LogLevel { debug, info, warning, error }

/// One line of the server log.
class LogEntry {
  final int id;
  final DateTime time;
  final LogLevel level;

  /// The message without the leading timestamp; may span several lines
  /// (stack trace).
  final String message;

  const LogEntry(this.id, this.time, this.level, this.message);

  Map<String, Object?> toJson() => {
    'id': id,
    'time': time.toUtc().toIso8601String(),
    'level': level.name,
    'message': message,
  };
}

/// The most recent log lines of the server, kept in memory for the web UI
/// (*Einstellungen → Entwickler*). Lines arrive through the one log sink of
/// the server, which has no levels: [classify] derives the level.
class LogBuffer {
  /// Most entries one query returns.
  static const maxQueryLimit = 1000;

  final int capacity;
  final DateTime Function() _now;
  final _entries = Queue<LogEntry>();
  int _nextId = 1;

  LogBuffer({this.capacity = 1000, DateTime Function()? now})
    : _now = now ?? DateTime.now;

  int get length => _entries.length;

  /// Adds a line; [isError] marks messages of the error stream.
  void add(String line, bool isError) {
    final (time, message) = _split(line);
    _entries.add(
      LogEntry(_nextId++, time ?? _now(), classify(message, isError), message),
    );
    while (_entries.length > capacity) {
      _entries.removeFirst();
    }
  }

  /// The newest entries first: only [levels] (null = all), only those that
  /// contain [search] (case-insensitive), at most [limit].
  List<LogEntry> query({
    Set<LogLevel>? levels,
    String? search,
    int limit = 200,
  }) {
    final needle = search?.trim().toLowerCase() ?? '';
    final result = <LogEntry>[];
    for (final e in _entries.toList().reversed) {
      if (levels != null && !levels.contains(e.level)) continue;
      if (needle.isNotEmpty && !e.message.toLowerCase().contains(needle)) {
        continue;
      }
      result.add(e);
      if (result.length >= limit) break;
    }
    return result;
  }

  static final _timestamp = RegExp(r'^(\d{4}-\d\d-\d\dT[\d:.]+Z?)\s+');

  /// Splits a leading ISO timestamp (all lines of the server have one) off.
  static (DateTime?, String) _split(String line) {
    final m = _timestamp.firstMatch(line);
    if (m == null) return (null, line);
    return (DateTime.tryParse(m.group(1)!), line.substring(m.end));
  }

  /// A request line of the HTTP server: `   0:00:00.001000 GET     [200] /path`.
  static final _request = RegExp(r'^\s*[\d:.]+\s+[A-Z]+\s+\[(\d{3})\] ');

  static final _errorWords = RegExp(
    r'\berror\b|unhandled|exception',
    caseSensitive: false,
  );
  static final _warningWords = RegExp(
    r'failed|cannot|not taken over',
    caseSensitive: false,
  );

  /// Level of a message: the error stream and server errors are errors,
  /// requests are debug output, failures are warnings, everything else info.
  static LogLevel classify(String message, bool isError) {
    if (isError) return LogLevel.error;
    final request = _request.firstMatch(message);
    if (request != null) {
      return int.parse(request.group(1)!) >= 500
          ? LogLevel.error
          : LogLevel.debug;
    }
    if (_errorWords.hasMatch(message)) return LogLevel.error;
    if (_warningWords.hasMatch(message)) return LogLevel.warning;
    return LogLevel.info;
  }
}
