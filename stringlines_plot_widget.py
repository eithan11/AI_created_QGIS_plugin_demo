from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout
from qgis.PyQt.QtCore import QUrl
# QWebEngineView is required to render Plotly HTML
from qgis.PyQt.QtWebEngineWidgets import QWebEngineView

class PlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.view = QWebEngineView()
        self.layout().addWidget(self.view)
        self.resize(800, 600)

    def load_html(self, html):
        # Use setHtml to load the plotly HTML (full HTML)
        self.view.setHtml(html, QUrl("about:blank"))
