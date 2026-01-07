document.addEventListener('DOMContentLoaded', function () {
    // 1. Register FilePond Plugins
    // Ensure plugin scripts are loaded in your base layout or template
    if (typeof FilePondPluginFileEncode !== 'undefined') {
        FilePond.registerPlugin(FilePondPluginFileEncode);
    }
    if (typeof FilePondPluginFileValidateSize !== 'undefined') {
        FilePond.registerPlugin(FilePondPluginFileValidateSize);
    }
    if (typeof FilePondPluginFileValidateType !== 'undefined') {
        FilePond.registerPlugin(FilePondPluginFileValidateType);
    }
    if (typeof FilePondPluginImagePreview !== 'undefined') {
        FilePond.registerPlugin(FilePondPluginImagePreview);
    }

    // 2. Create FilePond instance on the hidden input
    const inputElement = document.querySelector('input.filepond');

    // FilePond base configuration
    const filePond = FilePond.create(inputElement, {
        allowMultiple: true,
        maxFiles: 5,
        maxFileSize: '10MB', // Adjust as needed
        // Extensive list of accepted types (Images, PDF, Text, Excel, Word)
        acceptedFileTypes: [
            'image/*',
            'application/pdf',
            'text/plain',
            'text/csv',
            'application/vnd.ms-excel',                                                 // .xls
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',        // .xlsx
            'application/msword',                                                       // .doc
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'   // .docx
        ],
        labelIdle: '', // Left empty because we use our own UI
        credits: false,
        storeAsFile: true, // Important for encode to work if used
    });

    // Expose globally so chat_main.js can access (getFiles, removeFiles)
    window.filePond = filePond;


    // 3. DOM references for the new custom UI
    const dropzone = document.getElementById('chat-dropzone');
    const fileListContainer = document.getElementById('inline-file-list');
    const fileCounter = document.getElementById('file-counter');
    const paperclipBtn = document.getElementById('paperclip-button');


    // 4. Rendering Functions

    /**
     * Returns the Bootstrap icon class based on filename or file type.
     */
    function getFileIconClass(filename, type) {
        const ext = filename.split('.').pop().toLowerCase();

        // Images
        if (type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) {
            return 'bi-file-earmark-image';
        }
        // PDF
        if (type === 'application/pdf' || ext === 'pdf') {
            return 'bi-file-earmark-pdf';
        }
        // Excel / Spreadsheets
        if (['xls', 'xlsx', 'csv'].includes(ext) || type.includes('spreadsheet') || type.includes('excel')) {
            return 'bi-file-earmark-excel';
        }
        // Word / Documents
        if (['doc', 'docx'].includes(ext) || type.includes('word') || type.includes('document')) {
            return 'bi-file-earmark-word';
        }
        // Text / Code
        if (['txt', 'md', 'json', 'py', 'js', 'html', 'css'].includes(ext)) {
            return 'bi-file-earmark-text';
        }

        // Default icon
        return 'bi-file-earmark';
    }

    /**
     * Rebuilds the visual file list below the input.
     */
    function renderFileList() {
        if (!fileListContainer) return;

        const files = filePond.getFiles();
        fileListContainer.innerHTML = ''; // Clear current list

        if (files.length > 0) {
            fileListContainer.style.display = 'block';

            // Update counter
            if (fileCounter) {
                fileCounter.textContent = `${files.length}/${filePond.maxFiles || 5}`;
                fileCounter.style.display = 'inline-block';
            }

            files.forEach(fileItem => {
                const file = fileItem.file;
                const iconClass = getFileIconClass(file.name, file.type || '');

                // Create file row
                const row = document.createElement('div');
                row.className = 'file-list-item';

                row.innerHTML = `
                    <i class="bi ${iconClass} file-icon"></i>
                    <span class="file-name" title="${file.name}">${file.name}</span>
                    <i class="bi bi-x-circle-fill file-remove" role="button" aria-label="Remove file"></i>
                `;

                // Click event on the remove button of the row
                const removeBtn = row.querySelector('.file-remove');
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation(); // Prevent click propagation if nested in a clickable area
                    filePond.removeFile(fileItem.id);
                });

                fileListContainer.appendChild(row);
            });
        } else {
            // Hide list and counter if no files
            fileListContainer.style.display = 'none';
            if (fileCounter) fileCounter.style.display = 'none';
        }
    }


    // 5. Interaction Event Management

    // -- Custom Dropzone Robust Handling --
    if (dropzone) {
        // Prevent default browser behavior for drag events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        // Highlight dropzone on drag enter/over
        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, () => {
                dropzone.classList.add('drag-over');
            }, false);
        });

        // Remove highlight on drag leave or drop
        // Note: checking relatedTarget prevents flickering when dragging over child elements
        dropzone.addEventListener('dragleave', (e) => {
            if (!dropzone.contains(e.relatedTarget)) {
                dropzone.classList.remove('drag-over');
            }
        }, false);

        dropzone.addEventListener('drop', (e) => {
            dropzone.classList.remove('drag-over');

            // Pass dropped files to FilePond
            // We convert FileList to Array to ensure compatibility
            if (e.dataTransfer && e.dataTransfer.files.length > 0) {
                filePond.addFiles(Array.from(e.dataTransfer.files));
            }
        }, false);

        // Click on zone opens native selector
        dropzone.addEventListener('click', function() {
            filePond.browse();
        });
    }

    // -- "Clip" Button (Legacy design compatibility) --
    if (paperclipBtn) {
        paperclipBtn.addEventListener('click', function() {
            filePond.browse();
        });
    }


    // 6. FilePond Hooks for Reactivity

    // On file add (even if validation error, FilePond manages array)
    filePond.on('addfile', (error, file) => {
        if (error) {
            console.error('FilePond Error:', error);
            // Optional: Show error toast if file is invalid (e.g., too large)
            return;
        }
        renderFileList();
    });

    // On file remove
    filePond.on('removefile', (error, file) => {
        renderFileList();
    });

    // Event for general error (e.g., type not allowed on drop)
    filePond.on('warning', (error) => {
        console.warn('FilePond Warning:', error);
    });

    // Initialization: Initial render in case browser cached state
    renderFileList();
});