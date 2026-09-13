/**
 * Dictation, using only what the browser already has.
 *
 * Spec §38 asks for voice input, says not to make external voice APIs mandatory for V1, and says
 * not to build a complicated real-time system unless it is reliable. That is the correct call and
 * it has a consequence worth stating out loud: `webkitSpeechRecognition` is not a local
 * recogniser. Chrome sends the audio to Google, so **on a phone with no data connection the
 * microphone fails with a `network` error**, in exactly the scenario this product is for. This
 * hook therefore treats voice as a convenience that disappears when it does - the text box is
 * always there, always enabled, and never becomes a dead end.
 *
 * What the transcript does next is the other half of §38: it goes into the same message field,
 * which goes through the same `POST /api/community/reports`. There is no second pipeline for
 * speech, so a spoken report and a typed one cannot be treated differently downstream. The only
 * trace it leaves is the `voice_transcript` flag, which tells an operator the words were dictated.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** The subset of the API this app uses. Declared here rather than as a dependency. */
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onend: (() => void) | null;
}

interface ResultItem {
  transcript?: unknown;
}

interface ResultEvent {
  resultIndex?: number;
  results: { length: number; [index: number]: { isFinal?: unknown; 0?: ResultItem } };
}

interface ErrorEvent {
  error?: unknown;
}

type Constructor = new () => SpeechRecognitionLike;

function findConstructor(): Constructor | null {
  const w = window as unknown as {
    SpeechRecognition?: Constructor;
    webkitSpeechRecognition?: Constructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface SpeechInput {
  /** False means no dictation here, and the screen should not show a microphone at all. */
  supported: boolean;
  listening: boolean;
  error: string | null;
  start: () => void;
  stop: () => void;
  toggle: () => void;
}

/**
 * `onTranscript` receives each finalised phrase; the caller decides whether to append or replace.
 * `lang` is the reader's own BCP-47 tag, so a Nepali screen dictates in Nepali - the recogniser
 * is per-language and getting this wrong produces fluent nonsense in the other one.
 */
export function useSpeechInput(options: {
  lang: string;
  onTranscript: (text: string) => void;
}): SpeechInput {
  const { lang, onTranscript } = options;
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  // The callback changes every render; a ref keeps a long-lived recogniser from hearing a stale one.
  const callback = useRef(onTranscript);
  callback.current = onTranscript;
  const language = useRef(lang);
  language.current = lang;

  const supported = findConstructor() !== null;

  const stop = useCallback(() => {
    const instance = recognition.current;
    if (instance) {
      try {
        instance.stop();
      } catch {
        /* already ended */
      }
    }
    setListening(false);
  }, []);

  const start = useCallback(() => {
    const Ctor = findConstructor();
    if (!Ctor) return;
    // One recogniser at a time: a second `start()` on a live instance throws, and a re-click
    // while it is still listening is a normal thing for someone to do.
    if (recognition.current) {
      try {
        recognition.current.abort();
      } catch {
        /* ignore */
      }
      recognition.current = null;
    }

    setError(null);
    let instance: SpeechRecognitionLike;
    try {
      instance = new Ctor();
    } catch {
      setError("constructor");
      return;
    }
    instance.lang = language.current;
    instance.continuous = false;
    instance.interimResults = false;
    instance.maxAlternatives = 1;

    instance.onresult = (event: unknown) => {
      const result = (event as ResultEvent).results;
      let text = "";
      for (let index = (event as ResultEvent).resultIndex ?? 0; index < result.length; index += 1) {
        const row = result[index];
        if (row?.isFinal && typeof row[0]?.transcript === "string") text += `${row[0].transcript} `;
      }
      const trimmed = text.trim();
      // An empty final result happens when the utterance was all noise. Calling the parent
      // with "" would append a space and read as "it heard something and lost it".
      if (trimmed) callback.current(trimmed);
    };
    instance.onerror = (event: unknown) => {
      const code = (event as ErrorEvent).error;
      setError(typeof code === "string" ? code : "unknown");
      setListening(false);
    };
    instance.onend = () => {
      setListening(false);
    };

    recognition.current = instance;
    try {
      instance.start();
      setListening(true);
    } catch {
      setError("start");
      setListening(false);
    }
  }, []);

  useEffect(
    () => () => {
      const instance = recognition.current;
      recognition.current = null;
      if (!instance) return;
      instance.onresult = null;
      instance.onerror = null;
      instance.onend = null;
      try {
        instance.abort();
      } catch {
        /* nothing to abort */
      }
    },
    [],
  );

  const toggle = useCallback(() => {
    if (listening) stop();
    else start();
  }, [listening, start, stop]);

  return { supported, listening, error, start, stop, toggle };
}

/** Whether the browser offers dictation at all, for a screen that must decide before mounting. */
export function speechInputAvailable(): boolean {
  return findConstructor() !== null;
}
