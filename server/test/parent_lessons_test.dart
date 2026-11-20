import 'package:html/parser.dart' as html;
import 'package:liblanis/easy_client.dart' as lanis;
import 'package:lumo_server/src/sph/liblanis_gateway.dart';
import 'package:test/test.dart';

/// „Mein Unterricht“ of a parent account: one block per pupil, the pupil's id
/// is part of the ids and links.
const _parentPage = '''
<html><body><div id="content">
 <div class="pupilbox"><h2 data-pupil="111">Kind Eins</h2>
  <div class="tab-content">
   <div id="aktuell111" class="tab-pane active">
     <table><tr class="printable" data-entry="7"><td><h3><a href="meinunterricht.php?a=sus_view&id=5&p=111">Mathe</a></h3></td>
       <td><b class="thema">Brüche</b><small><span class="datum">10.11.2026</span></small></td></tr></table></div>
   <div id="mappen111" class="tab-pane"><div class="row">
     <div><h2>Mathe</h2><a class="btn btn-primary" href="meinunterricht.php?a=sus_view&id=5&p=111">Mappe</a></div>
   </div></div>
   <div id="anwesend111" class="tab-pane"></div>
  </div></div>
 <div class="pupilbox"><h2 data-pupil="222">Kind Zwei</h2>
  <div class="tab-content">
   <div id="aktuell222" class="tab-pane active"></div>
   <div id="mappen222" class="tab-pane"><div class="row">
     <div><h2>Kunst</h2><a class="btn btn-primary" href="meinunterricht.php?a=sus_view&id=6&p=222">Mappe</a></div>
   </div></div>
   <div id="anwesend222" class="tab-pane"></div>
  </div></div>
</div></body></html>''';

void main() {
  test('the parent page is read per pupil; the first pupil\'s courses', () {
    final overview = lanis.LessonsParentParser.parseOverviewDocument(
      html.parse(_parentPage),
    );
    expect(overview.lessonsByPupil.keys.map((p) => p.id), ['111', '222']);

    final lessons = firstPupilLessons(overview);
    expect(lessons.map((l) => l.name), ['Mathe']);
    expect(lessons.single.pupilId, '111');
    expect(lessons.single.courseURL.queryParameters['p'], '111');
  });
}
