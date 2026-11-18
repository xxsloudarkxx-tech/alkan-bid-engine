import 'package:speech_to_text/speech_to_text.dart';

/// Servicio Push-to-Talk para dictar nombres de proyecto, notas de obra y ajustes por voz.
class VoiceDictationService {
  final SpeechToText _speech = SpeechToText();
  bool _initialized = false;

  Future<bool> ensureReady() async {
    if (_initialized) return true;
    try {
      _initialized = await _speech.initialize();
    } catch (_) {
      _initialized = false;
    }
    return _initialized;
  }

  bool get isListening => _speech.isListening;

  Future<bool> startListening({
    required void Function(String transcript, bool isFinal) onText,
    String localeId = 'es_MX',
  }) async {
    final ok = await ensureReady();
    if (!ok) return false;
    await _speech.listen(
      localeId: localeId,
      listenMode: ListenMode.dictation,
      partialResults: true,
      onResult: (result) {
        onText(result.recognizedWords, result.finalResult);
      },
    );
    return true;
  }

  Future<void> stopListening() async {
    if (_speech.isListening) {
      await _speech.stop();
    }
  }
}
