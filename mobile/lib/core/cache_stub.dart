/// Where no file system is available (the web build) nothing is cached and the
/// app always uses the data it shipped with.
library;

Future<String?> read(String name) async => null;

Future<void> write(String name, String content) async {}
