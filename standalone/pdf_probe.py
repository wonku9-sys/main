"""Isolated native PDF font/engine diagnostic, using synthetic text only."""
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSize,QSizeF
from PySide6.QtGui import QFont,QFontInfo,QRawFont,QTextDocument,QPdfWriter,QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtPdf import QPdfDocument
from pos2.font_support import regular_font

app=QApplication([])
output=Path('standalone/dist/pdf-probe');output.mkdir(parents=True,exist_ok=True)
sample='검증 상점 | 사업자번호 123-45-67890 | 대표자 테스트 | 업태 도매,소매 | 업종 식료품 | 041-555-0123 | 가상시 검증로 123'
for label,font in [('noto',regular_font(10)),('malgun',QFont('Malgun Gothic',10)),('arial',QFont('Arial',10))]:
    raw=QRawFont.fromFont(font)
    print('FONT',label,QFontInfo(font).family(),'head',len(raw.fontTable('head')),'OS/2',bytes(raw.fontTable('OS/2'))[8:10].hex(),flush=True)
    for mode in ('default','embed','writer'):
        path=output/(label+'-'+mode+'.pdf');document=QTextDocument()
        document.setDefaultFont(font);document.setPageSize(QSizeF(794,1123));document.setPlainText(sample)
        if mode=='writer':
            device=QPdfWriter(str(path));device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        else:
            device=QPrinter(QPrinter.PrinterMode.HighResolution)
            device.setOutputFormat(QPrinter.OutputFormat.PdfFormat);device.setOutputFileName(str(path))
            print('EMBED_DEFAULT',label,device.fontEmbeddingEnabled(),flush=True)
            if mode=='embed':device.setFontEmbeddingEnabled(True)
        document.print_(device)
        reader=QPdfDocument(app);reader.load(str(path));app.processEvents()
        text='\n'.join(reader.getAllText(i).text() for i in range(reader.pageCount()))
        print('PDF',label,mode,'pages',reader.pageCount(),'text',repr(text),'size',path.stat().st_size,flush=True)
        if reader.pageCount():reader.render(0,QSize(794,1123)).save(str(path.with_suffix('.png')))
        reader.close()
