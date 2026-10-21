# Bundled Korean font provenance

- Family: Noto Sans KR, Google Fonts distribution; Korean and Latin glyphs.
- Original upstream filename: `NotoSansKR[wght].ttf` (variable font).
- Local filename: `NotoSansKR-Regular.ttf`. Starting in rc31 this is a static Regular (wght=400) instance of the upstream variable font, generated with fontTools varLib.instancer. Copyright and OFL notices remain embedded. The Reserved Font Name is 'Source', not 'Noto Sans KR'.
- Downloaded: 2026-10-19.
- Official source: https://github.com/google/fonts/tree/main/ofl/notosanskr
- Original font URL: https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf
- Original license URL: https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/OFL.txt
- License: SIL Open Font License 1.1; the complete original `OFL.txt` is included beside the font.
- Original copyright notice: Copyright 2014-2021 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'.

SHA256 of the exact redistributed files:

```text
4609a7b62a6da24cae3a8b73ecde7003581b8f60662d60cc8f55a3793de07763  NotoSansKR-Regular.ttf
1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9  OFL.txt
```

The application loads this local asset without any network request. Redistribution is bundled with the program, not as a separately sold font. This font has no relation to the old POS application.

The original variable binary SHA256 was `194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252`. Generated with fontTools 4.61.1 on 2026-10-21. Reproduction command:

```sh
fonttools varLib.instancer 'NotoSansKR[wght].ttf' wght=400 --static --update-name-table --no-recalc-timestamp -o NotoSansKR-Regular.ttf
```

The static instance gives consistent Regular UI rendering. Native diagnosis also showed that Windows Qt outlines even static memory-loaded fonts. Documents therefore prefer Windows' installed Malgun Gothic when present (not redistributed by this app), retaining this bundled font as an offline fallback. PDF tests require the actual seven business fields to be searchable/extractable, not just painted on screen.
