import sys
import os
import warnings
from PyQt6.QtWidgets import QApplication
from interfaz import InterfazBase

os.environ["POSTHOG_DISABLED"] = "1"
warnings.filterwarnings("ignore")

def iniciar_aplicacion():
    app = QApplication(sys.argv)
    ventana = InterfazBase()
    ventana.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    iniciar_aplicacion()