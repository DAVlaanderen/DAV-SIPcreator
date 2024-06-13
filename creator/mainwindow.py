import os
import json

from PySide6 import QtWidgets, QtCore, QtGui
import pandas as pd
import sqlite3 as sql

from .application import Application

from .widgets.searchable_list_widget import (
    SearchableSelectionListView,
    SIPListWidget,
)
from .widgets.dossier_widget import DossierWidget
from .widgets.sip_widget import SIPWidget
from .widgets.toolbar import Toolbar
from .widgets.dialog import YesNoDialog
from .widgets.warning_dialog import WarningDialog

from .controllers.file_controller import FileController

from .utils.state import State
from .utils.state_utils.dossier import Dossier
from .utils.state_utils.sip import SIP
from .utils.sip_status import SIPStatus

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.application: Application = QtWidgets.QApplication.instance()
        self.state: State = self.application.state

        self.central_widget = None

        # Toolbar
        self.toolbar = Toolbar()
        self.addToolBar(self.toolbar)

    def closeEvent(self, event):
        # If the main window dies, kill the whole application
        if any(
            s.status == SIPStatus.UPLOADING
            for s in self.application.db_controller.read_sips()
        ):
            WarningDialog(
                title="Upload bezig",
                text="Waarschuwing, een upload is momenteel bezig, de applicatie kan niet gesloten worden.",
            ).exec()

            event.ignore()
            return

        event.accept()
        self.application.quit()

class DigitalWidget(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.application: Application = QtWidgets.QApplication.instance()
        self.state: State = self.application.state

        self.state.sip_edepot_failed.connect(self.fail_reason_show)

    def fail_reason_show(self, sip: SIP, reason: str):
        WarningDialog(
            title="SIP upload gefaald",
            text=f"SIP '{sip.name}' is geweigerd door het Edepot met volgende reden:\n\n{reason}",
        ).exec()

        storage_location = self.state.configuration.misc.save_location
        with open(
            os.path.join(
                storage_location, FileController.SIP_STORAGE, sip.error_file_name
            ),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                f"SIP '{sip.name}' is geweigerd door het Edepot met volgende reden:\n\n{reason}"
            )

    def setup_ui(self):
        grid_layout = QtWidgets.QGridLayout()
        self.setLayout(grid_layout)

        # Dossiers
        add_dossier_button = QtWidgets.QPushButton(text="Voeg een dossier toe")
        add_dossier_button.clicked.connect(self.add_dossier_clicked)

        add_dossiers_button = QtWidgets.QPushButton(text="Voeg folder met dossiers toe")
        add_dossiers_button.clicked.connect(
            lambda: self.add_dossier_clicked(multi=True)
        )

        self.dossiers_list_view = SearchableSelectionListView()

        grid_layout.addWidget(add_dossier_button, 0, 0)
        grid_layout.addWidget(add_dossiers_button, 0, 1)
        grid_layout.addWidget(self.dossiers_list_view, 1, 0, 1, 2)

        # SIPS
        self.create_sip_button = QtWidgets.QPushButton(text="Start SIP")
        self.create_sip_button.clicked.connect(self.create_sip_clicked)
        self.create_sip_button.setEnabled(False)
        self.sip_list_view = SIPListWidget()
        
        self.parent().toolbar.configuration_changed.connect(self.sip_list_view.reload_widgets)

        grid_layout.addWidget(self.create_sip_button, 0, 2, 1, 2)
        grid_layout.addWidget(self.sip_list_view, 1, 2, 1, 2)

    def load_items(self):
        removed_dossiers = []
        dossier_widgets = []

        for dossier in self.application.state.dossiers:
            if dossier.disabled:
                continue

            if not os.path.exists(dossier.path):
                removed_dossiers.append(dossier)
                continue

            dossier_widget = DossierWidget(dossier=dossier)

            dossier_widgets.append(dossier_widget)

        self.dossiers_list_view.add_items(
            widgets=dossier_widgets,
            selection_changed_callback=self.dossier_selection_changed,
            first_launch=True,
        )

        if len(removed_dossiers) > 0:
            dialog = YesNoDialog(
                title="Verwijderde dossiers",
                text="Een aantal dossiers lijken niet meer op hun plaats te staan.\nWilt u deze ook uit de lijst verwijderen?\n\nDeze boodschap zal anders blijven verschijnen.",
            )
            dialog.exec()

            if dialog.result():
                for dossier in removed_dossiers:
                    dossier.disabled = True
                    self.application.state.remove_dossier(dossier)

        missing_sips = []
        sips = self.application.state.sips
        sorted_sips = sorted(sips, key=lambda s: s.status.get_priority(), reverse=True)

        for sip in sorted_sips:
            # Check for missing sips
            if sip.status in (
                SIPStatus.SIP_CREATED,
                SIPStatus.UPLOADING,
                SIPStatus.UPLOADED,
                SIPStatus.ACCEPTED,
                SIPStatus.REJECTED,
            ):
                base_sip_path = os.path.join(
                    self.state.configuration.misc.save_location,
                    FileController.SIP_STORAGE,
                )
                # Check if the saved SIP and sidecar still exists
                if not os.path.exists(
                    os.path.join(
                        base_sip_path,
                        sip.file_name,
                    )
                    or not os.path.exists(
                        os.path.join(base_sip_path, sip.sidecare_file_name)
                    )
                ):
                    missing_sips.append(sip.name)

                    continue

            sip_widget = SIPWidget(sip=sip)

            try:
                if sip.metadata_file_path != "":
                    sip_widget.metadata_df = pd.read_excel(
                        sip.metadata_file_path, dtype=str
                    )
            except Exception:
                missing_sips.append(sip.name)
                continue

            sip.value_changed.connect(self.state.update_sip)

            # Uploading is not a valid state, could have happened because of forced shutdown during upload
            if sip.status == SIPStatus.UPLOADING:
                sip.set_status(SIPStatus.SIP_CREATED)

            result = FileController.existing_grid(
                self.application.state.configuration, sip
            )

            if result is not None:
                grid = result

                sip_widget.import_template_df = grid
                sip_widget.import_template_location = os.path.join(
                    self.application.state.configuration.misc.save_location,
                    FileController.IMPORT_TEMPLATE_STORAGE,
                    f"{sip.series._id}.xlsx",
                )

            if sip.status != SIPStatus.IN_PROGRESS:
                sip_widget.open_button.setEnabled(False)

            if sip.status == SIPStatus.SIP_CREATED:
                sip_widget.upload_button.setEnabled(True)
                
            if sip.status in (
                SIPStatus.UPLOADED,
                SIPStatus.PROCESSING,
                SIPStatus.ACCEPTED,
                SIPStatus.REJECTED,
                SIPStatus.SIP_CREATED,
            ):
                sip_widget.open_explorer_button.setEnabled(True)

            if sip.status in (SIPStatus.PROCESSING, SIPStatus.ACCEPTED, SIPStatus.REJECTED):
                sip_widget.open_edepot_button.setEnabled(True)

            self.sip_list_view.add_item(
                searchable_name_field="sip_name",
                widget=sip_widget,
            )

        if len(missing_sips) > 0:
            WarningDialog(
                title="Missende bestanden",
                text=f"Een of meerdere sips, sidecars of metadata zijn niet aanwezig.\n\nMissende sips: {json.dumps(missing_sips, indent=4)}\n\nDeze bestanden zijn nodig om gegevens in te laden, deze sips worden overgeslagen.",
            ).exec()

    def add_dossier_clicked(self, multi=False):
        dossier_path = QtWidgets.QFileDialog.getExistingDirectory(
            caption="Selecteer dossier om toe te voegen"
        )

        if dossier_path != "":
            paths = [dossier_path]

            if multi:
                paths = os.listdir(dossier_path)

            overlapping_labels = self.dossiers_list_view.get_overlapping_values(paths)

            unique_paths = [p for p in paths if p not in overlapping_labels]

            bad_dossiers = [
                os.path.normpath(os.path.join(dossier_path, partial_path))
                for partial_path in overlapping_labels
            ]
            dossiers = []
            dossier_widgets = []

            estimated_seconds = len(unique_paths) // 800

            if estimated_seconds > 2:
                WarningDialog(
                    title="Dossiers toevoegen",
                    text=f"Het toevoegen van veel dossiers kan een tijdje duren.\n\nGeschatte tijd: {estimated_seconds} seconden",
                ).exec()

            for partial_path in unique_paths:
                path = os.path.normpath(os.path.join(dossier_path, partial_path))

                # NOTE: we do not care about files in there, we only take the folders as dossiers
                if not os.path.isdir(path):
                    continue

                dossier = Dossier(path=path)
                dossiers.append(dossier)

                dossier_widget = DossierWidget(dossier=dossier)

                dossier_widgets.append(dossier_widget)

            self.dossiers_list_view.add_items(
                widgets=dossier_widgets,
                selection_changed_callback=self.dossier_selection_changed,
            )

            self.state.add_dossiers(dossiers=dossiers)

            if len(bad_dossiers) > 0:
                WarningDialog(
                    title="Dossiers niet toegevoegd",
                    text=f"Sommige dossiers overlappen in naamgeving met bestaande dossiers.\n\nDossiers die overlappen: {json.dumps(bad_dossiers, indent=4)}.\n\nVerander de namen van de dossiers (foldernamen) zodat ze uniek zijn in de lijst van dossiers en voeg opnieuw toe.",
                ).exec()

    def create_sip_clicked(self):
        selected_dossiers = list(self.dossiers_list_view.get_selected())

        if len(selected_dossiers) > 0:
            dossiers = [d.dossier for d in selected_dossiers]

            sip = SIP(
                environment_name=self.application.state.configuration.active_environment_name,
                dossiers=dossiers,
            )
            sip.value_changed.connect(self.state.update_sip)
            sip_widget = SIPWidget(sip=sip)

            success = self.sip_list_view.add_item(
                searchable_name_field="sip_id",
                widget=sip_widget,
            )

            if success:
                self.application.state.add_sip(sip)

                # Remove the dossiers from the list
                self.dossiers_list_view.remove_selected_clicked()

                # Open the SIP
                sip_widget.open_button_clicked()

    def dossier_selection_changed(self):
        self.create_sip_button.setEnabled(
            len(self.dossiers_list_view.get_selected()) > 0
        )

class MigrationWidget(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.application: Application = QtWidgets.QApplication.instance()
        self.state: State = self.application.state

    def setup_ui(self):
        grid_layout = QtWidgets.QGridLayout()
        self.setLayout(grid_layout)

        self.tab_widget = QtWidgets.QTabWidget()
        grid_layout.addWidget(self.tab_widget, 0, 0)

        self.tabs: dict[str, QtWidgets.QTableView] = dict()

        self.main_tab = "Overdrachtslijst"
        self.main_table = QtWidgets.QTableView()

    def load_items(self):
        self.create_db()
        self.load_overdrachtslijst()
        self.load_main_tab()

    def create_db(self):
        import sqlite3 as sql
        import os

        os.remove("main.db")
        conn = sql.connect("main.db")

        with conn:
            conn.execute("""
            CREATE TABLE tables (
                id INTEGER PRIMARY KEY,
                table_name TEXT,

                UNIQUE(table_name)
            );""")

            conn.execute(f"""
            INSERT INTO tables (table_name)
            VALUES ('{self.main_tab}');
            """)

            conn.execute(f"""
            CREATE TABLE {self.main_tab} (
                id INTEGER PRIMARY KEY,
                
                serie TEXT,

                doosnr TEXT,
                nr_van_het_archiefbestanddeel TEXT,
                beschrijving TEXT,
                begin_datum TEXT,
                eind_datum TEXT,
                bestemming TEXT,
                bewaar_termijn TEXT,
                verwijzing_informatiebeheersplan TEXT,
                datum_uitvoeren_bestemming TEXT
            );""")

            conn.commit()

    def load_overdrachtslijst(self):
        import pandas as pd
        from openpyxl import load_workbook
        import sqlite3 as sql

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption="Selecteer Overdrachtslijst", filter="Overdrachtslijst (*.xlsx *.xlsm *.xltx *.xltm)"
        )

        wb = load_workbook(
            path,
            read_only=True,
            data_only=True,
            keep_links=False,
            rich_text=False,
        )

        if not self.main_tab in wb.sheetnames:
            raise ValueError(f"{self.main_tab} tab missing")

        ws = wb[self.main_tab]
        data = ws.values

        header_transform = lambda h: str(h).strip().lower().replace(" ", "_").replace("-", "_").replace("\n", "").replace(".", "")

        while "doosnr" != header_transform((headers := next(data))[0]):
            pass
        
        # Filter out empty headers
        headers = [
            header_transform(h)
            for h in headers
            if h is not None
        ]

        # Filter out empty rows
        df = pd.DataFrame(
            (
                r for r in 
                (r[:len(headers)] for r in list(data))
                if not all(not bool(v) for v in r)
            ),
            columns=headers,
        ).fillna("").astype(str).convert_dtypes()

        con = sql.connect("main.db")
        df.to_sql(
            name=self.main_tab,
            con=con,
            index=False,
            method="multi",
            if_exists="append",
            chunksize=1000,
        )

    def load_main_tab(self):
        from creator.utils.sqlitemodel import SQLliteModel
        from creator.controllers.api_controller import APIController

        container = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        container.setLayout(layout)

        listed_series = APIController.get_series(self.state.configuration)
        
        series_combobox = QtWidgets.QComboBox()
        series_combobox.setEditable(True)
        series_combobox.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        series_combobox.completer().setCompletionMode(
            QtWidgets.QCompleter.PopupCompletion
        )
        series_combobox.completer().setFilterMode(
            QtCore.Qt.MatchFlag.MatchContains
        )
        series_combobox.setMaximumWidth(900)
        series_combobox.addItems(
            [s.get_name() for s in listed_series if s.status == "Published"]
        )

        btn = QtWidgets.QPushButton(text="Voeg toe")
        btn.clicked.connect(lambda: self.add_to_new(series_combobox.currentText()))

        model = SQLliteModel(self.main_tab, is_main=True)
        self.main_table.setModel(model)

        layout.addWidget(btn, 0, 0)
        layout.addWidget(series_combobox, 0, 1, 1, 3)
        layout.addWidget(self.main_table, 1, 0, 1, 5)

        self.tab_widget.addTab(container, self.main_tab)
        self.tabs[self.main_tab] = container

    def add_to_new(self, name: str):
        # NOTE: only thing not allowed is double-quotes
        name = name.strip().replace('"', "'")

        # No funny business
        if name == "" or name == self.main_tab:
            return

        conn = sql.connect("main.db")

        selected_rows = [str(r.row() + 1) for r in self.main_table.selectionModel().selectedRows()]

        if len(selected_rows) == 0:
            return

        selected_rows_str = ", ".join(selected_rows)

        with conn:
            # Create table
            conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{name}" (
                id INTEGER PRIMARY KEY,

                main_id INTEGER NOT NULL,

                path_in_sip TEXT,
                type TEXT,
                dossierref TEXT,
                analoog TEXT,
                naam TEXT,
                beschrijving TEXT,
                dossiercode_bron TEXT,
                stukreferentie_bron TEXT,
                openingsdatum TEXT,
                sluitingsdatum TEXT,
                id_bis_registernummer TEXT,
                id_rijksregisternummer TEXT,
                id_naam TEXT,
                kbo_nummer TEXT,
                ovo_code TEXT,
                organisatienaam TEXT,
                trefwoorden_vrij TEXT,
                opmerkingen TEXT,
                auteur TEXT,
                taal TEXT,
                openbaarheidsregime TEXT,
                openbaarheidsmotivering TEXT,
                hergebruikregime TEXT,
                hergebruikmotivering TEXT,
                creatiedatum TEXT,
                origineel_doosnummer TEXT,
                legacy_locatie_id TEXT,
                legacy_range TEXT,
                verpakkingstype TEXT
            );""")

            # Update the tables table
            conn.execute(f"""
                INSERT OR IGNORE INTO tables (table_name)
                VALUES ('"{name}"');
            """)

            # Remove where needed
            cursor = conn.execute(f"""
                SELECT id, serie
                FROM {self.main_tab}
                WHERE id IN ({selected_rows_str})
                  AND serie != '{name}';
            """)

            for main_id, table in cursor.fetchall():
                conn.execute(f"""
                    DELETE FROM "{table}"
                    WHERE main_id={main_id};
                """)

                rows = conn.execute(f"""
                    SELECT count() FROM "{table}";
                """).fetchone()[0]

                if rows == 0:
                    conn.execute(f"""
                        DROP TABLE "{table}";
                    """)
                    
                    conn.execute(f"""
                        DELETE FROM tables
                        WHERE table_name='"{name}"';
                    """)

                    self.tab_widget.removeTab(list(self.tabs).index(table))
                    del self.tabs[table]
                    
                    continue

                # Recalculate shape for table
                model: SQLliteModel = self.tabs[table].model()
                model.row_count = rows

                # Update the graphical side
                model.layoutChanged.emit()

            # Insert where needed
            conn.execute(f"""
                INSERT INTO "{name}" (main_id, origineel_doosnummer, beschrijving, openingsdatum, sluitingsdatum)
                SELECT id, doosnr, beschrijving, begin_datum, eind_datum
                FROM {self.main_tab}
                WHERE id IN ({selected_rows_str})
                  AND (serie != '{name}' OR serie IS NULL);
            """)
            
            # Update the main table to show correct linking
            conn.execute(f"""
                UPDATE {self.main_tab}
                SET serie='{name}'
                WHERE id IN ({selected_rows_str});
            """)

            # Update the graphical side
            model: SQLliteModel = self.main_table.model()
            model.layoutChanged.emit()

            conn.commit()

        # If the tab already exists, stop here
        if name in self.tabs:
            # Recalculate shape for table
            model: SQLliteModel = self.tabs[name].model()
            model.calculate_shape()
            
            # Update the graphical side
            model.layoutChanged.emit()

            return

        container = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        container.setLayout(layout)

        series_label = QtWidgets.QLabel(text=name)
        table_view = QtWidgets.QTableView()

        layout.addWidget(series_label, 0, 0)
        layout.addWidget(table_view, 1, 0)

        from creator.utils.sqlitemodel import SQLliteModel

        model = SQLliteModel(name)
        table_view.setModel(model)

        self.tab_widget.addTab(container, name)
        self.tabs[name] = table_view

def set_main(application: Application, main: MainWindow) -> None:
    config = application.state.configuration

    # TODO: use role
    active_role, active_type = config.active_role, config.active_type

    print(active_type)

    if active_type == "digitaal":
        main.central_widget = DigitalWidget(main)
        main.setWindowTitle("SIP Creator digitaal")
    else:
        main.central_widget = MigrationWidget(main)
        main.setWindowTitle("SIP Creator migratie")

    main.setCentralWidget(None)
    main.setCentralWidget(main.central_widget)
    main.central_widget.setup_ui()
    main.central_widget.load_items()
