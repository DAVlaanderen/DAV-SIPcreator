from PySide6 import QtCore

import sqlite3 as sql

class SQLliteModel(QtCore.QAbstractTableModel):
    def __init__(
        self,
        table_name: str,
        db_name: str,
        is_main: bool=False,
    ):
        super().__init__()
        self._table_name = table_name
        self._db_name = db_name

        self.is_main = is_main

        # NOTE: keep track of if a change in the data has occurred
        self.has_changed = False

        # How many columns to skip (id for is_main, id/main_id for other)
        self.columns_to_skip = 1 if self.is_main else 2
        # self.columns_to_skip = 0

        # Dict with key = 0-index, value = column_name
        self.columns: dict[int, str] = dict()

        self.row_count, self.col_count = -1, -1

        self._data: list[list[str]] = []
        self.get_data()

        # self.calculate_shape()

    @property
    def conn(self):
        return sql.connect(self._db_name)

    def get_value(self, index):
        row, col = index.row(), index.column() + self.columns_to_skip

        # NOTE: quotes are not allowed for now
        return self._data[row][col].replace('"', "").replace("'", "")
    
    def set_value(self, index, new_value: str):
        self.has_changed = True

        row, col = index.row(), index.column() + self.columns_to_skip

        # NOTE: quotes are not allowed for now
        self._data[row][col] = new_value.replace('"', "").replace("'", "")

    def calculate_shape(self):
        with self.conn as conn:
            cursor = conn.execute(f"SELECT count() FROM \"{self._table_name}\";")

            self.row_count = cursor.fetchone()[0]

            cursor = conn.execute(f"pragma table_info(\"{self._table_name}\");")

            self.columns = {
                i: column_name
                for i, column_name, *_ in cursor.fetchall()
            }

            self.col_count = len(self.columns)

    def get_data(self) -> list[list[str]]:
        with self.conn as conn:
            self._data = [
                [v if v is not None else "" for v in r]
                for r in conn.execute(f"SELECT * FROM \"{self._table_name}\";").fetchall()
            ]
            self.row_count = len(self._data)

            cursor = conn.execute(f"pragma table_info(\"{self._table_name}\");")

            self.columns = {
                i: column_name
                for i, column_name, *_ in cursor.fetchall()
            }

            self.col_count = len(self.columns)

        # NOTE: not very good to use this method for retrieval and getting
        return self._data

    def save_data(self) -> None:
        with self.conn as conn:
            for row in range(self.row_count):
                main_id = self._data[row][1]
                set_value = ",\n\t".join([f"{self.columns[col]}='{self._data[row][col]}'" for col in range(self.columns_to_skip, self.col_count)])

                conn.execute(
                    f"""
                        UPDATE "{self._table_name}"
                        SET {set_value}
                        WHERE main_id={main_id};
                    """
                )

    def rowCount(self, *index):
        return self.row_count

    def columnCount(self, *index):
        return self.col_count - self.columns_to_skip

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return

        if (
            role == QtCore.Qt.ItemDataRole.DisplayRole
            or role == QtCore.Qt.ItemDataRole.EditRole
        ):
            return self.get_value(index)

    def setData(self, index, value, role=QtCore.Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False

        if role == QtCore.Qt.ItemDataRole.EditRole:
            self.set_value(index, value)

            return True

        return False

    def headerData(self, section, orientation, role):
        # section is the index of the column/row.
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return list(self.columns.values())[section + self.columns_to_skip]

            if orientation == QtCore.Qt.Orientation.Vertical:
                return section

    def flags(self, index):
        return (
            QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsEditable
        ) if not self.is_main else (
            QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
        )

    def sort(self, col: int, order: QtCore.Qt.SortOrder) -> None:
        self.layoutAboutToBeChanged.emit()

        self._data.sort(
            key=lambda row: row[col + self.columns_to_skip],
            reverse=order is QtCore.Qt.SortOrder.DescendingOrder
        )

        self.layoutChanged.emit()
