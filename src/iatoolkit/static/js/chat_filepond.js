function registerAvailableFilePondPlugins() {
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
}

function createSharedFilePond(inputElement, overrides = {}) {
    if (!inputElement || typeof FilePond === 'undefined') {
        return null;
    }

    return FilePond.create(inputElement, {
        allowMultiple: true,
        maxFiles: 5,
        maxFileSize: '30MB',
        acceptedFileTypes: [
            'image/*',
            'application/pdf',
            'text/plain',
            'text/csv',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ],
        labelIdle: '',
        credits: false,
        storeAsFile: true,
        ...overrides,
    });
}

window.createSharedFilePond = createSharedFilePond;

document.addEventListener('DOMContentLoaded', function () {
    // 1. Register FilePond Plugins
    // Ensure plugin scripts are loaded in your base layout or template
    registerAvailableFilePondPlugins();

    // 2. Create FilePond instance on the hidden input
    const inputElement = document.querySelector('input.filepond');

    // FilePond base configuration
    const filePond = createSharedFilePond(inputElement);

    // Expose globally so chat_main.js can access (getFiles, removeFiles)
    window.filePond = filePond;


    if (!filePond) return;
    // The question box takes pasted images itself (below); FilePond's own
    // listener on the whole page would add each of them a second time.
    filePond.setOptions({ allowPaste: false });
    const fileListContainer = document.getElementById('inline-file-list');
    const paperclipBtn = document.getElementById('paperclip-button');
    const overlay = document.getElementById('chat-drop-overlay');
    const dropTarget = document.querySelector('.chat-main') || document.getElementById('chat-container');
    const textarea = document.getElementById('question');
    const tr = (key, fallback) => {
        if (typeof window.t_js === 'function') {
            const text = window.t_js(key);
            if (text && text !== key) return text;
        }
        return fallback;
    };

    /** The Bootstrap icon for a file, by its type or extension. */
    function getFileIconClass(filename, type) {
        const ext = String(filename || '').split('.').pop().toLowerCase();
        if (type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) return 'bi-file-earmark-image';
        if (type === 'application/pdf' || ext === 'pdf') return 'bi-file-earmark-pdf';
        if (['xls', 'xlsx', 'csv'].includes(ext) || type.includes('spreadsheet') || type.includes('excel')) return 'bi-file-earmark-excel';
        if (['doc', 'docx'].includes(ext) || type.includes('word') || type.includes('document')) return 'bi-file-earmark-word';
        if (['txt', 'md', 'json', 'py', 'js', 'html', 'css'].includes(ext)) return 'bi-file-earmark-text';
        return 'bi-file-earmark';
    }

    function formatSize(bytes) {
        if (!bytes && bytes !== 0) return '';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    const previews = new Map();

    /** The attached files as chips inside the input bar, above the text. */
    function renderFileList() {
        if (!fileListContainer) return;
        const files = filePond.getFiles();
        fileListContainer.innerHTML = '';
        fileListContainer.hidden = files.length === 0;
        const alive = new Set(files.map(item => item.id));
        previews.forEach((url, id) => {
            if (!alive.has(id)) { URL.revokeObjectURL(url); previews.delete(id); }
        });

        files.forEach(fileItem => {
            const file = fileItem.file;
            const type = file.type || '';
            const chip = document.createElement('div');
            chip.className = 'file-chip';

            if (type.startsWith('image/')) {
                if (!previews.has(fileItem.id)) previews.set(fileItem.id, URL.createObjectURL(file));
                const thumb = document.createElement('img');
                thumb.className = 'file-chip-thumb';
                thumb.src = previews.get(fileItem.id);
                thumb.alt = '';
                chip.appendChild(thumb);
            } else {
                const icon = document.createElement('i');
                icon.className = `bi ${getFileIconClass(file.name, type)} file-chip-icon`;
                icon.setAttribute('aria-hidden', 'true');
                chip.appendChild(icon);
            }

            const text = document.createElement('span');
            text.className = 'file-chip-text';
            const name = document.createElement('span');
            name.className = 'file-chip-name';
            name.textContent = file.name;
            name.title = file.name;
            const size = document.createElement('span');
            size.className = 'file-chip-size';
            size.textContent = formatSize(file.size);
            text.append(name, size);
            chip.appendChild(text);

            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'file-chip-remove';
            remove.setAttribute('aria-label', `${tr('attach_remove', 'Quitar')} ${file.name}`);
            remove.innerHTML = '<i class="bi bi-x" aria-hidden="true"></i>';
            remove.addEventListener('click', (event) => {
                event.stopPropagation();
                filePond.removeFile(fileItem.id);
            });
            chip.appendChild(remove);
            fileListContainer.appendChild(chip);
        });

        if (files.length) {
            const counter = document.createElement('span');
            counter.className = 'file-chip-counter';
            counter.textContent = `${files.length}/${filePond.maxFiles || 5}`;
            counter.title = tr('attach_limits', '');
            fileListContainer.appendChild(counter);
        }
    }

    // -- Drop files anywhere on the chat: an overlay says where they go --
    const hasFiles = (event) => Array.from((event.dataTransfer && event.dataTransfer.types) || []).includes('Files');
    let dragDepth = 0;
    const showOverlay = (visible) => { if (overlay) overlay.hidden = !visible; };

    window.addEventListener('dragenter', (event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        dragDepth += 1;
        showOverlay(true);
    });
    window.addEventListener('dragover', (event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = dropTarget && dropTarget.contains(event.target) ? 'copy' : 'none';
    });
    window.addEventListener('dragleave', (event) => {
        if (!hasFiles(event)) return;
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) showOverlay(false);
    });
    window.addEventListener('drop', (event) => {
        if (!hasFiles(event)) return;
        // Never let the browser open the file in place of the chat.
        event.preventDefault();
        dragDepth = 0;
        showOverlay(false);
        if (dropTarget && dropTarget.contains(event.target) && event.dataTransfer.files.length) {
            filePond.addFiles(Array.from(event.dataTransfer.files));
        }
    });

    // -- Paste an image (a screenshot) straight into the question --
    if (textarea) {
        textarea.addEventListener('paste', (event) => {
            const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
            const files = items.filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
            if (!files.length) return;
            const pastedText = event.clipboardData.getData('text/plain');
            if (!pastedText) event.preventDefault();
            filePond.addFiles(files.map((file, index) => (
                file.name && file.name !== 'image.png'
                    ? file
                    : new File([file], `captura-${Date.now()}-${index + 1}.${(file.type.split('/')[1] || 'png')}`,
                               { type: file.type })
            )));
        });
    }

    // -- The (+) button opens the file picker --
    if (paperclipBtn) {
        paperclipBtn.addEventListener('click', function () {
            filePond.browse();
        });
    }

    // -- FilePond hooks --
    filePond.on('addfile', (error, file) => {
        if (error) {
            // Too large, a type not allowed, or over the limit: it goes, with the reason.
            const reason = [error.main, error.sub].filter(Boolean).join(' · ');
            if (window.toastr) window.toastr.warning(`${tr('attach_rejected', 'No se pudo adjuntar')} ${file && file.filename ? file.filename : ''}: ${reason}`);
            if (file) filePond.removeFile(file.id);
            return;
        }
        renderFileList();
    });
    filePond.on('removefile', () => renderFileList());
    filePond.on('warning', (error) => {
        if (window.toastr && error && error.body) window.toastr.warning(`${error.body}. ${tr('attach_limits', '')}`);
    });

    renderFileList();
});
