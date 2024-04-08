from typing import List

from PySide6 import QtWidgets, QtCore

from ..application import Application

from .dossier_widget import DossierWidget
from .sip_widget import SIPWidget
from .dialog import Dialog

from ..utils.configuration import Environment
from ..utils.state import State
from ..utils.sip_status import SIPStatus


class SearchableListWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.application: Application = QtWidgets.QApplication.instance()
        self.state: State = self.application.state

        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.setLayout(self.grid_layout)

        self.searchbox = QtWidgets.QLineEdit()
        self.searchbox.textEdited.connect(self.reload_widgets)
        self.grid_layout.addWidget(self.searchbox, 1, 0)

        self.count_label = QtWidgets.QLabel(text="0")
        self.grid_layout.addWidget(self.count_label, 1, 1)

        scroll_area = QtWidgets.QScrollArea()
        central_widget = QtWidgets.QWidget()
        self.list_layout = QtWidgets.QVBoxLayout()
        self.list_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        central_widget.setLayout(self.list_layout)
        scroll_area.setWidget(central_widget)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll_area.setWidgetResizable(True)
        self.grid_layout.addWidget(scroll_area, 2, 0, 1, 2)

        self.widgets = []

    # NOTE: not optimal to always do it all over, but shouldn't be too much of an issue
    def reload_widgets(self):
        # Instead of deleting and adding items, we simply set their visibility
        widgets_to_show = self.search_widgets()

        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            widget.setVisible(False)

            if widget in widgets_to_show:
                if not isinstance(widget, SIPWidget):
                    widget.setVisible(True)
                    continue

                if (
                    widget.sip.environment.name
                    == self.state.configuration.active_environment
                ):
                    widget.setVisible(True)

    def get_widget_by_value(self, value: str):
        for w in self.widgets:
            if getattr(w["reference"], w["field"]) == value:
                return w

    # NOTE: we implemented our own search function here
    def search_widgets(self):
        partial_name = self.searchbox.text()

        if partial_name == "":
            return list(map(lambda w: w["reference"], self.widgets))

        widgets_to_show = []

        for widget in self.widgets:
            if partial_name in getattr(widget["reference"], widget["field"]):
                widgets_to_show.append(widget["reference"])

        return widgets_to_show

    def remove_widget_by_value(self, value: str):
        # We do not care if it's a widget we do not have
        if not (widget := self.get_widget_by_value(value)):
            return

        try:
            self.list_layout.removeWidget(widget["reference"])
            # Make sure we don't double delete
            widget["reference"].destroyed.disconnect()
            widget["reference"].deleteLater()
        except RuntimeError:
            # Item was already deleted somewhere else
            pass

        self.widgets.remove(widget)

        # On closing of the application this raises a runtime error
        # NOTE: not safe to just catch runtime errors like this
        try:
            self.count_label.setText(str(len(self.widgets)))
        except RuntimeError:
            pass

    def add_item(self, searchable_name_field: str, widget: SIPWidget) -> bool:
        # We want stuff to be unique, but will just overwrite if it isn't
        # Return success state, if "self.never_overwrite" is True, we do not overwrite nor ask, but return False on collision
        # TODO: proper logging
        if not hasattr(widget, searchable_name_field):
            return False

        value = getattr(widget, searchable_name_field)

        self.widgets.append(
            {
                "reference": widget,
                "field": searchable_name_field,
            }
        )
        self.list_layout.insertWidget(0, widget)

        widget.destroyed.connect(lambda: self.remove_widget_by_value(value))
        self.reload_widgets()
        self.count_label.setText(str(self.list_layout.count()))

        return True


class SearchableSelectionListView(SearchableListWidget):
    def __init__(self):
        super().__init__()

        self.count_label.setText("0 / 0")

        self.remove_selected_button = QtWidgets.QPushButton(
            text="Verwijder geselecteerde dossiers"
        )
        self.remove_selected_button.clicked.connect(self.remove_selected_clicked)
        self.remove_selected_button.setEnabled(False)

        self.select_all_button = QtWidgets.QCheckBox(text="Selecteer alle dossiers")
        self.select_all_button.clicked.connect(self.select_all_clicked)

        self.grid_layout.addWidget(self.select_all_button, 0, 0, 1, 2)
        self.grid_layout.addWidget(self.remove_selected_button, 3, 0, 1, 2)

    def add_item(self, searchable_name_field: str, widget: DossierWidget) -> bool:
        response = super().add_item(
            searchable_name_field=searchable_name_field, widget=widget
        )

        widget.selection_changed.connect(self.selection_changed)
        self.selection_changed()

        return response

    def remove_widget_by_value(self, value: str):
        super().remove_widget_by_value(value=value)

        self.selection_changed()

    def selection_changed(self):
        amount_selected = len(self.get_selected())

        self.count_label.setText(f"{amount_selected} / {len(self.widgets)}")

        if amount_selected == 0:
            self.remove_selected_button.setEnabled(False)
        else:
            self.remove_selected_button.setEnabled(True)

        if amount_selected == len(self.widgets):
            self.select_all_button.setCheckState(QtCore.Qt.CheckState.Checked)
        else:
            self.select_all_button.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def get_selected(self) -> list:
        selected_dossiers = []

        for i in range(self.list_layout.count()):
            dossier = self.list_layout.itemAt(i).widget()

            if not isinstance(dossier, DossierWidget):
                continue

            if dossier.is_selected():
                selected_dossiers.append(dossier)

        return selected_dossiers

    def remove_selected_clicked(self):
        for dossier_widget in self.get_selected():
            self.application.state.remove_dossier(dossier_widget.dossier)
            dossier_widget.deleteLater()

    def select_all_clicked(self):
        if self.select_all_button.checkState() == QtCore.Qt.CheckState.Checked:
            selected = True
        else:
            selected = False

        for i in range(self.list_layout.count()):
            dossier = self.list_layout.itemAt(i).widget()

            if not isinstance(dossier, DossierWidget):
                continue

            dossier.set_selected(selected)


class SIPListWidget(SearchableListWidget):
    def __init__(self):
        super().__init__()

        self.sips_status_filter = QtWidgets.QComboBox()
        self.sips_status_filter.addItems(
            ["alles tonen"] + [s.get_status_label() for s in SIPStatus]
        )
        self.sips_status_filter.currentTextChanged.connect(self.reload_widgets)

        self.grid_layout.addWidget(self.sips_status_filter, 0, 0, 1, 2)

    def search_widgets(self):
        widgets_to_show: List[SIPWidget] = []
        partial_name = self.searchbox.text()

        if partial_name == "":
            widgets_to_show = list(map(lambda w: w["reference"], self.widgets))
        else:
            for widget in self.widgets:
                if partial_name in getattr(widget["reference"], widget["field"]):
                    widgets_to_show.append(widget["reference"])

        status_filter_text = self.sips_status_filter.currentText()

        if status_filter_text == "alles tonen":
            return widgets_to_show

        return [
            w
            for w in widgets_to_show
            if w.sip.status.get_status_label() == status_filter_text
        ]
