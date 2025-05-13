import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea, QSizePolicy,
                             QStatusBar) # Added QStatusBar
from PyQt6.QtCore import Qt, QSize, QDir, QRunnable, QThreadPool, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QIcon, QPalette, QColor, QImageReader, QImage
from ctypes import windll

# --- Constants ---
THUMBNAIL_TARGET_SIZE = QSize(200, 150)
IMAGE_WIDGET_FIXED_SIZE = QSize(220, 220) # Container for thumbnail, name, button
IMAGES_PER_ROW = 4
VALID_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp'] # GIF support can be added, QImageReader handles first frame
GRID_SPACING = 15

# --- Worker for Thumbnail Loading ---
class WorkerSignals(QObject):
    finished_one = pyqtSignal(str, QPixmap)  # image_path, thumbnail_pixmap
    finished_all = pyqtSignal(int)           # count of successfully loaded images
    error_loading_one = pyqtSignal(str, str) # image_path, error_message
    progress_message = pyqtSignal(str)       # For status updates

class ThumbnailLoader(QRunnable):
    def __init__(self, image_paths, thumbnail_size):
        super().__init__()
        self.signals = WorkerSignals()
        self.image_paths = image_paths
        self.thumbnail_size = thumbnail_size
        self._is_cancelled = False
        self.successfully_loaded_count = 0

    def run(self):
        total_images = len(self.image_paths)
        for i, image_path in enumerate(self.image_paths):
            if self._is_cancelled:
                self.signals.progress_message.emit("Image loading cancelled.")
                break
            
            self.signals.progress_message.emit(f"Loading image {i+1}/{total_images}: {os.path.basename(image_path)}")
            
            pixmap, error_msg = self._load_thumbnail_pixmap(image_path, self.thumbnail_size)
            if self._is_cancelled: # Check again after potentially slow load
                break

            if pixmap:
                self.signals.finished_one.emit(image_path, pixmap)
                self.successfully_loaded_count += 1
            else:
                self.signals.error_loading_one.emit(image_path, error_msg or "Unknown error loading thumbnail")
        
        if not self._is_cancelled:
            self.signals.finished_all.emit(self.successfully_loaded_count)

    def _load_thumbnail_pixmap(self, image_path, target_size):
        try:
            # Using QImage for better scaling control
            img = QImage(image_path)
            if img.isNull():
                # Fallback to QImageReader to get error string if QImage fails silently
                reader_check = QImageReader(image_path)
                err_str = f"Failed to load QImage. Reader error: {reader_check.errorString()}" if reader_check.error() != QImageReader.ImageReaderError.UnknownError else "Failed to load QImage."
                return None, err_str

            # Apply EXIF orientation if any (QImage doesn't do this automatically like QImageReader with setAutoTransform)
            # However, QImageReader.setAutoTransform(True) is usually applied before reader.read().
            # For direct QImage(path), this step might be needed if orientation is an issue.
            # For simplicity here, we rely on common image formats not needing manual EXIF handling
            # or assume pre-processing if it's critical.

            # Scale QImage smoothly
            scaled_img = img.scaled(target_size,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            
            return QPixmap.fromImage(scaled_img), None
        except Exception as e:
            return None, f"Exception during thumbnail generation: {str(e)}"

    def cancel(self):
        self._is_cancelled = True

class WallpaperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern Wallpaper Manager")
        self.setMinimumSize(1000, 700)
        
        self.setWindowIcon(QIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DesktopIcon)))
        
        self.set_dark_theme()
        
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        self.setup_top_panel()
        self.setup_image_area()
        self.setup_status_bar() # Added status bar
        
        self.image_files_paths = [] # Stores paths of images to be loaded
        self.current_directory = ""
        self.images_added_to_grid_count = 0
        self.current_row_widget = None
        self.current_row_layout = None

        self.thread_pool = QThreadPool.globalInstance()
        self.current_thumbnail_loader = None
        
        # Windows API for wallpaper setting (platform-specific)
        try:
            self.user32 = windll.user32
            self.SPI_SETDESKWALLPAPER = 0x0014
            self.SPIF_UPDATEINIFILE = 0x01
            self.SPIF_SENDWININICHANGE = 0x02 # Also known as SPIF_SENDCHANGE
        except AttributeError:
            self.user32 = None # Not on Windows or ctypes issue
            self.statusBar().showMessage("Warning: Could not initialize Windows API for setting wallpaper.", 5000)


        self._update_refresh_button_state()
        self.show_initial_message()


    def set_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white) # Keep, but QToolTip in QSS overrides
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.black) # Keep, but QToolTip in QSS overrides
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        
        self.setPalette(dark_palette)
        self.setStyleSheet("""
            QToolTip { 
                color: #ffffff; 
                background-color: #2a82da; 
                border: 1px solid white; 
                padding: 2px;
            }
            QPushButton {
                background-color: #353535;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 5px 10px; /* Adjusted padding */
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #454545;
                border: 1px solid #666;
            }
            QPushButton:pressed {
                background-color: #252525;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888888;
                border: 1px solid #454545;
            }
            QScrollArea {
                border: 1px solid #555;
                border-radius: 5px;
            }
            QLabel#imageLabel { /* For the image itself */
                border: 2px solid transparent;
                border-radius: 3px; /* Slightly rounded corners for the image */
                background-color: #2d2d2d; /* Background for empty space if image is smaller */
            }
            QLabel#imageLabel:hover {
                border: 2px solid #2a82da;
            }
            /* QLabel#imageLabel.selected { border: 2px solid #42d4f4; } */ /* Selection not implemented */
            QWidget#imageContainerWidget { /* For the widget holding image, name, button */
                 background-color: #3a3a3a; 
                 border-radius: 5px;
            }
            QStatusBar {
                color: white; /* Ensure status bar text is white */
            }
            QLabel#statusLabel { /* Specific for status message labels */
                font-size: 14px;
                padding: 10px;
            }
        """)

    def setup_top_panel(self):
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)
        
        self.folder_label = QLabel("Selected Folder: None")
        self.folder_label.setStyleSheet("font-size: 14px;")
        
        self.select_button = QPushButton("Select Folder")
        self.select_button.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        self.select_button.clicked.connect(self.select_directory)
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_BrowserReload))
        self.refresh_button.clicked.connect(self.refresh_images)
        
        top_layout.addWidget(self.folder_label, 1) # Add stretch factor
        # top_layout.addStretch() # Removed to allow label to take more space
        top_layout.addWidget(self.select_button)
        top_layout.addWidget(self.refresh_button)
        
        self.main_layout.addWidget(top_panel)

    def setup_image_area(self):
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        self.image_container_widget = QWidget() # This widget will hold the image_container_layout
        self.image_container_layout = QVBoxLayout(self.image_container_widget)
        self.image_container_layout.setContentsMargins(10, 10, 10, 10)
        self.image_container_layout.setSpacing(GRID_SPACING) # Use constant
        self.image_container_layout.setAlignment(Qt.AlignmentFlag.AlignTop) # Critical for rows to fill from top
        
        self.scroll_area.setWidget(self.image_container_widget)
        self.main_layout.addWidget(self.scroll_area)

    def setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready.", 3000)

    def _update_refresh_button_state(self):
        self.refresh_button.setEnabled(bool(self.current_directory))

    def show_initial_message(self):
        self.clear_image_container_content()
        initial_label = QLabel("Please select a folder to view wallpapers.")
        initial_label.setObjectName("statusLabel")
        initial_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_container_layout.addWidget(initial_label)

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", self.current_directory or QDir.homePath(), QFileDialog.Option.ShowDirsOnly)
        if directory:
            if self.current_thumbnail_loader and self.thread_pool.activeThreadCount() > 0:
                self.current_thumbnail_loader.cancel()
                self.status_bar.showMessage("Previous image loading cancelled.", 3000)

            self.current_directory = directory
            self.folder_label.setText(f"Selected Folder: {os.path.normpath(directory)}")
            self.status_bar.showMessage(f"Folder selected: {os.path.basename(directory)}", 3000)
            self.load_images_from_directory()
        self._update_refresh_button_state()

    def refresh_images(self):
        if self.current_directory:
            if self.current_thumbnail_loader and self.thread_pool.activeThreadCount() > 0:
                self.current_thumbnail_loader.cancel()
                self.status_bar.showMessage("Previous image loading cancelled.", 3000)
            self.status_bar.showMessage("Refreshing images...", 2000)
            self.load_images_from_directory()
        else:
            self.status_bar.showMessage("No folder selected to refresh.", 3000)

    def clear_image_container_content(self):
        # Remove all widgets from image_container_layout
        while self.image_container_layout.count():
            item = self.image_container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater() # Important for proper cleanup
        
        # Reset grid tracking variables
        self.images_added_to_grid_count = 0
        self.current_row_widget = None
        self.current_row_layout = None
        self.image_files_paths = []


    def load_images_from_directory(self):
        if not self.current_directory:
            self.show_initial_message()
            return

        self.clear_image_container_content()

        loading_label = QLabel("Scanning for images...")
        loading_label.setObjectName("statusLabel")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_container_layout.addWidget(loading_label) # Temporary loading label

        try:
            all_files = os.listdir(self.current_directory)
        except OSError as e:
            self.status_bar.showMessage(f"Error accessing directory: {e}", 5000)
            self.image_container_layout.takeAt(0).widget().deleteLater() # Remove "Scanning..."
            error_label = QLabel(f"Error accessing directory: {os.path.basename(self.current_directory)}\n{e}")
            error_label.setObjectName("statusLabel")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setWordWrap(True)
            self.image_container_layout.addWidget(error_label)
            return

        self.image_files_paths = [
            os.path.join(self.current_directory, f) for f in all_files
            if os.path.isfile(os.path.join(self.current_directory, f)) and 
               any(f.lower().endswith(ext) for ext in VALID_IMAGE_EXTENSIONS)
        ]

        self.image_container_layout.takeAt(0).widget().deleteLater() # Remove "Scanning..." or previous error label

        if not self.image_files_paths:
            no_files_label = QLabel("No images found in the selected directory.")
            no_files_label.setObjectName("statusLabel")
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_container_layout.addWidget(no_files_label)
            self.status_bar.showMessage("No images found.", 3000)
            return

        self.status_bar.showMessage(f"Found {len(self.image_files_paths)} images. Loading thumbnails...", 0) # Persistent until done

        # Setup and start the thumbnail loader worker
        if self.current_thumbnail_loader: # Should have been cancelled earlier, but as a safeguard
             self.current_thumbnail_loader.cancel()

        self.current_thumbnail_loader = ThumbnailLoader(self.image_files_paths, THUMBNAIL_TARGET_SIZE)
        self.current_thumbnail_loader.signals.finished_one.connect(self.add_thumbnail_to_grid)
        self.current_thumbnail_loader.signals.finished_all.connect(self.handle_all_thumbnails_loaded)
        self.current_thumbnail_loader.signals.error_loading_one.connect(self.handle_thumbnail_error)
        self.current_thumbnail_loader.signals.progress_message.connect(
            lambda msg: self.status_bar.showMessage(msg, 0) # Show progress continuously
        )
        self.thread_pool.start(self.current_thumbnail_loader)

    def add_thumbnail_to_grid(self, image_path, thumbnail_pixmap):
        if self.images_added_to_grid_count % IMAGES_PER_ROW == 0:
            # Start a new row
            self.current_row_widget = QWidget()
            self.current_row_layout = QHBoxLayout(self.current_row_widget)
            self.current_row_layout.setContentsMargins(0, 0, 0, 0)
            self.current_row_layout.setSpacing(GRID_SPACING)
            self.current_row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft) # Align items to the left of the row
            self.image_container_layout.addWidget(self.current_row_widget)
        
        image_display_widget = self.create_image_display_widget(image_path, thumbnail_pixmap)
        self.current_row_layout.addWidget(image_display_widget)
        self.images_added_to_grid_count += 1

        # Add stretch to the last row if it's not full, after all items are potentially added
        # This is better handled in handle_all_thumbnails_loaded or by ensuring rows always consume available space.


    def handle_all_thumbnails_loaded(self, count_loaded):
        if self.current_row_layout and self.images_added_to_grid_count % IMAGES_PER_ROW != 0:
            self.current_row_layout.addStretch() # Fill remaining space in the last row

        if count_loaded == 0 and not self.image_files_paths: # Double check if paths were there but none loaded
             # This case should be covered by initial scan, but as a fallback
            no_files_label = QLabel("No images found or loaded.")
            no_files_label.setObjectName("statusLabel")
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_container_layout.addWidget(no_files_label)
            self.status_bar.showMessage("No images were successfully loaded.", 3000)
        elif count_loaded == 0 and self.image_files_paths:
            self.status_bar.showMessage("Finished: 0 images loaded (all failed or cancelled).", 3000)
        else:
            self.status_bar.showMessage(f"Finished: Loaded {count_loaded} image thumbnails.", 5000)
        
        self.current_thumbnail_loader = None # Clear worker reference

    def handle_thumbnail_error(self, image_path, error_message):
        self.status_bar.showMessage(f"Error loading {os.path.basename(image_path)}: {error_message}", 5000)
        # Optionally, add a placeholder or error message in the grid for this specific image

    def create_image_display_widget(self, image_path, thumbnail_pixmap):
        container = QWidget()
        container.setObjectName("imageContainerWidget") # For styling the whole card
        container.setFixedSize(IMAGE_WIDGET_FIXED_SIZE)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8) # Padding inside the card
        layout.setSpacing(8) # Spacing between image, name, button

        # Image Label
        image_label = QLabel()
        image_label.setObjectName("imageLabel") # For styling
        image_label.setFixedSize(THUMBNAIL_TARGET_SIZE) # Thumbnail area
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if thumbnail_pixmap and not thumbnail_pixmap.isNull():
            # Center the pixmap within the label, scaled to fit but keeping aspect ratio
            # The pixmap is already scaled by the worker, here we just set it.
            # If the pixmap is smaller than the label, it will be centered.
            image_label.setPixmap(thumbnail_pixmap)
        else:
            image_label.setText("Error") # Placeholder for failed load
            image_label.setStyleSheet("color: red; background-color: #403030;")

        image_label.setScaledContents(False) # We handle scaling before setting pixmap

        # Filename Label
        filename = os.path.basename(image_path)
        name_label = QLabel(filename)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 11px;") # Slightly smaller font
        name_label.setWordWrap(True)
        name_label.setFixedHeight(35) # Allow for two lines of text

        # Set Wallpaper Button
        set_button = QPushButton("Set as Wallpaper")
        set_button.setFixedHeight(30)
        set_button.clicked.connect(lambda _, p=image_path: self.set_wallpaper(p))
        
        layout.addWidget(image_label)
        layout.addWidget(name_label)
        layout.addWidget(set_button)
        layout.addStretch() # Pushes content to top if container is larger than content sum

        return container
        
    def set_wallpaper(self, image_path):
        if not self.user32:
            self.status_bar.showMessage("Cannot set wallpaper: Windows API not available.", 5000)
            return
        try:
            # Ensure the path is absolute and correctly formatted for the API
            abs_image_path = os.path.abspath(image_path)
            
            # The SystemParametersInfoW function requires a Unicode string (LPWSTR)
            # Python strings are Unicode, ctypes handles conversion.
            result = self.user32.SystemParametersInfoW(
                self.SPI_SETDESKWALLPAPER,  
                0,  # uiParam, not used for this action
                abs_image_path,  
                self.SPIF_UPDATEINIFILE | self.SPIF_SENDWININICHANGE # Apply changes and notify other apps
            )
            if result:
                self.status_bar.showMessage(f"Wallpaper set: {os.path.basename(image_path)}", 3000)
            else:
                # You might want to use GetLastError() here for more detailed error info from Windows
                self.status_bar.showMessage("Failed to set wallpaper. (Windows API error)", 5000)
        except Exception as e:
            self.status_bar.showMessage(f"Error setting wallpaper: {str(e)}", 5000)

    def closeEvent(self, event):
        # Clean up threads if any are running
        if self.current_thumbnail_loader:
            self.current_thumbnail_loader.cancel()
        self.thread_pool.waitForDone(1000) # Wait up to 1 sec for threads to finish
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # app.setStyle("Fusion") # Optional: force a style if system default is problematic
    window = WallpaperApp()
    window.show()
    sys.exit(app.exec())
