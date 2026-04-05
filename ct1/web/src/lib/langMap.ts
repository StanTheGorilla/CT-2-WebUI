/** Maps language identifier → [file extension, MIME type] */
export const LANG_MAP: Record<string, [string, string]> = {
  python:     ['.py',   'text/x-python'],
  javascript: ['.js',   'text/javascript'],
  typescript: ['.ts',   'text/typescript'],
  html:       ['.html', 'text/html'],
  css:        ['.css',  'text/css'],
  cpp:        ['.cpp',  'text/x-c++src'],
  c:          ['.c',    'text/x-csrc'],
  go:         ['.go',   'text/x-go'],
  rust:       ['.rs',   'text/x-rustsrc'],
  json:       ['.json', 'application/json'],
  sql:        ['.sql',  'text/x-sql'],
  bash:       ['.sh',   'text/x-sh'],
  shell:      ['.sh',   'text/x-sh'],
  ruby:       ['.rb',   'text/x-ruby'],
  java:       ['.java', 'text/x-java'],
  kotlin:     ['.kt',   'text/x-kotlin'],
  swift:      ['.swift','text/x-swift'],
  yaml:       ['.yaml', 'text/yaml'],
  toml:       ['.toml', 'text/x-toml'],
  markdown:   ['.md',   'text/markdown'],
  text:       ['.txt',  'text/plain'],
};

/** Get [extension, mime] for a language, defaulting to ['.txt', 'text/plain'] */
export function getLangMeta(lang: string): [string, string] {
  return LANG_MAP[lang?.toLowerCase()] ?? ['.txt', 'text/plain'];
}
