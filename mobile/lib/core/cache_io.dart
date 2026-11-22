/// Downloaded data files, kept in the app's own private storage.
library;

import 'dart:io';

import 'package:path_provider/path_provider.dart';

Future<File> _file(String name) async {
  final dir = await getApplicationSupportDirectory();
  return File('${dir.path}/$name');
}

Future<String?> read(String name) async {
  final f = await _file(name);
  return await f.exists() ? f.readAsString() : null;
}

/// Written to a temporary name first and then renamed, so a download cut off
/// half-way can never leave a truncated file to be read at the next launch.
Future<void> write(String name, String content) async {
  final f = await _file(name);
  final part = File('${f.path}.part');
  await part.writeAsString(content, flush: true);
  await part.rename(f.path);
}
