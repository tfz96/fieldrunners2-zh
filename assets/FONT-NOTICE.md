# 中文字体

`Chinese.ttf` is a renamed, subsetted, static instance of **Noto Sans SC** from Google Fonts, derived from Adobe's Source Han Sans. It is distributed under the SIL Open Font License 1.1, reproduced in `OFL.txt`. The reserved font name is “Source”; this derivative is named **FR2 Chinese UI** / **FR2ChineseUI**.

- Upstream: https://github.com/google/fonts/tree/main/ofl/notosanssc
- Source file: `NotoSansSC[wght].ttf`
- Upstream commit: `2894aab31764f10f29c421bdfd2340d3b382d384`
- Source SHA-256: `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`
- Instantiated weight: `550`
- Retained glyphs: translation JSON text, Latin-1 characters, and `Ω→←↑↓×÷★☆…`.
- Included derivative SHA-256: `21336259c473afa3a46b85e2a5bf6132800e03e0e1c61978a39af47d601b1425`
- The derivative's OpenType modification timestamp is fixed to 2026-01-01 UTC for reproducible output.
- `native/metrics.h` contains advance widths derived from this same font and is covered by the same OFL.

The original variable font uses TrueType `glyf` outlines. A static subset is necessary for the game's older FreeType/FTGL renderer. No Windows system fonts or proprietary game fonts are redistributed.
