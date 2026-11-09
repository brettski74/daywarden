/** The Advanced settings of a cut, with the defaults and limits of the matching bin/cut-clips options. */

export type CutKey = "min_silence" | "threshold" | "min_speech" | "guard" | "loudness";
export type CutTexts = Record<CutKey, string>;

export type CutField = {
  key: CutKey;
  label: string;
  unit: string;
  defaultValue: number;
  whole: boolean;
  allowed: (value: number) => boolean;
  message: string;
  /** A slider beside the number box, where the field has one. A typed number may go beyond it. */
  slider?: { min: number; max: number; step: number };
};

export const CUT_FIELDS: CutField[] = [
  {
    key: "min_silence",
    label: "Minimum silence",
    unit: "ms",
    defaultValue: 700,
    whole: true,
    allowed: (value) => value >= 200,
    message: "A whole number of milliseconds, 200 or more.",
  },
  {
    key: "threshold",
    label: "Threshold",
    unit: "dB",
    defaultValue: 35,
    whole: false,
    allowed: (value) => value > 0 && value < 200,
    message: "Decibels below the loudest point, above 0 and below 200.",
    slider: { min: 10, max: 80, step: 1 },
  },
  {
    key: "min_speech",
    label: "Minimum speech",
    unit: "ms",
    defaultValue: 150,
    whole: true,
    allowed: (value) => value >= 0,
    message: "A whole number of milliseconds, 0 or more.",
  },
  {
    key: "guard",
    label: "Guard",
    unit: "ms",
    defaultValue: 100,
    whole: true,
    allowed: (value) => value >= 10,
    message: "A whole number of milliseconds, 10 or more.",
  },
  {
    key: "loudness",
    label: "Loudness",
    unit: "LUFS",
    defaultValue: -18,
    whole: false,
    allowed: (value) => value >= -40 && value <= -10,
    message: "From \u221240 to \u221210 LUFS.",
    slider: { min: -40, max: -10, step: 1 },
  },
];

export const DEFAULT_TEXTS = Object.fromEntries(CUT_FIELDS.map((field) => [field.key, String(field.defaultValue)])) as CutTexts;

/** Return the number a box holds when it is allowed, otherwise null. A typographic minus counts as a minus. */
export function cutValue(field: CutField, text: string): number | null {
  const plain = text.trim().replace(/\u2212/g, "-");
  const pattern = field.whole ? /^-?\d+$/ : /^-?(\d+(\.\d*)?|\.\d+)$/;
  if (!pattern.test(plain)) return null;
  const value = Number(plain);
  return Number.isFinite(value) && field.allowed(value) ? value : null;
}

export function differsFromDefault(field: CutField, text: string): boolean {
  return cutValue(field, text) !== field.defaultValue;
}

/** The settings to send with a cut, or null while any box holds a value that is not allowed. */
export function cutSettings(texts: CutTexts): Record<CutKey, number> | null {
  const settings = {} as Record<CutKey, number>;
  for (const field of CUT_FIELDS) {
    const value = cutValue(field, texts[field.key]);
    if (value === null) return null;
    settings[field.key] = value;
  }
  return settings;
}

/** How the default is written for people, such as "35 dB" or "−18 LUFS". */
export function defaultText(field: CutField): string {
  return `${String(field.defaultValue).replace("-", "\u2212")} ${field.unit}`;
}

/** Where a field's slider sits for the text in its box: the value, held at the slider's ends, or the default. */
export function sliderValue(field: CutField, text: string): number {
  const { min, max } = field.slider!;
  const value = cutValue(field, text) ?? field.defaultValue;
  return Math.min(max, Math.max(min, value));
}
