"""One lazy catalogue model per voucher, not tens of thousands of items per line."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import QComboBox


class TradeProductModel(QAbstractListModel):
    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.records = [None, *records]
        self.positions = {record['id']: index for index, record in enumerate(self.records) if record}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.records):
            return None
        record = self.records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return record['name'] if record else '상품 선택'
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{record['code']} · {record['name']}" if record else '상품 선택'
        if role == Qt.ItemDataRole.UserRole:
            return record['id'] if record else None
        return None

    def ensure(self, record):
        if record['id'] in self.positions:
            index = self.positions[record['id']]
            self.records[index] = record
            self.dataChanged.emit(self.index(index), self.index(index))
            return index
        index = len(self.records)
        self.beginInsertRows(QModelIndex(), index, index)
        self.positions[record['id']] = index
        self.records.append(record)
        self.endInsertRows()
        return index


class TradeProductCombo(QComboBox):
    def __init__(self, model):
        super().__init__()
        self.setModel(model)
        self.setMinimumContentsLength(18)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.view().setUniformItemSizes(True)
        self.currentIndexChanged.connect(lambda _index: self.setToolTip(self.currentText()))
        self.setToolTip(self.currentText())

    def findData(self, value, role=Qt.ItemDataRole.UserRole, flags=Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive):
        if role == Qt.ItemDataRole.UserRole:
            return 0 if value is None else self.model().positions.get(value, -1)
        return super().findData(value, role, flags)
