/// Text helpers shared by search and postcode matching.
library;

/// Latin letters with their marks removed, so that "Ynys Môn", "Sinéad" and
/// "Llŷr" can be found by someone typing without accents.
const Map<String, String> _fold = {
  'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a', 'å': 'a', 'ā': 'a', 'ă': 'a', 'ą': 'a',
  'ç': 'c', 'ć': 'c', 'ĉ': 'c', 'ċ': 'c', 'č': 'c',
  'ď': 'd', 'đ': 'd',
  'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e', 'ē': 'e', 'ĕ': 'e', 'ė': 'e', 'ę': 'e', 'ě': 'e',
  'ĝ': 'g', 'ğ': 'g', 'ġ': 'g', 'ģ': 'g',
  'ĥ': 'h', 'ħ': 'h',
  'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i', 'ĩ': 'i', 'ī': 'i', 'ĭ': 'i', 'į': 'i', 'ı': 'i',
  'ĵ': 'j', 'ķ': 'k',
  'ĺ': 'l', 'ļ': 'l', 'ľ': 'l', 'ł': 'l',
  'ñ': 'n', 'ń': 'n', 'ņ': 'n', 'ň': 'n',
  'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o', 'ø': 'o', 'ō': 'o', 'ŏ': 'o', 'ő': 'o',
  'ŕ': 'r', 'ř': 'r',
  'ś': 's', 'ŝ': 's', 'ş': 's', 'š': 's', 'ß': 'ss',
  'ţ': 't', 'ť': 't',
  'ù': 'u', 'ú': 'u', 'û': 'u', 'ü': 'u', 'ũ': 'u', 'ū': 'u', 'ŭ': 'u', 'ů': 'u', 'ű': 'u', 'ų': 'u',
  'ŵ': 'w',
  'ý': 'y', 'ÿ': 'y', 'ŷ': 'y',
  'ź': 'z', 'ż': 'z', 'ž': 'z',
  'æ': 'ae', 'œ': 'oe',
};

final RegExp _combining = RegExp('[̀-ͯ]');
final RegExp _notWord = RegExp('[^a-z0-9 ]');
final RegExp _spaces = RegExp(r'\s+');

/// Lower-case, accent-free, punctuation-free form used to compare names.
String norm(String? input) {
  if (input == null || input.isEmpty) return '';
  final lower = input.toLowerCase().replaceAll(_combining, '');
  final out = StringBuffer();
  for (final rune in lower.runes) {
    final ch = String.fromCharCode(rune);
    out.write(_fold[ch] ?? ch);
  }
  return out
      .toString()
      .replaceAll('&', ' and ')
      .replaceAll(_notWord, ' ')
      .replaceAll(_spaces, ' ')
      .trim();
}

/// A full UK postcode, with or without the space.
final RegExp postcodePattern = RegExp(r'^[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}$');

bool looksLikePostcode(String input) => postcodePattern.hasMatch(input.trim());

final RegExp _postcodeStart = RegExp(r'^[A-Za-z]{1,2}\d[A-Za-z\d]?\s*(\d[A-Za-z]?)?$');

/// The beginning of a postcode, not yet all of it: "G12", "SW1A 0". No
/// constituency or representative has a name that starts like this, so there
/// is nothing to search for until the rest has been typed.
bool looksLikePartPostcode(String input) =>
    !looksLikePostcode(input) && _postcodeStart.hasMatch(input.trim());

String capitalise(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

/// 1234 -> "1,234".
String thousands(num? n) {
  if (n == null) return '—';
  final digits = n.round().abs().toString();
  final out = StringBuffer(n < 0 ? '-' : '');
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write(',');
    out.write(digits[i]);
  }
  return out.toString();
}
