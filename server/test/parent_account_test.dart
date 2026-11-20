import 'package:liblanis/easy_client.dart' as lanis;
import 'package:lumo_server/lumo_server.dart';
import 'package:lumo_server/src/sph/mappers.dart' show courseKey;
import 'package:test/test.dart';

import 'support/fake_gateway.dart';

void main() {
  group('course ids', () {
    test(
      'plain numbers stay, the pupil of a parent link becomes part of it',
      () {
        expect(courseKey('100'), '100');
        expect(courseKey('100&p=456'), '100-p-456');
        expect(courseKey('a b/c'), 'a-b-c');
        expect(
          RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(courseKey('100&p=456')),
          isTrue,
        );
      },
    );
  });

  group('SphService with a parent account', () {
    late FakeGateway gw;
    late SphService svc;

    setUp(() {
      gw = FakeGateway()..accountTypeValue = 'parent';
      // Course links of a parent carry the pupil.
      for (final l in gw.lessonsData) {
        l.courseID = '${l.courseID}&p=9';
      }
      gw.lessonsData = [
        for (final l in gw.lessonsData)
          lanis.Lesson(
            courseID: l.courseID,
            name: l.name,
            courseURL: Uri.parse(
              'https://start.schulportal.hessen.de/meinunterricht.php?a=sus_view&id=${l.courseID}',
            ),
            teachers: l.teachers,
            currentEntry: l.currentEntry,
          ),
      ];
      svc = SphService(gw);
    });
    tearDown(() => svc.dispose());

    test('courses, details and homework use the safe id', () async {
      final courses = await svc.courses();
      expect(courses.map((c) => c.id), ['100-p-9', '200-p-9']);
      final details = await svc.courseDetails('100-p-9');
      expect(details.course.id, '100-p-9');
      for (final h in await svc.homework()) {
        expect(h.courseId, matches(RegExp(r'^[A-Za-z0-9_-]+$')));
      }
    });

    test(
      'older homework counts as done: the portal has no status for it',
      () async {
        // Like the real portal for parents: the history has no marker (liblanis
        // reads it as not done); only the entry of the overview has one.
        lanis.CurrentEntry entry(String id, {required bool done}) =>
            lanis.CurrentEntry(
              entryID: id,
              files: [],
              uploads: [],
              topicDate: DateTime(2026, 11, id == 'new' ? 16 : 9),
              homework: lanis.Homework(
                description: 'Aufgabe $id',
                homeWorkDone: done,
              ),
            );
        final current = entry('new', done: false);
        gw.lessonsData = [
          lanis.Lesson(
            courseID: '100&p=9',
            name: 'Mathe',
            courseURL: Uri.parse(
              'https://start.schulportal.hessen.de/meinunterricht.php?a=sus_view&id=100&p=9',
            ),
            teachers: [],
            currentEntry: current,
          ),
        ];
        gw.olderEntries['100&p=9'] = [entry('old', done: false)];
        final all = {
          for (final h in (await svc.lessonsSnapshot()).allHomework)
            h.entryId: h.done,
        };
        expect(all, {'new': false, 'old': true});

        final history = (await svc.courseDetails('100-p-9')).history;
        expect(
          {for (final e in history) e.id: e.homeworkDone},
          {'new': false, 'old': true},
        );
      },
    );

    test('homework cannot be marked as done', () async {
      await expectLater(
        svc.setHomeworkDone('100-p-9', 'e1', true),
        throwsA(isA<SphFeatureDisabledException>()),
      );
      expect(gw.homeworkCalls, isEmpty, reason: 'nothing sent to the portal');
    });
  });
}
