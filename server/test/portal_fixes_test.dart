import 'package:lumo_server/lumo_server.dart';
import 'package:html/parser.dart' as html;
import 'package:test/test.dart';

void main() {
  group('course overview', () {
    const full = '''
<div id="mappen"><div class="row">
  <div><h2>Mathematik</h2><a class="btn btn-primary" href="meinunterricht.php?a=sus_view&id=5">Mappe</a></div>
</div></div>
<table><tr class="printable" data-entry="7"><td><span class="datum">10.11.2026</span>
  <span class="homework"><span class="realHomework">S. 5</span></span></td></tr></table>''';

    test('a complete page stays unchanged', () {
      expect(fixCourseOverview(full), full);
    });

    test('no course list: an empty one is added', () {
      final doc = html.parse(
        fixCourseOverview('<html><body><p>x</p></body></html>'),
      );
      // What liblanis does: row! on #mappen's rows.
      final rows = doc.getElementById('mappen')!.getElementsByClassName('row');
      expect(rows, hasLength(1));
      expect(rows.first.children, isEmpty);
    });

    test('incomplete course cards and entries are dropped', () {
      const broken = '''
<div id="mappen"><div class="row">
  <div><h2>Ohne Link</h2></div>
  <div><h2>Mathematik</h2><a class="btn btn-primary" href="x?id=5">Mappe</a></div>
</div></div>
<table>
  <tr class="printable"><td><span class="datum">10.11.2026</span></td></tr>
  <tr class="printable" data-entry="8"><td><span class="datum">11.11.2026</span>
    <span class="homework">ohne Text</span></td></tr>
</table>''';
      final doc = html.parse(fixCourseOverview(broken));
      expect(doc.querySelectorAll('#mappen .row > div'), hasLength(1));
      final rows = doc.querySelectorAll('tr.printable');
      expect(rows, hasLength(1), reason: 'entry without data-entry dropped');
      expect(rows.single.querySelector('.homework'), isNull);
    });
  });

  group('responses of meinunterricht.php', () {
    final uri = Uri.parse(
      'https://start.schulportal.hessen.de/meinunterricht.php',
    );

    test('the answer to marking homework as done stays „1“', () {
      // A POST; the body of the request carries the action, not the address.
      expect(fixCoursePage('POST', uri, '1'), '1');
      expect(fixCourseOverview('1'), '1');
      expect(fixCoursePage('GET', uri, '1'), '1');
    });

    test('the overview page (GET without action) is repaired', () {
      final fixed = fixCoursePage(
        'GET',
        uri,
        '<html><body><p>x</p></body></html>',
      );
      expect(html.parse(fixed).getElementById('mappen'), isNotNull);
    });

    test('course detail pages stay unchanged', () {
      final detail = uri.replace(queryParameters: {'a': 'sus_view', 'id': '5'});
      const page = '<html><body><p>x</p></body></html>';
      expect(fixCoursePage('GET', detail, page), page);
    });

    test('other addresses stay unchanged', () {
      final other = Uri.parse(
        'https://start.schulportal.hessen.de/stundenplan.php',
      );
      expect(fixCoursePage('GET', other, '<p>x</p>'), '<p>x</p>');
    });
  });
}
