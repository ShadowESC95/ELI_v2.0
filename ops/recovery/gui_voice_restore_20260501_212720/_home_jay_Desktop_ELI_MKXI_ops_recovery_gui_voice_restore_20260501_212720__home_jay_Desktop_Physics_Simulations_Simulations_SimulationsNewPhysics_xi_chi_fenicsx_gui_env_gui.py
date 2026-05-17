import sys
import numpy as np
import pyvista as pv
import meshio
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import QTimer
from pyvistaqt import BackgroundPlotter

# Helper mapping from meshio cell type to VTK integer
def cell_type_from_str(cell_type):
    vtk_types = {
        "triangle": 5,
        "tetra": 10,
        "quad": 9,
        "hexahedron": 12,
        "line": 3,
    }
    return vtk_types.get(cell_type, -1)

pv.cell_type_from_str = cell_type_from_str  # Inject for convenience

class FieldVisualizer(QMainWindow):
    def __init__(self, xdmf_folder="./data", timestep_interval=100):
        super().__init__()
        self.setWindowTitle("Ξ–χ Field Sandbox")
        self.xdmf_folder = xdmf_folder
        self.step = 0
        self.timestep_interval = timestep_interval

        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_visualization)

    def init_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout()

        self.start_button = QPushButton("Start Visualization")
        self.start_button.clicked.connect(self.start)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Visualization")
        self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button)

        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self.plotter = BackgroundPlotter(window_size=(800, 600))
        self.plotter.add_text("Ξ Field Evolution", position='upper_left', font_size=12)

    def start(self):
        self.timer.start(self.timestep_interval)

    def stop(self):
        self.timer.stop()

    def update_visualization(self):
        filename = f"{self.xdmf_folder}/xi_field{self.step:04d}.vtu"

        try:
            mesh = meshio.read(filename)

            if not mesh.cells:
                raise ValueError("No cells found in VTU file.")

            cell_block = mesh.cells[0]
            cell_type_str = cell_block.type
            cells = cell_block.data

            vtk_cell_type = pv.cell_type_from_str(cell_type_str)
            if vtk_cell_type == -1:
                raise ValueError(f"Unknown cell type: {cell_type_str}")
            cell_types = np.full(len(cells), vtk_cell_type)

            # Flatten cells for pyvista
            cells_flat = np.hstack([np.insert(cell, 0, len(cell)) for cell in cells])
            grid = pv.UnstructuredGrid(cells_flat, cell_types, mesh.points)

            if "Xi" in mesh.point_data:
                grid.point_data["Xi"] = mesh.point_data["Xi"]

            self.plotter.clear()
            self.plotter.add_mesh(grid, scalars="Xi", show_edges=False)
            self.step += 1

        except FileNotFoundError:
            self.timer.stop()
            print(f"No more time steps found at {filename}")
        except Exception as e:
            self.timer.stop()
            print(f"Error visualizing file '{filename}': {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = FieldVisualizer()
    viewer.show()
    sys.exit(app.exec_())

