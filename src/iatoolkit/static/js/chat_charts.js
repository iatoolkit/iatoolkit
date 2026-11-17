/**
 * Output charts and other answer parts in the chat (BL-025).
 *
 * The server sends each chart as a part of the answer: its ECharts option
 * (data only, built by ChartService), its rows and where they came from. The
 * answer HTML has an empty slot per part (`.iat-part[data-part-id]`); this
 * module fills it. ECharts loads from the CDN the first time an answer has a
 * chart. Number formatting, the theme and the controls (image, bars/lines,
 * the data as a table, CSV, the SQL) are added here, never by the model.
 */
(function (global) {
    'use strict';

    const ECHARTS_URL = 'https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js';
    const CHART_HEIGHT_PX = 340;
    const MARKER = /\[\[chart:([a-z0-9]{6,32})\]\]/g;

    let echartsLoading = null;

    function t(key, fallback) {
        if (typeof global.t_js === 'function') {
            const text = global.t_js(key);
            if (text && text !== key) return text;
        }
        return fallback || key;
    }

    function loadEcharts() {
        if (global.echarts) return Promise.resolve(global.echarts);
        if (echartsLoading) return echartsLoading;
        echartsLoading = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = ECHARTS_URL;
            script.async = true;
            script.onload = () => (global.echarts ? resolve(global.echarts) : reject(new Error('echarts missing')));
            script.onerror = () => {
                echartsLoading = null;
                reject(new Error('echarts failed to load'));
            };
            document.head.appendChild(script);
        });
        return echartsLoading;
    }

    function isDarkTheme() {
        const root = document.documentElement;
        const explicit = root.getAttribute('data-bs-theme') || document.body.getAttribute('data-bs-theme');
        if (explicit) return explicit === 'dark';
        return false;
    }

    function locale() {
        return document.documentElement.lang || navigator.language || 'es';
    }

    function numberFormatter(format) {
        const plain = new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 });
        return (value) => {
            if (value === null || value === undefined || value === '' || isNaN(Number(value))) return '–';
            const text = plain.format(Number(value));
            if (format === 'percent') return `${text} %`;
            if (format === 'currency') return `$${text}`;
            return text;
        };
    }

    /** The server's option, plus what a function or the page decides. */
    function finishOption(chart, dark) {
        const option = JSON.parse(JSON.stringify(chart.echarts || {}));
        const formatValue = numberFormatter(chart.format);
        option.backgroundColor = 'transparent';
        option.animationDuration = 400;
        option.tooltip = Object.assign({}, option.tooltip, { valueFormatter: formatValue, confine: true });
        if (option.yAxis && option.yAxis.type === 'value') {
            option.yAxis = Object.assign({}, option.yAxis, { axisLabel: { formatter: formatValue } });
        }
        if (option.xAxis && option.xAxis.type === 'category') {
            option.xAxis = Object.assign({}, option.xAxis, { axisLabel: { hideOverlap: true } });
        }
        if (option.title) {
            option.title = Object.assign({}, option.title, {
                textStyle: { fontSize: 15, fontWeight: 600, color: dark ? '#e6e6e6' : '#212529' },
            });
        }

        const features = {
            saveAsImage: {
                title: t('chart_download_png', 'Descargar imagen'),
                name: (chart.title || 'grafico').replace(/[^\w\-áéíóúñÁÉÍÓÚÑ ]+/g, '').trim() || 'grafico',
                backgroundColor: dark ? '#212529' : '#ffffff',
                pixelRatio: 2,
            },
        };
        if (['bar', 'line', 'area', 'combo'].includes(chart.type)) {
            const types = ['bar', 'line'];
            if ((chart.series || []).length > 1) types.push('stack');
            features.magicType = {
                type: types,
                title: { bar: t('chart_as_bars', 'Barras'), line: t('chart_as_lines', 'Líneas'), stack: t('chart_stack', 'Apilar') },
            };
        }
        option.toolbox = { right: 4, top: 0, itemSize: 14, feature: features };
        return option;
    }

    function csvOf(chart) {
        const escape = (value) => {
            const text = value === null || value === undefined ? '' : String(value);
            return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
        };
        const lines = [chart.columns || []].concat(chart.rows || []).map((row) => row.map(escape).join(','));
        return '﻿' + lines.join('\n');
    }

    function download(filename, content, type) {
        const blob = new Blob([content], { type });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function dataTable(chart) {
        const labels = {};
        (chart.series || []).forEach((s) => { labels[s.field] = s.label || s.field; });
        const formatValue = numberFormatter(chart.format);
        const table = $('<table>');
        const head = $('<tr>');
        (chart.columns || []).forEach((column) => head.append($('<th>').text(labels[column] || column)));
        table.append($('<thead>').append(head));
        const body = $('<tbody>');
        (chart.rows || []).forEach((row) => {
            const tr = $('<tr>');
            row.forEach((value, index) => {
                const cell = $('<td>');
                if (index === 0) cell.text(value === null ? '' : String(value));
                else cell.attr('align', 'right').text(formatValue(value));
                tr.append(cell);
            });
            body.append(tr);
        });
        return $('<div>').addClass('iat-chart-data').append(table.append(body));
    }

    function controls(chart, figure) {
        const bar = $('<div>').addClass('iat-chart-controls');
        const canvas = figure.find('.iat-chart-canvas');
        let table = null;

        const toggle = $('<button type="button">').addClass('iat-chart-control').text(t('chart_view_data', 'Ver datos'));
        toggle.on('click', () => {
            if (!table) {
                table = dataTable(chart).hide();
                canvas.after(table);
            }
            const showing = table.is(':visible');
            table.toggle(!showing);
            canvas.toggle(showing);
            toggle.text(showing ? t('chart_view_data', 'Ver datos') : t('chart_view_chart', 'Ver gráfico'));
            if (showing && figure.data('chart')) figure.data('chart').resize();
        });

        const csv = $('<button type="button">').addClass('iat-chart-control').text(t('chart_download_csv', 'Descargar CSV'));
        csv.on('click', () => download(`${chart.title || 'grafico'}.csv`, csvOf(chart), 'text/csv;charset=utf-8'));

        bar.append(toggle, csv);

        const source = chart.source || {};
        if (source.kind === 'sql' && source.query) {
            const details = $('<details>').addClass('iat-chart-sql');
            details.append($('<summary>').text(`${t('chart_show_sql', 'Consulta SQL')} · ${source.database_key || ''}`));
            details.append($('<pre>').append($('<code>').text(source.query)));
            figure.append(bar, details);
        } else {
            figure.append(bar);
        }
        (chart.notes || []).forEach((note) => figure.append($('<div>').addClass('iat-chart-note').text(note)));
    }

    function renderChart(slot, chart) {
        const figure = $('<figure>').addClass('iat-chart').attr('data-part-id', chart.id);
        const canvas = $('<div>').addClass('iat-chart-canvas').css('height', `${CHART_HEIGHT_PX}px`);
        const pending = $('<div>').addClass('iat-chart-pending').text(t('chart_pending', 'Preparando el gráfico…'));
        figure.append(canvas.append(pending));
        $(slot).replaceWith(figure);

        return loadEcharts().then((echarts) => {
            pending.remove();
            const dark = isDarkTheme();
            const instance = echarts.init(canvas[0], dark ? 'dark' : null, { renderer: 'canvas' });
            instance.setOption(finishOption(chart, dark));
            figure.data('chart', instance);
            if (typeof ResizeObserver === 'function') {
                const observer = new ResizeObserver(() => instance.resize());
                observer.observe(canvas[0]);
            }
            controls(chart, figure);
        }).catch(() => {
            pending.text(t('chart_unavailable', 'No se pudo dibujar el gráfico.')).addClass('iat-chart-failed');
            // The numbers are still worth having: offer them as a table.
            controls(chart, figure);
        });
    }

    function fileIcon(part) {
        const name = String(part.filename || '').toLowerCase();
        const mime = String(part.mime_type || '').toLowerCase();
        if (mime.includes('spreadsheet') || /\.(xlsx|xls|csv)$/.test(name)) return 'bi-file-earmark-excel';
        if (mime.includes('pdf') || name.endsWith('.pdf')) return 'bi-file-earmark-pdf';
        if (mime.includes('word') || /\.docx?$/.test(name)) return 'bi-file-earmark-word';
        if (mime.startsWith('image/')) return 'bi-file-earmark-image';
        return 'bi-file-earmark-arrow-down';
    }

    /** A file a tool generated, as a download card (BL-025). */
    function fileCard(part) {
        if (part.expired) {
            // A file of an old conversation, deleted after the tenant's retention (BL-001).
            const gone = $('<span>').addClass('iat-file-card is-expired').attr('data-part-id', part.id);
            gone.append($('<i>').addClass(`bi ${fileIcon(part)} iat-file-card-icon`));
            const goneText = $('<span>').addClass('iat-file-card-text');
            goneText.append($('<span>').addClass('iat-file-card-name').text(part.filename || ''));
            goneText.append($('<span>').addClass('iat-file-card-action').text(t('part_file_expired', 'Archivo vencido')));
            return gone.append(goneText);
        }
        const card = $('<a>')
            .addClass('iat-file-card')
            .attr({ href: part.url, target: '_blank', rel: 'noopener', 'data-part-id': part.id });
        card.append($('<i>').addClass(`bi ${fileIcon(part)} iat-file-card-icon`));
        const text = $('<span>').addClass('iat-file-card-text');
        text.append($('<span>').addClass('iat-file-card-name').text(part.filename || ''));
        text.append($('<span>').addClass('iat-file-card-action').text(t('part_file_download', 'Descargar')));
        card.append(text);
        return card;
    }

    /** Fills the answer's part slots with the parts the turn returned: charts
     *  are drawn, files become download cards (also where the answer links them). */
    function renderParts(container, parts) {
        const byId = {};
        (parts || []).forEach((part) => { if (part && part.id) byId[part.id] = part; });
        const pending = [];
        $(container).find('.iat-part[data-part-id]').each(function () {
            const part = byId[this.getAttribute('data-part-id')];
            if (part && part.kind === 'chart') {
                pending.push(renderChart(this, part));
            } else if (part && part.kind === 'file') {
                $(this).replaceWith(fileCard(part));
            } else {
                $(this).remove();
            }
        });
        (parts || []).filter((part) => part && part.kind === 'file' && part.url).forEach((part) => {
            $(container).find('a[href]').not('.iat-file-card').each(function () {
                if (this.getAttribute('href') === part.url) $(this).replaceWith(fileCard(part));
            });
        });
        return Promise.all(pending);
    }

    // ---- Diagrams: ```mermaid blocks (BL-025, PR-6) ---------------------------
    const MERMAID_URL = 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js';
    let mermaidLoading = null;
    let diagramCount = 0;

    function loadMermaid() {
        if (global.mermaid) return Promise.resolve(global.mermaid);
        if (mermaidLoading) return mermaidLoading;
        mermaidLoading = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = MERMAID_URL;
            script.async = true;
            script.onload = () => {
                if (!global.mermaid) return reject(new Error('mermaid missing'));
                // strict: no HTML in labels, no click handlers, no scripts.
                global.mermaid.initialize({
                    startOnLoad: false,
                    securityLevel: 'strict',
                    theme: isDarkTheme() ? 'dark' : 'neutral',
                    fontFamily: 'inherit',
                });
                resolve(global.mermaid);
            };
            script.onerror = () => {
                mermaidLoading = null;
                reject(new Error('mermaid failed to load'));
            };
            document.head.appendChild(script);
        });
        return mermaidLoading;
    }

    /**
     * Models often write node labels with parentheses or other symbols without
     * quotes (`A[Orden (OC)]`), which Mermaid rejects. Quoting them is safe:
     * `A["Orden (OC)"]` means the same node.
     */
    function quoteMermaidLabels(code) {
        return String(code)
            .replace(/(\b[\w-]+)\[(?!["(\[\/\\])([^\]\n"]*[(){}<>:;#&|][^\]\n"]*)\](?!\))/g, '$1["$2"]')
            .replace(/(\b[\w-]+)\{(?!["{])([^}\n"]*[()\[\]<>:;#&|][^}\n"]*)\}/g, '$1{"$2"}')
            .replace(/(\b[\w-]+)\(\[(?!")([^\]\n"]*[(){}<>:;#&|][^\]\n"]*)\]\)/g, '$1(["$2"])');
    }

    function renderMermaid(mermaid, code) {
        diagramCount += 1;
        const id = `iat-diagram-${Date.now()}-${diagramCount}`;
        return mermaid.render(id, code).catch((error) => {
            const repaired = quoteMermaidLabels(code);
            if (repaired === code) throw error;
            diagramCount += 1;
            return mermaid.render(`${id}-r`, repaired);
        });
    }

    function renderDiagram(pre) {
        const code = $(pre).find('code.language-mermaid').text();
        if (!code.trim()) return Promise.resolve();
        return loadMermaid().then((mermaid) => renderMermaid(mermaid, code)).then(({ svg }) => {
            const figure = $('<figure>').addClass('iat-diagram');
            const drawing = $('<div>').addClass('iat-diagram-svg').html(svg);
            const source = $(pre).clone().addClass('iat-diagram-source').hide();
            const bar = $('<div>').addClass('iat-chart-controls');
            const toggle = $('<button type="button">').addClass('iat-chart-control').text(t('diagram_view_code', 'Ver código'));
            toggle.on('click', () => {
                const showing = source.is(':visible');
                source.toggle(!showing);
                drawing.toggle(showing);
                toggle.text(showing ? t('diagram_view_code', 'Ver código') : t('diagram_view_diagram', 'Ver diagrama'));
            });
            const save = $('<button type="button">').addClass('iat-chart-control').text(t('diagram_download_svg', 'Descargar SVG'));
            save.on('click', () => download('diagrama.svg', svg, 'image/svg+xml'));
            figure.append(drawing, source, bar.append(toggle, save));
            $(pre).replaceWith(figure);
        }).catch(() => {
            // A diagram that does not parse stays as the code it is.
        });
    }

    /** Draws the answer's ```mermaid blocks as diagrams. */
    function renderDiagrams(container) {
        const blocks = $(container).find('pre').filter(function () {
            return $(this).find('code.language-mermaid').length > 0;
        });
        return Promise.all(blocks.toArray().map(renderDiagram));
    }

    /** While the answer streams, a marker shows as a waiting block. */
    function replaceMarkersWhileStreaming(html) {
        return String(html || '').replace(MARKER, () =>
            `<span class="iat-chart-pending iat-chart-pending-inline">${$('<span>').text(t('chart_pending', 'Preparando el gráfico…')).html()}</span>`);
    }

    global.IATCharts = { renderParts, renderDiagrams, quoteMermaidLabels, replaceMarkersWhileStreaming, loadEcharts, ECHARTS_URL };
})(window);
