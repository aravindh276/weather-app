/**
 * SAP Transport Comparison Tool
 *
 * Compares STMS_IMPORT transport histories from Production and Test systems
 * to identify transports that need re-importing after a system refresh.
 *
 * SAP Transport Number Format:
 *   - Pattern: <SID>K<NNNNNN> (e.g., DEVK900001)
 *   - SID = 3-character System ID (e.g., DEV, ERP, S4H)
 *   - K = constant character
 *   - NNNNNN = 6-digit sequential number
 *
 * Transport of Copies:
 *   - Created via SE01/SE09 as "Transport of Copies"
 *   - Contains copies of objects from other transports
 *   - The transport number itself does NOT differ in format from regular transports
 *   - Identified by description keywords or by the "Transport of Copies" type in STMS
 *   - Common description patterns: "Transport of Copies", "TOC", "Copy of <transport>"
 *   - May reference a main/parent transport in the description
 */

// ============================================================
// FILE UPLOAD HANDLERS
// ============================================================

document.getElementById('prodFile').addEventListener('change', function (e) {
    handleFileUpload(e, 'prodInput');
});

document.getElementById('testFile').addEventListener('change', function (e) {
    handleFileUpload(e, 'testInput');
});

function handleFileUpload(event, targetTextareaId) {
    const file = event.target.files[0];
    if (!file) return;

    const extension = file.name.split('.').pop().toLowerCase();

    if (extension === 'xlsx' || extension === 'xls') {
        // For Excel files, we need to inform the user
        // Since we're running client-side only, we handle .xlsx via a basic approach
        alert('Excel file detected. For best results, please save as .txt or .csv from SAP and upload that instead.\n\nAlternatively, open the Excel file, select all data, copy, and paste into the text area.');
        event.target.value = '';
        return;
    }

    const reader = new FileReader();
    reader.onload = function (e) {
        document.getElementById(targetTextareaId).value = e.target.result;
    };
    reader.readAsText(file);
}

// ============================================================
// TRANSPORT PARSING
// ============================================================

/**
 * SAP transport number regex.
 * Matches patterns like DEVK900001, ERPK912345, S4HK800100, etc.
 * Format: 3 alphanumeric chars + 'K' + 6 digits
 */
const TRANSPORT_REGEX = /\b([A-Z][A-Z0-9]{2}K\d{6})\b/g;

/**
 * Patterns that indicate a "Transport of Copies" in the description.
 */
const COPY_INDICATORS = [
    /transport\s+of\s+cop(y|ies)/i,
    /\bTOC\b/,
    /\bcopy\s+of\b/i,
    /\bcopied\s+from\b/i,
    /\brelocated\s+copy\b/i
];

/**
 * Parse raw text input from STMS_IMPORT export.
 * Returns an array of transport objects.
 */
function parseTransportList(rawText) {
    if (!rawText || !rawText.trim()) return [];

    const lines = rawText.split('\n');
    const transports = [];
    const seen = new Set();

    for (const line of lines) {
        const trimmedLine = line.trim();
        if (!trimmedLine) continue;

        // Find all transport numbers in the line
        const matches = [...trimmedLine.matchAll(TRANSPORT_REGEX)];
        if (matches.length === 0) continue;

        // The first transport number on the line is the main transport being listed
        const transportNumber = matches[0][1];

        // Skip duplicates (take first occurrence)
        if (seen.has(transportNumber)) continue;
        seen.add(transportNumber);

        // Extract return code if present
        const rcMatch = trimmedLine.match(/\bRC\s*[=:]\s*(\d+)/i) ||
            trimmedLine.match(/\breturn\s*code\s*[=:]\s*(\d+)/i);
        const returnCode = rcMatch ? parseInt(rcMatch[1], 10) : null;

        // Extract date if present (various formats)
        const dateMatch = trimmedLine.match(/\b(\d{4}[-/.]\d{2}[-/.]\d{2})\b/) ||
            trimmedLine.match(/\b(\d{2}[-/.]\d{2}[-/.]\d{4})\b/) ||
            trimmedLine.match(/\b(\d{2}\.\d{2}\.\d{4})\b/);
        const date = dateMatch ? dateMatch[1] : '';

        // Check if this is a transport of copies
        const isCopy = COPY_INDICATORS.some(pattern => pattern.test(trimmedLine));

        // Look for referenced transports in the description (other transport numbers on the same line)
        const referencedTransports = matches.slice(1).map(m => m[1]);

        // Extract the remaining text as description
        // Remove the transport number and common fields to get the description
        let description = trimmedLine;

        transports.push({
            number: transportNumber,
            returnCode: returnCode,
            date: date,
            isCopy: isCopy,
            referencedTransports: referencedTransports,
            description: description,
            rawLine: trimmedLine
        });
    }

    return transports;
}

/**
 * Extract the SID (System ID) prefix from a transport number.
 * E.g., DEVK900001 -> DEV
 */
function getSID(transportNumber) {
    return transportNumber.substring(0, 3);
}

/**
 * Get the numeric portion of a transport number.
 * E.g., DEVK900001 -> 900001
 */
function getTransportSequence(transportNumber) {
    return transportNumber.substring(4);
}

// ============================================================
// COMPARISON LOGIC
// ============================================================

/**
 * Main comparison function.
 *
 * Logic:
 * 1. Parse both Production and Test transport lists
 * 2. Find transports in Test that are NOT in Production (test-only)
 * 3. Among test-only transports, identify "transport of copies"
 * 4. For each transport of copies, check if its main/referenced transport IS in Production
 *    - If YES: remove it (the main transport covers it)
 *    - If NO: keep it (needs re-importing)
 * 5. Return the filtered list of transports to re-import
 */
function compareTransports() {
    const prodText = document.getElementById('prodInput').value;
    const testText = document.getElementById('testInput').value;
    const includeRC4 = document.getElementById('includeRC4').checked;
    const includeRC8 = document.getElementById('includeRC8').checked;

    if (!prodText.trim() && !testText.trim()) {
        alert('Please provide transport history data for at least one system.');
        return;
    }

    if (!testText.trim()) {
        alert('Please provide the Test system transport history.');
        return;
    }

    // Parse both lists
    const prodTransports = parseTransportList(prodText);
    const testTransports = parseTransportList(testText);

    if (testTransports.length === 0) {
        alert('No valid transport numbers found in the Test system input. Please check the format.\n\nExpected transport number format: XXXK999999 (e.g., DEVK900001)');
        return;
    }

    // Build a set of production transport numbers for fast lookup
    const prodTransportNumbers = new Set(prodTransports.map(t => t.number));

    // Also build a set of production transport sequences (numeric part)
    // to match across different SIDs (in case Dev→Test and Dev→Prod use different SIDs)
    const prodTransportSequences = new Set(prodTransports.map(t => getTransportSequence(t.number)));

    // Step 1: Find test-only transports
    const testOnlyTransports = testTransports.filter(t => {
        // Check both exact match and sequence match
        const inProd = prodTransportNumbers.has(t.number) ||
            prodTransportSequences.has(getTransportSequence(t.number));
        return !inProd;
    });

    // Step 2: Find common transports
    const commonTransports = testTransports.filter(t => {
        const inProd = prodTransportNumbers.has(t.number) ||
            prodTransportSequences.has(getTransportSequence(t.number));
        return inProd;
    });

    // Step 3: Among test-only, identify copies whose main transport is in Production
    const copiesWithMainInProd = [];
    const transportsToReimport = [];

    for (const transport of testOnlyTransports) {
        // Filter by return code if configured
        if (transport.returnCode !== null) {
            if (transport.returnCode >= 8 && !includeRC8) continue;
            if (transport.returnCode === 4 && !includeRC4) continue;
        }

        let removedAsCopy = false;

        if (transport.isCopy && transport.referencedTransports.length > 0) {
            // Check if ANY referenced (main) transport is in Production
            const mainInProd = transport.referencedTransports.some(ref => {
                return prodTransportNumbers.has(ref) ||
                    prodTransportSequences.has(getTransportSequence(ref));
            });

            if (mainInProd) {
                copiesWithMainInProd.push(transport);
                removedAsCopy = true;
            }
        }

        if (!removedAsCopy) {
            transportsToReimport.push(transport);
        }
    }

    // Display results
    displayResults({
        prodCount: prodTransports.length,
        testCount: testTransports.length,
        testOnlyTransports: testOnlyTransports,
        commonTransports: commonTransports,
        copiesWithMainInProd: copiesWithMainInProd,
        transportsToReimport: transportsToReimport
    });
}

// ============================================================
// DISPLAY RESULTS
// ============================================================

function displayResults(data) {
    const resultsDiv = document.getElementById('results');
    resultsDiv.style.display = 'block';

    // Summary
    const summaryDiv = document.getElementById('summary');
    summaryDiv.innerHTML = `
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-number">${data.prodCount}</div>
                <div class="summary-label">Production Transports</div>
            </div>
            <div class="summary-card">
                <div class="summary-number">${data.testCount}</div>
                <div class="summary-label">Test Transports</div>
            </div>
            <div class="summary-card">
                <div class="summary-number">${data.commonTransports.length}</div>
                <div class="summary-label">Common (Both Systems)</div>
            </div>
            <div class="summary-card">
                <div class="summary-number">${data.testOnlyTransports.length}</div>
                <div class="summary-label">Test-Only (Total)</div>
            </div>
            <div class="summary-card">
                <div class="summary-number">${data.copiesWithMainInProd.length}</div>
                <div class="summary-label">Copies Removed (Main in Prod)</div>
            </div>
            <div class="summary-card highlight">
                <div class="summary-number">${data.transportsToReimport.length}</div>
                <div class="summary-label">To Re-Import After Refresh</div>
            </div>
        </div>
    `;

    // Store data globally for export
    window._resultData = data;

    // Render tables
    renderTable('reimport-table', data.transportsToReimport);
    renderTable('copies-removed-table', data.copiesWithMainInProd);
    renderTable('test-only-table', data.testOnlyTransports);
    renderTable('common-table', data.commonTransports);

    // Update counts
    document.getElementById('reimport-count').textContent = `${data.transportsToReimport.length} transports`;
    document.getElementById('copies-removed-count').textContent = `${data.copiesWithMainInProd.length} transports`;
    document.getElementById('test-only-count').textContent = `${data.testOnlyTransports.length} transports`;
    document.getElementById('common-count').textContent = `${data.commonTransports.length} transports`;

    // Show the reimport tab by default
    showTab('reimport');

    // Scroll to results
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

function renderTable(containerId, transports) {
    const container = document.getElementById(containerId);

    if (transports.length === 0) {
        container.innerHTML = '<p class="no-data">No transports in this category.</p>';
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Transport Number</th>
                    <th>Date</th>
                    <th>RC</th>
                    <th>Type</th>
                    <th>Referenced Transports</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
    `;

    transports.forEach((t, index) => {
        const rcClass = t.returnCode === 0 ? 'rc-ok' :
            t.returnCode === 4 ? 'rc-warn' :
                t.returnCode >= 8 ? 'rc-error' : '';
        const rcDisplay = t.returnCode !== null ? t.returnCode : '-';
        const typeDisplay = t.isCopy ? 'Copy' : 'Workbench/Customizing';
        const refsDisplay = t.referencedTransports.length > 0 ?
            t.referencedTransports.join(', ') : '-';

        html += `
            <tr>
                <td>${index + 1}</td>
                <td class="transport-num">${escapeHtml(t.number)}</td>
                <td>${escapeHtml(t.date)}</td>
                <td class="${rcClass}">${rcDisplay}</td>
                <td>${typeDisplay}</td>
                <td>${escapeHtml(refsDisplay)}</td>
                <td class="description-cell" title="${escapeHtml(t.description)}">${escapeHtml(truncate(t.description, 80))}</td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

// ============================================================
// TAB NAVIGATION
// ============================================================

function showTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('active');
    });

    // Show selected tab
    document.getElementById('tab-' + tabName).classList.add('active');

    // Find and activate the corresponding button
    const buttons = document.querySelectorAll('.tab-btn');
    const tabMap = { 'reimport': 0, 'copies-removed': 1, 'test-only': 2, 'common': 3 };
    if (tabMap[tabName] !== undefined) {
        buttons[tabMap[tabName]].classList.add('active');
    }
}

// ============================================================
// EXPORT FUNCTIONS
// ============================================================

function getTransportsByTab(tabName) {
    if (!window._resultData) return [];
    switch (tabName) {
        case 'reimport': return window._resultData.transportsToReimport;
        case 'copies-removed': return window._resultData.copiesWithMainInProd;
        case 'test-only': return window._resultData.testOnlyTransports;
        case 'common': return window._resultData.commonTransports;
        default: return [];
    }
}

function exportTable(tabName) {
    const transports = getTransportsByTab(tabName);
    if (transports.length === 0) {
        alert('No data to export.');
        return;
    }

    let csv = 'Transport Number,Date,Return Code,Type,Referenced Transports,Description\n';
    transports.forEach(t => {
        const type = t.isCopy ? 'Copy' : 'Workbench/Customizing';
        const refs = t.referencedTransports.join('; ');
        // Escape CSV fields
        const desc = '"' + t.description.replace(/"/g, '""') + '"';
        csv += `${t.number},${t.date},${t.returnCode !== null ? t.returnCode : ''},${type},"${refs}",${desc}\n`;
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `sap-transports-${tabName}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
}

function copyTable(tabName) {
    const transports = getTransportsByTab(tabName);
    if (transports.length === 0) {
        alert('No data to copy.');
        return;
    }

    let text = 'Transport Number\tDate\tReturn Code\tType\tReferenced Transports\tDescription\n';
    transports.forEach(t => {
        const type = t.isCopy ? 'Copy' : 'Workbench/Customizing';
        const refs = t.referencedTransports.join('; ');
        text += `${t.number}\t${t.date}\t${t.returnCode !== null ? t.returnCode : ''}\t${type}\t${refs}\t${t.description}\n`;
    });

    navigator.clipboard.writeText(text).then(() => {
        alert('Copied to clipboard!');
    }).catch(() => {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        alert('Copied to clipboard!');
    });
}

// ============================================================
// UTILITY FUNCTIONS
// ============================================================

function clearAll() {
    document.getElementById('prodInput').value = '';
    document.getElementById('testInput').value = '';
    document.getElementById('prodFile').value = '';
    document.getElementById('testFile').value = '';
    document.getElementById('results').style.display = 'none';
    window._resultData = null;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function truncate(text, maxLen) {
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen) + '...';
}
