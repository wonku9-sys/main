# SY POS · 아이콘3d

Created specifically for this application using OpenAI image generation on 2026-10-20, in response to the owner's request for clear, realistic 3D menu icons. Not extracted from the reference PDF or legacy executable; no external icon pack or brand logo is used.

`menu-icons-3d.png` is a transparent RGBA 1374 × 1145 sprite atlas with 6 columns × 5 rows, 229 × 229 pixels per icon. The owner-requested lighting revision adds upper-left studio reflections and brighter polished top bevels, without large glow clouds or box backgrounds. Edge cleanup preserves white object surfaces and 3D depth. Edited using OpenAI image generation; the generated revision is included without additional raster edits. Qt displays each cell independently at high-DPI resolutions; no rounded-square backplates are painted.

SHA256: `91096d5d54212a57301f6645f0b85d79152e5bd87397e55552b21356525933e8`

Qt converts the loaded image to premultiplied alpha before resampling. Transparent pixels blend with the actual current toolbar/panel background, including seasonal skins, rather than a fixed white or gray rectangle. White paper, arrow shapes and genuine material highlights are retained.

The light effect is baked into the local artwork: no flashing, timers, per-frame compositing or continuous animation was added. Icon sizes, cache limits and menu behavior remain unchanged.

The later printer/Excel request uses dedicated realistic artwork for those two families; see `OUTPUT_ICONS_3D.md`. Their original cells remain in this atlas as an offline recovery fallback. The other 28 families and the SY POS wordmark are unchanged by that update.

The subsequent hover request uses two cached UI renderings without modifying these PNGs. Resting menu artwork fits a centered 120×120 area of a 128px transparent icon; hovered artwork uses the complete original 128px rendering (about 6.7% larger). The iconSize/row/button geometry stays fixed and neither state zooms beyond the original image. Leaving, hiding or disabling restores the normal rendering. No per-frame timers or network work are added.

Row order: previous / next / home / calendar / products / purchase;
sale / reports / members / payment / print / spreadsheet;
barcode scanner / supplier truck / inventory / categories / settings / search;
add / edit / waste / diary / wallet / work log;
lottery / target / manual card / transfer / backup / information.

Displayed sizes after the owner's small-increase request: main toolbar 38 logical pixels; payment toolbar 34; print/Excel icons 28; personal shortcuts 26; sidebar 18. Each is only two logical pixels larger than the previous size. Main working text and sidebar remain 14 logical pixels, while the dense numbered menu strip remains 13. Qt's normal display scaling is retained. These are application design choices after visual comparison with manual pages 13 and 99, not pixel dimensions specified by the PDF.
