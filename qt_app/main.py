"""Launch the Qt viewer with `python -m qt_app.main --ip 192.168.1.10`."""

import argparse
import ipaddress
import sys

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

import app.app_state as app_state
import version
from qt_app.window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="MSO5000 Qt live viewer")
    parser.add_argument("--ip", help="Scope IPv4 address")
    parser.add_argument("--version", action="version", version=version.VERSION)
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    ip = args.ip
    if not ip:
        ip, ok = QInputDialog.getText(None, "Connect to scope", "MSO5000 IPv4 address:")
        if not ok:
            return 0
    try:
        address = ipaddress.ip_address(ip.strip())
        if not isinstance(address, ipaddress.IPv4Address):
            raise ValueError
    except ValueError:
        QMessageBox.warning(None, "Invalid address", "Enter a valid IPv4 address.")
        return 2
    app_state.is_shutting_down = False
    window = MainWindow(str(address))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
