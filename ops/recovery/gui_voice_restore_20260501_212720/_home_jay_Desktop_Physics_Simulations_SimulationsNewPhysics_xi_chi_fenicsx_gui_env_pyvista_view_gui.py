import os
import glob
import numpy as np
import pandas as pd
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt5 import QtWidgets, QtCore

# ----------------------------
# USER PARAMETERS
# ----------------------------
vtu_dir = "output_with_u"
fields = ["Xi", "Chi", "E"]  # available fields
output_csv_dir = "outputs/field_metrics"
os.makedirs(output_csv_dir, exist_ok=True)

# ----------------------------
# LOAD VTU SERIES
# ----------------------------
vtu_files = sorted(glob.glob(os.path.join(vtu_dir, "*.vtu")))
if not vtu_files:
    raise FileNotFoundError(f"No VTU files found in {vtu_dir}")
mesh_series = [pv.read(f) for f in vtu_files]

# ----------------------------
# COMPUTE METRICS
# ----------------------------
def compute_metrics(mesh, field_name="Xi"):
    if field_name not in mesh.point_arrays:
        raise KeyError(f"Field '{field_name}' not in mesh.point_arrays")
    vec = mesh.point_arrays[field_name]
    if vec.ndim == 1:
        vec = np.stack([vec]*3, axis=1)
    div = np.gradient(vec, axis=0).sum(axis=1)
    curl = np.cross(np.gradient(vec, axis=0), vec)
    energy = 0.5 * np.sum(vec**2, axis=1)
    return div, curl, energy

# ----------------------------
# GUI
# ----------------------------
class FieldAnalyzerGUI(QtWidgets.QWidget):
    def __init__(self, mesh_series, fields):
        super().__init__()
        self.mesh_series = mesh_series
        self.fields = fields
        self.idx = 0
        self.current_field = fields[0]
        self.plotter = pv.QtInteractor(self)
        
        # layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.plotter.interactor)

        # control buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.next_btn = QtWidgets.QPushButton("Next timestep")
        self.next_btn.clicked.connect(self.next_step)
        self.prev_btn = QtWidgets.QPushButton("Prev timestep")
        self.prev_btn.clicked.connect(self.prev_step)
        self.field_select = QtWidgets.QComboBox()
        self.field_select.addItems(fields)
        self.field_select.currentTextChanged.connect(self.change_field)
        self.slice_toggle = QtWidgets.QPushButton("Toggle Slice/Volume")
        self.slice_toggle.setCheckable(True)
        self.slice_toggle.clicked.connect(self.update_plot)
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.field_select)
        btn_layout.addWidget(self.slice_toggle)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.update_plot()

    def change_field(self, text):
        self.current_field = text
        self.update_plot()

    def next_step(self):
        self.idx = (self.idx + 1) % len(self.mesh_series)
        self.update_plot()

    def prev_step(self):
        self.idx = (self.idx - 1) % len(self.mesh_series)
        self.update_plot()

    def update_plot(self):
        self.plotter.clear()
        mesh = self.mesh_series[self.idx]
        try:
            div, curl, energy = compute_metrics(mesh, self.current_field)
            df = pd.DataFrame({"div": div, "curl_x": curl[:,0], "curl_y": curl[:,1], "curl_z": curl[:,2], "energy": energy})
            df.to_csv(os.path.join(output_csv_dir, f"field_metrics_{self.current_field}_t{self.idx:04d}.csv"), index=False)
        except KeyError:
            print(f"Field {self.current_field} not found in timestep {self.idx}")

        if self.slice_toggle.isChecked():
            slice_mesh = mesh.slice(normal='z')
            self.plotter.add_mesh(slice_mesh, scalars=self.current_field, cmap="coolwarm")
        else:
            self.plotter.add_mesh(mesh, scalars=self.current_field, cmap="coolwarm")

        self.plotter.reset_camera()
        self.plotter = QtInteractor(self)


# ----------------------------
# RUN
# ----------------------------
app = QtWidgets.QApplication([])
window = FieldAnalyzerGUI(mesh_series, fields)
window.setWindowTitle("Ξ–χ–E Field Analyzer")
window.resize(1280, 800)
window.show()

# auto animation
timer = QtCore.QTimer()
timer.timeout.connect(window.next_step)
timer.start(800)  # ms per frame
app.exec()

