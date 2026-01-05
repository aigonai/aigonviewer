// Auto-refresh functionality
let refreshInterval = null;
let serverCheckInterval = null;
let serverDown = false;

// Check if server is alive
async function checkServerAlive() {
    try {
        const response = await fetch('/api/files', {
            method: 'GET',
            cache: 'no-cache'
        });

        if (serverDown && response.ok) {
            // Server came back up
            serverDown = false;
            hideServerDownMessage();
        }

        return response.ok;
    } catch (error) {
        if (!serverDown) {
            // Server just went down
            serverDown = true;
            showServerDownMessage();
        }
        return false;
    }
}

// Show server down message
function showServerDownMessage() {
    // Remove any existing message
    hideServerDownMessage();

    const message = document.createElement('div');
    message.id = 'server-down-message';
    message.innerHTML = `
        <div style="
            position: fixed;
            top: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: #e74c3c;
            color: white;
            padding: 15px 30px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            z-index: 10000;
            font-size: 16px;
            font-weight: 500;
            text-align: center;
        ">
            ⚠️ Server disconnected
            <div style="font-size: 14px; margin-top: 8px; opacity: 0.9;">
                The viewer has been stopped. This page will no longer update.
            </div>
        </div>
    `;
    document.body.appendChild(message);
}

// Hide server down message
function hideServerDownMessage() {
    const existing = document.getElementById('server-down-message');
    if (existing) {
        existing.remove();
    }
}

// Setup auto-refresh
window.setupAutoRefresh = function(refreshFunction) {
    // Clear any existing interval
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }

    if (serverCheckInterval) {
        clearInterval(serverCheckInterval);
    }

    // Set up the auto-refresh interval (always on)
    if (window.REFRESH_INTERVAL) {
        refreshInterval = setInterval(refreshFunction, window.REFRESH_INTERVAL);
    }

    // Set up server health check (every 5 seconds)
    serverCheckInterval = setInterval(checkServerAlive, 5000);

    // Initial check
    checkServerAlive();

    // Manual refresh button handler
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshFunction();

            // Visual feedback
            refreshBtn.style.transform = 'rotate(360deg)';
            setTimeout(() => {
                refreshBtn.style.transform = '';
            }, 500);
        });
    }
};

// Add transition for refresh button rotation
const style = document.createElement('style');
style.textContent = `
    #refresh-btn {
        transition: transform 0.5s ease;
    }
`;
document.head.appendChild(style);

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Check if we have a refresh function defined
    if (window.refreshIndex) {
        window.setupAutoRefresh(window.refreshIndex);
    } else if (window.refreshViewer) {
        window.setupAutoRefresh(window.refreshViewer);
    }

    // Style note references like [abc1] anywhere in the content
    function styleNoteReferences() {
        // First handle code blocks
        const codeElements = document.querySelectorAll('.markdown-content code');
        codeElements.forEach(code => {
            const text = code.textContent.trim();
            if (text.match(/^\[[a-z0-9]{2,6}\]$/i)) {
                code.style.fontSize = '0.75em';
                code.style.color = '#95a5a6';
                code.style.background = '#f9f9f9';
                code.style.padding = '0.1rem 0.3rem';
                code.classList.add('note-ref');
            }
        });

        // Also handle text nodes - find [xxxx] patterns and wrap them
        const walker = document.createTreeWalker(
            document.querySelector('.markdown-content'),
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        const textNodes = [];
        let node;
        while (node = walker.nextNode()) {
            if (node.parentNode.tagName !== 'CODE' && node.parentNode.tagName !== 'PRE') {
                textNodes.push(node);
            }
        }

        textNodes.forEach(textNode => {
            const text = textNode.textContent;
            // Match both single IDs [abc1] and comma-separated IDs [abc1,def2,ghi3]
            const pattern = /\[([a-z0-9]{2,6}(?:,[a-z0-9]{2,6})*)\]/gi;
            if (pattern.test(text)) {
                const newHTML = text.replace(/\[([a-z0-9]{2,6}(?:,[a-z0-9]{2,6})*)\]/gi,
                    '<span class="inline-note-ref">[$1]</span>');
                const wrapper = document.createElement('span');
                wrapper.innerHTML = newHTML;
                textNode.parentNode.replaceChild(wrapper, textNode);
            }
        });
    }

    // Copy button functionality
    function addCopyButtons() {
        // Find all code blocks with highlighting
        const codeBlocks = document.querySelectorAll('.markdown-content .highlight');

        codeBlocks.forEach(codeBlock => {
            // Skip if already has copy button
            if (codeBlock.querySelector('.copy-button')) {
                return;
            }

            // Wrap in container if not already wrapped
            if (!codeBlock.parentElement.classList.contains('code-block-container')) {
                const container = document.createElement('div');
                container.className = 'code-block-container';
                codeBlock.parentNode.insertBefore(container, codeBlock);
                container.appendChild(codeBlock);
            }

            // Create copy button
            const copyButton = document.createElement('button');
            copyButton.className = 'copy-button';
            copyButton.textContent = 'Copy';
            copyButton.setAttribute('aria-label', 'Copy code to clipboard');

            // Add click handler
            copyButton.addEventListener('click', async () => {
                try {
                    // Get the code text (from pre > code inside the highlight div)
                    const codeElement = codeBlock.querySelector('pre code') || codeBlock.querySelector('pre');
                    const codeText = codeElement.textContent || codeElement.innerText;

                    // Use modern clipboard API if available
                    if (navigator.clipboard && window.isSecureContext) {
                        await navigator.clipboard.writeText(codeText);
                    } else {
                        // Fallback for older browsers or non-HTTPS
                        const textArea = document.createElement('textarea');
                        textArea.value = codeText;
                        textArea.style.position = 'fixed';
                        textArea.style.left = '-999999px';
                        textArea.style.top = '-999999px';
                        document.body.appendChild(textArea);
                        textArea.focus();
                        textArea.select();
                        document.execCommand('copy');
                        textArea.remove();
                    }

                    // Visual feedback
                    copyButton.textContent = 'Copied!';
                    copyButton.classList.add('copied');

                    // Reset after 2 seconds
                    setTimeout(() => {
                        copyButton.textContent = 'Copy';
                        copyButton.classList.remove('copied');
                    }, 2000);

                } catch (err) {
                    console.error('Failed to copy code: ', err);

                    // Error feedback
                    copyButton.textContent = 'Error';
                    setTimeout(() => {
                        copyButton.textContent = 'Copy';
                    }, 2000);
                }
            });

            // Add button to the code block container
            const container = codeBlock.parentElement;
            container.appendChild(copyButton);
        });

        // Also handle plain pre blocks without .highlight class
        const plainCodeBlocks = document.querySelectorAll('.markdown-content pre:not(.highlight pre)');

        plainCodeBlocks.forEach(codeBlock => {
            // Skip if already has copy button or is inside a .highlight
            if (codeBlock.querySelector('.copy-button') || codeBlock.closest('.highlight')) {
                return;
            }

            // Wrap in container if not already wrapped
            if (!codeBlock.parentElement.classList.contains('code-block-container')) {
                const container = document.createElement('div');
                container.className = 'code-block-container';
                codeBlock.parentNode.insertBefore(container, codeBlock);
                container.appendChild(codeBlock);
            }

            // Create copy button
            const copyButton = document.createElement('button');
            copyButton.className = 'copy-button';
            copyButton.textContent = 'Copy';
            copyButton.setAttribute('aria-label', 'Copy code to clipboard');

            // Add click handler (same as above)
            copyButton.addEventListener('click', async () => {
                try {
                    const codeText = codeBlock.textContent || codeBlock.innerText;

                    if (navigator.clipboard && window.isSecureContext) {
                        await navigator.clipboard.writeText(codeText);
                    } else {
                        const textArea = document.createElement('textarea');
                        textArea.value = codeText;
                        textArea.style.position = 'fixed';
                        textArea.style.left = '-999999px';
                        textArea.style.top = '-999999px';
                        document.body.appendChild(textArea);
                        textArea.focus();
                        textArea.select();
                        document.execCommand('copy');
                        textArea.remove();
                    }

                    copyButton.textContent = 'Copied!';
                    copyButton.classList.add('copied');

                    setTimeout(() => {
                        copyButton.textContent = 'Copy';
                        copyButton.classList.remove('copied');
                    }, 2000);

                } catch (err) {
                    console.error('Failed to copy code: ', err);
                    copyButton.textContent = 'Error';
                    setTimeout(() => {
                        copyButton.textContent = 'Copy';
                    }, 2000);
                }
            });

            // Add button to the code block container
            const container = codeBlock.parentElement;
            container.appendChild(copyButton);
        });
    }

    // Run initial styling and copy button setup
    styleNoteReferences();
    addCopyButtons();

    // Make functions globally available
    window.styleNoteReferences = styleNoteReferences;
    window.addCopyButtons = addCopyButtons;
});