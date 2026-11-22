/// Somewhere a visitor has chosen: a postcode or a single area, with the
/// constituencies and regions that cover it.
library;

import 'models.dart';

class Place {
  const Place({required this.label, required this.keys, this.notes = const []});

  factory Place.fromJson(Map<String, dynamic> j) => Place(
        label: (j['label'] ?? '').toString(),
        keys: [for (final k in (j['keys'] as List? ?? const [])) k.toString()],
        notes: [for (final n in (j['notes'] as List? ?? const [])) n.toString()],
      );

  factory Place.area(Area area) => Place(label: area.area, keys: [area.key]);

  /// What to call it: the postcode as typed, or the area's name.
  final String label;

  /// Area keys, in no particular order.
  final List<String> keys;

  /// Things the visitor should know about how the place was resolved.
  final List<String> notes;

  Map<String, dynamic> toJson() => {'label': label, 'keys': keys, 'notes': notes};

  /// The areas this place covers: the Commons seat first, then devolved
  /// constituencies, then regional lists.
  List<Area> areas(AppData data) {
    final out = [
      for (final k in keys)
        if (data.areaByKey[k] != null) data.areaByKey[k]!,
    ];
    int rank(Area a) => (a.parliament == kUkParliament ? 0 : 1) + (a.isRegion ? 1 : 0);
    out.sort((a, b) => rank(a).compareTo(rank(b)));
    return out;
  }
}
