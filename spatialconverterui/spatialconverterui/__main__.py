import sys
from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("spatialconverterui")
    app.setOrganizationName("vision-utils")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
