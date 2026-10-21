"""Printing and local exports always recheck the current document permission."""
from pathlib import Path
from PySide6.QtCore import QIODevice,QSaveFile
from PySide6.QtPrintSupport import QPrinter,QPrintPreviewDialog
from PySide6.QtGui import QPageSize
from PySide6.QtWidgets import QFileDialog,QMessageBox
from .commercial_paper import paper_document,paper_images


def output_paper(store,identifier,title,parent,mode='preview'):
    record=store.sales_form(identifier)
    document=paper_document(record,title)
    if mode=='email':
        from .document_mail import DocumentMailDialog
        DocumentMailDialog(store,record,title,parent).exec();return
    if mode=='preview':
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        preview=QPrintPreviewDialog(printer,parent);preview.setWindowTitle(title+' · 인쇄 미리보기');preview.resize(1100,800)
        def paint(target):
            try:
                store.sales_form(identifier)  # Revoked access must not print.
                document.print_(target)
            except PermissionError:preview.reject()
        preview.paintRequested.connect(paint);preview.exec();return
    if mode=='pdf':
        name,_=QFileDialog.getSaveFileName(parent,'PDF 저장',record['number']+'.pdf','PDF 문서 (*.pdf)')
        if not name:return
        path=Path(name).with_suffix('.pdf');store.sales_form(identifier)
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(path));document.print_(printer)
        if not path.is_file() or path.stat().st_size==0:raise ValueError('PDF 파일을 저장하지 못했습니다.')
        return str(path)
    if mode!='image':raise ValueError('문서 출력 방식을 확인하세요.')
    name,_=QFileDialog.getSaveFileName(parent,'문서 이미지 저장',record['number']+'.png','PNG 이미지 (*.png)')
    if not name:return
    path=Path(name).with_suffix('.png')
    paths=[path if document.pageCount()==1 else path.with_name(path.stem+f'-{i+1:02d}.png') for i in range(document.pageCount())]
    if any(p.exists() for p in paths) and QMessageBox.question(parent,'파일 덮어쓰기','이미 존재하는 이미지 파일을 교체할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
    store.sales_form(identifier)
    for path,image in zip(paths,paper_images(document)):
        output=QSaveFile(str(path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(output,'PNG') or not output.commit():raise ValueError('이미지 저장에 실패했습니다. 저장 위치와 디스크 공간을 확인하세요.')
    return [str(path) for path in paths]
